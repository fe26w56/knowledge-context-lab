"""Frozen synthetic retrieval evaluation; final labels never tune a searcher."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import statistics
import tempfile
import time

from .evaluate import score_payload, validate_inputs
from .metrics import UnitCounter, percentile
from .retrieval import BudgetTooSmallError
from .retrieval_v2 import ADAPTERS, Config, RetrievalV2, STAGES, digest


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_hash():
    root = Path(__file__).parent
    return digest({name: file_hash(root/name) for name in ("retrieval_v2.py", "retrieval.py", "metrics.py")})


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k,v in row.items()} for row in rows)


def summarize(rows, categories=False):
    groups = {}
    for r in rows:
        key = (r["stage"], r["method"], r["budget"], r["cache_state"], r["category"] if categories else "all")
        groups.setdefault(key, []).append(r)
    out=[]
    for (stage, method, budget, cache, category), members in sorted(groups.items()):
        eligible = [r for r in members if r["evidence_eligible"]]
        first = [r for r in members if r["repeat"] == 0]
        first_eligible = [r for r in first if r["evidence_eligible"]]
        out.append(dict(stage=stage, stage_name=STAGES[stage], method=method, budget=budget, cache_state=cache, category=category,
                        trials=len(members), unique_queries=len(first), eligible_queries=len(first_eligible),
                        complete_queries=sum(r["complete_evidence"] for r in first_eligible),
                        condition_missing_queries=sum(r["condition_missing"] for r in first),
                        obsolete_only_queries=sum(r["obsolete_only"] for r in first),
                        forbidden_quote_hits=sum(r["forbidden_quote_hits"] for r in first),
                        first_repeat_units_total=sum(r["returned_units"] for r in first),
                        median_units=statistics.median(r["returned_units"] for r in members),
                        retrieval_ms_median=statistics.median(r["retrieval_ms"] for r in members),
                        retrieval_ms_p95=percentile([r["retrieval_ms"] for r in members], .95),
                        total_ms_median=statistics.median(r["total_ms"] for r in members),
                        total_ms_p95=percentile([r["total_ms"] for r in members], .95),
                        search_rounds_mean=statistics.mean(r["search_rounds"] for r in members),
                        extra_candidates_total=sum(r["additional_candidate_documents"] for r in first),
                        errors=sum(bool(r["retrieval_error"]) for r in members),
                        unanswerable_unscored=sum(not r["evidence_eligible"] for r in first)))
    return out


def run(corpus_path, query_path, output, *, stages, budgets=(1000,2000,4000), repeats=2, seed=20261030, config_overrides=None, selected_config=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = output/"source"/"context_lab"
    source.mkdir(parents=True)
    for name in ("__init__.py", "retrieval_v2.py", "retrieval.py", "evaluate.py", "metrics.py", "phase2_eval.py"):
        shutil.copyfile(Path(__file__).parent/name, source/name)
    initial_implementation = implementation_hash()
    corpus, queries = json.loads(Path(corpus_path).read_text()), json.loads(Path(query_path).read_text())
    validate_inputs(corpus, queries)
    counter = UnitCounter("o200k_base")
    counter("warm 日本語")
    configurations = {s: Config(stage=s, **(config_overrides or {})) for s in stages}
    if selected_config:
        configurations[selected_config["stage"]] = Config(**selected_config)
    rows, payloads, builds = [], [], []
    with tempfile.TemporaryDirectory(prefix="context-lab-eval-") as temp:
        adapters, engines = {}, {}
        for name, cls in ADAPTERS.items():
            start = time.perf_counter()
            adapters[name] = cls.create(Path(temp)/name, corpus["documents"])
            import_ms = (time.perf_counter()-start)*1000
            for stage, cfg in configurations.items():
                start = time.perf_counter()
                engines[name,stage] = RetrievalV2(adapters[name], cfg)
                builds.append(dict(backend=name, stage=stage, import_ms=import_ms, index_ms=(time.perf_counter()-start)*1000,
                                   source_read_calls=1, logical_source_bytes=sum(len(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()) for d in corpus["documents"])))
        jobs=[(q,stage,method,budget,cache,repeat) for q in queries["queries"] for stage in stages for method in ("A","B","C") for budget in budgets for cache in ("cold_index","warm_index") for repeat in range(repeats)]
        random.Random(seed).shuffle(jobs)
        for q,stage,method,budget,cache,repeat in jobs:
            backend = "sqlite" if method=="C" else "file"
            setup_ms=0
            if cache=="cold_index":
                start=time.perf_counter()
                # Reopen the persisted adapter and rebuild the shared index.
                adapter = ADAPTERS[backend](Path(temp)/backend)
                try:
                    engine=RetrievalV2(adapter, configurations[stage])
                finally:
                    adapter.close()
                setup_ms=(time.perf_counter()-start)*1000
            else:
                engine=engines[backend,stage]
            # Keep token-count cache state constant to isolate index reuse.
            counter.__call__.cache_clear()
            start=time.perf_counter(); error=None
            try:
                result=engine.retrieve(dict(q["request"]), budget, counter, full=method=="A")
            except BudgetTooSmallError as exc:
                error=type(exc).__name__
                result={"payload":json.dumps({"items":[],"error":error}),"search_rounds":0,"additional_candidate_documents":0}
            ms=(time.perf_counter()-start)*1000
            payload=result["payload"]
            expected=q.get("expected_quotes",[])
            found, forbidden=score_payload(payload,expected,q.get("forbidden_quotes",[]))
            conditions,_=score_payload(payload,q.get("condition_quotes",[]),[])
            obsolete,_=score_payload(payload,q.get("obsolete_quotes",[]),[])
            eligible=bool(q.get("answerable",True) and expected)
            row=dict(query_id=q["id"],split=q.get("split"),category=q["category"],stage=stage,method=method,backend=backend,
                     budget=budget,cache_state=cache,repeat=repeat,evidence_eligible=eligible,
                     complete_evidence=bool(eligible and all(found)),required_quotes=len(expected),found_quotes=sum(found),
                     missing_quote_indices=[i for i,v in enumerate(found) if not v],condition_missing=bool(conditions and not all(conditions)),
                     obsolete_only=bool(any(obsolete) and eligible and not any(found)),obsolete_present=any(obsolete),
                     forbidden_quote_hits=sum(forbidden),returned_units=counter(payload),budget_exceeded=counter(payload)>budget,
                     retrieval_ms=ms,setup_ms=setup_ms,total_ms=ms+setup_ms,search_rounds=result["search_rounds"],
                     additional_candidate_documents=result["additional_candidate_documents"],
                     context_api_attempts=1,context_api_successes=int(error is None),retrieval_retries=0,
                     query_backend_read_calls=result.get("backend_calls_during_query",0),
                     candidate_documents=result.get("candidate_documents",[]),selected_sections=result.get("selected_sections",[]),
                     stop_reason=result.get("stop_reason"),retrieval_error=error,
                     answer_correctness=None,human_correction_minutes=None)
            rows.append(row)
            # Repeated payloads are deterministic; save one per query/config.
            if repeat==0 and cache=="warm_index":
                payloads.append({k:row[k] for k in ("query_id","stage","method","budget")} | {"payload":payload})
        for adapter in adapters.values():
            adapter.close()
    rows.sort(key=lambda r:(r["stage"],r["method"],r["budget"],r["cache_state"],r["query_id"],r["repeat"]))
    metadata=dict(created_at=datetime.now(timezone.utc).isoformat(),privacy="public_synthetic",python=platform.python_version(),
                  platform=platform.platform(),sqlite=sqlite3.sqlite_version,tiktoken=importlib.metadata.version("tiktoken"),
                  corpus_path=str(corpus_path),query_path=str(query_path),corpus_sha256=file_hash(corpus_path),queries_sha256=file_hash(query_path),
                  implementation_sha256=initial_implementation,evaluator_sha256=file_hash(__file__),seed=seed,repeats=repeats,
                  configurations={str(k):asdict(v) for k,v in configurations.items()},budgets=list(budgets),builds=builds,
                  cache_definition="cold_index: reopen adapter and rebuild index; warm_index: reuse in-process index; token-count cache cleared for BOTH; OS disk cache not flushed; tokenizer encoding preloaded",
                  warm_priming_excluded=False,backend_query_io="none; identical shared in-process retrieval; initial full corpus read counted in builds",llm_measured=False,d1_measured=False,
                  answer_quality_measured=False,provider_billing_measured=False,human_correction_cost_measured=False,
                  quality_metric="literal_source_evidence_coverage; unanswerable cases not credited")
    write_json(output/"metadata.json",metadata)
    write_json(output/"results.json",rows)
    write_csv(output/"results.csv",rows)
    summaries=summarize(rows)
    write_json(output/"summary.json",summaries)
    write_json(output/"categories.json",summarize(rows,True))
    (output/"payloads.jsonl").write_text("".join(json.dumps(p,ensure_ascii=False)+"\n" for p in payloads))
    # Byte equality of B/C responses is the backend-quality isolation check.
    pairs={}
    for p in payloads:
        if p["method"] in {"B","C"}:
            pairs.setdefault((p["query_id"],p["stage"],p["budget"]),{})[p["method"]]=p["payload"]
    parity={"pairs":len(pairs),"identical_pairs":sum(v.get("B")==v.get("C") for v in pairs.values())}
    write_json(output/"backend-parity.json",parity)
    if parity["pairs"] != parity["identical_pairs"]:
        raise AssertionError("Backend payload mismatch")
    if initial_implementation != implementation_hash():
        raise AssertionError("Implementation changed during measurement")
    return summaries


def select(dev_run):
    path=Path(dev_run)
    summaries=json.loads((path/"summary.json").read_text())
    candidates=[s for s in summaries if s["method"]=="B" and s["cache_state"]=="warm_index" and s["forbidden_quote_hits"]==0 and s["errors"]==0]
    # Predeclared lexicographic rule; no final questions or gold are read here.
    selected=min(candidates,key=lambda s:(-s["complete_queries"],s["condition_missing_queries"],s["obsolete_only_queries"],s["first_repeat_units_total"],s["stage"],s["budget"]))
    result=dict(created_at=datetime.now(timezone.utc).isoformat(),development_run=str(path),
                criterion="max complete evidence, then min condition omissions, obsolete-only, total tokens, stage, budget; zero leaks and execution errors required",
                stage=selected["stage"],budget=selected["budget"],dev_result=selected,implementation_sha256=implementation_hash(),
                dev_metadata_sha256=file_hash(path/"metadata.json"),final_results_seen=False)
    result["config"] = json.loads((path/"metadata.json").read_text())["configurations"][str(selected["stage"])]
    target=path/"selection.json"
    if target.exists():
        raise FileExistsError(target)
    write_json(target,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",choices=("dev","final","regression"),required=True)
    p.add_argument("--corpus",type=Path,default=Path("fixtures/phase2/corpus.json"))
    p.add_argument("--queries",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--selection",type=Path)
    p.add_argument("--repeats",type=int,default=2)
    p.add_argument("--stages",default=",".join(str(s) for s in STAGES))
    p.add_argument("--config",default="{}",help="Development-only JSON overrides")
    args=p.parse_args()
    if args.repeats<1:
        p.error("repeats must be positive")
    if args.mode=="dev":
        run(args.corpus,args.queries or Path("fixtures/phase2/dev.json"),args.output,stages=[int(s) for s in args.stages.split(",")],repeats=args.repeats,config_overrides=json.loads(args.config))
        print(json.dumps(select(args.output),ensure_ascii=False))
    else:
        if not args.selection:
            p.error("Freeze a development selection before final/regression evaluation")
        selected=json.loads(args.selection.read_text())
        if selected["implementation_sha256"]!=implementation_hash():
            p.error("Implementation changed since selection; rerun development and freeze again")
        result=run(args.corpus,args.queries or Path("fixtures/phase2/final.json"),args.output,stages=sorted({0,selected["stage"]}),repeats=args.repeats,selected_config=selected.get("config"))
        write_json(args.output/"selection-used.json",selected)
        print(json.dumps({"output":str(args.output),"summary_groups":len(result),"selected_stage":selected["stage"],"selected_budget":selected["budget"]}))


if __name__=="__main__":
    main()
