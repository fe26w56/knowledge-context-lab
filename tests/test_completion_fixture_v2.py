import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v2"


class CompletionFixtureV2Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.questions = json.loads((ROOT / "dev.json").read_text())["queries"] + json.loads((ROOT / "final.json").read_text())["queries"]
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}

    def test_split_and_categories(self):
        self.assertEqual(len(self.docs), 80)
        self.assertEqual(sum(q["split"] == "dev" for q in self.questions), 20)
        self.assertEqual(sum(q["split"] == "final" for q in self.questions), 20)
        expected = {"current": 4, "history": 2, "proposal": 2, "paraphrase": 2, "condition_exception": 2, "multi_source": 3, "handoff": 2, "insufficient": 2, "private_boundary": 1}
        for split in ("dev", "final"):
            got = {}
            for q in self.questions:
                if q["split"] == split:
                    got[q["category"]] = got.get(q["category"], 0) + 1
            self.assertEqual(got, expected)

    def test_request_contract_and_quote_presence(self):
        for q in self.questions:
            self.assertEqual(set(q["request"]), {"text", "actor", "scope", "mode", "as_of"})
            self.assertNotIn("cv1_", json.dumps(q, ensure_ascii=False))
            self.assertNotIn("cv2_", q["request"]["text"])
            self.assertEqual(set(q["evidence_sources"]), set(q["expected_quotes"]))
            for quote in q["expected_quotes"]:
                source_ids = q["evidence_sources"][quote]
                self.assertTrue(source_ids)
                self.assertTrue(any(quote in self.docs[s]["body"] for s in source_ids))

    def test_provenance_and_multi_source_completeness(self):
        for d in self.docs.values():
            self.assertRegex(d["source_family"], r"^family_[0-9]{2}_[ab]$")
        for q in self.questions:
            if q["category"] != "multi_source":
                continue
            families = {d["source_family"] for ids in q["evidence_sources"].values() for sid in ids for d in [self.docs[sid]]}
            self.assertGreaterEqual(len(families), 2)
            self.assertEqual(set(q["rubric"]["required_source_families"]), families)
            self.assertTrue(q["rubric"]["no_single_document_satisfies_all_claims"])
            claim_sources = [set(c["accepted_source_ids"]) for c in q["rubric"]["atomic_claims"]]
            self.assertGreaterEqual(len(set.union(*claim_sources)), 2)

    def test_condition_values_are_exact_and_atomic(self):
        expected = {
            "Willow": ("35", "percent forecast load", "same-day decision", "none"),
            "Xylo": ("red", "severity label", "incident-commander", "declared drill"),
            "Quill": ("90", "minutes of delay", "operator", "maintenance window"),
            "Rook": ("missing", "owner tag", "block dispatch", "emergency route"),
        }
        for q in self.questions:
            if q["category"] != "condition_exception":
                continue
            topic = q["request"]["text"].split()[1].rstrip(",")
            self.assertIn(topic, expected)
            table = q["condition_quotes"][0]
            for value in expected[topic]:
                self.assertIn(value, table)
            self.assertIn(table, [c["evidence_quote"] for c in q["rubric"]["atomic_claims"]])

    def test_private_is_denial_safe(self):
        for q in self.questions:
            if q["category"] != "private_boundary":
                continue
            self.assertEqual(q["request"]["actor"], "analyst_99")
            self.assertEqual(q["request"]["scope"], "private")
            self.assertIn("denial-safe", q["request"]["text"])
            self.assertTrue(all("calibration note content" not in quote.lower() for quote in q["expected_quotes"]))
            for sid in q["rubric"]["atomic_claims"][0]["accepted_source_ids"]:
                self.assertEqual(self.docs[sid]["scope"], "shared")

    def test_rubric_and_freeze(self):
        for q in self.questions:
            self.assertEqual(q["rubric"]["abstain"], not q["answerable"])
            for c in q["rubric"]["atomic_claims"]:
                self.assertEqual(set(c), {"key", "value", "evidence_quote", "accepted_source_ids"})
                self.assertIn(c["evidence_quote"], q["expected_quotes"])
        self.assertTrue(self.freeze["author_not_exposed_to_new_implementation"])
        self.assertTrue(self.freeze["frozen_before_improvement_implementation"])
        self.assertFalse(self.freeze["independent_benchmark"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
