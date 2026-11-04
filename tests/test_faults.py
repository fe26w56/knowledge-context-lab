import tempfile
import unittest
from pathlib import Path
from context_lab.faults import run_once


class FaultExperimentTests(unittest.TestCase):
    def test_sixteen_workers_and_recovery_have_auditable_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            result=run_once(Path(temp),"test")
        self.assertTrue(result['all_pass'],result['checks'])
        raw=result['raw']
        self.assertEqual(16,len(raw['race']))
        self.assertEqual(list(range(16)),sorted(raw['head_after_retries']['content']['events']))
        self.assertEqual(16,len(raw['duplicates']))
        self.assertEqual(15,sum(r['result']['replayed'] for r in raw['duplicates']))
        self.assertEqual(raw['lost_ack']['status'],raw['lost_ack']['replay'])
        self.assertLess(raw['lost_ack']['replay']['version'],raw['lost_ack']['later']['version'])
        self.assertTrue(all(raw['private'].values()))
        self.assertEqual({'revisions':0,'heads':0,'requests':0},raw['rollback']['counts'])
        self.assertEqual(2,len(raw['recovery']['lost_revisions']))
        self.assertEqual(['post-backup-1','post-backup-2'],raw['recovery']['lost_request_ids'])
        self.assertGreater(raw['recovery']['restore_and_verify_ms'],0)
        self.assertTrue(all(raw['taskflow_stub'].values()))
        self.assertGreater(result['metrics']['elapsed_ms'],0)
