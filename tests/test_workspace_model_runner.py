import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("workspace_model_runner", Path(__file__).parents[1] / "scripts/run_workspace_model.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ClientStub:
    calls = 0
    def __init__(self, *args, **kwargs):
        pass
    def complete(self, kind, payload, schema, prompt, **kwargs):
        type(self).calls += 1
        return {"status": "ok", "payload": payload, "metadata": kwargs["metadata"]}


class WorkspaceModelRunnerTests(TestCase):
    def test_success_status_runs_all_pairs_and_resume_reuses_without_new_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(output=root / "first", fixture=Path("fixtures/phase2-migration-v2"),
                split="dev", arms=["raw", "current"], candidate_pages=6, live=True,
                ledger=root / "mock-budget.sqlite", key_file=root / "unused", resume_from=None)
            ClientStub.calls = 0
            with patch.object(runner, "BudgetedClient", ClientStub), patch.object(runner, "read_key", return_value="mock-only"):
                runner.run(args)
                self.assertEqual(16, ClientStub.calls)
                summary = json.loads((args.output / "summary.json").read_text())
                self.assertEqual(16, summary["successful"])
                args.resume_from = args.output
                args.output = root / "second"
                runner.run(args)
                self.assertEqual(16, ClientStub.calls)
                resumed = json.loads((args.output / "summary.json").read_text())
                self.assertEqual(0, resumed["new_attempts"])
                self.assertEqual(16, resumed["reused_successful_responses"])
