#!/usr/bin/env python3
"""Evaluate retrieval separately from evaluator-only session evidence labels."""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

import tiktoken

from context_lab.history_retrieval import retrieve


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    freeze = json.loads(Path('fixtures/phase2-longmemeval-selection-v1/FREEZE.json').read_text())
    public_path = args.data / f'{args.split}-public-inputs.json'
    gold_path = args.data / f'{args.split}-gold.json'
    for p in (public_path, gold_path):
        if sha(p) != freeze['prepared_hashes'][p.name]:
            raise ValueError('prepared dataset changed')
    # Freeze the retriever input/output before loading evaluation labels.
    public = json.loads(public_path.read_text())
    enc = tiktoken.get_encoding('o200k_base')
    rows = []
    for case in public:
        for method in args.methods:
            start = perf_counter()
            sources = retrieve(case['request'], case['sources'], method=method, limit=args.limit)
            elapsed = perf_counter() - start
            payload = {'request':case['request'], 'as_of':case['as_of'], 'sources':sources}
            rows.append({'case':case['evaluator_case_key'], 'method':method,
                         'source_ids':[s['session_id'] for s in sources],
                         'source_count':len(sources), 'total_sources':len(case['sources']),
                         'tokens':len(enc.encode(json.dumps(payload, ensure_ascii=False, sort_keys=True))),
                         'retrieval_seconds':elapsed})
    gold = {g['evaluator_case_key']:g for g in json.loads(gold_path.read_text())}
    for row in rows:
        required = set(gold[row['case']]['neutral_evidence_ids'])
        row.update(required_sessions=len(required),
                   retained_sessions=len(required & set(row['source_ids'])),
                   all_required_sessions=required.issubset(row['source_ids']))
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'split':args.split, 'limit':args.limit, 'methods':{},
               'quality_note':'Session-label retention is not answer correctness. Labels never enter retrieval.',
               'source_sha256':{'retriever':sha(Path('src/context_lab/history_retrieval.py')),
                                'runner':sha(Path(__file__)), 'public':sha(public_path), 'gold':sha(gold_path)}}
    for method in args.methods:
        a = [r for r in rows if r['method']==method]
        summary['methods'][method] = {'cases':len(a), 'all_required_sessions':sum(r['all_required_sessions'] for r in a),
            'retained_sessions':sum(r['retained_sessions'] for r in a), 'required_sessions':sum(r['required_sessions'] for r in a),
            'total_tokens':sum(r['tokens'] for r in a), 'retrieval_seconds':sum(r['retrieval_seconds'] for r in a)}
    (args.output/'rows.json').write_text(json.dumps(rows, indent=2)+'\n')
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--data',type=Path,default=Path('work/longmemeval/prepared-v1'))
    p.add_argument('--split',choices=['dev','final'],default='dev')
    p.add_argument('--methods',nargs='+',default=['full','overlap'])
    p.add_argument('--limit',type=int,default=6)
    p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())
