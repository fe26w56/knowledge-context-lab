#!/usr/bin/env python3
"""Diagnose post-ranking state filtering using intentionally hard old versions.

Run from the repository root with:
    python3 scripts/check_obsolete_candidates.py

This is a single fixed-query diagnostic, not a large-corpus benchmark.  The
current document deliberately uses different phrasing, while obsolete titles
closely match the query.  Neither the query nor the retrieval implementation is
changed after observing results.  All names, contents, and URLs are synthetic.
Measurements use Unicode character counts, not tokens or billing data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from context_lab.retrieval import RetrievalEngine  # noqa: E402


REQUEST = {
    "text": "ルミナ計画 現在の保管方式",
    "actor": "diagnostic_reader",
    "mode": "current",
    "as_of": "2026-10-29",
}
OBSOLETE_COUNTS = (0, 3, 10, 100)
CURRENT_DOCUMENT_ID = "lumina_current"
CURRENT_SECTION_ID = "lumina_current_rule"
CURRENT_TEXT = (
    "ルミナ計画の確定事項。調査結果の原本は専用データベースに保存する。"
    "根拠のURLと版番号を一緒に残し、公開用の表示は原本から生成する。"
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def corpus(obsolete_count):
    current_section = {
        "id": CURRENT_SECTION_ID,
        "heading": "運用ルール",
        "text": CURRENT_TEXT,
        "kind": "decision",
        "adoption_status": "adopted",
        "valid_from": "2026-10-15",
        "valid_to": None,
        "verified_at": "2026-10-15",
    }
    documents = [{
        "id": CURRENT_DOCUMENT_ID,
        "title": "ルミナ計画の決定記録",
        "source_url": "https://example.invalid/lumina/current",
        "recorded_at": "2026-10-15",
        "verified_at": "2026-10-15",
        "scope": "shared",
        "owner": None,
        "body": "## 運用ルール\n" + CURRENT_TEXT,
        "sections": [current_section],
    }]
    old_text = (
        "ルミナ計画の現在の保管方式は、共有ノートの一枚に資料を集める方法である。"
        "この記録は後続の決定で置き換え済み。"
    )
    for index in range(obsolete_count):
        old_id = f"lumina_obsolete_{index:03d}"
        old_section = {
            "id": old_id + "_rule",
            "heading": "現在の保管方式",
            "text": old_text,
            "kind": "decision",
            "adoption_status": "superseded",
            "valid_from": "2026-01-01",
            "valid_to": "2026-10-15",
            "verified_at": "2026-01-01",
        }
        documents.append({
            "id": old_id,
            "title": f"ルミナ計画 現在の保管方式（旧版{index:03d}）",
            "source_url": f"https://example.invalid/lumina/obsolete/{index:03d}",
            "recorded_at": "2026-01-01",
            "verified_at": "2026-01-01",
            "scope": "shared",
            "owner": None,
            "body": "## 現在の保管方式\n" + old_text,
            "sections": [old_section],
        })
    return documents


def main():
    cases = []
    for count in OBSOLETE_COUNTS:
        documents = corpus(count)
        with RetrievalEngine(documents, candidate_limit=3) as engine:
            result = engine.retrieve("C", REQUEST, budget=2000)
            returned_texts = [item["text"] for item in json.loads(result["payload"])["items"]]
            cases.append({
                "obsolete_documents": count,
                "total_documents": len(documents),
                "corpus_sha256": hashlib.sha256(canonical(documents).encode("utf-8")).hexdigest(),
                "candidate_documents": result["candidate_documents"],
                "selected_documents": result["selected_documents"],
                "selected_sections": result["selected_sections"],
                "current_evidence_present": CURRENT_TEXT in returned_texts,
                "returned_units": result["returned_units"],
                "unit": result["unit"],
                "budget_exceeded": result["budget_exceeded"],
                "omitted_sections": result["omitted_sections"],
                "query_elapsed_ms_reference_only": result["elapsed_ms"],
                "construction_ms_reference_only": engine.index_build_ms,
                "sqlite_version": engine.sqlite_version,
            })
    misses = [case["obsolete_documents"] for case in cases if not case["current_evidence_present"]]
    report = {
        "schema_version": 1,
        "diagnostic": "obsolete_candidates_before_state_filter",
        "classification": "single_query_deliberate_hard_negative_diagnostic",
        "created_at_jst": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "request": REQUEST,
        "candidate_limit": 3,
        "budget_unicode_chars": 2000,
        "python": platform.python_version(),
        "retrieval_source_sha256": hashlib.sha256((ROOT / "src/context_lab/retrieval.py").read_bytes()).hexdigest(),
        "design": {
            "fixed_before_execution": True,
            "generation": "The adopted current document deliberately uses different wording; obsolete titles closely match the fixed query.",
            "retrieval": "Unmodified C: top three common document candidates, then SQL state and validity filters.",
            "expected_evidence": "One unchanged adopted decision exists in every corpus.",
            "data_origin": "All content is synthetic; source URLs use example.invalid.",
            "counts_are_not_population_estimates": True,
            "measurements_not_comparable_to_token_benchmarks": True,
            "timings": "One local execution per condition; reference only, not performance estimates.",
        },
        "cases": cases,
        "observation": {
            "baseline_current_evidence_present": cases[0]["current_evidence_present"],
            "first_missed_at_obsolete_count": min(misses) if misses else None,
            "missed_counts": misses,
            "interpretation": (
                "When obsolete documents occupy all candidate slots, filtering them afterwards cannot recover an eligible document outside those slots."
                if misses and cases[0]["current_evidence_present"] else
                "Inspect the per-condition evidence results; this diagnostic alone does not establish a general retrieval property."
            ),
        },
        "not_measured": [
            "LLM answer quality or downstream task completion",
            "Representative user workload or large-corpus search performance",
            "Tokens, billing, or end-to-end speedup",
            "D1 behavior, hosted availability, or authentication",
        ],
    }
    destination = ROOT / "runs/obsolete-candidates.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(destination),
        "current_evidence_by_obsolete_count": {case["obsolete_documents"]: case["current_evidence_present"] for case in cases},
        "unit": "unicode_chars",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
