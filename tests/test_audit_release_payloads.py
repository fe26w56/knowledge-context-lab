import copy
import json
import unittest

from context_lab.retrieval_v2 import digest
from scripts.audit_release_payloads import audit_payload, condition_roots


class ReleasePayloadAuditTests(unittest.TestCase):
    def setUp(self):
        section = dict(id="section", heading="Rule", text="alpha condition", kind="decision",
                       adoption_status="adopted", valid_from="2026-01-01", valid_to=None)
        doc = dict(id="d", title="Rule", body=section["text"], scope="shared", owner=None,
                   source_url="https://example.invalid/d", sections=[section])
        self.docs = {"d": doc}
        self.lineage = {"d": ("d", "base")}
        self.original = [copy.deepcopy(doc)]
        self.query = dict(request=dict(mode="current", as_of="2026-02-01", scope="shared", actor="bot_01"),
            expected_quotes=["alpha condition"], evidence_sources={"alpha condition": ["d"]},
            accepted_source_ids=["d"], condition_quotes=["condition"], answerable=True)
        item = dict(section, document_id="d", parent_section_id="section", section_id="section~0",
                    spans=[[0, 5], [5, len(section["text"])]])
        item.pop("id")
        self.value = dict(mode="current", as_of="2026-02-01", items=[item],
            sources={"d": dict(title=doc["title"], source_url=doc["source_url"], revision=digest(doc["body"]))})

    def audit(self, method="B"):
        return audit_payload(json.dumps(self.value), self.query, self.docs, self.lineage, self.original, method)

    def test_joined_spans_and_exact_copy_grounding(self):
        self.assertTrue(self.audit()["strict_complete"])
        self.docs["g"] = copy.deepcopy(self.docs["d"])
        self.docs["g"]["id"] = "g"
        self.lineage["g"] = ("d", "exact")
        self.value["items"][0]["document_id"] = "g"
        self.value["sources"]["g"] = self.value["sources"].pop("d")
        self.assertTrue(self.audit()["strict_complete"])
        self.lineage["g"] = ("d", "near")
        self.assertFalse(self.audit()["strict_complete"])
        self.assertEqual(self.audit()["condition_wrong_source"], 1)

    def test_missing_source_and_mutated_revision_are_detected(self):
        saved = copy.deepcopy(self.value)
        self.value["sources"] = {}
        self.assertIn("source_set", self.audit()["source_errors"])
        self.value = saved
        self.value["sources"]["d"]["revision"] = "incorrect"
        self.assertIn("source_revision", self.audit()["source_errors"])

    def test_invalid_bounds_parent_and_metadata_are_detected(self):
        saved = copy.deepcopy(self.value)
        self.value["items"][0]["spans"] = [[0, 999999]]
        self.assertTrue(self.audit()["span_errors"])
        self.value = copy.deepcopy(saved)
        self.value["items"][0]["parent_section_id"] = "unknown"
        self.assertIn("unknown_parent_section", self.audit()["source_errors"])
        self.value = saved
        self.value["items"][0]["adoption_status"] = "superseded"
        self.assertTrue(self.audit()["metadata_errors"])

    def test_state_and_scope_are_independent_of_metadata_equality(self):
        self.docs["d"]["sections"][0]["adoption_status"] = "proposed"
        self.value["items"][0]["adoption_status"] = "proposed"
        self.assertEqual(self.audit()["state_violations"], 1)
        self.assertFalse(self.audit()["metadata_errors"])
        self.docs["d"].update(scope="private", owner="someone_else")
        self.assertEqual(self.audit()["scope_violations"], 1)

    def test_condition_uses_narrow_expected_source_before_global_set(self):
        self.query["accepted_source_ids"].append("other")
        self.assertEqual(condition_roots("condition", self.query), {"d"})
        self.query["obsolete_quotes"] = ["alpha condition"]
        self.assertFalse(self.audit()["strict_complete"])
        self.assertEqual(self.audit()["obsolete_hits"], 1)

    def test_full_replay_checks_body_but_does_not_claim_state_correctness(self):
        self.value["items"] = [dict(document_id="d", text=self.docs["d"]["body"])]
        result = self.audit("A")
        self.assertFalse(result["source_errors"])
        self.assertIsNone(result["strict_complete"])
        self.value["items"][0]["text"] = "tampered"
        self.assertIn("full_body", self.audit("A")["source_errors"])
