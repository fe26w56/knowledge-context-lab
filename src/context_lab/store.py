"""Local SQLite experiment for revision and retry semantics.

This module does not implement HTTP authentication, D1 transactions, replication,
failover, or a taskflow completion endpoint. ``actor`` is supplied by a trusted
caller; a production API must derive it from authenticated credentials.

Persisted revisions and successful request records are append-only. Evidence
references are preserved but their external content/existence is not verified.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


APPLICATION_ID = 0x4B434C31  # KCL1: do not silently adopt an unrelated database.
SCHEMA_VERSION = 1


class StoreError(Exception):
    """Base class for expected store failures."""


class ValidationError(StoreError):
    pass


class VersionConflict(StoreError):
    pass


class IdempotencyConflict(StoreError):
    pass


class AccessDenied(StoreError):
    pass


class NotFound(StoreError):
    """Also used for records the caller may not read."""


class StoreSchemaError(StoreError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS revisions (
    record_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('shared', 'private')),
    owner TEXT,
    authored_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (record_id, version),
    CHECK ((scope = 'shared' AND owner IS NULL)
        OR (scope = 'private' AND owner IS NOT NULL AND length(owner) > 0))
);
CREATE TABLE IF NOT EXISTS heads (
    record_id TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK (current_version >= 1),
    FOREIGN KEY (record_id, current_version)
        REFERENCES revisions(record_id, version)
);
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    actor TEXT NOT NULL,
    record_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (record_id, version) REFERENCES revisions(record_id, version)
);
CREATE TRIGGER IF NOT EXISTS revisions_no_update
BEFORE UPDATE ON revisions BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS revisions_no_delete
BEFORE DELETE ON revisions BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS requests_no_update
BEFORE UPDATE ON requests BEGIN
    SELECT RAISE(ABORT, 'successful requests are immutable');
END;
CREATE TRIGGER IF NOT EXISTS requests_no_delete
BEFORE DELETE ON requests BEGIN
    SELECT RAISE(ABORT, 'successful requests are immutable');
END;
CREATE TRIGGER IF NOT EXISTS heads_monotonic
BEFORE UPDATE ON heads
WHEN NEW.record_id <> OLD.record_id
  OR NEW.current_version <> OLD.current_version + 1
BEGIN
    SELECT RAISE(ABORT, 'head must advance by one version');
END;
"""


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValidationError(f"{name} must be a nonempty string of <= 256 characters")
    return value


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("payload must contain finite, JSON-serializable values") from exc


