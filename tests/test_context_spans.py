import copy
import unittest

from context_lab.context_spans import compact_context


class ContextSpanCompactionTests(unittest.TestCase):
    def test_nested(self):
        c = {"sources": [{"id": "x", "spans": [{"start": 0, "end": 10, "text": "abcdefghij"}, {"start": 2, "end": 5, "text": "cde"}]}]}
        self.assertEqual(compact_context(c)["sources"][0]["spans"], [{"start": 0, "end": 10, "text": "abcdefghij"}])

    def test_overlap(self):
        c = {"sources": [{"id": "x", "spans": [{"start": 0, "end": 5, "text": "abcde"}, {"start": 3, "end": 8, "text": "defgh"}]}]}
        self.assertEqual(compact_context(c)["sources"][0]["spans"][0]["text"], "abcdefgh")

    def test_adjacent(self):
        c = {"sources": [{"id": "x", "spans": [{"start": 0, "end": 2, "text": "ab"}, {"start": 2, "end": 4, "text": "cd"}]}]}
        self.assertEqual(compact_context(c)["sources"][0]["spans"], [{"start": 0, "end": 4, "text": "abcd"}])

    def test_gap_preserved(self):
        c = {"sources": [{"id": "x", "spans": [{"start": 0, "end": 2, "text": "ab"}, {"start": 3, "end": 5, "text": "de"}]}]}
        self.assertEqual(len(compact_context(c)["sources"][0]["spans"]), 2)

    def test_mismatch_rejected(self):
        c = {"sources": [{"id": "x", "spans": [{"start": 0, "end": 5, "text": "abcde"}, {"start": 3, "end": 8, "text": "XYZgh"}]}]}
        with self.assertRaises(ValueError): compact_context(c)

    def test_input_immutable(self):
        c = {"meta": {"x": 1}, "sources": [{"id": "x", "title": "T", "spans": [{"start": 0, "end": 2, "text": "ab"}, {"start": 2, "end": 4, "text": "cd"}]}]}
        before = copy.deepcopy(c); compact_context(c); self.assertEqual(c, before)

    def test_body_and_metadata_preserved(self):
        c = {"sources": [{"id": "x", "body": "raw", "status": "current", "spans": [{"start": 0, "end": 2, "text": "ab"}]}]}
        got = compact_context(c); self.assertEqual(got["sources"][0]["body"], "raw"); self.assertEqual(got["sources"][0]["status"], "current")

    def test_multiple_sources_independent(self):
        c = {"sources": [{"id": "a", "spans": [{"start": 0, "end": 1, "text": "a"}, {"start": 1, "end": 2, "text": "b"}]}, {"id": "b", "spans": [{"start": 0, "end": 1, "text": "x"}]}]}
        got = compact_context(c); self.assertEqual(got["sources"][0]["spans"][0]["text"], "ab"); self.assertEqual(got["sources"][1]["spans"][0]["text"], "x")

    def test_malformed_span_rejected_fail_closed(self):
        for span in [{"start": True, "end": 1, "text": "a"},
                     {"start": 0, "end": 0, "text": ""},
                     {"start": 0, "end": 1, "text": "a", "label": "x"}]:
            with self.subTest(span=span), self.assertRaises(ValueError):
                compact_context({"sources": [{"id": "x", "spans": [span]}]})
