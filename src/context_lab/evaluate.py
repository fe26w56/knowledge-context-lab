"""Retrieval-only replay. This module never calls a generation model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import random
import re
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from typing import Any

from .metrics import UnitCounter, percentile
from .retrieval import RetrievalEngine, BudgetTooSmallError


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def code_hash() -> str:
    files = sorted(Path(__file__).parent.glob("*.py"))
    return canonical_hash({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings(item)]
    return []


def score_payload(payload: str, expected: list[str], forbidden: list[str]) -> tuple[list[bool], list[bool]]:
    parsed = json.loads(payload)
    texts = []
    for item in parsed.get("items", []):
        text = item["text"]
        # A can replay a Notion envelope. Only its page body is source evidence.
        match = re.search(r"<content>\n([\s\S]*?)\n</content>", text)
        texts.append(match.group(1) if match else text)
    found = [any(quote in text for text in texts) for quote in expected]
    leaked = [any(quote in text for text in strings(parsed)) for quote in forbidden]
    return found, leaked


def validate_inputs(corpus: dict, queries: dict) -> None:
    doc_ids: set[str] = set()
    section_ids: set[str] = set()
    available = []
    for doc in corpus["documents"]:
        if doc["id"] in doc_ids:
            raise ValueError("Duplicate document ID")
        doc_ids.add(doc["id"])
        available.append(doc.get("body", ""))
        for sec in doc.get("sections", []):
            if sec["id"] in section_ids:
                raise ValueError("Duplicate section ID")
            section_ids.add(sec["id"])
            if sec["text"] not in doc["body"]:
                raise ValueError(f"Section is not verbatim in original body: {sec['id']}")
    query_ids = set()
    for query in queries["queries"]:
        if query["id"] in query_ids:
            raise ValueError("Duplicate query ID")
        query_ids.add(query["id"])
        if not query["request"].get("as_of"):
            raise ValueError("Evaluation requests must fix as_of for reproducibility")
        for quote in query.get("expected_quotes", []) + query.get("forbidden_quotes", []):
            if not quote or not any(quote in text for text in available):
                raise ValueError(f"Gold quote not grounded in corpus: {query['id']}")
        if not query.get("answerable", True) and query.get("expected_quotes"):
            raise ValueError("Unanswerable cases cannot be credited for evidence coverage")


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["split"], row["method"], row["budget"])
        groups.setdefault(key, []).append(row)
    result = []
    for (split, method, budget), members in sorted(groups.items()):
        eligible = [r for r in members if r["evidence_eligible"]]
        expected_count = sum(r["expected_quote_count"] for r in eligible)
        found_count = sum(r["found_quote_count"] for r in eligible)
        units = [r["returned_units"] for r in members]
        ms = [r["retrieval_ms"] for r in members]
        result.append({
            "split": split, "method": method, "budget": budget,
            "trials": len(members), "unique_queries": len({r["query_id"] for r in members}),
            "evidence_eligible_trials": len(eligible),
            "complete_evidence_trials": sum(r["complete_evidence"] for r in eligible),
            "complete_evidence_rate": sum(r["complete_evidence"] for r in eligible) / len(eligible) if eligible else None,
            "required_quote_recall": found_count / expected_count if expected_count else None,
            "forbidden_quote_hits": sum(r["forbidden_quote_hits"] for r in members),
            "returned_units_total": sum(units), "returned_units_median": statistics.median(units),
            "local_retrieval_ms_median": statistics.median(ms), "local_retrieval_ms_p95": percentile(ms, .95),
            "budget_exceeding_trials": sum(r["returned_units"] > r["budget"] for r in members),
            "no_evidence_trials": sum(r["found_quote_count"] == 0 for r in eligible),
        })
    return result


def markdown_summary(meta: dict, summary: list[dict]) -> str:
    lines = [
        "# Retrieval replay results", "",
        f"Corpus: `{meta['corpus_id']}`. Unit: `{meta['unit']}`.", "",
        "These are local retrieval and payload measurements. Evidence coverage is not answer accuracy. No LLM responses, provider billing, network latency or D1 availability were measured.", "",
        f"A is a top-{meta['candidate_limit']}-document full-payload replay proxy. B extracts sections. C stores the same sections in SQLite and applies explicit state filters. A may exceed the stated budget; B/C flag insufficient budgets.", "",
        "| Split | Method | Budget | Complete evidence | Required quote recall | Median units | Total units | Scope leak hits |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summary:
        recall = f"{s['required_quote_recall']:.1%}" if s["required_quote_recall"] is not None else "n/a"
        lines.append(f"| {s['split']} | {s['method']} | {s['budget']} | {s['complete_evidence_trials']}/{s['evidence_eligible_trials']} | {recall} | {s['returned_units_median']:.0f} | {s['returned_units_total']} | {s['forbidden_quote_hits']} |")
    lines += ["", "Raw results include failures. No common-quality efficiency multiplier is inferred from an unqualified ratio of payload totals.", "", f"Corpus SHA-256: `{meta['corpus_sha256']}`", f"Queries SHA-256: `{meta['queries_sha256']}`", f"Code SHA-256: `{meta['code_sha256']}`", ""]
    return "\n".join(lines)


def run(corpus: dict, queries: dict, budgets: list[int], unit: str, repeats: int, output: Path, seed: int = 20261029, candidate_limit: int = 3) -> dict:
    validate_inputs(corpus, queries)
    counter = UnitCounter(unit)
    # Warm the encoding before timing retrieval. Index build is separately reported.
    counter("warmup 日本語")
    build_start = time.perf_counter()
    engine = RetrievalEngine(corpus["documents"], candidate_limit=candidate_limit)
    build_ms = (time.perf_counter() - build_start) * 1000
    jobs = [(q, method, budget, repeat) for q in queries["queries"] for method in ("A", "B", "C") for budget in budgets for repeat in range(repeats)]
    random.Random(seed).shuffle(jobs)
    rows = []
    payload_rows = []
    for query, method, budget, repeat in jobs:
        counter.__call__.cache_clear()
        start = time.perf_counter()
        retrieval_error = None
        try:
            result = engine.retrieve(method, dict(query["request"]), budget=budget, count_units=counter)
        except BudgetTooSmallError as exc:
            retrieval_error = type(exc).__name__
            result = {"payload": json.dumps({"items": [], "error": retrieval_error}), "warnings": [str(exc)]}
        retrieval_ms = (time.perf_counter() - start) * 1000
        payload = result["payload"]
        expected = query.get("expected_quotes", [])
        found, forbidden = score_payload(payload, expected, query.get("forbidden_quotes", []))
        eligible = bool(query.get("answerable", True) and expected)
        row = {
            "query_id": query["id"], "split": query.get("split", "eval"), "category": query.get("category", "unspecified"),
            "method": method, "budget": budget, "repeat": repeat, "unit": counter.unit,
            "returned_units": counter(payload), "returned_chars": len(payload),
            "retrieval_ms": retrieval_ms, "evidence_eligible": eligible,
            "expected_quote_count": len(expected) if eligible else 0,
            "found_quote_count": sum(found) if eligible else 0,
            "complete_evidence": bool(eligible and all(found)), "forbidden_quote_hits": sum(forbidden),
            "missing_quote_indices": [i for i, hit in enumerate(found) if not hit],
            "selected_documents": result.get("selected_documents", []), "selected_sections": result.get("selected_sections", []),
            "warnings": result.get("warnings", []),
            "retrieval_error": retrieval_error,
        }
        rows.append(row)
        payload_rows.append({"query_id": query["id"], "method": method, "budget": budget, "repeat": repeat, "payload": payload})
    if hasattr(engine, "close"):
        engine.close()
    rows.sort(key=lambda r: (r["split"], r["query_id"], r["method"], r["budget"], r["repeat"]))
    try:
        token_version = importlib.metadata.version("tiktoken")
    except importlib.metadata.PackageNotFoundError:
        token_version = None
    meta = {
        "schema_version": 1, "corpus_id": corpus.get("corpus_id", "unknown"), "privacy": corpus.get("privacy", "unspecified"),
        "created_at": datetime.now(timezone.utc).isoformat(), "unit": counter.unit, "tiktoken_version": token_version,
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "budgets": budgets, "repeats": repeats, "seed": seed, "candidate_limit": candidate_limit, "index_build_ms": build_ms,
        "corpus_sha256": canonical_hash(corpus), "queries_sha256": canonical_hash(queries), "code_sha256": code_hash(),
        "llm_generation_performed": False, "actual_provider_usage_measured": False, "d1_exercised": False,
        "baseline": f"local_top{candidate_limit}_full_payload_replay_proxy",
        "quality_metric": "literal_required_evidence_coverage_not_answer_accuracy",
        "timing_conditions": "encoding warmed; token-count cache cleared per trial; local-only",
    }
    output.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    for filename, value in [("metadata.json", meta), ("results.json", rows), ("summary.json", summary)]:
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    (output / "payloads.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in payload_rows))
    with (output / "results.csv").open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0]) if rows else [], lineterminator="\n")
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    (output / "SUMMARY.md").write_text(markdown_summary(meta, summary))
    return {"metadata": meta, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unit", default="chars", choices=("chars", "o200k_base", "cl100k_base"))
    parser.add_argument("--budgets", default="1000,2000,4000")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--candidate-documents", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be >= 1")
    budgets = [int(x) for x in args.budgets.split(",")]
    if any(x <= 0 for x in budgets):
        parser.error("budgets must be positive")
    report = run(json.loads(args.corpus.read_text()), json.loads(args.queries.read_text()), budgets, args.unit, args.repeats, args.output, candidate_limit=args.candidate_documents)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
