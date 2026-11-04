"""Explicit-topic, reviewed source ranges bound to one local read snapshot.

Content review is not policy approval. Callers supply trusted local identities;
this module is not remote authentication or arbitrary-question topic routing.
"""
from copy import deepcopy
import hashlib

from .snapshot import documents_from_snapshot
from .store import ValidationError
from .workspace import digest


def _key(project, topic_id):
    if not all(isinstance(x, str) and x.strip() for x in (project, topic_id)):
        raise ValidationError('project and topic_id are required')
    return 'reviewed:' + digest([project, topic_id])


def _body_hash(body):
    return hashlib.sha256(body.encode()).hexdigest()


def _dependencies(sources):
    return [{'source_id': s['page']['id'], 'version': s['version'],
             'sha256': s['sha256']} for s in sorted(sources, key=lambda s:s['page']['id'])]


class ReviewView:
    """An actor-bound fixed observation, not a promise of continuing freshness."""
    def __init__(self, snapshot):
        self.actor = snapshot['actor']
        self.snapshot_sha256 = snapshot['snapshot_sha256']
        self._sources = {}; self._reviews = {}
        for doc in documents_from_snapshot(snapshot):
            if doc.get('kind') == 'source':
                page = doc['page']; props = page.get('properties', {})
                key = (props.get('project'), props.get('topic_id'))
                self._sources.setdefault(key, []).append({'page':page, 'version':doc['version'],
                                                          'sha256':doc['sha256']})
            elif doc.get('kind') == 'reviewed_context':
                self._reviews[(doc['project'], doc['topic_id'])] = doc

    def context(self, project, topic_id, *, mode='current', full=False):
        _key(project,topic_id)
        if mode not in {'current','history'}: raise ValidationError('mode must be current or history')
        sources = self._sources.get((project,topic_id), [])
        base = {'project':project,'topic_id':topic_id,'mode':mode,'status':'unavailable',
                'coverage':'explicit_topic_in_visible_snapshot','sources':[]}
        if not sources:return base
        selected = [s for s in sources if mode == 'history' or s['page'].get('properties',{}).get('status') not in {'historical','superseded','retired'}]
        if not selected:return base
        review = self._reviews.get((project,topic_id))
        if review is None or review['dependencies'] != _dependencies(sources):
            return {**base,'status':'needs_review'}
        by_id = {s['page']['id']:s for s in sources}
        # Reconstruct every quote from this snapshot, not from saved prose.
        for ref in review['ranges']:
            source=by_id.get(ref['source_id'])
            if source is None or ref['source_version']!=source['version']:
                return {**base,'status':'needs_review'}
            body=source['page']['body'];start,end=ref['start'],ref['end']
            if not 0 <= start < end <= len(body) or _body_hash(body[start:end]) != ref['text_sha256']:
                raise ValidationError('review range does not match snapshot')
        records=[]
        for source in sorted(selected,key=lambda s:s['page']['id']):
            page=source['page']
            item={'id':page['id'],'title':page['title'],'version':source['version'],
                  'sha256':source['sha256'],'state':page.get('properties',{}).get('status'),
                  'properties':deepcopy(page.get('properties',{}))}
            if full:item['body']=page['body']
            else:
                item['spans']=[{'start':r['start'],'end':r['end'],
                                'text':page['body'][r['start']:r['end']],
                                'citation_id':digest([page['id'],source['version'],r['start'],r['end']])[:24]}
                               for r in review['ranges'] if r['source_id']==page['id']]
            records.append(item)
        return {**base,'status':'available','review_version':review['version'],
                'topic_signature':digest(review['dependencies']),'sources':records}


class ReviewedWorkspace:
    def __init__(self, workspace): self.workspace=workspace

    def snapshot(self, *, actor):
        return ReviewView(self.workspace.store.read_snapshot(actor=actor))

    def publish(self, project, topic_id, ranges, *, actor, request_id,
                expected_version=0, confirmed=False, view=None):
        if confirmed is not True:raise ValidationError('explicit content review confirmation required')
        key=_key(project,topic_id)
        view=self.snapshot(actor=actor) if view is None else view
        if not isinstance(view,ReviewView) or view.actor!=actor:
            raise ValidationError('review snapshot actor mismatch')
        sources=view._sources.get((project,topic_id),[])
        if not sources:raise ValidationError('no visible sources for topic')
        if not isinstance(ranges,list) or not ranges:raise ValidationError('review ranges required')
        by_id={s['page']['id']:s for s in sources}
        if {r.get('source_id') for r in ranges} != set(by_id):
            raise ValidationError('review must declare every visible topic member')
        checked=[]
        for r in ranges:
            source=by_id[r['source_id']];page=source['page'];body=page['body']
            if r.get('reviewed') is not True or r.get('topic_id')!=topic_id or r.get('scope')!=page['scope']:
                raise ValidationError('review consent or source scope mismatch')
            if r.get('source_version')!=page.get('properties',{}).get('version') or r.get('body_sha256')!=_body_hash(body):
                raise ValidationError('reviewed source version or hash mismatch')
            start,end=r.get('start'),r.get('end')
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body):
                raise ValidationError('invalid reviewed range')
            checked.append({'source_id':page['id'],'source_version':source['version'],
                            'source_revision':f"source:{page['id']}@{source['version']}",
                            'start':start,'end':end,'text_sha256':_body_hash(body[start:end])})
        checked.sort(key=lambda r:(r['source_id'],r['start'],r['end']))
        scope='private' if any(s['page']['scope']=='private' for s in sources) else 'shared'
        content={'kind':'reviewed_context','project':project,'topic_id':topic_id,
                 'dependencies':_dependencies(sources),'ranges':checked,'confirmed_by':actor,
                 'policy':'content reviewed; source decision state is unchanged'}
        return self.workspace.store.commit(record_id=key,content=content,evidence=checked,
                    actor=actor,scope=scope,owner=actor if scope=='private' else None,
                    expected_version=expected_version,request_id=request_id)


def render_citations(context, citation_ids):
    """Resolve selected IDs without generating or rewriting a quotation.

    This validates citation membership, not semantic support for a model claim.
    """
    if not isinstance(citation_ids,list) or not all(isinstance(c,str) for c in citation_ids):
        raise ValidationError('citation_ids must be strings')
    available={span['citation_id']:{'source_id':s['id'],'source_version':s['version'],
                'start':span['start'],'end':span['end'],'quote':span['text']}
               for s in context.get('sources',[]) for span in s.get('spans',[])}
    if any(c not in available for c in citation_ids):raise ValidationError('unknown citation ID')
    return [deepcopy(available[c]) for c in citation_ids]
