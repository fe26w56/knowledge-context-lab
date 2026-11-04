"""Recompute mechanical metrics from saved model traces; never calls an API.

Literal matching is deliberately not a semantic answer grader. Semantic review
is a separate artifact, keyed by intent, arm and repetition.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean, median


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('output must be new')
    results = json.loads((args.run / 'results.json').read_text())
    cases = {c['id']: c for c in json.loads((args.fixture / 'final.json').read_text())}
    rows = []
    groups = defaultdict(list)
    for row in results:
        response = row['response']
        if response['status'] != 'ok':
            raise ValueError('incomplete traces need explicit failure accounting')
        output = response['output']
        context = response['metadata']['payload']['context']
        sources = {s['id']: s for s in context['sources']}
        invalid = []
        metadata_quotes = []
        quotations = 0
        claims = output['claims']
        for index, claim in enumerate(claims):
            if row['arm'] == 'citation_ids':
                ids = claim['citation_ids']
                available = {sp['citation_id']: (s, sp) for s in sources.values()
                             for sp in s.get('spans', [])}
                resolved = row.get('resolved_claims', [])
                if not ids or any(cid not in available for cid in ids) or index >= len(resolved):
                    invalid.append(index)
                    continue
                expected = [{'source_id': available[cid][0]['id'],
                             'source_version': available[cid][0]['version'],
                             'start': available[cid][1]['start'],
                             'end': available[cid][1]['end'],
                             'quote': available[cid][1]['text']} for cid in ids]
                if resolved[index]['citations'] != expected:
                    invalid.append(index)
                quotations += len(ids)
            else:
                source = sources.get(claim['source_id'])
                texts = [] if source is None else ([source['body']] if 'body' in source
                                                    else [s['text'] for s in source['spans']])
                if not claim['quote'] or not any(claim['quote'] in t for t in texts):
                    invalid.append(index)
                    metadata = {} if source is None else {k: v for k, v in source.items() if k not in {'body', 'spans'}}
                    if claim['quote'] and claim['quote'] in json.dumps(metadata, ensure_ascii=False, sort_keys=True):
                        metadata_quotes.append(index)
                quotations += 1
        usage = response['usage']
        case = cases[row['intent_id']]
        item = {'intent_id': row['intent_id'], 'arm': row['arm'], 'round': row['round'],
                'answerable': case['answerable'], 'input_tokens': usage['input_tokens'],
                'output_tokens': usage['output_tokens'],
                'reasoning_tokens': usage.get('output_tokens_details', {}).get('reasoning_tokens', 0),
                'count_equals_usage': response['counted_input_tokens'] == usage['input_tokens'],
                'elapsed_seconds': row['elapsed_seconds'],
                'conservative_cost_nanodollars': response['metadata']['conservative_cost_nanodollars'],
                'nominal_cost_nanodollars': response['metadata']['nominal_cost_bounds']['point_nanodollars'],
                'request_sha256': response['request_sha256'], 'payload_sha256': row['payload_sha256'],
                'claims': len(claims), 'quotations': quotations,
                'invalid_quote_claim_indices': invalid, 'literal_citations_valid': not invalid,
                'metadata_quote_claim_indices': metadata_quotes,
                'all_quotes_in_supplied_body_or_metadata': set(invalid) <= set(metadata_quotes),
                'no_claims_on_unavailable': not claims if not case['answerable'] else None,
                'answer': output['answer'],
                'literal_required_quotes_in_answer': sum(q in output['answer'] for q in case['required_quotes']) if case['answerable'] else None,
                'required_quotes_count': len(case['required_quotes']) if case['answerable'] else None,
                'literal_matching_is_not_semantic_correctness': True}
        rows.append(item)
        groups[row['arm']].append(item)
    summaries = {}
    for arm, items in groups.items():
        intents = defaultdict(list)
        for item in items:
            intents[item['intent_id']].append(item)
        summaries[arm] = {
            'calls': len(items), 'answerable_calls': sum(i['answerable'] for i in items),
            'unavailable_calls': sum(not i['answerable'] for i in items),
            'input_tokens_sum': sum(i['input_tokens'] for i in items),
            'input_tokens_median': median(i['input_tokens'] for i in items),
            'output_tokens_sum': sum(i['output_tokens'] for i in items),
            'reasoning_tokens_sum': sum(i['reasoning_tokens'] for i in items),
            'elapsed_seconds_median': median(i['elapsed_seconds'] for i in items),
            'elapsed_seconds_mean': mean(i['elapsed_seconds'] for i in items),
            'conservative_cost_nanodollars': sum(i['conservative_cost_nanodollars'] for i in items),
            'nominal_cost_nanodollars': sum(i['nominal_cost_nanodollars'] for i in items),
            'count_equals_usage': sum(i['count_equals_usage'] for i in items),
            'literal_citation_valid_answers': sum(i['literal_citations_valid'] for i in items),
            'claims': sum(i['claims'] for i in items),
            'quotations': sum(i['quotations'] for i in items),
            'invalid_quote_claims': sum(len(i['invalid_quote_claim_indices']) for i in items),
            'metadata_only_quotes': sum(len(i['metadata_quote_claim_indices']) for i in items),
            'supplied_body_or_metadata_valid_answers': sum(i['all_quotes_in_supplied_body_or_metadata'] for i in items),
            'no_claims_on_unavailable': sum(i['no_claims_on_unavailable'] is True for i in items),
            'intent_groups': len(intents),
            'same_request_all_repetitions': sum(len({i['request_sha256'] for i in group}) == 1 for group in intents.values()),
            'identical_answer_all_repetitions': sum(len({i['answer'] for i in group}) == 1 for group in intents.values()),
            'distinct_answer_counts': {k: len({i['answer'] for i in g}) for k, g in intents.items()},
        }
    summary = {'schema': 'phase2-reuse-model-analysis-v2', 'arms': summaries,
               'literal_citation_contract': 'Body/span substring only. Metadata quotations are separately counted, not fabricated evidence.',
               'semantic_quality': 'Separate review required; quote validity does not establish claim support or completeness.',
               'statistical_unit': '12 authored intents with 3 repeated calls each; not 36 independent tasks per arm.',
               'invoice_measured': False,
               'hashes': {'results': digest(args.run / 'results.json'),
                          'final': digest(args.fixture / 'final.json'), 'analyzer': digest(__file__)}}
    args.output.mkdir(parents=True)
    (args.output / 'rows.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == '__main__':
    main()
