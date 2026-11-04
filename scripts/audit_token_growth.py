"""Read-only audit of the frozen token-growth final run.

This deliberately does not open the final question/gold file.  It checks the
run manifest, row pairing/denominators, and independently counts one saved
failure payload plus fixture characteristics regenerated from author_fixture.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

import tiktoken

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/phase2-token-growth-final-v1"
FIXTURE = ROOT / "fixtures/phase2-token-growth-v4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def p95(values):
    values = sorted(values)
    return values[math.ceil(.95 * len(values)) - 1]


def main() -> None:
    summary = json.loads((RUN / "summary.json").read_text())
    manifest = summary["manifest"]
    freeze = json.loads((FIXTURE / "FREEZE.json").read_text())
    hash_checks = {name: sha(FIXTURE / name) == digest
                   for name, digest in freeze["files"].items()}
    code_checks = {
        name: sha(ROOT / name) == digest
        for name, digest in manifest["code_sha256"].items()
    }
    rows = [json.loads(line) for line in (RUN / "rows.jsonl").read_text().splitlines()]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["seed"], row["scenario"], row["size"],
                row["length_multiplier"], row["qid"])].append(row)
    pairing = {
        "groups": len(groups),
        "all_eight_methods": all(len({r["method"] for r in g}) == 8
                                  and len(g) == 8 for g in groups.values()),
        "duplicate_rows": len(rows) != len({
            (r["seed"], r["scenario"], r["size"], r["length_multiplier"],
             r["qid"], r["method"]) for r in rows}),
    }
    denominators = {
        "all_rows_answerable": all(r["answerable_case"] for r in rows),
        "complete_not_over_denominator": all(
            r["complete_evidence"] <= r["answerable_case"] for r in rows
        ),
        "private_exposure_zero": sum(r["private_exposure"] for r in rows) == 0,
        "stale_exposure_zero": sum(r["stale_exposure"] for r in rows) == 0,
    }

    # Independent check of one persisted failure payload: token count, offsets,
    # and serialized-context hash are checked without reading the final gold.
    failure = json.loads((RUN / "failures.jsonl").read_text().splitlines()[0])
    enc = tiktoken.get_encoding("o200k_base")
    serialize = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"))
    matching = next(r for r in rows if all(r[k] == failure[k] for k in
                       ("seed", "scenario", "size", "length_multiplier", "qid", "method")))
    context = failure["context"]
    context_tokens = len(enc.encode(serialize(context), disallowed_special=()))
    payload_sha = hashlib.sha256(serialize(context).encode()).hexdigest()
    source_files = json.loads((FIXTURE / "FREEZE.json").read_text())["files"]
    author_path = FIXTURE / "author_fixture.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("growth_author_audit", author_path)
    author = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = author
    spec.loader.exec_module(author)

    # Corpus characteristics are regenerated independently from the frozen
    # generator, for every measured growth size and the long-document arm.
    characteristics = {}
    for scenario, sizes in (("unrelated", (100, 1000, 10000)),
                            ("mixed", (100, 1000, 10000))):
        for size in sizes:
            docs = author.generate(size, scenario, 20261103, 1)
            toks = [len(enc.encode(d["body"], disallowed_special=())) for d in docs]
            characteristics[f"{scenario}:{size}"] = {
                "documents": len(docs), "body_token_min": min(toks),
                "body_token_median": statistics.median(toks),
                "body_token_p95": p95(toks),
                "status_counts": dict(Counter(d["status"] for d in docs)),
                "scope_counts": dict(Counter(d["scope"] for d in docs)),
                "duplicate_body_count": len(docs) - len({d["body"] for d in docs}),
            }
    docs = author.generate(100, "long", 20261103, 16)
    characteristics["long:100:x16"] = {
        "documents": len(docs),
        "body_chars_min": min(len(d["body"]) for d in docs),
        "body_chars_median": statistics.median(len(d["body"]) for d in docs),
        "body_chars_p95": p95([len(d["body"]) for d in docs]),
    }

    receipt = {
        "schema": "token-growth-audit-v1",
        "run": str(RUN.relative_to(ROOT)),
        "final_gold_opened": False,
        "rows": len(rows), "summary_rows": summary["rows"],
        "fixture_hashes": hash_checks, "code_hashes": code_checks,
        "pairing": pairing, "denominators": denominators,
        "independent_saved_payload": {
            "row_key": {k: matching[k] for k in ("seed", "scenario", "size", "length_multiplier", "qid", "method")},
            "context_tokens_recount": context_tokens,
            "context_tokens_recorded": matching["context_tokens"],
            "payload_sha_recount": payload_sha,
            "payload_sha_recorded": matching["payload_sha256"],
            "offsets_valid": all(
                isinstance(s.get("start"), int) and isinstance(s.get("end"), int)
                and s["start"] <= s["end"] for rec in context["sources"]
                for s in rec.get("spans", [])
            ),
        },
        "characteristics": characteristics,
        "limitations": [
            "three seeds repeat the same frozen questions; they are not independent question samples",
            "retrieval evidence completeness is not model answer quality",
            "synthetic fixture is not a production Notion or 16-agent workload",
        ],
    }
    (RUN / "audit-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
