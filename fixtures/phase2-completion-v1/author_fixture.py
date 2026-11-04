#!/usr/bin/env python3
"""Author and deterministically emit the phase2 completion fixture.

This file is intentionally self-contained: it contains only fictional research
notes and no implementation or prior benchmark data.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
PREFIX = "cv1_"

# Twenty topics per split.  The repeated current pair (Lattice/Marrow) is an
# intentional near-condition pair: both mention retention, but differ in days.
TOPICS = [
    ("Lattice", "dev", "current", "The adopted Lattice retention rule is 45 days, and deletion requires an approval record.", "Lattice retains audit traces for 45 days; deletion requires an approval record."),
    ("Marrow", "dev", "current", "The adopted Marrow retention rule is 60 days, and deletion requires an approval record.", "Marrow retains audit traces for 60 days; deletion requires an approval record."),
    ("Nimbus", "dev", "current", "The adopted Nimbus export rule is encrypted transfer, with the checksum stored before handoff.", "Nimbus exports use encrypted transfer; the checksum is stored before handoff."),
    ("Orchid", "dev", "current", "The adopted Orchid review rule requires two reviewers before publication.", "Orchid publication requires confirmation by two reviewers."),
    ("Pillar", "dev", "history", "As of 2026-08-12, the superseded Pillar intake window was 16:00; it changed to 18:00 on 2026-08-20.", "The superseded Pillar intake window was 16:00; it changed to 18:00 on 2026-08-20."),
    ("Radian", "dev", "history", "As of 2026-08-11, the superseded Radian cache lifetime was 24 hours; it changed to 12 hours on 2026-08-19.", "The superseded Radian cache lifetime was 24 hours; it changed to 12 hours on 2026-08-19."),
    ("Sable", "dev", "proposal", "The Sable per-team quota proposal is not adopted and remains under review.", "The per-team quota proposal is under review and is not adopted."),
    ("Tundra", "dev", "proposal", "The Tundra automatic purge proposal was rejected and is not an active rule.", "The automatic purge proposal was rejected and is not an active rule."),
    ("Umbra", "dev", "paraphrase", "For Umbra, a failed checksum means the package must be held for manual review.", "A checksum failure places the Umbra package on hold for manual review."),
    ("Vela", "dev", "paraphrase", "For Vela, a missing consent receipt blocks publication.", "Vela cannot be published when its consent receipt is missing."),
    ("Willow", "dev", "condition_exception", "For Willow, a 35-percent load forecast requires the on-call lead's same-day decision; the forecast alone does not authorize shutdown.", "If Willow's load forecast reaches 35%, confirm the on-call lead's same-day decision; do not infer shutdown from the forecast alone."),
    ("Xylo", "dev", "condition_exception", "For Xylo, a red severity label requires an incident commander check, except during a declared drill.", "A red Xylo severity label requires an incident-commander check, except during a declared drill."),
    ("Yarrow", "dev", "multi_source", "Yarrow keeps review logs for 30 days.", "The Yarrow review log retention is 30 days."),
    ("Zephyr", "dev", "multi_source", "Zephyr handoffs require the receiving queue and a checksum.", "A Zephyr handoff records both the receiving queue and the checksum."),
    ("Aster", "dev", "multi_source", "Aster's decision register is shared, while its exception register is restricted to reviewers.", "Aster's decision register is shared, and the exception register is reviewer-restricted."),
    ("Beryl", "dev", "handoff", "The Beryl handoff owner must attach the unresolved-question list before transfer.", "Before transferring Beryl, attach the unresolved-question list; the handoff owner remains responsible until receipt."),
    ("Cinder", "dev", "handoff", "Cinder's next operator must verify the rollback marker before resuming work.", "Cinder's next operator verifies the rollback marker before resuming work."),
    ("Dahlia", "dev", "insufficient", "", ""),
    ("Ember", "dev", "insufficient", "", ""),
    ("Fable", "dev", "private_boundary", "The private Fable calibration note is visible only to its owner; nonowner analyst_99 must be denied.", "Fable calibration note: owner analyst_17 only; nonowner analyst_99 is denied."),
    ("Garnet", "final", "current", "The adopted Garnet sampling rule is 8 items per batch, and the batch manifest is retained.", "Garnet samples 8 items per batch; retain the batch manifest."),
    ("Harbor", "final", "current", "The adopted Harbor alert rule pages after three consecutive failures and records the window.", "Harbor pages after three consecutive failures and records the alert window."),
    ("Indigo", "final", "current", "The adopted Indigo review rule requires a signed decision and a linked evidence note.", "Indigo requires a signed decision linked to an evidence note."),
    ("Juniper", "final", "current", "The adopted Juniper redaction rule removes direct identifiers before export and records a two-person check.", "Juniper exports remove direct identifiers and record a two-person redaction check."),
    ("Kestrel", "final", "history", "As of 2026-08-14, the superseded Kestrel retry limit was 5; it changed to 3 on 2026-08-22.", "The superseded Kestrel retry limit was 5; it changed to 3 on 2026-08-22."),
    ("Lumen", "final", "history", "As of 2026-08-15, the superseded Lumen archive interval was 14 days; it changed to 7 days on 2026-08-23.", "The superseded Lumen archive interval was 14 days; it changed to 7 days on 2026-08-23."),
    ("Mica", "final", "proposal", "The Mica zero-review publication proposal is not adopted and is explicitly rejected.", "The zero-review publication proposal is rejected and not adopted."),
    ("Nectar", "final", "proposal", "The Nectar auto-merge proposal is pending review and must not be treated as active.", "The auto-merge proposal is pending review and is not active."),
    ("Oriel", "final", "paraphrase", "For Oriel, an unsigned manifest prevents release.", "Oriel release is blocked when the manifest lacks a signature."),
    ("Pumice", "final", "paraphrase", "For Pumice, a stale source marker requires revalidation before use.", "A stale Pumice source marker requires revalidation before use."),
    ("Quill", "final", "condition_exception", "For Quill, a 90-minute delay requires an operator check; a maintenance window is an exception.", "When Quill delay reaches 90 minutes, check with the operator, except during a maintenance window."),
    ("Rook", "final", "condition_exception", "For Rook, a missing owner tag blocks dispatch, except for the documented emergency route.", "A missing Rook owner tag blocks dispatch, except on the documented emergency route."),
    ("Saffron", "final", "multi_source", "Saffron's scorecard uses the median of three readings.", "The Saffron scorecard uses the median of three readings."),
    ("Topaz", "final", "multi_source", "Topaz handoffs require a named queue and a receipt timestamp.", "A Topaz handoff includes a named queue and receipt timestamp."),
    ("Umber", "final", "multi_source", "Umber's public summary omits raw identifiers, while the audit appendix is restricted.", "The Umber public summary omits raw identifiers; its audit appendix is restricted."),
    ("Violet", "final", "handoff", "The Violet handoff package must include the last verified checkpoint.", "Include Violet's last verified checkpoint in the handoff package; do not mark transfer complete until receipt."),
    ("Wren", "final", "handoff", "Wren's receiving operator must acknowledge the dependency list before execution.", "Wren's receiving operator acknowledges the dependency list before execution."),
    ("Xenon", "final", "insufficient", "", ""),
    ("Yonder", "final", "insufficient", "", ""),
    ("Zinnia", "final", "private_boundary", "The private Zinnia calibration note is visible only to owner analyst_18; nonowner analyst_99 must be denied.", "Zinnia calibration note: owner analyst_18 only; nonowner analyst_99 is denied."),
]

def doc_id(i: int, side: str) -> str:
    return f"{PREFIX}doc_{i:02d}{side}"

def make_docs(i: int, topic: str, split: str, category: str, claim: str, quote: str):
    primary = doc_id(i, "a")
    near = doc_id(i, "b")
    scope = "private" if category == "private_boundary" else "shared"
    owner = "analyst_17" if topic == "Fable" else ("analyst_18" if topic == "Zinnia" else f"owner_{i:02d}")
    status = {"history": "superseded", "proposal": "proposed"}.get(category, "adopted")
    section = {"id": f"{primary}_s1", "heading": "Evidence", "text": quote or "The available notes do not establish the requested combined condition.", "kind": "decision", "adoption_status": status, "valid_from": "2026-08-01", "valid_to": "2026-08-20" if category == "history" else None, "verified_at": "2026-08-29"}
    table = "\n\n| threshold | unit | condition | exception |\n|---|---|---|---|\n| stated value | percent or minutes | operator check required | documented maintenance or drill |" if category == "condition_exception" else ""
    evidence_line = quote or "The available notes do not establish the requested combined condition."
    body = f"# {topic} research record\nFictional evaluation material; no real person or organization is represented.\nScope: {scope}; owner: {owner}.\n\n{claim or 'This note records only a partial observation and does not establish the requested answer.'}\nEvidence quote: {evidence_line}{table}\n"
    primary_doc = {"id": primary, "title": f"{topic} evidence record", "source_url": f"https://example.invalid/phase2-completion-v1/{primary}", "recorded_at": "2026-08-29", "verified_at": "2026-08-29", "scope": scope, "owner": owner, "body": body, "sections": [section]}
    near_text = (f"The {topic} adjacent note records an escalation contact." if category == "multi_source" else (f"A nearby {topic} note uses similar wording but is not the governing record. It must not replace the evidence above." if quote else f"A nearby {topic} note mentions a related observation but omits the requested condition."))
    near_doc = {"id": near, "title": f"{topic} adjacent research note", "source_url": f"https://example.invalid/phase2-completion-v1/{near}", "recorded_at": "2026-08-28", "verified_at": "2026-08-28", "scope": scope, "owner": owner, "body": f"# {topic} adjacent note\nFictional evaluation material.\n{near_text}\n", "sections": [{"id": f"{near}_s1", "heading": "Adjacent note", "text": near_text, "kind": "note", "adoption_status": "draft", "valid_from": "2026-08-01", "valid_to": None, "verified_at": "2026-08-28"}]}
    return primary_doc, near_doc

def make_question(i: int, topic: str, split: str, category: str, claim: str, quote: str):
    a, b = doc_id(i, "a"), doc_id(i, "b")
    private = category == "private_boundary"
    actor = "analyst_99" if private else f"analyst_{(i % 7) + 1:02d}"
    scope = "private" if private else "shared"
    mode = "history" if category == "history" else ("current" if category == "current" else "search")
    if category == "insufficient":
        text = f"What is the complete adopted rule for {topic}, including the missing threshold and exception?"
        expected, evidence, atomic = [], {}, []
        answerable, abstain = False, True
    elif category == "multi_source":
        text = f"Combine the {topic} evidence record and its adjacent note: what two constraints apply?"
        # second constraint is deliberately in the second source only
        second = f"The {topic} adjacent note records an escalation contact." 
        quote = f"{quote}"
        expected, evidence = [quote, second], {quote: [a], second: [b]}
        atomic = [{"key": "primary_constraint", "value": claim, "evidence_quote": quote, "accepted_source_ids": [a]}, {"key": "secondary_constraint", "value": second, "evidence_quote": second, "accepted_source_ids": [b]}]
        atomic[1]["value"] = second
        answerable, abstain = True, False
    else:
        text = (f"What is the private {topic} rule, and should nonowner analyst_99 receive it?" if private else f"What is the {('current' if category == 'current' else 'historical' if category == 'history' else 'proposed' if category == 'proposal' else 'handoff') } {topic} rule?")
        expected, evidence = ([quote] if quote else []), ({quote: [a]} if quote else {})
        atomic = ([{"key": "claim_1", "value": claim, "evidence_quote": quote, "accepted_source_ids": [a]}] if quote else [])
        answerable, abstain = True, False
    obsolete = ["The adjacent draft is not the governing record."] if category == "history" else []
    forbidden = ["Do not disclose private material to a nonowner."] if private else []
    condition = ["Apply the stated exception before concluding."] if category == "condition_exception" else []
    return {"id": f"cv1q_{i:02d}", "split": split, "category": category, "request": {"text": text, "actor": actor, "scope": scope, "mode": mode, "as_of": "2026-08-29"}, "expected_quotes": expected, "evidence_sources": evidence, "condition_quotes": condition, "obsolete_quotes": obsolete, "forbidden_quotes": forbidden, "answerable": answerable, "rubric": {"atomic_claims": atomic, "abstain": abstain, "notes": "Every atomic claim must be supported by its evidence_quote; abstain when answerable is false."}}

def build():
    docs, questions, grading = [], [], {"schema_version": 1, "corpus_id": "synthetic-phase2-completion-v1", "rubric_schema": {"atomic_claims": "list of {key,value,evidence_quote,accepted_source_ids}", "abstain": "boolean; true requires explicit insufficiency"}, "question_ids": []}
    for i, (topic, split, category, claim, quote) in enumerate(TOPICS, 1):
        p, n = make_docs(i, topic, split, category, claim, quote)
        docs.extend([p, n])
        q = make_question(i, topic, split, category, claim, quote)
        questions.append(q)
        grading["question_ids"].append(q["id"])
    corpus = {"schema_version": 1, "corpus_id": "synthetic-phase2-completion-v1", "privacy": "public_synthetic", "fixture_kind": "phase2_completion_v1", "description": "完全架空の研究・決定・引継ぎfixture。独立ベンチマークではない。", "documents": docs}
    (ROOT / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "dev.json").write_text(json.dumps({"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in questions if q["split"] == "dev"]}, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "final.json").write_text(json.dumps({"schema_version": 1, "corpus_id": corpus["corpus_id"], "queries": [q for q in questions if q["split"] == "final"]}, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n")
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("corpus.json", "dev.json", "final.json", "grading.json")}
    freeze = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_documents": len(docs), "corpus_sections": sum(len(d["sections"]) for d in docs), "question_counts": {"dev": 20, "final": 20}, "sha256": files, "author_not_exposed_to_new_implementation": True, "frozen_before_improvement_implementation": True, "independent_benchmark": False, "source_ids_are_grader_metadata": True}
    (ROOT / "FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__":
    build()
