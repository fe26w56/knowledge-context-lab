#!/usr/bin/env python3
"""Audit workflow fixtures without sending gold data to a retriever/model.

The episode JSON is the runtime input.  Gold is loaded from a sibling
``gold.json`` only for this offline audit and is never emitted as runtime
payload.  The command writes a fresh JSON report and refuses to overwrite it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import date


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _issue(items, code, message, *, task=None, severity="error"):
    row = {"code": code, "message": message, "severity": severity}
    if task is not None:
        row["task_id"] = task
    items.append(row)


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def audit_episode(ep: dict, gold: dict, schema: dict) -> dict:
    errors, warnings = [], []
    episode_id = ep.get("episode_id")
    if not episode_id or ep.get("gold") is not None:
        _issue(errors, "runtime_gold_mixing", "episode runtime must not contain gold")
    if gold.get("episode_id") != episode_id:
        _issue(errors, "gold_episode_mismatch", "gold episode_id does not match runtime")
    sources = ep.get("sources", [])
    source_by_id = {s.get("source_id"): s for s in sources if isinstance(s, dict)}
    if len(source_by_id) != len(sources):
        _issue(errors, "duplicate_source_id", "source IDs must be unique")
    for source_id, source in source_by_id.items():
        if not isinstance(source_id, str) or not source_id:
            _issue(errors, "invalid_source_id", "source_id must be a non-empty string")
        for key in ("logical_id", "revision", "scope", "owner", "title", "body", "state"):
            if not isinstance(source.get(key), str) or not source[key]:
                _issue(errors, "source_field", f"source {source_id!r} missing string {key}")
        if source.get("scope") == "private" and not source.get("owner"):
            _issue(errors, "private_owner", f"private source {source_id!r} has no owner")
        if source.get("scope") not in {"shared", "private"}:
            _issue(errors, "source_scope", f"source {source_id!r} has invalid scope")

    waves = ep.get("waves", [])
    if len(waves) != 4:
        _issue(errors, "wave_count", f"expected 4 waves, got {len(waves)}")
    tasks = []
    task_wave = {}
    actors = []
    for wave_index, wave in enumerate(waves, 1):
        if wave.get("wave") != wave_index:
            _issue(errors, "wave_order", f"wave position {wave_index} has label {wave.get('wave')!r}")
        available = wave.get("available_source_ids", [])
        if len(available) != len(set(available)):
            _issue(errors, "available_duplicates", "available_source_ids contains duplicates")
        for sid in available:
            if sid not in source_by_id:
                _issue(errors, "unknown_available_source", f"wave exposes unknown source {sid!r}")
        wave_tasks = wave.get("tasks", [])
        if len(wave_tasks) != 4:
            _issue(errors, "tasks_per_wave", f"wave {wave_index} expected 4 tasks, got {len(wave_tasks)}")
        for task in wave_tasks:
            tid, actor = task.get("task_id"), task.get("actor")
            if not tid or tid in task_wave:
                _issue(errors, "task_id", f"duplicate or missing task_id {tid!r}")
            task_wave[tid] = wave_index
            tasks.append(task)
            actors.append(actor)
            if not isinstance(task.get("request"), str) or not task["request"].strip():
                _issue(errors, "task_request", "task request is empty", task=tid)
            spec = task.get("output_spec")
            if not isinstance(spec, dict) or not 3 <= len(spec) <= 6:
                _issue(errors, "output_spec", "output_spec must contain 3-6 fields", task=tid)
            for field, definition in (spec or {}).items():
                if not isinstance(definition, dict) or definition.get("type") == "null":
                    _issue(errors, "null_output_type", f"output field {field!r} exposes null-only type", task=tid)
                if not isinstance(definition, dict) or not isinstance(definition.get("description"), str):
                    _issue(errors, "output_description", f"output field {field!r} lacks description", task=tid)
            for dep in task.get("depends_on", []):
                if dep not in task_wave:
                    _issue(errors, "unknown_dependency", f"dependency {dep!r} is unknown", task=tid)
                elif task_wave[dep] >= wave_index:
                    _issue(errors, "same_wave_dependency", f"dependency {dep!r} is not from a prior wave", task=tid)
            # IDs belong to the corpus/wave, never to the model-facing task.
            task_text = json.dumps({k: v for k, v in task.items() if k != "depends_on"}, ensure_ascii=False)
            leaked = [sid for sid in source_by_id if sid in task_text]
            if leaked:
                _issue(errors, "source_id_leak", f"task contains source IDs {leaked}", task=tid)
            for sid in task.get("visible_sources", []):
                _issue(errors, "legacy_visible_sources", "task must not select source IDs directly", task=tid)

    if len(set(actors)) != 16:
        _issue(errors, "actor_count", f"expected 16 distinct actors, got {len(set(actors))}")
    if len(tasks) != 16:
        _issue(errors, "task_count", f"expected 16 tasks, got {len(tasks)}")

    gold_tasks = gold.get("tasks", {})
    if set(gold_tasks) != set(task_wave):
        _issue(errors, "gold_task_coverage", "gold must cover exactly every runtime task")
    for task in tasks:
        tid = task["task_id"]
        entry = gold_tasks.get(tid)
        if not entry:
            continue
        spec_fields = set(task.get("output_spec", {}))
        gold_fields = set(entry.get("fields", {}))
        if spec_fields != gold_fields:
            _issue(errors, "field_coverage", f"runtime/gold fields differ: {spec_fields ^ gold_fields}", task=tid)
        wave = waves[task_wave[tid] - 1]
        available = set(wave.get("available_source_ids", []))
        as_of = _day(wave.get("as_of"))
        if as_of is None:
            _issue(errors, "wave_as_of", "wave has no ISO as_of date", task=tid)
        actor = task.get("actor")
        required = set(entry.get("required_source_ids", []))
        for sid in required:
            source = source_by_id.get(sid)
            if source is None:
                _issue(errors, "unknown_required_source", f"required source {sid!r} is absent", task=tid)
            elif sid not in available:
                _issue(errors, "required_not_available", f"required source {sid!r} is not available at wave time", task=tid)
            elif source.get("scope") == "private" and source.get("owner") != actor:
                _issue(errors, "private_scope", f"private source {sid!r} is not visible to {actor!r}", task=tid)
            if source is not None and as_of is not None:
                start, end = _day(source.get("effective_from")), _day(source.get("effective_to"))
                if start is not None and start > as_of:
                    _issue(errors, "source_not_yet_effective", f"required source {sid!r} starts after wave as_of", task=tid)
                if end is not None and as_of >= end:
                    _issue(errors, "source_expired", f"required source {sid!r} expired before wave as_of", task=tid)
        quoted_sources = set()
        for field, field_gold in entry.get("fields", {}).items():
            expected = field_gold.get("expected")
            unknown = field_gold.get("must_be_unknown")
            if unknown != (expected is None):
                _issue(errors, "unknown_mismatch", f"must_be_unknown={unknown!r} but expected={expected!r}", task=tid)
            dynamic = field_gold.get("dynamic")
            if dynamic is not None:
                if not isinstance(dynamic, dict) or dynamic.get("kind") != "predecessor_field":
                    _issue(errors, "dynamic_gold_schema", "dynamic gold must declare predecessor_field", task=tid)
                else:
                    predecessor = dynamic.get("task_id")
                    if predecessor not in task_wave:
                        _issue(errors, "dynamic_predecessor_missing", "dynamic predecessor task is absent", task=tid)
                    elif task_wave[predecessor] >= task_wave[tid]:
                        _issue(errors, "dynamic_predecessor_order", "dynamic predecessor is not from an earlier wave", task=tid)
                    if not isinstance(dynamic.get("field"), str) or not dynamic.get("field"):
                        _issue(errors, "dynamic_predecessor_field", "dynamic predecessor field is missing", task=tid)
            for quote in field_gold.get("exact_quotes", []):
                sid, text = quote.get("source_id"), quote.get("quote")
                quoted_sources.add(sid)
                source = source_by_id.get(sid)
                if source is None or not isinstance(text, str) or text not in source.get("body", ""):
                    _issue(errors, "quote_not_verbatim", f"quote for {field!r} is not an exact source span", task=tid)
                if sid not in available:
                    _issue(errors, "quote_not_available", f"quote source {sid!r} unavailable at wave time", task=tid)
                if source and source.get("scope") == "private" and source.get("owner") != actor:
                    _issue(errors, "quote_private_scope", f"quote source {sid!r} is not visible to actor", task=tid)
                if source is not None and as_of is not None:
                    start, end = _day(source.get("effective_from")), _day(source.get("effective_to"))
                    if (start is not None and start > as_of) or (end is not None and as_of >= end):
                        _issue(errors, "quote_outside_validity", f"quote source {sid!r} is outside wave validity", task=tid)
        missing_quote_sources = quoted_sources - required
        if missing_quote_sources:
            _issue(errors, "quote_source_not_required", f"exact quotes use sources absent from required_source_ids: {sorted(missing_quote_sources)}", task=tid)
        if not entry.get("required_source_ids"):
            _issue(warnings, "no_required_source", "task has no required source; verify that this is a deliberate unknown case", task=tid, severity="warning")

    body_texts = [s.get("body", "") for s in sources]
    duplicate_bodies = len(body_texts) - len(set(body_texts))
    word_counts = sorted(len(re.findall(r"\S+", body)) for body in body_texts)
    private_without_value = [s["source_id"] for s in sources if s.get("scope") == "private" and re.search(r"emergency contact|private record", s.get("body", ""), re.I)]
    if private_without_value:
        _issue(warnings, "private_placeholder", f"private sources appear policy/placeholder-only: {private_without_value}", severity="warning")
    if duplicate_bodies:
        _issue(warnings, "duplicate_bodies", f"{duplicate_bodies} duplicate source bodies", severity="warning")
    if word_counts and word_counts[-1] < 80:
        _issue(warnings, "short_corpus", f"longest source has only {word_counts[-1]} words; long-form behavior is underrepresented", severity="warning")
    approval_fields = [f for t in gold_tasks.values() for f, v in t.get("fields", {}).items() if f == "approval_ticket"]
    approval_unknown = [v for t in gold_tasks.values() for f, v in t.get("fields", {}).items() if f == "approval_ticket" and v.get("must_be_unknown") is True and v.get("expected") is None]
    if approval_fields and len(approval_fields) == len(approval_unknown):
        _issue(warnings, "approval_ticket_always_unknown", f"all {len(approval_fields)} approval_ticket gold fields are unknown/null; this can permit an always-null shortcut", severity="warning")
    return {
        "episode_id": episode_id,
        "status": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
        "metrics": {"sources": len(sources), "waves": len(waves), "tasks": len(tasks), "distinct_actors": len(set(actors)), "duplicate_bodies": duplicate_bodies, "source_word_counts": word_counts, "private_sources_without_concrete_value": private_without_value},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    # v4 stores one episode per dev/final subdirectory; retain the v1-v3 flat layout.
    episodes = sorted((args.fixture / "dev").glob("*/episode.json")) + sorted((args.fixture / "final").glob("*/episode.json"))
    episodes += sorted((args.fixture / "dev").glob("episode-*.json")) + sorted((args.fixture / "final").glob("episode-*.json"))
    if not episodes:
        episodes = sorted(args.fixture.glob("**/episode-*.json"))
    reports = []
    for episode_path in episodes:
        gold_path = episode_path.with_name("gold.json")
        if not gold_path.exists():
            reports.append({"episode_id": episode_path.stem, "status": "fail", "errors": [{"code": "missing_gold", "message": str(gold_path)}], "warnings": [], "metrics": {}})
            continue
        schema_path = args.fixture / "schema.json"
        reports.append(audit_episode(_read(episode_path), _read(gold_path), _read(schema_path) if schema_path.exists() else {}))
    # Cross-episode semantic checks are deliberately summarized, never gold-dumped.
    designs = []
    sharing = {}
    length_words = {}
    distractor_counts = {}
    for episode_path in episodes:
        ep, gold = _read(episode_path), _read(episode_path.with_name("gold.json"))
        d = ep.get("design", {})
        designs.append({k: d.get(k) for k in ("length", "reuse", "update", "independent_benchmark")})
        req = {tid: set(v.get("required_source_ids", [])) for tid, v in gold.get("tasks", {}).items()}
        sharing.setdefault(d.get("reuse"), []).append({
            "required_source_union": len(set().union(*req.values())) if req else 0,
            "pairwise_reuse_edges": sum(bool(req[a] & req[b]) for a in req for b in req if a < b),
        })
        words = [len(re.findall(r"\S+", s.get("body", ""))) for s in ep.get("sources", [])]
        length_words.setdefault(d.get("length"), []).append({"min": min(words or [0]), "max": max(words or [0]), "mean": round(sum(words) / len(words), 1) if words else 0})
        required = set().union(*req.values()) if req else set()
        distractors = [s for s in ep.get("sources", []) if s.get("source_id") not in required]
        # A distractor must be an actual source body, not a label in metadata/body.
        distractor_counts.setdefault(d.get("reuse"), []).append({
            "unrequired_sources": len(distractors),
            "explicit_placeholder_mentions": sum(bool(re.search(r"\bdistractor\b|placeholder", s.get("body", ""), re.I)) for s in distractors),
        })
    summary = {
        "episode_count": len(episodes),
        "dev_count": sum("/dev/" in str(p) for p in episodes),
        "final_count": sum("/final/" in str(p) for p in episodes),
        "designs": designs,
        "sharing": sharing,
        "length_word_ranges": length_words,
        "distractors": distractor_counts,
        "independent_benchmark_claim": any(d.get("independent_benchmark") for d in designs),
        "semantic_notes": [
            "Gold remains offline-only; dynamic predecessor_field references were structurally checked per task.",
            "This is a controlled synthetic series, not an independent benchmark.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {"status": "pass" if reports and all(r["status"] == "pass" for r in reports) else "fail", "fixture": str(args.fixture), "fixture_sha256": hashlib.sha256("".join(json.dumps(r, sort_keys=True) for r in reports).encode()).hexdigest(), "episodes": reports, "summary": summary, "gold_sent_to_retriever": False}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "episodes": len(reports), "errors": sum(len(r["errors"]) for r in reports), "warnings": sum(len(r["warnings"]) for r in reports)}))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
