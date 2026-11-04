"""Offline, provenance-aware grading for workflow run results.

This module deliberately receives gold separately from the runtime result.  It
checks typed values and citation mechanics; it does not claim textual
entailment.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any


def _norm_text(value: Any) -> str:
    value = "" if value is None else str(value)
    value = re.sub(r"\s+", " ", value.strip().lower())
    return value.rstrip(" .。、,;；:：!?！？")


def _same_value(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return type(actual) is bool and actual == expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return type(actual) in (int, float) and not isinstance(actual, bool) and actual == expected
    if isinstance(expected, str):
        return isinstance(actual, str) and _norm_text(actual) == _norm_text(expected)
    return actual == expected


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _source_valid(source: dict, as_of: str | None) -> bool:
    when = _day(as_of)
    start, end = _day(source.get("effective_from")), _day(source.get("effective_to"))
    return when is not None and (start is None or start <= when) and (end is None or when < end)


def _task_grade(task_id: str, task: dict, gold_task: dict, runtime: dict, canonical: dict, wave: dict) -> dict:
    output = runtime.get("output") if isinstance(runtime, dict) else None
    fields = output.get("fields", {}) if isinstance(output, dict) else {}
    payload = runtime.get("payload", {}) if isinstance(runtime, dict) else {}
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    by_id = {}
    for source in sources:
        if isinstance(source, dict): by_id.setdefault(source.get("source_id"), []).append(source)
    actor, as_of = task.get("actor"), wave["as_of"]
    available = set(wave["available_source_ids"])
    predecessor = payload.get("predecessor_handoffs", []) if isinstance(payload, dict) else []
    predecessor_fields = {}
    for handoff in predecessor:
        for name, value in (handoff.get("fields", {}) or {}).items():
            predecessor_fields[name] = value.get("value") if isinstance(value, dict) else value

    values, provenance, currentstate, handoff = {}, {}, {}, {}
    actual_citation_ids = set()
    output_text = json.dumps(output, ensure_ascii=False, sort_keys=True)
    forbidden = gold_task.get("forbidden_claims", [])
    leak = [token for token in forbidden if token and token in output_text]
    static_required = set()
    for field_name, expected_gold in gold_task.get("fields", {}).items():
        dynamic = expected_gold.get("dynamic") if isinstance(expected_gold, dict) else None
        expected = expected_gold.get("expected") if isinstance(expected_gold, dict) else None
        if dynamic and dynamic.get("kind") == "predecessor_field":
            expected = predecessor_fields.get(dynamic.get("field"))
            handoff[field_name] = _same_value(fields.get(field_name, {}).get("value") if isinstance(fields.get(field_name), dict) else None, expected)
        actual_entry = fields.get(field_name) if isinstance(fields, dict) else None
        actual = actual_entry.get("value") if isinstance(actual_entry, dict) else None
        values[field_name] = _same_value(actual, expected)
        citations = actual_entry.get("citations", []) if isinstance(actual_entry, dict) else []
        field_valid = True
        for citation in citations:
            sid, quote = citation.get("source_id"), citation.get("quote")
            source = canonical.get(sid)
            actual_citation_ids.add(sid)
            if (source is None or sid not in available or not isinstance(quote, str) or not quote.strip()
                    or quote not in source["body"] or not any(quote in s.get("text", "") for s in by_id.get(sid, []))):
                field_valid = False
            elif source.get("scope") == "private" and source.get("owner") != actor:
                field_valid = False
            elif not _source_valid(source, as_of):
                field_valid = False
        if actual is not None and not dynamic and not citations:
            field_valid = False
        provenance[field_name] = field_valid
        currentstate[field_name] = all(c.get("source_id") in available and c.get("source_id") in canonical and _source_valid(canonical[c["source_id"]], as_of) for c in citations)
        if not dynamic and expected is not None:
            for quote in expected_gold.get("exact_quotes", []):
                static_required.add(quote.get("source_id"))

    required_covered = static_required.issubset(actual_citation_ids)
    field_names = set(task.get("output_spec", {}))
    field_coverage = field_names == set(fields)
    values_ok = field_coverage and all(values.get(name, False) for name in field_names)
    citations_ok = field_coverage and all(provenance.get(name, False) for name in field_names)
    strict = values_ok and citations_ok and required_covered and not leak
    return {
        "task_id": task_id, "strict_pass": strict, "values_correct": values_ok,
        "field_values": values, "provenance_valid": provenance,
        "required_sources_covered": required_covered,
        "required_source_ids": sorted(static_required), "cited_source_ids": sorted(actual_citation_ids, key=str),
        "forbidden_code_leak": leak, "currentstate": currentstate,
        "handoff": handoff, "needs_more": output.get("needs_more") if isinstance(output, dict) else None,
        "field_coverage": field_coverage,
    }


def grade(episode: dict, gold: dict, result: dict) -> dict:
    """Grade one run without exposing gold to the runtime/retriever."""
    runtime_tasks = (result or {}).get("results", {}) if isinstance(result, dict) else {}
    task_by_id = {t.get("task_id"): t for w in episode.get("waves", []) for t in w.get("tasks", [])}
    wave_by_task = {t["task_id"]: w for w in episode.get("waves", []) for t in w.get("tasks", [])}
    canonical = {s["source_id"]: s for s in episode.get("sources", [])}
    gold_tasks = (gold or {}).get("tasks", {}) if isinstance(gold, dict) else {}
    reports, missing = [], []
    for task_id, task in task_by_id.items():
        if task_id not in runtime_tasks or task_id not in gold_tasks:
            missing.append(task_id)
            continue
        reports.append(_task_grade(task_id, task, gold_tasks[task_id], runtime_tasks[task_id], canonical, wave_by_task[task_id]))
    unknown_runtime = sorted(set(runtime_tasks) - set(task_by_id))
    return {
        "episode_id": episode.get("episode_id"),
        "case_pass": bool(reports) and len(reports) == len(task_by_id) and not missing and not unknown_runtime and all(r["strict_pass"] for r in reports),
        "task_count": len(task_by_id), "graded_tasks": len(reports), "missing_tasks": missing,
        "strict_pass_count": sum(r["strict_pass"] for r in reports),
        "values_correct_count": sum(r["values_correct"] for r in reports),
        "forbidden_leak_count": sum(bool(r["forbidden_code_leak"]) for r in reports),
        "unexpected_runtime_tasks": unknown_runtime, "tasks": reports,
        "gold_sent_to_retriever": False,
    }
