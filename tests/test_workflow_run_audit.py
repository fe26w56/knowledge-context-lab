import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from context_lab.workflow_eval import run

spec=importlib.util.spec_from_file_location('audit_workflow_run',Path(__file__).parents[1]/'scripts/audit_workflow_run.py')
audit_mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit_mod)

class WorkflowRunAuditTests(unittest.TestCase):
    def make_run(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        fixture=root/'fixture';case=fixture/'dev'/'unit';case.mkdir(parents=True)
        source={'source_id':'s1','body':'No current adopted operational decision exists.','revision':'v1','scope':'shared','owner':'ops','state':'proposed','effective_from':'2026-01-01','effective_to':None,'title':'Operational decision'}
        waves=[];gold={'tasks':{}}
        for w in range(4):
            tasks=[]
            for n in range(4):
                tid=f't-{w*4+n}'
                task={'task_id':tid,'actor':f'actor-{w*4+n}','topic':'Operational decision','area':'site','request':'What adopted decision exists?','output_spec':{'status':{'type':'string','description':'Adopted decision or null'}},'depends_on':[]}
                tasks.append(task);gold['tasks'][tid]={'fields':{'status':{'expected':None,'exact_quotes':[]}},'forbidden_claims':[]}
            waves.append({'wave':w+1,'as_of':'2026-02-01','available_source_ids':['s1'],'tasks':tasks})
        episode={'episode_id':'unit','design':{'length':'short','reuse':'high','update':'none'},'sources':[source],'waves':waves}
        for name,value in [('episode.json',episode),('gold.json',gold)]: (case/name).write_text(json.dumps(value))
        files={str(p.relative_to(fixture)):hashlib.sha256(p.read_bytes()).hexdigest() for p in case.glob('*.json')}
        (fixture/'FREEZE.json').write_text(json.dumps({'files':files,'frozen_at_utc':'2026-01-01T00:00:00Z','manifest_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}))
        response={'id':'fake','status':'completed','usage':{'input_tokens':3,'output_tokens':2,'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}},'output_text':json.dumps({'fields':{'status':{'value':None,'citations':[]}},'needs_more':True})}
        target=root/'run';ledger=root/'ledger.sqlite'
        with patch.dict('os.environ',{'OPENAI_API_KEY':'unit-test'}),patch('context_lab.workflow_api._post',return_value=response),contextlib.redirect_stdout(io.StringIO()):
            run(fixture,'dev',['full12'],target,ledger,workers=4)
        return target,fixture,ledger

    def test_actual_runner_shape_replays_saved_code_and_ledger(self):
        target,fixture,ledger=self.make_run();r=audit_mod.audit(target,fixture,ledger)
        self.assertEqual(r['status'],'pass',r['errors']);self.assertEqual(r['checked'],16)
        self.assertEqual(r['replayed_case_grades'],1);self.assertTrue(r['ledger_checked'])

    def test_request_tamper_and_gold_inside_json_string_are_rejected(self):
        target,fixture,ledger=self.make_run();p=next(target.glob('unit/full12/api/attempt-*.json'))
        a=json.loads(p.read_text());value=json.loads(a['request']['input'][1]['content']);value['expected']='leak'
        a['request']['input'][1]['content']=json.dumps(value);p.write_text(json.dumps(a))
        r=audit_mod.audit(target,fixture,ledger);codes={e['code'] for e in r['errors']}
        self.assertEqual(r['status'],'fail');self.assertIn('request_hash',codes);self.assertIn('evaluation_key_in_request',codes)

    def test_missing_completion_is_incomplete(self):
        target,fixture,ledger=self.make_run();(target/'summary.json').unlink()
        self.assertEqual(audit_mod.audit(target,fixture,ledger)['status'],'incomplete')

    def test_grade_tamper_does_not_pass(self):
        target,fixture,ledger=self.make_run();p=target/'unit/full12/quality.json';value=json.loads(p.read_text());value['case_pass']=False;p.write_text(json.dumps(value))
        r=audit_mod.audit(target,fixture,ledger);self.assertIn('grade_replay',{e['code'] for e in r['errors']})

    def test_saved_source_tamper_does_not_import_current_code(self):
        target,fixture,ledger=self.make_run();p=target/'source/workflow_grade.py';p.write_text('# replaced')
        r=audit_mod.audit(target,fixture,ledger);self.assertIn('source_hash',{e['code'] for e in r['errors']})

if __name__=='__main__':unittest.main()
