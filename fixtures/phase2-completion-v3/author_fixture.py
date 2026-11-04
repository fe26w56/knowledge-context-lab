#!/usr/bin/env python3
"""Create v3 from the reviewed v2 payload, with explicit roles and opaque IDs."""
from __future__ import annotations
import hashlib, json, random
from datetime import datetime, timezone
from pathlib import Path

V2 = Path(__file__).parents[1] / "phase2-completion-v2"
ROOT = Path(__file__).parent

TABLES = {
 "Willow": ("07", "35", "percent forecast load", "confirm on-call lead same-day decision", "none; forecast alone never authorizes shutdown"),
 "Xylo": ("11", "red", "severity label", "incident-commander check", "declared drill"),
 "Quill": ("15", "90", "minutes of delay", "operator check", "maintenance window"),
 "Rook": ("19", "missing", "owner tag", "block dispatch", "documented emergency route"),
}

def load(name):
    return json.loads((V2 / name).read_text())

def opaque(seed, prefix):
    return prefix + hashlib.sha256(seed.encode()).hexdigest()[:16]

def table_text(topic, row, threshold, unit, action, exception):
    rows = ["| row | threshold | unit | action / exception |", "|---:|---|---|---|"]
    for n in range(1, 21):
        if f"{n:02d}" == row:
            rows.append(f"| {n:02d} | {threshold} | {unit} | {action}; exception: {exception} |")
        else:
            if topic in {"Willow", "Quill"}:
                rows.append(f"| {n:02d} | {n * 5} | minutes or percent | record {topic.lower()} reading {n}; exception: operator review |")
            elif topic == "Xylo":
                rows.append(f"| {n:02d} | severity-{n:02d} | severity label | route {topic.lower()} case {n}; exception: documented drill |")
            else:
                rows.append(f"| {n:02d} | owner-state-{n:02d} | owner tag | route {topic.lower()} dispatch {n}; exception: emergency route review |")
    return "\n".join(rows)

