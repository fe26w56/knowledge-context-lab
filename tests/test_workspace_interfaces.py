from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from context_lab.workspace import Workspace
from context_lab.store import ValidationError


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures" / "phase2-migration-v2"


def fixture_pages(split: str = "dev") -> list[dict]:
    corpus = json.loads((FIXTURE / "pages.json").read_text(encoding="utf-8"))
    prefix = "dev-" if split == "dev" else "fin-"
    # The CLI actor is ops-bot; keep the private page out of this seed batch.
    # Private import is exercised separately with its owner identity.
    return [page for page in corpus["pages"] if page["id"].startswith(prefix) and page["scope"] == "shared"]


class WorkspaceInterfaceTests(unittest.TestCase):
    def test_context_all_is_not_capped_for_large_visible_snapshot(self):
        pages = [
            {
                "id": f"dev-bulk-{index:03d}",
                "title": f"公開メモ {index:03d}",
                "body": f"共有された架空の運用メモ {index:03d}。",
                "scope": "shared",
                "owner": None,
                "properties": {"kind": "fictional"},
                "source_url": None,
                "attachments": [],
                "updated_at": "2026-09-12T00:00:00Z",
            }
            for index in range(101)
        ]
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(Path(td) / "large.sqlite")
            ws.import_pages(pages, actor="ops-bot", request_id="large-context-seed")
            result = ws.context("合計で全件を確認", actor="ops-bot", coverage="all", candidate_pages=1)
            self.assertEqual(result["policy"]["selected"], "all")
            self.assertEqual(result["visible_source_count"], 101)
            self.assertEqual(result["returned_source_count"], 101)
            self.assertEqual(len(result["sources"]), 101)

    def test_context_coverage_explicit_all_ranked_and_private_boundary(self):
        pages = fixture_pages()
        private = next(p for p in json.loads((FIXTURE / "pages.json").read_text(encoding="utf-8"))["pages"] if p["scope"] == "private")
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(Path(td) / "workspace.sqlite")
            ws.import_pages(pages, actor="ops-bot", request_id="context-seed")
            ws.import_pages([private], actor="contract-admin", request_id="private-seed")
            all_context = ws.context("合計で全件を確認", actor="ops-bot", coverage="all")
            self.assertEqual(all_context["policy"]["selected"], "all")
            self.assertEqual(all_context["visible_source_count"], 7)
            self.assertEqual(all_context["returned_source_count"], 7)
            self.assertTrue(all("text" in item and "properties" in item for item in all_context["sources"]))
            ranked = ws.context("Cedar 公開条件", actor="ops-bot", coverage="ranked", candidate_pages=1, ranking="overlap")
            self.assertEqual(ranked["returned_source_count"], 1)
            self.assertIn(ranked["sources"][0]["source_id"], {"dev-cedar-main", "dev-cedar-note"})
            file_sources = ws._visible_sources("ops-bot")
            self.assertEqual(
                all_context,
                Workspace.context_sources(file_sources, "合計で全件を確認", coverage="all"),
            )
            self.assertEqual(
                ranked,
                Workspace.context_sources(file_sources, "Cedar 公開条件", coverage="ranked",
                                         candidate_pages=1, ranking="overlap"),
            )
            self.assertNotIn(private["id"], json.dumps(all_context, ensure_ascii=False))

    def test_opt_in_ranking_keeps_full_compact_payload_and_file_parity(self):
        pages = fixture_pages()
        # Add a rare body term without changing the public fixture.
        rare = dict(pages[0])
        rare["id"] = "dev-rare"
        rare["title"] = "一般運用メモ"
        rare["body"] = rare["body"] + "\n固有語 zaffre-lattice-91。"
        pages = pages + [rare]
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(Path(td) / "workspace.sqlite")
            ws.import_pages(pages, actor="ops-bot", request_id="ranking-seed")
            query = "zaffre-lattice-91"
            sqlite_result = ws.search(query, actor="ops-bot", mode="compact", ranking="overlap", candidate_pages=1)
            file_sources = ws._visible_sources("ops-bot")
            file_result = Workspace.search_sources(file_sources, query, mode="compact", ranking="overlap", candidate_pages=1)
            self.assertEqual(sqlite_result, file_result)
            self.assertEqual(sqlite_result["sources"][0]["source_id"], "dev-rare")
            self.assertIn("zaffre-lattice-91", sqlite_result["sources"][0]["text"])
            self.assertEqual(sqlite_result["sources"][0]["source_version"], 1)

    def test_capture_mode_preserves_connector_payload_once_and_file_parity(self):
        pages = fixture_pages()
        for page in pages:
            page["raw_capture"] = {"connector": "fictional", "page_id": page["id"],
                                   "blocks": [{"kind": "custom", "value": page["title"]}]}
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(Path(td) / "workspace.sqlite")
            ws.import_pages(pages, actor="ops-bot", request_id="capture-seed")
            sqlite_result = ws.search("Cedar 公開条件", actor="ops-bot", mode="capture",
                                      ranking="legacy", candidate_pages=3)
            file_sources = ws._visible_sources("ops-bot")
            file_result = Workspace.search_sources(file_sources, "Cedar 公開条件", mode="capture",
                                                   ranking="legacy", candidate_pages=3)
            self.assertEqual(sqlite_result, file_result)
            self.assertTrue(sqlite_result["sources"])
            selected_id = sqlite_result["sources"][0]["source_id"]
            original = next(page["raw_capture"] for page in pages if page["id"] == selected_id)
            sqlite_result["sources"][0]["capture"]["blocks"][0]["value"] = "mutated"
            self.assertEqual(ws.get_source(selected_id, actor="ops-bot")["page"]["raw_capture"], original)

            incomplete = [dict(page) for page in pages]
            incomplete_page = next(page for page in incomplete if page["id"] == "dev-cedar-main")
            incomplete_page.pop("raw_capture")
            broken = Workspace(Path(td) / "broken.sqlite")
            broken.import_pages(incomplete, actor="ops-bot", request_id="capture-broken-seed")
            with self.assertRaisesRegex(ValidationError, "raw_capture"):
                broken.search("Cedar 公開条件", actor="ops-bot", mode="capture", candidate_pages=3)

    def test_cli_import_search_source_export_restore(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "workspace.sqlite")
            pages_file = Path(td) / "pages.json"
            cli_pages = fixture_pages()
            for page in cli_pages:
                page["raw_capture"] = {"connector": "fictional", "id": page["id"]}
            pages_file.write_text(json.dumps({"pages": cli_pages}, ensure_ascii=False), encoding="utf-8")

            def cli(*args: str, check: bool = True):
                proc = subprocess.run(
                    [sys.executable, "-m", "context_lab.workspace_cli", "--db", db,
                     "--actor", "ops-bot", *args], cwd=ROOT, text=True,
                    capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
                if check:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                return proc

            imported = json.loads(cli("import-pages", "--input", str(pages_file), "--request-id", "cli-import").stdout)
            self.assertEqual(len(imported["committed"]), 7)
            found = json.loads(cli("search", "Lumen通知の現行方針と以前の案", "--ranking", "overlap").stdout)
            self.assertEqual(found["status"], "found")
            self.assertEqual(found["sources"][0]["source_id"], "dev-lumen-main")
            captured = json.loads(cli("search", "Cedar 公開条件", "--mode", "capture").stdout)
            self.assertEqual(captured["sources"][0]["capture"]["connector"], "fictional")
            context = json.loads(cli("context", "合計で全件を確認", "--coverage", "all").stdout)
            self.assertEqual(context["policy"]["selected"], "all")
            self.assertEqual(context["returned_source_count"], 7)
            source = json.loads(cli("source", "dev-lumen-main").stdout)
            self.assertEqual(source["page"]["id"], "dev-lumen-main")
            bundle_path = Path(td) / "bundle.json"
            exported = json.loads(cli("export", "--output", str(bundle_path)).stdout)
            self.assertTrue(bundle_path.exists())
            self.assertIn("revisions", exported.get("tables", {}))
            restored_db = Path(td) / "restored.sqlite"
            restored = cli("restore", "--input", str(bundle_path), "--destination", str(restored_db))
            self.assertEqual(json.loads(restored.stdout)["restored"], str(restored_db.resolve()))

    def test_mcp_initialize_tools_and_actor_injection(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "workspace.sqlite"
            ws = Workspace(db)
            mcp_pages = fixture_pages()
            for page in mcp_pages:
                page["raw_capture"] = {"connector": "fictional", "id": page["id"]}
            ws.import_pages(mcp_pages, actor="ops-bot", request_id="mcp-seed")
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"request": "Lumen通知の現行方針", "ranking": "bm25"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search", "arguments": {"request": "Lumen通知", "actor": "attacker"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "search", "arguments": {"request": "Lumen通知", "bogus": 1}}},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "context", "arguments": {"request": "合計で全件を確認", "coverage": "all"}}},
                {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "search", "arguments": {"request": "Cedar 公開条件", "mode": "capture"}}},
            ]
            payload = "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages)
            proc = subprocess.run(
                [sys.executable, "-m", "context_lab.workspace_mcp", "--db", str(db), "--actor", "ops-bot"],
                cwd=ROOT, input=payload, text=True, capture_output=True,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
            self.assertEqual([reply["id"] for reply in replies], [1, 2, 3, 4, 5, 6, 7])
            self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-11-25")
            self.assertTrue(replies[1]["result"]["tools"])
            self.assertIn("structuredContent", replies[2]["result"])
            # An explicit actor argument is rejected; process identity is not
            # presented as an authentication mechanism.
            self.assertIn("error", replies[3])
            self.assertIn("error", replies[4])
            self.assertEqual(replies[5]["result"]["structuredContent"]["policy"]["selected"], "all")
            self.assertEqual(replies[6]["result"]["structuredContent"]["sources"][0]["capture"]["connector"], "fictional")

    def test_mcp_notifications_and_invalid_jsonrpc_are_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "workspace.sqlite"
            payload = "\n".join([
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "1.0", "id": 2, "method": "ping"}),
                "not-json",
                "",
            ]) + "\n"
            proc = subprocess.run(
                [sys.executable, "-m", "context_lab.workspace_mcp", "--db", str(db), "--actor", "ops-bot"],
                cwd=ROOT, input=payload, text=True, capture_output=True,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
            # Notifications have no response; malformed JSON gets one parse error.
            self.assertEqual(len(replies), 2)
            self.assertEqual(replies[0]["error"]["code"], -32600)
            self.assertEqual(replies[1]["error"]["code"], -32700)

    def test_mcp_requires_initialize_and_negotiates_unknown_version(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "workspace.sqlite"
            payload = "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "future"}}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": []}),
            ]) + "\n"
            proc = subprocess.run(
                [sys.executable, "-m", "context_lab.workspace_mcp", "--db", str(db), "--actor", "ops-bot"],
                cwd=ROOT, input=payload, text=True, capture_output=True,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
            self.assertEqual(replies[0]["error"]["code"], -32002)
            self.assertEqual(replies[1]["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(replies[2]["result"], {})


if __name__ == "__main__":
    unittest.main()
