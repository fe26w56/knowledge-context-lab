from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_workspace_interfaces import fixture_pages

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceHandoffCliTests(unittest.TestCase):
    def test_initial_delta_identity_mismatch_and_atomic_next(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "workspace.sqlite"
            pages_path = root / "pages.json"
            pages = fixture_pages()
            unchanged_marker = "UNTOUCHED_LONG_MARKER_" + ("x" * 180)
            pages[0] = dict(pages[0], body=pages[0]["body"] + "\n" + unchanged_marker + "\n最後の未変更段落")
            pages_path.write_text(json.dumps({"pages": pages}, ensure_ascii=False), encoding="utf-8")

            def cli(actor, *args, check=True):
                proc = subprocess.run(
                    [sys.executable, "-m", "context_lab.workspace_cli", "--db", str(db), "--actor", actor, *args],
                    cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                    text=True, capture_output=True)
                if check:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                return proc

            cli("ops-bot", "import-pages", "--input", str(pages_path), "--request-id", "seed")
            first = root / "first.json"
            packet = json.loads(cli("ops-bot", "handoff", "--scope", "shared", "--next", str(first)).stdout)
            self.assertEqual(packet["packet"]["mode"], "snapshot")
            self.assertEqual(packet["base_status"], "fresh_snapshot")
            first_before = first.read_bytes()

            updated = [dict(page) for page in pages]
            lines = updated[0]["body"].splitlines(keepends=True)
            changed_index = next(index for index, line in enumerate(lines) if "追加条件" not in line and "UNTOUCHED_LONG_MARKER_" not in line)
            lines[changed_index] = lines[changed_index].rstrip("\n") + " (revised)\n"
            updated[0] = dict(updated[0], title=updated[0]["title"] + " revised", body="".join(lines))
            updated_path = root / "updated.json"
            updated_path.write_text(json.dumps({"pages": updated}, ensure_ascii=False), encoding="utf-8")
            expected_path = root / "expected.json"
            expected_path.write_text(json.dumps({updated[0]["id"]: 1}), encoding="utf-8")
            cli("ops-bot", "import-pages", "--input", str(updated_path), "--request-id", "correction", "--expected-versions", str(expected_path))

            second = root / "second.json"
            delta = json.loads(cli("ops-bot", "handoff", "--scope", "shared", "--base", str(first), "--next", str(second)).stdout)
            self.assertEqual(delta["packet"]["mode"], "delta")
            page_id = updated[0]["id"]
            patches = delta["packet"]["patches"]
            self.assertIn("body/" + page_id, patches)
            self.assertNotIn(unchanged_marker, patches["body/" + page_id]["text"])
            self.assertIn("revised", patches["metadata/" + page_id]["text"])
            from context_lab.handoff_delta import apply_update
            initial_pages = apply_update(None, packet["packet"], principal="ops-bot", scope="shared")
            updated_pages = apply_update(initial_pages, delta["packet"], principal="ops-bot", scope="shared")
            self.assertEqual(updated_pages["body/" + page_id], updated[0]["body"])
            self.assertEqual(updated_pages, json.loads(second.read_text())["pages"])
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            self.assertEqual(first.read_bytes(), first_before)

            attacker_next = root / "attacker.json"
            attacker = json.loads(cli("attacker", "handoff", "--scope", "shared", "--base", str(first), "--next", str(attacker_next)).stdout)
            self.assertTrue(attacker["base_status"].startswith("fresh_snapshot:"))
            self.assertEqual(attacker["packet"]["mode"], "snapshot")
            self.assertNotIn("patches", attacker["packet"])

            second_before = second.read_bytes()
            failed = cli("ops-bot", "handoff", "--scope", "shared", "--base", str(first), "--next", str(second), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(second.read_bytes(), second_before)

    def test_authorized_view_fails_closed_and_purges_lost_visibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "workspace.sqlite"
            pages = fixture_pages()
            pages_path = root / "pages.json"
            pages_path.write_text(json.dumps({"pages": pages}, ensure_ascii=False), encoding="utf-8")

            def cli(*args, check=True):
                proc = subprocess.run(
                    [sys.executable, "-m", "context_lab.workspace_cli", "--db", str(db),
                     "--actor", "ops-bot", *args], cwd=ROOT,
                    env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                    text=True, capture_output=True)
                if check:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                return proc

            cli("import-pages", "--input", str(pages_path), "--request-id", "seed")
            first = root / "first.json"
            cli("handoff", "--scope", "shared", "--next", str(first))
            visible = pages[0]
            manifest = root / "authorized.json"
            manifest.write_text(json.dumps({"actor": "ops-bot", "scope": "shared", "complete": True,
                "pages": [{"id": visible["id"], "title": visible["title"],
                           "body_sha256": hashlib.sha256(visible["body"].encode()).hexdigest()}]}), encoding="utf-8")
            reduced = root / "reduced.json"
            result = json.loads(cli("handoff", "--scope", "shared", "--base", str(first),
                                    "--authorized-view", str(manifest), "--next", str(reduced)).stdout)
            self.assertEqual(result["packet"]["mode"], "delta")
            purged = {key.removeprefix("body/") for key in result["packet"]["purge"] if key.startswith("body/")}
            self.assertEqual(purged, {page["id"] for page in pages[1:]})
            self.assertNotIn(pages[1]["body"], json.dumps(result["packet"], ensure_ascii=False))

            changed_manifest = root / "unsynced.json"
            changed_manifest.write_text(json.dumps({"actor": "ops-bot", "scope": "shared", "complete": True,
                "pages": [{"id": visible["id"], "title": visible["title"], "body_sha256": "0" * 64}]}), encoding="utf-8")
            missing_next = root / "must-not-exist.json"
            failed = cli("handoff", "--scope", "shared", "--base", str(first),
                         "--authorized-view", str(changed_manifest), "--next", str(missing_next), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(missing_next.exists())

            unavailable = root / "unavailable.json"
            unavailable.write_text(json.dumps({"actor": "ops-bot", "scope": "shared", "complete": False,
                "pages": []}), encoding="utf-8")
            unavailable_next = root / "unavailable-next.json"
            failed = cli("handoff", "--scope", "shared", "--base", str(first),
                         "--authorized-view", str(unavailable), "--next", str(unavailable_next), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(unavailable_next.exists())


if __name__ == "__main__":
    unittest.main()
