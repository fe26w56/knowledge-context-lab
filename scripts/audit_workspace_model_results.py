"""Export numeric, anonymous audits of private paired workspace model runs.

The input manifest is private and lists case, condition, run directory and
acquisition measurements. Source text, answers, paths and case names are never
included in the public result. This audit does not grade answer meaning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

from scripts.evaluate_workspace_pilot import _outside_repo


CONDITIONS = ("notion_fetch", "file_mirror")


def audit(manifest: Path, *, repo: Path | None = None) -> dict:
    repo = (repo or Path(__file__).resolve().parents[1]).resolve()
    manifest = _outside_repo(manifest, repo, "manifest")
    entries = json.loads(manifest.read_text())
    cases, pairs, rows = {}, {}, []
    for entry in entries:
        case, condition = entry["case"], entry["condition"]
        if condition not in CONDITIONS:
            raise ValueError("unknown comparison condition")
        if (case, condition) in pairs:
            raise ValueError("duplicate case/condition")
        case_number = cases.setdefault(case, len(cases) + 1)
        directory = _outside_repo(Path(entry["run"]), repo, "run")
        results = json.loads((directory / "results.json").read_text())
        if len(results) != 1 or results[0]["case"] != case:
            raise ValueError("manifest must identify one matching response per run")
        response = results[0]["response"]
        if response["status"] != "ok":
            raise ValueError("incomplete responses require a separate failure audit")
        request_hash = hashlib.sha256(json.dumps(response["request"], sort_keys=True,
                                                 ensure_ascii=False).encode()).hexdigest()
        if request_hash != response["request_sha256"]:
            raise ValueError("saved request hash mismatch")
        payload = response["payload"]
        if set(payload) != {"request", "sources"} or case in json.dumps(payload):
            raise ValueError("unexpected evaluator metadata in model payload")
        pairs[case, condition] = response["request"]
        sources = {s["source_id"]: s["capture"]["text"] for s in payload["sources"]}
        claims = response["output"]["claims"]
        exact = [bool(c["quote"]) and c["quote"] in sources.get(c["source_id"], "") for c in claims]
        acquisition = entry["acquisition"]
        if condition == "notion_fetch":
            if acquisition["exact_capture_equal"] is not True:
                raise ValueError("remote source drift must be reported separately")
            acquire_seconds = acquisition["fetch_ms"] / 1000
        else:
            if acquisition["payload_equal"] is not True:
                raise ValueError("local payload mismatch")
            acquire_seconds = acquisition["local_acquisition_seconds"]
        usage = response["usage"]
        rows.append({"case_number": case_number, "condition": condition,
                     "claims": len(claims), "exact_capture_quotes": sum(exact),
                     "all_quotes_exact": bool(exact) and all(exact),
                     "acquisition_seconds": acquire_seconds,
                     "api_latency_seconds": response["latency_seconds"],
                     "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                     "nominal_cost_nanodollars": response["nominal_cost_estimate_nanodollars"],
                     "conservative_cost_nanodollars": response["conservative_cost_nanodollars"]})
    complete = [case for case in cases if all((case, c) in pairs for c in CONDITIONS)]
    equal = sum(pairs[case, CONDITIONS[0]] == pairs[case, CONDITIONS[1]] for case in complete)
    aggregates = {}
    for condition in CONDITIONS:
        selected = [r for r in rows if r["condition"] == condition]
        if not selected:
            continue
        aggregates[condition] = {key: sum(r[key] for r in selected) for key in (
            "claims", "exact_capture_quotes", "all_quotes_exact", "acquisition_seconds",
            "api_latency_seconds", "input_tokens", "output_tokens", "nominal_cost_nanodollars",
            "conservative_cost_nanodollars")}
        aggregates[condition].update(cases=len(selected),
            acquisition_median_seconds=median(r["acquisition_seconds"] for r in selected),
            measured_component_sum_seconds=sum(r["acquisition_seconds"] + r["api_latency_seconds"] for r in selected))
    return {"format": "workspace-private-paired-audit-v1", "cases": len(cases),
            "complete_pairs": len(complete), "byte_equal_api_requests": equal,
            "rows": rows, "aggregates": aggregates,
            "scope": {"semantic_quality_scored": False, "invoice_measured": False,
                      "production_end_to_end_measured": False, "private_content_exported": False,
                      "cost_difference_is_database_effect": False},
            "timing_note": "Acquisition and generation are separately measured components; process startup and human work are excluded.",
            "cost_note": "Identical inputs can have different output lengths and provider cache treatment. Do not attribute that difference to storage."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"cases": result["cases"], "complete_pairs": result["complete_pairs"],
                      "byte_equal_api_requests": result["byte_equal_api_requests"]}))


if __name__ == "__main__":
    main()
