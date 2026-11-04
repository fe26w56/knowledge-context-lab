import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_phase2_bundle import build, collect


class BundleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("synthetic", "phase2"):
            folder = self.root / "fixtures" / name
            folder.mkdir(parents=True)
            (folder / "corpus.json").write_text(json.dumps({"privacy": "public_synthetic"}))
        (self.root / "README.md").write_text("Example public data")

    def test_allowlist_and_hash_readback(self):
        (self.root / ".env").write_text("EXCLUDED=value")
        (self.root / "work").mkdir()
        (self.root / "work/private.json").write_text("excluded")
        output = self.root / "out.zip"
        result = build(output, self.root)
        self.assertEqual(result["files"], 3)
        with zipfile.ZipFile(output) as archive:
            self.assertNotIn("knowledge-context-lab/.env", archive.namelist())
            self.assertFalse(any("work/" in name for name in archive.namelist()))
        with self.assertRaises(FileExistsError):
            build(output, self.root)

    def test_credential_blocks_export(self):
        (self.root / "README.md").write_text("sk-" + "a" * 40)
        with self.assertRaisesRegex(ValueError, "credential"):
            collect(self.root)

    def test_symlink_blocks_export(self):
        target = self.root / "target.txt"
        target.write_text("example")
        (self.root / "README.md").unlink()
        (self.root / "README.md").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            collect(self.root)

    def test_non_synthetic_marker_blocks_export(self):
        (self.root / "fixtures/phase2/corpus.json").write_text(json.dumps({"privacy": "private"}))
        with self.assertRaisesRegex(ValueError, "synthetic"):
            collect(self.root)
