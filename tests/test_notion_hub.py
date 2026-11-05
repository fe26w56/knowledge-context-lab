import hashlib
import unittest
from unittest.mock import patch

from context_lab.notion_hub import NotionHub, WriteUncertain


ROOT = "00000000-0000-4000-8000-000000000001"
CHILD = "00000000-0000-4000-8000-000000000002"
OUTSIDE = "00000000-0000-4000-8000-000000000003"
ROOT2 = "00000000-0000-4000-8000-000000000007"
DATA_SOURCE = "00000000-0000-4000-8000-000000000006"
DATABASE = "00000000-0000-4000-8000-000000000004"
ROW = "00000000-0000-4000-8000-000000000005"
CREATED = "00000000-0000-4000-8000-000000000008"


def page(page_id, parent, title="Page"):
    return {"object": "page", "id": page_id,
            "parent": {"page_id": parent} if parent else {"type": "workspace", "workspace": True},
            "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}}}


class NotionHubTests(unittest.TestCase):
    def setUp(self):
        self.hub = NotionHub("secret_x", [ROOT])
        self.pages = {ROOT: page(ROOT, None, "Root"), CHILD: page(CHILD, ROOT, "Child"), OUTSIDE: page(OUTSIDE, None, "Outside")}
        self.md = {ROOT: "root", CHILD: "before", OUTSIDE: "private"}

    def request(self, method, path, payload=None):
        if method == "GET" and path.startswith("/v1/pages/") and "/markdown" not in path:
            p = path.split("/")[3]
            return (200, self.pages[p]) if p in self.pages else (404, {"code": "object_not_found"})
        if method == "GET" and "/markdown" in path:
            p = path.split("/")[3]
            return (200, {"object": "page_markdown", "id": p, "markdown": self.md[p], "truncated": False, "unknown_block_ids": []})
        if method == "GET" and path.startswith("/v1/blocks/"):
            p = path.split("/")[3]
            return (200, {"object": "list", "results": ([{"type": "child_page", "id": CHILD}] if p == ROOT else []), "has_more": False, "next_cursor": None})
        if method == "PATCH":
            update = payload["update_content"]["content_updates"][0]
            self.md[CHILD] = self.md[CHILD].replace(update["old_str"], update["new_str"])
            return 200, {"object": "page", "id": CHILD}
        raise AssertionError((method, path, payload))

    def test_current_requires_true_ancestry(self):
        with patch.object(self.hub, "_request", side_effect=self.request):
            self.assertEqual(self.hub.current(CHILD), {"body/" + CHILD: "before"})
            self.assertEqual(self.hub.current(OUTSIDE), {})

    def test_discover_recurses_only_child_pages(self):
        with patch.object(self.hub, "_request", side_effect=self.request):
            self.assertEqual(self.hub.discover(), [{"page_id": ROOT, "title": "Root"}, {"page_id": CHILD, "title": "Child"}])

    def test_replace_checks_digest_and_unique_text(self):
        with patch.object(self.hub, "_request", side_effect=self.request):
            digest = hashlib.sha256(b"before").hexdigest()
            result = self.hub.replace_text(CHILD, digest, "before", "after")
            self.assertEqual(result["sha256"], hashlib.sha256(b"after").hexdigest())
            with self.assertRaises(ValueError):
                self.hub.replace_text(CHILD, digest, "after", "new")

    def test_incomplete_markdown_fails_closed(self):
        def incomplete(method, path, payload=None):
            if method == "GET" and "/markdown" in path:
                return 200, {"object": "page_markdown", "id": CHILD, "markdown": "x", "truncated": True, "unknown_block_ids": []}
            return self.request(method, path, payload)
        with patch.object(self.hub, "_request", side_effect=incomplete):
            with self.assertRaises(ValueError):
                self.hub.current(CHILD)

    def test_mutation_does_not_retry(self):
        calls = []
        def fail(method, path, payload=None):
            calls.append(method)
            return 503, {}
        with patch.object(self.hub, "_request", side_effect=fail):
            with self.assertRaises(ValueError):
                self.hub.replace_text(OUTSIDE, "x", "a", "b")
        self.assertEqual(calls, ["GET"])  # no mutation was attempted or replayed

    def test_database_query_is_supported_by_discovery(self):
        database = DATABASE
        row = ROW
        self.pages[row] = page(row, ROOT, "Row")
        original = self.request
        def request(method, path, payload=None):
            if method == "GET" and path == f"/v1/databases/{database}":
                return 200, {"object": "database", "id": database, "data_sources": [{"id": "00000000-0000-4000-8000-000000000006"}]}
            if method == "POST" and path.startswith("/v1/data_sources/"):
                return 200, {"object": "list", "results": [self.pages[row]], "has_more": False, "next_cursor": None}
            if method == "GET" and path.startswith("/v1/blocks/") and path.split("/")[3] == ROOT:
                return 200, {"object": "list", "results": [{"type": "child_database", "id": database}], "has_more": False, "next_cursor": None}
            return original(method, path, payload)
        with patch.object(self.hub, "_request", side_effect=request):
            self.assertEqual([p["page_id"] for p in self.hub.discover()], [ROOT, row])

    def test_data_source_parent_is_authorized_for_current(self):
        self.pages[ROW] = page(ROW, DATA_SOURCE, "Row")
        self.pages[ROW]["parent"] = {"type": "data_source_id", "data_source_id": DATA_SOURCE, "database_id": DATABASE}
        self.md[ROW] = "before"
        def request(method, path, payload=None):
            if method == "GET" and path == f"/v1/data_sources/{DATA_SOURCE}":
                return 200, {"object": "data_source", "id": DATA_SOURCE, "parent": {"type": "database_id", "database_id": DATABASE}}
            if method == "GET" and path == f"/v1/databases/{DATABASE}":
                return 200, {"object": "database", "id": DATABASE, "parent": {"type": "page_id", "page_id": ROOT}}
            if method == "GET" and path == f"/v1/pages/{ROW}":
                return 200, self.pages[ROW]
            return self.request(method, path, payload)
        with patch.object(self.hub, "_request", side_effect=request):
            self.assertEqual(self.hub.current(ROW), {"body/" + ROW: "before"})

    def test_multiple_roots_do_not_make_valid_root_fail_when_other_revoked(self):
        hub = NotionHub("secret_x", [ROOT, ROOT2])
        hub.pages = self.pages
        def request(method, path, payload=None):
            if method == "GET" and path == f"/v1/pages/{ROOT2}":
                return 404, {"code": "object_not_found"}
            return self.request(method, path, payload)
        with patch.object(hub, "_request", side_effect=request):
            self.assertEqual(hub.current(CHILD), {"body/" + CHILD: "before"})

    def test_empty_page_body_is_a_valid_delivery(self):
        self.md[CHILD] = ""
        with patch.object(self.hub, "_request", side_effect=self.request):
            self.assertEqual(self.hub.current(CHILD), {"body/" + CHILD: ""})

    def test_verify_created_page_accepts_observed_canonical_form_and_hashes_readback(self):
        title = "A title"
        body = "# A title\n\nKCL_ACCEPTANCE_MARKER_2026_11_05\n\nStable line retained across the partial update.\n"
        self.pages[CREATED] = page(CREATED, ROOT, title)
        self.md[CREATED] = "KCL\\_ACCEPTANCE\\_MARKER\\_2026\\_11\\_05\n\nStable line retained across the partial update."
        with patch.object(self.hub, "_request", side_effect=self.request):
            result = self.hub.verify_created_page(CREATED, ROOT, title, body)
        self.assertEqual(result["page_id"], CREATED)
        self.assertEqual(result["sha256"], hashlib.sha256(self.md[CREATED].encode()).hexdigest())

    def test_verify_created_page_keeps_data_loss_uncertain(self):
        title, body = "A title", "# A title\n\nmarker\n\nmeaningful line\n"
        self.pages[CREATED] = page(CREATED, ROOT, title)
        self.md[CREATED] = "marker"
        with patch.object(self.hub, "_request", side_effect=self.request):
            with self.assertRaises(WriteUncertain) as caught:
                self.hub.verify_created_page(CREATED, ROOT, title, body)
        self.assertEqual(caught.exception.page_id, CREATED)

    def test_verify_created_page_does_not_canonicalize_code_or_other_heading(self):
        title = "Page title"
        body = "# Different heading\n\n```text\nkeep_a_b\n```\n\nkeep_a_b\n"
        self.pages[CREATED] = page(CREATED, ROOT, title)
        self.md[CREATED] = "# Different heading\n\n```text\nkeep_a\\_b\n```\n\nkeep_a_b"
        with patch.object(self.hub, "_request", side_effect=self.request):
            with self.assertRaises(WriteUncertain):
                self.hub.verify_created_page(CREATED, ROOT, title, body)

    def test_verify_created_page_requires_server_title_and_parent(self):
        title, body = "Page title", "body\n"
        self.pages[CREATED] = page(CREATED, OUTSIDE, title)
        self.md[CREATED] = "body"
        with patch.object(self.hub, "_request", side_effect=self.request):
            with self.assertRaises(WriteUncertain):
                self.hub.verify_created_page(CREATED, ROOT, title, body)

    def test_data_source_cursor_is_in_query_body_and_advances(self):
        cursors = []
        def request(method, path, payload=None):
            if method == "GET" and path.startswith("/v1/databases/"):
                return 200, {"object": "database", "id": DATABASE, "data_sources": [{"id": DATA_SOURCE}]}
            if method == "POST" and path == f"/v1/data_sources/{DATA_SOURCE}/query":
                cursors.append(payload.get("start_cursor"))
                if len(cursors) == 1:
                    return 200, {"object": "list", "results": [], "has_more": True, "next_cursor": "cursor-2"}
                return 200, {"object": "list", "results": [], "has_more": False, "next_cursor": None}
            if method == "GET" and path.startswith(f"/v1/blocks/{ROOT}"):
                return 200, {"object": "list", "results": [{"type": "child_database", "id": DATABASE}], "has_more": False, "next_cursor": None}
            return self.request(method, path, payload)
        with patch.object(self.hub, "_request", side_effect=request):
            self.hub.discover()
        self.assertEqual(cursors, [None, "cursor-2"])

    def test_mutating_http_transport_is_called_once_on_503(self):
        class Response:
            status = 503
            def read(self): return b"{}"
            def getheader(self, name): return None
        class Connection:
            calls = 0
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): Connection.calls += 1
            def getresponse(self): return Response()
            def close(self): pass
        with patch("context_lab.notion_hub.http.client.HTTPSConnection", Connection):
            status, _ = self.hub._request("PATCH", "/v1/pages/" + CHILD + "/markdown", {})
        self.assertEqual(status, 503)
        self.assertEqual(Connection.calls, 1)

    def test_nested_block_parent_and_discovery(self):
        block_id = ROOT2
        self.pages[CHILD]["parent"] = {"type": "block_id", "block_id": block_id}
        def request(method, path, payload=None):
            if path == f"/v1/blocks/{block_id}":
                return 200, {"object": "block", "id": block_id, "parent": {"type": "page_id", "page_id": ROOT}}
            if path.startswith(f"/v1/blocks/{ROOT}/children"):
                return 200, {"object": "list", "results": [{"id": block_id, "type": "toggle", "has_children": True}], "has_more": False}
            if path.startswith(f"/v1/blocks/{block_id}/children"):
                return 200, {"object": "list", "results": [{"id": CHILD, "type": "child_page"}], "has_more": False}
            return self.request(method, path, payload)
        with patch.object(self.hub, "_request", side_effect=request):
            self.assertEqual([p["page_id"] for p in self.hub.discover()], [ROOT, CHILD])
            self.assertEqual(self.hub.current(CHILD), {"body/" + CHILD: "before"})

    def test_repeated_cursor_and_transient_access_error_never_purge(self):
        def looping(method, path, payload=None):
            if "/children" in path:
                return 200, {"object": "list", "results": [], "has_more": True, "next_cursor": "repeat"}
            return self.request(method, path, payload)
        with patch.object(self.hub, "_request", side_effect=looping):
            with self.assertRaisesRegex(ValueError, "repeated"):
                self.hub.discover()
        for status in (401, 403, 429, 503):
            with self.subTest(status=status), patch.object(self.hub, "_request", return_value=(status, {"code": "restricted_resource"})):
                with self.assertRaises(ValueError):
                    self.hub.current(CHILD)


if __name__ == "__main__":
    unittest.main()
