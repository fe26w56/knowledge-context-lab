"""Consistent, access-controlled read snapshots for retrieval.

Snapshots are local SQLite observations only.  A snapshot is one read
transaction over the current heads visible to an actor; it is not a claim of
distributed or D1 transaction semantics.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping

from .store import KnowledgeStore, ValidationError, _identifier


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def read_snapshot(
    store: KnowledgeStore,
    *,
    actor: str,
    record_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Read visible current heads in one SQLite read transaction.

    Private rows not owned by ``actor`` are omitted, including from the
    manifest.  Returned data is detached from SQLite and callers may mutate
    it without changing a later read or the store.
    """
    _identifier(actor, "actor")
    requested = None
    if record_ids is not None:
        requested = list(record_ids)
        for record_id in requested:
            _identifier(record_id, "record_id")
        if len(requested) != len(set(requested)):
            raise ValidationError("record_ids must be unique")

    with store._connection() as connection:
        connection.execute("BEGIN")
        try:
            query = (
                "SELECT r.* FROM heads h JOIN revisions r "
                "ON r.record_id=h.record_id AND r.version=h.current_version"
            )
            params: list[Any] = []
            clauses = ["(r.scope='shared' OR r.owner=?)"]
            params.append(actor)
            if requested is not None:
                if not requested:
                    clauses.append("1=0")
                else:
                    clauses.append("r.record_id IN (" + ",".join("?" for _ in requested) + ")")
                    params.extend(requested)
            query += " WHERE " + " AND ".join(clauses) + " ORDER BY r.record_id"
            rows = connection.execute(query, params).fetchall()
            records = [store._revision(row) for row in rows]
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    manifest = []
    for record in records:
        manifest.append({
            "record_id": record["record_id"],
            "version": record["version"],
            "revision_id": record["revision_id"],
            "scope": record["scope"],
            "owner": record["owner"],
            "content_sha256": _sha(record["content"]),
            "evidence_sha256": _sha(record["evidence"]),
        })
    return {
        "schema_version": 1,
        "actor": actor,
        "records": deepcopy(records),
        "manifest": deepcopy(manifest),
        "snapshot_sha256": _sha(manifest),
    }


def documents_from_snapshot(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build retrieval documents, binding identity to the store revision.

    Document content may carry ordinary retrieval fields, but cannot override
    authoritative record identity, revision, scope, or owner metadata.
    """
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("records"), list):
        raise ValidationError("snapshot must contain a records list")
    manifest = snapshot.get("manifest")
    if not isinstance(manifest, list) or len(manifest) != len(snapshot["records"]):
        raise ValidationError("snapshot manifest does not match records")
    by_id = {item.get("record_id"): item for item in manifest if isinstance(item, Mapping)}
    if len(by_id) != len(manifest) or snapshot.get("snapshot_sha256") != _sha(manifest):
        raise ValidationError("snapshot manifest integrity check failed")
    actor = snapshot.get("actor")
    if not isinstance(actor, str) or not actor:
        raise ValidationError("snapshot actor is required")
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in snapshot["records"]:
        if not isinstance(record, Mapping):
            raise ValidationError("snapshot records must be objects")
        record_id = record.get("record_id")
        version = record.get("version")
        revision_id = record.get("revision_id")
        scope = record.get("scope")
        owner = record.get("owner")
        if not isinstance(record_id, str) or not record_id or record_id in seen:
            raise ValidationError("snapshot record IDs must be unique nonempty strings")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValidationError("snapshot versions must be positive integers")
        if revision_id != f"{record_id}@{version}":
            raise ValidationError("snapshot revision_id does not match record identity")
        entry = by_id.get(record_id)
        if entry is None or any(entry.get(key) != record.get(key)
                                for key in ("record_id", "version", "revision_id", "scope", "owner")):
            raise ValidationError("snapshot manifest entry does not match record")
        if scope == "private" and owner != actor:
            raise ValidationError("snapshot contains a private record outside its actor scope")
        if scope not in {"shared", "private"} or (scope == "private" and not owner):
            raise ValidationError("snapshot scope/owner is invalid")
        content = record.get("content")
        if not isinstance(content, Mapping) or not content:
            raise ValidationError("snapshot content must be a nonempty object")
        if entry["content_sha256"] != _sha(content) or entry["evidence_sha256"] != _sha(record.get("evidence")):
            raise ValidationError("snapshot content or evidence digest mismatch")
        for key, expected in (("id", record_id), ("record_id", record_id),
                              ("revision_id", revision_id), ("version", version),
                              ("scope", scope), ("owner", owner)):
            if key in content and content[key] != expected:
                raise ValidationError(f"content {key} conflicts with authoritative snapshot metadata")
        document = deepcopy(dict(content))
        document.update(id=record_id, revision_id=revision_id, version=version,
                        scope=scope, owner=owner)
        documents.append(document)
        seen.add(record_id)
    return documents


def retrieval_documents(
    store: KnowledgeStore, *, actor: str, record_ids: Iterable[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a snapshot and return its manifest plus defensive retrieval copies."""
    snapshot = read_snapshot(store, actor=actor, record_ids=record_ids)
    return snapshot, documents_from_snapshot(snapshot)

