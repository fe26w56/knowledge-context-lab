"""Durable client-side receiver for reader handoff packets.

The receiver is deliberately small and transport agnostic.  A bot supplies a
callable that invokes the remote ``read_changes`` and ``ack_changes`` tools.
The reconstructed pages are committed to a private SQLite database before an
acknowledgement is sent, so a lost response can be retried safely.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable

import fcntl  # Supported deployment targets: Linux and macOS.

from .handoff_delta import apply_update, snapshot_digest


class RemoteToolError(RuntimeError):
    """A tool ran and rejected a request (distinct from transport failure)."""


class BotReceiver:
    """Persist and apply one bot's handoff stream.

    ``call`` receives a tool name (``read_changes`` or ``ack_changes``) and an
    argument mapping and must return the decoded tool result.  It may raise on
    transport failures; those failures leave the pending packet on disk.
    """

    def __init__(self, directory: Path, *, source: str, actor: str,
                 reader: str, scope: str,
                 call: Callable[[str, dict[str, Any]], dict[str, Any]]):
        values = (source, actor, reader, scope)
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("source, actor, reader, and scope are required")
        if not callable(call):
            raise ValueError("call must be callable")
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.stat().st_mode & 0o077:
            raise ValueError("receiver state directory must be private (mode 0700)")
        identity = json.dumps([source, actor, reader, scope], ensure_ascii=False,
                              separators=(",", ":"))
        name = hashlib.sha256(identity.encode()).hexdigest()
        self.path = self.directory / (name + ".sqlite3")
        self._lock_path = self.directory / (name + ".lock")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self.source, self.actor, self.reader, self.scope, self.call = values[0], values[1], values[2], values[3], call
        self._lock = threading.RLock()
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS receiver_pages (
                page_id TEXT PRIMARY KEY,
                pages TEXT NOT NULL,
                head TEXT NOT NULL,
                pending_receipt TEXT,
                pending_head TEXT,
                pending_packet TEXT)""")

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def _row(self, page_id: str) -> sqlite3.Row | None:
        with self._transaction() as db:
            return db.execute("SELECT * FROM receiver_pages WHERE page_id=?", (page_id,)).fetchone()

    def _pages(self, row: sqlite3.Row | None) -> dict[str, str] | None:
        if row is None:
            return None
        try:
            pages = json.loads(row["pages"])
            if not isinstance(pages, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                  for k, v in pages.items()):
                raise ValueError
            if snapshot_digest(pages, principal=self.actor, scope=self.scope) != row["head"]:
                raise ValueError("receiver state integrity check failed")
            return pages
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("receiver state is corrupt; request a fresh snapshot") from exc

    def _invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        value = self.call(name, args)
        if not isinstance(value, dict):
            raise ValueError(f"{name} returned an invalid envelope")
        if value.get("isError"):
            raise RemoteToolError(str(value.get("error") or value.get("message") or f"{name} failed"))
        return value

    @contextmanager
    def _process_lock(self):
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        handle = os.fdopen(fd, "a+", encoding="ascii")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    @staticmethod
    def _valid_key(key: str, page_id: str) -> bool:
        return key in {f"body/{page_id}", f"metadata/{page_id}"}

    @staticmethod
    def _validate_packet(page_id: str, offer: dict[str, Any]) -> dict[str, Any]:
        if offer.get("page_id") != page_id or not isinstance(offer.get("receipt"), str) or not offer["receipt"]:
            raise ValueError("handoff envelope has an unexpected page")
        packet = offer.get("packet")
        if not isinstance(packet, dict) or packet.get("mode") not in {"snapshot", "delta"}:
            raise ValueError("handoff packet is invalid")
        if not isinstance(packet.get("head"), str) or not packet["head"]:
            raise ValueError("handoff packet has no integrity head")
        if packet["mode"] == "snapshot":
            pages = packet.get("pages")
            if not isinstance(pages, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                  for k, v in pages.items()):
                raise ValueError("snapshot packet has invalid pages")
            if any(not BotReceiver._valid_key(k, page_id) for k in pages):
                raise ValueError("snapshot packet contains an unauthorized document key")
        else:
            for key in ("base", "purge", "added", "patches"):
                if key not in packet:
                    raise ValueError("delta packet is incomplete")
            if not isinstance(packet["purge"], list) or not isinstance(packet["added"], dict) or not isinstance(packet["patches"], dict):
                raise ValueError("delta packet has invalid fields")
            keys = list(packet["purge"]) + list(packet["added"]) + list(packet["patches"])
            if any(not isinstance(k, str) or not BotReceiver._valid_key(k, page_id) for k in keys):
                raise ValueError("delta packet contains an unauthorized document key")
        return packet

    def _stage(self, page_id: str, offer: dict[str, Any], previous: dict[str, str] | None) -> dict[str, str]:
        packet = self._validate_packet(page_id, offer)
        updated = apply_update(previous, packet, principal=self.actor, scope=self.scope)
        with self._transaction() as db:
            db.execute("""INSERT INTO receiver_pages(page_id,pages,head,pending_receipt,pending_head,pending_packet)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(page_id) DO UPDATE SET pages=excluded.pages, head=excluded.head,
                           pending_receipt=excluded.pending_receipt, pending_head=excluded.pending_head,
                           pending_packet=excluded.pending_packet""",
                       (page_id, json.dumps(updated, ensure_ascii=False, sort_keys=True), packet["head"],
                        offer["receipt"], packet["head"], json.dumps(packet, ensure_ascii=False, sort_keys=True)))
        return updated

    def _ack(self, page_id: str, receipt: str, head: str) -> None:
        result = self._invoke("ack_changes", {"page_id": page_id, "receipt": receipt, "head": head})
        if result.get("acknowledged") is not True or result.get("page_id") != page_id or result.get("head") != head:
            raise RemoteToolError("acknowledgement response failed validation")
        with self._transaction() as db:
            db.execute("UPDATE receiver_pages SET pending_receipt=NULL,pending_head=NULL,pending_packet=NULL WHERE page_id=? AND pending_receipt=?",
                       (page_id, receipt))

    def _sync_locked(self, page_id: str, fresh: bool = False) -> dict[str, Any]:
        if not isinstance(page_id, str) or not page_id.strip() or type(fresh) is not bool:
            raise ValueError("page_id must be a nonempty string and fresh must be boolean")
        with self._lock:
            row = self._row(page_id)
            try:
                previous = self._pages(row)
            except ValueError:
                previous = None
                fresh = True
            if previous is None:
                fresh = True
            pending = bool(previous is not None and row is not None and row["pending_receipt"])
            if pending:
                try:
                    self._ack(page_id, row["pending_receipt"], row["pending_head"])
                    pending = False
                except RemoteToolError:
                    fresh = True
                except Exception:
                    # Transport failure leaves the staged packet untouched.
                    raise
            offer = self._invoke("read_changes", {"page_id": page_id, "fresh": fresh})
            packet = self._validate_packet(page_id, offer)
            if packet["mode"] == "delta" and (previous is None or packet["base"] != snapshot_digest(previous, principal=self.actor, scope=self.scope)):
                # The server may have been restored from an older backup while
                # this bot retained a newer state. Reconcile from a snapshot.
                offer = self._invoke("read_changes", {"page_id": page_id, "fresh": True})
                packet = self._validate_packet(page_id, offer)
                if packet["mode"] != "snapshot":
                    raise ValueError("fresh read did not return a snapshot")
                fresh = True
            base = None if fresh or previous is None else previous
            updated = self._stage(page_id, offer, base)
            self._ack(page_id, offer["receipt"], packet["head"])
            return {"page_id": page_id, "head": packet["head"],
                    "changed": updated != previous,
                    "acknowledged": True, "packet": copy.deepcopy(packet)}

    def sync(self, page_id: str, fresh: bool = False) -> dict[str, Any]:
        with self._lock:
            with self._process_lock():
                return self._sync_locked(page_id, fresh)

    def local_page(self, page_id: str) -> dict[str, str] | None:
        if not isinstance(page_id, str) or not page_id.strip():
            raise ValueError("page_id must be a nonempty string")
        with self._lock:
            return copy.deepcopy(self._pages(self._row(page_id)))

    def known_pages(self) -> list[str]:
        """Return locally retained page IDs for hub reconciliation."""
        with self._lock:
            with self._transaction() as db:
                rows = db.execute("SELECT page_id FROM receiver_pages ORDER BY page_id").fetchall()
            return [str(row[0]) for row in rows]

