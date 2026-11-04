import concurrent.futures
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from context_lab.workspace import Workspace, digest, notion_pages
from context_lab.store import AccessDenied, ValidationError, VersionConflict, IdempotencyConflict


def page():
    return {
        "id": "source-a", "title": "Aster release decision",
        "url": "https://example.invalid/source-a", "scope": "shared", "owner": "editor",
        "properties": {"decision_status": "adopted", "unknown_future_property": ["keep", 2]},
        "body": "# Aster\n\n## Current\nOwner approved two reviews before release.\n\n## History\nOne review was sufficient.\n",
        "attachments": [{"url": "https://example.invalid/report.pdf", "downloaded": False}],
    }


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ws = Workspace(self.root / "original.sqlite")
        self.original = page()
        self.ws.import_pages([self.original], actor="editor", request_id="first-import")
        quote = "Owner approved two reviews before release."
        start = self.original["body"].index(quote)
        self.ref = {"source_id": "source-a", "source_version": 1,
                    "start": start, "end": start + len(quote), "quote": quote}
        self.payload = {"title": "Aster", "summary": "Require two reviews.",
                        "conditions": ["before release"], "state": "adopted",
                        "as_of": "2026-11-03", "task_refs": ["external-task:4"],
                        "approval": {**self.ref, "confirmed_by": "owner"}}

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, **kwargs):
        return self.ws.publish_topic("aster", self.payload, [self.ref], actor="editor",
                                     expected_version=kwargs.get("version", 0),
                                     request_id=kwargs.get("request", "publish"))

    def test_import_is_lossless_idempotent_and_does_not_create_decision(self):
        self.assertEqual(self.original, self.ws.get_source("source-a", actor="editor")["page"])
        receipt = self.ws.import_pages([self.original], actor="editor", request_id="first-import")
        self.assertTrue(receipt["committed"][0]["replayed"])
        self.assertEqual([], self.ws.list_topics(actor="editor")["topics"])

    def test_only_exact_current_evidence_and_explicit_approval_can_be_published(self):
        bad = deepcopy(self.ref)
        bad["quote"] = "Owner approved one review."
        with self.assertRaises(ValidationError):
            self.ws.publish_topic("aster", self.payload, [bad], actor="editor",
                                  expected_version=0, request_id="bad-quote")
        del self.payload["approval"]
        with self.assertRaises(ValidationError):
            self.publish()
        self.assertEqual([], self.ws.list_topics(actor="editor")["topics"])

    def test_correction_withholds_stale_current_but_retains_history(self):
        self.publish()
        changed = deepcopy(self.original)
        changed["body"] = changed["body"].replace("two reviews", "three reviews")
        self.ws.import_pages([changed], actor="editor", request_id="correction",
                             expected_versions={"source-a": 1})
        stale = self.ws.get_topic("aster", actor="editor")
        self.assertEqual("needs_review", stale["status"])
        self.assertNotIn("payload", stale)
        historical = self.ws.get_topic("aster", actor="editor", version=1)
        self.assertEqual("Require two reviews.", historical["payload"]["summary"])
        self.assertEqual(self.original, self.ws.get_source("source-a", actor="editor", version=1)["page"])

    def test_lost_ack_publish_retry_survives_a_later_source_correction(self):
        first = self.publish()
        changed = deepcopy(self.original)
        changed["properties"]["extra"] = "new observation"
        self.ws.import_pages([changed], actor="editor", request_id="correction",
                             expected_versions={"source-a": 1})
        replay = self.publish()
        self.assertEqual(first["version"], replay["version"])
        self.assertTrue(replay["replayed"])

    def test_private_sources_do_not_leak_through_search_export_or_public_topic(self):
        private = deepcopy(self.original)
        private.update(id="private-source", scope="private", owner="alice")
        self.ws.import_pages([private], actor="alice", request_id="alice-import")
        self.assertNotIn("private-source", json.dumps(self.ws.search("Aster", actor="bob")))
        self.assertNotIn("private-source", json.dumps(self.ws.export_bundle(actor="bob")))
        ref = {**self.ref, "source_id": "private-source"}
        self.payload["approval"] = {**ref, "confirmed_by": "owner"}
        with self.assertRaises(AccessDenied):
            self.ws.publish_topic("private-topic", self.payload, [ref], actor="alice",
                                  expected_version=0, request_id="share-private")

    def test_export_restore_preserves_full_history_and_request_receipts(self):
        first = self.publish()
        changed = deepcopy(self.original)
        changed["properties"]["extra"] = "new observation"
        self.ws.import_pages([changed], actor="editor", request_id="correction",
                             expected_versions={"source-a": 1})
        bundle = self.ws.export_bundle(actor="editor")
        restored = Workspace.restore_bundle(bundle, self.root / "restored.sqlite")
        self.assertEqual(bundle, restored.export_bundle(actor="editor"))
        self.assertEqual("needs_review", restored.get_topic("aster", actor="editor")["status"])
        self.assertEqual(first["version"], restored.store.request_status("publish", actor="editor")["version"])
        damaged = deepcopy(bundle)
        damaged["tables"]["heads"][0]["current_version"] = 99
        with self.assertRaises(ValidationError):
            Workspace.restore_bundle(damaged, self.root / "damaged.sqlite")
        self.assertFalse((self.root / "damaged.sqlite").exists())

    def test_sixteen_expected_version_writers_do_not_lose_updates(self):
        self.publish()
        def update(i):
            try:
                return self.publish(version=1, request=f"concurrent-{i}")["version"]
            except VersionConflict:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(update, range(16)))
        self.assertEqual(1, results.count(2))
        self.assertEqual(15, results.count("conflict"))

    def test_search_keeps_exact_offsets_and_history_is_available(self):
        result = self.ws.search("Aster current release", actor="editor")
        for source in result["sources"]:
            for section in source["sections"]:
                self.assertEqual(section["text"], self.original["body"][section["start"]:section["end"]])
        self.assertNotIn("One review was sufficient", json.dumps(result))
        history = self.ws.search("Aster previous review", actor="editor")
        self.assertIn("One review was sufficient", json.dumps(history))

    def test_source_update_requires_client_version_and_rejects_reused_request_content(self):
        changed = deepcopy(self.original)
        changed["body"] += "\nCorrection."
        with self.assertRaises(VersionConflict):
            self.ws.import_pages([changed], actor="editor", request_id="update")
        with self.assertRaises(IdempotencyConflict):
            self.ws.import_pages([changed], actor="editor", request_id="first-import")
        self.ws.import_pages([changed], actor="editor", request_id="update",
                             expected_versions={"source-a": 1})
        with self.assertRaises(VersionConflict):
            self.ws.import_pages([self.original], actor="editor", request_id="stale-editor",
                                 expected_versions={"source-a": 1})
        replay = self.ws.import_pages([self.original], actor="editor", request_id="first-import")
        self.assertEqual(1, replay["committed"][0]["version"])
        self.assertEqual(changed, self.ws.get_source("source-a", actor="editor")["page"])

    def test_compact_is_complete_source_text_not_a_summary(self):
        result = self.ws.search("Aster release", actor="editor", mode="compact")
        source = result["sources"][0]
        self.assertEqual(self.original["body"], source["text"])
        self.assertEqual(self.original["properties"], source["properties"])
        self.assertEqual(self.original["attachments"], source["attachments"])
        self.assertEqual(self.original["owner"], source["owner"])
        self.assertEqual(1, source["source_version"])

    def test_notion_capture_preserves_original_and_inventory_without_approving(self):
        body = '## Current\nProposed only.\n<mention url="https://example.invalid/child" />\n<file source="https://example.invalid/report.pdf">Report</file>'
        raw = {'id': 'notion-demo', 'title': 'Topic', 'url': 'https://example.invalid/topic',
               'text': '<page>\n<properties>\n{"status":"adopted"}\n</properties>\n<content>\n' + body + '\n</content>\n</page>'}
        converted = notion_pages([raw], owner="alice")
        self.ws.import_pages(converted, actor="alice", request_id="capture")
        restored = self.ws.get_source("notion-demo", actor="alice")["page"]
        self.assertEqual(raw, restored["raw_capture"])
        self.assertEqual(body, restored["body"])
        self.assertEqual(2, len(restored["linked_resources"]))
        self.assertEqual([], self.ws.list_topics(actor="alice")["topics"])
        self.assertNotIn("notion-demo", json.dumps(self.ws.export_bundle(actor="bob")))

    def test_notion_capture_correction_reprojects_and_rejects_body_only_edit(self):
        body = "## Current\nProposed only.\n"
        raw = {'id': 'notion-correct', 'title': 'Correctable topic', 'url': 'https://example.invalid/correct',
               'page_last_edited_at': '2026-11-03T10:00:00Z',
               'text': '<page>\n<properties>\n{"status":"proposed"}\n</properties>\n<content>\n' + body + '\n</content>\n</page>'}
        converted = notion_pages([raw], owner="alice")
        self.ws.import_pages(converted, actor="alice", request_id="correct-seed")
        quote = "Proposed only."
        start = converted[0]["body"].index(quote)
        self.ws.publish_topic("correct-topic", {
            "title": "Correct topic", "summary": "A proposed record.",
            "conditions": ["review source"], "state": "proposed", "as_of": "2026-11-03",
            "task_refs": ["pilot:correction"]},
            [{"source_id": "notion-correct", "source_version": 1,
              "start": start, "end": start + len(quote), "quote": quote}],
            actor="alice", expected_version=0, request_id="correct-topic-publish",
            scope="private", owner="alice")
        body_only = deepcopy(converted[0])
        body_only["body"] = body_only["body"].replace("Proposed only.", "Corrected only.")
        with self.assertRaisesRegex(ValidationError, "projection mismatch: body"):
            self.ws.import_pages([body_only], actor="alice", request_id="body-only")
        incomplete = deepcopy(converted[0])
        incomplete["raw_capture"]["truncated"] = True
        with self.assertRaisesRegex(ValidationError, "truncated"):
            self.ws.import_pages([incomplete], actor="alice", request_id="capture-truncated")
        corrected_raw = deepcopy(raw)
        corrected_raw["page_last_edited_at"] = "2026-11-03T11:00:00Z"
        corrected_raw["text"] = corrected_raw["text"].replace("Proposed only.", "Corrected only.")
        corrected = notion_pages([corrected_raw], owner="alice")[0]
        receipt = self.ws.import_pages([corrected], actor="alice", request_id="capture-correction",
                                       expected_versions={"notion-correct": 1})
        self.assertEqual(receipt["committed"][0]["version"], 2)
        current = self.ws.get_source("notion-correct", actor="alice")
        self.assertIn("Corrected only.", current["page"]["body"])
        self.assertIn("Corrected only.", current["page"]["raw_capture"]["text"])
        self.assertEqual(self.ws.get_topic("correct-topic", actor="alice")["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
