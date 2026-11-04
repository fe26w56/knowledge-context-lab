"""Read-only reconciliation; raw intervals remain immutable after repricing."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from context_lab.workflow_api import nominal_cost_bounds


def audit(ledger,runs):
    errors=[];incomplete=[];artifacts={};pending=set();nominal=0
    def error(code,aid=''):errors.append({'code':code,'attempt_id':aid})
    with closing(sqlite3.connect('file:'+str(Path(ledger).resolve())+'?mode=ro',uri=True)) as db:
        settings=db.execute('SELECT cap,halted FROM experiment_budget WHERE singleton=1').fetchone()
        rows={r[0]:dict(reserved=r[1],accounted=r[2],status=r[3],usage=json.loads(r[4]) if r[4] else None)
              for r in db.execute('SELECT attempt_id,reserved,accounted,status,usage_json FROM attempts')}
    if settings[0]!=10_000_000_000:error('cap_changed')
    if settings[1]:error('ledger_halted')
    for path in sorted(Path(runs).glob('phase2-workflow-*/**/api/attempt-*.json')):
        a=json.loads(path.read_text());aid=a['attempt_id']
        if not aid.startswith('workflow-'):error('unexpected_attempt_prefix',aid);continue
        if path.name.endswith('.pending.json'):
            pending.add(aid);continue
        if aid in artifacts:error('duplicate_artifact',aid)
        artifacts[aid]=a
    workflow={k:v for k,v in rows.items() if k.startswith('workflow-')}
    for aid in sorted(set(workflow)-set(artifacts)):
        if workflow[aid]['status'] in {'reserved','uncertain'}:incomplete.append(aid)
        else:error('missing_settled_artifact',aid)
    for aid in set(artifacts)-set(workflow):error('orphan_artifact',aid)
    for aid,a in artifacts.items():
        if aid not in workflow:continue
        row=workflow[aid]
        if row['status']!='settled' or a.get('ledger_status')!='settled':
            incomplete.append(aid);continue
        if a.get('status')!='ok':error('failed_response',aid)
        if a['conservative_cost_nanodollars']!=row['accounted']:error('conservative_cost_mismatch',aid)
        for k in ('input_tokens','output_tokens'):
            if row['usage'][k]!=a['usage'][k]:error('usage_mismatch',aid)
        if row['usage'].get('input_tokens_details_cached_tokens')!=a['usage'].get('input_tokens_details',{}).get('cached_tokens'):
            error('cached_usage_mismatch',aid)
        request=a['request']
        actual_hash=hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if actual_hash!=a['request_sha256']:error('request_hash',aid)
        options=request.get('prompt_cache_options',{})
        if options.get('ttl','30m')!='30m':error('unsupported_request_ttl',aid)
        for message in request['input']:
            if isinstance(message['content'],list):
                for block in message['content']:
                    if block.get('prompt_cache_breakpoint',{}).get('ttl','30m')!='30m':error('unsupported_breakpoint_ttl',aid)
        amount=nominal_cost_bounds(a['usage'],write_ttl='30m')['point_nanodollars']
        if amount is None:error('write_count_missing',aid);continue
        nominal+=amount
        old=a['nominal_cost_bounds']
        # Earlier runs intentionally recorded wider intervals. A derived point
        # inside that interval is consistent, not a reason to rewrite history.
        if not old['lower_nanodollars']<=amount<=old['upper_nanodollars']:error('reprice_outside_saved_bounds',aid)
    if pending:incomplete.extend(pending)
    total=sum(v['accounted'] for v in rows.values())
    if total>settings[0]:error('authorized_cap_exceeded')
    historical={k:v for k,v in rows.items() if k not in workflow}
    return {'status':'fail' if errors else 'incomplete' if incomplete else 'pass','errors':errors,
            'incomplete_attempts':sorted(set(incomplete)),'artifact_calls':len(artifacts),'workflow_ledger_rows':len(workflow),
            'workflow_status_counts':dict(Counter(v['status'] for v in workflow.values())),
            'historical_status_counts':dict(Counter(v['status'] for v in historical.values())),
            'cap_usd':settings[0]/1e9,'total_conservative_accounted_usd':total/1e9,
            'historical_accounted_usd':sum(v['accounted'] for v in historical.values())/1e9,
            'workflow_accounted_usd':sum(v['accounted'] for v in workflow.values())/1e9,
            'workflow_nominal_30m_estimate_usd':nominal/1e9,'invoice_measured':False,'credit_balance_measured':False,
            'audit_api_calls':0,'original_estimates_unchanged':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--ledger',type=Path,required=True);p.add_argument('--runs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);r=audit(a.ledger,a.runs)
    (a.output/'summary.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k not in ('errors','incomplete_attempts')}))
    return 0 if r['status']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
