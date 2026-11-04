import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('history_runner',ROOT/'scripts/run_history_model.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class StubClient:
    calls=[]
    fail=False
    def __init__(self,*args,**kwargs):pass
    def complete(self,kind,payload,schema,prompt,**kwargs):
        self.calls.append(payload)
        assert set(payload)=={'request','as_of','sources'}
        return {'status':'error' if self.fail else 'ok','attempt_id':str(len(self.calls)),
                'usage':{'input_tokens':10,'output_tokens':5},'latency_seconds':0.1,
                'request_sha256':'stub','payload':payload,
                'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                'schema_sha256':hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),
                'nominal_cost_estimate_nanodollars':1,'conservative_cost_nanodollars':2,
                'nominal_cost_bounds':{'lower_nanodollars':1,'upper_nanodollars':1}}


class HistoryRunnerTests(unittest.TestCase):
    def execute(self,fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=Path.cwd()
            try:
                os.chdir(root)
                data=root/'work/data';data.mkdir(parents=True)
                records=[{'evaluator_case_key':str(i),'request':'blue','as_of':'2026',
                    'sources':[{'session_id':'s0','date':'2026','turns':[{'role':'user','content':'blue'}]}]}
                    for i in range(3)]
                source=data/'dev-public-inputs.json';source.write_text(json.dumps(records))
                freeze=root/'fixtures/phase2-longmemeval-selection-v1';freeze.mkdir(parents=True)
                (freeze/'FREEZE.json').write_text(json.dumps({'prepared_hashes':{source.name:runner.sha(source)}}))
                for name in ('src/context_lab/history_retrieval.py','src/context_lab/workflow_api.py',
                             'src/context_lab/budget.py','scripts/run_history_model.py'):
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text((ROOT/name).read_text())
                args=SimpleNamespace(output=root/'runs/first',work=root/'work/first',data=data,split='dev',
                    methods=['full','overlap'],limit=6,workers=2,live=True,reuse=None,
                    ledger=root/'work/ledger.sqlite',key_file=root/'unused')
                StubClient.calls=[];StubClient.fail=fail
                with patch.object(runner,'BudgetedClient',StubClient),patch.object(runner,'read_key',return_value='stub'):
                    runner.run(args)
                    self.assertEqual(2 if fail else 6,len(StubClient.calls))
                    if not fail:
                        args.reuse=args.work;args.work=root/'work/second';args.output=root/'runs/second'
                        runner.run(args)
                        self.assertEqual(6,len(StubClient.calls))
                        self.assertEqual(6,len(json.loads((args.work/'results.json').read_text())))
            finally:os.chdir(old)

    def test_success_completes_and_reuses_exact_responses(self):self.execute()
    def test_failure_stops_next_batch_without_retry(self):self.execute(True)
