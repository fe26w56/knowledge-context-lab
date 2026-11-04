from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.evaluate_workspace_pilot import run
from context_lab.workspace import notion_pages


class WorkspacePilotTests(unittest.TestCase):
    def _pages(self):
        return {
            "privacy": "private_authorized",
            "pages": [{
                "id": "pilot-page",
                "title": "架空のprivate pilot",
                "body": "## 現在の方針\n一次応答は確認後に記録します。\n## 履歴\n以前の案。",
                "scope": "private",
                "owner": "pilot-owner",
                "properties": {"category": "fictional"},
                "url": "https://pilot.example.invalid/private/page",
            }],
        }

    def test_pilot_records_file_sqlite_arms_reads_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages.json"
            requests = root / "requests.json"
            output = root / "nested" / "result.json"
            pages.write_text(json.dumps(self._pages(), ensure_ascii=False), encoding="utf-8")
            requests.write_text(json.dumps({"requests": [{"case": "pilot", "request": "現在の方針"}]}, ensure_ascii=False), encoding="utf-8")
            result = run(pages, requests, output, actor="pilot-owner", repo=Path(__file__).parents[1])
            self.assertEqual(len(result["arms"]), 4)
            self.assertTrue(all(row["payload_equal"] for row in result["arms"]))
            self.assertEqual(result["local_reads"]["completed"], 16)
            self.assertTrue(result["local_reads"]["all_payload_equal"])
            self.assertEqual(result["lifecycle"]["topic_status_after_correction"], "needs_review")
            self.assertTrue(result["lifecycle"]["replay_unchanged"])
            self.assertTrue(result["lifecycle"]["export_restore_parity"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            proc = subprocess.run(
                [sys.executable, "scripts/evaluate_workspace_pilot.py", "--pages", str(pages),
                 "--requests", str(requests), "--output", str(root / "cli.json"),
                 "--actor", "pilot-owner"], cwd=Path(__file__).parents[1], text=True,
                capture_output=True, env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
                check=True)
            summary = json.loads(proc.stdout)
            self.assertEqual(set(summary), {"status", "page_count", "request_count", "arm_count", "output_written"})
            self.assertEqual(summary["status"], "ok")
            with self.assertRaisesRegex(ValueError, "new path"):
                run(pages, requests, output, actor="pilot-owner", repo=Path(__file__).parents[1])

    def test_native_capture_arm_uses_raw_page_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = self._pages()
            data["pages"][0]["raw_capture"] = {"id": "pilot-page", "text": "<content>..."}
            pages = root / "pages.json"
            requests = root / "requests.json"
            output = root / "result.json"
            pages.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            requests.write_text(json.dumps({"requests": [{"case": "pilot", "request": "現在の方針"}]}, ensure_ascii=False), encoding="utf-8")
            result = run(pages, requests, output, actor="pilot-owner", repo=Path(__file__).parents[1])
            self.assertTrue(result["native_capture_available"])
            native = [row for row in result["arms"] if row["arm"] == "native_capture"]
            self.assertEqual(len(native), 1)
            self.assertEqual(native[0]["payload"]["sqlite"]["sources"][0]["capture"]["id"], "pilot-page")
            self.assertEqual(result["local_reads"]["max_inflight"], 16)

    def test_canonical_notion_capture_correction_reprojects_and_reads_back(self):
        raw = {"id": "pilot-notion", "title": "Canonical pilot", "url": "https://pilot.example.invalid/page",
               "text": "<page>\n<properties>\n{\"status\":\"proposed\"}\n</properties>\n"
                       "<content>\n## Current\nOriginal capture text.\n</content>\n</page>"}
        page = notion_pages([raw], owner="pilot-owner")[0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages = root / "pages.json"
            requests = root / "requests.json"
            output = root / "result.json"
            pages.write_text(json.dumps({"privacy": "private_authorized", "pages": [page]}, ensure_ascii=False), encoding="utf-8")
            requests.write_text(json.dumps({"requests": [{"case": "pilot", "request": "Original capture"}]}, ensure_ascii=False), encoding="utf-8")
            result = run(pages, requests, output, actor="pilot-owner", repo=Path(__file__).parents[1])
            self.assertEqual(result["lifecycle"]["correction_projection"], "capture_reprojected")
            self.assertTrue(result["lifecycle"]["capture_body_readback_consistent"])
            self.assertEqual(result["lifecycle"]["readback_version"], 2)
            self.assertTrue(result["lifecycle"]["readback_sha256_matches_corrected"])
            self.assertTrue(result["lifecycle"]["old_version_preserved"])

    def test_public_repo_input_and_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            requests = root / "requests.json"
            requests.write_text(json.dumps({"requests": [{"case": "pilot", "request": "x"}]}), encoding="utf-8")
            public_pages = Path(__file__).parents[1] / "pyproject.toml"
            with self.assertRaisesRegex(ValueError, "outside the public repository"):
                run(public_pages, requests, root / "result.json", actor="pilot-owner", repo=Path(__file__).parents[1])

