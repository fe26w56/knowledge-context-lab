"""Independently check saved evidence, source snapshots and protected inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from context_lab.metrics import UnitCounter
from context_lab.retrieval_v2 import digest


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    checks = {}
    protected = read(root / "BUNDLE_MANIFEST.json")["sha256"]
    protected = {p: h for p, h in protected.items() if p.startswith(("fixtures/synthetic/", "runs/synthetic-v1/"))}
    assert protected and all(sha(root / p) == h for p, h in protected.items())
    checks["phase1_protected_files"] = len(protected)
    frozen = read(root / "fixtures/phase2/FREEZE.json")
    assert all(sha(root / "fixtures/phase2" / p) == h for p, h in frozen["sha256"].items())
    checks["phase2_frozen_files"] = len(frozen["sha256"])

    selection = read(root / "runs/phase2-dev-v3/selection.json")
    final = root / "runs/phase2-final-v1"
    metadata = read(final / "metadata.json")
    source = final / "source/context_lab"
    names = ("retrieval_v2.py", "retrieval.py", "metrics.py")
    implementation = digest({p: sha(source / p) for p in names})
    assert implementation == metadata["implementation_sha256"] == selection["implementation_sha256"]
    assert sha(source / "phase2_eval.py") == metadata["evaluator_sha256"]
    assert all(sha(source / p) == sha(root / "src/context_lab" / p) for p in names)
    assert metadata["queries_sha256"] == frozen["sha256"]["final.json"]
    assert metadata["corpus_sha256"] == frozen["sha256"]["corpus.json"]
    assert read(final / "selection-used.json") == selection
    assert selection["frozen_at"] < metadata["created_at"]
    checks["selection_and_final_snapshot_match"] = True
    for name in ("phase2-load-v1", "phase2-faults-v3"):
        run = root / "runs" / name
        meta = read(run / "metadata.json")
        assert all(sha(run / "source/context_lab" / p) == h for p, h in meta["source_sha256"].items())
    checks["load_and_fault_source_snapshots_match"] = True

    rows = read(final / "results.json")
    first = {(r["stage"], r["method"], r["budget"], r["query_id"]): r for r in rows if r["repeat"] == 0 and r["cache_state"] == "warm_index"}
    queries = {q["id"]: q for q in read(root / "fixtures/phase2/final.json")["queries"]}
    docs = {d["id"]: d for d in read(root / "fixtures/phase2/corpus.json")["documents"]}
    counter = UnitCounter("o200k_base")
    payloads = [json.loads(line) for line in (final / "payloads.jsonl").read_text().splitlines()]
    for p in payloads:
        row = first[p["stage"], p["method"], p["budget"], p["query_id"]]
        value = json.loads(p["payload"])
        assert counter(p["payload"]) == row["returned_units"]
        if p["method"] != "A":
            assert counter(p["payload"]) <= p["budget"]
        request = queries[p["query_id"]]["request"]
        for item in value["items"]:
            doc = docs[item["document_id"]]
            assert doc["scope"] == "shared" or doc["owner"] == request["actor"]
            if request.get("scope"):
                assert doc["scope"] == request["scope"]
            if p["method"] != "A":
                section = next(s for s in doc["sections"] if s["id"] == item["parent_section_id"])
                assert item["text"] == "".join(section["text"][a:b] for a, b in item["spans"])
    for row in rows:
        if row["method"] != "B":
            continue
        peers = [r for r in rows if all(r[k] == row[k] for k in ("query_id", "stage", "budget", "cache_state", "repeat"))]
        assert len(peers) == 3
        assert all(p["candidate_documents"] == row["candidate_documents"] for p in peers)
    checks["payloads_token_budget_privacy_source_spans"] = len(payloads)
    checks["abc_candidates_identical_for_all_trials"] = True
    by_key = {(p["query_id"], p["stage"], p["budget"], p["method"]): p["payload"] for p in payloads}
    pairs = [(q, s, b) for q, s, b, method in by_key if method == "B"]
    assert all(by_key[q, s, b, "B"] == by_key[q, s, b, "C"] for q, s, b in pairs)
    checks["final_backend_payload_pairs"] = len(pairs)
    assert all(not r["retrieval_error"] and not r["forbidden_quote_hits"] for r in rows)

    load = root / "runs/phase2-load-v1"
    trials = [json.loads(line) for line in (load / "trials.jsonl").read_text().splitlines()]
    for group in read(load / "aggregates.json"):
        members = [r for r in trials if all(r[k] == group[k] for k in ("size", "method", "cache_state"))]
        assert len(members) == group["trials"]
        assert statistics.median(r["total_ms"] for r in members) == group["median_ms"]
        assert statistics.mean(r["original_source_quote_recall"] for r in members) == group["original_source_quote_recall"]
    checks["load_rows_and_aggregates"] = len(trials)
    faults = read(root / "runs/phase2-faults-v3/results.json")
    for r in faults:
        assert r["all_pass"] and all(r["checks"].values())
        raw = r["raw"]
        assert len(raw["race"]) == 16 and sum(x["status"] == "committed" for x in raw["race"]) == 1
        assert sorted(raw["head_after_retries"]["content"]["events"]) == list(range(16))
        assert sum(x["result"]["replayed"] for x in raw["duplicates"]) == 15
        assert raw["lost_ack"]["status"]["version"] == raw["lost_ack"]["replay"]["version"]
        assert raw["recovery"]["backup_counts"] == raw["recovery"]["restored_counts"]
        assert len(raw["recovery"]["lost_revisions"]) == 2
    checks["fault_repeats_with_raw_evidence"] = len(faults)
    baseline = read(root / "runs/phase2-baseline/comparison.json")
    assert baseline["non_timing_equal"] and baseline["payloads_equal"] and baseline["rows_new"] == 270
    checks["baseline_comparison"] = baseline
    return {"ok": True, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.root)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(text)
    print(text)
