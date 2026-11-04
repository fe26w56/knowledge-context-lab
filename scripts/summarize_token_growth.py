"""Summarize token-growth evaluation runs without making new model calls.

The evaluator counts reference message-content tokens with o200k_base.  This
script intentionally reports question rows and unique qids separately: seeds
are repeated observations, not independent questions.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


def median(values):
    return statistics.median(values) if values else None


def load_run(path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    rows = [json.loads(line) for line in (path / "rows.jsonl").read_text().splitlines() if line.strip()]
    datasets_path = path / "datasets.json"
    datasets = json.loads(datasets_path.read_text()) if datasets_path.exists() else []
    return {"path": str(path), "manifest": manifest, "rows": rows, "datasets": datasets}


def group_rows(rows, keys):
    result = {}
    for row in rows:
        key = tuple(row.get(k) for k in keys)
        result.setdefault(key, []).append(row)
    return result


def row_metrics(rows):
    answerable = [r for r in rows if r["answerable_case"]]
    qids = sorted({r["qid"] for r in rows})
    answerable_qids = sorted({r["qid"] for r in answerable})
    complete_qids = sorted({r["qid"] for r in answerable if r["complete_evidence"]})
    all_complete_qids = []
    for qid in answerable_qids:
        observations = [r for r in answerable if r["qid"] == qid]
        if observations and all(r["complete_evidence"] for r in observations):
            all_complete_qids.append(qid)
    tokens = [r["input_reference_tokens"] for r in rows]
    return {
        "rows": len(rows),
        "unique_questions": len(qids),
        "seeds": len({r["seed"] for r in rows}),
        "answerable_rows": len(answerable),
        "answerable_unique_questions": len(answerable_qids),
        "complete_evidence_rows": sum(bool(r["complete_evidence"]) for r in answerable),
        "complete_evidence_rate_rows": (sum(bool(r["complete_evidence"]) for r in answerable) / len(answerable)) if answerable else None,
        "complete_evidence_unique_questions_any": len(complete_qids),
        "complete_evidence_unique_questions_all_observations": len(all_complete_qids),
        "input_token_median": median(tokens),
        "input_token_p95": percentile(tokens, .95),
        "private_exposure": sum(r["private_exposure"] for r in rows),
        "stale_exposure": sum(r["stale_exposure"] for r in rows),
        "overflow_rows": sum(r["budget_exceeded"] for r in rows),
    }


def point_rows(rows):
    return [r for r in rows if r["kind"] == "point"]


def summarize_arms(rows):
    keys = ["scenario", "size", "length_multiplier", "method", "kind"]
    return [dict(zip(keys, key), **row_metrics(group))
            for key, group in sorted(group_rows(rows, keys).items(), key=str)]


def paired_growth(rows, method):
    """Pair same seed+qid+method across mixed corpus sizes; no significance test."""
    selected = [r for r in rows if r["scenario"] == "mixed" and r["kind"] == "point" and r["method"] == method]
    by_pair = group_rows(selected, ["seed", "qid"])
    out = []
    for (seed, qid), observations in sorted(by_pair.items()):
        by_size = {r["size"]: r for r in observations}
        if 100 not in by_size:
            continue
        for size in (1000, 10000):
            if size in by_size:
                base = by_size[100]["input_reference_tokens"]
                current = by_size[size]["input_reference_tokens"]
                out.append({"seed": seed, "qid": qid, "size": size, "delta_tokens": current - base,
                            "ratio": (current / base) if base else None})
    result = []
    for size in (1000, 10000):
        pairs = [x for x in out if x["size"] == size]
        by_qid = group_rows(pairs, ["qid"])
        result.append({"from_size": 100, "to_size": size, "pairs": len(pairs),
                       "unique_questions": len({x["qid"] for x in pairs}),
                       "seeds": len({x["seed"] for x in pairs}),
                       "median_delta_tokens": median([x["delta_tokens"] for x in pairs]),
                       "p95_delta_tokens": percentile([x["delta_tokens"] for x in pairs], .95),
                       "median_ratio": median([x["ratio"] for x in pairs]),
                       "p95_ratio": percentile([x["ratio"] for x in pairs], .95),
                       "max_ratio": max((x["ratio"] for x in pairs), default=None),
                       "unique_questions_all_observed_ratios_le_1_25": sum(all(x["ratio"] <= 1.25 for x in group) for group in by_qid.values()),
                       "all_seed_qid_pairs_ratio_le_1_25": sum(x["ratio"] <= 1.25 for x in pairs)})
    return result


def long_growth(run, methods):
    rows = run["rows"]
    datasets = {}
    for d in run["datasets"]:
        datasets.setdefault((d["scenario"], d["size"], d["length_multiplier"]), []).append(d)
    result = []
    for method in methods:
        for mult in (1, 4, 16):
            selected = [r for r in rows if r["scenario"] == "long" and r["size"] == 100 and r["length_multiplier"] == mult
                        and r["method"] == method and r["kind"] == "point"]
            if not selected:
                continue
            ds = datasets.get(("long", 100, mult), [])
            body_chars = [d["body_chars"] for d in ds]
            result.append({"method": method, "length_multiplier": mult,
                           "body_chars_per_seed": body_chars,
                           "body_chars_median": median(body_chars),
                           "body_chars_min": min(body_chars) if body_chars else None,
                           "body_chars_max": max(body_chars) if body_chars else None,
                           "rows": len(selected),
                           "unique_questions": len({r["qid"] for r in selected}),
                           "input_token_median": median([r["input_reference_tokens"] for r in selected]),
                           "input_token_p95": percentile([r["input_reference_tokens"] for r in selected], .95),
                           "complete_evidence_rows": sum(bool(r["complete_evidence"]) for r in selected),
                           "answerable_rows": sum(bool(r["answerable_case"]) for r in selected)})
    return result


def paired_ablation(rows, candidate):
    """Compare methods on identical seed/scenario/size/multiplier/qid rows."""
    keys = ["seed", "scenario", "size", "length_multiplier", "qid", "kind"]
    groups = group_rows(rows, keys)
    result = []
    for key, group in sorted(groups.items(), key=str):
        by_method = {r["method"]: r for r in group}
        base = by_method.get(candidate)
        if not base:
            continue
        for method, row in sorted(by_method.items()):
            if method == candidate:
                continue
            result.append({"seed": key[0], "scenario": key[1], "size": key[2],
                           "length_multiplier": key[3], "qid": key[4], "kind": key[5],
                           "candidate": candidate, "baseline": method,
                           "token_delta_candidate_minus_baseline": base["input_reference_tokens"] - row["input_reference_tokens"],
                           "candidate_complete_evidence": bool(base["complete_evidence"]),
                           "baseline_complete_evidence": bool(row["complete_evidence"]),
                           "complete_evidence_delta": int(bool(base["complete_evidence"])) - int(bool(row["complete_evidence"]))})
    grouped = group_rows(result, ["scenario", "size", "length_multiplier", "kind", "baseline"])
    return [{"scenario": key[0], "size": key[1], "length_multiplier": key[2], "kind": key[3],
             "baseline": key[4], "candidate": candidate, "paired_rows": len(group),
             "unique_questions": len({r["qid"] for r in group}),
             "median_token_delta_candidate_minus_baseline": median([r["token_delta_candidate_minus_baseline"] for r in group]),
             "candidate_complete_evidence_rows": sum(r["candidate_complete_evidence"] for r in group),
             "baseline_complete_evidence_rows": sum(r["baseline_complete_evidence"] for r in group),
             "complete_evidence_delta_rows": sum(r["complete_evidence_delta"] for r in group)}
            for key, group in sorted(grouped.items(), key=str)]


def make_plot(summary, output):
    import matplotlib.pyplot as plt
    arms = summary["arms"]
    methods = [summary["candidate"]] + ["project", "all"]
    methods = [m for i, m in enumerate(methods) if m and m not in methods[:i]]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for method in methods:
        values = [next((a["input_token_median"] for a in arms if a["method"] == method and a["scenario"] == "mixed" and a["size"] == size and a["kind"] == "point"), None) for size in (100, 1000, 10000)]
        if any(v is not None for v in values):
            axes[0].plot([100, 1000, 10000], values, marker="o", label=method)
    axes[0].set_xscale("log"); axes[0].set_xlabel("mixed corpus records (log)"); axes[0].set_ylabel("median input tokens")
    axes[0].set_yscale("log"); axes[0].set_title("Mixed growth: point questions"); axes[0].legend(fontsize=8)
    long = [x for x in summary["long_fixed_100"] if x["method"] in methods]
    for method in methods:
        values = [next((x["input_token_median"] for x in long if x["method"] == method and x["length_multiplier"] == m), None) for m in (1, 4, 16)]
        chars = [next((x["body_chars_median"] for x in long if x["method"] == method and x["length_multiplier"] == m), None) for m in (1, 4, 16)]
        if any(v is not None for v in values):
            axes[1].plot(chars, values, marker="o", label=method)
    axes[1].set_xlabel("actual body characters (fixed N=100)"); axes[1].set_ylabel("median input tokens")
    axes[1].set_title("Long documents: point questions"); axes[1].legend(fontsize=8)
    for method in methods:
        values = [next((a["complete_evidence_rate_rows"] for a in arms if a["method"] == method and a["scenario"] == "mixed" and a["size"] == size and a["kind"] == "point"), None) for size in (100, 1000, 10000)]
        if any(v is not None for v in values):
            axes[2].plot([100, 1000, 10000], values, marker="o", label=method)
    axes[2].set_xscale("log"); axes[2].set_ylim(0, 1.05); axes[2].set_xlabel("mixed corpus records (log)"); axes[2].set_ylabel("complete evidence rate")
    axes[2].set_title("Mixed growth: retention"); axes[2].legend(fontsize=8)
    fig.suptitle("Synthetic diagnostic; o200k_base reference message-content tokens")
    fig.savefig(output, dpi=160)
    fig.savefig(output.with_suffix(".svg"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="final or other evaluation run")
    parser.add_argument("--development", type=Path, required=True, help="development evaluation run")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", required=True, help="candidate method name, e.g. sections_4000")
    parser.add_argument("--no-plot", action="store_true", help="write tables without the optional matplotlib dependency")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output must be new: {args.output}")
    final = load_run(args.run)
    development = load_run(args.development)
    args.output.mkdir(parents=True)
    final_arms = summarize_arms(final["rows"])
    development_arms = summarize_arms(development["rows"])
    summary = {
        "schema": "token-growth-summary-v1",
        "unit": "reference message-content tokens:o200k_base",
        "counting": "evaluator input_reference_tokens; provider framing excluded",
        "diagnostic_boundary": "synthetic authored diagnostic; no new model calls; seeds are repeated observations, not independent questions",
        "candidate": args.candidate,
        "runs": {"run": final["path"], "development": development["path"]},
        "arms": final_arms,
        "development_arms": development_arms,
        "paired_mixed_growth": {
            "development": paired_growth(development["rows"], args.candidate),
            "run": paired_growth(final["rows"], args.candidate),
        },
        "long_fixed_100": long_growth(final, [args.candidate, "project", "all"]),
        "development_long_fixed_100": long_growth(development, [args.candidate, "project", "all"]),
        "exhaustive": [a for a in final_arms if a["kind"] == "exhaustive"],
        "development_exhaustive": [a for a in development_arms if a["kind"] == "exhaustive"],
        "paired_ablation": {
            "run": paired_ablation(final["rows"], args.candidate),
            "development": paired_ablation(development["rows"], args.candidate),
        },
        "notes": [
            "complete_evidence rows and unique-question counts are reported separately",
            "unique_questions counts qids, while rows include repeated seeds",
            "the project arm is shown as a filtering baseline; filtering/token shortening is not attributed to a database",
            "exhaustive rows are reported separately and no capped success claim is made",
            "no statistical significance is inferred from correlated seeds",
        ],
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Token growth summary", "", "Synthetic authored diagnostic; reference message-content tokens counted with `o200k_base`. Seeds are repeated observations, not independent questions.", "", f"Candidate: `{args.candidate}`", "", "## Mixed point questions", "", "| Scenario | Size | Method | Rows | Unique q | Median tokens | P95 tokens | Complete evidence rows / answerable rows |", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for a in final_arms:
        if a["scenario"] == "mixed" and a["kind"] == "point":
            lines.append(f"| mixed | {a['size']} | {a['method']} | {a['rows']} | {a['unique_questions']} | {a['input_token_median']} | {a['input_token_p95']} | {a['complete_evidence_rows']} / {a['answerable_rows']} |")
    lines += ["", "## Interpretation boundaries", "", "- Paired growth is within the same seed and qid; it is descriptive, not a significance test.", "- `project` is a filtering baseline. Any token reduction from filtering or JSON shape is not credited to a database.", "- Exhaustive cases are listed separately in `summary.json`; their result must not be presented as a capped-success claim.", "- Long-document results use actual generated body characters at fixed N=100."]
    (args.output / "comparison.md").write_text("\n".join(lines) + "\n")
    if not args.no_plot:
        make_plot(summary, args.output / "token-growth.png")
    print(json.dumps({"output": str(args.output), "arms": len(summary["arms"]), "plot": None if args.no_plot else "token-growth.png"}))


if __name__ == "__main__":
    main()
