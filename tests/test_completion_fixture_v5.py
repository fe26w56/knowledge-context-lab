import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v5"


class CompletionFixtureV5Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.questions = json.loads((ROOT / "dev.json").read_text())["queries"] + json.loads((ROOT / "final.json").read_text())["queries"]
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())
        cls.tokens = json.loads((ROOT / "TOKEN_REPORT.json").read_text())

    def test_bundle_and_hashes(self):
        self.assertEqual(len(self.docs), 80)
        self.assertEqual(len(self.questions), 40)
        self.assertTrue(any(v["tokens"] > 2000 for v in self.tokens.values()))
        self.assertTrue(self.freeze["author_not_exposed_to_new_implementation"])
        self.assertTrue(self.freeze["frozen_before_improvement_implementation"])
        self.assertFalse(self.freeze["independent_benchmark"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    def test_all_gold_quotes_are_visible(self):
        for q in self.questions:
            self.assertEqual(set(q["request"]), {"text", "actor", "scope", "mode", "as_of"})
            self.assertEqual(set(q["evidence_sources"]), set(q["expected_quotes"]))
            for quote in q["expected_quotes"]:
                self.assertTrue(any(quote in self.docs[s]["body"] or quote in " ".join(x["text"] for x in self.docs[s]["sections"]) for s in q["evidence_sources"][quote]))
            for c in q["rubric"]["atomic_claims"]:
                self.assertIn(c["evidence_quote"], q["expected_quotes"])

    def test_multi_source_requested_roles_and_distinct_facts(self):
        for q in self.questions:
            if q["category"] != "multi_source":
                continue
            self.assertGreaterEqual(len(q["rubric"]["atomic_claims"]), 4)
            role_claims = [c for c in q["rubric"]["atomic_claims"] if c["key"].startswith("role_")]
            self.assertEqual(len(role_claims), 2)
            self.assertTrue(all(c["evidence_quote"] in q["expected_quotes"] for c in role_claims))
            self.assertTrue(q["rubric"].get("no_single_document_satisfies_all_claims"))
            if "Zephyr" in q["request"]["text"] or "Topaz" in q["request"]["text"]:
                self.assertIn("office hours", q["request"]["text"])
                self.assertTrue(any("office hours" in x.lower() for x in q["expected_quotes"]))
            if "Aster" in q["request"]["text"]:
                self.assertIn("escalation", q["request"]["text"])
                self.assertTrue(any("escalation" in x.lower() for x in q["expected_quotes"]))

    def test_named_insufficient_and_required_missing_fields(self):
        expected = {"Dahlia", "Ember", "Xenon", "Yonder"}
        seen = set()
        for q in self.questions:
            if q["category"] == "insufficient":
                topic = next(t for t in expected if t in q["request"]["text"])
                seen.add(topic)
                self.assertFalse(q["answerable"])
                self.assertEqual(q["expected_quotes"], [])
                self.assertEqual(q["rubric"]["missing_information"], ["threshold", "action", "exception"])
                self.assertIn("missing", q["rubric"]["notes"])
        self.assertEqual(seen, expected)

    def test_handoff_history_and_private_boundaries(self):
        for q in self.questions:
            if q["category"] == "handoff" and "Beryl" in q["request"]["text"]:
                self.assertTrue(any(c["key"] == "responsibility_until_receipt" for c in q["rubric"]["atomic_claims"]))
            if q["category"] == "handoff" and "Cinder" in q["request"]["text"]:
                self.assertIn("rollback-marker", q["request"]["text"])
            if q["category"] == "history":
                self.assertRegex(q["request"]["text"], r"as of 2026-08-\d{2}")
                self.assertIn("as of", q["rubric"]["atomic_claims"][0]["value"].lower())
            if q["category"] == "private_boundary":
                self.assertEqual(q["request"]["scope"], "shared")
                self.assertTrue(q["rubric"]["access_boundary"]["private_content_excluded"])
                self.assertTrue(all(self.docs[s]["scope"] == "shared" for c in q["rubric"]["atomic_claims"] for s in c["accepted_source_ids"]))


if __name__ == "__main__":
    unittest.main()
