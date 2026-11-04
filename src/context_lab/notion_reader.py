"""Read complete Markdown for an operator-selected set of Notion pages."""
from __future__ import annotations

import http.client
import json
import os
from uuid import UUID


class NotionPages:
    def __init__(self, page_ids: list[str]):
        self.page_ids = sorted({str(UUID(page_id)) for page_id in page_ids})
        self.token = os.environ.get("NOTION_TOKEN")
        if not self.page_ids or not self.token:
            raise ValueError("Notion handoff requires page IDs and NOTION_TOKEN")
        if not self.token.isascii() or not self.token.isprintable() or any(c.isspace() for c in self.token):
            raise ValueError("NOTION_TOKEN must be a single printable credential")

    def __call__(self, page_id: str) -> dict[str, str]:
        if str(UUID(page_id)) != page_id:
            raise ValueError("use the canonical hyphenated Notion page UUID")
        if page_id not in self.page_ids:
            return {}
        connection = http.client.HTTPSConnection("api.notion.com", timeout=20)
        try:
            connection.request("GET", f"/v1/pages/{page_id}/markdown?markdown_version=v2",
                               headers={"Authorization": f"Bearer {self.token}", "Notion-Version": "2026-03-11"})
            response = connection.getresponse()
            try:
                value = json.loads(response.read())
            except (ValueError, UnicodeError):
                raise ValueError("Notion returned an invalid response; retry the read") from None
            if not isinstance(value, dict):
                raise ValueError("Notion returned an invalid response; retry the read")
            if response.status == 404 and value.get("code") == "object_not_found":
                return {}  # Deleted or inaccessible to this connection.
            if response.status != 200:
                raise ValueError(f"Notion read failed (HTTP {response.status}); no changes delivered")
            body = value.get("markdown")
            if (value.get("object") != "page_markdown" or value.get("id") != page_id
                    or not isinstance(body, str) or value.get("truncated") is not False
                    or value.get("unknown_block_ids") != [] or value.get("warnings") or "<unknown " in body):
                raise ValueError("Notion page is incomplete or unsupported; no changes delivered")
            return {"body/" + page_id: body}
        finally:
            connection.close()
