import copy
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
import unittest

from context_lab.reviewed_context import ReviewedWorkspace, render_citations
from context_lab.store import ValidationError
from context_lab.workspace import Workspace


def page(pid, body, *, topic='topic-a', project='demo', scope='shared', owner=None,
         status='current', version=1, proposal=False):
    props = {'project': project, 'topic_id': topic, 'status': status, 'version': version}
    if proposal: props['decision_state'] = 'proposal'
    out = {'id': pid, 'title': pid, 'body': body, 'scope': scope, 'properties': props}
    if owner is not None: out['owner'] = owner
    return out


class ReviewedContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.ws = Workspace(self.tmp.name + '/db.sqlite')
        self.review = ReviewedWorkspace(self.ws)
        self.body = '# Topic\n## Decision\nUse 42.\n## Condition\nOnly after review.\n'
        self.ws.import_pages([page('p1', self.body)], actor='alice', request_id='import-1')

    def tearDown(self): self.tmp.cleanup()

    def publish(self, *, actor='alice', request='publish-1', expected=0, confirmed=True, body=None):
        text = body or self.body
        return self.review.publish('demo', 'topic-a', [{'source_id':'p1','source_version':1,
            'body_sha256':__import__('hashlib').sha256(text.encode()).hexdigest(),
            'start':0,'end':len(text),'topic_id':'topic-a','scope':'shared','reviewed':True}],
            actor=actor, request_id=request, expected_version=expected, confirmed=confirmed)

    def test_publish_and_citations(self):
        self.publish(); view=self.review.snapshot(actor='alice'); ctx=view.context('demo','topic-a')
        self.assertEqual(ctx['status'],'available'); self.assertIn('42',ctx['sources'][0]['spans'][0]['text'])
        self.assertEqual(render_citations(ctx,[ctx['sources'][0]['spans'][0]['citation_id']])[0]['quote'], self.body)

    def test_unreviewed_correction_and_rereview(self):
        self.publish(); new=self.body.replace('42','43'); self.ws.import_pages([page('p1',new,version=2)], actor='alice', request_id='import-2', expected_versions={'p1':1})
        self.assertEqual(self.review.snapshot(actor='alice').context('demo','topic-a')['status'],'needs_review')
        self.review.publish('demo','topic-a',[{'source_id':'p1','source_version':2,'body_sha256':__import__('hashlib').sha256(new.encode()).hexdigest(),'start':0,'end':len(new),'topic_id':'topic-a','scope':'shared','reviewed':True}],actor='alice',request_id='publish-2',expected_version=1,confirmed=True)
        self.assertEqual(self.review.snapshot(actor='alice').context('demo','topic-a')['status'],'available')

    def test_topic_addition_and_retire_require_review(self):
        self.publish(); self.ws.import_pages([page('p2','# Extra\nnew',version=1)],actor='alice',request_id='import-2')
        self.assertEqual(self.review.snapshot(actor='alice').context('demo','topic-a')['status'],'needs_review')
        retired=page('p1',self.body,status='retired',version=2)
        self.ws.import_pages([retired],actor='alice',request_id='import-3',expected_versions={'p1':1})
        self.assertEqual(self.review.snapshot(actor='alice').context('demo','topic-a')['status'],'needs_review')

    def test_private_isolation_and_unknown_citation(self):
        self.ws.import_pages([page('secret','private',scope='private',owner='alice',topic='secret')],actor='alice',request_id='secret-1')
        self.assertEqual(self.review.snapshot(actor='bob').context('demo','secret')['status'],'unavailable')
        self.publish(); ctx=self.review.snapshot(actor='alice').context('demo','topic-a')
        with self.assertRaises(ValidationError): render_citations(ctx,['unknown'])

    def test_proposal_state_is_not_adopted(self):
        self.ws.import_pages([page('prop','proposal',proposal=True,topic='prop')],actor='alice',request_id='prop-1')
        body='proposal'; import hashlib
        self.review.publish('demo','prop',[{'source_id':'prop','source_version':1,'body_sha256':hashlib.sha256(body.encode()).hexdigest(),'start':0,'end':len(body),'topic_id':'prop','scope':'shared','reviewed':True}],actor='alice',request_id='prop-review',confirmed=True)
        self.assertEqual(self.ws.get_source('prop',actor='alice')['page']['properties']['decision_state'],'proposal')

    def test_history_and_immutable_fresh_views(self):
        old=self.review.snapshot(actor='alice'); self.publish(); fixed=old.context('demo','topic-a'); self.assertEqual(fixed['status'],'needs_review')
        new=self.review.snapshot(actor='alice').context('demo','topic-a'); self.assertEqual(new['status'],'available')
        self.assertIsNot(fixed,new)

    def test_history_mode_includes_reviewed_historical_member(self):
        old_body = '# Old\nlegacy condition'
        self.ws.import_pages([page('old', old_body, status='historical')], actor='alice', request_id='old-1')
        import hashlib
        ranges=[]
        for pid, body in [('old', old_body), ('p1', self.body)]:
            ranges.append({'source_id':pid,'source_version':1,'body_sha256':hashlib.sha256(body.encode()).hexdigest(),
                           'start':0,'end':len(body),'topic_id':'topic-a','scope':'shared','reviewed':True})
        self.review.publish('demo','topic-a',ranges,actor='alice',request_id='history-publish',confirmed=True)
        current=self.review.snapshot(actor='alice').context('demo','topic-a',mode='current')
        history=self.review.snapshot(actor='alice').context('demo','topic-a',mode='history')
        self.assertNotIn('old',{s['id'] for s in current['sources']})
        self.assertIn('old',{s['id'] for s in history['sources']})

    def test_publish_rejects_snapshot_from_another_actor(self):
        import hashlib
        view = self.review.snapshot(actor='alice')
        ranges=[{'source_id':'p1','source_version':1,'body_sha256':hashlib.sha256(self.body.encode()).hexdigest(),
                 'start':0,'end':len(self.body),'topic_id':'topic-a','scope':'shared','reviewed':True}]
        with self.assertRaises(ValidationError):
            self.review.publish('demo','topic-a',ranges,actor='bob',request_id='wrong-actor',confirmed=True,view=view)

    def test_old_view_publish_then_fresh_view_detects_new_member(self):
        import hashlib
        view = self.review.snapshot(actor='alice')
        self.ws.import_pages([page('p2','# New\nmember',topic='topic-a')],actor='alice',request_id='new-member')
        ranges=[{'source_id':'p1','source_version':1,'body_sha256':hashlib.sha256(self.body.encode()).hexdigest(),
                 'start':0,'end':len(self.body),'topic_id':'topic-a','scope':'shared','reviewed':True}]
        self.review.publish('demo','topic-a',ranges,actor='alice',request_id='old-view-publish',confirmed=True,view=view)
        self.assertEqual(self.review.snapshot(actor='alice').context('demo','topic-a')['status'],'needs_review')

    def test_scope_change_is_rejected_before_it_can_leak(self):
        self.publish()
        private = page('p1', self.body, scope='private', owner='alice', version=2)
        with self.assertRaises(ValidationError):
            self.ws.import_pages([private],actor='alice',request_id='scope-change',expected_versions={'p1':1})
        bob = self.review.snapshot(actor='bob').context('demo','topic-a')
        self.assertEqual(bob['status'], 'available')
        self.assertIn('p1', {s['id'] for s in bob['sources']})

    def test_parallel_reads_consistent(self):
        self.publish(); r=self.review.snapshot(actor='alice')
        with ThreadPoolExecutor(max_workers=16) as pool: values=list(pool.map(lambda _: r.context('demo','topic-a'),range(16)))
        self.assertTrue(all(v==values[0] for v in values))

    def test_publish_rejects_bad_range_and_confirmation(self):
        import hashlib
        with self.assertRaises(ValidationError): self.publish(confirmed=False)
        with self.assertRaises(ValidationError): self.review.publish('demo','topic-a',[{'source_id':'p1','source_version':1,'body_sha256':'wrong','start':0,'end':2,'topic_id':'topic-a','scope':'shared','reviewed':True}],actor='alice',request_id='bad',confirmed=True)
