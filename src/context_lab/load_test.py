"""Deterministic synthetic load measurements for the selected Phase 2 setup."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import shutil
import json
import platform
import random
import sqlite3
import statistics
import tempfile
import time
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .evaluate import score_payload, validate_inputs
from .metrics import UnitCounter, percentile
from .phase2_eval import file_hash, implementation_hash
from .retrieval_v2 import ADAPTERS, Config, RetrievalV2

SEED = 20261030


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def generate_corpus(base, size, seed=SEED):
    if size < len(base["documents"]):
        raise ValueError("size is smaller than source corpus")
    rng = random.Random(seed + size)
    docs = deepcopy(base["documents"])
    labels = {k: 0 for k in ("exact_duplicate", "near_duplicate", "condition_variant", "old_version", "contradiction", "unrelated")}
    while len(docs) < size:
        source = deepcopy(base["documents"][rng.randrange(len(base["documents"]))])
        n = len(docs)
        kind = rng.choices(tuple(labels), weights=(18, 27, 18, 15, 12, 10))[0]
        labels[kind] += 1
        source["id"] = f"load_{n:05d}"
        source["source_url"] = f"https://example.invalid/load/{source['id']}"
        for section in source["sections"]:
            section["id"] = f"{source['id']}_{section['id']}"
        if kind == "near_duplicate":
            source["title"] += f" 類似調査 {n}"
            source["body"] += f"\n類似資料番号: {n}。適用条件は元資料と異なる。"
        elif kind == "condition_variant":
            old = source["sections"][0]["text"]
            new = old + f" 条件変更版では対象を{n % 7 + 1}件に限定する。"
            source["sections"][0]["text"] = new
            source["body"] = source["body"].replace(old, new, 1)
            source["title"] += f" 条件変更 {n}"
        elif kind == "old_version":
            for sec in source["sections"]:
                sec["text"] += " この旧版は2026年4月12日に失効した。"
                sec["adoption_status"] = "superseded"
                sec["valid_from"], sec["valid_to"] = "2026-04-01", "2026-04-12"
            source["title"] += f" 旧版 {n}"
            source["body"] = "\n\n".join(f"## {sec['heading']} (失効日2026-04-12)\n{sec['text']}" for sec in source["sections"])
        elif kind == "contradiction":
            sec = source["sections"][0]; original = sec["text"]
            new = "相反案: 次の原案の実行には反対し、実施を保留する。原案「" + original + "」この反対案は提案中で、採用されていない。"
            sec["text"] = new; sec["adoption_status"] = "proposed"; sec["valid_from"] = "2026-04-20"; sec["valid_to"] = None
            source["body"] = source["body"].replace(original, new, 1); source["title"] += f" 相反案 {n}"
        elif kind == "unrelated":
            source["title"] = f"無関係な負荷資料 {n}"
            text = "検索条件とは異なる架空の話題を記録する。"
            source["body"] = f"# 無関係な負荷資料 {n}\n{text}"
            source["sections"] = [{"id": f"{source['id']}_s1", "heading": "無関係な記録", "text": text, "kind": "report", "adoption_status": "na", "valid_from": "2026-04-01", "valid_to": None, "verified_at": "2026-04-20"}]
        docs.append(source)
    result = dict(base, corpus_id=f"{base['corpus_id']}-load-{size}", fixture_kind="phase2_load_generated", documents=docs)
    body_hashes = [hashlib.sha256(d["body"].encode()).hexdigest() for d in docs]
    duplicate_count = sum(n - 1 for n in Counter(body_hashes).values())
    params = {"seed": seed, "size": size, "weights": {"exact_duplicate": 18, "near_duplicate": 27, "condition_variant": 18, "old_version": 15, "contradiction": 12, "unrelated": 10}, "generated_labels": labels, "measured_exact_duplicate_bodyhash_rate": duplicate_count / max(1, size - len(base["documents"])), "measured_bodyhash_duplicate_count": duplicate_count}
    validate_inputs(result, {"queries": []})
    return result, params


def _selected_queries(queries):
    selected = [q for q in queries["queries"] if q.get("answerable", True) and q.get("expected_quotes")][:6]
    for category in ("multi_source", "long_table"):
        q = next((x for x in queries["queries"] if x.get("category") == category and x.get("expected_quotes")), None)
        if q and q not in selected: selected.append(q)
    return selected


def _quote_map(corpus, query):
    return [{"quote": quote, "source_ids": [d["id"] for d in corpus["documents"] if quote in d.get("body", "")]} for quote in query.get("expected_quotes", [])]


def _quote_recall(payload, quote_map):
    items = json.loads(payload).get("items", [])
    literal = [x["quote"] for x in quote_map if any(x["quote"] in i.get("text", "") for i in items)]
    original = [x["quote"] for x in quote_map if any(x["quote"] in i.get("text", "") and i.get("document_id") in x["source_ids"] for i in items)]
    n = len(quote_map)
    return (sum(q in literal for q in (x["quote"] for x in quote_map)) / n if n else None, sum(q in original for q in (x["quote"] for x in quote_map)) / n if n else None)


def _write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["empty"]); writer.writeheader(); writer.writerows(rows)


def storage_bytes(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else path.stat().st_size


def run_load(corpus, queries, selection, output, sizes=(100, 1000, 10000), repeats=3, seed=SEED, input_hashes=None):
    if repeats < 1 or not sizes:
        raise ValueError("Positive repeats and sizes required")
    initial_hash = implementation_hash()
    if selection.get("implementation_sha256", initial_hash) != initial_hash:
        raise ValueError("Selection implementation differs from measured implementation")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source" / "context_lab"
    source.mkdir(parents=True)
    source_hashes = {}
    for name in ("__init__.py", "retrieval.py", "retrieval_v2.py", "metrics.py", "evaluate.py", "phase2_eval.py", "load_test.py"):
        origin = Path(__file__).parent / name
        shutil.copyfile(origin, source / name)
        source_hashes[name] = file_hash(origin)
    counter = UnitCounter("o200k_base")
    counter("warm tokenizer 日本語")
    config = Config(**selection.get("config", {"stage": int(selection["stage"])}))
    budget = int(selection["budget"])
    selected = _selected_queries(queries)
    trials, startup, generated_meta, amortization = [], [], [], []
    parity_pairs = 0
    with tempfile.TemporaryDirectory(prefix="context-load-") as tmp:
        tmp = Path(tmp)
        for size in sizes:
            generated, params = generate_corpus(corpus, int(size), seed)
            before_hash = canonical_hash(generated)
            generated_meta.append({"size": size, "params": params, "corpus_sha256_before_update": before_hash})
            backend_order = list(ADAPTERS)
            random.Random(seed + size + 1).shuffle(backend_order)
            backends = {}
            for backend in backend_order:
                path = tmp / f"{size}-{backend}"
                started = time.perf_counter()
                adapter = ADAPTERS[backend].create(path, generated["documents"])
                import_ms = (time.perf_counter()-started)*1000
                started = time.perf_counter()
                engine = RetrievalV2(adapter, config)
                index_ms = (time.perf_counter()-started)*1000
                backends[backend] = dict(path=path, adapter=adapter, engine=engine)
                startup.append(dict(size=size, backend=backend, event="initial_import_index", import_ms=import_ms,
                                    index_ms=index_ms, storage_bytes=storage_bytes(path), source_read_calls=adapter.read_calls,
                                    logical_source_bytes=adapter.logical_bytes_read))
            update = deepcopy(generated["documents"][-1])
            old = update["sections"][0]["text"]
            update["sections"][0]["text"] = old + " 差分更新負荷テスト。"
            update["body"] = update["body"].replace(old, update["sections"][0]["text"], 1)
            update["recorded_at"] = "2026-04-21"
            for backend in backend_order:
                b = backends[backend]
                started = time.perf_counter()
                b["adapter"].update([update])
                update_ms = (time.perf_counter()-started)*1000
                readback = {d["id"]: d for d in b["adapter"].read()}
                assert readback[update["id"]] == update
                started = time.perf_counter()
                b["engine"] = RetrievalV2(b["adapter"], config)
                reindex_ms = (time.perf_counter()-started)*1000
                assert b["engine"].docs[update["id"]] == update
                startup.append(dict(size=size, backend=backend, event="delta_update_reindex", update_ms=update_ms,
                                    reindex_ms=reindex_ms, updated_document=update["id"], updated_document_sha256=canonical_hash(update),
                                    readback_verified=True, reindex_visible=True, storage_bytes=storage_bytes(b["path"])))
            for cache_state in ("cold", "warm"):
                for repeat in range(repeats):
                    engines, cold_adapters, cold_setup = {}, [], {}
                    for backend in backend_order:
                        if cache_state == "cold":
                            started = time.perf_counter()
                            a = ADAPTERS[backend](backends[backend]["path"])
                            engines[backend] = RetrievalV2(a, config)
                            setup_ms = (time.perf_counter()-started)*1000
                            cold_adapters.append(a)
                            cold_setup[backend] = setup_ms
                            startup.append(dict(size=size, backend=backend, event="cold_index", repeat=repeat,
                                                setup_ms=setup_ms, source_read_calls=a.read_calls, logical_source_bytes=a.logical_bytes_read))
                        else:
                            engines[backend] = backends[backend]["engine"]
                            cold_setup[backend] = 0.0
                    qorder = list(selected)
                    random.Random(seed + size + repeat).shuffle(qorder)
                    for query in qorder:
                        quote_map = _quote_map(corpus, query)
                        payloads = {}
                        jobs = [("A", "file"), ("B", "file"), ("C", "sqlite")]
                        random.Random(seed + size + repeat + sum(map(ord, query["id"]))).shuffle(jobs)
                        for method, backend in jobs:
                            counter.__call__.cache_clear()
                            started = time.perf_counter()
                            result = engines[backend].retrieve(dict(query["request"]), budget, counter, full=method == "A")
                            retrieve_ms = (time.perf_counter()-started)*1000
                            literal, original = _quote_recall(result["payload"], quote_map)
                            payloads[method] = result["payload"]
                            trials.append(dict(size=size, method=method, backend=backend, cache_state=cache_state, repeat=repeat,
                                               query_id=query["id"], budget=budget, returned_units=counter(result["payload"]),
                                               literal_quote_recall=literal, original_source_quote_recall=original,
                                               setup_ms=cold_setup[backend], retrieve_ms=retrieve_ms,
                                               total_ms=cold_setup[backend]+retrieve_ms,
                                               candidate_documents=result["candidate_documents"], search_rounds=result["search_rounds"],
                                               backend_query_reads=result["backend_calls_during_query"], source_quote_map=quote_map,
                                               payload_sha256=hashlib.sha256(result["payload"].encode()).hexdigest()))
                        if payloads["B"] != payloads["C"]:
                            raise AssertionError("B/C load payload mismatch")
                        parity_pairs += 1
                    for a in cold_adapters:
                        a.close()
                    del engines
            for backend, b in backends.items():
                b["adapter"].close()
                initial = next(x for x in startup if x["size"]==size and x["backend"]==backend and x["event"]=="initial_import_index")
                update_event = next(x for x in startup if x["size"]==size and x["backend"]==backend and x["event"]=="delta_update_reindex")
                query_ms = statistics.median(r["retrieve_ms"] for r in trials if r["size"]==size and r["backend"]==backend and r["method"]!="A" and r["cache_state"]=="warm")
                for uses in (1,16,1600):
                    amortization.append(dict(size=size,backend=backend,queries_per_update=uses,
                                             first_ingest_ms_per_query=(initial["import_ms"]+initial["index_ms"])/uses+query_ms,
                                             steady_update_ms_per_query=(update_event["update_ms"]+update_event["reindex_ms"])/uses+query_ms))
            generated_meta[-1]["corpus_sha256_after_update"] = canonical_hash(dict(generated, documents=[update if d["id"]==update["id"] else d for d in generated["documents"]]))
            del backends
    aggregates = []
    for key in sorted({(r["size"],r["method"],r["cache_state"]) for r in trials}):
        rows = [r for r in trials if (r["size"],r["method"],r["cache_state"])==key]
        aggregates.append(dict(size=key[0],method=key[1],cache_state=key[2],trials=len(rows),
                               median_ms=statistics.median(r["total_ms"] for r in rows),p95_ms=percentile([r["total_ms"] for r in rows],.95),
                               retrieval_ms_median=statistics.median(r["retrieve_ms"] for r in rows),
                               retrieval_ms_p95=percentile([r["retrieve_ms"] for r in rows],.95),
                               median_units=statistics.median(r["returned_units"] for r in rows),
                               literal_quote_recall=statistics.mean(r["literal_quote_recall"] for r in rows),
                               original_source_quote_recall=statistics.mean(r["original_source_quote_recall"] for r in rows)))
    metadata=dict(created_at=datetime.now(timezone.utc).isoformat(),privacy="public_synthetic",sizes=list(sizes),repeats=repeats,seed=seed,
                  config=selection.get("config",{"stage":selection["stage"]}),budget=budget,selected_query_ids=[q["id"] for q in selected],
                  generation=generated_meta,input_canonical_hashes=dict(corpus=canonical_hash(corpus),queries=canonical_hash(queries),selection=canonical_hash(selection)),
                  input_file_hashes=input_hashes or {},implementation_sha256=initial_hash,source_sha256=source_hashes,
                  python=platform.python_version(),platform=platform.platform(),sqlite=sqlite3.sqlite_version,tiktoken=importlib.metadata.version("tiktoken"),
                  unit="reference_tokens:o200k_base",backend_parity_pairs=parity_pairs,
                  cache_definition="cold: three independent adapter opens and index rebuilds per backend, each serving a query sweep; setup_ms reused as single-query cold-start estimate, not additive across sweep; warm: reuse index; token-count cache cleared for every method/trial; OS cache not flushed; encoding preloaded",
                  human_correction_cost_measured=False,provider_billing_measured=False,llm_measured=False,d1_measured=False,
                  amortization_note="1/16/1600-query scenarios are local milliseconds; steady update includes full common reindex, not provider money")
    for name, value in (("metadata.json",metadata),("aggregates.json",aggregates),("startup-events.json",startup),("amortization.json",amortization)):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    (output/"trials.jsonl").write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in trials))
    _write_csv(output/"trials.csv",trials)
    if initial_hash != implementation_hash():
        raise AssertionError("Implementation changed during load run")
    return dict(trials=len(trials),queries=len(selected),backend_parity_pairs=parity_pairs)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--corpus", type=Path, required=True); parser.add_argument("--queries", type=Path, required=True); parser.add_argument("--selection", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--sizes", default="100,1000,10000"); parser.add_argument("--repeats", type=int, default=3); args = parser.parse_args()
    corpus, queries, selection = json.loads(args.corpus.read_text()), json.loads(args.queries.read_text()), json.loads(args.selection.read_text()); validate_inputs(corpus, queries); print(json.dumps(run_load(corpus, queries, selection, args.output, tuple(int(x) for x in args.sizes.split(",")), args.repeats, input_hashes={"corpus": file_hash(args.corpus), "queries": file_hash(args.queries), "selection": file_hash(args.selection)}), ensure_ascii=False))


if __name__ == "__main__": main()
