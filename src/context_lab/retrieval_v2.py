"""Storage-neutral retrieval experiments. No model, network, or gold labels.

Both stores feed the same in-process index. SQL FTS, distributed cache and D1
are deliberately outside this comparison. Access identity is caller supplied;
this local library is not an authentication service.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Callable

from .retrieval import BudgetTooSmallError, _features, _date_value, _json


def digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def validate_documents(documents):
    ids, sections = set(), set()
    if not documents:
        raise ValueError("Empty corpus")
    for doc in documents:
        if not isinstance(doc.get("id"), str) or not doc["id"] or doc["id"] in ids:
            raise ValueError("Document IDs must be unique nonempty strings")
        ids.add(doc["id"])
        if doc.get("scope") not in {"shared", "private"}:
            raise ValueError("Explicit scope required")
        if doc["scope"] == "private" and not doc.get("owner"):
            raise ValueError("Private document requires owner")
        for sec in doc["sections"]:
            if not sec.get("id") or sec["id"] in sections:
                raise ValueError("Unique section ID required")
            sections.add(sec["id"])
            if not sec.get("text") or sec["text"] not in doc["body"]:
                raise ValueError("Sections must be nonempty source spans")
            if sec.get("adoption_status", "na") not in {"na", "draft", "adopted", "proposed", "superseded"}:
                raise ValueError("Invalid adoption status")
            start, end = (_date_value(sec.get(k), k) for k in ("valid_from", "valid_to"))
            if start and end and start >= end:
                raise ValueError("Invalid validity interval")


class FileAdapter:
    """One JSON file per document; atomic single-document replacement.

    A batch is NOT a multi-file transaction. Use KnowledgeStore if concurrent
    writers, revision CAS, or durable request IDs are required.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.read_calls = 0
        self.logical_bytes_read = 0
        if not self.path.is_dir():
            raise FileNotFoundError(path)

    @classmethod
    def create(cls, path, documents):
        validate_documents(documents)
        path = Path(path)
        path.mkdir(parents=True, exist_ok=False)
        obj = cls(path)
        obj.update(documents)
        return obj

    def read(self):
        self.read_calls += 1
        raw = [p.read_bytes() for p in self.path.glob("*.json")]
        self.logical_bytes_read += sum(len(value) for value in raw)
        return sorted((json.loads(value) for value in raw), key=lambda d: d["id"])

    def update(self, documents):
        validate_documents(documents)
        for doc in documents:
            name = hashlib.sha256(doc["id"].encode()).hexdigest() + ".json"
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path, delete=False) as f:
                temp = Path(f.name)
                try:
                    f.write(_json(doc)); f.flush(); os.fsync(f.fileno())
                except BaseException:
                    temp.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temp, self.path / name)
            finally:
                temp.unlink(missing_ok=True)
        fd = os.open(self.path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def close(self):
        pass


class SQLiteAdapter:
    """Same document JSON as FileAdapter, committed in one SQLite transaction."""
    def __init__(self, path):
        self.path = Path(path)
        self.read_calls = 0
        self.logical_bytes_read = 0
        if not self.path.is_file():
            raise FileNotFoundError(path)
        self.db = sqlite3.connect(self.path)
        try:
            if self.db.execute("PRAGMA application_id").fetchone()[0] != 1262701654:
                raise ValueError("Not a context-lab retrieval database")
        except BaseException:
            self.db.close()
            raise

    @classmethod
    def create(cls, path, documents):
        validate_documents(documents)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb"):
            pass
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA application_id=1262701654")
            db.execute("CREATE TABLE documents(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        obj = cls(path)
        obj.update(documents)
        return obj

    def read(self):
        self.read_calls += 1
        raw = [row[0] for row in self.db.execute("SELECT payload FROM documents ORDER BY id")]
        self.logical_bytes_read += sum(len(value.encode()) for value in raw)
        return [json.loads(value) for value in raw]

    def update(self, documents):
        validate_documents(documents)
        with self.db:
            self.db.executemany("INSERT INTO documents VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", [(d["id"], _json(d)) for d in documents])

    def close(self):
        self.db.close()


ADAPTERS = {"file": FileAdapter, "sqlite": SQLiteAdapter}


@dataclass(frozen=True)
class Config:
    stage: int = 6
    candidate_limit: int = 3
    max_candidates: int = 12
    max_rounds: int = 3
    coverage_stop: float = .75
    chunk_chars: int = 420
    use_aliases: bool | None = None
    expand_candidates: bool | None = None
    split_long: bool | None = None
    coverage_selection: bool | None = None
    ranking: str = "cosine"
    definition_expansion: bool = False

    def __post_init__(self):
        for k in ("stage", "candidate_limit", "max_candidates", "max_rounds", "chunk_chars"):
            if type(getattr(self, k)) is not int:
                raise ValueError(f"{k} must be an integer")
        if not 0 <= self.stage <= 6 or self.candidate_limit < 1 or self.max_candidates < self.candidate_limit or self.max_rounds < 1 or self.chunk_chars < 80:
            raise ValueError("Invalid configuration")
        if not 0 < self.coverage_stop <= 1:
            raise ValueError("Invalid coverage stop")
        for field in ("use_aliases", "expand_candidates", "split_long", "coverage_selection"):
            if getattr(self, field) is not None and type(getattr(self, field)) is not bool:
                raise ValueError(f"{field} must be boolean or None")
        if self.ranking not in {"cosine", "bm25"}:
            raise ValueError("Unknown ranking")
        if type(self.definition_expansion) is not bool:
            raise ValueError("definition_expansion must be boolean")

    def enabled(self, field):
        thresholds = {"use_aliases": 3, "expand_candidates": 4, "split_long": 5, "coverage_selection": 6}
        override = getattr(self, field)
        return override if override is not None else self.stage >= thresholds[field]


STAGES = {
    0: "section_baseline", 1: "shared_source_metadata", 2: "prefilter_state_and_time",
    3: "lexical_aliases", 4: "bounded_candidate_expansion", 5: "split_long_sections", 6: "query_coverage_selection",
}

# Public, inspectable lexical equivalents. These are not semantic embeddings
# and are never generated from question IDs, gold citations, or scoring results.
ALIASES = (
    ("引継", "引き継", "引継ぎ", "引きつぎ", "handoff"),
    ("保管", "保存", "格納", "蓄積"),
    ("知識庫", "ナレッジ", "kb", "知識を保存", "知識の保存"),
    ("取消", "取り消", "キャンセル"), ("価格", "費用", "金額", "予算"),
    ("時刻", "時間", "締切", "期限"), ("上限", "限度", "最大"),
    ("根拠", "証拠", "evidence"), ("未確認", "未検証", "わからない"),
)


def features(text, expand=False):
    result = _features(text)
    if expand:
        low = text.lower()
        for i, group in enumerate(ALIASES):
            if any(term in low for term in group):
                result[f"alias:{i}"] += 2
    return result


def combine(parts, expand):
    out = Counter()
    for text, weight in parts:
        out.update({k: v * weight for k, v in features(text, expand).items()})
    return out


class LexicalIndex:
    """Precomputed IDF and inverted postings; eligible IDs are scored identically."""
    def __init__(self, entries, ranking="cosine"):
        self.ranking = ranking
        df = Counter(k for f in entries.values() for k in f)
        self.idf = {k: math.log((len(entries) + 1) / (n + 1)) + 1 for k, n in df.items()}
        if ranking == "bm25":
            self.idf = {k: math.log1p((len(entries) - n + .5) / (n + .5)) for k, n in df.items()}
        average_length = sum(sum(f.values()) for f in entries.values()) / max(1, len(entries)) or 1
        self.postings = defaultdict(dict)
        self.norms = {}
        self.keys = {i: set(f) for i, f in entries.items()}
        for i, f in entries.items():
            vector = {k: math.log1p(v) * self.idf[k] for k, v in f.items()}
            if ranking == "bm25":
                # Positive-IDF BM25 with weighted lexical features, k1=1.2,b=.75.
                # Shared Python scoring, not SQLite FTS5 or a database effect.
                length = sum(f.values())
                vector = {k: self.idf[k] * v * 2.2 / (v + 1.2 * (.25 + .75 * length / average_length)) for k,v in f.items()}
            self.norms[i] = math.sqrt(sum(v*v for v in vector.values()))
            for k, v in vector.items():
                self.postings[k][i] = v

    def rank(self, query_features, eligible):
        q = {k: math.log1p(v) * (1 if self.ranking == "bm25" else self.idf.get(k, 1)) for k, v in query_features.items()}
        norm = math.sqrt(sum(v*v for v in q.values()))
        if not norm:
            return []
        scores = defaultdict(float)
        for k, v in q.items():
            for i, d in self.postings.get(k, {}).items():
                if i in eligible:
                    scores[i] += v*d
        return sorted(((i, s if self.ranking == "bm25" else s / (norm * self.norms[i])) for i, s in scores.items() if self.norms[i]), key=lambda x: (-x[1], x[0]))


def split_spans(text, limit):
    """Return lists of verbatim offsets. Tables repeat header and global notes.

    Rows and sentences are never sliced mid-unit. A single oversized row or
    sentence is retained whole; budget failure is explicit at packing time.
    """
    if len(text) <= limit:
        return [[(0, len(text))]]
    lines = list(re.finditer(r"[^\n]+(?:\n|$)", text))
    table = [i for i, m in enumerate(lines) if m.group().lstrip().startswith("|")]
    if len(table) >= 3 and re.fullmatch(r"[\s|:\-]+", lines[table[1]].group()):
        first, last = table[0], table[-1]
        prefix = [(0, lines[table[1]].end())]
        suffix = [(lines[last].end(), len(text))] if lines[last].end() < len(text) else []
        rows = [(lines[i].start(), lines[i].end()) for i in table[2:]]
        groups, current, size = [], [], 0
        for span in rows:
            if current and size + span[1] - span[0] > limit:
                groups.append(prefix + current + suffix); current, size = [], 0
            current.append(span); size += span[1] - span[0]
        if current:
            groups.append(prefix + current + suffix)
        return groups
    units = list(re.finditer(r"[^。！？\n]+[。！？\n]*|[。！？\n]+", text))
    groups, start, end = [], None, None
    for m in units:
        if start is not None and m.end() - start > limit:
            groups.append([(start, end)]); start = None
        if start is None:
            start = m.start()
        end = m.end()
    if start is not None:
        groups.append([(start, end)])
    return groups or [[(0, len(text))]]


class RetrievalV2:
    def __init__(self, adapter, config=Config()):
        self.config = config
        self.adapter = adapter
        documents = adapter.read()
        validate_documents(documents)
        self.docs = {d["id"]: deepcopy(d) for d in documents}
        self.chunks, self.by_doc = {}, defaultdict(list)
        expand = config.enabled("use_aliases")
        chunk_features, doc_features = {}, {}
        for doc in documents:
            doc_features[doc["id"]] = combine(((doc["title"], 2), (doc["body"], 1)), expand)
            for sec in doc["sections"]:
                spans = split_spans(sec["text"], config.chunk_chars) if config.enabled("split_long") else [[(0, len(sec["text"]))]]
                for n, ranges in enumerate(spans):
                    key = sec["id"] + (f"~{n}" if len(spans) > 1 else "")
                    chunk = dict(sec, id=key, parent_section_id=sec["id"], document_id=doc["id"], spans=ranges,
                                 text="".join(sec["text"][a:b] for a, b in ranges))
                    self.chunks[key] = chunk
                    self.by_doc[doc["id"]].append(key)
                    chunk_features[key] = combine(((doc["title"], .5), (sec["heading"], 2), (chunk["text"], 1)), expand)
        self.doc_index = LexicalIndex(doc_features, config.ranking)
        self.chunk_index = LexicalIndex(chunk_features, config.ranking)

    @staticmethod
    def _eligible(sec, mode, as_of):
        if mode == "current" and sec.get("kind") == "decision" and sec.get("adoption_status") != "adopted":
            return False
        if mode in {"current", "history"}:
            start = _date_value(sec.get("valid_from"), "valid_from")
            end = _date_value(sec.get("valid_to"), "valid_to")
            return (not start or start <= as_of) and (not end or as_of < end)
        return True

    def retrieve(self, request, budget=2000, count_units: Callable[[str], int]=len, full=False):
        source_calls_before = self.adapter.read_calls
        allowed = {"text", "actor", "scope", "mode", "as_of"}
        if set(request) - allowed:
            raise ValueError("Retrieval accepts request fields only; gold labels/IDs prohibited")
        if not isinstance(request.get("text"), str) or not request["text"].strip():
            raise ValueError("Nonempty text required")
        if type(budget) is not int or budget <= 0:
            raise ValueError("Positive integer budget required")
        actor, scope = request.get("actor", ""), request.get("scope")
        mode, as_of = request.get("mode", "search"), _date_value(request.get("as_of"), "as_of")
        if not isinstance(actor, str) or scope not in {None, "shared", "private"} or mode not in {"current", "history", "search"}:
            raise ValueError("Invalid actor, scope, or mode")
        if mode in {"current", "history"} and not as_of:
            raise ValueError("Explicit as_of required for reproducibility")
        cfg = self.config
        visible = {i for i, d in self.docs.items() if (scope is None or d["scope"] == scope) and (d["scope"] == "shared" or d.get("owner") == actor and bool(actor))}
        eligible = {i for d in visible for i in self.by_doc[d] if cfg.stage < 2 or self._eligible(self.chunks[i], mode, as_of)}
        candidates_allowed = {self.chunks[i]["document_id"] for i in eligible}
        expansion_terms = []
        if cfg.definition_expansion and re.search(r"どう呼|何と呼|呼び名|略称|略語|英字|用語の意味", request["text"]):
            expansion_terms = ["用語", "略語", "定義", "名称"]
        qf = features(request["text"] + " " + " ".join(expansion_terms), cfg.enabled("use_aliases"))
        ranked_docs = self.doc_index.rank(qf, candidates_allowed)
        ranked_chunks = self.chunk_index.rank(qf, eligible)
        candidates, rounds, trace = [], 0, []
        query_keys = set(qf) & set(self.chunk_index.idf)
        weights = {k: self.chunk_index.idf[k] for k in query_keys}
        denom = sum(weights.values()) or 1
        previous_coverage = -1
        limit = cfg.candidate_limit
        while True:
            rounds += 1
            candidates = [i for i, _ in ranked_docs[:limit]]
            keys = set().union(*(self.chunk_index.keys[i] for d in candidates for i in self.by_doc[d] if i in eligible)) if candidates else set()
            coverage = sum(weights[k] for k in query_keys & keys) / denom
            trace.append({"round": rounds, "candidate_count": len(candidates), "query_feature_coverage": coverage})
            if not cfg.enabled("expand_candidates"):
                stop = "fixed_candidate_limit"; break
            if coverage >= cfg.coverage_stop:
                stop = "query_feature_coverage"; break
            if len(candidates) == len(ranked_docs):
                stop = "candidate_exhaustion"; break
            if rounds >= cfg.max_rounds or limit >= cfg.max_candidates:
                stop = "search_cap"; break
            if coverage <= previous_coverage:
                stop = "no_coverage_gain"; break
            previous_coverage = coverage
            limit = min(limit * 2, cfg.max_candidates)
        candidate_set = set(candidates)
        ranked = [(i, s) for i, s in ranked_chunks if self.chunks[i]["document_id"] in candidate_set]
        envelope = {"mode": mode, "as_of": as_of, "items": [], "sources": {}, "budget_limited": False,
                    "warnings": ["retrieval_only; missing_evidence_is_not_proof_of_absence"]}
        if full:
            envelope["warnings"].append("full_document_replay; can_include_labelled_history_and_proposals")
        selected, covered = [], set()

        def source(d):
            return {"title": d["title"], "source_url": d.get("source_url"), "recorded_at": d.get("recorded_at"),
                    "verified_at": d.get("verified_at"), "revision": digest(d["body"])}

        def item_for(i):
            c = self.chunks[i]; d = self.docs[c["document_id"]]
            item = {k: c.get(k) for k in ("document_id", "parent_section_id", "heading", "kind", "adoption_status", "valid_from", "valid_to", "verified_at", "text")}
            item["section_id"] = i
            item["spans"] = c["spans"]
            if cfg.stage == 0:
                item.update(source(d))
            return item

        if count_units(_json(envelope)) > budget and not full:
            raise BudgetTooSmallError("Budget cannot fit the retrieval envelope")
        if full:
            for d in candidates:
                doc = self.docs[d]
                envelope["sources"][d] = source(doc)
                envelope["items"].append({"document_id": d, "text": doc["body"]})
            selected = [i for i, _ in ranked]
        else:
            remaining = list(ranked)
            while remaining:
                if cfg.enabled("coverage_selection"):
                    def utility(pair):
                        i, score = pair
                        novel = (self.chunk_index.keys[i] & query_keys) - covered
                        gain = sum(weights[k] for k in novel) / denom
                        return score + .7 * gain
                    remaining.sort(key=lambda pair: (-utility(pair), pair[0]))
                i, _ = remaining.pop(0)
                d = self.chunks[i]["document_id"]
                item = item_for(i)
                previous_source = d in envelope["sources"]
                if cfg.stage >= 1:
                    envelope["sources"][d] = source(self.docs[d])
                envelope["items"].append(item)
                # Reserve true flag while packing, then restore actual flag.
                envelope["budget_limited"] = True
                if count_units(_json(envelope)) <= budget:
                    selected.append(i)
                    covered |= self.chunk_index.keys[i] & query_keys
                else:
                    envelope["items"].pop()
                    if not previous_source:
                        envelope["sources"].pop(d, None)
            envelope["budget_limited"] = len(selected) < len(ranked)
        payload = _json(envelope)
        # Boolean false is occasionally a different token length for custom
        # counters; enforce the complete serialized envelope after finalizing.
        if not full and count_units(payload) > budget:
            raise BudgetTooSmallError("Final envelope exceeds budget")
        return {"payload": payload, "candidate_documents": candidates, "selected_sections": selected,
                "candidate_chunks": len(ranked), "omitted_chunks": len(ranked) - len(selected),
                "search_rounds": rounds, "stop_reason": stop, "search_trace": trace,
                "backend_calls_during_query": self.adapter.read_calls - source_calls_before,
                "additional_candidate_documents": max(0, len(candidates) - cfg.candidate_limit),
                "query_expansion_terms": expansion_terms,
                "source_reads_note": "All documents loaded at index construction; query uses the in-process index."}
