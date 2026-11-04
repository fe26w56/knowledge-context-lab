import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v3"


class CompletionFixtureV3Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.questions = json.loads((ROOT / "dev.json").read_text())["queries"] + json.loads((ROOT / "final.json").read_text())["queries"]
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}

    def test_opaque_shuffled_ids_and_counts(self):
        self.assertEqual(len(self.docs), 80)
        self.assertEqual(len(self.questions), 40)
        self.assertTrue(all(re.fullmatch(r"cv3d_[0-9a-f]{16}", i) for i in self.docs))
        self.assertTrue(all(re.fullmatch(r"cv3q_[0-9a-f]{16}", q["id"]) for q in self.questions))
        positions = [d["id"] for d in self.corpus["documents"]]
        self.assertNotEqual(positions, sorted(positions))

    def test_quotes_and_request_boundary(self):
        for q in self.questions:
            self.assertEqual(set(q["request"]), {"text", "actor", "scope", "mode", "as_of"})
            self.assertNotIn("cv3_", q["request"]["text"])
            self.assertEqual(set(q["evidence_sources"]), set(q["expected_quotes"]))
            for quote in q["expected_quotes"]:
                ids = q["evidence_sources"][quote]
                self.assertTrue(ids)
                self.assertTrue(any(quote in self.docs[s]["body"] or quote in " ".join(sec["text"] for sec in self.docs[s]["sections"]) for s in ids))

    def test_roles_and_multi_source_claim_separation(self):
        for d in self.docs.values():
            self.assertTrue(d.get("source_family"))
            self.assertTrue(d.get("source_role"))
        for q in self.questions:
            if q["category"] != "multi_source":
                continue
            families = {self.docs[s]["source_family"] for ids in q["evidence_sources"].values() for s in ids}
            self.assertGreaterEqual(len(families), 2)
            claim_docs = [set(c["accepted_source_ids"]) for c in q["rubric"]["atomic_claims"]]
            self.assertGreaterEqual(len(set.union(*claim_docs)), 2)
            self.assertTrue(q["rubric"].get("no_single_document_satisfies_all_claims"))
            self.assertGreaterEqual(len(set(q["request"]["text"].split())), 8)

    def test_topic_specific_long_tables(self):
        topics = {"Willow": ("07", "35", "percent forecast load", "same-day decision", "none"), "Xylo": ("11", "red", "severity label", "incident-commander", "declared drill"), "Quill": ("15", "90", "minutes of delay", "operator", "maintenance window"), "Rook": ("19", "missing", "owner tag", "block dispatch", "emergency route")}
        seen = set()
        for q in self.questions:
            if q["category"] != "condition_exception":
                continue
            words = q["request"]["text"].split()
            topic = words[words.index("condition") - 1]
            seen.add(topic)
            row, threshold, unit, action, exception = topics[topic]
            quote = q["condition_quotes"][0]
            for value in (row, threshold, unit, action, exception):
                self.assertIn(value, quote)
            source = self.docs[q["evidence_sources"][quote][0]]
            self.assertGreaterEqual(len(source["body"]), 5000)
            self.assertGreaterEqual(source["body"].count("|") / 4, 20)
            self.assertIn("Exception note:", source["body"])
            self.assertIn(quote, source["body"])
        self.assertEqual(seen, set(topics))

    def test_private_and_rubric_freeze(self):
        private = [q for q in self.questions if q["category"] == "private_boundary"]
        self.assertEqual(len(private), 2)
        for q in private:
            self.assertEqual(q["request"]["actor"], "analyst_99")
            self.assertIn("denial-safe", q["request"]["text"])
            for c in q["rubric"]["atomic_claims"]:
                self.assertNotIn("calibration note content", c["value"].lower())
                self.assertTrue(all(self.docs[s]["scope"] == "shared" for s in c["accepted_source_ids"]))
        self.assertTrue(self.freeze["author_not_exposed_to_new_implementation"])
        self.assertTrue(self.freeze["frozen_before_improvement_implementation"])
        self.assertFalse(self.freeze["independent_benchmark"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
