import json
from pathlib import Path
import tempfile
import unittest

from context_lab.budget import BudgetExceeded, ExperimentBudget, token_cost
from context_lab.stability_api import API_URL, COUNT_URL, CountedClient


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def response(input_tokens=10, output_tokens=5):
    return {"id": "resp_test", "model": "gpt-6-luna", "status": "completed",
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "output_text": json.dumps({"answer": "ok"})}


class StabilityApiTests(unittest.TestCase):
    def client(self, root, transport, cap="10"):
        ledger = ExperimentBudget(Path(root) / "ledger.sqlite", cap_usd=cap)
        return CountedClient(ledger, Path(root) / "out", "secret-in-memory", transport=transport), ledger

    def test_missing_or_tampered_count_fails_closed_without_generation(self):
        calls = []
        def transport(body, url, key):
            calls.append(url)
            return {} if url == COUNT_URL else response()
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.client(tmp, transport)
            with self.assertRaises(ValueError): client.complete("p", {"x": 1}, SCHEMA)
        self.assertEqual(calls, [COUNT_URL])

    def test_preflight_payload_and_reservation_exist_before_generation(self):
        seen = []
        root = None
        def transport(body, url, key):
            seen.append((url, body))
            if url == API_URL:
                self.assertTrue(list(Path(root, "out").glob("*.pending.json")))
                return response()
            return {"input_tokens": 100}
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp
            client, ledger = self.client(tmp, transport)
            result = client.complete("developer", {"x": "y"}, SCHEMA)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(ledger.report()["attempts"][0]["status"], "settled")
        self.assertEqual([x[0] for x in seen], [COUNT_URL, API_URL])
        self.assertEqual(seen[0][1]["input"], seen[1][1]["input"])
        self.assertEqual(seen[0][1]["text"], seen[1][1]["text"])

    def test_generation_failure_retains_uncertain_reservation_and_does_not_retry(self):
        calls = []
        def transport(body, url, key):
            calls.append(url)
            if url == COUNT_URL: return {"input_tokens": 10}
            raise RuntimeError("network")
        with tempfile.TemporaryDirectory() as tmp:
            client, ledger = self.client(tmp, transport, cap="0.003")
            result = client.complete("p", {"x": 1}, SCHEMA)
            self.assertEqual(result["status"], "error")
            self.assertEqual(ledger.report()["attempts"][0]["status"], "uncertain")
            with self.assertRaises(BudgetExceeded): client.complete("p2", {"x": 2}, SCHEMA)
        self.assertEqual(calls.count(API_URL), 1)

    def test_budget_rejection_happens_before_generation(self):
        calls = []
        def transport(body, url, key):
            calls.append(url)
            return {"input_tokens": 100} if url == COUNT_URL else response()
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.client(tmp, transport, cap="0.001")
            with self.assertRaises(BudgetExceeded): client.complete("p", {"x": 1}, SCHEMA)
        self.assertEqual(calls, [COUNT_URL])

    def test_actual_input_overshoot_halts_future_attempts(self):
        calls = []
        def transport(body, url, key):
            calls.append(url)
            if url == COUNT_URL: return {"input_tokens": 10}
            return response(input_tokens=2000)
        with tempfile.TemporaryDirectory() as tmp:
            client, ledger = self.client(tmp, transport)
            result = client.complete("p", {"x": 1}, SCHEMA)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["metadata"]["ledger_status"], "halted_input_overshoot")
            report = ledger.report()
            self.assertTrue(report["halted"])
            self.assertEqual(report["accounted"], token_cost(2000, "0.55") + token_cost(5, "0.825"))
            with self.assertRaises(BudgetExceeded): client.complete("p2", {"x": 2}, SCHEMA)
        self.assertEqual(calls.count(API_URL), 1)

    def test_count_must_be_integer_and_cache_is_payload_bound(self):
        calls = []
        def transport(body, url, key):
            calls.append((url, body))
            return {"input_tokens": True} if url == COUNT_URL else response()
        with tempfile.TemporaryDirectory() as tmp:
            client, _ = self.client(tmp, transport)
            with self.assertRaises(ValueError): client.complete("p", {"x": 1}, SCHEMA)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
