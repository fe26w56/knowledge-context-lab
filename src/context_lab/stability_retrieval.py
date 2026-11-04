"""Opt-in order normalization and whole-parent evidence expansion.

This is a retrieval diagnostic, not a completeness detector. Parent expansion
retains source text exactly and can still miss evidence outside ranked parents.
"""
from __future__ import annotations
from collections import defaultdict
import re
from .token_retrieval import ContextIndex
from .history_retrieval import _tokens


def parent_span(body, span):
    headings = [(m.start(), len(m.group(1))) for m in re.finditer(r'^(#{1,6})\s+', body, re.M)]
    preceding = [(start, level) for start, level in headings if start <= span['start']]
    if not preceding:
        return dict(span)
    start, level = preceding[-1]
    if level > 2:
        parents = [(s, n) for s, n in preceding[:-1] if n < level]
        if parents:
            start, level = parents[-1]
    end = next((s for s, n in headings if s > start and n <= level), len(body))
    return {'start': start, 'end': end, 'text': body[start:end]}


class StabilityIndex:
    def __init__(self, sources, *, counter):
        self.legacy = ContextIndex(sources, counter=counter)
        self.canonical = ContextIndex(sorted(sources, key=lambda s: s['id']), counter=counter)
        self.counter = counter

    @staticmethod
    def serialize(context):
        return ContextIndex.serialize(context)

    def retrieve(self, request, *, method='legacy', budget=2000):
        if method not in {'legacy', 'canonical', 'parent', 'full'}:
            raise ValueError('unknown stability method')
        engine = self.legacy if method == 'legacy' else self.canonical
        if method == 'full':
            return engine.retrieve(request, method='project', budget=budget)
        initial = engine.retrieve(request, method='diverse_sections', budget=budget)
        if method != 'parent' or request.mode == 'all':
            return initial
        # Same candidate spans as canonical at the same budget: isolate parent
        # expansion from a new ranker, larger candidate list or hidden gold.
        wanted = {(r['id'], s['start'], s['end']) for r in initial['sources'] for s in r.get('spans', [])}
        view = engine._view(request, scoped=True, deduplicate=True)
        entries = view['unique_section_entries']
        terms = set(_tokens(request.text)) - set(_tokens(request.project))
        ranked = view['unique_section_index'].rank(terms)
        sources = view['sources']; groups = []; seen = set()
        for pos in ranked:
            index, span = entries[pos]
            source = sources[index]
            if (source['id'], span['start'], span['end']) not in wanted:
                continue
            whole = parent_span(source['body'], span)
            identity = (index, whole['start'], whole['end'])
            if identity not in seen:
                seen.add(identity); groups.append((index, whole))
        selected = defaultdict(list)
        result = engine._context([], 'selected', omitted=True)
        omitted = initial['omitted_for_budget']
        for index, span in groups:
            selected[index].append(span)
            records = [engine._record(sources[i], sorted(parts, key=lambda s:s['start']))
                       for i, parts in sorted(selected.items())]
            candidate = engine._context(records, 'selected', omitted=True)
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
