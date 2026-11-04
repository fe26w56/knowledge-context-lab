import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_release_bundle import build, collect


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in ("README.md", "pyproject.toml", "MANIFEST.in", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", ".gitignore", "BUNDLE_MANIFEST.json"):
            (self.root / name).write_text("public synthetic package\n")
        for name in ("src/context_lab", "tests", "docs", "configs", ".github", "fixtures/synthetic", "fixtures/phase2", "fixtures/phase2-release-v6", "runs/synthetic-v1", "scripts"):
            (self.root / name).mkdir(parents=True)
        for name in ("fixtures/synthetic/corpus.json", "fixtures/phase2/corpus.json", "fixtures/phase2-release-v6/corpus.json"):
            (self.root / name).write_text(json.dumps({"privacy": "public_synthetic"}))
        (self.root / "src/context_lab/demo.py").write_text("pass\n")

    def test_allowlist_manifest_readback_and_excludes_drafts(self):
        (self.root / "scripts/create_release_fixture_v6.py").write_text("draft\n")
        (self.root / "scripts/keep.py").write_text("pass\n")
        out = self.root / "review.zip"
        result = build(out, self.root)
        self.assertEqual(result["manifest"]["license"], "MIT")
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
            self.assertNotIn("knowledge-context-lab/scripts/create_release_fixture_v6.py", names)
            self.assertIn("knowledge-context-lab/scripts/keep.py", names)
            manifest = json.loads(archive.read("knowledge-context-lab/RELEASE_BUNDLE_MANIFEST.json"))
            for name, digest in manifest["sha256"].items():
                self.assertEqual(digest, hashlib.sha256(archive.read("knowledge-context-lab/" + name)).hexdigest())
        with self.assertRaises(FileExistsError):
            build(out, self.root)

    def test_personal_url_and_symlink_are_rejected(self):
        (self.root / "README.md").write_text("https://app.notion.com/" + "p/private\n")
        with self.assertRaises(ValueError):
            collect(self.root)
        (self.root / "README.md").write_text("public\n")
        (self.root / "target").write_text("x")
        (self.root / "docs/link.md").symlink_to(self.root / "target")
        with self.assertRaises(ValueError):
            collect(self.root)

    def test_fixture_url_is_not_a_local_path(self):
        (self.root / "README.md").write_text("https://example.invalid/private/contact\n")
        collect(self.root)
        for folder in ("Users", "private", "tmp"):
            (self.root / "README.md").write_text('"/' + folder + '/secret"\n')
            with self.assertRaises(ValueError):
                collect(self.root)


if __name__ == "__main__":
    unittest.main()
