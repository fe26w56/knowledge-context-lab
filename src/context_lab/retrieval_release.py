"""Conservative duplicate handling on the frozen Phase 2 retrieval pipeline.

Exact copies share an index entry; the returned ID/URL still belongs to the
representative document. Diversity only changes ranking, never equality.
"""
from dataclasses import dataclass

from .retrieval_v2 import Config, RetrievalV2, digest


def document_signature(document):
    """Ignore locator IDs only. All other input metadata remains significant."""
    value = {key: val for key, val in document.items() if key not in {"id", "source_url", "sections"}}
    value["sections"] = [{key: val for key, val in section.items() if key != "id"} for section in document["sections"]]
    return digest(value)


@dataclass(frozen=True)
class ReleaseConfig(Config):
    stage: int = 2
    split_long: bool | None = True
    definition_expansion: bool = True
    deduplicate_documents: bool = True
    candidate_diversity: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        if type(self.deduplicate_documents) is not bool:
            raise ValueError("deduplicate_documents must be boolean")
        if type(self.candidate_diversity) not in {float, int} or not 0 <= self.candidate_diversity <= 1:
            raise ValueError("candidate_diversity must be between zero and one")


class _GroupedAdapter:
    def __init__(self, adapter):
        self.adapter = adapter
        self.documents_read = 0
        self.documents_indexed = 0

    @property
    def read_calls(self):
        return self.adapter.read_calls

    def read(self):
        documents = self.adapter.read()
        groups = {}
        # Tie-breaking uses opaque identifiers, not known original-source IDs.
        for document in sorted(documents, key=lambda d: d["id"]):
            groups.setdefault(document_signature(document), document)
        self.documents_read = len(documents)
        self.documents_indexed = len(groups)
        return list(groups.values())


class _DiverseDocumentIndex:
    def __init__(self, index, keys, weight, limit):
        self.index = index
        self.keys = keys
        self.weight = weight
        self.limit = limit

    def rank(self, query_features, eligible):
        ranked = self.index.rank(query_features, eligible)
        remaining = list(ranked)
        chosen = []
        overlaps = {key: 0.0 for key, _ in ranked}
        while remaining and len(chosen) < self.limit:
            # The original score remains in the result; only order changes.
            position = max(range(len(remaining)), key=lambda n: (remaining[n][1] * (1 - self.weight * overlaps[remaining[n][0]]), -n))
            entry = remaining.pop(position)
            chosen.append(entry)
            selected = self.keys[entry[0]]
            for key, _ in remaining:
                union = selected | self.keys[key]
                similarity = len(selected & self.keys[key]) / len(union) if union else 0.0
                overlaps[key] = max(overlaps[key], similarity)
        return chosen + remaining


class ReleaseRetrieval(RetrievalV2):
    def __init__(self, adapter, config=ReleaseConfig()):
        grouped = _GroupedAdapter(adapter) if config.deduplicate_documents else adapter
        super().__init__(grouped, config)
        # These are build statistics for a trusted host, never response fields.
        self.documents_read = grouped.documents_read if config.deduplicate_documents else len(self.docs)
        self.documents_indexed = len(self.docs)
        if config.candidate_diversity:
            keys = {}
            for document_id, document in self.docs.items():
                keys[document_id] = {digest({k: v for k, v in section.items() if k != "id"}) for section in document["sections"]}
            limit = config.max_candidates if config.enabled("expand_candidates") else config.candidate_limit
            self.doc_index = _DiverseDocumentIndex(self.doc_index, keys, config.candidate_diversity, limit)
