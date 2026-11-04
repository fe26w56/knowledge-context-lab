#!/usr/bin/env python3
"""Evaluate raw-page workspace retrieval and migration semantics on v2 dev data."""
from __future__ import annotations

import argparse
import hashlib
import json
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from time import perf_counter

from context_lab.metrics import UnitCounter
from context_lab.workspace import Workspace, digest, _sections


def load_fixture(root: Path) -> tuple[list[dict], dict]:
    pages = json.loads((root / "pages.json").read_text())["pages"]
    dev = json.loads((root / "dev.json").read_text())
    return pages, dev


def file_sources(pages: list[dict], actor: str) -> list[dict]:
    out = []
    for page in pages:
        if page["scope"] == "private" and page.get("owner") != actor:
            continue
        out.append({"page": page, "version": 1, "sha256": digest(page),
                    "revision_id": "source:" + page["id"] + "@1"})
    return out


def spans_present(result: dict, required: list[str]) -> list[str]:
    found = set()
    for source in result.get("sources", []):
        page = source.get("page", {})
        if page:
            chunks = _sections(page.get("body", ""))
            sid = page.get("id")
        else:
            chunks = source.get("sections", [])
            sid = source.get("source_id")
        for chunk in chunks:
            heading = chunk.get("heading", "")
            found.add(f"{sid}#{heading}")
    return [x for x in required if x in found]


def exact_spans_present(result: dict, pages: dict, required: list[str]) -> list[str]:
    found = set()
    for source in result.get("sources", []):
        sid = source.get("source_id") or source.get("page", {}).get("id")
        page = pages.get(sid)
        if not page:
            continue
        expected = {f"{sid}#{c['heading']}": c for c in _sections(page["body"])}
        chunks = source.get("sections") or _sections(source.get("page", {}).get("body", ""))
        for chunk in chunks:
            key = f"{sid}#{chunk.get('heading', '')}"
            if key in expected and all(chunk.get(k) == expected[key].get(k) for k in ("heading", "start", "end", "text")):
                found.add(key)
    return [x for x in required if x in found]


def query(mode: str, sources: list[dict], task: dict) -> dict:
    started = perf_counter()
    result = Workspace.search_sources(sources, task["request"], mode=mode)
    elapsed = (perf_counter() - started) * 1000
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    kept = exact_spans_present(result, {s["page"]["id"]: s["page"] for s in sources}, task["gold"].get("source_spans", []))
    return {"mode": mode, "task_id": task["task_id"], "status": result["status"],
            "candidate_source_count": len(result["sources"]), "retained_spans": kept,
            "required_span_count": len(task["gold"].get("source_spans", [])),
            "units": UnitCounter("o200k_base")(payload), "bytes": len(payload.encode()),
            "elapsed_ms": elapsed, "result": result}


