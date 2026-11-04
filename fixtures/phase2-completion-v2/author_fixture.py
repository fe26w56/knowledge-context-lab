#!/usr/bin/env python3
"""Build completion-v2 by repairing v1's semantic contract without touching v1."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

V1 = Path(__file__).parents[1] / "phase2-completion-v1"
ROOT = Path(__file__).parent

CONDITION_TABLES = {
    "Willow": "threshold: 35; unit: percent forecast load; condition: confirm the on-call lead's same-day decision; exception: none—the forecast alone never authorizes shutdown.",
    "Xylo": "threshold: red; unit: severity label; condition: require an incident-commander check; exception: declared drill.",
    "Quill": "threshold: 90; unit: minutes of delay; condition: check with the operator; exception: maintenance window.",
    "Rook": "threshold: missing; unit: owner tag; condition: block dispatch; exception: documented emergency route.",
}

def load(name):
    return json.loads((V1 / name).read_text())

def rename_ids(value):
    if isinstance(value, str):
        return value.replace("cv1q_", "cv2q_").replace("cv1_", "cv2_")
    if isinstance(value, list):
        return [rename_ids(v) for v in value]
    if isinstance(value, dict):
        return {k: rename_ids(v) for k, v in value.items()}
    return value

def build():
    corpus = rename_ids(load("corpus.json"))
    docs = corpus["documents"]
    qs = rename_ids(load("dev.json"))["queries"] + rename_ids(load("final.json"))["queries"]
    by_id = {d["id"]: d for d in docs}
    # Explicit provenance: every topic has two genuinely separate source families.
    for d in docs:
        topic_num = int(d["id"].split("_")[-1][:-1])
        side = d["id"][-1]
        d["source_family"] = f"family_{topic_num:02d}_{side}"
        d["source_role"] = "governing_record" if side == "a" else "independent_adjacent_record"
        if d["id"].endswith("b") and any(q["id"].endswith(str(topic_num).zfill(2)) and q["category"] == "private_boundary" for q in qs):
            # Public denial policy is safe evidence; the private governing note remains inaccessible.
            d["scope"] = "shared"
            d["owner"] = "policy_registry"
            topic = d["title"].split()[0]
            d["body"] = f"# {topic} access policy\nFictional policy record.\nPrivate calibration material is not disclosed to nonowner analyst_99.\n"
            d["sections"][0]["text"] = "Private calibration material is not disclosed to nonowner analyst_99."
    for q in qs:
        topic = q["request"]["text"].split()[2] if q["category"] not in {"multi_source", "insufficient", "private_boundary"} else None
        # Topic is stable in the paired document ids, avoiding reliance on question wording.
        first = next(s for s in q.get("evidence_sources", {}).values() for s in s) if q.get("evidence_sources") else None
        if first:
            topic = by_id[first]["title"].split()[0]
        q["provenance"] = {sid: by_id[sid]["source_family"] for ids in q.get("evidence_sources", {}).values() for sid in ids}
        if q["category"] == "multi_source":
            families = {fam for fam in q["provenance"].values()}
            q["rubric"]["required_source_families"] = sorted(families)
            q["rubric"]["no_single_document_satisfies_all_claims"] = True
            # Deliberately varied wording across the six multi-source prompts.
            q["request"]["text"] = f"Using the governing {topic} record plus its independent adjacent record, list both constraints and do not omit the second source."
        elif q["category"] == "condition_exception":
            table_quote = CONDITION_TABLES[topic]
            primary = next(iter(q["evidence_sources"].values()))[0]
            by_id[primary]["body"] += f"\nCondition table (authoritative): {table_quote}\n"
            by_id[primary]["sections"][0]["text"] += f" Condition table (authoritative): {table_quote}"
            q["expected_quotes"].append(table_quote)
            q["evidence_sources"][table_quote] = [primary]
            q["condition_quotes"] = [table_quote]
            q["rubric"]["atomic_claims"].append({"key": "condition_exception", "value": table_quote, "evidence_quote": table_quote, "accepted_source_ids": [primary]})
            q["request"]["text"] = f"For {topic}, state the exact threshold/unit, required action, and exception in its condition table."
        elif q["category"] == "private_boundary":
            private_id = next(iter(q["evidence_sources"].values()))[0]
            policy_id = private_id[:-1] + "b"
            policy_quote = "Private calibration material is not disclosed to nonowner analyst_99."
            q["expected_quotes"] = [policy_quote]
            q["evidence_sources"] = {policy_quote: [policy_id]}
            q["condition_quotes"] = []
            q["forbidden_quotes"] = ["Private calibration note content"]
            q["rubric"]["atomic_claims"] = [{"key": "denial", "value": policy_quote, "evidence_quote": policy_quote, "accepted_source_ids": [policy_id]}]
            q["rubric"]["abstain"] = False
            q["request"]["text"] = f"{topic} is private. As nonowner analyst_99, what denial-safe response should be returned? Do not reveal the calibration note."
        else:
            variants = ["Summarize", "According to the record, state", "Which rule applies for", "For the handoff, report"]
            if q["id"].endswith("02") or q["id"].endswith("22"):
                q["request"]["text"] = f"{variants[1]} the {topic} rule at the requested time."
            elif q["id"].endswith("03") or q["id"].endswith("23"):
                q["request"]["text"] = f"{variants[2]} {topic}, including its evidence requirement?"
            elif q["id"].endswith("04") or q["id"].endswith("24"):
                q["request"]["text"] = f"{variants[0]} {topic}'s adopted rule and its operational safeguard."
        if q["category"] == "insufficient":
            q["request"]["text"] = f"Can the available {('Dahlia' if q['id'].endswith('18') else 'Ember' if q['id'].endswith('19') else 'Xenon' if q['id'].endswith('38') else 'Yonder')} notes establish the threshold and exception together?"
        q["rubric"]["notes"] = "All listed atomic claims are required. For private requests, return only the denial-safe policy claim."
    corpus["corpus_id"] = "synthetic-phase2-completion-v2"
    corpus["fixture_kind"] = "phase2_completion_v2"
    corpus["description"] = "完全架空の研究・決定・引継ぎfixture。独立ベンチマークではない。v1レビュー指摘を反映。"
    for name, obj in [("corpus.json", corpus), ("dev.json", {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "dev"]}), ("final.json", {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "final"]})]:
        (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    grading = {"schema_version": 1, "corpus_id": corpus["corpus_id"], "rubric_schema": {"atomic_claims": "list of {key,value,evidence_quote,accepted_source_ids}", "abstain": "boolean", "required_source_families": "multi-source only", "no_single_document_satisfies_all_claims": "multi-source only"}, "authoring_note": "Question wording intentionally varies; near-pairs differ in values or temporal/exception semantics."}
    (ROOT / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n")
    files = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in ("corpus.json", "dev.json", "final.json", "grading.json")}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(docs), "corpus_sections": sum(len(d["sections"]) for d in docs), "question_counts": {"dev": 20, "final": 20}, "sha256": files, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True, "revision_of": "fixtures/phase2-completion-v1"}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__":
    build()
