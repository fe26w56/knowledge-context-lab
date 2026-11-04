import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_longmemeval import public_and_gold, assert_public_clean


class LongMemEvalPrepareTest(unittest.TestCase):
    def test_separates_answer_and_original_ids(self):
        record = {"question_id": "q1", "question_type": "single-session-user", "question": "request", "question_date": "2024/01/01",
                  "answer": "secret answer", "answer_session_ids": ["orig"], "haystack_session_ids": ["orig"],
                  "haystack_dates": ["2024/01/01"], "haystack_sessions": [[{"role": "user", "content": "x"}, {"role": "assistant", "content": "y", "has_answer": True}]]}
        public, gold = public_and_gold(record, "lm-dev-00")
        assert_public_clean(public)
        self.assertNotIn("secret answer", json.dumps(public))
        self.assertNotIn("orig", json.dumps(public))
        self.assertNotIn("answer_session_ids", public)
        self.assertEqual(gold["answer"], "secret answer")
        self.assertEqual(gold["neutral_evidence_ids"], ["s0000"])

    def test_rejects_mismatched_lengths(self):
        record = {"question_id":"q1","question_type":"multi-session","question":"x","question_date":"d","answer":"a","answer_session_ids":[],"haystack_session_ids":["s"],"haystack_dates":[],"haystack_sessions":[]}
        with self.assertRaises(ValueError):
            public_and_gold(record, "lm-dev-00")


if __name__ == "__main__":
    unittest.main()
