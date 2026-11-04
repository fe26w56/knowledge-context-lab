import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v7"
V6 = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v6"


class CompletionFixtureV7StructuralRepair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.v6corpus = json.loads((V6 / "corpus.json").read_text())
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())

    def test_validator_and_section_body_consistency(self):
        from context_lab.retrieval_v2 import validate_documents
        self.assertIsNone(validate_documents(self.corpus["documents"]))
        for doc in self.docs.values():
            self.assertTrue(doc["sections"])
            for section in doc["sections"]:
                self.assertIn(section["text"], doc["body"], doc["id"])
            self.assertTrue(any(s.get("kind") == "document_body" and s["text"] == doc["body"] for s in doc["sections"]))

    def test_questions_gold_and_rubrics_unchanged(self):
        for name in ("dev.json", "final.json"):
            current = json.loads((ROOT / name).read_text())["queries"]
            previous = json.loads((V6 / name).read_text())["queries"]
            self.assertEqual(current, previous)

    def test_mechanical_repair_accounting_and_hashes(self):
        repair = json.loads((ROOT / "STRUCTURAL_REPAIR.json").read_text())
        self.assertEqual(repair["questions_changed"], 0)
        self.assertEqual(repair["gold_changed"], 0)
        self.assertEqual(repair["rubric_changed"], 0)
        self.assertTrue(repair["semantic_fixture_not_reauthored"])
        self.assertFalse(self.freeze["frozen_before_improvement_implementation"])
        self.assertTrue(self.freeze["structural_repair_after_implementation_start"])
        self.assertTrue(self.freeze["no_baseline_or_candidate_measurement"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    def test_token_report_has_body_and_indexed_section_lengths(self):
        report = json.loads((ROOT / "TOKEN_REPORT.json").read_text())
        self.assertEqual(len(report), 80)
        self.assertTrue(all("body_tokens" in v and "section_tokens" in v for v in report.values()))
        self.assertGreater(max(v["body_tokens"] for v in report.values()), 2000)


if __name__ == "__main__":
    unittest.main()
