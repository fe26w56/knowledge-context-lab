import json
import unittest
from context_lab.evaluate import score_payload


class EvidenceScoringTests(unittest.TestCase):
    def test_metadata_and_cross_item_concatenation_are_not_evidence(self):
        payload = json.dumps({"items": [{"title": "required fact", "text": "first"}, {"text": "second"}]})
        found, _ = score_payload(payload, ["required fact", "first\nsecond", "first"], [])
        self.assertEqual(found, [False, False, True])

    def test_source_envelope_does_not_supply_page_evidence(self):
        payload = json.dumps({"items": [{"text": "metadata-only\n<content>\nsource fact\n</content>\nother metadata"}]})
        found, _ = score_payload(payload, ["metadata-only", "source fact"], [])
        self.assertEqual(found, [False, True])

    def test_scope_leak_checks_warning_and_metadata(self):
        payload = json.dumps({"items": [{"source_url": "private-marker", "text": "public"}], "warnings": ["secret-marker"]})
        _, leaked = score_payload(payload, [], ["private-marker", "secret-marker"])
        self.assertEqual(leaked, [True, True])
