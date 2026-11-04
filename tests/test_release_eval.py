import json
from pathlib import Path
import unittest

from context_lab.release_eval import generate, requirements, score


class ReleaseGradingTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads((Path(__file__).parents[1]/"fixtures/phase2/corpus.json").read_text())

    def test_generator_is_repeatable_with_private_and_status_metadata(self):
        a, lineage, info = generate(self.corpus, 100, 77)
        b, other, repeated = generate(self.corpus, 100, 77)
        self.assertEqual((a, lineage, info), (b, other, repeated))
        self.assertEqual(100, len(a))
        self.assertEqual(set(lineage), {d["id"] for d in a})
        self.assertEqual(79, sum(info["generated_counts"].values()))
        self.assertTrue(all(d.get("owner") for d in a if d["scope"] == "private"))

    def test_wrong_source_copy_is_not_complete_and_allowed_exact_clone_is(self):
        request = dict(text="Ask about policy", actor="bot_01", scope=None, mode="search", as_of="2026-05-20")
        query = dict(request=request, expected_quotes=["Approved policy"], evidence_sources={"Approved policy": ["correct"]})
        docs = {key: dict(scope="shared", owner=None) for key in ("correct", "clone", "opposing")}
        lineage = {"correct": ("correct", "base"), "clone": ("correct", "exact"), "opposing": ("correct", "contradiction")}
        rules = requirements(query, [], lineage)
        bad = json.dumps({"items": [{"document_id": "opposing", "text": "Reject the Approved policy"}]})
        result = score(bad, query, rules, docs)
        self.assertTrue(result["literal_complete"])
        self.assertFalse(result["complete"])
        good = json.dumps({"items": [{"document_id": "clone", "text": "Approved policy"}]})
        self.assertTrue(score(good, query, rules, docs)["complete"])

    def test_empty_unknown_is_unscored_and_scope_is_checked_without_canary(self):
        query = dict(request=dict(actor="bot_01", scope="shared"), expected_quotes=[], answerable=False)
        empty = score('{"items":[]}', query, {}, {})
        self.assertFalse(empty["eligible"])
        self.assertFalse(empty["complete"])
        result = score('{"items":[{"document_id":"p","text":"generic text"}]}', query, {}, {"p": dict(scope="private", owner="bot_02")})
        self.assertEqual(1, result["scope_violations"])
