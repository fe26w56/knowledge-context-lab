"""Local lifecycle exercise for reviewed source reuse (toy data only).

This is a trusted-local-caller experiment. It is not authenticated-agent or
production authorization evidence and never calls a model API.
"""
from __future__ import annotations
import hashlib, json, shutil, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from context_lab.reviewed_context import ReviewedWorkspace, render_citations
from context_lab.workspace import Workspace
from context_lab.store import AccessDenied, StoreError, ValidationError

def page(pid, topic, body_text, *, status='current', scope='shared', owner=None, version=1):
    return {'id':pid,'title':pid,'body':body_text,'scope':scope,'owner':owner,
            'properties':{'project':'toy','topic_id':topic,'version':version,'status':status}}

def ranges(view, project, topic):
    sources=view._sources[(project,topic)]
    return [{'source_id':s['page']['id'],'source_version':s['version'],
             'body_sha256':hashlib.sha256(s['page']['body'].encode()).hexdigest(),
             'start':0,'end':len(s['page']['body']),'topic_id':topic,
             'scope':s['page']['scope'],'reviewed':True} for s in sources]

def hashes(context):
    return sorted((s['id'],s['version'],s['sha256']) for s in context.get('sources',[]))

def main():
    started=time.perf_counter(); root=Path(tempfile.mkdtemp(prefix='phase2-reuse-lifecycle-'))
    db=root/'toy.sqlite'; ws=Workspace(db); rw=ReviewedWorkspace(ws); actor='local-reviewer'
    source_a=page('toy-a','dispatch','DECISION dispatch-next-day\nCONDITION weekday-confirmed\nEXCEPTION cold-chain')
    source_b=page('toy-b','dispatch','EVIDENCE inventory-check-42\nCONDITION inventory-match\nEXCEPTION mismatch-hold')
    source_old=page('toy-old','retired-topic','old decision',status='retired')
    ws.import_pages([source_a,source_b,source_old],actor=actor,request_id='import-1')
    initial=rw.snapshot(actor=actor)
    out={'schema':'phase2-reuse-lifecycle-v1','toy_only':True,'model_api_calls':0,'steps':{},'setup_ms':(time.perf_counter()-started)*1000}
    out['steps']['unreviewed_needs_review']=rw.snapshot(actor=actor).context('toy','dispatch')['status']=='needs_review'
    pub=rw.publish('toy','dispatch',ranges(initial,'toy','dispatch'),actor=actor,request_id='publish-1',confirmed=True,view=initial)
    with ThreadPoolExecutor(max_workers=16) as pool:
        reads=list(pool.map(lambda _:rw.snapshot(actor=actor).context('toy','dispatch'),range(16)))
    out['steps']['published_16_reads_same_payload']=len(reads)==16 and len({json.dumps(x,sort_keys=True) for x in reads})==1
    old_view=rw.snapshot(actor=actor).context('toy','dispatch')
    corrected=dict(source_a); corrected['body']='DECISION dispatch-two-days\nCONDITION weekday-confirmed\nEXCEPTION cold-chain'; corrected['properties']=dict(source_a['properties'],version=2)
    ws.import_pages([corrected],actor=actor,request_id='import-correction',expected_versions={'toy-a':1})
    current_after=rw.snapshot(actor=actor).context('toy','dispatch')
    out['steps']['update_needs_review_and_no_old_payload']=(current_after['status']=='needs_review' and 'dispatch-next-day' not in str(current_after))
    out['steps']['old_pinned_view_is_old_not_current']=('dispatch-next-day' in str(old_view) and old_view.get('status')=='available')
    reviewed2=rw.snapshot(actor=actor); rw.publish('toy','dispatch',ranges(reviewed2,'toy','dispatch'),actor=actor,request_id='publish-2',expected_version=1,confirmed=True,view=reviewed2)
    reread=rw.snapshot(actor=actor).context('toy','dispatch',full=True)
    out['steps']['rereview_16_reads_same_payload']=len({json.dumps(rw.snapshot(actor=actor).context('toy','dispatch'),sort_keys=True) for _ in range(16)})==1
    added=page('toy-c','dispatch','EVIDENCE carrier-scan-9\nCONDITION scan-present\nEXCEPTION scan-mismatch')
    ws.import_pages([added],actor=actor,request_id='import-add')
    out['steps']['same_topic_new_source_needs_review']=rw.snapshot(actor=actor).context('toy','dispatch')['status']=='needs_review'
    review3=rw.snapshot(actor=actor); rw.publish('toy','dispatch',ranges(review3,'toy','dispatch'),actor=actor,request_id='publish-3',expected_version=2,confirmed=True,view=review3)
    final=rw.snapshot(actor=actor).context('toy','dispatch',full=True)
    out['steps']['rereview_all_sources_verbatim']=all(text in str(final) for text in ['dispatch-two-days','inventory-check-42','carrier-scan-9'])
    other=page('toy-other','other-topic','UNRELATED other-topic'); ws.import_pages([other],actor=actor,request_id='import-other')
    out['steps']['other_topic_does_not_change_dispatch']=rw.snapshot(actor=actor).context('toy','dispatch')['status']=='available'
    backup=ws.store.backup_to(root/'backup.sqlite'); restored=Workspace(ws.store.restore_from(backup,root/'restored.sqlite').path)
    out['steps']['backup_restore_payload_equal']=rw.snapshot(actor=actor).context('toy','dispatch',full=True)==ReviewedWorkspace(restored).snapshot(actor=actor).context('toy','dispatch',full=True)
    replay=ws.import_pages([other],actor=actor,request_id='import-other'); out['steps']['same_request_replay_no_double_apply']=bool(replay['committed'] and all(x.get('replayed') is True for x in replay['committed'])) or bool(replay['unchanged'])
    retired=rw.snapshot(actor=actor).context('toy','retired-topic'); out['steps']['historical_retired_not_current']=retired['status']=='unavailable'
    try:
        private=dict(source_b); private['scope']='private'; private['owner']=actor; ws.import_pages([private],actor=actor,request_id='scope-transition',expected_versions={'toy-b':2}); out['scope_transition']='unexpectedly_allowed'
    except (AccessDenied,StoreError,ValidationError): out['scope_transition']='not_measured_store_rejected'
    out['unmeasured']=['scope transition/revoke semantics: current Store rejected attempted transition; no revoke success claimed','trusted local callers are not authenticated agents','filesystem durability beyond SQLite backup not established']
    out['counts']={'source_versions':len(ws.store.read_snapshot(actor=actor)['records']),'dispatch_sources':len(final['sources'])}
    out['hashes']={'dispatch_payload':hashlib.sha256(ws.serialize if False else json.dumps(final,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    out['code_hashes']={'exercise_reviewed_context.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        'reviewed_context.py':hashlib.sha256((Path(__file__).parent.parent/'src/context_lab/reviewed_context.py').read_bytes()).hexdigest()}
    out['elapsed_ms']= (time.perf_counter()-started)*1000
    out['all_required_steps_pass']=all(v is True for v in out['steps'].values())
    run=Path('runs/phase2-reuse-lifecycle-v1'); run.mkdir(parents=True,exist_ok=True); (run/'receipt.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    shutil.rmtree(root,ignore_errors=True)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out['all_required_steps_pass']: raise SystemExit(1)
if __name__=='__main__': main()
