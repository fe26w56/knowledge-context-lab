import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v1"


class CompletionFixtureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.dev = json.loads((ROOT / "dev.json").read_text())["queries"]
        cls.final = json.loads((ROOT / "final.json").read_text())["queries"]
        cls.grading = json.loads((ROOT / "grading.json").read_text())
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}
        cls.questions = cls.dev + cls.final

    def test_counts_and_distribution(self):
        self.assertEqual(len(self.docs), 80)
        self.assertEqual(len(self.dev), 20)
        self.assertEqual(len(self.final), 20)
        expected = {"current": 4, "history": 2, "proposal": 2, "paraphrase": 2,
                    "condition_exception": 2, "multi_source": 3, "handoff": 2,
                    "insufficient": 2, "private_boundary": 1}
        for split in (self.dev, self.final):
            got = {}
            for q in split:
                got[q["category"]] = got.get(q["category"], 0) + 1
            self.assertEqual(got, expected)

    def test_document_metadata_is_explicit_and_opaque(self):
        ids = set(self.docs)
        self.assertEqual(len(ids), 80)
        for doc in self.docs.values():
            self.assertRegex(doc["id"], r"^cv1_doc_[0-9]{2}[ab]$")
            self.assertTrue(doc["title"])
            self.assertRegex(doc["source_url"], r"^https://example\.invalid/")
            self.assertRegex(doc["recorded_at"], r"^2026-08-[0-9]{2}$")
            self.assertRegex(doc["verified_at"], r"^2026-08-[0-9]{2}$")
            self.assertIn(doc["scope"], {"shared", "private"})
            self.assertTrue(doc["owner"])
            self.assertTrue(doc["sections"])

    def test_request_has_only_allowed_fields_and_no_gold_ids(self):
        allowed = {"text", "actor", "scope", "mode", "as_of"}
        for q in self.questions:
            self.assertEqual(set(q["request"]), allowed)
            self.assertTrue(q["request"]["text"])
            self.assertIn(q["request"]["mode"], {"current", "history", "search"})
            self.assertRegex(q["request"]["as_of"], r"^2026-08-[0-9]{2}$")
            self.assertNotRegex(q["request"]["text"], r"cv1_(?:doc|q)_")

    def test_quotes_and_evidence_sources_are_real(self):
        for q in self.questions:
            for quote in q["expected_quotes"] + q["condition_quotes"] + q["obsolete_quotes"] + q["forbidden_quotes"]:
                # Forbidden/obsolete strings are allowed to be answer-policy text,
                # but every gold expected quote must occur in an accepted document.
                if quote in q["expected_quotes"]:
                    self.assertIn(quote, "\n".join(self.docs[s]["body"] for s in q["evidence_sources"][quote]))
                    self.assertTrue(q["evidence_sources"][quote])
                    for sid in q["evidence_sources"][quote]:
                        self.assertIn(sid, self.docs)
            self.assertEqual(set(q["evidence_sources"]), set(q["expected_quotes"]))

    def test_rubric_is_machine_evaluable(self):
        for q in self.questions:
            rubric = q["rubric"]
            self.assertIsInstance(rubric["atomic_claims"], list)
            self.assertIsInstance(rubric["abstain"], bool)
            self.assertEqual(rubric["abstain"], not q["answerable"])
            for claim in rubric["atomic_claims"]:
                self.assertEqual(set(claim), {"key", "value", "evidence_quote", "accepted_source_ids"})
                self.assertIn(claim["evidence_quote"], q["expected_quotes"])
                self.assertTrue(set(claim["accepted_source_ids"]).issubset(self.docs))
        for q in self.questions:
            if q["category"] == "multi_source":
                self.assertGreaterEqual(len(q["expected_quotes"]), 2)
                self.assertTrue(all(len(q["evidence_sources"][quote]) >= 1 for quote in q["expected_quotes"]))

    def test_insufficient_and_private_boundaries(self):
        for q in self.questions:
            if q["category"] == "insufficient":
                self.assertFalse(q["answerable"])
                self.assertEqual(q["expected_quotes"], [])
                self.assertTrue(q["rubric"]["abstain"])
            if q["category"] == "private_boundary":
                self.assertEqual(q["request"]["scope"], "private")
                self.assertIn("nonowner", q["request"]["text"])
                self.assertTrue(q["forbidden_quotes"])

    def test_freeze_hashes_and_provenance(self):
        self.assertTrue(self.freeze["author_not_exposed_to_new_implementation"])
        self.assertTrue(self.freeze["frozen_before_improvement_implementation"])
        self.assertFalse(self.freeze["independent_benchmark"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(self.freeze["corpus_documents"], len(self.docs))

    def test_condition_questions_have_table_contract(self):
        for q in self.questions:
            if q["category"] == "condition_exception":
                topic = q["id"].replace("cv1q_", "")
                primary = self.docs[f"cv1_doc_{int(topic):02d}a"]
                self.assertIn("threshold", primary["body"])
                self.assertIn("unit", primary["body"])
                self.assertIn("exception", primary["body"])


if __name__ == "__main__":
    unittest.main()
