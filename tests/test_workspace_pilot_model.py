import json
import unittest

from scripts.run_workspace_pilot_model import prepare


class PrivatePilotModelTests(unittest.TestCase):
    def setUp(self):
        self.page = {"id": "fictional", "title": "Orbit", "body": "A tentative rule.",
                     "properties": {}, "scope": "private", "owner": "reader",
                     "raw_capture": {"text": "A tentative rule.", "metadata": {"coverage": "unknown"}}}

    def test_evaluation_case_is_not_in_model_payload_and_capture_is_preserved(self):
        rows = prepare([self.page], [{"case": "evaluation-only-91", "request": "Orbit rule"}],
                       actor="reader", arms=["capture", "current"], candidate_pages=1)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("evaluation-only-91", json.dumps([r["payload"] for r in rows]))
        self.assertEqual(rows[0]["payload"]["sources"][0]["capture"], self.page["raw_capture"])
        self.assertEqual(set(rows[0]["payload"]), {"request", "sources"})

    def test_gold_fields_and_wrong_actor_are_rejected_before_model_input(self):
        with self.assertRaises(ValueError):
            prepare([self.page], [{"case": "x", "request": "Orbit", "gold": "secret answer"}],
                    actor="reader", arms=["capture"], candidate_pages=1)
        with self.assertRaises(ValueError):
            prepare([self.page], [{"case": "x", "request": "Orbit"}],
                    actor="another-reader", arms=["capture"], candidate_pages=1)
