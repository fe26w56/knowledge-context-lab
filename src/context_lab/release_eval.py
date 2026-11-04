"""Source-aware synthetic evaluation for the release candidate; no model calls."""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import random
import re
import shutil
import sqlite3
import statistics
import tempfile
import time

from .metrics import UnitCounter, percentile
from .retrieval_v2 import ADAPTERS, digest, validate_documents
from .retrieval_release import ReleaseConfig, ReleaseRetrieval, document_signature

FIXTURE = Path("fixtures/phase2-release-v6")
SOURCE_NAMES = ("__init__.py", "metrics.py", "retrieval.py", "retrieval_v2.py", "retrieval_release.py", "release_eval.py")
VARIANTS = {
    "control": asdict(ReleaseConfig(deduplicate_documents=False)),
    "exact": asdict(ReleaseConfig()),
    "diversity_half": asdict(ReleaseConfig(candidate_diversity=.5)),
    "diversity_full": asdict(ReleaseConfig(candidate_diversity=1.0)),
    "exact_six": asdict(ReleaseConfig(candidate_limit=6)),
    "exact_twelve": asdict(ReleaseConfig(candidate_limit=12)),
    "exact_bm25": asdict(ReleaseConfig(ranking="bm25")),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(names=SOURCE_NAMES):
    return {name: sha(Path(__file__).parent / name) for name in names}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def generate(corpus, size, seed):
    """Perturbations and lineage are for the grader; only documents enter stores."""
    if size < len(corpus["documents"]):
        raise ValueError("Requested size smaller than base corpus")
    rng = random.Random(seed)
    documents = deepcopy(corpus["documents"])
    lineage = {d["id"]: (d["id"], "base") for d in documents}
    kinds = ("exact", "near", "condition", "old", "contradiction", "unrelated")
    counts = Counter()
    while len(documents) < size:
        original = rng.choice(corpus["documents"])
        doc = deepcopy(original)
        index = len(documents)
        key = "g_" + hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()[:16]
        kind = rng.choices(kinds, (35, 25, 15, 10, 10, 5))[0]
        counts[kind] += 1
        doc["id"] = key
        doc["source_url"] = "https://example.invalid/generated/" + key
        for n, section in enumerate(doc["sections"]):
            section["id"] = f"{key}_{n}"
        if kind in {"near", "condition"}:
            old = doc["sections"][0]["text"]
            if kind == "condition":
                changed = re.sub(r"\d+", lambda m: str(int(m.group()) + 3), old, count=1)
                changed += f" この別条件は第{index % 19 + 1}地区だけに適用する。"
            else:
                changed = old + f" この類似記録は第{index % 13 + 1}班のみ対象とし、承認者の再確認が必要。"
            doc["body"] = doc["body"].replace(old, changed, 1)
            # Overlapping source sections (e.g. a paragraph and its full body)
            # must reflect the same text edit, not leave stale non-source spans.
            for section in doc["sections"]:
                if old in section["text"]:
                    section["text"] = section["text"].replace(old, changed, 1)
            doc["title"] += f" 条件違い{index % 19 + 1}"
        elif kind == "old":
            for section in doc["sections"]:
                section.update(adoption_status="superseded", valid_from="2026-04-01", valid_to="2026-05-01")
                section["text"] += " この記録は2026年5月1日以後には適用しない。"
            doc["body"] = "\n\n".join(s["heading"] + "\n" + s["text"] for s in doc["sections"])
            doc["title"] += " 失効記録"
        elif kind == "contradiction":
            section = doc["sections"][0]
            old = section["text"]
            section.update(text="未採用の反対案: 原文「" + old + "」は実施しないと提案している。", kind="decision", adoption_status="proposed", valid_from="2026-05-15", valid_to=None)
            doc["body"] = "\n\n".join(s["heading"] + "\n" + s["text"] for s in doc["sections"])
            doc["title"] += " 未採用の反対案"
        elif kind == "unrelated":
            text = f"架空の雲の観察を番号{index}として記録した。業務規定とは無関係。"
            doc.update(title="雲の観察記録", body=text,
                       sections=[dict(id=key+"_0", heading="観察", text=text, kind="report", adoption_status="na", valid_from=None, valid_to=None)])
        documents.append(doc)
        lineage[key] = (original["id"], kind)
    rng.shuffle(documents)
    validate_documents(documents)
    signatures = Counter(document_signature(d) for d in documents)
    return documents, lineage, dict(size=size, seed=seed, generated_counts=dict(counts),
        generation_weights=dict(zip(kinds, (35, 25, 15, 10, 10, 5))),
        exact_duplicate_fraction=(size-len(signatures))/size, corpus_hash=digest(documents))


def requirements(query, original_documents, lineage):
    """Only the evaluator sees this map. Exact copies may satisfy their source."""
    result = {}
    for quote in query.get("expected_quotes", []):
        accepted = query.get("evidence_sources", {}).get(quote)
        if accepted is None:
            accepted = query.get("accepted_source_ids")
        if accepted is None:
            accepted = [d["id"] for d in original_documents if quote in d["body"]]
        result[quote] = {key for key, (origin, kind) in lineage.items() if origin in accepted and kind in {"base", "exact"}}
    return result


def score(payload, query, evidence, documents):
    value = json.loads(payload)
    items = value["items"]
    literal, grounded = [], []
    for quote, ids in evidence.items():
        literal.append(any(quote in item["text"] for item in items))
        grounded.append(any(item["document_id"] in ids and quote in item["text"] for item in items))
    actor = query["request"]["actor"]
    scope = query["request"].get("scope")
    violations = sum((documents[i["document_id"]]["scope"] == "private" and documents[i["document_id"]].get("owner") != actor)
                     or (scope is not None and documents[i["document_id"]]["scope"] != scope) for i in items)
    eligible = bool(query.get("answerable", True) and evidence)
    # Non-adoption is a state constraint even if an importer uses a content
    # kind other than decision. Full-document replay has no per-item state;
    # this check therefore applies only to the bounded section envelopes.
    state_violations = sum(query["request"].get("mode") == "current" and
        item.get("adoption_status") in {"draft", "proposed", "superseded"} for item in items)
    return dict(eligible=eligible, complete=bool(eligible and all(grounded)), literal_complete=bool(eligible and all(literal)),
        missing_evidence=[n for n, found in enumerate(grounded) if not found], source_quotes=sum(grounded), required_quotes=len(evidence),
        missing_conditions=sum(not any(quote in i["text"] for i in items) for quote in query.get("condition_quotes", [])),
        forbidden_hits=sum(quote in payload for quote in query.get("forbidden_quotes", [])), scope_violations=violations,
        state_violations=state_violations)


def aggregate(rows):
    groups = {}
    for row in rows:
        key = (row["variant"], row["method"], row["budget"], row["size"], row["seed"])
        groups.setdefault(key, []).append(row)
    result = []
    for key, group in sorted(groups.items()):
        first = [r for r in group if r["repeat"] == 0]
        result.append(dict(zip(("variant", "method", "budget", "size", "seed"), key)) | dict(
            unique_questions=len(first), eligible=sum(r["eligible"] for r in first), complete=sum(r["complete"] for r in first),
            literal_complete=sum(r["literal_complete"] for r in first), missing_conditions=sum(r["missing_conditions"] for r in first),
            forbidden_hits=sum(r["forbidden_hits"] for r in first), scope_violations=sum(r["scope_violations"] for r in first),
            state_violations=sum(r.get("state_violations", 0) for r in first),
            units=sum(r["units"] for r in first), median_ms=statistics.median(r["query_ms"] for r in group),
            p95_ms=percentile([r["query_ms"] for r in group], .95), trials=len(group)))
    return result


def run(corpus_path, queries_path, output, variants, datasets, repeats=2, budgets=(1000, 2000, 4000),
        *, engine_class=ReleaseRetrieval, config_class=ReleaseConfig, source_names=SOURCE_NAMES):
    if repeats < 1:
        raise ValueError("Positive repeats required")
    output.mkdir(parents=True, exist_ok=False)
    initial_hashes = source_hashes(source_names)
    source = output / "source/context_lab"
    source.mkdir(parents=True)
    for name in source_names:
        shutil.copyfile(Path(__file__).parent/name, source/name)
    corpus = json.loads(corpus_path.read_text())
    queries = json.loads(queries_path.read_text())["queries"]
    counter = UnitCounter("o200k_base")
    counter("Encoding warmup")
    rows, payloads, builds, generated = [], [], [], []
    parity_pairs = 0
    with tempfile.TemporaryDirectory(prefix="release-eval-") as tmp:
        for dataset, (size, seed) in enumerate(datasets):
            documents, lineage, info = generate(corpus, size, seed)
            generated.append(info)
            docs = {d["id"]: d for d in documents}
            evidence = {q["id"]: requirements(q, corpus["documents"], lineage) for q in queries}
            adapters = {}
            for backend in random.Random(seed).sample(list(ADAPTERS), len(ADAPTERS)):
                start = time.perf_counter()
                adapters[backend] = ADAPTERS[backend].create(Path(tmp)/f"{dataset}-{backend}", documents)
                builds.append(dict(dataset=dataset, size=size, seed=seed, backend=backend, event="import", ms=(time.perf_counter()-start)*1000))
            for name in random.Random(seed+1).sample(list(variants), len(variants)):
                cfg = config_class(**variants[name])
                engines = {}
                for backend in adapters:
                    start = time.perf_counter()
                    engines[backend] = engine_class(adapters[backend], cfg)
                    builds.append(dict(dataset=dataset, size=size, seed=seed, backend=backend, variant=name, event="index", ms=(time.perf_counter()-start)*1000,
                        documents_read=engines[backend].documents_read, documents_indexed=engines[backend].documents_indexed))
                jobs = [(q, budget, repeat) for q in queries for budget in budgets for repeat in range(repeats)]
                random.Random(seed+2).shuffle(jobs)
                for query, budget, repeat in jobs:
                    outputs = {}
                    for method in random.Random(seed+repeat+sum(map(ord, query["id"]))).sample(["A", "B", "C"], 3):
                        backend = "sqlite" if method == "C" else "file"
                        counter.__call__.cache_clear()
                        start = time.perf_counter()
                        value = engines[backend].retrieve(dict(query["request"]), budget, counter, full=method == "A")
                        ms = (time.perf_counter()-start)*1000
                        outputs[method] = value
                        row = dict(variant=name, method=method, budget=budget, size=size, seed=seed, repeat=repeat,
                            query_id=query["id"], category=query["category"], units=counter(value["payload"]), query_ms=ms,
                            candidates=value["candidate_documents"], search_rounds=value["search_rounds"], query_backend_reads=value["backend_calls_during_query"],
                            payload_sha256=hashlib.sha256(value["payload"].encode()).hexdigest(),
                            **score(value["payload"], query, evidence[query["id"]], docs))
                        rows.append(row)
                        if method != "A":
                            assert row["units"] <= budget
                        if repeat == 0:
                            payloads.append({k: row[k] for k in ("variant", "method", "budget", "size", "seed", "query_id", "payload_sha256")} | {"payload": value["payload"]})
                    assert outputs["A"]["candidate_documents"] == outputs["B"]["candidate_documents"] == outputs["C"]["candidate_documents"]
                    assert outputs["B"]["payload"] == outputs["C"]["payload"]
                    parity_pairs += 1
                del engines
            for adapter in adapters.values():
                adapter.close()
    summaries = aggregate(rows)
    write(output/"summary.json", summaries)
    write(output/"results.json", rows)
    with (output/"results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in rows)
    write(output/"builds.json", builds)
    (output/"payloads.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False)+"\n" for p in payloads))
    metadata = dict(created_at=datetime.now(timezone.utc).isoformat(), privacy="public_synthetic", python=platform.python_version(),
        platform=platform.platform(), sqlite=sqlite3.sqlite_version, tiktoken=importlib.metadata.version("tiktoken"),
        corpus_sha256=sha(corpus_path), queries_sha256=sha(queries_path), source_sha256=initial_hashes,
        fixture_freeze_sha256=sha(corpus_path.parent/"FREEZE.json") if (corpus_path.parent/"FREEZE.json").exists() else None,
        variants=variants, datasets=generated, repeats=repeats, budgets=list(budgets),
        backend_payload_and_candidate_parity_pairs=parity_pairs,
        timing_definition="warm in-process index, clear token-count cache per method/trial, encoding warmed; index separately measured; OS caches not flushed",
        quality_definition="source-aware literal evidence, equivalent exact-copy IDs accepted; unanswerable questions unscored",
        independent_benchmark=False, llm_measured=False, provider_cost_measured=False, d1_measured=False, human_correction_measured=False)
    write(output/"metadata.json", metadata)
    assert initial_hashes == source_hashes(source_names), "Source changed during measurement"
    return summaries, metadata


def select(output, summaries, metadata):
    choices = []
    for variant in metadata["variants"]:
        for budget in metadata["budgets"]:
            groups = [r for r in summaries if r["variant"] == variant and r["budget"] == budget and r["method"] == "B"]
            if any(r["scope_violations"] or r["forbidden_hits"] or r.get("state_violations", 0) for r in groups):
                continue
            choices.append(dict(variant=variant, budget=budget, complete=sum(r["complete"] for r in groups),
                eligible=sum(r["eligible"] for r in groups), missing_conditions=sum(r["missing_conditions"] for r in groups),
                units=sum(r["units"] for r in groups)))
    order = list(metadata["variants"])
    chosen = min(choices, key=lambda c: (-c["complete"], c["missing_conditions"], c["units"], order.index(c["variant"]), c["budget"]))
    selection = dict(chosen, engine="release", config=metadata["variants"][chosen["variant"]],
                     source_sha256=metadata["source_sha256"], frozen_at=datetime.now(timezone.utc).isoformat(),
                     final_results_seen=False, development_results_sha256=sha(output/"results.json"))
    write(output/"selection.json", selection)
    write(output/"selection-comparison.json", choices)
    return selection


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("dev", "final", "regression"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--corpus", type=Path, default=FIXTURE/"corpus.json")
    p.add_argument("--queries", type=Path)
    p.add_argument("--selection", type=Path)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--datasets", help="Comma-separated size:seed pairs, base size inferred for base")
    args = p.parse_args()
    base = len(json.loads(args.corpus.read_text())["documents"])
    variants = VARIANTS
    if args.mode != "dev":
        if not args.selection:
            p.error("Frozen development selection is required")
        selection = json.loads(args.selection.read_text())
        if selection["source_sha256"] != source_hashes():
            p.error("Source changed after selection; rerun development first")
        variants = {"control": VARIANTS["control"], "selected": selection["config"]}
    default = [(base, 8100), (1000, 8101), (1000, 8102)] if args.mode == "dev" else [(base, 9100)]
    datasets = [tuple(map(int, pair.split(":"))) for pair in args.datasets.split(",")] if args.datasets else default
    queries = args.queries or FIXTURE / ("dev.json" if args.mode == "dev" else "final.json")
    summaries, metadata = run(args.corpus, queries, args.output, variants, datasets, args.repeats)
    if args.mode == "dev":
        print(json.dumps(select(args.output, summaries, metadata)))
    else:
        write(args.output/"selection-used.json", selection)
        print(json.dumps({"groups": len(summaries), "parity_pairs": metadata["backend_payload_and_candidate_parity_pairs"]}))


if __name__ == "__main__":
    main()
