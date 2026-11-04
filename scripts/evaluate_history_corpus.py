"""Offline session-retention audit, separate from model answer quality."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import tiktoken
from context_lab.history_retrieval import retrieve
from context_lab.context_policy import coverage_policy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare_longmemeval import public_and_gold, assert_public_clean

EXPECTED_SOURCE_SHA256='d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=Path('work/longmemeval/longmemeval_s_cleaned.json'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('use a new output directory')
    source_hash=sha(args.source)
    if source_hash!=EXPECTED_SOURCE_SHA256:raise ValueError('source changed')
    records=json.loads(args.source.read_bytes())
    if len(records)!=500:raise ValueError('expected 500 records')
    freeze=json.loads(Path('fixtures/phase2-longmemeval-selection-v1/FREEZE.json').read_text())
    data=Path('work/longmemeval/prepared-v1')
    for name,expected in freeze['prepared_hashes'].items():
        if sha(data/name)!=expected:raise ValueError('prepared inputs changed')
    # Evaluation-only mapping for exact reproduction of prior dev/final rows.
    selected={}
    expected_rows={}
    for split,run in [('dev','phase2-longmemeval-dev-bm25-v1'),('final','phase2-longmemeval-final-retrieval-v1')]:
        for g in json.loads((data/f'{split}-gold.json').read_text()):selected[g['question_id']]=g['evaluator_case_key']
        for row in json.loads(Path(f'runs/{run}/rows.json').read_text()):
            expected_rows[row['case'],row['method']]=row
    methods={'full':('full',6),'overlap6':('overlap',6),'bm25six':('bm25',6),'bm25twelve':('bm25',12),'coverage':None,'turn_bm25six':('turn_bm25',6),'coverage_turn':None}
    enc=tiktoken.get_encoding('o200k_base')
    rows=[];parity_checks=0
    started=perf_counter()
    for i,record in enumerate(records):
        public,_=public_and_gold(record,f'lm-all-{i:03d}')
        assert_public_clean(public)
        outputs={}
        for name,config in methods.items():
            before=perf_counter()
            route=coverage_policy(public['request']) if config is None else None
            method,limit=config if config else ('full' if route['selected']=='all' else 'turn_bm25' if name=='coverage_turn' else 'bm25',6)
            sources=retrieve(public['request'],public['sources'],method=method,limit=limit)
            elapsed=perf_counter()-before
            payload={'request':public['request'],'as_of':public['as_of'],'sources':sources}
            tokens=len(enc.encode(json.dumps(payload,ensure_ascii=False,sort_keys=True),disallowed_special=()))
            outputs[name]={'source_ids':[s['session_id'] for s in sources],
                'input_tokens':tokens,'retrieval_seconds':elapsed,'route':method if config is None else None}
        # Scores are computed only after every candidate has finished retrieval.
        _,gold=public_and_gold(record,f'lm-all-{i:03d}')
        required=set(gold['neutral_evidence_ids'])
        group='abstention' if record['question_id'].endswith('_abs') else record['question_type']
        for name,values in outputs.items():
            values['required_hits']=len(required & set(values['source_ids']))
            values['all_required']=required.issubset(values['source_ids'])
            if record['question_id'] in selected and name in {'full','overlap6','bm25six'}:
                key=selected[record['question_id']],{'full':'full','overlap6':'overlap','bm25six':'bm25'}[name]
                expected=expected_rows.get(key)
                if expected:
                    if expected['source_ids']!=values['source_ids'] or expected['tokens']!=values['input_tokens']:
                        raise ValueError(f'prior selected-case retrieval/token parity failed: {key}')
                    parity_checks+=1
        rows.append({'case_index':i,'question_type':group,'source_count':len(public['sources']),
                     'required_count':len(required),'methods':outputs})
        if (i+1)%100==0:print(json.dumps({'completed':i+1}),flush=True)
    summary={}
    for method in methods:
        groups={}
        for group in ['all']+sorted({r['question_type'] for r in rows}):
            subset=[r for r in rows if group=='all' or r['question_type']==group]
            required=sum(r['required_count'] for r in subset)
            hit=sum(r['methods'][method]['required_hits'] for r in subset)
            groups[group]={'cases':len(subset),'all_required_cases':sum(r['methods'][method]['all_required'] for r in subset),
                'required_session_hits':hit,'required_session_total':required,'session_recall':hit/required if required else None,
                'input_tokens':sum(r['methods'][method]['input_tokens'] for r in subset),
                'retrieval_seconds':sum(r['methods'][method]['retrieval_seconds'] for r in subset)}
        summary[method]=groups
    args.output.mkdir(parents=True)
    metadata={'source_sha256':source_hash,'source_records':500,'source_bytes':args.source.stat().st_size,
        'selected_case_payload_token_parity_checks':parity_checks,'wall_seconds':perf_counter()-started,
        'token_unit':'reference_tokens:o200k_base; complete request/as_of/sources JSON, matching evaluate_history.py',
        'quality_claim':'session retention only, not 500-case answer accuracy',
        'abstention_note':'Gold sessions may supply counterevidence. Session retention on abstention is reported separately, not called answerability.',
        'independence_note':'Externally authored benchmark. 21 cases exposed during development/evaluation; remaining 479 opened in a fixed-candidate exploratory audit.',
        'source_code_sha256':{str(q):sha(q) for q in [Path('src/context_lab/history_retrieval.py'),Path('src/context_lab/context_policy.py'),Path('scripts/evaluate_history_corpus.py'),Path('scripts/prepare_longmemeval.py')]}}
    (args.output/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({k:v['all'] for k,v in summary.items()}))
    return 0


if __name__=='__main__':raise SystemExit(main())
