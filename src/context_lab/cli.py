"""Build a local corpus store and retrieve source-attributed context."""
import argparse
import json
from pathlib import Path
import sys
import time
from importlib.resources import files

from .metrics import UnitCounter
from .retrieval_v2 import ADAPTERS, Config, RetrievalV2
from .retrieval_release import ReleaseConfig, ReleaseRetrieval
from .retrieval_completion import CompletionConfig, CompletionRetrieval


def demo(output):
    """Create synthetic example inputs in a new directory; no external access."""
    output.mkdir(parents=True, exist_ok=False)
    current = "Orionの検索キャッシュは10分で期限切れにする。決定の確定時は保存先の版を照合する。"
    old = "以前は60分保持していた。この方針は2026年5月10日に失効した。"
    documents = []
    for key in ("policy-original", "policy-copy"):
        documents.append(dict(id=key, title="Orion キャッシュ方針", scope="shared", owner=None,
            source_url="https://example.invalid/"+key, body=current+"\n"+old,
            sections=[dict(id=key+"-now", heading="現行のキャッシュ", text=current, kind="decision", adoption_status="adopted", valid_from="2026-05-10", valid_to=None),
                      dict(id=key+"-old", heading="旧方針", text=old, kind="decision", adoption_status="superseded", valid_from="2026-05-01", valid_to="2026-05-10")]))
    corpus = dict(schema_version=1, corpus_id="public-demo", privacy="public_synthetic", documents=documents)
    (output/"corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2)+"\n")
    request = dict(text="Orionの現在のキャッシュ期限と確認条件は？", actor="demo-agent", scope="shared", mode="current", as_of="2026-05-20")
    (output/"request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2)+"\n")
    adapter = ADAPTERS["file"].create(output/"index", documents)
    adapter.close()
    print(json.dumps({"directory": str(output), "backend": "file", "index": str(output/"index"), "request": str(output/"request.json")}, ensure_ascii=False))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    example=commands.add_parser("demo",help="Create a new synthetic example without network access")
    example.add_argument("--output",type=Path,required=True)
    build=commands.add_parser("build",help="Create a new store; never overwrite")
    build.add_argument("--corpus",type=Path,required=True)
    query=commands.add_parser("query",help="Caller identity must be trusted by the embedding application")
    query.add_argument("--request",type=Path,required=True,help="JSON with text, actor, mode, as_of and optional scope only")
    profile_args=query.add_mutually_exclusive_group()
    profile_args.add_argument("--selection",type=Path,help="Frozen selection.json")
    profile_args.add_argument("--profile",choices=("release","completion","control"),default="release",
                              help="Experimental configuration; see findings for measured quality and failures")
    context_args=query.add_mutually_exclusive_group()
    context_args.add_argument("--budget",type=int)
    context_args.add_argument("--full",action="store_true",
                              help="Return candidate bodies without a token ceiling (A); may include labelled history/proposals")
    query.add_argument("--unit",choices=("o200k_base","chars"),default="o200k_base")
    query.add_argument("--diagnostics",action="store_true")
    for sub in (build,query):
        sub.add_argument("--backend",choices=tuple(ADAPTERS),required=True)
        sub.add_argument("--index",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command == "demo":
        demo(args.output)
        return
    if args.command == "query" and args.budget is not None and args.budget <= 0:
        parser.error("budget must be positive")
    if args.command=="build":
        corpus=json.loads(args.corpus.read_text())
        adapter=ADAPTERS[args.backend].create(args.index,corpus["documents"])
        adapter.close()
        print(json.dumps({"created":str(args.index),"backend":args.backend,"documents":len(corpus["documents"])}))
        return
    selection=json.loads(args.selection.read_text() if args.selection else files("context_lab").joinpath(f"profiles/{args.profile}.json").read_text())
    engine_name=selection.get("engine", "phase2")
    engines = {"phase2": (Config, RetrievalV2), "release": (ReleaseConfig, ReleaseRetrieval),
               "completion": (CompletionConfig, CompletionRetrieval)}
    if engine_name not in engines:
        parser.error("Unknown retrieval engine")
    config_type, engine_type = engines[engine_name]
    cfg=config_type(**selection["config"])
    request=json.loads(args.request.read_text())
    counter=UnitCounter(args.unit)
    adapter=ADAPTERS[args.backend](args.index)
    try:
        start=time.perf_counter()
        engine=engine_type(adapter,cfg)
        setup_ms=(time.perf_counter()-start)*1000
        start=time.perf_counter()
        result=engine.retrieve(request,args.budget if args.budget is not None else selection["budget"],counter,full=args.full)
        query_ms=(time.perf_counter()-start)*1000
    finally:
        adapter.close()
    print(result["payload"])
    if args.diagnostics:
        print(json.dumps(dict(index_build_ms=setup_ms,retrieval_ms=query_ms,units=counter(result["payload"]),unit=counter.unit,
                              search_rounds=result["search_rounds"],query_expansion_terms=result["query_expansion_terms"])),file=sys.stderr)


if __name__=="__main__":
    main()
