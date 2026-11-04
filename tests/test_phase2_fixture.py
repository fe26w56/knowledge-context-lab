import hashlib
import json
import unittest
from pathlib import Path

from context_lab.evaluate import validate_inputs


ROOT = Path(__file__).parents[1]
FIX = ROOT / "fixtures" / "phase2"


class Phase2FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((FIX / "corpus.json").read_text())
        cls.dev = json.loads((FIX / "dev.json").read_text())
        cls.final = json.loads((FIX / "final.json").read_text())
        cls.freeze = json.loads((FIX / "FREEZE.json").read_text())

    def test_frozen_hashes_and_counts(self):
        self.assertTrue(self.freeze["frozen_before_improvement"])
        self.assertFalse(self.freeze["independent_benchmark"])
        self.assertEqual({"dev": 20, "final": 20}, self.freeze["question_counts"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(digest, hashlib.sha256((FIX / name).read_bytes()).hexdigest())

    def test_each_split_is_valid_and_grounded(self):
        for data in (self.dev, self.final):
            validate_inputs(self.corpus, data)
            self.assertEqual(20, len(data["queries"]))
            for query in data["queries"]:
                for key in ("condition_quotes", "obsolete_quotes", "rubric"):
                    self.assertIn(key, query)
                self.assertIn(query["category"], {"current_decision", "history", "proposal", "paraphrase", "long_table", "condition_exception", "multi_source", "multiple_conditions", "unknown", "scope_private", "scope_owner", "handoff", "handoff_constraint", "retry", "idempotency", "concurrency", "measured_vs_target", "short_new", "old_version"})

    def test_categories_and_private_cases_cover_both_splits(self):
        required = {"current_decision", "history", "proposal", "paraphrase", "long_table", "condition_exception", "multi_source", "unknown", "handoff_constraint"}
        for data in (self.dev, self.final):
            categories = {q["category"] for q in data["queries"]}
            self.assertTrue(required <= categories, categories)
        private = [q for q in self.dev["queries"] + self.final["queries"] if q["category"] == "scope_private"]
        self.assertGreaterEqual(len(private), 3)
        self.assertTrue(any(q["forbidden_quotes"] for q in private))

    def test_no_query_id_or_gold_is_in_retrieval_request(self):
        gold_keys = {"id", "expected_quotes", "forbidden_quotes", "condition_quotes", "obsolete_quotes", "rubric", "answerable"}
        for data in (self.dev, self.final):
            for query in data["queries"]:
                self.assertEqual({"text", "actor", "as_of", "mode"}, set(query["request"]))
                self.assertTrue(gold_keys.isdisjoint(query["request"]))


if __name__ == "__main__":
    unittest.main()
