"""Offline orchestration test for the bounded Notion acceptance command."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from scripts.accept_notion_hub import _MutationReceipt, _mutate, _recover_first_create, main


ROOT = "11111111-1111-4111-8111-111111111111"


class FakeNotionHub:
    """Small shared in-memory gateway; HTTP and BotClient remain real."""

    pages: dict[str, dict] = {}

    def __init__(self, *, token, roots, limiter=None):
        self.roots = roots
        if not self.pages:
            self.pages[ROOT] = {"title": "Synthetic Agent Hub", "body": "root"}

    def current(self, page_id: str) -> dict[str, str]:
        page = self.pages.get(page_id)
        return {"body/" + page_id: page["body"]} if page else {}

    def _allowed(self, page_id: str) -> bool:
        return page_id in self.pages

    def discover(self) -> list[dict[str, str]]:
        found = []
        pending = list(self.roots)
        seen = set()
        while pending:
            page_id = pending.pop(0)
            if page_id in seen or page_id not in self.pages:
                continue
            seen.add(page_id)
            page = self.pages[page_id]
            found.append({"page_id": page_id, "title": page["title"]})
            pending.extend(page.get("children", []))
        return found

    def create_page(self, parent_id: str, title: str, markdown: str) -> dict[str, str]:
        if parent_id not in self.pages:
            raise ValueError("missing parent")
        page_id = str(uuid4())
        self.pages[page_id] = {"title": title, "body": markdown, "children": []}
        self.pages[parent_id].setdefault("children", []).append(page_id)
        self.pages[parent_id]["body"] += f'\n<page url="{page_id}">{title}</page>\n'
        return {"page_id": page_id, "sha256": hashlib.sha256(markdown.encode()).hexdigest()}

    def replace_text(self, page_id: str, expected_sha256: str, old_text: str, new_text: str) -> dict[str, str]:
        page = self.pages[page_id]
        body = page["body"]
        if hashlib.sha256(body.encode()).hexdigest() != expected_sha256 or body.count(old_text) != 1:
            raise ValueError("conflict")
        page["body"] = body.replace(old_text, new_text, 1)
        return {"page_id": page_id, "sha256": hashlib.sha256(page["body"].encode()).hexdigest()}


class AcceptanceOrchestrationTest(unittest.TestCase):
    def test_recovery_reads_back_only_the_single_recorded_creation(self):
        page_id = str(uuid4())
        args = {"parent_id": ROOT, "title": "Test", "markdown": "original"}
        outcome = {"status": "uncertain", "result": {"page_id": page_id}}
        with tempfile.TemporaryDirectory() as temp:
            journal = _MutationReceipt(Path(temp))
            journal.begin("create_page", "original-intent", args)
            journal.finish("original-intent", "uncertain", outcome)
            gateway = Mock(spec=["verify_created_page"])
            gateway.verify_created_page.return_value = {"page_id": page_id, "sha256": "readback"}
            result = _recover_first_create(journal.path, gateway, args)
            self.assertEqual(result["original_request_id"], "original-intent")
            gateway.verify_created_page.assert_called_once_with(page_id, ROOT, "Test", "original")
            with self.assertRaises(ValueError):
                _recover_first_create(journal.path, gateway, dict(args, parent_id=str(uuid4())))
            journal.begin("create_page", "additional-intent", args)
            with self.assertRaises(ValueError):
                _recover_first_create(journal.path, gateway, args)

    def test_mutation_exception_leaves_durable_uncertain_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = _MutationReceipt(Path(temp))
            with self.assertRaises(RuntimeError):
                _mutate(journal, "replace_text", {"request_id": "synthetic-failure"},
                        lambda: (_ for _ in ()).throw(OSError("response lost")))
            entries = json.loads((Path(temp) / "mutations.json").read_text())
            self.assertEqual(entries[0]["status"], "uncertain")
            self.assertEqual(entries[0]["request_id"], "synthetic-failure")

    def test_full_bounded_flow_over_real_local_http(self):
        FakeNotionHub.pages = {}
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            token_file = base / "notion-token"
            token_file.write_text("synthetic-token\n")
            token_file.chmod(0o600)
            output = base / "receipt"
            with patch("context_lab.notion_hub.NotionHub", FakeNotionHub):
                with patch("scripts.accept_notion_hub.NotionHub", FakeNotionHub):
                    with patch("sys.stdout"):
                        status = main(["--token-file", str(token_file), "--root", ROOT,
                                       "--output", str(output)])
            self.assertEqual(status, 0)
            receipt = json.loads((output / "receipt.json").read_text())
            self.assertEqual(receipt["created_test_pages"], 2)
            self.assertEqual(receipt["reader_count"], 16)
            self.assertEqual(receipt["pre_sync_baselines"], {"v1": 5, "v2": 6, "unread": 5})
            self.assertEqual(receipt["delivery_modes"], {"delta": 11, "snapshot": 5})
            self.assertTrue(receipt["lost_ack_restart_recovered"])
            mutations = json.loads((output / "mutations.json").read_text())
            self.assertEqual(len(mutations), 4)
            self.assertTrue(all(item["status"] == "completed" for item in mutations))
            self.assertTrue(all(item["request_id"] for item in mutations))


if __name__ == "__main__":
    unittest.main()
