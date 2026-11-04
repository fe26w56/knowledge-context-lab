"""Offline token/evidence comparison for explicit reviewed-topic reuse."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import tempfile
import time

import tiktoken

from context_lab.reviewed_context import ReviewedWorkspace
from context_lab.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTION = "資料だけを根拠に、決定・条件・例外・根拠・状態を区別して回答してください。資料にないことは不明としてください。"
SIZES = (100, 1000, 10000)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_author(path):
    spec = importlib.util.spec_from_file_location("reuse_author", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_context(records, *, project, topic_id, mode, full):
    sources = []
    for record in records:
        if record["content"].get("kind") != "source":
            continue
        page = record["content"]["page"]
        props = page.get("properties", {})
        if props.get("project") != project:
            continue
        if not full and props.get("topic_id") != topic_id:
            continue
        if mode != "history" and props.get("status") in {"historical", "superseded", "retired"}:
            continue
        item = {"id": page["id"], "title": page["title"], "version": record["version"],
                "sha256": record["content"]["sha256"], "state": props.get("status"),
                "properties": props}
        item["body"] = page["body"]
        sources.append(item)
    return {"project": project, "topic_id": topic_id, "mode": mode,
            "status": "available" if sources else "unavailable",
            "coverage": "project_full" if full else "topic_scoped", "sources": sorted(sources, key=lambda x: x["id"])}


def score(context, case, source_map, actor):
    returned = {s["id"]: s for s in context.get("sources", [])}
    required = case.get("required_source_ids", [])
    missing_ids = [sid for sid in required if sid not in returned]
    missing_quotes = []
    for quote in case.get("required_quotes", []):
        if not any(quote in (s.get("body", "") or "") or any(quote in sp.get("text", "") for sp in s.get("spans", [])) for sid,s in returned.items() if sid in required and quote in source_map[sid]['body']):
            missing_quotes.append(quote)
    for sid,s in returned.items():
        if 'body' in s and s['body']!=source_map[sid]['body']: raise ValueError('body mismatch')
        for span in s.get('spans',[]):
            if source_map[sid]['body'][span['start']:span['end']]!=span['text']:raise ValueError('span mismatch')
    private_exposure = [sid for sid, s in returned.items() if source_map.get(sid, {}).get("scope") == "private" and source_map[sid].get("owner") != actor]
    stale = [sid for sid, s in returned.items() if case.get("mode") != "history" and s.get("state") in {"historical", "superseded", "retired"}]
    answerable = bool(case.get("answerable"))
    complete = bool(answerable and not missing_ids and not missing_quotes)
    return {"answerable": answerable, "required_sources": len(required), "source_hits": len(required) - len(missing_ids),
            "required_quotes": len(case.get("required_quotes", [])), "quote_hits": len(case.get("required_quotes", [])) - len(missing_quotes),
            "complete_evidence": complete, "missing_source_ids": missing_ids, "missing_quotes": missing_quotes,
            "private_exposure": len(private_exposure), "stale_exposure": len(stale),
            "retrieval_status": context.get("status"), "expected_status": case.get("expect_status"),
            "status_matches": context.get("status") == case.get("expect_status"),
            "state_preserved": all(s.get("state") == source_map[s["id"]].get("properties",{}).get("status") for s in returned.values())}


def publish_reviewed(workspace, manifest, sources, *, editor="editor"):
    by_id = {s["id"]: s for s in sources}
    groups = defaultdict(list)
    for item in manifest["items"]:
        if item["source_id"] in by_id:
            groups[(by_id[item["source_id"]]["properties"]["project"], item["topic_id"])].append(item)
    published = 0
    skipped = 0
    rw = ReviewedWorkspace(workspace)
    views = {}
    for (project, topic), items in sorted(groups.items()):
        if not all(item.get("reviewed") is True for item in items):
            skipped += 1
            continue
        owner = next((by_id[item["source_id"]].get("owner") for item in items if by_id[item["source_id"]].get("scope") == "private"), editor)
        ranges = [{**item, "scope": by_id[item["source_id"]]["scope"]} for item in items]
        if owner not in views: views[owner]=rw.snapshot(actor=owner)
        rw.publish(project, topic, ranges, actor=owner, request_id=f"review:{project}:{topic}", confirmed=True, view=views[owner])
        published += 1
    return {"published": published, "skipped": skipped}


def concurrent_metrics(reviewed, project, topic, mode):
    pinned = reviewed.snapshot(actor="reader")
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        pinned_results = list(pool.map(lambda _: pinned.context(project, topic, mode=mode, full=False), range(16)))
    pinned_seconds = time.perf_counter() - start
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        def read_fresh(i):
            view=reviewed.snapshot(actor=f'reader-{i:02d}')
            return {'snapshot':view.snapshot_sha256,'payload':view.context(project,topic,mode=mode,full=False)}
        fresh_results = list(pool.map(read_fresh, range(16)))
    fresh_seconds = time.perf_counter() - start
    return {"pinned_reads": 16, "pinned_seconds": pinned_seconds,
            "pinned_snapshot_sha256": pinned.snapshot_sha256,
            "pinned_payloads_equal": len({canonical(x) for x in pinned_results}) == 1,
            "fresh_reads": 16, "fresh_seconds": fresh_seconds,
            "fresh_snapshot_hashes": len({x['snapshot'] for x in fresh_results}),
            "fresh_payloads_equal":len({canonical(x['payload']) for x in fresh_results})==1,
            "caller_identities":"trusted local strings, not remote authentication"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "fixtures/phase2-reuse-v1")
    parser.add_argument("--split", choices=("dev", "final"), default="dev")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output must be new")
    freeze = json.loads((args.fixture / "FREEZE.json").read_text())
    for name, digest in freeze["files"].items():
        if sha(args.fixture / name) != digest:
            raise ValueError("fixture hash mismatch")
    code_files = ["src/context_lab/reviewed_context.py", "src/context_lab/workspace.py", "src/context_lab/store.py", "src/context_lab/snapshot.py", "scripts/evaluate_reuse.py"]
    code_hashes = {name: sha(ROOT / name) for name in code_files}
    if args.split == "final":
        if not args.selection:
            raise ValueError("final requires selection")
        selection = json.loads(args.selection.read_text())
        if selection.get("fixture_freeze_sha256") != sha(args.fixture / "FREEZE.json") or selection.get("code_sha256") != code_hashes:
            raise ValueError("selection hash mismatch")
    cases = json.loads((args.fixture / f"{args.split}.json").read_text())
    manifest = json.loads((args.fixture / "review_manifest.json").read_text())
    author = load_author(args.fixture / "author_fixture.py")
    enc = tiktoken.get_encoding("o200k_base")
    counter = lambda text: len(enc.encode(text, disallowed_special=()))
    args.output.mkdir(parents=True)
    rows = []
    datasets = []
    concurrency = []
    for size in SIZES:
        sources = author.generate(size, 20261103, 0)
        source_map = {s["id"]: s for s in sources}
        db = args.output / f"workspace-{size}.sqlite"
        workspace = Workspace(db)
        started = time.perf_counter()
        for source in sources:
            actor = source["owner"] if source["scope"] == "private" else "editor"
            workspace.import_pages([source], actor=actor, request_id=f"import:{size}:{source['id']}")
        import_seconds = time.perf_counter() - started
        started = time.perf_counter()
        publish_info = publish_reviewed(workspace, manifest, sources)
        publish_seconds = time.perf_counter() - started
        reviewed = ReviewedWorkspace(workspace)
        raw_snapshot=workspace.store.read_snapshot(actor='reader')
        from context_lab.reviewed_context import ReviewView
        snapshots = {'reader': ReviewView(raw_snapshot)}
        datasets.append({"size": size, "sources": len(sources), "import_seconds": import_seconds,
                         "publish_seconds": publish_seconds, "published": publish_info,
                         "snapshot_sha256": {actor: view.snapshot_sha256 for actor, view in snapshots.items()}})
        for case in cases:
            for variant, text in enumerate(case["variants"]):
                request = {"text": text, "project": case["project"], "topic_id": case["topic_id"], "mode": case["mode"]}
                actor = 'reader'  # Fixed caller; never derive access from gold source IDs.
                view = snapshots[actor]
                contexts = {
                    "full_project": source_context(raw_snapshot["records"], project=case["project"], topic_id=case["topic_id"], mode=case["mode"], full=True),
                    "scoped_project": source_context(raw_snapshot["records"], project=case["project"], topic_id=case["topic_id"], mode=case["mode"], full=False),
                    "reviewed_full": view.context(case["project"], case["topic_id"], mode=case["mode"], full=True),
                    "reviewed_scoped": view.context(case["project"], case["topic_id"], mode=case["mode"], full=False),
                }
                for method, context in contexts.items():
                    wire = canonical(context)
                    scored = score(context, case, source_map, actor)
                    rows.append({"size": size, "intent_id": case["id"], "variant": variant, "method": method,
                                 "project": case["project"], "topic_id": case["topic_id"], "mode": case["mode"],
                                 "actor": actor, "context_tokens": counter(wire),
                                 "input_reference_tokens": counter(INSTRUCTION) + counter(canonical(request)) + counter(wire),
                                 "payload_sha256": hashlib.sha256(wire.encode()).hexdigest(), **scored})
        for case in cases[:1]:
            concurrency.append({"size": size, "topic_id": case["topic_id"], **concurrent_metrics(reviewed, case["project"], case["topic_id"], case["mode"])})
        print(json.dumps({"split": args.split, "size": size, "rows": len(rows)}), flush=True)
    manifest_out = {"schema": "reuse-evaluation-v1", "split": args.split,
                    "fixture_freeze_sha256": sha(args.fixture / "FREEZE.json"), "code_sha256": code_hashes,
                    "unit": "reference tokens:o200k_base", "instruction": INSTRUCTION,
                    "new_model_calls": 0, "independent_benchmark": False,
                    "source_growth_note": "noise shares projects but uses different topics; both baselines retain the same explicit scope",
                    "pinned_and_fresh_reads_are_reported_separately": True}
    (args.output / "manifest.json").write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n")
    (args.output / "rows.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    (args.output / "datasets.json").write_text(json.dumps(datasets, ensure_ascii=False, indent=2) + "\n")
    (args.output / "concurrency.json").write_text(json.dumps(concurrency, ensure_ascii=False, indent=2) + "\n")
    summary = {"rows": len(rows), "datasets": datasets, "concurrency": concurrency,
               "complete_evidence_rows": sum(r["complete_evidence"] for r in rows),
               "answerable_rows": sum(r["answerable"] for r in rows),
               "status_match_rows": sum(r["status_matches"] for r in rows),
               "private_exposure": sum(r["private_exposure"] for r in rows),
               "stale_exposure": sum(r["stale_exposure"] for r in rows),
               "note": "Synthetic diagnostic; model generation, review creation labor, and human semantic review cost are not measured."}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
