"""Prepare 16 distinct shared-scope actors per context arm; no API calls.

Derived from already opened regression cases, not new independent quality data.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from context_lab import retrieval_completion
from context_lab.metrics import UnitCounter
from context_lab.model_eval import sanitize_request, sanitize_retrieved_payload
from context_lab.release_eval import generate
from context_lab.retrieval_completion import CompletionConfig, CompletionRetrieval


class MemoryAdapter:
    def __init__(self, documents):
        self.documents = documents
        self.read_calls = 0
    def read(self):
        self.read_calls += 1
        return deepcopy(self.documents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, default=Path('fixtures/phase2-completion-v7'))
    parser.add_argument('--size', type=int, default=10000)
    parser.add_argument('--seed', type=int, default=19111)
    parser.add_argument('--budget', type=int, default=4000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    metadata = json.loads((args.run/'metadata.json').read_text())
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    query_file = args.fixture/'final.json'
    corpus_file = args.fixture/'corpus.json'
    if sha(query_file) != metadata['queries_sha256'] or sha(corpus_file) != metadata['corpus_sha256']:
        raise ValueError('frozen input mismatch')
    source = Path(retrieval_completion.__file__).parent
    for name, expected in metadata['source_sha256'].items():
        if name != '__init__.py' and sha(source/name) != expected:
            raise ValueError('retrieval code differs from measured code')
    queries = [q for q in json.loads(query_file.read_text())['queries'] if q['request'].get('scope') == 'shared'][:16]
    if len(queries) != 16:
        raise ValueError('need 16 shared-scope regression questions')
    documents, _, info = generate(json.loads(corpus_file.read_text()), args.size, args.seed)
    expected = next(d for d in metadata['datasets'] if (d['size'],d['seed']) == (args.size,args.seed))
    if info['corpus_hash'] != expected['corpus_hash']:
        raise ValueError('generated corpus mismatch')
    raw = {}
    for line in (args.run/'payloads.jsonl').read_text().splitlines():
        row = json.loads(line)
        if (row['size'],row['seed'],row['budget']) == (args.size,args.seed,args.budget):
            if hashlib.sha256(row['payload'].encode()).hexdigest() != row['payload_sha256']:
                raise ValueError('saved payload hash mismatch')
            raw[(row['query_id'],row['variant'],row['method'])] = row
    outputs, mappings = {}, []
    for variant in ('control','selected'):
        engine = CompletionRetrieval(MemoryAdapter(documents), CompletionConfig(**metadata['variants'][variant]))
        for method in ('A','B'):
            tasks = []
            for index,q in enumerate(queries):
                req = sanitize_request(q['request'])
                req['actor'] = f'concurrency-agent-{index+1:02d}'
                actual = engine.retrieve(req,args.budget,UnitCounter('o200k_base'),full=method=='A')['payload']
                saved = raw[(q['id'],variant,method)]
                if actual != saved['payload']:
                    raise ValueError('actor substitution changed retrieval payload')
                key = f"concurrency:{variant}:{method}:{index}"
                tasks.append(dict(task_key=key,request=req,retrieved_payload=sanitize_retrieved_payload(actual)))
                mappings.append(dict(task_key=key,query_id=q['id'],original_actor=q['request']['actor'],
                    substituted_actor=req['actor'],variant=variant,method=method,payload_sha256=saved['payload_sha256']))
            outputs[f'{variant}-{method}-tasks.json'] = tasks
    args.output.mkdir(parents=True,exist_ok=False)
    for name, tasks in outputs.items():
        (args.output/name).write_text(json.dumps(tasks,ensure_ascii=False)+'\n')
    (args.output/'mapping.json').write_text(json.dumps(mappings,indent=2)+'\n')
    receipt = dict(api_requests_sent=0,source_queries='already opened regression cases; not independent quality questions',
        selection_rule='first 16 shared-scope final queries in frozen file order',questions=16,actors_per_arm=16,
        arms=len(outputs),planned_requests=sum(map(len,outputs.values())),identity_invariance_checks=len(mappings),
        size=args.size,seed=args.seed,budget=args.budget,
        tasks_sha256={name:sha(args.output/name) for name in outputs},
        query_sha256=sha(query_file),corpus_sha256=sha(corpus_file),script_sha256=sha(Path(__file__)),
        shared_budget_required_usd=10,parallel_model_execution_measured=False)
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
