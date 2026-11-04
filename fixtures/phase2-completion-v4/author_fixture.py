#!/usr/bin/env python3
"""Create v4 from v3 with complete role claims, named abstention topics, and varied prompts."""
from __future__ import annotations
import hashlib, json, random
from datetime import datetime, timezone
from pathlib import Path

V3 = Path(__file__).parents[1] / "phase2-completion-v3"
ROOT = Path(__file__).parent

MULTI_PROMPTS = {
    "Yarrow": "Which record supplies the 30-day retention constraint, which records escalation, and what responsible role owns each?",
    "Zephyr": "Reconcile the receiving queue/checksum rule with the separate office-hours record; report both constraints and name both responsible roles.",
    "Aster": "Compare the shared decision register with the restricted exception register. State both access constraints and identify their custodians.",
    "Saffron": "Audit the scorecard against its exception ledger: give the median-reading rule, the escalation constraint, and the responsible roles.",
    "Topaz": "For this handoff, combine the queue/timestamp requirement with the office-hours exception; name the role responsible for each record.",
    "Umber": "What may the public summary expose, what remains restricted in the appendix, and which roles control those two records?",
}
CONDITION_PROMPTS = {
    "Willow": "The load review is borderline. Quote matrix row 07 and explain why its same-day decision exception prevents an automatic shutdown.",
    "Xylo": "During a possible drill, inspect matrix row 11: give the red-label action and the declared-drill exception.",
    "Quill": "A delay reached the row-15 boundary. State its minutes/unit, operator action, and maintenance-window exception.",
    "Rook": "Before dispatch, apply matrix row 19: identify the missing-tag block and the documented emergency-route exception.",
}
INSUFFICIENT = {"dev": ["Dahlia", "Ember"], "final": ["Xenon", "Yonder"]}

def load(name):
    return json.loads((V3 / name).read_text())

def build():
    corpus = load("corpus.json")
    qs = load("dev.json")["queries"] + load("final.json")["queries"]
    docs = corpus["documents"]
    by_id = {d["id"]: d for d in docs}
    # Make responsibility an observable body fact, not merely title metadata.
    multi_topics = set(MULTI_PROMPTS)
    for d in docs:
        topic = d["title"].split()[0]
        if topic in multi_topics:
            role_quote = f"Responsible role: {d['source_role']}."
            if role_quote not in d["body"]:
                d["body"] += f"\n{role_quote}\n"
            d["sections"][0]["text"] += f" {role_quote}"
        if topic in {"Willow", "Xylo", "Quill", "Rook"} and d["source_role"] in {"governing_record", "evidence record"}:
            # A deliberately over-budget governing matrix: long, topic-specific
            # audit notes ensure one side exceeds a 2k-token retrieval budget.
            audit_lines = []
            for n in range(1, 101):
                audit_lines.append(f"{topic} audit note {n:03d}: verify the row-specific threshold, unit, action, responsible operator, decision timestamp, and exception handling against the {topic.lower()} control register before applying this condition.")
            d["body"] += "\nDetailed audit notes:\n" + "\n".join(audit_lines) + "\n"
    insufficient_seen = {"dev": 0, "final": 0}
    rewritten = []
    for q in qs:
        q = json.loads(json.dumps(q))
        # Topic is recovered from listed evidence when available; insufficient
        # cases intentionally have no gold and therefore use split order.
        source_ids = [sid for ids in q["evidence_sources"].values() for sid in ids]
        topic = by_id[source_ids[0]]["title"].split()[0] if source_ids else ""
        if q["category"] == "insufficient":
            topic = INSUFFICIENT[q["split"]][insufficient_seen[q["split"]]]
            insufficient_seen[q["split"]] += 1
            q["request"]["text"] = f"Can the available {topic} notes establish the threshold, action, and exception together? If not, identify the missing combination and abstain."
        elif q["category"] == "multi_source":
            q["request"]["text"] = MULTI_PROMPTS[topic]
            # Add one role claim per document, with exact visible body evidence.
            role_claims = []
            for sid in sorted(set(source_ids)):
                role = by_id[sid]["source_role"]
                quote = f"Responsible role: {role}."
                if quote not in q["expected_quotes"]:
                    q["expected_quotes"].append(quote)
                q["evidence_sources"][quote] = [sid]
                role_claims.append({"key": f"role_{len(role_claims)+1}", "value": role, "evidence_quote": quote, "accepted_source_ids": [sid]})
            q["rubric"]["atomic_claims"].extend(role_claims)
            q["rubric"]["notes"] = "Both constraints and both responsible-role claims are required; each role is evidenced in its own record body."
        elif q["category"] == "condition_exception":
            q["request"]["text"] = CONDITION_PROMPTS[topic]
        rewritten.append(q)
    corpus.update({"corpus_id": "synthetic-phase2-completion-v4", "fixture_kind": "phase2_completion_v4", "description": "完全架空。役割claim、topic付きabstention、構造変化した条件/multi-source問を含む。独立ベンチマークではない。", "documents": docs})
    outputs = {"corpus.json": corpus, "dev.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in rewritten if q["split"] == "dev"]}, "final.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in rewritten if q["split"] == "final"]}}
    for name, obj in outputs.items():
        (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    grading = {"schema_version": 1, "corpus_id": corpus["corpus_id"], "rubric_schema": {"atomic_claims": "list of {key,value,evidence_quote,accepted_source_ids}", "abstain": "boolean", "required_source_families": "multi-source only"}, "source_roles": "roles are visible body claims, not title-only metadata", "authoring_note": "Multi-source and condition requests vary in claim order, exceptions, and comparison structure."}
    (ROOT / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n")
    # Real tokenizer report is produced when this script runs in the project venv.
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        token_report = {d["id"]: {"chars": len(d["body"]), "tokens": len(enc.encode(d["body"]))} for d in docs}
    except Exception as exc:
        token_report = {"error": str(exc)}
    (ROOT / "TOKEN_REPORT.json").write_text(json.dumps(token_report, ensure_ascii=False, indent=2) + "\n")
    names = ("corpus.json", "dev.json", "final.json", "grading.json", "TOKEN_REPORT.json")
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(docs), "corpus_sections": sum(len(d["sections"]) for d in docs), "question_counts": {"dev": 20, "final": 20}, "sha256": hashes, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True, "revision_of": "fixtures/phase2-completion-v3", "tokenizer": "o200k_base"}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__":
    build()
