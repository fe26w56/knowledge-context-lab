import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from scripts.check_distribution import check_archive


class DistributionChecksTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def _sdist(self, name="sample-0.1.0.tar.gz", *, extra=None):
        path = self.root / name
        entries = {
            "README.md": b"synthetic review package\n",
            "pyproject.toml": b"[build-system]\n",
            "src/context_lab/__init__.py": b"__all__=[]\n",
            "tests/test_smoke.py": b"pass\n",
            "fixtures/phase2/corpus.json": b'{"privacy":"public_synthetic"}\n',
        }
        entries.update(extra or {})
        with tarfile.open(path, "w:gz") as archive:
            for relative, data in entries.items():
                info = tarfile.TarInfo("sample-0.1.0/" + relative)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_prefixed_sdist_is_checked_after_stripping_one_root(self):
        result = check_archive(self._sdist())
        self.assertEqual("sdist", result["kind"])

    def test_sdist_content_secret_is_rejected(self):
        path = self._sdist(extra={"docs/bad.md": b"token sk-" + b"a" * 40})
        with self.assertRaisesRegex(ValueError, "credential-like content"):
            check_archive(path)

    def test_sdist_private_runtime_path_is_rejected(self):
        path = self._sdist(extra={"docs/path.md": b"runtime: /" + b"tmp/kcl-work\n"})
        with self.assertRaisesRegex(ValueError, "private or runtime path"):
            check_archive(path)

    def test_sdist_private_path_is_rejected(self):
        path = self._sdist(extra={"docs/path.md": b"source: /" + b"private/secret\n"})
        with self.assertRaisesRegex(ValueError, "private or runtime path"):
            check_archive(path)

    def test_url_path_is_not_treated_as_local_private_path(self):
        path = self._sdist(extra={"fixtures/page.json": b'{"url":"https://example.invalid/private/contact"}'})
        self.assertEqual("sdist", check_archive(path)["kind"])

    def test_sdist_environment_and_sqlite_files_are_rejected(self):
        env = self._sdist(extra={".env.local": b"TOKEN=redacted\n"})
        with self.assertRaisesRegex(ValueError, "environment file"):
            check_archive(env)
        sqlite = self._sdist(extra={"runs/store.sqlite-wal": b"not public\n"})
        with self.assertRaisesRegex(ValueError, "archive/database file"):
            check_archive(sqlite)

    def test_sdist_traversal_is_rejected_before_normalization(self):
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            check_archive(self._sdist(extra={"../outside.txt": b"escape"}))

    def test_wheel_absolute_path_is_rejected(self):
        path = self.root / "bad.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("/absolute.txt", b"bad")
        with self.assertRaisesRegex(ValueError, "absolute path"):
            check_archive(path)

    def test_wheel_symlink_is_rejected(self):
        path = self.root / "bad.whl"
        info = zipfile.ZipInfo("context_lab/link")
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, b"target")
        with self.assertRaisesRegex(ValueError, "symlink"):
            check_archive(path)

    def test_sdist_root_directory_does_not_shift_content_scans(self):
        path = self.root / "root-entry.tar.gz"
        source = self._sdist()
        with tarfile.open(source) as original, tarfile.open(path, "w:gz") as output:
            root = tarfile.TarInfo("sample-0.1.0")
            root.type = tarfile.DIRTYPE
            output.addfile(root)
            for member in original.getmembers():
                output.addfile(member, original.extractfile(member))
            bad = tarfile.TarInfo("sample-0.1.0/docs/last.md")
            data = b"ghp_" + b"x" * 40
            bad.size = len(data)
            output.addfile(bad, io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, "credential-like content"):
            check_archive(path)


if __name__ == "__main__":
    unittest.main()
