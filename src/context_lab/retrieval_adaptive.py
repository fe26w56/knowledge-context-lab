"""Safe adaptive packing for short, fully indexed documents.

The adaptive path is deliberately conservative: it can replace bounded section
spans with a complete document only when the complete document is itself a
valid, current, actor-visible source and is smaller than the bounded payload.
Otherwise the exact bounded payload is returned.
"""
from __future__ import annotations

from dataclasses import dataclass

from .retrieval import _date_value, _json
from .retrieval_completion import CompletionConfig, CompletionRetrieval
from .retrieval_v2 import digest


@dataclass(frozen=True)
class AdaptiveConfig(CompletionConfig):
    safe_document_packing: bool = False

    def __post_init__(self):
        super().__post_init__()
        if type(self.safe_document_packing) is not bool:
            raise ValueError("safe_document_packing must be boolean")


class AdaptiveRetrieval(CompletionRetrieval):
    """Completion retrieval with an opt-in complete-document packing fallback."""

    def __init__(self, adapter, config=AdaptiveConfig()):
        super().__init__(adapter, config)

    @staticmethod
    def _body_covered(doc):
        body = doc.get("body")
        if not isinstance(body, str):
            return False
        covered = [False] * len(body)
        for section in doc.get("sections", []):
            text = section.get("text") if isinstance(section, dict) else None
            if not isinstance(text, str) or not text:
                return False
            start = body.find(text)
            if start < 0:
                return False
            while start >= 0:
                for i in range(start, start + len(text)):
                    covered[i] = True
                start = body.find(text, start + 1)
        offset = 0
        for line in body.splitlines(keepends=True):
            if not line.lstrip().startswith("#") and any(not ch.isspace() and not covered[offset+i] for i, ch in enumerate(line)):
                return False
            offset += len(line)
        return True

    def _safe_document(self, doc, mode, as_of, actor, scope):
        if scope is not None and doc.get("scope") != scope:
            return False
        if doc.get("scope") == "private" and doc.get("owner") != actor:
            return False
        sections = doc.get("sections")
        if not sections or not self._body_covered(doc):
            return False
        tuples = []
        for section in sections:
            if not self._eligible(section, mode, as_of):
                return False
            if mode == "current" and section.get("adoption_status") not in {"adopted", "na"}:
                return False
            tuples.append(tuple(section.get(k) for k in
                                ("adoption_status", "valid_from", "valid_to", "verified_at")))
        if len(set(tuples)) != 1:
            return False
        return True

    @staticmethod
    def _source(doc):
        return {"title": doc["title"], "source_url": doc.get("source_url"),
                "recorded_at": doc.get("recorded_at"), "verified_at": doc.get("verified_at"),
                "revision": digest(doc["body"])}

    def _complete_payload(self, docs, mode, as_of, budget, count_units):
        envelope = {"mode": mode, "as_of": as_of, "items": [], "sources": {},
                    "budget_limited": False,
                    "warnings": ["retrieval_only; missing_evidence_is_not_proof_of_absence"]}
        for doc in docs:
            item = {"document_id": doc["id"], "text": doc["body"],
                    "kind": "document_body", "source_format": "document_body",
                    "spans": [[0, len(doc["body"])]],
                    "adoption_status": doc["sections"][0].get("adoption_status"),
                    "valid_from": doc["sections"][0].get("valid_from"),
                    "valid_to": doc["sections"][0].get("valid_to"),
                    "verified_at": doc["sections"][0].get("verified_at")}
            item = {k: v for k, v in item.items() if v is not None}
            envelope["items"].append(item)
            envelope["sources"][doc["id"]] = self._source(doc)
        payload = _json(envelope)
        return payload if count_units(payload) <= budget else None

    def retrieve(self, request, budget=2000, count_units=len, full=False):
        bounded = super().retrieve(request, budget, count_units, full=full)
        if full or not self.config.safe_document_packing:
            return bounded
        # Full replay is also the authoritative diagnostic result for the same
        # candidates.  It prevents the adaptive result from reporting bounded
        # section IDs while actually returning document bodies.
        complete_reference = super().retrieve(request, budget, count_units, full=True)
        if complete_reference["candidate_documents"] != bounded["candidate_documents"]:
            return bounded
        candidates = [self.docs[d] for d in complete_reference["candidate_documents"]]
        mode = request.get("mode", "search")
        as_of = _date_value(request.get("as_of"), "as_of")
        safe = all(self._safe_document(doc, mode, as_of, request.get("actor", ""), request.get("scope"))
                   for doc in candidates)
        if not safe:
            return bounded
        complete = self._complete_payload(candidates, mode, as_of, budget, count_units)
        if complete is None or count_units(complete) >= count_units(bounded["payload"]):
            return bounded
        result = dict(complete_reference)
        result["payload"] = complete
        result["packing_strategy"] = "complete_document"
        return result
