import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v4"


class CompletionFixtureV4Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.questions = json.loads((ROOT / "dev.json").read_text())["queries"] + json.loads((ROOT / "final.json").read_text())["queries"]
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())
        cls.tokens = json.loads((ROOT / "TOKEN_REPORT.json").read_text())

    def test_counts_ids_and_freeze(self):
        self.assertEqual(len(self.docs), 80)
        self.assertEqual(len(self.questions), 40)
        self.assertTrue(all(re.fullmatch(r"cv3d_[0-9a-f]{16}", x) for x in self.docs))
        self.assertTrue(all(re.fullmatch(r"cv3q_[0-9a-f]{16}", q["id"]) for q in self.questions))
        self.assertTrue(any(v["tokens"] > 2000 for v in self.tokens.values()))
        self.assertEqual(self.freeze["tokenizer"], "o200k_base")
        self.assertTrue(self.freeze["author_not_exposed_to_new_implementation"])
        self.assertTrue(self.freeze["frozen_before_improvement_implementation"])
        self.assertFalse(self.freeze["independent_benchmark"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    def test_quotes_and_request_schema(self):
        for q in self.questions:
            self.assertEqual(set(q["request"]), {"text", "actor", "scope", "mode", "as_of"})
            self.assertNotIn("cv3_", q["request"]["text"])
            self.assertEqual(set(q["evidence_sources"]), set(q["expected_quotes"]))
            for quote in q["expected_quotes"]:
                ids = q["evidence_sources"][quote]
                self.assertTrue(ids)
                self.assertTrue(any(quote in self.docs[s]["body"] or quote in " ".join(x["text"] for x in self.docs[s]["sections"]) for s in ids))
            for claim in q["rubric"]["atomic_claims"]:
                self.assertIn(claim["evidence_quote"], q["expected_quotes"])

    def test_multi_source_roles_are_gold_claims(self):
        for q in self.questions:
            if q["category"] != "multi_source":
                continue
            self.assertGreaterEqual(len(q["rubric"]["atomic_claims"]), 4)
            role_claims = [c for c in q["rubric"]["atomic_claims"] if c["key"].startswith("role_")]
            self.assertEqual(len(role_claims), 2)
            for c in role_claims:
                sid = c["accepted_source_ids"][0]
                self.assertIn(c["evidence_quote"], self.docs[sid]["body"])
                self.assertIn(c["value"], self.docs[sid]["source_role"])
            self.assertTrue(q["rubric"].get("no_single_document_satisfies_all_claims"))

    def test_insufficient_topics_and_structural_variation(self):
        expected = {"Dahlia", "Ember", "Xenon", "Yonder"}
        seen = set()
        for q in self.questions:
            if q["category"] == "insufficient":
                words = q["request"]["text"].split()
                topic = next(x for x in expected if x in words)
                seen.add(topic)
                self.assertFalse(q["answerable"])
                self.assertTrue(q["rubric"]["abstain"])
                self.assertEqual(q["expected_quotes"], [])
        self.assertEqual(seen, expected)
        multi = [q["request"]["text"] for q in self.questions if q["category"] == "multi_source"]
        conditions = [q["request"]["text"] for q in self.questions if q["category"] == "condition_exception"]
        self.assertGreaterEqual(len(set(multi)), 5)
        self.assertGreaterEqual(len(set(conditions)), 4)

    def test_private_denial_safe(self):
        for q in self.questions:
            if q["category"] == "private_boundary":
                self.assertEqual(q["request"]["actor"], "analyst_99")
                self.assertIn("denial-safe", q["request"]["text"])
                for c in q["rubric"]["atomic_claims"]:
                    self.assertTrue(all(self.docs[s]["scope"] == "shared" for s in c["accepted_source_ids"]))
                    self.assertNotIn("calibration note content", c["value"].lower())


if __name__ == "__main__":
    unittest.main()
