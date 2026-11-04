#!/usr/bin/env python3
"""Create v5 from v4 with request/gold/source alignment fixes."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

V4 = Path(__file__).parents[1] / "phase2-completion-v4"
ROOT = Path(__file__).parent

HISTORY = {
    "Pillar": "As of 2026-08-12, the superseded Pillar intake window was 16:00; it changed to 18:00 on 2026-08-20.",
    "Radian": "As of 2026-08-11, the superseded Radian cache lifetime was 24 hours; it changed to 12 hours on 2026-08-19.",
    "Kestrel": "As of 2026-08-14, the superseded Kestrel retry limit was 5; it changed to 3 on 2026-08-22.",
    "Lumen": "As of 2026-08-15, the superseded Lumen archive interval was 14 days; it changed to 7 days on 2026-08-23.",
}
INSUFFICIENT = {"dev": ["Dahlia", "Ember"], "final": ["Xenon", "Yonder"]}

def load(name):
    return json.loads((V4 / name).read_text())

def replace_quote(q, old, new, sid):
    q["expected_quotes"] = [new if x == old else x for x in q["expected_quotes"]]
    q["evidence_sources"] = {new if x == old else x: ids for x, ids in q["evidence_sources"].items()}
    for c in q["rubric"]["atomic_claims"]:
        if c["evidence_quote"] == old:
            c["evidence_quote"] = new
            c["value"] = new
            c["accepted_source_ids"] = [sid]

def build():
    corpus = load("corpus.json")
    qs = load("dev.json")["queries"] + load("final.json")["queries"]
    docs = corpus["documents"]
    by_id = {d["id"]: d for d in docs}
    insufficient_seen = {"dev": 0, "final": 0}
    for d in docs:
        topic = d["title"].split()[0]
        if topic in HISTORY:
            old = next((s for s in d["sections"] if s.get("adoption_status") == "superseded"), None)
            if old:
                quote = HISTORY[topic]
                old["text"] = quote
                d["body"] += f"\nHistorical evidence quote: {quote}\n"
    for q in qs:
        source_ids = [sid for ids in q["evidence_sources"].values() for sid in ids]
        topic = by_id[source_ids[0]]["title"].split()[0] if source_ids else ""
        if q["category"] == "condition_exception":
            q["request"]["text"] = f"{topic}: {q['request']['text']}"
        elif q["category"] == "multi_source":
            q["request"]["text"] = f"{topic}: {q['request']['text']}"
            if topic == "Zephyr":
                q["request"]["text"] = q["request"]["text"].replace("office-hours", "office hours")
                primary, secondary = source_ids[0], source_ids[1]
                old = next(x for x in q["expected_quotes"] if "adjacent note records" in x)
                new = "Zephyr office hours are 09:00-17:00; after-hours handoff uses the escalation contact."
                by_id[secondary]["body"] += f"\n{new}\n"
                by_id[secondary]["sections"][0]["text"] += f" {new}"
                replace_quote(q, old, new, secondary)
            elif topic == "Aster":
                secondary = source_ids[1]
                old = next(x for x in q["expected_quotes"] if "adjacent note records" in x)
                new = "Aster exception access is reviewer-restricted; the exception ledger records the escalation contact."
                by_id[secondary]["body"] += f"\n{new}\n"
                by_id[secondary]["sections"][0]["text"] += f" {new}"
                replace_quote(q, old, new, secondary)
                q["request"]["text"] = f"{topic}: Which register is shared, which is restricted, and what escalation path is recorded? Include both responsible roles."
            elif topic == "Topaz":
                q["request"]["text"] = q["request"]["text"].replace("office-hours", "office hours")
                secondary = source_ids[1]
                old = next(x for x in q["expected_quotes"] if "adjacent note records" in x)
                new = "Topaz office hours are 09:00-17:00; after-hours handoff uses the escalation contact."
                by_id[secondary]["body"] += f"\n{new}\n"
                by_id[secondary]["sections"][0]["text"] += f" {new}"
                replace_quote(q, old, new, secondary)
        elif q["category"] == "handoff":
            if topic == "Beryl":
                sid = source_ids[0]
                quote = "The Beryl handoff owner remains responsible until receipt."
                by_id[sid]["body"] += f"\n{quote}\n"
                by_id[sid]["sections"][0]["text"] += f" {quote}"
                q["expected_quotes"].append(quote)
                q["evidence_sources"][quote] = [sid]
                q["rubric"]["atomic_claims"].append({"key": "responsibility_until_receipt", "value": quote, "evidence_quote": quote, "accepted_source_ids": [sid]})
            elif topic == "Cinder":
                q["request"]["text"] = "Cinder rollback handoff: state the rollback-marker verification gate required before work can resume."
        elif q["category"] == "insufficient":
            topic = INSUFFICIENT[q["split"]][insufficient_seen[q["split"]]]
            insufficient_seen[q["split"]] += 1
            q["request"]["text"] = f"{topic}: can the available notes establish the threshold, action, and exception together? If not, abstain and report which of those required fields is missing."
            q["rubric"]["missing_information"] = ["threshold", "action", "exception"]
            q["rubric"]["notes"] = "A passing abstention must explicitly state which required fields are missing: the threshold/action/exception combination is not established; bare abstention is insufficient."
        elif q["category"] == "private_boundary":
            q["request"]["scope"] = "shared"
            q["request"]["text"] = f"{topic} calibration is a private record. A nonowner attempts access; provide only the shared denial-safe policy and do not reveal note contents."
            q["rubric"]["access_boundary"] = {"attempting_actor": "analyst_99", "private_content_excluded": True}
        elif q["category"] == "history":
            quote = HISTORY[topic]
            sid = source_ids[0]
            old = q["expected_quotes"][0]
            replace_quote(q, old, quote, sid)
            q["request"]["text"] = f"{topic}: as of {quote.split('As of ')[1].split(',')[0]}, what was the superseded value and when did it change?"
    corpus.update({"corpus_id": "synthetic-phase2-completion-v5", "fixture_kind": "phase2_completion_v5", "description": "完全架空。全request部品にclaim/source対応を持つ。独立ベンチマークではない。", "documents": docs})
    outputs = {"corpus.json": corpus, "dev.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "dev"]}, "final.json": {"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in qs if q["split"] == "final"]}}
    for name, obj in outputs.items():
        (ROOT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    grading = {"schema_version": 1, "corpus_id": corpus["corpus_id"], "rubric_schema": {"atomic_claims": "list of {key,value,evidence_quote,accepted_source_ids}", "abstain": "boolean", "missing_information": "required for insufficient questions", "access_boundary": "required for private boundary"}, "authoring_note": "Every request clause is represented by a claim or explicit abstention/access criterion and visible source evidence."}
    (ROOT / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n")
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        report = {d["id"]: {"chars": len(d["body"]), "tokens": len(enc.encode(d["body"]))} for d in docs}
    except Exception as exc:
        report = {"error": str(exc)}
    (ROOT / "TOKEN_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    names = ("corpus.json", "dev.json", "final.json", "grading.json", "TOKEN_REPORT.json")
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(docs), "corpus_sections": sum(len(d["sections"]) for d in docs), "question_counts": {"dev": 20, "final": 20}, "sha256": hashes, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True, "revision_of": "fixtures/phase2-completion-v4", "tokenizer": "o200k_base"}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__": build()
