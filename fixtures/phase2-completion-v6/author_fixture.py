#!/usr/bin/env python3
"""Create v6 from v5 with temporally eligible history requests."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

V5 = Path(__file__).parents[1] / "phase2-completion-v5"
ROOT = Path(__file__).parent
HISTORY_DATES = {"Pillar": "2026-08-12", "Radian": "2026-08-11", "Kestrel": "2026-08-14", "Lumen": "2026-08-15"}

def load(name):
    return json.loads((V5 / name).read_text())

def build():
    corpus = load("corpus.json")
    qs = load("dev.json")["queries"] + load("final.json")["queries"]
    for q in qs:
        if q["category"] == "history":
            topic = next(iter(q["evidence_sources"].values()))[0]
            doc = next(d for d in corpus["documents"] if d["id"] == topic)
            name = doc["title"].split()[0]
            q["request"]["as_of"] = HISTORY_DATES[name]
            q["rubric"]["notes"] = f"History eligibility requires valid_from <= as_of < valid_to for the superseded {name} section."
    corpus.update({"corpus_id": "synthetic-phase2-completion-v6", "fixture_kind": "phase2_completion_v6", "description": "完全架空。全source/date eligibilityを検証可能にした版。独立ベンチマークではない。"})
    outputs = {"corpus.json": corpus, "dev.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "dev"]}, "final.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "final"]}}
    for name, obj in outputs.items():
        (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    grading = load("grading.json")
    grading["corpus_id"] = corpus["corpus_id"]
    grading["rubric_schema"]["temporal_eligibility"] = "for current/history, valid_from <= request.as_of < valid_to (or valid_to null); current requires adopted"
    (ROOT / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "TOKEN_REPORT.json").write_bytes((V5 / "TOKEN_REPORT.json").read_bytes())
    names = ("corpus.json", "dev.json", "final.json", "grading.json", "TOKEN_REPORT.json")
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(corpus["documents"]), "corpus_sections": sum(len(d["sections"]) for d in corpus["documents"]), "question_counts": {"dev": 20, "final": 20}, "sha256": hashes, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True, "revision_of": "fixtures/phase2-completion-v5", "tokenizer": "o200k_base"}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__": build()
