"""Offline token/evidence evaluation for the frozen stability fixture."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import time

import tiktoken

from context_lab.token_retrieval import ContextRequest
from context_lab.stability_retrieval import StabilityIndex

ROOT = Path(__file__).resolve().parents[1]
SIZES = (100, 1000, 10000)
ORDER_SEEDS = (0, 1, 2)
METHODS = {
    "legacy": ("legacy", 2000),
    "canonical_2000": ("canonical", 2000),
    "canonical_8000": ("canonical", 8000),
    "parent8000": ("parent", 8000),
    "fullproject": ("full", 8000),
}

_score_spec = importlib.util.spec_from_file_location("token_growth_eval", ROOT / "scripts/evaluate_token_growth.py")
_score_module = importlib.util.module_from_spec(_score_spec)
_score_spec.loader.exec_module(_score_module)
INSTRUCTION, score = _score_module.INSTRUCTION, _score_module.score


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_module(path):
    spec = importlib.util.spec_from_file_location("stability_author", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def variants(case):
    values = case.get("variants", [])
    return values.items() if isinstance(values, dict) else enumerate(values)


def adapted_case(case, variant_text):
    value = dict(case)
    value["qid"] = f"{case['id']}::{variant_text}"
    value["text"] = variant_text
    value["required_source_ids"] = case.get("required_source_ids", [])
    value["required_quotes"] = case.get("required_quotes", [])
    value["forbidden_source_ids"] = case.get("forbidden_source_ids", [])
    return value


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["method"], row["size"], row["kind"])].append(row)
    result = []
    for (method, size, kind), group in sorted(groups.items(), key=str):
        answerable = [r for r in group if r["answerable"]]
        intents = sorted({r["intent_id"] for r in group})
        answerable_intents = sorted({r["intent_id"] for r in answerable})
        passed = []
        for intent in answerable_intents:
            observed = [r for r in answerable if r["intent_id"] == intent]
            if observed and all(r["complete_evidence"] for r in observed):
                passed.append(intent)
        tokens = [r["input_reference_tokens"] for r in group]
        result.append({"method": method, "size": size, "kind": kind,
                       "rows": len(group), "unique_intents": len(intents),
                       "answerable_rows": len(answerable),
                       "answerable_unique_intents": len(answerable_intents),
                       "all_conditions_passed_unique_intents": len(passed),
                       "complete_evidence_rows": sum(bool(r["complete_evidence"]) for r in answerable),
                       "median_input_tokens": statistics.median(tokens) if tokens else None,
                       "p95_input_tokens": sorted(tokens)[max(0, int(len(tokens) * .95 + .999999) - 1)] if tokens else None,
                       "private_exposure": sum(r["private_exposure"] for r in group),
                       "stale_exposure": sum(r["stale_exposure"] for r in group),
                       "forbidden_exposure": sum(r["forbidden_exposure"] for r in group)})
    return result


def payload_invariance(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["intent_id"], row["variant"], row["size"], row["method"])].append(row)
    checks = []
    for key, group in sorted(groups.items(), key=str):
        hashes = {row["payload_sha256"] for row in group}
        checks.append({"intent_id": key[0], "variant": key[1], "size": key[2], "method": key[3],
                       "order_seed_count": len(group), "distinct_payload_hashes": len(hashes),
                       "order_invariant": len(hashes) == 1})
    return {"groups": len(checks), "passed": sum(x["order_invariant"] for x in checks),
            "failed": sum(not x["order_invariant"] for x in checks), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "fixtures/phase2-stability-v3")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "final"), default="dev")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--seed", type=int, default=20261103)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output must be new")
    freeze = json.loads((args.fixture / "FREEZE.json").read_text())
    expected_hashes = freeze.get("hashes", {})
    for name, digest in expected_hashes.items():
        if sha(args.fixture / name) != digest:
            raise ValueError("fixture hash mismatch")
    code_files = ["src/context_lab/stability_retrieval.py", "src/context_lab/token_retrieval.py",
                  "src/context_lab/history_retrieval.py", "scripts/evaluate_token_growth.py",
                  "scripts/evaluate_stability.py"]
    code_hashes = {name: sha(ROOT / name) for name in code_files}
    fixture_hash = sha(args.fixture / "FREEZE.json")
    if args.split == "final":
        if not args.selection:
            raise ValueError("final requires frozen development selection")
        selection = json.loads(args.selection.read_text())
        if selection.get("fixture_freeze_sha256") != fixture_hash:
            raise ValueError("selection fixture hash mismatch")
        selected_hashes = selection.get("code_sha256") or selection.get("source_sha256")
        if selected_hashes != code_hashes:
            raise ValueError("selection implementation hash mismatch")
    # Deliberately load the selected split only after final selection validation.
    cases = json.loads((args.fixture / f"{args.split}.json").read_text())
    author = load_module(args.fixture / "author_fixture.py")
    enc = tiktoken.get_encoding("o200k_base")
    counter = lambda text: len(enc.encode(text, disallowed_special=()))
    args.output.mkdir(parents=True)
    manifest = {"schema": "stability-evaluation-v1", "split": args.split,
                "fixture_freeze_sha256": fixture_hash, "fixture_hashes": expected_hashes,
                "code_sha256": code_hashes, "python": platform.python_version(),
                "tiktoken": tiktoken.__version__, "sizes": list(SIZES),
                "order_seeds": list(ORDER_SEEDS), "new_model_calls": 0,
                "independent_benchmark": False,
                "counting": "instruction + whitelisted request JSON + serialized retrieved context; o200k_base; provider framing excluded"}
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    rows = []
    failure_keys = set()
    for size in SIZES:
        for order_seed in ORDER_SEEDS:
            sources = author.generate(size, args.seed, order_seed)
            source_map = {source["id"]: source for source in sources}
            index = StabilityIndex(sources, counter=counter)
            for case in cases:
                for variant, text_value in variants(case):
                    request_fields = {"text": text_value, "project": case["project"], "mode": case.get("mode", "current")}
                    request = ContextRequest(**request_fields)
                    overhead = counter(INSTRUCTION) + counter(serialize(request_fields))
                    for label, (method, budget) in METHODS.items():
                        started = time.perf_counter()
                        context = index.retrieve(request, method=method, budget=budget)
                        elapsed = time.perf_counter() - started
                        wire = serialize(context)
                        adapted = adapted_case(case, text_value)
                        scored = score(context, adapted, source_map, request.actor)
                        row = {"intent_id": case["id"], "kind": case["category"], "variant": variant, "order_seed": order_seed,
                               "size": size, "method": label, "context_tokens": counter(wire),
                               "message_overhead_tokens": overhead,
                               "input_reference_tokens": counter(wire) + overhead,
                               "payload_sha256": hashlib.sha256(wire.encode()).hexdigest(),
                               "selected_sources": len(context.get("sources", [])),
                               "retrieval_seconds": elapsed, "answerable": bool(case.get("answerable")),
                               "expected_answer_fragments_present": None, "unknown_abstention_quality": "not_model_evaluated",
                               "coverage": context.get("coverage"), "budget_exceeded": context.get("budget_exceeded"),
                               **scored}
                        rows.append(row)
                        with (args.output / "rows.jsonl").open("a") as stream:
                            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                        if row["answerable"] and not row["complete_evidence"]:
                            failure_key = (row["intent_id"], row["method"], row["size"])
                            if failure_key not in failure_keys:
                                failure_keys.add(failure_key)
                                with (args.output / "failures.jsonl").open("a") as stream:
                                    stream.write(json.dumps({k: row[k] for k in ("intent_id", "variant", "order_seed", "size", "method", "missing_quotes", "complete_evidence")}, ensure_ascii=False) + "\n")
            (args.output / "progress.json").write_text(json.dumps({"size": size, "order_seed": order_seed, "rows": len(rows)}) + "\n")
            print(json.dumps({"split": args.split, "size": size, "order_seed": order_seed, "rows": len(rows)}), flush=True)
    summary = {"manifest": manifest, "rows": len(rows), "aggregates": aggregate(rows),
               "payload_order_invariance": payload_invariance(rows),
               "unknown_rows": sum(not row["answerable"] for row in rows),
               "unknown_not_counted_as_pass": True}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
