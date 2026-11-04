"""Measure reference message-content tokens and evidence across controlled growth."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import statistics
import time

import tiktoken
from context_lab.token_retrieval import ContextIndex, ContextRequest, source_identity

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTION = '資料を根拠に回答し、条件・例外・版を保持してください。原文にないことは不明とし、根拠を引用してください。'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def p95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if values else None


def score(context, case, source_map, actor):
    found = []
    by_identity = defaultdict(list)
    for record in context['sources']:
        src = source_map[record['id']]
        spans = record.get('spans', [])
        if 'body' in record:
            by_identity[source_identity(src)].append(record['body'])
        else:
            for span in spans:
                if src['body'][span['start']:span['end']] != span['text']:
                    raise ValueError('returned span does not match source offsets')
                by_identity[source_identity(src)].append(span['text'])
    required_ids = case.get('required_source_ids', [])
    source_hits = sum(source_identity(source_map[s]) in by_identity for s in required_ids)
    for quote in case.get('required_quotes', []):
        identities = {source_identity(source_map[s]) for s in required_ids if quote in source_map[s]['body']}
        found.append(any(quote in span for identity in identities for span in by_identity.get(identity, [])))
    leaked = [r['id'] for r in context['sources'] if source_map[r['id']]['scope'] == 'private' and source_map[r['id']]['owner'] != actor]
    stale = [r['id'] for r in context['sources'] if case['mode'] != 'history' and r['status'] != 'current']
    forbidden = sorted(set(case.get('forbidden_source_ids', [])) & {r['id'] for r in context['sources']})
    return {'answerable_case': bool(required_ids), 'required_sources': len(required_ids),
            'source_hits': source_hits, 'required_spans': len(found), 'span_hits': sum(found),
            'complete_evidence': (source_hits == len(required_ids) and all(found)) if required_ids else None,
            'missing_quotes': [q for q, hit in zip(case.get('required_quotes', []), found) if not hit],
            'private_exposure': len(leaked), 'stale_exposure': len(stale), 'forbidden_exposure': len(forbidden),
            'unknown_answer_quality': 'not_model_evaluated' if not required_ids else None}


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['scenario'], row['size'], row['length_multiplier'], row['method'], row['kind'])].append(row)
    result = []
    for (scenario, size, mult, method, kind), group in sorted(groups.items()):
        answerable = [r for r in group if r['answerable_case']]
        tokens = [r['input_reference_tokens'] for r in group]
        result.append({'scenario': scenario, 'size': size, 'length_multiplier': mult,
                       'method': method, 'kind': kind, 'rows': len(group),
                       'unique_questions': len({r['qid'] for r in group}),
                       'complete_evidence': sum(r['complete_evidence'] for r in answerable),
                       'answerable_rows': len(answerable), 'total_input_tokens': sum(tokens),
                       'median_input_tokens': statistics.median(tokens), 'p95_input_tokens': p95(tokens),
                       'private_exposure': sum(r['private_exposure'] for r in group),
                       'stale_exposure': sum(r['stale_exposure'] for r in group),
                       'overflow_rows': sum(r['budget_exceeded'] for r in group)})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, default=ROOT/'fixtures/phase2-token-growth-v4')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--split', choices=['dev', 'final'], default='dev')
    p.add_argument('--seeds', default='20261103')
    p.add_argument('--selection', type=Path)
    p.add_argument('--sizes', default='100,1000,10000')
    args = p.parse_args()
    if args.output.exists(): raise ValueError('output must be new')
    freeze = json.loads((args.fixture/'FREEZE.json').read_text())
    for name, digest in freeze['files'].items():
        if sha(args.fixture/name) != digest: raise ValueError('fixture hash mismatch')
    source_files = ['src/context_lab/token_retrieval.py', 'scripts/evaluate_token_growth.py']
    source_hashes = {f: sha(ROOT/f) for f in source_files}
    budgets = [2000, 4000, 8000]
    if args.split == 'final':
        if not args.selection: raise ValueError('freeze development selection before opening final')
        selection = json.loads(args.selection.read_text())
        if selection['code_sha256'] != source_hashes or selection['fixture_freeze_sha256'] != sha(args.fixture/'FREEZE.json'):
            raise ValueError('selection implementation or fixture mismatch')
        budgets = [selection['budget']]
    cases = json.loads((args.fixture/f'{args.split}.json').read_text())
    spec = importlib.util.spec_from_file_location('growth_author', args.fixture/'author_fixture.py')
    author = importlib.util.module_from_spec(spec); spec.loader.exec_module(author)
    enc = tiktoken.get_encoding('o200k_base')
    counter = lambda text: len(enc.encode(text, disallowed_special=()))
    args.output.mkdir(parents=True)
    manifest = {'schema': 'token-growth-run-v1', 'split': args.split, 'unit': 'reference_tokens:o200k_base',
                'counting': 'Sum of separately tokenized instruction, request JSON and complete context JSON; provider message framing excluded',
                'fixture_freeze_sha256': sha(args.fixture/'FREEZE.json'), 'code_sha256': source_hashes,
                'python': platform.python_version(), 'tiktoken': tiktoken.__version__,
                'budgets': budgets, 'new_model_calls': 0, 'independent_benchmark': False}
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    rows, datasets = [], []
    conditions = [(s, n, 1) for s in ['unrelated', 'mixed'] for n in map(int, args.sizes.split(','))]
    conditions += [('long', 100, mult) for mult in [1, 4, 16]]
    for seed in map(int, args.seeds.split(',')):
        for scenario, size, multiplier in conditions:
            before = time.perf_counter()
            sources = author.generate(size, scenario, seed, multiplier)
            source_map = {s['id']: s for s in sources}
            index = ContextIndex(sources, counter=counter)
            dataset = {'seed': seed, 'scenario': scenario, 'size': size, 'length_multiplier': multiplier,
                       'corpus_sha256': hashlib.sha256(serialize(sources).encode()).hexdigest(),
                       'body_chars': sum(len(s['body']) for s in sources),
                       'generation_seconds': time.perf_counter()-before,
                       'generator_metadata': author.generation_metadata(size, scenario, seed, multiplier)}
            datasets.append(dataset)
            context_counts = {}
            methods = [(m, 4000) for m in ['all', 'project', 'documents', 'deduplicated']]
            methods += [(method, budget) for method in ['sections', 'unique_sections', 'indexed_sections', 'diverse_sections'] for budget in budgets]
            for case in cases:
                # Whitelist request fields: no qid, gold, expected source or category.
                request_fields = {key: case[key] for key in ['text', 'project', 'mode']}
                request = ContextRequest(**request_fields)
                message_overhead = counter(INSTRUCTION) + counter(serialize(request_fields))
                for method, budget in methods:
                    start = time.perf_counter()
                    context = index.retrieve(request, method=method, budget=budget)
                    elapsed = time.perf_counter()-start
                    wire = serialize(context); context_sha = hashlib.sha256(wire.encode()).hexdigest()
                    if context_sha not in context_counts: context_counts[context_sha] = counter(wire)
                    score_row = score(context, case, source_map, request.actor)
                    kind = 'unknown' if not score_row['answerable_case'] else 'exhaustive' if case['mode']=='all' else 'point'
                    row = {'seed': seed, 'scenario': scenario, 'size': size, 'length_multiplier': multiplier,
                           'qid': case['qid'], 'kind': kind, 'method': f'{method}_{budget}' if method in {'sections', 'unique_sections', 'indexed_sections', 'diverse_sections'} else method,
                           'context_tokens': context_counts[context_sha], 'message_overhead_tokens': message_overhead,
                           'input_reference_tokens': context_counts[context_sha]+message_overhead,
                           'payload_sha256': context_sha, 'selected_sources': len(context['sources']),
                           'budget_exceeded': context['budget_exceeded'], 'omitted_for_budget': context['omitted_for_budget'],
                           'retrieval_seconds': elapsed, **score_row}
                    rows.append(row)
                    with (args.output/'rows.jsonl').open('a') as f: f.write(json.dumps(row, ensure_ascii=False)+'\n')
                    if not score_row['complete_evidence'] and score_row['answerable_case'] and method != 'all':
                        with (args.output/'failures.jsonl').open('a') as f:
                            f.write(json.dumps({'seed': seed, 'scenario': scenario, 'size': size, 'length_multiplier': multiplier,
                                                'qid': case['qid'], 'method': row['method'], 'context': context,
                                                'missing_quotes': score_row['missing_quotes']}, ensure_ascii=False)+'\n')
            print(json.dumps({'split': args.split, 'seed': seed, 'scenario': scenario, 'size': size,
                              'multiplier': multiplier, 'rows': len(rows)}), flush=True)
            (args.output/'datasets.json').write_text(json.dumps(datasets, indent=2)+'\n')
    summary = {'manifest': manifest, 'rows': len(rows), 'aggregates': aggregate(rows)}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({'complete': True, 'rows': len(rows)}))


if __name__ == '__main__':
    main()
