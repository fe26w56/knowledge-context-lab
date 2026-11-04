import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parents[1] / "fixtures" / "phase2-completion-v6"


class CompletionFixtureV6Eligibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((ROOT / "corpus.json").read_text())
        cls.questions = json.loads((ROOT / "dev.json").read_text())["queries"] + json.loads((ROOT / "final.json").read_text())["queries"]
        cls.docs = {d["id"]: d for d in cls.corpus["documents"]}
        cls.freeze = json.loads((ROOT / "FREEZE.json").read_text())

    def test_counts_and_freeze(self):
        self.assertEqual(len(self.docs), 80)
        self.assertEqual(len(self.questions), 40)
        self.assertTrue(self.freeze["frozen_before_improvement_implementation"])
        self.assertTrue(self.freeze["author_not_exposed_to_new_implementation"])
        self.assertFalse(self.freeze["independent_benchmark"])
        for name, digest in self.freeze["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    def test_all_required_sources_visible_to_actor_scope(self):
        for q in self.questions:
            source_ids = {sid for ids in q["evidence_sources"].values() for sid in ids}
            source_ids |= {sid for c in q["rubric"]["atomic_claims"] for sid in c["accepted_source_ids"]}
            for sid in source_ids:
                doc = self.docs[sid]
                # Shared docs are visible to every synthetic actor. Private docs
                # would require owner identity; v6 gold never requires one for a nonowner.
                if doc["scope"] == "private":
                    self.assertEqual(q["request"]["actor"], doc["owner"])

    def test_gold_quotes_have_temporally_eligible_sections(self):
        for q in self.questions:
            if q["category"] == "insufficient":
                self.assertEqual(q["expected_quotes"], [])
                continue
            as_of = date.fromisoformat(q["request"]["as_of"])
            for quote, source_ids in q["evidence_sources"].items():
                found = False
                for sid in source_ids:
                    for section in self.docs[sid]["sections"]:
                        if quote not in section["text"]:
                            continue
                        start = date.fromisoformat(section["valid_from"])
                        end = date.fromisoformat(section["valid_to"]) if section["valid_to"] else None
                        if q["category"] in {"current", "history"}:
                            eligible = start <= as_of and (end is None or as_of < end)
                            if q["category"] == "current":
                                eligible = eligible and section["adoption_status"] == "adopted"
                            else:
                                eligible = eligible and section["adoption_status"] == "superseded"
                            self.assertTrue(eligible, (q["id"], quote, section))
                        found = True
                self.assertTrue(found, (q["id"], quote))

    def test_history_as_of_matches_prompt_and_bounds(self):
        for q in self.questions:
            if q["category"] != "history":
                continue
            self.assertIn(q["request"]["as_of"], q["request"]["text"])
            for sid in set(x for ids in q["evidence_sources"].values() for x in ids):
                sections = [s for s in self.docs[sid]["sections"] if s["adoption_status"] == "superseded"]
                self.assertTrue(sections)
                s = sections[0]
                self.assertLess(q["request"]["as_of"], s["valid_to"])

    def test_request_schema_and_rubric_alignment(self):
        for q in self.questions:
            self.assertEqual(set(q["request"]), {"text", "actor", "scope", "mode", "as_of"})
            self.assertEqual(set(q["evidence_sources"]), set(q["expected_quotes"]))
            self.assertEqual(q["rubric"]["abstain"], not q["answerable"])
            for claim in q["rubric"]["atomic_claims"]:
                self.assertIn(claim["evidence_quote"], q["expected_quotes"])


if __name__ == "__main__":
    unittest.main()
