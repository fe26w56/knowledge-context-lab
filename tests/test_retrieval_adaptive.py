import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from context_lab.retrieval_adaptive import AdaptiveConfig, AdaptiveRetrieval
from context_lab.retrieval_completion import CompletionConfig, CompletionRetrieval
from context_lab.retrieval_v2 import FileAdapter, SQLiteAdapter


def doc(did='d1', body='## Policy\nAdopted rule text.\n', *, status='adopted', verified='2026-11-02'):
    text=body.split('\n',1)[1].strip() if '\n' in body else body
    return {'id':did,'title':'Doc '+did,'source_url':'https://example.invalid/'+did,
      'recorded_at':'2026-11-01','verified_at':verified,'scope':'shared','owner':'team',
      'body':body,'sections':[{'id':did+'_s','heading':'Policy','text':text,'kind':'decision',
      'adoption_status':status,'valid_from':'2026-10-01','valid_to':None,'verified_at':verified}]}


def multisection(did='d1', *, scope='shared', owner='team', valid_from='2026-10-01', valid_to=None):
    sections=[]; parts=[]
    for i in range(8):
        text=f'Adopted policy section {i} records the approved rule and its evidence.'
        parts.extend([f'## Section {i}', text])
        sections.append({'id':f'{did}_s{i}','heading':f'Section {i}','text':text,'kind':'decision',
          'adoption_status':'adopted','valid_from':valid_from,'valid_to':valid_to,'verified_at':'2026-11-02'})
    return {'id':did,'title':'Doc '+did,'source_url':'https://example.invalid/'+did,
      'recorded_at':'2026-11-01','verified_at':'2026-11-02','scope':scope,'owner':owner,
      'body':'\n'.join(parts)+'\n','sections':sections}


