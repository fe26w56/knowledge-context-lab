"""Reaggregate saved LongMemEval retrieval rows by full-context token quartile.

This is an offline audit of an existing 500-case retrieval run. It does not call
an API and does not use labels as retrieval input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def aggregate(rows, method):
    full = [r["methods"]["full"]["input_tokens"] for r in rows]
    order = sorted(range(len(rows)), key=lambda i: (full[i], i))
    groups = []
    for q in range(4):
        start = (len(order) * q) // 4
        end = (len(order) * (q + 1)) // 4
        ids = order[start:end]
        selected = [rows[i] for i in ids]
        vals = [full[i] for i in ids]
        m = [r["methods"][method] for r in selected]
        groups.append({
            "quartile": q + 1,
            "cases": len(selected),
            "full_token_min": min(vals),
            "full_token_max": max(vals),
            "full_tokens": sum(vals),
            "method_tokens": sum(x["input_tokens"] for x in m),
            "method_tokens_vs_full_pct": round(100 * sum(x["input_tokens"] for x in m) / sum(vals), 3),
            "all_required_cases": sum(bool(x["all_required"]) for x in m),
            "required_session_hits": sum(x["required_hits"] for x in m),
            "required_session_total": sum(r["methods"]["full"]["required_hits"] for r in selected),
        })
        groups[-1]["session_recall"] = round(
            groups[-1]["required_session_hits"] / groups[-1]["required_session_total"], 6
        )
    return groups


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=Path("runs/phase2-longmemeval-corpus-v3/rows.json"))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    rows = json.loads(args.input.read_text())
    assert len(rows) == 500
    methods = ["full", "bm25six", "bm25twelve", "coverage"]
    result = {
        "schema": "phase2-token-external-growth-v1",
        "source_run": str(args.input),
        "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "corpus_cases": len(rows),
        "unit": "reference tokenizer tokens stored in corpus-v3 rows",
        "grouping": "quartiles by each case's full-context input_tokens, stable case-index tie break",
        "methods": {m: aggregate(rows, m) for m in methods},
        "overall": {
            m: {
                "cases": len(rows),
                "full_tokens": sum(r["methods"]["full"]["input_tokens"] for r in rows),
                "method_tokens": sum(r["methods"][m]["input_tokens"] for r in rows),
                "all_required_cases": sum(bool(r["methods"][m]["all_required"]) for r in rows),
                "required_session_hits": sum(r["methods"][m]["required_hits"] for r in rows),
                "required_session_total": sum(r["methods"]["full"]["required_hits"] for r in rows),
            }
            for m in methods
        },
        "interpretation": {
            "scope": "offline retrieval evidence retention only",
            "not_measured": ["model answers", "billable tokens", "Notion retrieval", "DB effect", "production agents"],
            "scale_claim": "quartile association across 500 saved cases, not a controlled corpus-size growth experiment",
            "labels_not_sent_to_retriever": True,
        },
    }
    for m, value in result["overall"].items():
        value["session_recall"] = round(value["required_session_hits"] / value["required_session_total"], 6)
        value["method_vs_full_pct"] = round(100 * value["method_tokens"] / value["full_tokens"], 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "cases": len(rows), "methods": methods}, ensure_ascii=False))


if __name__ == "__main__":
    main()
