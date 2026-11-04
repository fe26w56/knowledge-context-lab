import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from context_lab.budget import ExperimentBudget
from context_lab.workflow_api import nominal_cost_bounds

spec = importlib.util.spec_from_file_location('workflow_accounting', Path(__file__).parents[1] / 'scripts/audit_workflow_accounting.py')
accounting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accounting)


class WorkflowAccountingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ledger = ExperimentBudget(self.root / 'ledger.sqlite', cap_usd='10')
        self.folder = self.root / 'runs' / 'phase2-workflow-test' / 'case' / 'arm' / 'api'
        self.folder.mkdir(parents=True)

    def add_settled(self):
        aid = 'workflow-test'
        usage = {'input_tokens': 100, 'output_tokens': 20,
                 'input_tokens_details': {'cached_tokens': 10, 'cache_write_tokens': 50}}
        request = {'input': [{'role': 'user', 'content': '{}'}]}
        self.ledger.reserve(aid, 1000000)
        self.ledger.settle(aid, 100000, {'input_tokens': 100, 'output_tokens': 20,
                                       'input_tokens_details_cached_tokens': 10})
        artifact = {'attempt_id': aid, 'status': 'ok', 'ledger_status': 'settled',
                    'usage': usage, 'conservative_cost_nanodollars': 100000,
                    'request': request,
                    'request_sha256': hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                    'nominal_cost_bounds': nominal_cost_bounds(usage)}
        path = self.folder / ('attempt-' + aid + '.json')
        path.write_text(json.dumps(artifact))
        return path

    def audit(self):
        return accounting.audit(self.ledger.path, self.root / 'runs')

    def test_old_interval_reconciles_with_default_ttl_and_retains_history(self):
        path = self.add_settled()
        before = path.read_bytes()
        self.ledger.reserve('historical-unknown', 20000000)
        self.ledger.mark_uncertain('historical-unknown')
        result = self.audit()
        self.assertEqual(result['status'], 'pass', result)
        self.assertEqual(result['historical_accounted_usd'], .02)
        self.assertEqual(path.read_bytes(), before)
        usage = json.loads(before)['usage']
        self.assertEqual(result['workflow_nominal_30m_estimate_usd'],
                         nominal_cost_bounds(usage, write_ttl='30m')['point_nanodollars'] / 1e9)

    def test_pending_without_artifact_is_not_reported_complete(self):
        self.ledger.reserve('workflow-pending', 1000000)
        self.assertEqual(self.audit()['status'], 'incomplete')

    def test_duplicate_and_missing_artifact_are_failures(self):
        path = self.add_settled()
        copy = path.with_name('attempt-copy.json')
        copy.write_bytes(path.read_bytes())
        self.assertIn('duplicate_artifact', {e['code'] for e in self.audit()['errors']})
        copy.unlink()
        path.unlink()
        self.assertIn('missing_settled_artifact', {e['code'] for e in self.audit()['errors']})

    def test_accounting_tamper_is_detected(self):
        path = self.add_settled()
        artifact = json.loads(path.read_text())
        artifact['conservative_cost_nanodollars'] = 1
        path.write_text(json.dumps(artifact))
        self.assertIn('conservative_cost_mismatch', {e['code'] for e in self.audit()['errors']})


if __name__ == '__main__':
    unittest.main()
