from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from context_lab.model_quality import audit_answer, digest, grade_template, main, measurements, prepare, summarize


class ModelQualityTests(unittest.TestCase):
    def setUp(self):
        self.question = dict(request=dict(text='Retention?', actor='a', scope='shared', mode='current'),
            forbidden_quotes=['PRIVATE_SECRET'], rubric=dict(abstain=False, atomic_claims=[
                dict(key='retention', value='Keep for 30 days.', accepted_source_ids=['d'])]))
        self.docs = {'d': dict(id='d', scope='shared', body='Keep for 30 days. Deletion needs approval.')}
        self.lineage = {'d': ('d', 'base')}
        self.answer = dict(answer='Keep for 30 days.', abstain=False, missing_information=[],
            claims=[dict(statement='Keep for 30 days.', citations=[dict(document_id='d', quote='Keep for 30 days.')])])
        self.attempt = dict(status='ok', output=self.answer, retrieved_payload=dict(mode='current', as_of=None,
            budget_limited=False, warnings=[], items=[dict(document_id='d', text=self.docs['d']['body'])]))

    def packet(self, attempt=None):
        attempt = deepcopy(attempt or self.attempt)
        p = dict(review_id='r', request=self.question['request'], rubric=self.question['rubric'],
                 output=attempt['output'], automatic=audit_answer(attempt, self.question, self.docs, self.lineage))
        return dict(packets=[p], bindings=[dict(review_id='r', packet_sha256=digest(p),
            attempt=attempt, attempt_sha256=digest(attempt), mapping=dict(variant='selected', method='B',
            size=80, seed=1, query_id='q', repeat=0))])

    def test_real_quote_alone_never_establishes_semantic_success(self):
        p = self.packet()
        self.assertFalse(p['packets'][0]['automatic']['semantic_correctness_established'])
        result = summarize(p, [])
        self.assertEqual('pending', result['rows'][0]['status'])
        self.assertFalse(result['semantic_review_complete'])
        g = grade_template(p['packets'][0])
        g.update(reviewer='test judge', notes='Fabricated unit-test judgment, not a model measurement.')
        g['judgments'] = dict.fromkeys(g['judgments'], 'pass')
        self.assertEqual('pass', summarize(p, [g])['rows'][0]['status'])
        g['judgments']['retention'] = 'uncertain'
        self.assertEqual('pending', summarize(p, [g])['rows'][0]['status'])

    def test_hallucinated_source_or_quote_cannot_pass_review_override(self):
        for change in ('source', 'empty', 'missing'):
            with self.subTest(change=change):
                a = deepcopy(self.attempt)
                citation = a['output']['claims'][0]['citations'][0]
                if change == 'source': citation['document_id'] = 'invented'
                if change == 'empty': citation['quote'] = ' '
                if change == 'missing': citation['quote'] = 'Keep forever.'
                p = self.packet(a)
                g = grade_template(p['packets'][0])
                g.update(reviewer='test judge', notes='This override must not pass.')
                g['judgments'] = dict.fromkeys(g['judgments'], 'pass')
                self.assertEqual('fail', summarize(p, [g])['rows'][0]['status'])

    def test_wrong_condition_source_cannot_satisfy_required_source(self):
        self.lineage['d'] = ('d', 'condition')
        failures = audit_answer(self.attempt, self.question, self.docs, self.lineage)['failures']
        self.assertIn('required_source_not_cited_retention', failures)

    def test_cited_quote_must_be_supplied_even_if_in_source_body(self):
        self.attempt['retrieved_payload']['items'][0]['text'] = 'Deletion needs approval.'
        self.assertTrue(audit_answer(self.attempt, self.question, self.docs, self.lineage)['failures'])

    def test_uncited_private_context_and_literal_leak_are_failures(self):
        self.docs['private'] = dict(id='private', scope='private', owner='other', body='private')
        self.attempt['retrieved_payload']['items'].append(dict(document_id='private', text='private'))
        self.answer['answer'] += ' PRIVATE_SECRET'
        failures = audit_answer(self.attempt, self.question, self.docs, self.lineage)['failures']
        self.assertIn('unavailable_or_out_of_scope_model_context', failures)
        self.assertIn('forbidden_literal_in_answer', failures)

    def test_automatic_failure_does_not_mean_semantic_review_complete(self):
        self.attempt['status'] = 'budget_exceeded'
        result = summarize(self.packet(), [])
        self.assertEqual('fail', result['rows'][0]['status'])
        self.assertTrue(result['trial_outcomes_resolved'])
        self.assertFalse(result['semantic_review_complete'])

    def test_abstention_requires_missing_information_and_semantic_review(self):
        self.question['rubric'] = dict(abstain=True, atomic_claims=[], missing_information=['threshold'])
        self.answer.update(abstain=True, claims=[], answer='Threshold is unavailable.')
        self.assertIn('abstention_without_missing_information', audit_answer(self.attempt, self.question, self.docs, self.lineage)['failures'])
        self.answer['missing_information'] = ['threshold']
        self.assertEqual('pending', summarize(self.packet(), [])['rows'][0]['status'])

    def test_stale_partial_duplicate_and_malformed_reviews_are_rejected(self):
        p = self.packet()
        g = grade_template(p['packets'][0])
        for edit in ('hash', 'criterion', 'type', 'duplicate'):
            with self.subTest(edit=edit):
                c = deepcopy(g)
                if edit == 'hash': c['packet_sha256'] = 'stale'
                if edit == 'criterion': del c['judgments']['retention']
                if edit == 'type': c['reviewer'] = []
                with self.assertRaises(ValueError): summarize(p, [c, c] if edit == 'duplicate' else [c])
        p['packets'][0]['output']['answer'] = 'changed'
        with self.assertRaises(ValueError): summarize(p, [])
        with self.assertRaises(ValueError): summarize(dict(packets=[], bindings=[]), [])

    def test_preparation_binds_real_frozen_input_to_each_attempt(self):
        # Uses frozen retrieval, but the answer below is deliberately fabricated.
        root = Path(__file__).parents[1]
        fixture = root/'fixtures/phase2-completion-v7'
        run = root/'fixtures/phase2-model-quality-regression-v1'
        question = json.loads((fixture/'final.json').read_text())['queries'][0]
        raw = next(json.loads(line) for line in (run/'payloads.jsonl').read_text().splitlines()
                   if (lambda r: r['size']==80 and r['query_id']==question['id'] and r['method']=='B' and r['variant']=='selected' and r['budget']==4000)(json.loads(line)))
        payload = json.loads(raw['payload'])
        task = dict(task_key='test-key', request=question['request'], retrieved_payload=payload)
        m = {k: raw[k] for k in ('size','seed','query_id','variant','method','budget','payload_sha256')}
        m.update(task_key='test-key', repeat=0)
        answer = dict(answer='Deliberately ungraded test answer.', abstain=False, claims=[], missing_information=[])
        attempt = dict(task_index=0, **task, status='ok', response_status='completed', output=answer, output_text=json.dumps(answer))
        with tempfile.TemporaryDirectory() as tmp:
            temp=Path(tmp)
            for name,value in (('tasks.json',[task]), ('mapping.json',[m]), ('run.json',dict(attempts=[attempt]))):
                (temp/name).write_text(json.dumps(value))
            args=(temp/'tasks.json',temp/'mapping.json',fixture/'final.json',fixture/'corpus.json',run,temp)
            prepared = prepare(*args)
            self.assertEqual(1,len(prepared['packets']))
            self.assertNotIn('variant', prepared['packets'][0])
            self.assertNotIn('method', prepared['packets'][0])
            packet = prepared['packets'][0]
            self.assertNotIn('method', packet['supplied_context'])
            self.assertEqual(payload['items'], packet['supplied_context']['items'])
            required = {source for claim in question['rubric']['atomic_claims']
                        for source in claim['accepted_source_ids']}
            self.assertEqual(required, {doc['id'] for doc in packet['canonical_sources']})
            self.assertTrue(all('sections' in doc for doc in packet['canonical_sources']))
            # A reviewer must not silently substitute canonical evidence for
            # what the model actually received; both are covered by the hash.
            changed = json.loads(json.dumps(prepared))
            changed['packets'][0]['supplied_context']['items'] = []
            with self.assertRaisesRegex(ValueError, 'modified'):
                summarize(changed, [])
            self.assertFalse(prepared['semantic_review_complete'])
            main(['prepare','--tasks',str(args[0]),'--mapping',str(args[1]),'--queries',str(args[2]),
                  '--corpus',str(args[3]),'--retrieval-run',str(run),'--model-run',str(temp),
                  '--output',str(temp/'review')])
            main(['summarize','--prepared',str(temp/'review/result.json'),
                  '--reviews',str(temp/'review/reviews-template.json'),'--output',str(temp/'summary')])
            result = json.loads((temp/'summary/result.json').read_text())
            self.assertFalse(result['semantic_review_complete'])
            self.assertEqual('fail', result['rows'][0]['status'])
            attempt['task_index']=1
            (temp/'run.json').write_text(json.dumps(dict(attempts=[attempt])))
            with self.assertRaisesRegex(ValueError,'index'): prepare(*args)
            attempt['task_index']=0
            attempt['request']=dict(question['request'],text='changed')
            (temp/'run.json').write_text(json.dumps(dict(attempts=[attempt])))
            with self.assertRaisesRegex(ValueError,'input'): prepare(*args)

    def test_observed_parallelism_counts_distinct_actors_and_unknown_usage(self):
        def row(actor, start, end):
            return dict(status='ok', request=dict(actor=actor), started_at=start, ended_at=end,
                        latency_seconds=end-start, usage=dict(input_tokens=10, output_tokens=5),
                        nominal_cost_estimate_nanodollars=100)
        attempts = [row('a', 0, 2), row('a', 1, 3), row('b', 1.5, 2.5), row('c', 3, 4)]
        attempts[2]['usage'] = None
        attempts.append(dict(status='budget_exceeded'))
        result = measurements(attempts)
        self.assertEqual(3, result['peak_overlapping_attempt_intervals'])
        self.assertEqual(2, result['peak_overlapping_distinct_actors'])
        self.assertEqual(1, result['usage_unknown_attempts'])
        self.assertEqual(30, result['observed_totals']['input_tokens'])
        self.assertFalse(result['invoice_measured'])


if __name__ == '__main__':
    unittest.main()
