"""Persistent delivery and acknowledgement for one trusted MCP reader."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Callable

from .handoff_delta import make_update, snapshot_digest


def serialize_reply(reply: dict) -> str:
    """The JSON text carried by the hub's read_changes MCP result."""
    return json.dumps(reply, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reference_token_counter() -> Callable[[str], int]:
    import tiktoken
    encoding = tiktoken.get_encoding("o200k_base")
    return lambda text: len(encoding.encode_ordinary(text))


class ReaderHandoff:
    def __init__(self, directory: Path, *, source: str, actor: str, reader: str,
                 scope: str, current: Callable[[str], dict[str, str]],
                 count_tokens: Callable[[str], int] | None = None):
        if not all(isinstance(v, str) and v.strip() for v in (source, actor, reader, scope)):
            raise ValueError("source, actor, reader, and scope must identify a persistent reader")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise ValueError("handoff state directory must be private (mode 0700)")
        identity = json.dumps([source, actor, reader, scope], ensure_ascii=False)
        name = hashlib.sha256(identity.encode()).hexdigest()
        self.path = directory / (name + ".sqlite3")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.actor, self.scope, self.current = actor, scope, current
        self.count_tokens = count_tokens
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS reader_state (
                page_id TEXT PRIMARY KEY,
                accepted_pages TEXT, accepted_id TEXT, accepted_head TEXT,
                offered_pages TEXT, offered_id TEXT, offered_head TEXT, offered_mode TEXT)""")

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def read(self, *, page_id: str, fresh: bool = False) -> dict:
        if not isinstance(page_id, str) or not page_id.strip() or type(fresh) is not bool:
            raise ValueError("page_id must be a nonempty string and fresh must be boolean")
        with self._transaction() as db:
            # Serialize fetches for this reader only. Always recheck upstream
            # before sending any packet, including retries of an unacked offer.
            pages = self.current(page_id)
            db.execute("INSERT OR IGNORE INTO reader_state (page_id) VALUES (?)", (page_id,))
            row = db.execute("SELECT * FROM reader_state WHERE page_id=?", (page_id,)).fetchone()
            snapshot = fresh or row["offered_mode"] == "snapshot"
            previous = None
            if not snapshot and row["accepted_pages"] is not None:
                previous = json.loads(row["accepted_pages"])
            if previous is not None and snapshot_digest(previous, principal=self.actor, scope=self.scope) != row["accepted_head"]:
                raise ValueError("accepted reader state failed its integrity check")
            # After a lost-baseline request, subsequent retries must stay full
            # until the reader acknowledges a new snapshot.
            packet = make_update(previous, pages, principal=self.actor,
                                 scope=self.scope, expected_base=row["accepted_head"])
            # Bind both candidates to the same receipt. A forced fresh read
            # supersedes a pending delta even if the upstream head is identical.
            reuse = packet["head"] == row["offered_head"] and not (snapshot and row["offered_mode"] == "delta")
            receipt = row["offered_id"] if reuse else uuid.uuid4().hex
            offer = {"page_id": page_id, "receipt": receipt, "packet": packet}
            mode = packet["mode"]
            if mode == "delta" and self.count_tokens is not None:
                full = {**offer, "packet": {"mode": "snapshot", "head": packet["head"], "pages": pages}}
                if self.count_tokens(serialize_reply(full)) < self.count_tokens(serialize_reply(offer)):
                    offer = full
                    # A cheap snapshot is not a lost-baseline request. A later
                    # revision may again use the reader's acknowledged base.
                    mode = "auto_snapshot"
            if not reuse or mode != row["offered_mode"]:
                db.execute("""UPDATE reader_state SET offered_pages=?, offered_id=?,
                              offered_head=?, offered_mode=? WHERE page_id=?""",
                           (json.dumps(pages, ensure_ascii=False), receipt, packet["head"], mode, page_id))
            return offer

    def acknowledge(self, *, page_id: str, receipt: str, head: str) -> dict:
        if not all(isinstance(v, str) and v for v in (page_id, receipt, head)):
            raise ValueError("page_id, receipt and reconstructed head are required")
        with self._transaction() as db:
            row = db.execute("SELECT * FROM reader_state WHERE page_id=?", (page_id,)).fetchone()
            if row is None:
                raise ValueError("no delivery for this reader and page")
            if (receipt, head) != (row["accepted_id"], row["accepted_head"]):
                if (receipt, head) != (row["offered_id"], row["offered_head"]):
                    raise ValueError("unknown or superseded receipt for this reader; read again")
                db.execute("""UPDATE reader_state SET accepted_pages=offered_pages,
                              accepted_id=offered_id, accepted_head=offered_head,
                              offered_pages=NULL, offered_id=NULL, offered_head=NULL, offered_mode=NULL
                              WHERE page_id=?""", (page_id,))
            return {"acknowledged": True, "page_id": page_id, "head": head}
