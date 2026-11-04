#!/usr/bin/env python3
"""Freeze a small, stratified LongMemEval selection with evaluator-only gold."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GROUP_RULE = "question_id ends with _abs -> abstention; otherwise question_type"
SALT = "20261103:"
FORBIDDEN_PUBLIC_KEYS = {"answer", "has_answer", "answer_session_ids", "question_id", "original_session_id"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def choose(records: list[dict], dev_per_group: int = 1, final_per_group: int = 2) -> tuple[list[dict], list[dict], dict]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        group = "abstention" if record["question_id"].endswith("_abs") else record["question_type"]
        groups.setdefault(group, []).append(record)
    chosen: dict[str, list[dict]] = {}
    for group, values in groups.items():
        ordered = sorted(values, key=lambda r: hashlib.sha256((SALT + r["question_id"]).encode()).hexdigest())
        chosen[group] = ordered[: dev_per_group + final_per_group]
    dev = [values[0] for values in chosen.values()]
    final = [value for values in chosen.values() for value in values[dev_per_group:dev_per_group + final_per_group]]
    return dev, final, {"groups": {k: len(v) for k, v in groups.items()}, "selected": {k: [x["question_id"] for x in v] for k, v in chosen.items()}}


def public_and_gold(record: dict, case_key: str) -> tuple[dict, dict]:
    ids = record["haystack_session_ids"]
    dates = record["haystack_dates"]
    sessions = record["haystack_sessions"]
    if not (len(ids) == len(dates) == len(sessions)):
        raise ValueError("haystack ids/dates/sessions length mismatch")
    neutral = {original: f"s{i:04d}" for i, original in enumerate(ids)}
    sources = []
    for i, (original, date_value, turns) in enumerate(zip(ids, dates, sessions)):
        clean_turns = []
        for turn in turns:
            if not isinstance(turn, dict) or "role" not in turn or "content" not in turn:
                raise ValueError("turn must preserve only role/content")
            clean_turns.append({"role": turn["role"], "content": turn["content"]})
        sources.append({"session_id": f"s{i:04d}", "date": date_value, "turns": clean_turns})
    answer_ids = record.get("answer_session_ids", [])
    if not all(a in neutral for a in answer_ids):
        raise ValueError("answer session is absent from haystack")
    public = {"evaluator_case_key": case_key, "request": record["question"], "as_of": record["question_date"], "sources": sources}
    answer_indices = {}
    for original in answer_ids:
        si = ids.index(original)
        answer_indices[neutral[original]] = [i for i, _ in enumerate(sessions[si])]
    gold = {"evaluator_case_key": case_key, "question_id": record["question_id"], "question_type": record["question_type"],
            "answer": record["answer"], "answer_session_ids": answer_ids,
            "neutral_evidence_ids": [neutral[x] for x in answer_ids], "answer_turn_indices": answer_indices}
    return public, gold


def assert_public_clean(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_PUBLIC_KEYS:
                raise AssertionError(f"forbidden public key: {key}")
            assert_public_clean(child)
    elif isinstance(value, list):
        for child in value:
            assert_public_clean(child)


def prepare(source: Path, destination: Path) -> dict:
    raw_bytes = source.read_bytes()
    records = json.loads(raw_bytes)
    if not isinstance(records, list) or len(records) != 500:
        raise ValueError(f"expected official cleaned S list of 500, got {type(records).__name__}/{len(records) if hasattr(records, '__len__') else '?'}")
    dev_records, final_records, groups = choose(records)
    if len(dev_records) != 7 or len(final_records) != 14:
        raise ValueError("selection rule did not produce 7 dev / 14 final")
    destination.mkdir(parents=True, exist_ok=False)
    prepared_dir = destination / "prepared-v1"
    prepared_dir.mkdir()
    outputs = {}
    for split, selected in (("dev", dev_records), ("final", final_records)):
        public, gold = [], []
        for i, record in enumerate(selected):
            case_key = f"lm-{split}-{i:02d}"
            pub, g = public_and_gold(record, case_key)
            assert_public_clean(pub)
            public.append(pub); gold.append(g)
        (prepared_dir / f"{split}-public-inputs.json").write_text(json.dumps(public, ensure_ascii=False, indent=2))
        (prepared_dir / f"{split}-gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2))
        outputs[split] = {"count": len(public), "public_sha256": sha256_bytes((prepared_dir / f"{split}-public-inputs.json").read_bytes()),
                          "gold_sha256": sha256_bytes((prepared_dir / f"{split}-gold.json").read_bytes())}
    selection = {"source_sha256": sha256_bytes(raw_bytes), "source_bytes": len(raw_bytes), "salt": SALT,
                 "rule": GROUP_RULE, "dev_per_group": 1, "final_per_group": 2, "groups": groups, "outputs": outputs,
                 "license": "MIT (LongMemEval repository/dataset; verify terms before redistribution)",
                 "source_links": ["https://github.com/xiaowu0162/LongMemEval", "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"]}
    (destination / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2))
    return selection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    print(json.dumps(prepare(args.source, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
