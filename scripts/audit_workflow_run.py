"""Replay a completed workflow from its saved source and check artifact integrity.

Model errors remain measured quality failures, not integrity failures, provided
that the grader/runtime recorded them faithfully. No network calls are made.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from decimal import Decimal, ROUND_CEILING
import hashlib
import importlib
import importlib.util
import json
import re
from pathlib import Path
import sqlite3
import sys


def load(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def encoded_hash(v, **kw): return hashlib.sha256(json.dumps(v, **kw).encode()).hexdigest()

def bad_keys(v):
    if isinstance(v, dict):
        return [k for k in v if any(x in k.lower() for x in ('gold','rubric','qid','question_id','expected','answer_key','fixture','task_id'))] + [k for child in v.values() for k in bad_keys(child)]
    if isinstance(v,list): return [k for child in v for k in bad_keys(child)]
    return []


def frozen_modules(run):
    root=run/'source'; name='workflow_audit_'+sha(run/'metadata.json')[:16]
    spec=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)])
    if spec is None or spec.loader is None: raise ValueError('saved package cannot load')
    package=importlib.util.module_from_spec(spec);sys.modules[name]=package;spec.loader.exec_module(package)
    return importlib.import_module(name+'.workflow_grade'),importlib.import_module(name+'.workflow_eval')


def audit(run, fixture, ledger=None):
    run,fixture=Path(run),Path(fixture)
    if not (run/'summary.json').exists() or not (run/'metadata.json').exists():
        return {'status':'incomplete','errors':[{'code':'missing_completion'}],'checked':0}
    summary,meta=load(run/'summary.json'),load(run/'metadata.json')
    if summary.get('status')!='complete':return {'status':'incomplete','errors':[{'code':'not_complete'}],'checked':0}
    errors=[]
    def check(ok,code,detail=''):
        if not ok:errors.append({'code':code,'detail':str(detail)})
    hashes=meta.get('implementation_sha256',{})
    check(bool(hashes),'missing_source_manifest')
    for name,want in hashes.items():
        p=run/'source'/name
        check(p.resolve().is_relative_to((run/'source').resolve()) and p.exists() and sha(p)==want,'source_hash',name)
    check(sha(fixture/'FREEZE.json')==meta.get('fixture_freeze_sha256'),'fixture_freeze_hash')
    freeze=load(fixture/'FREEZE.json')
    for name,want in freeze['files'].items():
        p=fixture/name
        check(p.resolve().is_relative_to(fixture.resolve()) and p.exists() and sha(p)==want,'fixture_file_hash',name)
    if errors:return {'status':'fail','errors':errors,'checked':0}
    try:grader,measure=frozen_modules(run)
    except Exception as exc:return {'status':'fail','errors':[{'code':'saved_source_import','type':type(exc).__name__}],'checked':0}
    workflow=importlib.import_module(grader.__package__+'.workflow')
    cases=meta['cases']; arms=meta['arms']; split=meta['split']
    rows={(r['case'],r['arm']):r for r in summary['rows']}
    check(len(rows)==len(summary['rows']) and set(rows)=={(c,a) for c in cases for a in arms},'matrix_coverage')
    seen=set(); orphan=set(); checked_tasks=0; replayed_grades=0; invalid_model_quotes=0
    ledger_rows={}
    if ledger is not None:
        with closing(sqlite3.connect('file:'+str(Path(ledger).resolve())+'?mode=ro',uri=True)) as db:
            ledger_rows={r[0]:r[1:] for r in db.execute('SELECT attempt_id,status,accounted,usage_json FROM attempts')}
    for case in cases:
        episode=load(fixture/split/case/'episode.json'); gold=load(fixture/split/case/'gold.json')
        canonical={s['source_id']:s for s in episode['sources']}
        task_defs={t['task_id']:(w,t) for w in episode['waves'] for t in w['tasks']}
        for arm in arms:
            directory=run/case/arm; row=rows.get((case,arm))
            if row is None:continue
            result=load(directory/'workflow/result.json'); tasks=result['results']
            check(set(tasks)==set(task_defs),'task_coverage',case+'/'+arm)
            check(len({r['actor'] for r in tasks.values()})==16,'sixteen_actor_coverage',case+'/'+arm)
            attempts={}
            for path in sorted((directory/'api').glob('attempt-*.json')):
                if path.name.endswith('.pending.json'):
                    check(False,'unresolved_pending',path.name);continue
                a=load(path);aid=a['attempt_id'];attempts[aid]=a
                check(aid not in seen,'duplicate_attempt',aid);seen.add(aid)
                request=a.get('request',{})
                check(encoded_hash(request,sort_keys=True,ensure_ascii=False)==a['request_sha256'],'request_hash',aid)
                check(hashlib.sha256(request['input'][0]['content'].encode()).hexdigest()==a['prompt_sha256'],'prompt_hash',aid)
                check(encoded_hash(request['text']['format']['schema'],sort_keys=True)==a['schema_sha256'],'schema_hash',aid)
                content=request['input'][1]['content']
                if isinstance(content,str):payload=json.loads(content)
                else:
                    payload={}
                    for part in content:
                        check(part['type']=='input_text','unsupported_content_block',aid)
                        decoded=json.loads(part['text'])
                        check(not (payload.keys() & decoded.keys()),'duplicate_content_key',aid)
                        payload.update(decoded)
                check(payload==a['payload'],'request_payload_binding',aid)
                check(not bad_keys(payload) and not bad_keys(request['text']['format']['schema']),'evaluation_key_in_request',aid)
                check(a['status']=='ok' and a['ledger_status']=='settled','attempt_status',aid)
                check(a['client_source_sha256']==hashes['workflow_api.py'],'client_source_hash',aid)
                usage=a['usage']
                check(all(type(usage[k]) is int and usage[k]>=0 for k in ('input_tokens','output_tokens')),'usage_type',aid)
                cost=sum(int((Decimal(usage[k])*Decimal(rate)*1000).to_integral_value(rounding=ROUND_CEILING)) for k,rate in [('input_tokens','.55'),('output_tokens','.825')])
                check(cost==a['conservative_cost_nanodollars'],'conservative_cost',aid)
                if ledger is not None:
                    entry=ledger_rows.get(aid)
                    check(entry is not None and entry[0]=='settled' and entry[1]==cost,'ledger_settlement',aid)
                    if entry:check(json.loads(entry[2])['input_tokens']==usage['input_tokens'] and json.loads(entry[2])['output_tokens']==usage['output_tokens'],'ledger_usage',aid)
                as_of=payload['as_of']; actor=payload.get('actor'); private_owners=set()
                allowed_ids=set().union(*(set(w['available_source_ids']) for w in episode['waves'] if w['as_of']==as_of))
                for supplied in payload['sources']:
                    sid=supplied['source_id']; original=canonical.get(sid)
                    check(original is not None and sid in allowed_ids,'snapshot_source',aid+':'+sid)
                    if original is None:continue
                    check(supplied['text'] in original['body'] and bool(supplied['text'].strip()),'source_excerpt',aid+':'+sid)
                    check(hashlib.sha256(original['body'].encode()).hexdigest()==supplied['body_sha256'],'body_hash',aid+':'+sid)
                    check(all(supplied[k]==original[k] for k in ('revision','scope','owner','state','effective_from','effective_to','title')),'source_metadata',aid+':'+sid)
                    check(original['effective_from']<=as_of and (original['effective_to'] is None or as_of<original['effective_to']),'source_date',aid+':'+sid)
                    if original['scope']=='private':
                        private_owners.add(original['owner'])
                        if actor:check(actor==original['owner'],'private_source_to_wrong_actor',aid)
                check(len(private_owners)<=1,'mixed_private_record',aid)
                if a['kind']=='operational_answer':
                    task_pattern=r'(?<![\w-])'+re.escape(a['metadata']['task_id'])+r'(?![\w-])'
                    check(re.search(task_pattern,json.dumps(request)) is None,'task_id_sent',aid)
                    fields=a['output']['fields']
                    for field in fields.values() if isinstance(fields,dict) else fields:
                        for citation in field['citations']:
                            if not citation['quote'].strip() or not any(s['source_id']==citation['source_id'] and citation['quote'] in s['text'] for s in payload['sources']):invalid_model_quotes+=1
            used=set()
            for tid,r in tasks.items():
                checked_tasks+=1; wave,task=task_defs[tid]
                check(r==load(directory/'workflow'/(tid+'.json')),'task_artifact_binding',tid)
                check(r['actor']==task['actor'] and r['as_of']==wave['as_of'],'task_identity',tid)
                used.update(r['attempt_ids'])
                if r.get('record'):used.add(r['record']['attempt_id'])
                check(len(r['attempt_ids'])==(2 if r['fallback'] else 1),'bounded_retry_count',tid)
                final=attempts.get(r['attempt_ids'][-1])
                normalized=getattr(workflow,'normalize_answer',lambda value,spec:value)(final['output'],task['output_spec']) if final else None
                check(final is not None and r['payload']==final['payload'] and r['output']==normalized,'final_answer_binding',tid)
                check(r['payload']['request']==task['request'],'request_text_binding',tid)
                expected_private={sid for sid in r['selected_source_ids'] if canonical[sid]['scope']=='private'}
                check(expected_private==set(r['private_source_ids']),'private_taint',tid)
                if 'selected_source_permissions' in r:
                    permissions=[{'source_id':sid,'logical_id':canonical[sid].get('logical_id',sid),'scope':canonical[sid]['scope'],'owner':canonical[sid]['owner']} for sid in r['selected_source_ids']]
                    check(permissions==r['selected_source_permissions'],'source_permission_provenance',tid)
                visible={sid for sid in wave['available_source_ids'] if canonical[sid]['scope']=='shared' or canonical[sid]['owner']==task['actor']}
                heads={canonical[sid].get('logical_id',sid):canonical[sid] for sid in wave['available_source_ids']}
                incoming=[]
                for dep in task['depends_on']:
                    prior=tasks[dep]
                    if set(prior['private_source_ids'])-visible:continue
                    if any(p['logical_id'] not in heads or (heads[p['logical_id']]['scope']=='private' and heads[p['logical_id']]['owner']!=task['actor']) for p in prior.get('selected_source_permissions',[])):continue
                    incoming.append({'actor':prior['actor'],'as_of':prior['as_of'],'fields':prior['output']['fields']})
                check(incoming==r['payload']['predecessor_handoffs'],'actual_handoff_binding',tid)
            check(set(attempts)==used,'orphan_or_missing_attempt',case+'/'+arm)
            orphan.update(set(attempts)-used)
            regrade=grader.grade(episode,gold,result); replayed_grades+=1
            check(regrade==load(directory/'quality.json')==row['quality'],'grade_replay',case+'/'+arm)
            check(measure.usage_summary(list(attempts.values()))==row['usage'],'usage_replay',case+'/'+arm)
    return {'status':'fail' if errors else 'pass','errors':errors,'checked':len(seen),'attempts':len(seen),
            'tasks':checked_tasks,'replayed_case_grades':replayed_grades,'invalid_model_quotes':invalid_model_quotes,
            'orphan_attempts':sorted(orphan),'saved_source_replay':True,'ledger_checked':ledger is not None,
            'semantic_entailment_reviewed':False,'invoice_measured':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--ledger',type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    result=audit(a.run,a.fixture,a.ledger)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('errors','orphan_attempts')}))
    return 0 if result['status']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
