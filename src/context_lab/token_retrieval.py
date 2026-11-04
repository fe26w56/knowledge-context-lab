"""Experimental scoped, source-exact context selection with explicit coverage.

No question IDs, grading labels, summarization model or storage backend enter this
pipeline. A selected context is candidate evidence, never a completeness promise.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import re

from .history_retrieval import _tokens


@dataclass(frozen=True)
class ContextRequest:
    text: str
    project: str
    mode: str = 'current'
    actor: str = 'agent-a'

    def __post_init__(self):
        if not self.text.strip() or not self.project.strip():
            raise ValueError('text and explicit project scope are required')
        if self.mode not in {'current', 'history', 'all'}:
            raise ValueError('mode must be current, history, or all')


def source_identity(source):
    """Exact-body equivalence only within the same access and temporal scope."""
    fields = [source[k] for k in ('project', 'status', 'scope', 'owner', 'body')]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def sections(body):
    starts = [m.start() for m in re.finditer(r'^#{1,6}\s+', body, re.M)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    bounds = starts + [len(body)]
    return [{'start': a, 'end': b, 'text': body[a:b]} for a, b in zip(bounds, bounds[1:]) if b > a]


class _BM25:
    def __init__(self, texts):
        self.postings = defaultdict(list)
        self.sizes = []
        for i, text in enumerate(texts):
            counts = Counter(_tokens(text))
            self.sizes.append(sum(counts.values()))
            for term, freq in counts.items():
                self.postings[term].append((i, freq))
        self.average = sum(self.sizes) / len(self.sizes) if self.sizes else 1
        self.average = self.average or 1

    def rank(self, terms):
        scores = defaultdict(float)
        count = len(self.sizes)
        for term in sorted(terms):
            hits = self.postings.get(term, ())
            idf = math.log(1 + (count - len(hits) + .5) / (len(hits) + .5))
            for i, freq in hits:
                scores[i] += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * self.sizes[i] / self.average))
        return sorted(scores, key=lambda i: (-scores[i], i))


class ContextIndex:
    def __init__(self, sources, *, counter):
        fields = ('id', 'title', 'project', 'status', 'scope', 'owner', 'updated_at', 'body')
        self.sources = tuple({key: s[key] for key in fields} for s in sources)
        if len({s['id'] for s in self.sources}) != len(self.sources):
            raise ValueError('source IDs must be unique')
        self.counter = counter
        self._views = {}

    @staticmethod
    def serialize(context):
        return json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    def _view(self, request, scoped, deduplicate):
        key = (request.actor, request.mode, request.project if scoped else None, deduplicate)
        if key in self._views:
            return self._views[key]
        sources = [s for s in self.sources if (s['scope'] == 'shared' or
                   (s['scope'] == 'private' and s['owner'] == request.actor))
                   and (request.mode == 'history' or s['status'] == 'current')
                   and (not scoped or s['project'] == request.project)]
        if deduplicate:
            seen = set(); unique = []
            for s in sorted(sources, key=lambda item: item['id']):
                identity = source_identity(s)
                if identity not in seen:
                    seen.add(identity); unique.append(s)
            sources = unique
        self._views[key] = {'sources': sources}
        return self._views[key]

    @staticmethod
    def _record(source, spans=None):
        result = {k: source[k] for k in ('id', 'title', 'project', 'status', 'updated_at')}
        if spans is None:
            result['body'] = source['body']
        else:
            result['spans'] = spans
        return result

    @staticmethod
    def _context(sources, coverage, *, omitted=False, exceeded=False):
        return {'coverage': coverage, 'answerability': 'not_assessed',
                'omitted_for_budget': omitted, 'budget_exceeded': exceeded, 'sources': sources}

    def retrieve(self, request, *, method='sections', budget=4000, limit=6):
        if method not in {'all', 'project', 'documents', 'deduplicated', 'sections', 'unique_sections', 'indexed_sections', 'diverse_sections'}:
            raise ValueError('unknown method')
        if type(budget) is not int or budget < 256 or type(limit) is not int or limit < 1:
            raise ValueError('invalid context budget or document limit')
        exhaustive = request.mode == 'all'
        view = self._view(request, scoped=method != 'all',
                          deduplicate=method in {'deduplicated', 'sections', 'unique_sections', 'indexed_sections', 'diverse_sections'} and not exhaustive)
        sources = view['sources']
        if method in {'all', 'project'} or exhaustive:
            result = self._context([self._record(s) for s in sources],
                                   'collection_complete' if method == 'all' else 'project_complete')
            if 'full_tokens' not in view:
                view['full_tokens'] = self.counter(self.serialize(result))
            result['budget_exceeded'] = view['full_tokens'] > budget
            return result
        # The project name is already enforced by the view, so it is not relevance evidence.
        terms = set(_tokens(request.text)) - set(_tokens(request.project))
        if method not in {'sections', 'unique_sections', 'indexed_sections', 'diverse_sections'}:
            if 'document_index' not in view:
                view['document_index'] = _BM25([s['title'] + '\n' + s['body'] for s in sources])
            chosen = view['document_index'].rank(terms)[:limit]
            result = self._context([self._record(sources[i]) for i in chosen], 'selected')
            result['budget_exceeded'] = self.counter(self.serialize(result)) > budget
            return result
        if 'section_index' not in view:
            entries = [(i, span) for i, source in enumerate(sources) for span in sections(source['body'])]
            view['section_entries'] = entries
            view['section_index'] = _BM25([span['text'] for _, span in entries])
        entries = view['section_entries']
        ranking_index = view['section_index']
        if method in {'indexed_sections', 'diverse_sections'}:
            if 'unique_section_index' not in view:
                seen = set(); unique_entries = []
                for index, span in entries:
                    source = sources[index]
                    identity = (source['project'], source['status'], source['scope'], source['owner'], span['text'].strip())
                    if identity not in seen:
                        seen.add(identity); unique_entries.append((index, span))
                view['unique_section_entries'] = unique_entries
                view['unique_section_index'] = _BM25([span['text'] for _, span in unique_entries])
            entries = view['unique_section_entries']
            ranking_index = view['unique_section_index']
        selected = defaultdict(list)
        result = self._context([], 'selected', omitted=True)
        # Rank all sections, then bound packing work to 256 candidates. Selection
        # is explicitly incomplete; do not cut a section to make it fit.
        ranked = ranking_index.rank(terms)
        if method == 'diverse_sections':
            # Prefer different wording before spending the budget on near copies.
            # Deferred passages remain candidates, not equivalent evidence. A
            # changed condition in a similar passage may still require expansion.
            representatives = []; diverse = []; deferred = []
            for position in ranked:
                words = set(_tokens(entries[position][1]['text']))
                if any(len(words & prior) / max(1, len(words | prior)) >= .8
                       for prior in representatives):
                    deferred.append(position)
                else:
                    representatives.append(words); diverse.append(position)
            ranked = diverse + deferred
        if method == 'unique_sections':
            seen = set(); unique = []
            for position in ranked:
                index, span = entries[position]
                # This is candidate suppression, not source equivalence. Keep
                # the actual representative's ID and offsets; never invent
                # provenance for other pages that contain the same paragraph.
                source = sources[index]
                identity = (source['project'], source['status'], source['scope'], source['owner'], span['text'].strip())
                if identity not in seen:
                    seen.add(identity); unique.append(position)
            ranked = unique
        omitted = len(ranked) > 256
        for position in ranked[:256]:
            index, span = entries[position]
            selected[index].append(span)
            records = [self._record(sources[i], sorted(parts, key=lambda x: x['start']))
                       for i, parts in sorted(selected.items())]
            candidate = self._context(records, 'selected', omitted=True)
            if self.counter(self.serialize(candidate)) <= budget - 2:
                result = candidate
            else:
                selected[index].pop()
                if not selected[index]: del selected[index]
                omitted = True
        result['omitted_for_budget'] = omitted
        if self.counter(self.serialize(result)) > budget:
            raise RuntimeError('context budget accounting failed')
        return result
