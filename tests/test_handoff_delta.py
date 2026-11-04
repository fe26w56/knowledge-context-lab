import unittest
from context_lab.handoff_delta import apply_update, make_update, snapshot_digest


class HandoffDeltaTest(unittest.TestCase):
    ctx = {"principal":"reader-1","scope":"pilot"}

    def transfer(self,old,new):
        base=snapshot_digest(old,**self.ctx)
        return make_update(old,new,expected_base=base,**self.ctx)

    def test_modification_keeps_complete_current_lines_and_purges_source(self):
        old={"plan":"見出し\r\n5 kg until Friday\r\n末尾","gone":"forbidden-history"}
        new={"plan":"見出し\r\n2 g except Friday\r\n末尾","extra":"改訂\n"}
        pkt=self.transfer(old,new)
        self.assertNotIn("forbidden-history",str(pkt))
        self.assertNotIn("5 kg",str(pkt))
        self.assertEqual("2 g except Friday\r\n",pkt["patches"]["plan"]["text"])
        self.assertEqual(apply_update(old,pkt,**self.ctx),new)

    def test_stale_or_wrong_principal_falls_back_without_disclosing_old(self):
        old={"prior":"formerly visible"}; new={"current":"open"}
        base=snapshot_digest(old,principal="other",scope="pilot")
        pkt=make_update(old,new,expected_base=base,**self.ctx)
        self.assertEqual("snapshot",pkt["mode"])
        self.assertNotIn("prior",str(pkt))
        self.assertEqual(apply_update(None,pkt,**self.ctx),new)
        with self.assertRaises(ValueError):
            apply_update(None,pkt,principal="other",scope="pilot")

    def test_bad_patch_or_wrong_revision_leaves_prior_state_untouched(self):
        old={"doc":"before"}; new={"doc":"after\n"}
        pkt=self.transfer(old,new)
        with self.assertRaises(ValueError):
            apply_update({},pkt,**self.ctx)
        pkt["patches"]["doc"]["text"]="wrong"
        with self.assertRaises(ValueError):
            apply_update(old,pkt,**self.ctx)
        self.assertEqual(old,{"doc":"before"})

    def test_newlines_and_empty_document_transitions(self):
        for before in ("","A","A\n","A\nB\n","X\nA\nB\n"):
            for after in ("","X","A\nB","X\nA\nB\n","A\n"):
                old={"doc":before};new={"doc":after}
                self.assertEqual(new,apply_update(old,self.transfer(old,new),**self.ctx))


    def test_separated_updates_omit_unchanged_middle_and_reject_overlap(self):
        middle = "unchanged section " * 80 + "\n"
        old = {"doc": "old start\n" + middle + "old end\n"}
        new = {"doc": "new start\n" + middle + "new end\n"}
        packet = self.transfer(old, new)
        hunks = packet["patches"]["doc"]["hunks"]
        self.assertEqual(len(hunks), 2)
        self.assertNotIn("unchanged section", str(hunks))
        self.assertEqual(apply_update(old, packet, **self.ctx), new)
        hunks[1]["start"] = hunks[0]["start"]
        with self.assertRaisesRegex(ValueError, "offsets"):
            apply_update(old, packet, **self.ctx)
        self.assertTrue(old["doc"].startswith("old start"))
