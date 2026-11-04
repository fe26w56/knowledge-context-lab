"""Post-hoc growth extension: frozen retrieval, ten non-exhaustive intents, 3 repeats.

This diagnostic was specified after the 100-document result. It is not a fresh
held-out selection and excludes the two exhaustive requests on cost grounds.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import time

import tiktoken
from context_lab.budget import ExperimentBudget
from context_lab.stability_api import CountedClient
from context_lab.stability_retrieval import StabilityIndex
from context_lab.token_retrieval import ContextRequest
from run_stability_model import PROMPT, SCHEMA, METHODS, ROOT, sha, serialize, read_key, load_author


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--key-file',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or not a.ledger.is_file():raise ValueError('new output and existing shared ledger required')
    fixture=ROOT/'fixtures/phase2-stability-v3'
    selection=json.loads((ROOT/'runs/phase2-stability-selection-v1/selection.json').read_text())
    for f,h in {**selection['code_sha256'],**selection['live_code_sha256']}.items():
        if sha(ROOT/f)!=h:raise ValueError('frozen implementation changed')
    if sha(fixture/'FREEZE.json')!=selection['fixture_freeze_sha256']:raise ValueError('freeze mismatch')
    for f,h in json.loads((fixture/'FREEZE.json').read_text())['hashes'].items():
        if sha(fixture/f)!=h:raise ValueError('fixture changed')
    a.output.mkdir(parents=True)
    manifest={'schema':'stability-scale-posthoc-v1','selected_method':'parent8000','size':10000,'rounds':3,
              'case_filter':'mode != all; all ten eligible intents; no filtering by observed correctness',
              'selection':selection,'script_sha256':sha(Path(__file__)),
              'started_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'prompt':PROMPT,'schema_definition':SCHEMA,'new_model_calls':True,
              'posthoc':True,'independent_benchmark':False,'additional_cap_usd':'0.34',
              'note':'Additional cap plus completed stability run is below 0.45 USD; global shared cap remains 10 USD.'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    cases=[c for c in json.loads((fixture/'final.json').read_text()) if c['mode']!='all']
    if len(cases)!=10:raise ValueError('ten eligible intents required')
    author=load_author(fixture/'author_fixture.py');enc=tiktoken.get_encoding('o200k_base')
    index=StabilityIndex(author.generate(10000,20261103,0),counter=lambda s:len(enc.encode(s,disallowed_special=())))
    tasks=[]
    import hashlib
    for c in cases:
        fields={'text':c['variants'][0],'project':c['project'],'mode':c['mode']}
        for arm in ['legacy','parent8000']:
            method,budget=METHODS[arm]
            payload={'request':fields,'context':index.retrieve(ContextRequest(**fields),method=method,budget=budget)}
            tasks.append({'intent_id':c['id'],'arm':arm,'payload':payload,'payload_sha256':hashlib.sha256(serialize(payload).encode()).hexdigest()})
    client=CountedClient(ExperimentBudget(a.ledger,cap_usd='10'),a.output/'api',read_key(a.key_file))
    before=client.ledger.report()['accounted'];estimates=[]
    try:
        for t in tasks:estimates.append(client.estimate(PROMPT,t['payload'],SCHEMA,2048))
    except Exception as exc:
        (a.output/'summary.json').write_text(json.dumps({'status':'count_failed','generation_calls':0,'error_type':type(exc).__name__})+'\n');return
    reservation=sum(e['reservation_nanodollars'] for e in estimates)*3
    plan={'total_worst_reservation_nanodollars':reservation,'additional_cap_nanodollars':340000000,
          'global_remaining_nanodollars':10000000000-before,'estimates':estimates}
    (a.output/'preflight.json').write_text(json.dumps(plan,indent=2)+'\n')
    if reservation>min(340000000,10000000000-before):
        (a.output/'summary.json').write_text(json.dumps({'status':'budget_stopped','generation_calls':0})+'\n');return
    results=[];start=time.time();failed=False
    for n in range(1,4):
        for i in range(0,len(tasks),2):
            pair=tasks[i:i+2]
            if (n+i//2)%2==0:pair=pair[::-1]
            for t in pair:
                callstart=time.perf_counter()
                row={k:t[k] for k in ['intent_id','arm','payload_sha256']};row['round']=n
                try:
                    row['response']=client.complete(PROMPT,t['payload'],SCHEMA,2048,metadata={'round':n,'intent_id':t['intent_id'],'arm':t['arm'],'corpus_size':10000})
                    failed=row['response']['status']!='ok'
                except Exception as exc:
                    row.update(status='runner_error',error_type=type(exc).__name__);failed=True
                row['elapsed_seconds']=time.perf_counter()-callstart;results.append(row)
                (a.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({'round':n,'completed_calls':len(results),'failed':failed}),flush=True)
                if failed:break
            if failed:break
        if failed:break
    after=client.ledger.report()['accounted']
    summary={'status':'partial' if failed else 'complete','results':len(results),'rounds':3,
             'successful':sum(r.get('response',{}).get('status')=='ok' for r in results),
             'ledger_accounted_before_nanodollars':before,'ledger_accounted_after_nanodollars':after,
             'additional_accounted_nanodollars':after-before,'count_endpoint_calls':len(estimates),
             'elapsed_seconds':time.time()-start,'posthoc':True,'exhaustive_model_responses_measured':False}
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