def audit(root: Path, out: Path) -> dict:
    if out.exists():
        raise SystemExit(f"refusing existing output: {out}")
    out.mkdir(parents=True)
    pages, dev = load_fixture(root)
    freeze = json.loads((root / "FREEZE.json").read_text())
    verified_hashes = {}
    for name, expected in freeze["sha256"].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"fixture hash mismatch: {name}")
        verified_hashes[name] = actual
    actor = "evaluator"
    page_map = {p["id"]: p for p in pages}
    file_load_start = perf_counter()
    cold_pages = json.loads((root / "pages.json").read_text())["pages"]
    files = file_sources(cold_pages, actor)
    file_load_ms = (perf_counter() - file_load_start) * 1000
    modes = ["raw", "normalized", "current"]
    rows = []
    orders = [modes, ["current", "raw", "normalized"], ["normalized", "current", "raw"],
              ["raw", "current", "normalized"], ["current", "normalized", "raw"]]
    for order in orders:
        for mode in order:
            for task in dev["tasks"]:
                rows.append(query(mode, files, task))

    ingest_start = perf_counter()
    db_path = out / "workspace.sqlite3"
    ws = Workspace(db_path)
    shared = [p for p in pages if p["scope"] == "shared"]
    receipt_shared = ws.import_pages(shared, actor=actor, request_id="migration-dev-import-shared")
    private_owners = sorted({p["owner"] for p in pages if p["scope"] == "private"})
    private_receipts = {}
    for owner in private_owners:
        owned = [p for p in pages if p["scope"] == "private" and p.get("owner") == owner]
        private_receipts[owner] = ws.import_pages(owned, actor=owner, request_id="migration-dev-import-private-" + owner)
    ingest_ms = (perf_counter() - ingest_start) * 1000
    private_absent = []
    for p in pages:
        if p["scope"] == "private":
            try:
                ws.get_source(p["id"], actor=actor)
            except Exception as exc:
                private_absent.append({"page_id": p["id"], "error": type(exc).__name__})
    sqlite_rows = []
    warm_start = perf_counter()
    for task in dev["tasks"]:
        started = perf_counter()
        result = ws.search(task["request"], actor=actor, mode="current")
        elapsed = (perf_counter() - started) * 1000
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
        sqlite_rows.append({"mode":"sqlite-current","task_id":task["task_id"],"status":result["status"],
                            "candidate_source_count":len(result["sources"]),
                            "retained_spans":exact_spans_present(result, page_map, task["gold"].get("source_spans", [])),
                            "required_span_count":len(task["gold"].get("source_spans", [])),
                            "units":UnitCounter("o200k_base")(payload),"bytes":len(payload.encode()),"elapsed_ms":elapsed,
                            "result":result})
    warm_ms = (perf_counter() - warm_start) * 1000

    before = {p["id"]: ws.get_source(p["id"], actor=actor) for p in pages if p["scope"] == "shared"}
    correction = next(x for x in dev["operations"] if x["op"] == "replace_page")
    expected = {correction["record_id"]: before[correction["record_id"]]["version"]}
    correction_receipt = ws.import_pages([correction["page"]], actor=actor,
                                         request_id="migration-dev-correction", expected_versions=expected)
    after_main = ws.get_source("dev-cedar-main", actor=actor)
    after_note = ws.get_source("dev-cedar-note", actor=actor)
    rerun = ws.search(next(t for t in dev["tasks"] if t["task_id"] == "d6")["request"], actor=actor)
    bundle_start = perf_counter()
    bundle = ws.export_bundle(actor=actor)
    with TemporaryDirectory(dir=out) as tmp:
        restored = Workspace.restore_bundle(bundle, Path(tmp) / "restored.sqlite3")
        bundle_ms = (perf_counter() - bundle_start) * 1000
        bundle2 = restored.export_bundle(actor=actor)
        bundle_parity = bundle2 == bundle

    barrier = Barrier(16)
    inflight = 0
    max_inflight = 0
    inflight_lock = Lock()
    def read_once(i: int) -> dict:
        nonlocal inflight, max_inflight
        barrier.wait()
        with inflight_lock:
            inflight += 1
            max_inflight = max(max_inflight, inflight)
        try:
            return ws.search("Sable輸出一覧", actor=actor)
        finally:
            with inflight_lock:
                inflight -= 1
    concurrent_start = perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        concurrent = list(pool.map(read_once, range(16)))
    concurrent_ms = (perf_counter() - concurrent_start) * 1000

    parity = []
    sqlite_by_id = {x["task_id"]: x for x in sqlite_rows}
    for task in dev["tasks"]:
        fc = query("current", files, task)["result"]
        sc = sqlite_by_id[task["task_id"]]["result"]
        parity.append({"task_id":task["task_id"],"canonical_json_equal":json.dumps(fc,ensure_ascii=False,sort_keys=True) == json.dumps(sc,ensure_ascii=False,sort_keys=True),
                       "exact_spans": exact_spans_present(fc,page_map,task["gold"].get("source_spans",[]))})

    summary = {"fixture":"phase2-migration-v2","split":"dev","pages":len(pages),"tasks":len(dev["tasks"]),
               "body_length_chars":{"min":min(len(p["body"]) for p in pages),"max":max(len(p["body"]) for p in pages)},
               "source_visibility":{"file_sources":len(files),"sqlite_shared":len(shared),"sqlite_private_owners":private_owners,"private_absent_to_evaluator":private_absent},
               "cold_file_load_ms":file_load_ms,"ingest_ms":ingest_ms,"warm_sqlite_total_ms":warm_ms,"export_restore_ms":bundle_ms,
               "bundle_bytes":len(json.dumps(bundle,ensure_ascii=False).encode()),"bundle_parity":bundle_parity,
               "correction":{"receipt":correction_receipt,"main_unchanged":after_main["version"] == before["dev-cedar-main"]["version"],"note_version_incremented":after_note["version"] == before["dev-cedar-note"]["version"] + 1,"rerun_status":rerun["status"]},
               "concurrency":{"readers":16,"completed":len(concurrent),"wall_ms":concurrent_ms,"max_inflight":max_inflight},
               "file_sqlite_parity":parity,
               "gold_audit":{"d4_forbidden_conflicts_with_answer":True,"d8_normative_answer_partly_unsupported":True,"semantic_accuracy":"not_scored"},
               "notes":["Evidence/section retention only; not answer accuracy.","File source modes share a cold load; timings label retrieval only.","Pages body lengths are 134-437 chars despite README target of roughly 500-1400; fixture limitation is retained."]}
    all_rows = rows + sqlite_rows
    (out / "rows.json").write_text(json.dumps(all_rows, ensure_ascii=False, indent=2))
    with (out / "rows.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["mode","task_id","candidate_source_count","required_span_count","retained_spans","units","bytes","elapsed_ms"])
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k) for k in writer.fieldnames})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    config = {"unit":"o200k_base","candidate_pages":6,"rounds":5,"actor":actor,"fixture_hashes":verified_hashes,
              "code_hashes": {"scripts/evaluate_workspace.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              "src/context_lab/workspace.py": hashlib.sha256(Path("src/context_lab/workspace.py").read_bytes()).hexdigest()}}
    (out / "config.json").write_text(json.dumps(config, indent=2))
    arm_summary = {}
    for row in all_rows:
        a = arm_summary.setdefault(row["mode"], {"count":0,"units":0,"retained":0,"required":0})
        a["count"] += 1; a["units"] += row["units"]; a["retained"] += len(row["retained_spans"]); a["required"] += row["required_span_count"]
    (out / "arm-summary.json").write_text(json.dumps(arm_summary, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=Path("fixtures/phase2-migration-v2"))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(audit(args.fixture, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
