import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from context_lab.budget import ExperimentBudget
import scripts.run_stability_model as runner


class FakeAuthor:
    @staticmethod
    def generate(size, seed, order_seed):
        return [{"id": "s1", "title": "S", "project": "p", "status": "current",
                 "scope": "shared", "owner": "team", "updated_at": "2026-11-03",
                 "body": "# S\n\n## Fact\nA fact."}]


class FakeIndex:
    def __init__(self, sources, counter):
        pass

    def retrieve(self, request, *, method, budget):
        return {"sources": [{"id": "s1", "title": "S", "project": request.project,
                             "status": "current", "updated_at": "2026-11-03", "body": "A fact."}],
                "coverage": "selected", "budget_exceeded": False,
                "omitted_for_budget": False}


class FakeClient:
    instances = []
    fail_estimate_at = None
    fail_complete_at = None

    def __init__(self, ledger, output_dir, api_key):
        self.ledger = ledger
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.estimates = []
        self.completes = []
        FakeClient.instances.append(self)

    def estimate(self, prompt, payload, schema, max_output_tokens):
        self.estimates.append(payload)
        if FakeClient.fail_estimate_at and len(self.estimates) == FakeClient.fail_estimate_at:
            raise ValueError("count failed")
        return {"count": 100, "input_bound": 1124, "reservation_nanodollars": 100_000,
                "count_request_sha256": "count-hash"}

    def complete(self, prompt, payload, schema, max_output_tokens, metadata):
        self.completes.append(metadata)
        if FakeClient.fail_complete_at and len(self.completes) == FakeClient.fail_complete_at:
            return {"status": "error", "usage": None, "request_sha256": "r"}
        return {"status": "ok", "usage": {"input_tokens": 100, "output_tokens": 5},
                "request_sha256": "r", "count_request_sha256": "c"}


class StabilityRunnerTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        FakeClient.fail_estimate_at = None
        FakeClient.fail_complete_at = None

    def fixture_and_selection(self, root):
        fixture = Path(root) / "fixture"
        fixture.mkdir()
        (fixture / "FREEZE.json").write_text(json.dumps({"hashes": {}}))
        cases = [{"id": f"i{i}", "project": "p", "mode": "current",
                  "variants": [f"question {i}"], "answerable": True} for i in range(12)]
        (fixture / "final.json").write_text(json.dumps(cases))
        selection = Path(root) / "selection.json"
        code_files = ["src/context_lab/stability_retrieval.py", "src/context_lab/token_retrieval.py",
                      "src/context_lab/history_retrieval.py", "scripts/evaluate_token_growth.py", "scripts/evaluate_stability.py"]
        selection.write_text(json.dumps({
            "fixture_freeze_sha256": runner.sha(fixture / "FREEZE.json"),
            "code_sha256": {name: runner.sha(runner.ROOT / name) for name in code_files},
            "live_code_sha256": {name: runner.sha(runner.ROOT / name) for name in ["scripts/run_stability_model.py", "src/context_lab/stability_api.py"]},
            "selected_method": "canonical_2000"}))
        key = Path(root) / "key.env"
        key.write_text("OPENAI_API_KEY=mock-only\n")
        return fixture, selection, key

    def run_main(self, root, cap="0.45"):
        fixture, selection, key = self.fixture_and_selection(root)
        ledger_path = Path(root) / "ledger.sqlite"
        ExperimentBudget(ledger_path, cap_usd="10")
        output = Path(root) / "run"
        argv = ["runner", "--fixture", str(fixture), "--selection", str(selection), "--output", str(output),
                "--ledger", str(ledger_path), "--key-file", str(key), "--max-additional-usd", cap]
        with patch.object(runner, "load_author", return_value=FakeAuthor), \
             patch.object(runner, "StabilityIndex", FakeIndex), \
             patch.object(runner, "CountedClient", FakeClient), \
             patch("sys.argv", argv):
            runner.main()
        return output

    def test_budget_preflight_stops_before_generation(self):
        with tempfile.TemporaryDirectory() as root:
            # 24*0.10 USD per round exceeds the explicitly tiny cap.
            original = FakeClient.estimate
            FakeClient.estimate = lambda self, *args: {"count": 100, "input_bound": 1124, "reservation_nanodollars": 100_000_000, "count_request_sha256": "c"}
            try:
                output = self.run_main(root, cap="0.05")
            finally:
                FakeClient.estimate = original
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "stopped_before_generation")
            self.assertEqual(FakeClient.instances[0].completes, [])

    def test_count_failure_has_no_generation(self):
        FakeClient.fail_estimate_at = 2
        with tempfile.TemporaryDirectory() as root:
            output = self.run_main(root)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "stopped_before_generation")
            self.assertEqual(summary["completed_estimates"], 1)
            self.assertEqual(FakeClient.instances[0].completes, [])

    def test_same_payloads_are_allowed_and_arms_are_interleaved(self):
        with tempfile.TemporaryDirectory() as root:
            output = self.run_main(root)
            client = FakeClient.instances[0]
            self.assertEqual(len(client.estimates), 24)
            self.assertEqual(len(client.completes), 120)
            for i in range(0, len(client.completes), 2):
                self.assertEqual({client.completes[i]["arm"], client.completes[i + 1]["arm"]}, {"legacy", "canonical_2000"})
            self.assertTrue((output / "preflight.json").exists())

    def test_response_failure_persists_partial_results_and_stops(self):
        FakeClient.fail_complete_at = 3
        with tempfile.TemporaryDirectory() as root:
            output = self.run_main(root)
            summary = json.loads((output / "summary.json").read_text())
            results = json.loads((output / "results.json").read_text())
            self.assertEqual(summary["status"], "partial")
            self.assertEqual(len(results), 3)
            self.assertEqual(results[-1]["response"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
