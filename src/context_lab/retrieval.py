"""Transparent A/B/C retrieval baselines, using only the Python standard library.

A replays the complete top-ranked candidate documents (three by default).
The candidate limit is fixed at engine construction and shared by A/B/C.
It deliberately reports, rather
than enforces, the requested budget: enforcing it would no longer reproduce a
full-document fetch.  B ranks verbatim sections within those documents and
packs complete sections into a bounded JSON payload.  C adds SQL filtering of
explicit temporal and adoption metadata, then uses B's ranking and packing.

The C database is local SQLite, not D1.  It uses ordinary metadata indexes;
lexical scoring is Python code.  A is a local replay proxy, not a measurement of
Notion search/network calls.  No baseline proves that an answer is correct or
that missing evidence does not exist.  Gold labels never enter this module.

Only ``result['payload']`` is context for a model.  Other result fields are
measurement instrumentation and are not additional returned context.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
import re
import sqlite3
from time import perf_counter
import unicodedata
from typing import Any


class BudgetTooSmallError(ValueError):
    """The budget cannot contain even the empty, explicit retrieval envelope."""


_ASCII = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")
_MODES = {"search", "current", "history"}
_SCOPES = {"shared", "private"}
_STATUSES = {"adopted", "proposed", "superseded", "na"}


def _features(text: str) -> Counter[str]:
    """Generic English words and Japanese character bigrams, with no query keys.

    Low-weight CJK unigrams retain a route for one-character queries.  ASCII
    terms retain identifiers such as D1, without a trigram minimum length.
    This is a lexical baseline; it does not claim semantic understanding.
    """
    normalized = unicodedata.normalize("NFKC", text).lower()
    features: Counter[str] = Counter()
    for word in _ASCII.findall(normalized):
        features["w:" + word] += 1.5
    for run in _CJK.findall(normalized):
        for char in run:
            features["u:" + char] += 0.1
        for index in range(len(run) - 1):
            features["b:" + run[index : index + 2]] += 1.0
    return features


def _combine(*parts: tuple[str, float]) -> Counter[str]:
    combined: Counter[str] = Counter()
    for text, multiplier in parts:
        for feature, count in _features(text).items():
            combined[feature] += count * multiplier
    return combined


def _scores(query: str, entries: list[tuple[Any, Counter[str]]]) -> list[tuple[Any, float]]:
    """Return positive lexical cosine scores with corpus-local IDF weights."""
    if not entries:
        return []
    query_features = _features(query)
    document_frequency: Counter[str] = Counter()
    for _, features in entries:
        document_frequency.update(features.keys())
    count = len(entries)

    def weighted(features: Counter[str]) -> dict[str, float]:
        return {
            term: math.log1p(frequency)
            * (math.log((count + 1) / (document_frequency.get(term, 0) + 1)) + 1)
            for term, frequency in features.items()
        }

    query_vector = weighted(query_features)
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    if not query_norm:
        return []
    results = []
    for entry, features in entries:
        vector = weighted(features)
        norm = math.sqrt(sum(value * value for value in vector.values()))
        if not norm:
            continue
        score = sum(value * vector.get(term, 0) for term, value in query_vector.items())
        score /= query_norm * norm
        if score > 0:
            results.append((entry, score))
    return sorted(results, key=lambda pair: (-pair[1], str(pair[0]["id"])))


def _date_value(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date or timestamp")
    try:
        # This experiment evaluates calendar-day validity, not sub-day ordering.
        parsed = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date in {field}: {value!r}") from exc
    return parsed.isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _unit_name(counter: Callable[[str], int]) -> str:
    if counter is len:
        return "unicode_chars"
    return str(getattr(counter, "unit_name", getattr(counter, "unit", "custom:" + getattr(counter, "__name__", type(counter).__name__))))


class RetrievalEngine:
    """A frozen corpus and an ephemeral indexed SQLite copy.

    ``as_of`` uses a date with inclusive valid_from and exclusive valid_to.
    C/current keeps adopted decisions only.  C/history with an explicit as_of
    filters validity but retains adoption labels, including superseded records.
    Historical adoption transitions are not inferred from a current status.
    C/search does not apply time or adoption filters.  All methods apply the
    same shared/private access rule before ranking.  ``actor`` is a supplied
    fixture identity; this experiment is not an authentication boundary.
    A deployed service must bind it to an authenticated caller.
    """

    def __init__(
        self, documents: Iterable[Mapping[str, Any]], candidate_limit: int = 3,
    ) -> None:
        started = perf_counter()
        if not isinstance(candidate_limit, int) or isinstance(candidate_limit, bool) or candidate_limit < 1:
            raise ValueError("candidate_limit must be a positive integer")
        self.candidate_limit = candidate_limit
        self.documents = deepcopy(list(documents))
        if not self.documents:
            raise ValueError("documents must not be empty")
        self._by_id: dict[str, dict[str, Any]] = {}
        section_ids: set[str] = set()
        for document in self.documents:
            doc_id = document.get("id")
            if not isinstance(doc_id, str) or not doc_id or doc_id in self._by_id:
                raise ValueError("Document IDs must be nonempty and unique")
            if document.get("scope") not in _SCOPES:
                raise ValueError(f"An explicit shared/private scope is required for {doc_id}")
            document.setdefault("owner", None)
            document.setdefault("title", doc_id)
            document.setdefault("source_url", "")
            document.setdefault("body", "")
            document.setdefault("sections", [])
            self._by_id[doc_id] = document
            for section in document["sections"]:
                section_id = section.get("id")
                if not isinstance(section_id, str) or not section_id or section_id in section_ids:
                    raise ValueError("Section IDs must be globally unique nonempty strings")
                section_ids.add(section_id)
                section.setdefault("heading", "")
                section.setdefault("text", "")
                section.setdefault("kind", "report")
                section.setdefault("adoption_status", "na")
                if section["adoption_status"] not in _STATUSES:
                    raise ValueError(f"Unsupported adoption_status for {section_id}")
                for name in ("valid_from", "valid_to"):
                    section[name] = _date_value(section.get(name), name)
                if section["valid_from"] and section["valid_to"] and section["valid_from"] >= section["valid_to"]:
                    raise ValueError(f"Invalid validity interval for {section_id}")
                if section["text"] and section["text"] not in document["body"]:
                    raise ValueError(f"Section {section_id} must be a verbatim span of its document body")

        self._db = sqlite3.connect(":memory:")
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                owner TEXT, metadata_json TEXT NOT NULL
            );
            CREATE INDEX documents_access ON documents(scope, owner);
            CREATE TABLE sections (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                kind TEXT NOT NULL, adoption_status TEXT NOT NULL,
                valid_from TEXT, valid_to TEXT, section_json TEXT NOT NULL
            );
            CREATE INDEX sections_document ON sections(document_id);
            CREATE INDEX sections_state ON sections(kind, adoption_status, valid_from, valid_to);
        """)
        with self._db:
            for document in self.documents:
                self._db.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?)",
                    (document["id"], document["scope"], document.get("owner"), _json({key: value for key, value in document.items() if key not in {"body", "raw_response", "sections"}})),
                )
                self._db.executemany(
                    "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(
                        section["id"], document["id"], section["kind"],
                        section["adoption_status"], section["valid_from"],
                        section["valid_to"], _json(section),
                    ) for section in document["sections"]],
                )
        self.index_build_ms = (perf_counter() - started) * 1000
        self.sqlite_version = sqlite3.sqlite_version
        self.document_count = len(self.documents)
        self.section_count = len(section_ids)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "RetrievalEngine":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _accessible(self, actor: str, scope: str | None) -> list[dict[str, Any]]:
        return [
            document for document in self.documents
            if (scope is None or document["scope"] == scope)
            and (
                document["scope"] == "shared"
                or (bool(actor) and bool(document.get("owner")) and document["owner"] == actor)
            )
        ]

    def _section_rows(
        self, method: str, candidates: list[dict[str, Any]], actor: str,
        scope: str | None, mode: str, as_of: str | None,
    ) -> list[dict[str, Any]]:
        if method == "B":
            return [dict(section, document_id=document["id"]) for document in candidates for section in document["sections"]]
        if not candidates:
            return []
        placeholders = ",".join("?" for _ in candidates)
        sql = f"""SELECT s.document_id, s.section_json
            FROM sections s JOIN documents d ON d.id=s.document_id
            WHERE d.id IN ({placeholders})
            AND (d.scope='shared' OR (d.scope='private' AND d.owner=? AND ?<>''))"""
        parameters: list[Any] = [document["id"] for document in candidates] + [actor, actor]
        if scope is not None:
            sql += " AND d.scope=?"
            parameters.append(scope)
        if mode == "current":
            sql += " AND (s.kind<>'decision' OR s.adoption_status='adopted')"
        if as_of is not None and mode in {"current", "history"}:
            sql += " AND (s.valid_from IS NULL OR s.valid_from<=?) AND (s.valid_to IS NULL OR s.valid_to>?)"
            parameters.extend([as_of, as_of])
        sql += " ORDER BY s.id"
        return [dict(json.loads(row["section_json"]), document_id=row["document_id"]) for row in self._db.execute(sql, parameters)]

    def _section_item(self, section: dict[str, Any]) -> dict[str, Any]:
        document = self._by_id[section["document_id"]]
        return {
            "document_id": document["id"], "section_id": section["id"],
            "title": document["title"], "heading": section["heading"],
            "source_url": document["source_url"],
            "recorded_at": document.get("recorded_at"),
            "verified_at": section.get("verified_at", document.get("verified_at")),
            "kind": section["kind"], "adoption_status": section["adoption_status"],
            "valid_from": section["valid_from"], "valid_to": section["valid_to"],
            "text": section["text"],
        }

    def retrieve(
        self, method: str, request: Mapping[str, Any], budget: int = 2000,
        count_units: Callable[[str], int] = len,
    ) -> dict[str, Any]:
        started = perf_counter()
        if method not in {"A", "B", "C"}:
            raise ValueError("method must be A, B, or C")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
            raise ValueError("budget must be a positive integer")
        query = request.get("text", "")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("request.text must be nonempty")
        actor = request.get("actor", "")
        if not isinstance(actor, str):
            raise ValueError("request.actor must be a string")
        scope = request.get("scope")
        if scope is not None and scope not in _SCOPES:
            raise ValueError("request.scope must be shared or private")
        mode = request.get("mode", "search")
        if mode not in _MODES:
            raise ValueError("request.mode must be search, current, or history")
        as_of = _date_value(request.get("as_of"), "as_of")
        if mode == "current" and as_of is None:
            as_of = datetime.now(timezone.utc).date().isoformat()

        visible = self._accessible(actor, scope)
        documents = _scores(query, [
            (document, _combine((document["title"], 2.0), (document["body"], 1.0)))
            for document in visible
        ])
        candidates = [document for document, _ in documents[:self.candidate_limit]]
        warnings = ["retrieval_only; missing_evidence_is_not_proof_of_absence"]
        if method == "A":
            warnings.append("full_document_replay_proxy; not_live_connector_measurement")
        if method == "C":
            warnings.append("local_sqlite_metadata_filter; not_D1_or_end_to_end_benchmark")
        if not candidates:
            warnings.append("no_positive_lexical_match")

        envelope: dict[str, Any] = {
            "method": method, "mode": mode, "as_of": as_of,
            "items": [], "budget_limited": False,
            "omitted_sections": 0, "warnings": warnings,
        }
        selected_sections: list[str] = []
        selected_documents: list[str] = []
        if method == "A":
            for document in candidates:
                content = document.get("raw_response") or document["body"]
                envelope["items"].append({
                    "document_id": document["id"], "title": document["title"],
                    "source_url": document["source_url"],
                    "recorded_at": document.get("recorded_at"),
                    "verified_at": document.get("verified_at"),
                    "source_format": "connector_response" if document.get("raw_response") else "body",
                    "text": content,
                })
                selected_documents.append(document["id"])
                selected_sections.extend(section["id"] for section in document["sections"] if section["text"] in content)
            payload = _json(envelope)
            if count_units(payload) > budget:
                warnings.append("full_document_baseline_exceeds_budget")
                payload = _json(envelope)
        else:
            # Score all candidate sections before structured filtering, so the
            # B/C IDF statistics are identical.  SQL then determines eligibility.
            all_sections = self._section_rows("B", candidates, actor, scope, mode, as_of)
            ranked = _scores(query, [
                (section, _combine(
                    (self._by_id[section["document_id"]]["title"], 0.5),
                    (section["heading"], 2.0), (section["text"], 1.0),
                )) for section in all_sections
            ])
            eligible = {section["id"] for section in self._section_rows(method, candidates, actor, scope, mode, as_of)}
            ranked = [(section, score) for section, score in ranked if section["id"] in eligible]
            envelope["omitted_sections"] = len(ranked)
            envelope["budget_limited"] = bool(ranked)
            if count_units(_json(envelope)) > budget:
                raise BudgetTooSmallError("Budget is smaller than the empty retrieval envelope")
            for section, _ in ranked:
                item = self._section_item(section)
                previous_limited = envelope["budget_limited"]
                envelope["items"].append(item)
                envelope["omitted_sections"] -= 1
                envelope["budget_limited"] = envelope["omitted_sections"] > 0
                if count_units(_json(envelope)) <= budget:
                    selected_sections.append(section["id"])
                    if section["document_id"] not in selected_documents:
                        selected_documents.append(section["document_id"])
                else:
                    envelope["items"].pop()
                    envelope["omitted_sections"] += 1
                    envelope["budget_limited"] = previous_limited
            payload = _json(envelope)

        returned_units = count_units(payload)
        return {
            "method": method, "payload": payload,
            "selected_sections": selected_sections,
            "selected_documents": selected_documents,
            "candidate_documents": [document["id"] for document in candidates],
            "returned_units": returned_units, "unit": _unit_name(count_units),
            "budget": budget, "budget_exceeded": returned_units > budget,
            "truncated": False, "omitted_sections": envelope["omitted_sections"],
            "warnings": list(warnings),
            "elapsed_ms": (perf_counter() - started) * 1000,
            "index_build_ms": self.index_build_ms,
        }
