#!/usr/bin/env python3
"""Replay saved exact API responses under a new, explicit coverage policy.

No new API calls. This is a regression replay, never a new held-out model run.
"""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from context_lab.context_policy import coverage_policy


def run(args):
    source=args.work/'results.json'
    results=json.loads(source.read_text())
    by_key={(r['case'],r['method']):r for r in results}
    review=json.loads(args.review.read_text())
    judgments={(r['case'],r['method']):r for r in review['cases']}
    rows=[]
    for key in sorted({r['case'] for r in results}):
        started=perf_counter()
        request=by_key[key,'full']['response']['payload']['request']
        policy=coverage_policy(request)
        method='full' if policy['selected']=='all' else 'bm25'
        elapsed=perf_counter()-started
        response=by_key[key,method]['response']
        selected=judgments[key,method]
        baseline=by_key[key,'full']['response']
        rows.append({'case':key,'policy':policy,'reused_method':method,'reused_attempt_id':response['attempt_id'],
            'answer_correct':selected['answer_correct'],'original_quotes_exact':selected['original_quotes_exact'],
            'semantic_claim_support':selected['semantic_claim_support'],
            'policy_seconds':elapsed,'input_tokens':response['usage']['input_tokens'],
            'output_tokens':response['usage']['output_tokens'],
            'model_seconds':response['latency_seconds'],
            'nominal_nanodollars':response['nominal_cost_estimate_nanodollars'],
            'conservative_nanodollars':response['conservative_cost_nanodollars'],
            'baseline_nominal_nanodollars':baseline['nominal_cost_estimate_nanodollars'],
            'baseline_seconds':baseline['latency_seconds'],
            'baseline_answer_correct':judgments[key,'full']['answer_correct']})
    total=sum(r['nominal_nanodollars'] for r in rows)
    base=sum(r['baseline_nominal_nanodollars'] for r in rows)
    summary={'cases':len(rows),'new_api_calls':0,'heldout':False,'measurement':'counterfactual replay of exact saved model responses; no fresh end-to-end timing',
        'answer_correct':sum(r['answer_correct'] for r in rows),
        'baseline_answer_correct':sum(r['baseline_answer_correct'] for r in rows),
        'new_answer_failures':sum(not r['answer_correct'] and r['baseline_answer_correct'] for r in rows),
        'original_quotes_exact':sum(r['original_quotes_exact'] for r in rows),
        'all_routes':sum(r['reused_method']=='full' for r in rows),
        'nominal_nanodollars':total,'baseline_nominal_nanodollars':base,'nominal_cost_reduction':1-total/base,
        'sum_model_seconds':sum(r['model_seconds'] for r in rows),'baseline_sum_model_seconds':sum(r['baseline_seconds'] for r in rows),
        'policy_seconds':sum(r['policy_seconds'] for r in rows),
        'source_sha256':{str(p.resolve().relative_to(Path.cwd())):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,args.review,Path('src/context_lab/context_policy.py'),Path(__file__)]}}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--work',type=Path,default=Path('work/longmemeval/model-final-v1'))
    p.add_argument('--review',type=Path,default=Path('runs/phase2-longmemeval-model-final-quality-v2/review.json'))
    p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())