def build():
    corpus = load("corpus.json")
    qs = load("dev.json")["queries"] + load("final.json")["queries"]
    old_docs = corpus["documents"]
    old_to_new = {}
    docs = []
    # Remap every document to a hash-derived opaque ID unrelated to question number or a/b.
    for d in old_docs:
        new = dict(d)
        nid = opaque(d["id"] + "|phase2-completion-v3", "cv3d_")
        old_to_new[d["id"]] = nid
        new["id"] = nid
        # Make source roles and titles meaningful for the 6 multi-source topics.
        topic = d["title"].split()[0]
        side = d["source_family"].rsplit("_", 1)[-1]
        role_map = {
            "Yarrow": ("運行到着ログ", "運行記録責任者"), "Zephyr": ("窓口引渡記録", "受渡窓口責任者"), "Aster": ("決定登録簿", "審査責任者"),
            "Saffron": ("採点観測ログ", "測定責任者"), "Topaz": ("窓口引渡記録", "受渡窓口責任者"), "Umber": ("公開要約台帳", "公開責任者"),
        }
        if topic in role_map:
            role, owner = role_map[topic] if side == "a" else (("運行例外台帳" if topic == "Yarrow" else "窓口営業時間決定" if topic in {"Zephyr", "Topaz"} else "例外アクセス台帳" if topic in {"Aster", "Umber"} else "測定例外台帳"), "独立記録責任者")
            new["title"] = f"{topic} {role}"
            new["owner"] = owner
            new["source_role"] = role
            new["body"] = new["body"].replace(f"# {topic} adjacent note", f"# {topic} {role}").replace(f"# {topic} research record", f"# {topic} {role}")
        if topic in TABLES and side == "a":
            row, threshold, unit, action, exception = TABLES[topic]
            text = table_text(topic, row, threshold, unit, action, exception)
            notes = "\n".join(f"Row {n:02d} note: {topic} reviewers record the observed value, responsible operator, decision timestamp, and exception handling before treating the row as applicable." for n in range(1, 21))
            exact = f"row {row}: threshold {threshold}; unit {unit}; action {action}; exception {exception}."
            new["body"] += "\n\nAuthoritative condition matrix (20 rows; all values are fictional):\n" + text + f"\nException note: row {row} is the governing exception-aware row; do not substitute another row.\n" + notes + "\n" + exact + "\n"
            new["sections"][0]["text"] += f" Authoritative condition matrix row {row}: threshold {threshold}; unit {unit}; action {action}; exception {exception}."
        docs.append(new)
    # Rewrite all source references and question IDs. Question text now asks for specific rows/roles.
    rewritten = []
    for q in qs:
        q = json.loads(json.dumps(q))
        q["id"] = opaque(q["id"] + "|phase2-completion-v3", "cv3q_")
        for old, new in old_to_new.items():
            q["expected_quotes"] = q["expected_quotes"]
            q["evidence_sources"] = {quote: [new if sid == old else sid for sid in ids] for quote, ids in q["evidence_sources"].items()}
            for c in q["rubric"]["atomic_claims"]:
                c["accepted_source_ids"] = [new if sid == old else sid for sid in c["accepted_source_ids"]]
        q["provenance"] = {sid: next(d["source_family"] for d in docs if d["id"] == sid) for ids in q["evidence_sources"].values() for sid in ids}
        # The topic is recoverable from the governing title, not from an ID pattern.
        primary = next(iter(q["evidence_sources"].values()), [])
        topic = next((d["title"].split()[0] for d in docs if d["id"] in primary), "")
        if q["category"] == "condition_exception":
            row, threshold, unit, action, exception = TABLES[topic]
            exact = f"row {row}: threshold {threshold}; unit {unit}; action {action}; exception {exception}."
            sid = primary[0]
            q["expected_quotes"].append(exact)
            q["evidence_sources"][exact] = [sid]
            q["condition_quotes"] = [exact]
            q["rubric"]["atomic_claims"].append({"key": "matrix_row", "value": exact, "evidence_quote": exact, "accepted_source_ids": [sid]})
            q["request"]["text"] = f"Read row {row} of the {topic} condition matrix: give its threshold, unit, action, and exception, including the exception note."
        elif q["category"] == "multi_source":
            role = next(d["source_role"] for d in docs if d["id"] == primary[0])
            q["request"]["text"] = f"Compare the {topic} {role} with its separate exception record; report both constraints and the responsible roles."
            q["rubric"]["notes"] = "The arrival/decision/exception records are different roles; both claims are required."
        elif q["category"] == "handoff":
            q["request"]["text"] = f"Prepare the {topic} handoff under its receipt gate: state the required artifact and the condition that prevents premature completion."
        elif q["category"] == "insufficient":
            q["request"]["text"] = f"Do the available {topic} notes establish the complete threshold, action, and exception? If not, abstain and identify the missing combination."
        elif q["category"] == "private_boundary":
            q["request"]["text"] = f"{topic} calibration is private. As nonowner analyst_99, provide only the denial-safe policy; do not reveal note contents."
        q["rubric"]["notes"] = q["rubric"].get("notes", "") + " Source IDs are grader metadata and must not be placed in retrieval requests."
        rewritten.append(q)
    qs = rewritten
    # Deterministically shuffle document order.
    random.Random(20261030).shuffle(docs)
    corpus.update({"corpus_id": "synthetic-phase2-completion-v3", "fixture_kind": "phase2_completion_v3", "description": "完全架空。役割分離、条件表、否認安全、opaque hash IDを含む。独立ベンチマークではない。", "documents": docs})
    outputs = {"corpus.json": corpus, "dev.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "dev"]}, "final.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "final"]}}
    for name, obj in outputs.items(): (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    grading = {"schema_version": 1, "corpus_id": corpus["corpus_id"], "rubric_schema": {"atomic_claims": "list of {key,value,evidence_quote,accepted_source_ids}", "abstain": "boolean", "required_source_families": "multi-source only"}, "source_roles": "operational/arrival, decision/office-hours, exception/access records carry distinct claims", "authoring_note": "Document order is shuffled; IDs are hash-derived and unrelated to question numbering."}
    (ROOT / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n")
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in ("corpus.json", "dev.json", "final.json", "grading.json")}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(docs), "corpus_sections": sum(len(d["sections"]) for d in docs), "question_counts": {"dev": 20, "final": 20}, "sha256": hashes, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True, "revision_of": "fixtures/phase2-completion-v2"}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__": build()
