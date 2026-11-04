"""Separately switchable eligible-section ranking and lossless span packing.

No fixture metadata is used. Request validation, visibility and state rules are
shared with the control. Each request has its own view of the immutable index.
"""
from copy import copy, deepcopy
from dataclasses import dataclass

from .retrieval import BudgetTooSmallError, _date_value, _json
from .retrieval_release import ReleaseConfig, ReleaseRetrieval
from .retrieval_v2 import RetrievalV2


@dataclass(frozen=True)
class CompletionConfig(ReleaseConfig):
    candidate_limit: int = 6
    eligible_section_ranking: bool = False
    compact_spans: bool = False
    lexical_diversity: float = 0.0
    strict_current_state: bool = False
    document_round_robin: bool = False

    def __post_init__(self):
        super().__post_init__()
        if any(type(value) is not bool for value in (self.eligible_section_ranking, self.compact_spans, self.strict_current_state, self.document_round_robin)):
            raise ValueError("completion switches must be boolean")
        if type(self.lexical_diversity) not in {int, float} or not 0 <= self.lexical_diversity <= 1:
            raise ValueError("lexical_diversity must be between zero and one")


class _EligibleDocumentIndex:
    def __init__(self, engine, mode, as_of):
        self.engine, self.mode, self.as_of = engine, mode, as_of

    def rank(self, query_features, eligible_documents):
        engine = self.engine
        eligible = {key for doc in eligible_documents for key in engine.by_doc[doc]
                    if engine._eligible(engine.chunks[key], self.mode, self.as_of)}
        if engine.config.eligible_section_ranking:
            scores = {}
            for key, score in engine.chunk_index.rank(query_features, eligible):
                doc = engine.chunks[key]["document_id"]
                scores[doc] = max(scores.get(doc, 0), score)
            ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        else:
            ranked = engine.doc_index.rank(query_features, eligible_documents)
        strength = engine.config.lexical_diversity
        if not strength:
            return ranked
        # A bounded reranking pool avoids quadratic work across the corpus.
        limit = engine.config.max_candidates if engine.config.enabled("expand_candidates") else engine.config.candidate_limit
        remaining = list(ranked[:max(64, limit*16)])
        keys = {doc: set().union(*(engine.chunk_index.keys[key] for key in engine.by_doc[doc] if key in eligible))
                for doc, _ in remaining}
        idf = engine.chunk_index.idf
        overlap, chosen = {doc: 0.0 for doc, _ in remaining}, []
        while remaining and len(chosen) < limit:
            position = max(range(len(remaining)), key=lambda n: (remaining[n][1] * (1-strength*overlap[remaining[n][0]]), -n))
            entry = remaining.pop(position)
            chosen.append(entry)
            selected = keys[entry[0]]
            for doc, _ in remaining:
                union = selected | keys[doc]
                similarity = sum(idf[k] for k in selected & keys[doc]) / (sum(idf[k] for k in union) or 1)
                overlap[doc] = max(overlap[doc], similarity)
        return chosen + remaining + ranked[max(64, limit*16):]


def merged_spans(spans):
    result = []
    for start, end in sorted(spans, key=lambda pair: (pair[0], pair[1])):
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


class CompletionRetrieval(ReleaseRetrieval):
    def __init__(self, adapter, config=CompletionConfig()):
        super().__init__(adapter, config)
        self.sections = {s["id"]: s for d in self.docs.values() for s in d["sections"]}

    def _eligible(self, section, mode, as_of):
        # Explicit non-adoption cannot become a current rule just because an
        # importer names the section "document_body" or another content kind.
        if self.config.strict_current_state and mode == "current" and section.get("adoption_status") in {"draft", "proposed", "superseded"}:
            return False
        return RetrievalV2._eligible(section, mode, as_of)

    def retrieve(self, request, budget=2000, count_units=len, full=False):
        view = copy(self)
        if self.config.eligible_section_ranking or self.config.lexical_diversity:
            view.doc_index = _EligibleDocumentIndex(
                self, request.get("mode", "search"), _date_value(request.get("as_of"), "as_of"))
        if full or not self.config.compact_spans:
            return RetrievalV2.retrieve(view, request, budget, count_units, full=full)

        # The full replay exposes the same validated candidate/chunk ranking as
        # the control. Its body is discarded; only source metadata is reused.
        ranked = RetrievalV2.retrieve(view, request, budget, count_units, full=True)
        import json
        full_envelope = json.loads(ranked["payload"])
        envelope = {"mode": full_envelope["mode"], "as_of": full_envelope["as_of"],
                    "items": [], "sources": {}, "budget_limited": True,
                    "warnings": ["retrieval_only; missing_evidence_is_not_proof_of_absence"]}
        if count_units(_json(envelope)) > budget:
            raise BudgetTooSmallError("Budget cannot fit the retrieval envelope")
        accepted, positions = [], {}
        order = ranked["selected_sections"]
        if self.config.document_round_robin:
            queues = {doc: [] for doc in ranked["candidate_documents"]}
            for key in order:
                queues[self.chunks[key]["document_id"]].append(key)
            order = []
            for level in range(max((len(queue) for queue in queues.values()), default=0)):
                order.extend(queue[level] for queue in queues.values() if level < len(queue))
        for key in order:
            chunk = self.chunks[key]
            parent, doc = chunk["parent_section_id"], chunk["document_id"]
            proposal = deepcopy(envelope)
            if parent in positions:
                item = proposal["items"][positions[parent]]
                item["spans"] = merged_spans(item["spans"] + chunk["spans"])
            else:
                item = {k: chunk[k] for k in ("document_id", "parent_section_id", "heading", "kind",
                        "adoption_status", "valid_from", "valid_to", "verified_at") if chunk.get(k) is not None}
                item.update(section_id=parent, spans=merged_spans(chunk["spans"]))
                proposal["items"].append(item)
                proposal["sources"][doc] = {k: v for k, v in full_envelope["sources"][doc].items() if v is not None}
            text = self.sections[parent]["text"]
            item["text"] = "".join(text[a:b] for a, b in item["spans"])
            if count_units(_json(proposal)) <= budget:
                if parent not in positions:
                    positions[parent] = len(envelope["items"])
                envelope = proposal
                accepted.append(key)
        envelope["budget_limited"] = len(accepted) < len(ranked["selected_sections"])
        payload = _json(envelope)
        if count_units(payload) > budget:
            raise BudgetTooSmallError("Final envelope exceeds budget")
        return dict(ranked, payload=payload, selected_sections=accepted,
                    omitted_chunks=ranked["candidate_chunks"]-len(accepted))
