import unittest
from context_lab.token_retrieval import ContextRequest, sections
from context_lab.stability_retrieval import StabilityIndex, parent_span


def source(key, body, **extras):
    return dict(id=key,title=key,project='demo',body=body,status='current',scope='shared',owner='',updated_at='2026-11-03',**extras)


class StabilityRetrievalTests(unittest.TestCase):
    def test_parent_keeps_sibling_condition_and_excludes_unrelated_topic(self):
        body='# Manual\n## Release\n### Decision\nQuasar deploys.\n### Condition\nOnly after two reviews.\n## Parking\nUse gate nine.'
        span=next(s for s in sections(body) if 'Quasar' in s['text'])
        got=parent_span(body,span)
        self.assertEqual(got['text'],body[got['start']:got['end']])
        self.assertIn('two reviews',got['text']);self.assertNotIn('gate nine',got['text'])

    def test_heading_level_two_does_not_expand_whole_document(self):
        body='## First\nAlpha.\n## Second\nBeta.'
        self.assertEqual(parent_span(body,sections(body)[0])['text'],'## First\nAlpha.\n')

    def test_parent_retrieval_preserves_conditions_and_budget(self):
        body='# Manual\n## Release\n### Decision\nQuasar deploys.\n### Condition\nOnly after two reviews.\n## Parking\nUse gate nine.'
        idx=StabilityIndex([source('x',body)],counter=len)
        got=idx.retrieve(ContextRequest('Quasar','demo'),method='parent',budget=900)
        self.assertIn('two reviews',str(got));self.assertNotIn('gate nine',str(got))
        self.assertLessEqual(len(idx.serialize(got)),900)

    def test_order_invariance_and_private_exclusion(self):
        docs=[source('a','## Rule\nQuasar A'),source('b','## Rule\nQuasar B')]
        hidden=source('x','Quasar SECRET');hidden.update(scope='private',owner='other')
        docs.append(hidden);request=ContextRequest('Quasar','demo')
        for method in ['legacy','canonical','parent']:
            results=[StabilityIndex(d,counter=len).retrieve(request,method=method,budget=1200) for d in [docs,list(reversed(docs))]]
            self.assertEqual(results[0],results[1]);self.assertNotIn('SECRET',str(results))

    def test_oversized_parent_not_partially_returned(self):
        idx=StabilityIndex([source('x','## Release\n### Decision\nQuasar.\n### Condition\n'+('conditions '*500))],counter=len)
        got=idx.retrieve(ContextRequest('Quasar','demo'),method='parent',budget=500)
        self.assertEqual(got['sources'],[]);self.assertTrue(got['omitted_for_budget'])

    def test_exhaustive_path_keeps_every_source_and_reports_overflow(self):
        docs=[source(str(i),'All '+('x'*300)) for i in range(4)]
        idx=StabilityIndex(docs,counter=len)
        got=idx.retrieve(ContextRequest('All','demo',mode='all'),method='parent',budget=256)
        self.assertEqual(len(got['sources']),4);self.assertTrue(got['budget_exceeded'])
