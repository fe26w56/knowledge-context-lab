"""Measure local completion snapshot consistency without models or fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from json import loads
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from context_lab.snapshot import read_snapshot
from context_lab.snapshot import retrieval_documents
from context_lab.store import KnowledgeStore
from context_lab.retrieval_release import ReleaseRetrieval
from context_lab.retrieval_v2 import digest


def document(text: str, section_id: str | None = None) -> dict:
    section_id = section_id or "section-" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return {"title": "Synthetic policy", "body": text,
            "sections": [{"id": section_id, "heading": "Rule", "text": text,
                          "kind": "decision", "adoption_status": "adopted"}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("runs/phase2-completion-snapshots-v1"))
    args = parser.parse_args()
    run = args.output_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    store = KnowledgeStore(run / "store.sqlite")
    store.commit(record_id="policy", content=document("v0"),
                 evidence=[{"source_id": "synthetic", "source_revision": "r0"}],
                 expected_version=0, request_id="r0", actor="writer")

    def reader() -> dict:
        started = perf_counter_ns()
        snapshot = read_snapshot(store, actor="reader")
        return {"latency_ns": perf_counter_ns() - started,
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "revision_id": snapshot["manifest"][0]["revision_id"]}

    with ThreadPoolExecutor(max_workers=16) as pool:
        observations = list(pool.map(lambda _: reader(), range(16)))
    writer = KnowledgeStore(store.path)
    writer.commit(record_id="policy", content=document("v1"),
                  evidence=[{"source_id": "synthetic", "source_revision": "r1"}],
                  expected_version=1, request_id="r1", actor="writer")
    after = read_snapshot(store, actor="reader")
    manifest_sha256 = hashlib.sha256(json.dumps(after["manifest"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    checks = {
        "failed_commit_invisible": False,
        "lost_ack_retry_no_extra_revision": False,
        "backup_restore_loss_reported": False,
        "sixteen_distinct_actor_adapter_reads": False,
    }

    # A real SQLite failure after revision insertion must expose neither the
    # revision nor its request record.
    with sqlite3.connect(store.path) as connection:
        connection.execute("""CREATE TRIGGER injected_snapshot_failure
            BEFORE INSERT ON heads BEGIN SELECT RAISE(ABORT, 'snapshot failure'); END""")
    failed_triggered = False
    try:
        try:
            store.commit(record_id="failed", content=document("never-visible"),
                         evidence=[{"source_id": "synthetic", "source_revision": "failed"}],
                         expected_version=0, request_id="failed", actor="writer")
        except sqlite3.IntegrityError:
            failed_triggered = True
    finally:
        with sqlite3.connect(store.path) as connection:
            connection.execute("DROP TRIGGER injected_snapshot_failure")
    checks["failed_commit_invisible"] = failed_triggered and all(
        record["record_id"] != "failed" for record in read_snapshot(store, actor="reader")["records"]
    )

    retry_payload = dict(record_id="retry", content=document("retry-v1"),
                          evidence=[{"source_id": "synthetic", "source_revision": "retry-v1"}],
                          expected_version=0, request_id="retry-request", actor="writer")
    first = store.commit(**retry_payload)
    store.commit(record_id="retry", content=document("retry-v2"),
                 evidence=[{"source_id": "synthetic", "source_revision": "retry-v2"}],
                 expected_version=1, request_id="retry-update", actor="writer")
    with sqlite3.connect(store.path) as connection:
        before_retry = connection.execute("SELECT count(*) FROM revisions WHERE record_id='retry'").fetchone()[0]
    replay = store.commit(**retry_payload)
    with sqlite3.connect(store.path) as connection:
        after_retry = connection.execute("SELECT count(*) FROM revisions WHERE record_id='retry'").fetchone()[0]
    head_after_retry = store.get_current("retry", actor="writer")["version"]
    checks["lost_ack_retry_no_extra_revision"] = (
        replay["replayed"] and replay["version"] == first["version"]
        and before_retry == after_retry == 2 and head_after_retry == 2
    )

    backup = store.backup_to(run / "backup.sqlite")
    store.commit(record_id="policy", content=document("v2"),
                 evidence=[{"source_id": "synthetic", "source_revision": "r2"}],
                 expected_version=2, request_id="r2", actor="writer")
    store.commit(record_id="policy", content=document("v3"),
                 evidence=[{"source_id": "synthetic", "source_revision": "r3"}],
                 expected_version=3, request_id="r3", actor="writer")
    restored = KnowledgeStore.restore_from(backup, run / "restored.sqlite")
    live_version = store.get_current("policy", actor="reader")["version"]
    restored_version = restored.get_current("policy", actor="reader")["version"]
    checks["backup_restore_loss_reported"] = restored_version == 2 and live_version == 4
    lost_revision_ids = [f"policy@{version}" for version in range(restored_version + 1, live_version + 1)]

    actors = []
    actor_stores = []
    for index in range(16):
        actor = f"actor-{index}"
        actor_store = KnowledgeStore(store.path)
        actors.append(actor)
        actor_stores.append(actor_store)
    batch_barrier = Barrier(16)
    def actor_operation(index: int) -> dict:
        actor = actors[index]
        body = f"actor-{index}"
        started = perf_counter_ns()
        batch_barrier.wait(timeout=10)
        actor_stores[index].commit(record_id=f"private-{index}", content=document(body, f"section-{index}"),
                           evidence=[{"source_id": "synthetic", "source_revision": hashlib.sha256(body.encode()).hexdigest()}],
                           expected_version=0, request_id=f"actor-request-{index}", actor=actor,
                           scope="private", owner=actor)
        write_finished = perf_counter_ns()
        snapshot, docs = retrieval_documents(store, actor=actor)
        read_finished = perf_counter_ns()
        ids = {doc["id"] for doc in docs}
        private_ids = {doc_id for doc_id in ids if doc_id.startswith("private-")}
        expected_revision = {
            record["record_id"]: record["revision_id"] for record in snapshot["records"]
        }
        consistent = all(doc["revision_id"] == expected_revision[doc["id"]] for doc in docs)
        isolated = private_ids == {f"private-{index}"}
        class Adapter:
            read_calls = 0
            def read(self_inner):
                self_inner.read_calls += 1
                return docs
        retrieval = ReleaseRetrieval(Adapter())
        query = retrieval.retrieve({"text": f"actor-{index}", "actor": actor, "mode": "search"})
        envelope = loads(query["payload"])
        selected_ids = sorted({item.get("document_id") for item in envelope.get("items", [])
                               if item.get("document_id")})
        private_sources = {doc_id for doc_id in envelope.get("sources", {})
                           if doc_id.startswith("private-")}
        expected_source_revisions = {
            record["record_id"]: digest(record["content"]["body"])
            for record in snapshot["records"]
        }
        source_revisions_match = all(
            envelope["sources"][doc_id].get("revision") == expected_source_revisions.get(doc_id)
            for doc_id in envelope.get("sources", {})
        )
        return {"actor": actor, "write_interval_ns": write_finished - started,
                "read_interval_ns": read_finished - write_finished,
                "write_started_ns": started, "write_finished_ns": write_finished,
                "read_finished_ns": read_finished, "consistent": consistent,
                "private_isolation": isolated and private_sources <= {f"private-{index}"},
                "selected_document_ids": selected_ids,
                "query_has_own_private": f"private-{index}" in set(selected_ids),
                "source_revisions_match": source_revisions_match,
                "record_count": len(snapshot["records"])}
    with ThreadPoolExecutor(max_workers=16) as pool:
        actor_results = list(pool.map(actor_operation, range(16)))
    intervals = [(item["write_started_ns"], item["read_finished_ns"]) for item in actor_results]
    concurrent_intervals = max(
        sum(start <= point < end for start, end in intervals)
        for point in {point for interval in intervals for point in interval}
    )
    checks["sixteen_distinct_actor_adapter_reads"] = (
        len({item["actor"] for item in actor_results}) == 16
        and all(item["consistent"] and item["private_isolation"]
                and item["query_has_own_private"] and item["source_revisions_match"]
                for item in actor_results)
        and concurrent_intervals >= 2
    )
    result = {"run": str(run), "claims": {"local_snapshot_consistency": True,
              "model_measurement": False, "d1_or_distributed": False},
              "reader_count": len(observations), "observations": observations,
              "post_write_revision_id": after["manifest"][0]["revision_id"],
              "post_write_manifest_sha256": manifest_sha256, "checks": checks,
              "actor_batch": {"submitted_operations": 32, "actor_results": actor_results,
                              "concurrent_interval_overlap_max": concurrent_intervals},
              "backup_restore": {"live_version": live_version, "restored_version": restored_version,
                                  "acknowledged_lost_revision_ids": lost_revision_ids},
              "failed_commit_triggered": failed_triggered,
              "retry_revision_counts": {"before_replay": before_retry, "after_replay": after_retry,
                                         "head_after_replay": head_after_retry},
              "evidence": "SQLite read transaction over current heads; no multi-record atomicity claim; snapshot checksums provide consistency evidence, not authenticity or authentication"}
    (run / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
