import hashlib, json, tempfile, unittest
from unittest.mock import patch
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from scripts.preflight import run

class PreflightTests(unittest.TestCase):
    def base(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        d=Path(temp.name); (d/".venv/bin").mkdir(parents=True); (d/".venv/bin/python").write_text("")
        (d/"fixtures/phase2").mkdir(parents=True); (d/"fixtures/phase2/corpus.json").write_text("{}")
        (d/"fixtures/phase2/dev.json").write_text("{}"),(d/"fixtures/phase2/final.json").write_text("{}")
        files={n:hashlib.sha256((d/"fixtures/phase2"/n).read_bytes()).hexdigest() for n in ("corpus.json","dev.json","final.json")}
        (d/"fixtures/phase2/FREEZE.json").write_text(json.dumps({"frozen_before_improvement":True,"sha256":files}))
        (d/"BUNDLE_MANIFEST.json").write_text(json.dumps({"sha256":{}})); return d
    def test_missing_cache_is_error_without_network(self):
        d=self.base(); r=run(d,skip_write_probe=True,cache_dir=d/"missing"); self.assertFalse(r["ok"]); self.assertEqual(r["checks"]["o200k_base_cache"]["status"],"error")
    def test_broken_phase2_hash_is_error(self):
        d=self.base(); (d/"fixtures/phase2/corpus.json").write_text("changed"); r=run(d,skip_write_probe=True,cache_dir=d); self.assertEqual(r["checks"]["phase2_freeze"]["status"],"error")
    def test_skip_write_probe_is_reported(self):
        d=self.base(); r=run(d,skip_write_probe=True,cache_dir=d); self.assertTrue(r["checks"]["write_probe"]["skipped"])
    def test_missing_package_does_not_attempt_remote_load(self):
        d=self.base()
        with patch("scripts.preflight.importlib.metadata.version",side_effect=PackageNotFoundError), patch("urllib.request.urlopen",side_effect=AssertionError("Network forbidden")):
            r=run(d,skip_write_probe=True,cache_dir=d)
        self.assertEqual(r["checks"]["tiktoken"]["status"],"error")
        self.assertEqual(r["checks"]["o200k_base_load"]["status"],"error")
    def test_corrupt_cache_is_reported_without_remote_fallback(self):
        d=self.base()
        key=hashlib.sha1(b"https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken").hexdigest()
        (d/key).write_bytes(b"corrupt")
        with patch("urllib.request.urlopen",side_effect=AssertionError("Network forbidden")):
            r=run(d,skip_write_probe=True,cache_dir=d)
        self.assertEqual(r["checks"]["o200k_base_load"]["status"],"error")
if __name__=="__main__": unittest.main()
