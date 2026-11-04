#!/usr/bin/env python3
"""Mechanical v7 structural repair; questions and gold are copied byte-for-byte."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

V6 = Path(__file__).parents[1] / "phase2-completion-v6"
ROOT = Path(__file__).parent

def load(name):
    return json.loads((V6 / name).read_text())

def build():
    corpus = load("corpus.json")
    docs = corpus["documents"]
    repairs = []
    for doc in docs:
        # Preserve every existing section verbatim. If a declared section was
        # authored outside body, append it mechanically so source text is real.
        missing = [s["text"] for s in doc["sections"] if s["text"] not in doc["body"]]
        if missing:
            doc["body"] += "\n\n[Indexed source details]\n" + "\n".join(missing) + "\n"
            repairs.append({"id": doc["id"], "appended_sections": len(missing), "chars_added": sum(len(x) for x in missing)})
        # Index the complete body so long matrix/audit content is not silently
        # outside the section retrieval surface.
        if not any(s.get("kind") == "document_body" for s in doc["sections"]):
            first = doc["sections"][0]
            doc["sections"].append({"id": f"{doc['id']}_body", "heading": "Indexed document body", "text": doc["body"], "kind": "document_body", "adoption_status": first.get("adoption_status", "draft"), "valid_from": first.get("valid_from", "2026-08-01"), "valid_to": first.get("valid_to"), "verified_at": first.get("verified_at", "2026-08-29")})
    corpus.update({"corpus_id": "synthetic-phase2-completion-v7", "fixture_kind": "phase2_completion_v7_structural_repair", "description": "v6のmechanical source-consistency修正版。質問・gold・rubricは変更なし。独立ベンチマークではない。"})
    outputs = {"corpus.json": corpus}
    for name in ("dev.json", "final.json", "grading.json"):
        outputs[name] = load(name)
        if "corpus_id" in outputs[name]: outputs[name]["corpus_id"] = corpus["corpus_id"]
    for name, obj in outputs.items():
        (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        report = {d["id"]: {"body_chars": len(d["body"]), "body_tokens": len(enc.encode(d["body"])), "section_chars": sum(len(s["text"]) for s in d["sections"]), "section_tokens": sum(len(enc.encode(s["text"])) for s in d["sections"])} for d in docs}
    except Exception as exc:
        report = {"error": str(exc)}
    (ROOT / "TOKEN_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "STRUCTURAL_REPAIR.json").write_text(json.dumps({"source_version": "phase2-completion-v6", "document_repairs": repairs, "questions_changed": 0, "gold_changed": 0, "rubric_changed": 0, "body_index_section_added": len(docs), "chronology_caveat": "v6 was frozen before implementation; v7 is a mechanical structural repair after implementation work began. No baseline or candidate measurement had run.", "semantic_fixture_not_reauthored": True}, ensure_ascii=False, indent=2) + "\n")
    names = ("corpus.json", "dev.json", "final.json", "grading.json", "TOKEN_REPORT.json", "STRUCTURAL_REPAIR.json")
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(docs), "corpus_sections": sum(len(d["sections"]) for d in docs), "question_counts": {"dev": 20, "final": 20}, "sha256": hashes, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": False, "structural_repair_after_implementation_start": True, "no_baseline_or_candidate_measurement": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True, "revision_of": "fixtures/phase2-completion-v6", "tokenizer": "o200k_base"}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__": build()
