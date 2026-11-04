"""Durable reservations for bounded experiments; never an invoice or credit balance.

Reserve a conservative request maximum BEFORE dispatch. Only confirmed usage may
reduce a reservation. Interrupted and failed calls retain the full reservation;
retries require distinct attempt IDs. SQLite serializes reservations across
threads/processes. The caller is responsible for a valid provider price bound.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import sqlite3


class BudgetExceeded(RuntimeError):
    pass


def nanodollars(usd: str | Decimal) -> int:
    value = Decimal(usd)
    if not value.is_finite() or value < 0:
        raise ValueError("cost must be finite and nonnegative")
    return int((value * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))


def token_cost(tokens: int, usd_per_million: str) -> int:
    if type(tokens) is not int or tokens < 0:
        raise ValueError("token count must be a nonnegative integer")
    return nanodollars(Decimal(usd_per_million) * tokens / 1_000_000)


class ExperimentBudget:
    """One ledger per authorized spending envelope, shared by all experiments."""

    def __init__(self, path: str | Path, *, cap_usd: str):
        self.path = Path(path)
        if str(path) == ":memory:":
            raise ValueError("a durable file is required")
        cap = nanodollars(cap_usd)
        if cap <= 0:
            raise ValueError("positive cap required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS experiment_budget "
                       "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), cap INTEGER NOT NULL, "
                       "halted INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts "
                       "(attempt_id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, "
                       "accounted INTEGER NOT NULL, status TEXT NOT NULL, usage_json TEXT)")
            db.execute("INSERT OR IGNORE INTO experiment_budget(singleton,cap) VALUES(1,?)", (cap,))
            if db.execute("SELECT cap FROM experiment_budget").fetchone()[0] != cap:
                raise ValueError("existing spending cap cannot be changed")

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def reserve(self, attempt_id: str, maximum_nanodollars: int) -> None:
        if not isinstance(attempt_id, str) or not attempt_id or len(attempt_id) > 256:
            raise ValueError("a nonempty attempt ID of at most 256 characters is required")
        if type(maximum_nanodollars) is not int or maximum_nanodollars <= 0:
            raise ValueError("positive integer reservation required")
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise ValueError("attempt already reserved; do not dispatch it again")
            settings = db.execute("SELECT * FROM experiment_budget").fetchone()
            used = db.execute("SELECT COALESCE(SUM(accounted),0) FROM attempts").fetchone()[0]
            if settings["halted"] or used + maximum_nanodollars > settings["cap"]:
                raise BudgetExceeded("request would exceed the experiment spending envelope")
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,NULL)",
                       (attempt_id, maximum_nanodollars, maximum_nanodollars, "reserved"))

    def settle(self, attempt_id: str, conservative_cost: int, usage: dict) -> None:
        """Account a usage-based upper estimate, not provider billed dollars.

        If the caller's price bound was wrong, record the excess and permanently
        halt new reservations. Do not hide the excess by rolling it back.
        """
        if type(conservative_cost) is not int or conservative_cost < 0:
            raise ValueError("nonnegative integer cost required")
        # Store only numeric token counts; credentials and response text cannot
        # enter the ledger through an arbitrary provider response dictionary.
        if not usage or any(not isinstance(k, str) or not k.endswith("tokens")
                            or type(v) is not int or v < 0 for k, v in usage.items()):
            raise ValueError("usage must contain only nonnegative integer token counts")
        encoded = json.dumps(usage, sort_keys=True)
        excess = False
        with self._transaction() as db:
            row = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None:
                raise ValueError("request was not reserved")
            if row["status"] == "uncertain":
                raise ValueError("uncertain billing retains its reservation; no automatic refund")
            if row["status"] == "settled":
                if row["accounted"] != conservative_cost or row["usage_json"] != encoded:
                    raise ValueError("settlement cannot be changed")
                return
            excess = conservative_cost > row["reserved"]
            db.execute("UPDATE attempts SET accounted=?,status='settled',usage_json=? WHERE attempt_id=?",
                       (conservative_cost, encoded, attempt_id))
            if excess:
                db.execute("UPDATE experiment_budget SET halted=1")
        if excess:
            raise BudgetExceeded("observed usage exceeded the price bound; further calls halted")

    def mark_uncertain(self, attempt_id: str) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT status FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row[0] == "settled":
                raise ValueError("only unsettled reservations can become uncertain")
            db.execute("UPDATE attempts SET status='uncertain' WHERE attempt_id=?", (attempt_id,))

    def report(self) -> dict:
        with self._transaction() as db:
            settings = dict(db.execute("SELECT * FROM experiment_budget").fetchone())
            attempts = [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY attempt_id")]
        for row in attempts:
            row["usage"] = json.loads(row.pop("usage_json") or "null")
        return dict(unit="USD nanodollars", cap=settings["cap"],
                    accounted=sum(r["accounted"] for r in attempts), halted=bool(settings["halted"]),
                    attempts=attempts, invoice_measured=False, credit_balance_measured=False,
                    definition="conservative usage estimates plus full unresolved reservations")
