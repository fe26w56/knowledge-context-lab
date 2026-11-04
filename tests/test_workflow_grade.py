import unittest

from context_lab.workflow_grade import grade


def _episode(task_specs):
    tasks = []
    for task_id, actor, fields, depends_on in task_specs:
        tasks.append({"task_id": task_id, "actor": actor,
                      "output_spec": {name: {"type": "string"} for name in fields},
                      "depends_on": depends_on})
    return {"episode_id": "x", "sources": [{"source_id": "s1", "scope": "shared", "owner": "records", "body": "An adopted policy; a second excerpt.", "effective_from": "2026-01-01", "effective_to": None}], "waves": [{"wave": 1, "as_of": "2026-06-01", "available_source_ids": ["s1"], "tasks": tasks}]}


def _gold(task_fields):
    fields = {}
    for name, expected in task_fields.items():
        fields[name] = {"expected": expected, "must_be_unknown": expected is None, "exact_quotes": [] if expected is None else [{"source_id": "s1", "quote": "adopted policy"}]}
    return {"episode_id": "x", "tasks": {"t1": {"fields": fields, "required_source_ids": ["s1"], "forbidden_claims": []}}}


def _result(value, quote="adopted policy", sources=None, handoffs=None):
    return {"results": {"t1": {"as_of": "2026-06-01", "output": {"fields": {"status": {"value": value, "citations": [] if quote is None else [{"source_id": "s1", "quote": quote}]}}, "needs_more": False}, "payload": {"sources": sources or [{"source_id": "s1", "scope": "shared", "owner": "records", "text": "An adopted policy; a second excerpt."}], "predecessor_handoffs": handoffs or []}}}}


class WorkflowGradeTests(unittest.TestCase):
    def test_typed_value_and_verbatim_citation_pass(self):
        e = _episode([("t1", "a", {"status": "adopted"}, [])])
        self.assertTrue(grade(e, _gold({"status": "adopted"}), _result(" Adopted. "))["case_pass"])

    def test_bool_is_not_numeric_value_and_missing_citation_fails(self):
        e = _episode([("t1", "a", {"status": 1}, [])])
        self.assertFalse(grade(e, _gold({"status": 1}), _result(True))["case_pass"])
        self.assertFalse(grade(e, _gold({"status": 1}), _result(1, quote=None))["case_pass"])

    def test_dynamic_withheld_is_null_without_supplied_handoff(self):
        e = _episode([("t1", "a", {"status": "adopted"}, [])])
        g = _gold({"status": None})
        g["tasks"]["t1"]["fields"]["status"]["dynamic"] = {"kind": "predecessor_field", "task_id": "oracle", "field": "status"}
        self.assertTrue(grade(e, g, _result(None, quote=None, handoffs=[]))["case_pass"])

    def test_dynamic_prefers_supplied_handoff_over_oracle_value(self):
        e = _episode([("t1", "a", {"status": "adopted"}, [])])
        g = _gold({"status": None})
        g["tasks"]["t1"]["fields"]["status"]["dynamic"] = {"kind": "predecessor_field", "task_id": "oracle", "field": "status"}
        supplied = [{"fields": {"status": {"value": "proposed"}}}]
        self.assertTrue(grade(e, g, _result("proposed", quote=None, handoffs=supplied))["case_pass"])

    def test_same_source_multiple_excerpts_accepts_first_excerpt(self):
        e = _episode([("t1", "a", {"status": "adopted"}, [])])
        sources = [{"source_id": "s1", "scope": "shared", "owner": "records", "text": "An adopted policy"}, {"source_id": "s1", "scope": "shared", "owner": "records", "text": "a second excerpt"}]
        self.assertTrue(grade(e, _gold({"status": "adopted"}), _result("adopted", sources=sources))["case_pass"])

    def test_empty_quote_and_fabricated_context_quote_fail(self):
        e = _episode([("t1", "a", {"status": "adopted"}, [])])
        self.assertFalse(grade(e, _gold({"status": "adopted"}), _result("adopted", quote=""))["case_pass"])
        fabricated = [{"source_id": "s1", "scope": "shared", "owner": "records", "text": "fabricated quote"}]
        self.assertFalse(grade(e, _gold({"status": "adopted"}), _result("adopted", sources=fabricated))["case_pass"])

    def test_past_revision_not_current_available_fails(self):
        e = _episode([("t1", "a", {"status": "adopted"}, [])])
        e["sources"][0]["effective_to"] = "2026-05-01"
        self.assertFalse(grade(e, _gold({"status": "adopted"}), _result("adopted"))["case_pass"])


if __name__ == "__main__":
    unittest.main()