class KnowledgeStore:
    """A file-backed local prototype. Each operation opens its own connection.

    Shared records are readable/writable by all trusted callers. Private records
    are readable/writable only by their owner. Scope and owner cannot change
    through ``commit``: publishing private history needs a separate reviewed flow.
    """

    def __init__(self, path: str | Path, *, timeout: float = 10.0) -> None:
        if str(path) == ":memory:":
            raise ValidationError("use a file path; connections are per operation")
        self.path = Path(path).resolve()
        self.timeout = timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if tables and (app_id != APPLICATION_ID or version != SCHEMA_VERSION):
                raise StoreSchemaError("refusing to adopt an unrelated or unsupported database")
            if version not in (0, SCHEMA_VERSION) or app_id not in (0, APPLICATION_ID):
                raise StoreSchemaError("unsupported database identity or schema version")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        # The experiment uses FULL sync; filesystem/hardware failure durability
        # is not established by the unit tests.
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _allowed(row: sqlite3.Row, actor: str) -> bool:
        return row["scope"] == "shared" or row["owner"] == actor

    @staticmethod
    def _result(row: Mapping[str, Any], *, replayed: bool) -> dict[str, Any]:
        return {
            "record_id": row["record_id"],
            "version": row["version"],
            "revision_id": f"{row['record_id']}@{row['version']}",
            "request_id": row["request_id"],
            "replayed": replayed,
        }

    @staticmethod
    def _revision(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "record_id": row["record_id"], "version": row["version"],
            "revision_id": f"{row['record_id']}@{row['version']}",
            "content": json.loads(row["content_json"]),
            "evidence": json.loads(row["evidence_json"]),
            "scope": row["scope"], "owner": row["owner"],
            "authored_by": row["authored_by"], "created_at": row["created_at"],
        }

    def commit(
        self,
        *,
        record_id: str,
        content: Mapping[str, Any],
        evidence: Sequence[Mapping[str, Any]],
        expected_version: int,
        request_id: str,
        actor: str,
        scope: str = "shared",
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Atomically append a revision, advance its head, and record the request.

        Use expected_version=0 to create. Retrying must preserve the complete
        original payload, including expected_version, even if the head advanced.
        request_id is globally unique within this store. A successful repeated
        request returns its original revision; it does not require the old head
        still to be current. This supports a lost acknowledgement.
        """
        _identifier(record_id, "record_id")
        _identifier(request_id, "request_id")
        _identifier(actor, "actor")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValidationError("expected_version must be a nonnegative integer")
        if scope not in {"shared", "private"}:
            raise ValidationError("scope must be shared or private")
        if scope == "private":
            _identifier(owner, "owner")
            if owner != actor:
                raise AccessDenied("a private record may only be written by its owner")
        elif owner is not None:
            raise ValidationError("shared records must have owner=None")
        if not isinstance(content, Mapping) or not content:
            raise ValidationError("content must be a nonempty JSON object")
        if not isinstance(evidence, (list, tuple)) or not evidence:
            raise ValidationError("at least one versioned evidence reference is required")
        for reference in evidence:
            if not isinstance(reference, Mapping):
                raise ValidationError("evidence references must be JSON objects")
            _identifier(reference.get("source_id"), "evidence.source_id")
            _identifier(reference.get("source_revision"), "evidence.source_revision")
        content_json = _json(dict(content))
        evidence_json = _json([dict(reference) for reference in evidence])
        canonical_request = _json({
            "record_id": record_id, "content": json.loads(content_json),
            "evidence": json.loads(evidence_json), "expected_version": expected_version,
            "actor": actor, "scope": scope, "owner": owner,
        })
        payload_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior_request = connection.execute(
                    "SELECT * FROM requests WHERE request_id=?", (request_id,)
                ).fetchone()
                if prior_request is not None:
                    if prior_request["payload_hash"] != payload_hash or prior_request["actor"] != actor:
                        raise IdempotencyConflict("request_id was already used with another payload")
                    result = self._result(prior_request, replayed=True)
                    connection.execute("COMMIT")
                    return result

                current = connection.execute(
                    "SELECT r.* FROM heads h JOIN revisions r "
                    "ON r.record_id=h.record_id AND r.version=h.current_version "
                    "WHERE h.record_id=?", (record_id,)
                ).fetchone()
                if current is not None:
                    if not self._allowed(current, actor):
                        raise AccessDenied("record is not writable by this actor")
                    if current["scope"] != scope or current["owner"] != owner:
                        raise ValidationError("scope/owner changes require a separate publication flow")
                current_version = current["version"] if current is not None else 0
                if current_version != expected_version:
                    raise VersionConflict(
                        f"expected version {expected_version}; current version is {current_version}"
                    )
                version = current_version + 1
                connection.execute(
                    "INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (record_id, version, content_json, evidence_json, scope, owner, actor, now),
                )
                connection.execute(
                    "INSERT INTO heads(record_id,current_version) VALUES (?,?) "
                    "ON CONFLICT(record_id) DO UPDATE SET current_version=excluded.current_version",
                    (record_id, version),
                )
                connection.execute(
                    "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)",
                    (request_id, payload_hash, actor, record_id, version, now),
                )
                result = self._result({"record_id": record_id, "version": version,
                                       "request_id": request_id}, replayed=False)
                connection.execute("COMMIT")
                return result
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get_current(self, record_id: str, *, actor: str) -> dict[str, Any]:
        _identifier(record_id, "record_id")
        _identifier(actor, "actor")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT r.* FROM heads h JOIN revisions r "
                "ON r.record_id=h.record_id AND r.version=h.current_version "
                "WHERE h.record_id=?", (record_id,)
            ).fetchone()
        if row is None or not self._allowed(row, actor):
            raise NotFound("record not found or not readable")
        return self._revision(row)

    def get_revision(self, record_id: str, version: int, *, actor: str) -> dict[str, Any]:
        _identifier(record_id, "record_id")
        _identifier(actor, "actor")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError("version must be a positive integer")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE record_id=? AND version=?", (record_id, version)
            ).fetchone()
        if row is None or not self._allowed(row, actor):
            raise NotFound("revision not found or not readable")
        return self._revision(row)

    def request_status(self, request_id: str, *, actor: str) -> dict[str, Any]:
        """Resolve an uncertain write without disclosing another actor's request."""
        _identifier(request_id, "request_id")
        _identifier(actor, "actor")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM requests WHERE request_id=? AND actor=?", (request_id, actor)
            ).fetchone()
        if row is None:
            raise NotFound("request not found or not readable")
        return self._result(row, replayed=True)

    def read_snapshot(self, *, actor: str, record_ids=None) -> dict[str, Any]:
        """Read current visible heads in one transaction; see ``snapshot``."""
        from .snapshot import read_snapshot
        return read_snapshot(self, actor=actor, record_ids=record_ids)

    def backup_to(self, destination: str | Path) -> Path:
        """Create a consistent SQLite backup at a new path, without overwriting."""
        return self._copy_database(self.path, destination)

    @classmethod
    def restore_from(cls, backup: str | Path, destination: str | Path) -> "KnowledgeStore":
        """Restore a verified KCL backup to a new path; the source is read-only."""
        restored_path = cls._copy_database(Path(backup).resolve(), destination)
        return cls(restored_path)

    @staticmethod
    def _copy_database(source: Path, destination: str | Path) -> Path:
        destination = Path(destination).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents accidentally replacing an existing database.
        with destination.open("xb"):
            pass
        try:
            source_connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            try:
                app_id = source_connection.execute("PRAGMA application_id").fetchone()[0]
                version = source_connection.execute("PRAGMA user_version").fetchone()[0]
                if app_id != APPLICATION_ID or version != SCHEMA_VERSION:
                    raise StoreSchemaError("backup source is not a supported knowledge store")
                target_connection = sqlite3.connect(destination)
                try:
                    source_connection.backup(target_connection)
                    if target_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise StoreSchemaError("backup integrity check failed")
                    if target_connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise StoreSchemaError("backup foreign key check failed")
                finally:
                    target_connection.close()
            finally:
                source_connection.close()
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return destination
