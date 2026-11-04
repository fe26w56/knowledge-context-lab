import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_lab.budget import ExperimentBudget
from context_lab.workflow_api import BudgetedClient, nominal_cost_bounds, _validate_output


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}

def reply(text='{"answer":"ok"}', input_tokens=3, output_tokens=2):
    return {"id": "resp", "status": "completed", "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}, "output_text": text}


class WorkflowApiTests(unittest.TestCase):
    def test_scalar_anyof_keeps_boolean_distinct_from_number(self):
        schema = {"type":"object", "properties":{"value":{"anyOf":[{"type":"number"},{"type":"null"}]}}, "required":["value"], "additionalProperties":False}
        _validate_output({"value":12},schema); _validate_output({"value":None},schema)
        with self.assertRaises(ValueError): _validate_output({"value":True},schema)
    def make(self, tmp):
        return BudgetedClient(ExperimentBudget(Path(tmp) / "ledger.sqlite", cap_usd="10"), Path(tmp) / "out", "secret", max_input_tokens=1_050_000, input_rate="0.55", output_rate="0.825")

    def test_success_keeps_metadata_local_and_sends_no_eval_fields(self):
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=reply()) as post:
            client = self.make(tmp); result = client.complete("packet", {"text": "evidence", "source": "s1"}, SCHEMA, "Answer from evidence", metadata={"task_id": "local"})
            sent = json.dumps(post.call_args.args[0]); self.assertNotIn("task_id", sent)
            self.assertEqual(result["status"], "ok"); self.assertEqual(result["output"], {"answer": "ok"})
            self.assertIn("local", (Path(tmp) / "out" / next(p.name for p in (Path(tmp)/"out").glob("attempt-*.json"))).read_text())

    def test_forbidden_eval_key_is_rejected_before_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self.make(tmp)
            with self.assertRaises(ValueError): client.complete("x", {"text": "x", "expected": "no"}, SCHEMA, "p")
            self.assertEqual(client.ledger.report()["attempts"], [])

    def test_parse_failure_is_settled_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=reply("not-json")):
            result = self.make(tmp).complete("packet", {"text": "e"}, SCHEMA, "p")
            self.assertEqual(result["status"], "error"); self.assertEqual(result["error_type"], "JSONDecodeError")
            self.assertIsNone(result["nominal_cost_estimate_nanodollars"])

    def test_transport_failure_retains_uncertain_reservation(self):
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", side_effect=OSError("private")):
            client = self.make(tmp); result = client.complete("packet", {"text": "e"}, SCHEMA, "p")
            self.assertEqual(result["status"], "error"); self.assertEqual(client.ledger.report()["attempts"][0]["status"], "uncertain")

    def test_floor_and_model_are_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): BudgetedClient(ExperimentBudget(Path(tmp)/"l", cap_usd="10"), Path(tmp)/"a", "x", input_rate="0.1", max_input_tokens=1_050_000)
            with self.assertRaises(ValueError): BudgetedClient(ExperimentBudget(Path(tmp)/"l2", cap_usd="10"), Path(tmp)/"b", "x", max_input_tokens=10)

    def test_nested_usage_is_flattened_for_ledger_but_preserved_in_artifact(self):
        nested = reply(); nested["usage"]["input_tokens_details"] = {"cached_tokens": 1, "cache_write_tokens": 2, "cache_write_tokens_details": {"ttl_30m_tokens": 2}}
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=nested):
            client = self.make(tmp); result = client.complete("packet", {"text": "e"}, SCHEMA, "p")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["usage"]["input_tokens_details"]["cache_write_tokens_details"]["ttl_30m_tokens"], 2)
            self.assertIn("input_tokens_details_cached_tokens", client.ledger.report()["attempts"][0]["usage"])

    def test_schema_violation_is_error_after_usage_settles(self):
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=reply('{"wrong":true}')):
            client = self.make(tmp); result = client.complete("packet", {"text": "e"}, SCHEMA, "p")
            self.assertEqual(result["status"], "error"); self.assertEqual(result["error_type"], "ValueError")
            self.assertEqual(client.ledger.report()["attempts"][0]["status"], "settled")

    def test_missing_write_detail_returns_interval_not_zero(self):
        result = nominal_cost_bounds({"input_tokens": 1000, "output_tokens": 10,
                                      "input_tokens_details": {"cached_tokens": 100}})
        self.assertIsNone(result["point_nanodollars"])
        self.assertLess(result["lower_nanodollars"], result["upper_nanodollars"])
        self.assertIn("unavailable", result["reason"])

    def test_documented_default_lifetime_prices_observed_writes(self):
        usage = {"input_tokens": 1000, "output_tokens": 10,
                 "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 200}}
        self.assertIsNone(nominal_cost_bounds(usage)["point_nanodollars"])
        self.assertEqual(nominal_cost_bounds(usage, write_ttl="30m")["point_nanodollars"], 101000)
        self.assertEqual(nominal_cost_bounds(usage, write_ttl="12h")["point_nanodollars"], 126000)

    def test_source_first_changes_order_only(self):
        payload = {"actor": "one", "sources": [{"text": "common evidence"}], "request": "question"}
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=reply()) as post:
            client = self.make(tmp)
            client.complete("answer", payload, SCHEMA, "p", source_first=True)
            encoded = post.call_args.args[0]["input"][1]["content"]
            self.assertTrue(encoded.startswith('{"sources":'))
            self.assertEqual(json.loads(encoded), payload)

    def test_explicit_boundary_preserves_all_content_and_uses_inherited_ttl(self):
        payload = {"actor": "one", "sources": [{"text": "common evidence"}], "request": "question"}
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=reply()) as post:
            self.make(tmp).complete("answer", payload, SCHEMA, "p", source_first=True, cache_boundary=True)
            content = post.call_args.args[0]["input"][1]["content"]
            combined = {}
            for item in content:combined.update(json.loads(item["text"]))
            self.assertEqual(combined, payload)
            self.assertEqual(content[0]["prompt_cache_breakpoint"], {"mode":"explicit"})
            self.assertNotIn("prompt_cache_breakpoint", content[1])

    def test_short_lifetime_split_is_exact_and_long_uses_long_rates(self):
        short = nominal_cost_bounds({"input_tokens": 1000, "output_tokens": 10,
            "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 200,
                                      "cache_write_tokens_details": {"ttl_30m_tokens": 50, "ttl_12h_tokens": 150}}})
        self.assertEqual(short["lower_nanodollars"], short["upper_nanodollars"])
        self.assertEqual(short["point_nanodollars"], short["lower_nanodollars"])
        self.assertEqual(short["point_nanodollars"], 119750)
        long = nominal_cost_bounds({"input_tokens": 300000, "output_tokens": 10,
            "input_tokens_details": {"cached_tokens": 1000, "cache_write_tokens": 2000,
                                      "cache_write_tokens_details": {"ttl_30m_tokens": 1000, "ttl_12h_tokens": 1000}}})
        self.assertEqual(long["lower_nanodollars"], long["upper_nanodollars"])
        self.assertEqual(long["point_nanodollars"], 60177500)

    def test_reasoning_details_are_preserved_without_double_counting(self):
        usage = {"input_tokens": 10, "output_tokens": 20,
                 "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                 "output_tokens_details": {"reasoning_tokens": 7}}
        result = nominal_cost_bounds(usage)
        self.assertEqual(result["point_nanodollars"], result["lower_nanodollars"])
        self.assertEqual(result["point_nanodollars"], result["upper_nanodollars"])
        self.assertEqual(result["point_nanodollars"], 11000)

    def test_invalid_schema_is_rejected_before_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self.make(tmp)
            invalid = {"type": "object", "properties": {"answer": {"type": "string"}},
                       "required": [], "additionalProperties": False}
            with self.assertRaises(ValueError): client.complete("x", {"text": "e"}, invalid, "p")
            self.assertEqual(client.ledger.report()["attempts"], [])

    def test_nullable_enum_output_and_pre_request_trace(self):
        schema = {"type": "object", "properties": {
            "answer": {"type": ["string", "null"], "enum": [None, "ok"]}},
            "required": ["answer"], "additionalProperties": False}
        with tempfile.TemporaryDirectory() as tmp, patch("context_lab.workflow_api._post", return_value=reply('{"answer":null}')):
            client = self.make(tmp); result = client.complete("packet", {"text": "e"}, schema, "p", metadata={"source_version": "s1"})
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["source_version"], "s1")
            self.assertTrue(result["request_sha256"])
            self.assertFalse(list((Path(tmp) / "out").glob("*.pending.json")))

