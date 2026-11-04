from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.prepare_publication import audit_tree, copy_file, mark_unbundled_links


class PublicationTests(unittest.TestCase):
    def test_symlink_cannot_export_outside_source(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, out = base / 'source', base / 'output'
            root.mkdir(); out.mkdir()
            (base / 'outside.txt').write_text('not part of the source tree')
            (root / 'leak.md').symlink_to(base / 'outside.txt')
            with self.assertRaises(ValueError):
                copy_file(root, out, 'leak.md')
            self.assertEqual([], list(out.iterdir()))

    def test_export_audit_rejects_credentials_and_runtime_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'evidence.json'
            p.write_text('sk-' + 'a' * 40)
            with self.assertRaises(ValueError):
                audit_tree(root)
            p.write_text('{}')
            (root / 'session.sqlite').write_bytes(b'local runtime')
            with self.assertRaises(ValueError):
                audit_tree(root)

    def test_missing_historical_links_are_explicit_without_rewriting_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docs').mkdir(); (root / 'fixtures').mkdir()
            fixture = root / 'fixtures' / 'fixed.json'
            fixture.write_text('{"quote":"unaltered"}')
            body = fixture.read_bytes()
            report = root / 'docs' / 'report.md'
            report.write_text('[present](../fixtures/fixed.json) [old](../runs/omitted.json)')
            changed = mark_unbundled_links(root)
            self.assertEqual({'docs/report.md': ['../runs/omitted.json']}, changed)
            self.assertIn('[present](../fixtures/fixed.json)', report.read_text())
            self.assertIn('historical artifact not included', report.read_text())
            self.assertEqual(body, fixture.read_bytes())