class AdaptiveTests(unittest.TestCase):
    def engine(self, documents, adaptive=True, budget=1000):
        temp=tempfile.TemporaryDirectory(); path=Path(temp.name)/'idx'
        adapter=FileAdapter.create(path, documents)
        cls=AdaptiveRetrieval if adaptive else CompletionRetrieval
        config=(AdaptiveConfig(safe_document_packing=True, compact_spans=True, candidate_limit=1)
                if adaptive else CompletionConfig(compact_spans=True,candidate_limit=1))
        return temp, adapter, cls(adapter,config), budget

    def test_uniform_document_is_packed_with_full_span(self):
        temp,a,e,b=self.engine([doc()]);
        try:
            longdoc=doc(body='## Policy\n'+'Adopted rule text. '*100+'\n')
            a.close();temp.cleanup();temp,a,e,b=self.engine([longdoc],budget=5000)
            out=e.retrieve({'text':'adopted rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'},b)
            payload=json.loads(out['payload']);self.assertEqual(out['packing_strategy'],'complete_document')
            self.assertEqual(payload['items'][0]['spans'],[[0,len(payload['items'][0]['text'])]])
            self.assertEqual(payload['items'][0]['kind'],'document_body');self.assertIn('source_format',payload['items'][0])
        finally:a.close();temp.cleanup()

    def test_fallback_is_byte_identical_when_state_differs(self):
        mixed=doc('d2',body='## Note\nAdopted rule text.\n\n## Draft\nDraft text.\n',status='adopted')
        mixed['sections'].append({'id':'d2_s2','heading':'Draft','text':'Draft text.','kind':'note','adoption_status':'draft','valid_from':'2026-10-01','valid_to':None,'verified_at':'2026-11-02'})
        temp,a,e,b=self.engine([mixed])
        try:
            req={'text':'draft','actor':'reader','scope':'shared','mode':'search','as_of':'2026-11-02'}
            bounded=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,b)
            adaptive=e.retrieve(req,b)
            self.assertNotIn('packing_strategy',adaptive);self.assertEqual(adaptive['payload'],bounded['payload'])
        finally:a.close();temp.cleanup()

    def test_full_mode_is_exact_parent_behavior(self):
        temp,a,e,b=self.engine([doc()]);
        try:
            req={'text':'adopted rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            parent=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,b,full=True)
            got=e.retrieve(req,b,full=True);self.assertEqual(got,parent)
        finally:a.close();temp.cleanup()

    def test_budget_forces_exact_bounded_fallback(self):
        temp,a,e,b=self.engine([multisection()],budget=10000)
        try:
            req={'text':'approved rule evidence','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            def hostile_counter(payload):
                return len(payload) + (100000 if '"kind":"document_body"' in payload else 0)
            bounded=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,b, count_units=hostile_counter)
            got=e.retrieve(req,b,count_units=hostile_counter)
            self.assertNotIn('packing_strategy',got);self.assertEqual(got['payload'],bounded['payload'])
        finally:a.close();temp.cleanup()

    def test_scope_none_and_private_owner_are_respected(self):
        private=multisection('private',scope='private',owner='owner')
        temp,a,e,b=self.engine([private])
        try:
            req={'text':'adopted rule','actor':'owner','scope':None,'mode':'search','as_of':'2026-11-02'}
            out=e.retrieve(req,10000);self.assertEqual(out.get('packing_strategy'),'complete_document')
            req['actor']='other';bounded=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,10000)
            self.assertEqual(e.retrieve(req,10000)['payload'],bounded['payload'])
            self.assertNotIn('Adopted policy section',e.retrieve(req,10000)['payload'])
        finally:a.close();temp.cleanup()

    def test_file_and_sqlite_payload_parity(self):
        temp,a,e,b=self.engine([doc()])
        try:
            db_path=Path(temp.name)/'store.sqlite';SQLiteAdapter.create(db_path,[doc()]);sql=SQLiteAdapter(db_path)
            es=AdaptiveRetrieval(sql,AdaptiveConfig(safe_document_packing=True,compact_spans=True,candidate_limit=1))
            req={'text':'adopted rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            self.assertEqual(e.retrieve(req,1000)['payload'],es.retrieve(req,1000)['payload']);sql.close()
        finally:a.close();temp.cleanup()

    def test_concurrent_requests_do_not_share_views(self):
        temp,a,e,b=self.engine([multisection()])
        try:
            requests=[
              {'text':'approved rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'},
              {'text':'approved evidence','actor':'reader','scope':'shared','mode':'search','as_of':'2026-11-02'},
              {'text':'approved rule','actor':'reader','scope':'shared','mode':'history','as_of':'2026-10-01'},
              {'text':'approved rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'},
            ]
            serial=[e.retrieve(req,10000)['payload'] for req in requests]
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(lambda req: e.retrieve(req,10000)['payload'], requests))
            self.assertEqual(serial,results)
        finally:a.close();temp.cleanup()

    def test_expired_section_falls_back(self):
        mixed=multisection();mixed['sections'][0]['valid_from']='2026-09-01';mixed['sections'][0]['valid_to']='2026-10-01'
        temp,a,e,b=self.engine([mixed])
        try:
            req={'text':'approved rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            bounded=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,10000)
            self.assertEqual(e.retrieve(req,10000)['payload'],bounded['payload'])
        finally:a.close();temp.cleanup()

    def test_unindexed_body_falls_back(self):
        broken=multisection();broken['body']+='\nHidden operational sentence.\n'
        temp,a,e,b=self.engine([broken])
        try:
            req={'text':'approved rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            bounded=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,10000)
            self.assertEqual(e.retrieve(req,10000)['payload'],bounded['payload'])
        finally:a.close();temp.cleanup()

    def test_flag_off_is_parent_byte_identical(self):
        temp,a,e,b=self.engine([multisection()])
        try:
            req={'text':'approved rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            parent=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,10000)
            off=AdaptiveRetrieval(a,AdaptiveConfig(safe_document_packing=False,compact_spans=True,candidate_limit=1)).retrieve(req,10000)
            self.assertEqual(parent,off)
        finally:a.close();temp.cleanup()

    def test_packed_diagnostics_come_from_full_parent(self):
        temp,a,e,b=self.engine([multisection()])
        try:
            req={'text':'approved rule','actor':'reader','scope':'shared','mode':'current','as_of':'2026-11-02'}
            full=CompletionRetrieval(a,CompletionConfig(compact_spans=True,candidate_limit=1)).retrieve(req,10000,full=True)
            got=e.retrieve(req,10000)
            self.assertEqual(got['candidate_documents'],full['candidate_documents'])
            self.assertEqual(got['selected_sections'],full['selected_sections'])
            self.assertEqual(got['candidate_chunks'],full['candidate_chunks'])
            self.assertGreater(got['selected_sections'].__len__(),0)
        finally:a.close();temp.cleanup()

if __name__=='__main__': unittest.main()
