import unittest

from context_lab.token_retrieval import ContextIndex, ContextRequest


def source(key, body, **overrides):
    return dict(id=key, title=key, project='demo', status='current', scope='shared',
                owner='', updated_at='2026-11-03', body=body, **overrides)


class TokenRetrievalTests(unittest.TestCase):
    def test_request_rejects_evaluator_fields(self):
        with self.assertRaises(TypeError):
            ContextRequest(text='q', project='demo', qid='answer-key')

    def test_permissions_and_history_apply_before_every_strategy(self):
        docs = [source('public', 'Visible current'), source('old', 'Historical')]
        docs[1]['status'] = 'historical'
        hidden = source('hidden', 'SECRET'); hidden.update(scope='private', owner='another')
        idx = ContextIndex(docs + [hidden], counter=len)
        for method in ['all', 'project', 'documents', 'deduplicated', 'sections', 'unique_sections', 'indexed_sections', 'diverse_sections']:
            result = idx.retrieve(ContextRequest('Visible', 'demo'), method=method, budget=1000)
            self.assertNotIn('SECRET', str(result))
            self.assertNotIn('Historical', str(result))
        history = idx.retrieve(ContextRequest('Historical', 'demo', mode='history'), method='project')
        self.assertEqual({'old', 'public'}, {x['id'] for x in history['sources']})

    def test_exact_source_offsets_and_atomic_condition_sections(self):
        body = '# Overview\nBackground.\n## Release gate\nQuasar approved only below 90ms.\nException: incidents require review.\n## Other\nArchive.'
        idx = ContextIndex([source('release', body)], counter=len)
        result = idx.retrieve(ContextRequest('Quasar release gate', 'demo'), method='sections', budget=1500)
        self.assertTrue(result['sources'])
        text = ''
        for item in result['sources']:
            for span in item['spans']:
                self.assertEqual(body[span['start']:span['end']], span['text'])
                text += span['text']
        self.assertIn('only below 90ms', text)
        self.assertIn('Exception: incidents require review.', text)

    def test_duplicate_collapse_respects_scope_and_status(self):
        a = source('a', 'Exact copied body')
        b = source('b', a['body'])
        other = source('other', a['body']); other['project'] = 'different'
        idx = ContextIndex([a, b, other], counter=len)
        result = idx.retrieve(ContextRequest('Exact copied', 'demo'), method='deduplicated', budget=1000)
        self.assertEqual(1, len(result['sources']))
        self.assertEqual('demo', result['sources'][0]['project'])

    def test_exhaustive_mode_reports_overflow_without_truncation(self):
        docs = [source(str(i), 'Inventory '+str(i)+' '+('x' * 200)) for i in range(8)]
        idx = ContextIndex(docs, counter=len)
        result = idx.retrieve(ContextRequest('All inventory', 'demo', mode='all'), method='sections', budget=500)
        self.assertEqual(8, len(result['sources']))
        self.assertTrue(result['budget_exceeded'])
        self.assertEqual('project_complete', result['coverage'])

    def test_large_section_is_not_cut_in_middle_to_claim_budget(self):
        idx = ContextIndex([source('long', '## Quasar\n' + 'quasar ' * 2000)], counter=len)
        result = idx.retrieve(ContextRequest('Quasar', 'demo'), method='sections', budget=1000)
        self.assertLessEqual(len(idx.serialize(result)), 1000)
        self.assertTrue(result['omitted_for_budget'])
        self.assertEqual('not_assessed', result['answerability'])

    def test_repeated_paragraphs_do_not_crowd_out_distinct_evidence(self):
        shared = '## Review\nReview release requirements and review release conditions.\n'
        docs = [source(f'n{i}', shared + f'## Other\nUnrelated note {i}.') for i in range(300)]
        docs.append(source('z', '## Evidence\nRelease archive is located in vault 731.\n'))
        index = ContextIndex(docs, counter=len)
        request = ContextRequest('Review release', 'demo')
        result = index.retrieve(request, method='unique_sections', budget=900)
        self.assertIn('vault 731', str(result))
        self.assertLessEqual(len(index.serialize(result)), 900)

    def test_near_duplicates_are_deferred_not_reported_as_equivalent(self):
        shared = '## Review\nReview release requirements and release review conditions. Code '
        docs = [source(f'n{i}', shared + str(i)) for i in range(40)]
        docs.append(source('z', '## Evidence\nRelease archive is located in vault 731.\n'))
        index = ContextIndex(docs, counter=len)
        request = ContextRequest('Review release', 'demo')
        small = index.retrieve(request, method='diverse_sections', budget=950)
        self.assertIn('vault 731', str(small))
        self.assertEqual('selected', small['coverage'])
        large = index.retrieve(request, method='diverse_sections', budget=20000)
        self.assertEqual(41, len(large['sources']))


if __name__ == '__main__':
    unittest.main()
