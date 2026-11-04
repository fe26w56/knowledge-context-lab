"""Recompute mechanical diagnostics without treating string matches as quality."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = {c['id']: c for c in json.loads((args.fixture/'final.json').read_text())}
    results = json.loads((args.run/'results.json').read_text())
    rows = []
    for record in results:
        response = record.get('response', {})
        artifact = response.get('metadata', {})
        output = response.get('output') or {}
        answer = output.get('answer', '')
        case = cases[record['intent_id']]
        source_text = defaultdict(list)
        for source in artifact.get('payload', {}).get('context', {}).get('sources', []):
            if 'body' in source:
                source_text[source['id']].append(source['body'])
            else:
                source_text[source['id']].extend(s['text'] for s in source.get('spans', []))
        claims = output.get('claims', [])
        invalid = [i for i, c in enumerate(claims)
                   if not c.get('quote') or not any(c['quote'] in body for body in source_text[c['source_id']])]
        row = {key: record[key] for key in ['round', 'intent_id', 'arm', 'payload_sha256']}
        row.update(attempt_id=artifact.get('attempt_id'), response_id=artifact.get('response_id'),
                   request_sha256=response.get('request_sha256'), status=response.get('status'),
                   answer=answer, claims=claims, unknowns=output.get('unknowns', []),
                   answer_sha256=hashlib.sha256(answer.encode()).hexdigest(),
                   expected_literal_fragments_missing=[v for v in case['expected_answer_fragments'] if v not in answer],
                   forbidden_literal_fragments_present=[v for v in case['forbidden_answer_fragments'] if v in answer],
                   fixture_answerable=case['answerable'],
                   fixture_erratum=record['intent_id'] == 'final-10',
                   claims_count=len(claims), invalid_literal_quote_indexes=invalid,
                   citation_text_match=not invalid,
                   # Empty claims may be correct abstention, never evidence of grounded facts.
                   usage=response.get('usage'), counted_input_tokens=response.get('counted_input_tokens'),
                   conservative_cost_nanodollars=artifact.get('conservative_cost_nanodollars'),
                   nominal_cost_bounds=artifact.get('nominal_cost_bounds'),
                   response_model=artifact.get('response_model'),
                   system_fingerprint=artifact.get('system_fingerprint'),
                   elapsed_seconds=record.get('elapsed_seconds'))
        rows.append(row)
    groups = defaultdict(list)
    for row in rows: groups[row['arm']].append(row)
    arms = {}
    repeat_groups = []
    for arm, group in groups.items():
        successful = [r for r in group if r['status'] == 'ok']
        for intent in sorted({r['intent_id'] for r in group}):
            intent_rows = [r for r in group if r['intent_id'] == intent]
            repeat_groups.append({'arm':arm, 'intent_id':intent, 'repetitions':len(intent_rows),
                                  'distinct_request_hashes':len({r['request_sha256'] for r in intent_rows}),
                                  'distinct_answer_strings':len({r['answer_sha256'] for r in intent_rows}),
                                  'semantic_quality':'requires source-grounded human/agent review'})
        inputs = [r['usage']['input_tokens'] for r in successful]
        outputs = [r['usage']['output_tokens'] for r in successful]
        arms[arm] = {'calls':len(group), 'successful':len(successful),
                     'input_tokens_total':sum(inputs), 'input_tokens_median':statistics.median(inputs),
                     'output_tokens_total':sum(outputs), 'output_tokens_median':statistics.median(outputs),
                     'conservative_cost_nanodollars':sum(r['conservative_cost_nanodollars'] or 0 for r in group),
                     'claim_count':sum(r['claims_count'] for r in successful),
                     'invalid_literal_quotes':sum(len(r['invalid_literal_quote_indexes']) for r in successful),
                     'answers_with_invalid_quotes':sum(bool(r['invalid_literal_quote_indexes']) for r in successful),
                     'count_vs_usage_mismatches':sum(r['usage']['input_tokens'] != r['counted_input_tokens'] for r in successful),
                     'median_call_seconds':statistics.median(r['elapsed_seconds'] for r in group),
                     'models':sorted({r['response_model'] for r in successful}),
                     'fingerprints':sorted({str(r['system_fingerprint']) for r in successful})}
    (args.output/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    summary = {'run':str(args.run), 'responses_sha256':hashlib.sha256((args.run/'results.json').read_bytes()).hexdigest(),
               'rows':len(rows), 'unique_response_ids':len({r['response_id'] for r in rows}),
               'arms':arms,'repeat_groups':repeat_groups,'mechanical_only':True,
               'caveats':['Literal quote presence does not prove claim entailment.',
                          'Exact answer string changes do not imply semantic mistakes.',
                          'final-10 has inaccessible required gold; raw fixture is preserved.',
                          'Repetitions are not independent task samples.']}
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'rows':len(rows),'arms':arms},ensure_ascii=False))


if __name__ == '__main__':
    main()
