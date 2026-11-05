"""Hierarchy-aware Notion gateway used by the shared handoff service.

The gateway deliberately keeps the Notion credential in the process and never
returns it.  Access is constrained by the configured page roots; a page is
accepted only after its parent chain has been checked on the current request.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import time
from uuid import UUID


API_VERSION = "2026-03-11"


class WriteRejected(ValueError):
    """The gateway rejected a request before any mutating HTTP call."""


class WriteUncertain(RuntimeError):
    """A mutation was sent, but its exact effect needs inspection."""
    def __init__(self, page_id: str | None = None):
        super().__init__("Notion write requires inspection; do not repeat automatically")
        self.page_id = page_id


class RateLimiter:
    """Share one request budget across bots using the same Notion connection."""
    def __init__(self, interval: float = 0.4):
        self.interval, self.next_request = interval, 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if self.next_request > now:
                time.sleep(self.next_request - now)
            self.next_request = time.monotonic() + self.interval


def _uuid(value: str) -> str:
    try:
        result = str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Notion IDs must be canonical UUIDs") from exc
    if result != value:
        raise ValueError("Notion IDs must use canonical hyphenated form")
    return result


def _create_readback_candidates(markdown: str, title: str) -> set[str]:
    """Allow a title moved to page metadata and measured plain-text rendering."""
    forms = {markdown}
    heading = f"# {title}\n\n"
    if "\n" not in title and markdown.startswith(heading):
        forms.add(markdown[len(heading):])
    # Do not guess how Notion escapes Markdown syntax, links, or code. Only
    # model the observed transformation of simple, single-line paragraphs.
    paragraph = r"[A-Za-z0-9][A-Za-z0-9_ ,.!?'()-]*"
    for source in tuple(forms):
        if re.fullmatch(rf"{paragraph}(?:\n\n{paragraph})*\n?", source):
            plain = source.removesuffix("\n")
            escaped = re.sub(r"(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])", r"\\_", plain)
            forms.update((plain, escaped, escaped + "\n" if source.endswith("\n") else escaped))
    return forms


class NotionHub:
    """Read and narrowly update pages below one or more Notion page roots."""

    def __init__(self, token: str, roots: list[str], *, timeout: float = 20,
                 max_pages: int = 1000, max_depth: int = 32, limiter=None):
        if not isinstance(token, str) or not token or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
            raise ValueError("token must be one printable credential")
        if not roots:
            raise ValueError("at least one root page is required")
        self._token = token
        self.roots = tuple(sorted({_uuid(root) for root in roots}))
        self.timeout, self.max_pages, self.max_depth = timeout, max_pages, max_depth
        self.limiter = limiter or RateLimiter()

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        headers = {"Authorization": f"Bearer {self._token}", "Notion-Version": API_VERSION,
                   "Content-Type": "application/json"}
        # Only idempotent reads are retried.  A failed POST/PATCH must never be
        # replayed because Notion may have committed it before the connection
        # failed.  Data-source query is a read-only POST and is explicitly safe.
        retryable = method == "GET" or (method == "POST" and "/query" in path)
        attempts = 3 if retryable else 1
        for attempt in range(attempts):
            self.limiter.wait()
            conn = http.client.HTTPSConnection("api.notion.com", timeout=self.timeout)
            try:
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                raw = response.read()
                try:
                    value = json.loads(raw)
                except (ValueError, UnicodeError):
                    value = {}
                if response.status == 429 or response.status >= 500:
                    if attempt + 1 < attempts:
                        retry_after = response.getheader("Retry-After")
                        try:
                            delay = max(0.05, float(retry_after)) if retry_after else 0.2 * (attempt + 1)
                        except ValueError:
                            delay = 0.2
                        if delay > 30:
                            return response.status, value if isinstance(value, dict) else {}
                        time.sleep(delay)
                        continue
                return response.status, value if isinstance(value, dict) else {}
            finally:
                conn.close()
        raise RuntimeError("Notion read retry limit exhausted")

    def _entity(self, kind: str, identifier: str) -> dict | None:
        endpoint = {"page": "pages", "block": "blocks", "database": "databases", "data_source": "data_sources"}[kind]
        identifier = _uuid(identifier)
        status, value = self._request("GET", f"/v1/{endpoint}/{identifier}")
        if status == 404 and value.get("code") == "object_not_found":
            return None
        if (status != 200 or value.get("object") != kind
                or value.get("id") != identifier):
            raise ValueError(f"Notion {kind} metadata unavailable or invalid (HTTP {status})")
        if value.get("archived") or value.get("in_trash"):
            return None
        return value

    def _page(self, page_id: str) -> dict | None:
        return self._entity("page", page_id)

    def _allowed(self, page_id: str) -> bool:
        kind, current = "page", _uuid(page_id)
        seen = set()
        for _ in range(self.max_depth):
            key = (kind, current)
            if key in seen:
                raise ValueError("Notion parent cycle detected")
            seen.add(key)
            entity = self._entity(kind, current)
            if entity is None:
                return False
            if kind == "page" and current in self.roots:
                return True
            parent = entity.get("parent")
            if not isinstance(parent, dict):
                raise ValueError("Notion parent metadata missing")
            parent_type = parent.get("type")
            # Fixtures and older endpoint responses may omit the discriminator.
            if parent_type is None:
                keys = [k for k in ("page_id", "block_id", "database_id", "data_source_id") if k in parent]
                parent_type = keys[0] if len(keys) == 1 else None
            if parent_type in {"workspace", "teamspace_id"}:
                return False
            if parent_type not in {"page_id", "block_id", "database_id", "data_source_id"}:
                raise ValueError("Notion parent type unsupported")
            kind, current = parent_type.removesuffix("_id"), _uuid(parent.get(parent_type))
        raise ValueError("Notion parent chain exceeds configured depth")

    @staticmethod
    def _title(page: dict) -> str:
        props = page.get("properties") or {}
        for prop in props.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                return "".join(x.get("plain_text", "") for x in prop.get("title", []) if isinstance(x, dict))
        return ""

    def _markdown(self, page_id: str) -> str | None:
        status, value = self._request("GET", f"/v1/pages/{page_id}/markdown?markdown_version=v2")
        if status == 404 and value.get("code") == "object_not_found":
            return None
        body = value.get("markdown")
        if status != 200 or value.get("object") != "page_markdown" or value.get("id") != page_id or not isinstance(body, str) or value.get("truncated") is not False or value.get("unknown_block_ids") != [] or value.get("warnings") or "<unknown " in body:
            raise ValueError("Notion page is incomplete or unsupported")
        return body

    def current(self, page_id: str) -> dict[str, str]:
        page_id = _uuid(page_id)
        if not self._allowed(page_id):
            return {}
        body = self._markdown(page_id)
        return {"body/" + page_id: body} if body is not None else {}

    def _list(self, path: str, *, query: bool = False):
        cursor, seen = None, set()
        for _ in range(self.max_pages + 1):
            if query:
                payload = {"page_size": 100}
                if cursor:
                    payload["start_cursor"] = cursor
                status, value = self._request("POST", path, payload)
            else:
                from urllib.parse import urlencode
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                status, value = self._request("GET", path + "?" + urlencode(params))
            if (status != 200 or value.get("object") != "list"
                    or not isinstance(value.get("results"), list) or type(value.get("has_more")) is not bool):
                raise ValueError("Notion listing incomplete or invalid")
            for entry in value["results"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                    raise ValueError("Notion listing contains an invalid object")
                _uuid(entry["id"])
                yield entry
            if not value["has_more"]:
                return
            cursor = value.get("next_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError("Notion listing cursor missing or repeated")
            seen.add(cursor)
        raise ValueError("Notion listing exceeds configured limit")

    def discover(self) -> list[dict[str, str]]:
        from collections import deque
        found, visited = [], set()
        queue = deque(("page", root, 0) for root in self.roots)
        while queue:
            kind, identifier, depth = queue.popleft()
            if (kind, identifier) in visited:
                continue
            if depth >= self.max_depth or len(visited) >= self.max_pages * 100:
                raise ValueError("Notion hierarchy exceeds configured depth or block limit")
            visited.add((kind, identifier))
            if kind == "page":
                if not self._allowed(identifier):
                    continue
                page = self._page(identifier)
                if page is None:
                    raise ValueError("Notion page disappeared during discovery; retry")
                if len(found) >= self.max_pages:
                    raise ValueError("Notion hierarchy exceeds configured page limit")
                found.append({"page_id": identifier, "title": self._title(page)})
            for block in self._list(f"/v1/blocks/{identifier}/children"):
                block_type = block.get("type")
                if block.get("archived") or block.get("in_trash"):
                    continue
                if block_type == "child_page":
                    queue.append(("page", block["id"], depth + 1))
                elif block_type == "child_database":
                    database = self._entity("database", block["id"])
                    if database is None or not isinstance(database.get("data_sources"), list):
                        raise ValueError("Notion database metadata incomplete")
                    for source in database["data_sources"]:
                        if not isinstance(source, dict):
                            raise ValueError("Notion data source metadata invalid")
                        source_id = _uuid(source.get("id"))
                        for row in self._list(f"/v1/data_sources/{source_id}/query", query=True):
                            if row.get("object") != "page":
                                raise ValueError("Notion query returned an unsupported object")
                            queue.append(("page", row["id"], depth + 1))
                elif block.get("has_children"):
                    # A linked synced block can expose content outside the root.
                    # Descendant discovery follows owned hierarchy only.
                    if block_type == "synced_block" and (block.get("synced_block") or {}).get("synced_from"):
                        continue
                    queue.append(("block", block["id"], depth + 1))
        return found

    def create_page(self, parent_id: str, title: str, markdown: str) -> dict[str, str]:
        parent_id = _uuid(parent_id)
        if not self._allowed(parent_id):
            raise WriteRejected("parent_outside_roots")
        if not isinstance(title, str) or not title.strip() or len(title) > 2000 or not isinstance(markdown, str):
            raise WriteRejected("invalid_title_or_markdown")
        # The markdown create form is a single mutation.  Keeping the body in
        # this request avoids a create-then-insert sequence that could leave a
        # half-created page if the second request fails.
        payload = {"markdown_version": "v2", "parent": {"page_id": parent_id}, "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}}, "markdown": markdown}
        status, value = self._request("POST", "/v1/pages", payload)
        if status not in (200, 201) or value.get("object") != "page" or not isinstance(value.get("id"), str):
            committed = (value.get("additional_data") or {}).get("committed_resource_id")
            raise WriteUncertain(_uuid(committed) if committed else None)
        page_id = _uuid(value["id"])
        return self.verify_created_page(page_id, parent_id, title, markdown)

    def verify_created_page(self, page_id: str, parent_id: str, title: str,
                            markdown: str) -> dict[str, str]:
        """Reconcile an already-created page using read-only metadata/content reads.

        The accepted content differences are limited to the observed Notion
        canonicalization: a title-equal leading H1 may be omitted, one final
        newline may be omitted, and intraword underscores in ordinary text may
        be escaped.  All other content loss remains uncertain.
        """
        page_id, parent_id = _uuid(page_id), _uuid(parent_id)
        if not isinstance(title, str) or not title.strip() or len(title) > 2000 or not isinstance(markdown, str):
            raise ValueError("invalid_title_or_markdown")
        try:
            page = self._page(page_id)
            parent = (page or {}).get("parent") if page else None
            parent_type = parent.get("type") if isinstance(parent, dict) else None
            if parent_type is None and isinstance(parent, dict) and "page_id" in parent:
                parent_type = "page_id"
            if (page is None or self._title(page) != title or parent_type != "page_id"
                    or parent.get("page_id") != parent_id or not self._allowed(page_id)):
                raise WriteUncertain(page_id)
            readback = self._markdown(page_id)
        except WriteUncertain:
            raise
        except Exception:
            raise WriteUncertain(page_id) from None
        if readback is None or readback not in _create_readback_candidates(markdown, title):
            raise WriteUncertain(page_id)
        return {"page_id": page_id, "sha256": hashlib.sha256(readback.encode()).hexdigest()}

    def replace_text(self, page_id: str, expected_sha256: str, old_text: str, new_text: str) -> dict[str, str]:
        page_id = _uuid(page_id)
        if not self._allowed(page_id):
            raise WriteRejected("page_outside_roots")
        current = self._markdown(page_id)
        if current is None:
            raise WriteRejected("page_unavailable")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise WriteRejected("invalid_text")
        digest = hashlib.sha256(current.encode()).hexdigest()
        if digest != expected_sha256:
            raise WriteRejected("version_conflict_refresh_before_editing")
        if current.count(old_text) != 1:
            raise WriteRejected("old_text_must_match_once")
        if not old_text:
            raise WriteRejected("old_text_must_not_be_empty")
        status, value = self._request("PATCH", f"/v1/pages/{page_id}/markdown", {"markdown_version": "v2", "type": "update_content", "update_content": {"content_updates": [{"old_str": old_text, "new_str": new_text}]}, "allow_async": False})
        if status not in (200, 201):
            raise WriteUncertain(page_id)
        try:
            readback = self._markdown(page_id)
        except Exception:
            raise WriteUncertain(page_id) from None
        expected = current.replace(old_text, new_text, 1)
        if readback != expected:
            raise WriteUncertain(page_id)
        return {"page_id": page_id, "sha256": hashlib.sha256(readback.encode()).hexdigest()}
