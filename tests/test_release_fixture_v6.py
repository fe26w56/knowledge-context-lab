import hashlib, json, re, unittest
from pathlib import Path
from context_lab.evaluate import validate_inputs

ROOT=Path(__file__).parents[1]; FIX=ROOT/"fixtures/phase2-release-v6"

class ReleaseFixtureV6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=json.loads((FIX/"corpus.json").read_text()); cls.g=json.loads((FIX/"grading.json").read_text()); cls.f=json.loads((FIX/"FREEZE.json").read_text()); cls.q={s:json.loads((FIX/f"{s}.json").read_text())["queries"] for s in ("dev","final")}; cls.docs={d["id"]:d for d in cls.c["documents"]}
    def test_freeze_and_schema(self):
        self.assertEqual("fixtures/phase2-release-v5",self.f["derived_from"]); self.assertTrue(self.f["review_fix"]); self.assertTrue(self.f["frozen_before_valid_measurement"]); self.assertTrue(self.f["author_blind_to_improvement_implementation"])
        self.assertEqual({"dev":20,"final":20},self.f["question_counts"])
        for n,h in self.f["sha256"].items(): self.assertEqual(h,hashlib.sha256((FIX/n).read_bytes()).hexdigest())
        for s in ("dev","final"): validate_inputs(self.c,{"queries":self.q[s]})
    def test_current_and_history_have_eligible_evidence(self):
        for q in self.q["dev"]+self.q["final"]:
            self.assertEqual(set(q["request"]),{"text","actor","scope","mode","as_of"})
            for quote in q["expected_quotes"]:
                ids=q.get("evidence_sources",{}).get(quote,q["accepted_source_ids"]); found=False
                for sid in ids:
                    d=self.docs[sid]
                    if d["scope"]=="private" and d["owner"]!=q["request"]["actor"]: continue
                    for sec in d["sections"]:
                        if quote not in sec["text"]: continue
                        valid=q["request"]["mode"]=="search" or (q["request"]["mode"]=="current" and sec["adoption_status"]=="adopted") or (q["request"]["mode"]=="history" and sec["adoption_status"]=="superseded")
                        valid=valid and sec["valid_from"]<=q["request"]["as_of"] and (sec["valid_to"] is None or q["request"]["as_of"]<sec["valid_to"])
                        found |= valid
                self.assertTrue(found,(q["id"],quote))
    def test_private_question_matches_canary_topic_and_nonowner(self):
        for q in self.q["dev"]+self.q["final"]:
            if q["category"] != "private_boundary": continue
            self.assertFalse(q["accepted_source_ids"]); self.assertTrue(q["forbidden_quotes"])
            entries=[v for v in self.g["private"].values() if v["canary"] in q["forbidden_quotes"]]
            self.assertEqual(1,len(entries)); entry=entries[0]; source=self.docs[entry["id"]]
            self.assertIn(source["title"].split()[0],q["request"]["text"]); self.assertNotEqual(entry["owner"],q["request"]["actor"])
    def test_no_gold_in_request_and_exact_clone_ids(self):
        for q in self.q["dev"]+self.q["final"]:
            self.assertNotIn("expected_quotes",q["request"]); self.assertNotIn("accepted_source_ids",q["request"])
        self.assertTrue(all(re.fullmatch(r"v4_[0-9a-f]{16}",d["id"]) for d in self.c["documents"]))

if __name__=="__main__": unittest.main()
