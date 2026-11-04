"""Explicit, budgeted workflow experiments and offline replay of their grades."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time

from .budget import ExperimentBudget
from .workflow import ARMS, VERSION, WorkflowEngine, digest
from .workflow_api import BudgetedClient, _atomic_json


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_fixture(path):
    path = Path(path)
    freeze = load(path / "FREEZE.json")
    expected = freeze["files"]
    for name, checksum in expected.items():
        target = path / name
        if not target.resolve().is_relative_to(path.resolve()) or sha(target) != checksum:
            raise ValueError("fixture freeze mismatch")
    if digest(expected) == freeze.get("manifest_sha256"):
        pass
    elif hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest() != freeze.get("manifest_sha256"):
        raise ValueError("fixture manifest hash mismatch")
    return freeze


def implementation_hashes():
    base = Path(__file__).parent
    result = {p.name: sha(p) for p in sorted(base.glob("*.py"))}
    result.update({"profiles/" + p.name: sha(p) for p in sorted((base / "profiles").glob("*.json"))})
    return result


def usage_summary(attempts):
    totals = Counter()
    lower = upper = conservative = 0
    missing, point_missing = 0, 0
    by_kind = {}
    for attempt in attempts:
        usage = attempt.get("usage")
        if usage is None:
            missing += 1
        else:
            for name in ("input_tokens", "output_tokens"):
                totals[name] += usage[name]
            details = usage.get("input_tokens_details", {})
            totals["cached_tokens"] += details.get("cached_tokens", 0)
            totals["cache_write_tokens_reported"] += details.get("cache_write_tokens", 0)
            totals["reasoning_tokens_included_in_output"] += usage.get("output_tokens_details", {}).get("reasoning_tokens", 0)
        bounds = attempt.get("nominal_cost_bounds")
        if bounds:
            lower += bounds["lower_nanodollars"]; upper += bounds["upper_nanodollars"]
            point_missing += bounds["point_nanodollars"] is None
        conservative += attempt.get("conservative_cost_nanodollars") or 0
        row = by_kind.setdefault(attempt["kind"], {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                  "cost_lower_nanodollars": 0, "cost_upper_nanodollars": 0})
        row["calls"] += 1
        for name in ("input_tokens", "output_tokens"):
            row[name] += (usage or {}).get(name, 0)
        if bounds:
            row["cost_lower_nanodollars"] += bounds["lower_nanodollars"]
            row["cost_upper_nanodollars"] += bounds["upper_nanodollars"]
    return {"calls": len(attempts), "totals": dict(totals), "usage_missing_calls": missing,
            "cost_lower_nanodollars": lower if not missing else None,
            "cost_upper_nanodollars": upper if not missing else None,
            "point_cost_missing_calls": point_missing,
            "conservative_usage_nanodollars": conservative, "by_kind": by_kind,
            "invoice_measured": False, "credit_balance_measured": False}


def run(fixture, split, arms, output, ledger_path, *, cases=None, workers=4, seed=74013, selection=None):
    from .workflow_grade import grade
    fixture, output = Path(fixture), Path(output)
    frozen = verify_fixture(fixture)
    hashes = implementation_hashes()
    if split == "final":
        if selection is None:
            raise ValueError("final execution requires a frozen selection file")
        chosen = load(selection)
        if hashes != chosen["implementation_sha256"] or list(arms) != chosen["arms"] or sha(fixture / "FREEZE.json") != chosen["fixture_freeze_sha256"]:
            raise ValueError("final selection differs from the implementation, arms or fixture")
    directories = sorted(p.parent for p in (fixture / split).glob("*/episode.json"))
    if cases:
        if set(cases) - {p.name for p in directories}:
            raise ValueError("unknown case names")
        directories = [p for p in directories if p.name in cases]
    if not directories or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        raise ValueError("invalid experiment matrix")
    ledger = ExperimentBudget(ledger_path, cap_usd="10")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "source"; snapshot.mkdir()
    for name in hashes:
        target = snapshot / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(__file__).parent / name).read_bytes())
    _atomic_json(output / "metadata.json", {"created_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": VERSION, "split": split, "arms": list(arms), "cases": [p.name for p in directories],
        "workers": workers, "order_seed": seed, "fixture_freeze_sha256": sha(fixture / "FREEZE.json"),
        "fixture_frozen_at": frozen["frozen_at_utc"], "implementation_sha256": hashes,
        "selection_sha256": sha(selection) if selection else None,
        "controlled_synthetic": True, "independent_benchmark": False})
    _atomic_json(output / "ledger-before.json", ledger.report())
    rows = []; rng = random.Random(seed)
    try:
        for directory in directories:
            episode = load(directory / "episode.json")
            order = list(arms); rng.shuffle(order)
            for arm in order:
                case_dir = output / directory.name / arm
                case_dir.mkdir(parents=True)
                before = time.perf_counter()
                client = BudgetedClient(ledger, case_dir / "api")
                engine = WorkflowEngine(arm, client, case_dir / "workflow")
                result = engine.run(episode["sources"], episode["waves"], workers=workers)
                total_seconds = time.perf_counter()-before
                # Gold is first loaded here, after all case requests have completed.
                quality = grade(episode, load(directory / "gold.json"), result)
                _atomic_json(case_dir / "quality.json", quality)
                attempts = [load(p) for p in sorted((case_dir / "api").glob("attempt-*.json")) if not p.name.endswith(".pending.json")]
                row = {"case": directory.name, "arm": arm, "order": order.index(arm),
                    "design": episode["design"], "elapsed_seconds": total_seconds,
                    "workflow_elapsed_seconds": result["elapsed_seconds"],
                    "quality": quality, "usage": usage_summary(attempts),
                    "fallback_tasks": sum(r["fallback"] for r in result["results"].values()),
                    "index_builds": result["index_builds"], "retrieval_hits": result["retrieval_hits"],
                    "record_builds": result["record_builds"], "record_hits": result["record_hits"]}
                rows.append(row)
                _atomic_json(output / "progress.json", {"status": "running", "rows": rows})
                print(json.dumps({"case": directory.name, "arm": arm, "calls": row["usage"]["calls"],
                    "seconds": round(total_seconds, 2), "quality": {k:v for k,v in quality.items() if k != "tasks"}}), flush=True)
        _atomic_json(output / "summary.json", {"status": "complete", "rows": rows})
    except BaseException as exc:
        _atomic_json(output / "interrupted.json", {"status": "interrupted", "error_type": type(exc).__name__,
            "completed_case_arms": len(rows), "automatic_resume": False})
        raise
    finally:
        _atomic_json(output / "ledger-after.json", ledger.report())
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", required=True); p.add_argument("--split", choices=("dev", "final"), required=True)
    p.add_argument("--arms", nargs="+", choices=ARMS, required=True)
    p.add_argument("--cases", nargs="+"); p.add_argument("--output", required=True)
    p.add_argument("--ledger", required=True); p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=74013); p.add_argument("--selection")
    p.add_argument("--live", action="store_true", help="Explicitly dispatch paid API requests using OPENAI_API_KEY")
    a = p.parse_args()
    if not a.live:
        p.error("--live is required for paid inference; use offline grade() for saved responses")
    run(a.fixture, a.split, a.arms, a.output, a.ledger, cases=a.cases, workers=a.workers, seed=a.seed, selection=a.selection)


if __name__ == "__main__":
    main()
