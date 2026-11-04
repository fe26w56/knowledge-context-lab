"""Auditable 16-worker SQLite fault experiments; no HTTP, D1 or real taskflow."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import tempfile
import threading
import time

from .store import AccessDenied, IdempotencyConflict, KnowledgeStore, NotFound, VersionConflict


EVIDENCE = [{"source_id": "synthetic-source", "source_revision": "v1"}]


def arguments(request_id, content, version, actor="bot_00", record="shared-record", **scope):
    return dict(record_id=record, content=content, evidence=EVIDENCE,
                expected_version=version, request_id=request_id, actor=actor, **scope)


def snapshot(path):
    with sqlite3.connect(path) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                for table in ("revisions", "heads", "requests")}


def counts(state):
    return {table: len(rows) for table, rows in state.items()}


def parallel(db, operation):
    stores = [KnowledgeStore(db) for _ in range(16)]
    barrier = threading.Barrier(16)

    def work(i):
        barrier.wait(timeout=20)
        start = time.perf_counter()
        result = operation(stores[i], i)
        return dict(worker=i, elapsed_ms=(time.perf_counter()-start)*1000, **result)

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(work, i) for i in range(16)]
        return [future.result(timeout=30) for future in futures]


class TaskflowStub:
    """Client acknowledgement gate, bound to one confirmed request and revision."""
    def __init__(self, store):
        self.store = store

    def complete(self, request_id, actor, record_id, version, *, client_state):
        if client_state != "confirmed":
            return False
        try:
            result = self.store.request_status(request_id, actor=actor)
            if result["record_id"] != record_id or result["version"] != version:
                return False
            revision = self.store.get_revision(record_id, version, actor=actor)
            return bool(revision["evidence"])
        except NotFound:
            return False


class LostAcknowledgement(Exception):
    pass


def save_with_lost_ack(store, request):
    store.commit(**request)
    raise LostAcknowledgement("Injected response loss AFTER commit")


def run_once(root: Path, label="trial"):
    started = time.perf_counter()
    db = root / "knowledge.sqlite"
    store = KnowledgeStore(db)
    store.commit(**arguments("base", {"events": []}, 0))
    raw, checks = {}, {}

    def race(s, i):
        request = arguments(f"race-{i}", {"events": [i]}, 1, actor=f"bot_{i:02d}")
        try:
            return dict(status="committed", request=request, result=s.commit(**request))
        except VersionConflict as exc:
            return dict(status="conflict", request=request, error=str(exc))

    raw["race"] = parallel(db, race)
    raw["retries"] = []
    for row in raw["race"]:
        if row["status"] == "conflict":
            i = row["worker"]
            current = store.get_current("shared-record", actor=f"bot_{i:02d}")
            request = arguments(f"retry-{i}", {"events": current["content"]["events"]+[i]},
                                current["version"], actor=f"bot_{i:02d}")
            raw["retries"].append(dict(worker=i, read_version=current["version"],
                                       request=request, result=store.commit(**request)))
    head = store.get_current("shared-record", actor="reader")
    raw["head_after_retries"] = head
    raw["history_after_retries"] = [store.get_revision("shared-record", v, actor="reader")
                                    for v in range(1, head["version"]+1)]
    checks["single_cas_winner"] = sum(r["status"] == "committed" for r in raw["race"]) == 1
    checks["fifteen_conflicts"] = sum(r["status"] == "conflict" for r in raw["race"]) == 15
    checks["all_bot_updates_retained"] = sorted(head["content"]["events"]) == list(range(16)) and head["version"] == 17

    request = arguments("duplicate", dict(head["content"], marker="same"), head["version"])
    before = snapshot(db)
    raw["duplicates"] = parallel(db, lambda s,i: dict(result=s.commit(**request)))
    after = snapshot(db)
    raw["duplicate_counts"] = {"before": counts(before), "after": counts(after)}
    checks["parallel_duplicate_single_apply"] = (
        sum(not r["result"]["replayed"] for r in raw["duplicates"]) == 1
        and sum(r["result"]["replayed"] for r in raw["duplicates"]) == 15
        and len(after["revisions"]) - len(before["revisions"]) == 1
        and len(after["requests"]) - len(before["requests"]) == 1)
    try:
        store.commit(**dict(request, content={"different": True}))
        checks["idempotency_content_mismatch_rejected"] = False
    except IdempotencyConflict as exc:
        raw["idempotency_conflict"] = str(exc)
        checks["idempotency_content_mismatch_rejected"] = snapshot(db) == after

    head = store.get_current("shared-record", actor="reader")
    ack_request = arguments("ack-lost", dict(head["content"], marker="lost-ack"), head["version"])
    try:
        save_with_lost_ack(store, ack_request)
    except LostAcknowledgement as exc:
        raw["lost_ack_exception"] = str(exc)
    status = KnowledgeStore(db).request_status("ack-lost", actor="bot_00")
    required = KnowledgeStore(db).get_revision("shared-record", status["version"], actor="reader")
    later = store.commit(**arguments("later", dict(required["content"], marker="later"), status["version"]))
    replay = KnowledgeStore(db).commit(**ack_request)
    raw["lost_ack"] = dict(request=ack_request, status=status, required_revision=required,
                           later=later, replay=replay)
    checks["lost_ack_resolved_to_original_revision"] = replay == status and replay["version"] < later["version"]
    checks["read_after_write_required_revision"] = required["version"] == status["version"] and required["content"] == ack_request["content"]

    private = arguments("private", {"synthetic_private": "canary"}, 0, actor="owner", record="private-record", scope="private", owner="owner")
    store.commit(**private)
    private_checks = {"owner_current": store.get_current("private-record", actor="owner")["content"] == private["content"],
                      "owner_history": store.get_revision("private-record", 1, actor="owner")["content"] == private["content"],
                      "owner_request": store.request_status("private", actor="owner")["version"] == 1}
    for name, operation in {
        "other_current": lambda: store.get_current("private-record", actor="other"),
        "other_history": lambda: store.get_revision("private-record", 1, actor="other"),
        "other_request": lambda: store.request_status("private", actor="other"),
    }.items():
        try:
            operation(); private_checks[name] = False
        except NotFound:
            private_checks[name] = True
    try:
        store.commit(**dict(private, actor="other", expected_version=1, request_id="private-attack"))
        private_checks["other_write"] = False
    except AccessDenied:
        private_checks["other_write"] = True
    raw["private"] = private_checks
    checks["private_boundary"] = all(private_checks.values())

    fault_path = root/"fault.sqlite"
    fault_store = KnowledgeStore(fault_path)
    failed_request = arguments("injected-failure", {"synthetic": True}, 0)
    with sqlite3.connect(fault_path) as conn:
        conn.execute("CREATE TRIGGER injected BEFORE INSERT ON heads BEGIN SELECT RAISE(ABORT, 'injected failure after revision insert'); END")
    try:
        fault_store.commit(**failed_request); injected = False
    except sqlite3.IntegrityError:
        injected = True
    raw["rollback"] = dict(injected=injected, counts=counts(snapshot(fault_path)))
    fault_gate = TaskflowStub(fault_store)
    checks["failed_commit_not_complete"] = not fault_gate.complete("injected-failure", "bot_00", "shared-record", 1, client_state="confirmed")
    with sqlite3.connect(fault_path) as conn:
        conn.execute("DROP TRIGGER injected")
    raw["rollback"]["retry"] = fault_store.commit(**failed_request)
    checks["transaction_rollback_and_retry"] = injected and raw["rollback"]["counts"] == dict(revisions=0, heads=0, requests=0) and not raw["rollback"]["retry"]["replayed"]

    backup_state = snapshot(db)
    backup = store.backup_to(root/"backup.sqlite")
    head = store.get_current("shared-record", actor="reader")
    post1 = store.commit(**arguments("post-backup-1", dict(head["content"], marker="post1"), head["version"]))
    post2 = store.commit(**arguments("post-backup-2", dict(head["content"], marker="post2"), post1["version"]))
    recover_start = time.perf_counter()
    restored = KnowledgeStore.restore_from(backup, root/"restored.sqlite")
    restored_state = snapshot(root/"restored.sqlite")
    restored_head = restored.get_current("shared-record", actor="reader")
    restored_replay = restored.commit(**ack_request)
    restore_ms = (time.perf_counter()-recover_start)*1000
    live_state = snapshot(db)
    lost_revisions = sorted(set((r[0],r[1]) for r in live_state["revisions"]) - set((r[0],r[1]) for r in restored_state["revisions"]))
    lost_requests = sorted(set(r[0] for r in live_state["requests"]) - set(r[0] for r in restored_state["requests"]))
    raw["recovery"] = dict(backup_counts=counts(backup_state), restored_counts=counts(restored_state),
                           restored_head=restored_head, restored_ack_replay=restored_replay,
                           post_backup_commits=[post1,post2], lost_revisions=lost_revisions,
                           lost_request_ids=lost_requests, restore_and_verify_ms=restore_ms)
    checks["backup_preserves_all_rows"] = backup_state == restored_state
    checks["backup_preserves_idempotency"] = restored_replay == replay
    checks["snapshot_loss_scope_measured"] = lost_revisions == [("shared-record",post1["version"]),("shared-record",post2["version"])] and lost_requests == ["post-backup-1","post-backup-2"]

    gate = TaskflowStub(store)
    restored_gate = TaskflowStub(restored)
    gate_checks = {
        "uncommitted_blocked": not gate.complete("missing", "bot_00", "shared-record", 1, client_state="confirmed"),
        "lost_ack_pending_blocked": not gate.complete("ack-lost", "bot_00", "shared-record", status["version"], client_state="ack_unknown"),
        "confirmed_allowed": gate.complete("ack-lost", "bot_00", "shared-record", status["version"], client_state="confirmed"),
        "wrong_version_blocked": not gate.complete("ack-lost", "bot_00", "shared-record", later["version"], client_state="confirmed"),
        "wrong_record_blocked": not gate.complete("ack-lost", "bot_00", "private-record", status["version"], client_state="confirmed"),
        "restored_missing_commit_blocked": not restored_gate.complete("post-backup-1", "bot_00", "shared-record", post1["version"], client_state="confirmed"),
    }
    raw["taskflow_stub"] = gate_checks
    checks["taskflow_gate"] = all(gate_checks.values())
    metrics = dict(elapsed_ms=(time.perf_counter()-started)*1000, restore_and_verify_ms=restore_ms,
                   race_commits=sum(r["status"]=="committed" for r in raw["race"]),
                   race_conflicts=sum(r["status"]=="conflict" for r in raw["race"]), retry_count=len(raw["retries"]),
                   duplicate_commits=sum(not r["result"]["replayed"] for r in raw["duplicates"]),
                   duplicate_replays=sum(r["result"]["replayed"] for r in raw["duplicates"]),
                   lost_ack_replays=int(replay["replayed"]),lost_revisions=len(lost_revisions),lost_requests=len(lost_requests))
    return dict(label=label, checks=checks, all_pass=all(checks.values()), metrics=metrics, raw=raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args=parser.parse_args()
    if args.repeats<1:
        parser.error("repeats must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    source=args.output/"source"/"context_lab"
    source.mkdir(parents=True)
    hashes={}
    for name in ("__init__.py","faults.py","store.py"):
        origin=Path(__file__).parent/name
        shutil.copyfile(origin,source/name)
        hashes[name]=hashlib.sha256(origin.read_bytes()).hexdigest()
    rows=[]
    for i in range(args.repeats):
        with tempfile.TemporaryDirectory() as temp:
            rows.append(run_once(Path(temp),f"repeat-{i}"))
    metadata=dict(created_at=datetime.now(timezone.utc).isoformat(),privacy="public_synthetic",
                  experiment="local_sqlite_faults_v3",python=platform.python_version(),platform=platform.platform(),
                  sqlite=sqlite3.sqlite_version,repeats=args.repeats,concurrency=16,source_sha256=hashes,
                  random_seed_used=False,retry_policy="serialize conflict recovery after 16-worker race",
                  taskflow_stub_exercised=True,http_exercised=False,d1_exercised=False,
                  rto_definition="restore database, validate all tables, read head, replay prior request",
                  rpo_definition="acknowledged writes since the snapshot; no incremental backup replay")
    for name,value in (("metadata.json",metadata),("results.json",rows)):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    flat=[dict(label=r["label"],all_pass=r["all_pass"],**r["metrics"]) for r in rows]
    with (args.output/"results.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    if not all(r["all_pass"] for r in rows):
        raise SystemExit("Fault invariant failure; see raw results")
    print(json.dumps(dict(output=str(args.output),repeats=len(rows),all_pass=True)))


if __name__ == "__main__":
    main()
