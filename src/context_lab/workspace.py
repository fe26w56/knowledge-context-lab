"""A local, versioned knowledge workspace with lossless source snapshots.

Source pages and reviewed topic records are different objects. Import never
creates an approved decision. Callers are trusted local identities; a hosted
deployment needs its own authenticated identity and authorization boundary.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from .store import (KnowledgeStore, ValidationError, VersionConflict,
                    AccessDenied, NotFound, _json, _identifier)
from .context_policy import coverage_policy


def digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _source_key(page_id: str) -> str:
    _identifier(page_id, "page_id")
    return _identifier("source:" + page_id, "source record_id")


def _topic_key(topic_id: str) -> str:
    _identifier(topic_id, "topic_id")
    return _identifier("topic:" + topic_id, "topic record_id")


def _validate_page(page: Any) -> dict:
    if not isinstance(page, dict):
        raise ValidationError("each page must be an object")
    _source_key(page.get("id"))
    if not isinstance(page.get("title"), str) or not page["title"].strip():
        raise ValidationError("page title is required")
    if not isinstance(page.get("body"), str):
        raise ValidationError("page body must be a string")
    if not isinstance(page.get("properties", {}), dict):
        raise ValidationError("page properties must be an object")
    if page.get("scope") not in ("shared", "private"):
        raise ValidationError("explicit page scope is required")
    if page["scope"] == "private":
        _identifier(page.get("owner"), "private page owner")
    if page.get("truncated") or page.get("unknown_block_count", 0):
        raise ValidationError("incomplete source capture cannot be imported as complete")
    if isinstance(page.get("capture_coverage"), str) and page["capture_coverage"].startswith(
            "Connector-rendered page and metadata;"):
        _validate_notion_projection(page)
    # 'incomplete' describes unresolved work, not capture truncation.
    _json(page)
    return deepcopy(page)


def _parse_notion_snapshot(snapshot: dict, *, owner: str) -> dict:
    """Project one connector snapshot without recursively validating the page."""
    text = snapshot.get("text")
    if not isinstance(text, str):
        raise ValidationError("snapshot text is required")
    start_marker, end_marker = "<content>\n", "\n</content>\n</page>"
    start, end = text.find(start_marker), text.rfind(end_marker)
    if start < 0 or end < start:
        raise ValidationError("capture has no complete outer page content")
    prop_match = re.search(r"<properties>\s*\n([\s\S]*?)\n</properties>", text[:start])
    if not prop_match:
        raise ValidationError("page property capture is missing")
    try:
        props = json.loads(prop_match.group(1))
    except ValueError as exc:
        raise ValidationError("page property capture is invalid") from exc
    body = text[start + len(start_marker):end]
    resources = [{"kind": match.group(1), "url": match.group(2),
                  "capture_status": "reference_only"}
                 for match in re.finditer(
                     r'<(page|database|mention|image|file|pdf|video|audio)\b[^>]*?(?:url|source)="([^"]+)"',
                     body)]
    return {
        "id": snapshot.get("id"), "title": snapshot.get("title"),
        "url": snapshot.get("url"), "properties": props, "body": body,
        "scope": "private", "owner": owner,
        "edited_at": snapshot.get("page_last_edited_at"),
        "raw_capture": deepcopy(snapshot), "linked_resources": resources,
        "capture_coverage": "Connector-rendered page and metadata; linked/attached resources not downloaded.",
    }


def _validate_notion_projection(page: dict) -> None:
    raw = page.get("raw_capture")
    if not isinstance(raw, dict):
        raise ValidationError("connector capture must be an object")
    if raw.get("truncated") or raw.get("unknown_block_count", 0):
        raise ValidationError("connector capture is truncated or has unknown blocks")
    projected = _parse_notion_snapshot(raw, owner=page["owner"])
    for field in ("id", "title", "url", "properties", "body", "edited_at", "linked_resources"):
        if page.get(field) != projected.get(field):
            raise ValidationError(f"Notion capture projection mismatch: {field}")


def notion_pages(snapshots: list[dict], *, owner: str) -> list[dict]:
    """Adapt explicit connector captures without inferring their permissions.

    Captures are private to the importing caller. Native mentions, child links,
    attachments and the complete connector response are preserved. Linked
    resources are inventoried; preserving their URLs is not downloading them.
    """
    _identifier(owner, "owner")
    if not isinstance(snapshots, list):
        raise ValidationError("snapshots must be a list")
    pages = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise ValidationError("snapshot must be an object")
        if snapshot.get("truncated") or snapshot.get("unknown_block_count", 0):
            raise ValidationError("capture is truncated or has unknown blocks")
        page = _parse_notion_snapshot(snapshot, owner=owner)
        pages.append(_validate_page(page))
    return pages


def _sections(body: str) -> list[dict]:
    """Return verbatim ranges; offsets always refer to the original page."""
    matches = list(re.finditer(r"(?m)^#{1,6}[ \t]+(.+?)\s*$", body))
    result = []
    if not matches:
        return [{"heading": "", "start": 0, "end": len(body), "text": body}]
    if matches[0].start():
        end = matches[0].start()
        result.append({"heading": "", "start": 0, "end": end, "text": body[:end]})
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        result.append({"heading": match.group(1), "start": start, "end": end,
                       "text": body[start:end]})
    return result


_HISTORY = re.compile(r"履歴|以前|過去|旧(?:案|決定|運用|版|手順)|設計時点|history|previous|superseded", re.I)
_HISTORY_REQUEST = re.compile(r"履歴|以前|過去|旧|背景|経緯|理由|比較|history|previous|why|changed", re.I)


def _terms(text: str) -> set[str]:
    lowered = text.casefold()
    result = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", lowered))
    for word in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", lowered):
        result.update(word[i:i + 2] for i in range(len(word) - 1))
    return result


class Workspace:
    def __init__(self, path: str | Path, *, observer=None):
        self.store = KnowledgeStore(path)
        self.observer = observer

    def _observe(self, operation: str, request: str, actor: str, mode: str,
                 settings: dict, started: float, result=None, error: Exception | None = None) -> None:
        if self.observer is not None:
            self.observer.record(operation=operation, request=request, actor=actor, mode=mode,
                                 settings=settings, started=started, result=result, error=error)

    def import_pages(self, pages: list[dict], *, actor: str, request_id: str,
                     expected_versions: dict[str, int] | None = None) -> dict:
        """Validate the batch first, then resume-safe per-page commits.

        A receipt distinguishes unchanged and committed pages. A source update
        preserves prior versions and invalidates topic views by version binding.
        The batch is not advertised as one transaction.
        """
        _identifier(actor, "actor")
        _identifier(request_id, "request_id")
        if not isinstance(pages, list):
            raise ValidationError("pages must be a list")
        if expected_versions is not None and (
            not isinstance(expected_versions, dict) or any(
                not isinstance(k, str) or type(v) is not int or v < 0
                for k, v in expected_versions.items())
        ):
            raise ValidationError("expected_versions must map page IDs to nonnegative integers")
        expected_versions = expected_versions or {}
        clean = [_validate_page(page) for page in pages]
        if len({p["id"] for p in clean}) != len(clean):
            raise ValidationError("duplicate page IDs in one import")
        for page in clean:
            if page["scope"] == "private" and page["owner"] != actor:
                raise AccessDenied("private import must use the page owner identity")
        receipt = {"committed": [], "unchanged": [], "atomic_batch": False}
        for page in clean:
            key = _source_key(page["id"])
            sha = digest(page)
            content = {"kind": "source", "page": page, "sha256": sha}
            operation_id = "import:" + digest([request_id, page["id"]])
            try:
                current = self.store.get_current(key, actor=actor)
            except NotFound:
                current = None
            # A prior successful request must replay its original expected version.
            try:
                prior = self.store.request_status(operation_id, actor=actor)
            except NotFound:
                prior = None
            if not prior and current and current["content"] == content:
                receipt["unchanged"].append({"page_id": page["id"], "version": current["version"]})
                continue
            if prior:
                expected = expected_versions.get(page["id"], prior["version"] - 1)
            elif current:
                if page["id"] not in expected_versions:
                    raise VersionConflict("source correction requires an explicit expected version")
                expected = expected_versions[page["id"]]
            else:
                expected = expected_versions.get(page["id"], 0)
            result = self.store.commit(
                record_id=key, content=content,
                evidence=[{"source_id": page["id"], "source_revision": sha}],
                expected_version=expected,
                request_id=operation_id, actor=actor, scope=page["scope"],
                owner=page["owner"] if page["scope"] == "private" else None)
            receipt["committed"].append({**result, "page_id": page["id"]})
        return receipt

    def get_source(self, page_id: str, *, actor: str, version: int | None = None) -> dict:
        row = (self.store.get_current(_source_key(page_id), actor=actor) if version is None
               else self.store.get_revision(_source_key(page_id), version, actor=actor))
        return {"page": deepcopy(row["content"]["page"]), "version": row["version"],
                "sha256": row["content"]["sha256"], "revision_id": row["revision_id"]}

    def _visible_sources(self, actor: str) -> list[dict]:
        snapshot = self.store.read_snapshot(actor=actor)
        return [{"page": row["content"]["page"], "version": row["version"],
                 "sha256": row["content"]["sha256"], "revision_id": row["revision_id"]}
                for row in snapshot["records"] if row["content"].get("kind") == "source"]

    @staticmethod
    def search_sources(sources: list[dict], request: str, *, mode: str = "current",
                       candidate_pages: int = 6, ranking: str = "legacy") -> dict:
        """Common pipeline for exported file sources and SQLite source snapshots."""
        if not isinstance(request, str) or not request.strip():
            raise ValidationError("a nonempty request is required")
        if mode not in {"raw", "normalized", "current", "compact", "capture"}:
            raise ValidationError("mode must be raw, normalized, current, compact, or capture")
        if ranking not in {"legacy", "overlap", "bm25"}:
            raise ValidationError("ranking must be legacy, overlap, or bm25")
        if type(candidate_pages) is not int or not 1 <= candidate_pages <= 100:
            raise ValidationError("candidate_pages must be an integer between 1 and 100")
        query_terms = _terms(request)
        ranked = []
        bm25_scores = None
        if ranking == "bm25":
            from .history_retrieval import _bm25
            bm25_scores = _bm25(request, [page["title"] + "\n" + page["body"] for page in (s["page"] for s in sources)])
        for index, source in enumerate(sources):
            page = source["page"]
            title_terms = _terms(page["title"])
            body_terms = _terms(page["body"])
            named = {t for t in query_terms if re.fullmatch(r"[a-z][a-z0-9_-]{2,}", t)}
            if ranking == "bm25":
                score = bm25_scores[index]
            elif ranking == "overlap":
                score = len(query_terms & (title_terms | body_terms))
            else:
                score = (20 * len(named & title_terms)
                         + 3 * len(query_terms & title_terms) + len(query_terms & body_terms))
            if score:
                ranked.append((score, page["id"], source))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        results = []
        history_requested = bool(_HISTORY_REQUEST.search(request))
        for score, _, source in ranked[:candidate_pages]:
            page = source["page"]
            if mode == "raw":
                results.append({**deepcopy(source), "score": score})
                continue
            if mode == "capture":
                if "raw_capture" not in page:
                    raise ValidationError("capture mode requires raw_capture on every selected source")
                results.append({"source_id": page["id"], "source_version": source["version"],
                                "source_sha256": source["sha256"],
                                "capture": deepcopy(page["raw_capture"])})
                continue
            if mode == "compact":
                # The full body and all user metadata stay verbatim. Omit only
                # duplicate identity, storage digests and segmentation wrappers.
                packed = {k: deepcopy(v) for k, v in page.items() if k not in {"id", "body"}}
                packed.update(source_id=page["id"], source_version=source["version"], text=page["body"])
                results.append(packed)
                continue
            chunks = _sections(page["body"])
            omitted = []
            if mode == "current" and not history_requested:
                kept = []
                for chunk in chunks:
                    if _HISTORY.search(chunk["heading"]):
                        omitted.append({"heading": chunk["heading"], "start": chunk["start"],
                                        "end": chunk["end"]})
                    else:
                        kept.append(chunk)
                # No known current section means no implicit current-state inference.
                if kept:
                    chunks = kept
                else:
                    omitted = []
            results.append({
                "source_id": page["id"], "title": page["title"], "url": page.get("url"),
                "source_version": source["version"], "source_sha256": source["sha256"],
                "properties": deepcopy(page.get("properties", {})),
                "unresolved": page.get("incomplete"), "sections": chunks,
                "omitted_history": omitted,
            })
        return {"mode": mode, "history_requested": history_requested, "sources": results,
                "status": "found" if results else "not_found",
                "decision_policy": "Page metadata does not approve every paragraph. Check conditions and evidence."}

    def search(self, request: str, *, actor: str, mode: str = "current",
               candidate_pages: int = 6, ranking: str = "legacy") -> dict:
        started = time.perf_counter()
        settings = {"candidate_pages": candidate_pages, "ranking": ranking}
        try:
            result = self.search_sources(self._visible_sources(actor), request, mode=mode,
                                        candidate_pages=candidate_pages, ranking=ranking)
        except Exception as exc:
            self._observe("search", request, actor, mode, settings, started, error=exc)
            raise
        self._observe("search", request, actor, mode, settings, started, result=result)
        return result

    @staticmethod
    def context_sources(sources: list[dict], request: str, *, coverage: str = "auto",
                        candidate_pages: int = 6, ranking: str = "bm25") -> dict:
        """Build context from an actor-filtered visible source snapshot.

        ``sources`` must already be filtered for the requesting actor by the
        caller. This keeps file and SQLite adapters on the same formatting and
        coverage pipeline without making this pure transformation responsible
        for access control.
        """
        policy = coverage_policy(request, coverage)
        if ranking not in {"legacy", "overlap", "bm25"}:
            raise ValidationError("ranking must be legacy, overlap, or bm25")
        if type(candidate_pages) is not int or not 1 <= candidate_pages <= 100:
            raise ValidationError("candidate_pages must be an integer between 1 and 100")
        if policy["selected"] == "all":
            selected = []
            for source in sources:
                page = deepcopy(source["page"])
                packed = {k: v for k, v in page.items() if k not in {"id", "body"}}
                packed.update(source_id=page["id"], source_version=source["version"], text=page["body"])
                selected.append(packed)
        else:
            result = Workspace.search_sources(sources, request, mode="compact",
                                              candidate_pages=candidate_pages, ranking=ranking)
            selected = result["sources"]
        return {"policy": policy, "visible_source_count": len(sources),
                "returned_source_count": len(selected), "sources": selected}

    def context(self, request: str, *, actor: str, coverage: str = "auto",
                candidate_pages: int = 6, ranking: str = "bm25") -> dict:
        """Return full-body context under an explicit coverage policy.

        ``all`` means every currently visible source snapshot, not every item
        in the external world. No history heading or metadata is filtered.
        """
        started = time.perf_counter()
        settings = {"coverage": coverage, "candidate_pages": candidate_pages, "ranking": ranking}
        try:
            result = self.context_sources(self._visible_sources(actor), request,
                                          coverage=coverage, candidate_pages=candidate_pages,
                                          ranking=ranking)
        except Exception as exc:
            self._observe("context", request, actor, "context", settings, started, error=exc)
            raise
        self._observe("context", request, actor, "context", settings, started, result=result)
        return result

    def _checked_evidence(self, reference: dict, *, actor: str, scope: str,
                          require_current: bool = True) -> dict:
        if not isinstance(reference, dict):
            raise ValidationError("evidence must be an object")
        source = self.get_source(reference.get("source_id"), actor=actor,
                                 version=reference.get("source_version"))
        if type(reference.get("source_version")) is not int:
            raise ValidationError("evidence must pin an integer source version")
        start, end = reference.get("start"), reference.get("end")
        body = source["page"]["body"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body):
            raise ValidationError("invalid evidence character range")
        quote = reference.get("quote")
        if not isinstance(quote, str) or body[start:end] != quote:
            raise ValidationError("evidence quote does not match the pinned source")
        if scope == "shared" and source["page"]["scope"] != "shared":
            raise AccessDenied("shared topic cannot include private evidence")
        head = self.get_source(reference["source_id"], actor=actor)
        if require_current and head["version"] != reference["source_version"]:
            raise VersionConflict("review the current source before publishing a topic")
        return {**deepcopy(reference), "source_revision": source["revision_id"],
                "source_sha256": source["sha256"]}

    def publish_topic(self, topic_id: str, payload: dict, evidence: list[dict], *,
                      actor: str, expected_version: int, request_id: str,
                      scope: str = "shared", owner: str | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ValidationError("topic payload must be an object")
        for field in ("title", "summary"):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise ValidationError(f"{field} is required")
        if payload.get("state") not in {"proposed", "adopted", "reference", "superseded"}:
            raise ValidationError("explicit topic state is required")
        for field in ("conditions", "task_refs"):
            if not isinstance(payload.get(field), list) or not all(
                    isinstance(item, str) and item.strip() for item in payload[field]):
                raise ValidationError(f"{field} must be a list of nonempty strings")
        try:
            date.fromisoformat(payload["as_of"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("as_of must be an ISO date") from exc
        if not isinstance(evidence, list) or not evidence:
            raise ValidationError("reviewed topic needs exact source evidence")
        try:
            prior = self.store.request_status(request_id, actor=actor)
        except NotFound:
            prior = None
        checked = [self._checked_evidence(ref, actor=actor, scope=scope,
                                         require_current=prior is None) for ref in evidence]
        approval = payload.get("approval")
        if payload["state"] == "adopted":
            if not isinstance(approval, dict) or not isinstance(approval.get("confirmed_by"), str) or not approval["confirmed_by"].strip():
                raise ValidationError("adopted state requires an explicit approval record")
            checked_approval = self._checked_evidence(approval, actor=actor, scope=scope,
                                                       require_current=prior is None)
            if not any(all(ref.get(k) == checked_approval.get(k)
                           for k in ("source_id", "source_version", "start", "end"))
                       for ref in checked):
                checked.append(checked_approval)
        content = {"kind": "topic", "topic_id": topic_id, "payload": deepcopy(payload)}
        return self.store.commit(record_id=_topic_key(topic_id), content=content,
                                 evidence=checked, expected_version=expected_version,
                                 request_id=request_id, actor=actor, scope=scope, owner=owner)

    def get_topic(self, topic_id: str, *, actor: str, version: int | None = None) -> dict:
        row = (self.store.get_current(_topic_key(topic_id), actor=actor) if version is None
               else self.store.get_revision(_topic_key(topic_id), version, actor=actor))
        stale = []
        for ref in row["evidence"]:
            try:
                head = self.get_source(ref["source_id"], actor=actor)
                if head["version"] != ref["source_version"] or head["sha256"] != ref["source_sha256"]:
                    stale.append({"source_id": ref["source_id"], "reviewed_version": ref["source_version"],
                                  "current_version": head["version"]})
            except NotFound:
                stale.append({"source_id": ref["source_id"], "unavailable": True})
        result = {"topic_id": topic_id, "version": row["version"],
                  "status": "historical" if version is not None else "needs_review" if stale else "current",
                  "source_changes": stale}
        if not stale or version is not None:
            result.update(payload=row["content"]["payload"], evidence=row["evidence"])
        # Stale current summaries are withheld, not returned as an actionable decision.
        return result

    def list_topics(self, *, actor: str) -> dict:
        snapshot = self.store.read_snapshot(actor=actor)
        ids = [r["content"]["topic_id"] for r in snapshot["records"]
               if r["content"].get("kind") == "topic"]
        return {"topics": [self.get_topic(topic_id, actor=actor) for topic_id in ids]}

    def export_bundle(self, *, actor: str) -> dict:
        """Export visible histories and request receipts, preserving exact data."""
        _identifier(actor, "actor")
        with self.store._connection() as db:
            db.execute("BEGIN")
            keys = [row[0] for row in db.execute(
                "SELECT record_id FROM revisions WHERE scope='shared' OR owner=? GROUP BY record_id",
                (actor,))]
            tables = {}
            for table in ("revisions", "heads", "requests"):
                ordering = "record_id" if table == "heads" else "record_id, version"
                rows = db.execute(f"SELECT * FROM {table} ORDER BY {ordering}").fetchall()
                tables[table] = [dict(row) for row in rows if row["record_id"] in keys]
            db.execute("COMMIT")
        bundle = {"format": "context-workspace-v1", "tables": tables}
        return {**bundle, "sha256": digest(bundle)}

    @classmethod
    def restore_bundle(cls, bundle: dict, destination: str | Path) -> "Workspace":
        """Restore an audited export to a new database; never overwrite a store."""
        if not isinstance(bundle, dict) or bundle.get("format") != "context-workspace-v1":
            raise ValidationError("unsupported bundle")
        bare = {"format": bundle["format"], "tables": bundle.get("tables")}
        if bundle.get("sha256") != digest(bare):
            raise ValidationError("bundle integrity mismatch")
        tables = bundle.get("tables")
        if not isinstance(tables, dict) or set(tables) != {"revisions", "heads", "requests"}:
            raise ValidationError("bundle tables are incomplete")
        if Path(destination).exists():
            raise ValidationError("restore destination must not exist")
        # Validate each historical payload and its bound retry identity first.
        revisions = {}
        for row in tables["revisions"]:
            key = (row["record_id"], row["version"])
            if key in revisions:
                raise ValidationError("duplicate revision")
            content = json.loads(row["content_json"])
            if content.get("kind") == "source":
                page = _validate_page(content["page"])
                if content.get("sha256") != digest(page) or row["record_id"] != _source_key(page["id"]):
                    raise ValidationError("source hash or identity mismatch")
            elif content.get("kind") == "topic":
                if row["record_id"] != _topic_key(content["topic_id"]):
                    raise ValidationError("topic identity mismatch")
            else:
                raise ValidationError("unsupported record kind")
            revisions[key] = row
        for req in tables["requests"]:
            row = revisions.get((req["record_id"], req["version"]))
            if row is None:
                raise ValidationError("request points to missing revision")
            expected = digest({
                "record_id": row["record_id"], "content": json.loads(row["content_json"]),
                "evidence": json.loads(row["evidence_json"]), "expected_version": row["version"] - 1,
                "actor": req["actor"], "scope": row["scope"], "owner": row["owner"],
            })
            if expected != req["payload_hash"]:
                raise ValidationError("request identity hash mismatch")
        for head in tables["heads"]:
            versions = sorted(v for key, v in revisions if key == head["record_id"])
            if versions != list(range(1, head["current_version"] + 1)):
                raise ValidationError("revision history is not contiguous")
        restored = cls(destination)
        with restored.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                for table, columns in (
                    ("revisions", ("record_id", "version", "content_json", "evidence_json", "scope",
                                   "owner", "authored_by", "created_at")),
                    ("heads", ("record_id", "current_version")),
                    ("requests", ("request_id", "payload_hash", "actor", "record_id", "version", "created_at")),
                ):
                    for row in tables[table]:
                        if set(row) != set(columns):
                            raise ValidationError("unexpected export columns")
                        db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                   [row[key] for key in columns])
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValidationError("restored references are invalid")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return restored
