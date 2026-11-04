import unittest

from context_lab.history_retrieval import retrieve


class HistoryRetrievalTests(unittest.TestCase):
    def test_selection_preserves_complete_turns_dates_and_roles(self):
        sources=[{'session_id':'s0','date':'2026-01-01','turns':[
            {'role':'user','content':'The plan is red.'},
            {'role':'assistant','content':'A proposal, not approval.'}]},
            {'session_id':'s1','date':'2026-02-01','turns':[
                {'role':'user','content':'The later plan is blue; approval is pending.'}]}]
        result=retrieve('later blue',sources,limit=1)
        self.assertEqual([sources[1]],result)
        result[0]['turns'][0]['content']='mutated'
        self.assertIn('pending',sources[1]['turns'][0]['content'])
        self.assertEqual(sources,retrieve('arbitrary',sources,method='full'))

    def test_missing_match_does_not_fabricate_evidence(self):
        self.assertEqual([],retrieve('zebra',[{'session_id':'s0','date':'2026','turns':[
            {'role':'user','content':'Other topic.'}]}]))
        with self.assertRaises(ValueError):retrieve('q',[],method='unknown')

    def test_turn_bm25_avoids_long_session_dilution_and_returns_original_session(self):
        long_prefix = " ".join(f"unrelated{i}" for i in range(300))
        sources = [
            {"session_id": "long", "date": "2026-01-01", "turns": [
                {"role": "user", "content": long_prefix},
                {"role": "assistant", "content": "RareSubject quasar-771 approval condition."},
            ]},
            {"session_id": "other", "date": "2026-01-02", "turns": [
                {"role": "user", "content": "CommonSubject approval condition."},
            ]},
        ]
        result = retrieve("quasar-771", sources, method="turn_bm25", limit=1)
        self.assertEqual(["long"], [item["session_id"] for item in result])
        self.assertEqual(sources[0], result[0])
        self.assertEqual("2026-01-01", result[0]["date"])
        self.assertEqual(["user", "assistant"], [turn["role"] for turn in result[0]["turns"]])

    def test_turn_bm25_does_not_change_original_bm25(self):
        sources = [{"session_id": "s", "date": "2026", "turns": [
            {"role": "user", "content": "blue release"},
        ]}]
        self.assertEqual(retrieve("blue", sources, method="bm25"), retrieve("blue", sources, method="bm25"))
