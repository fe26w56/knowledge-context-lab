"""Compare a regression-informed heuristic BEFORE opening final questions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from context_lab.phase2_eval import run, select, write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),final_questions_used=False,
              reason="q22 remained missing after candidate limits 3/6/12 and cosine/BM25; q30 passed",
              comparison="add only definition-intent query expansion to compact+prefilter+split",
              gate="q22 and q30 required; then maximize dev evidence and minimize missing conditions, obsolete-only and tokens")
    write_json(args.output/"plan.json",plan)
    candidates=[]
    for name, expansion in (("control",False),("definition",True)):
        dest=args.output/name
        run(Path("fixtures/phase2/corpus.json"),Path("fixtures/phase2/dev.json"),dest,
            stages=[2],repeats=2,config_overrides=dict(split_long=True,definition_expansion=expansion))
        candidate=select(dest)
        regression=args.output/(name+"-regression")
        run(Path("fixtures/synthetic/corpus.json"),Path("fixtures/synthetic/queries.json"),regression,
            stages=[2],repeats=1,selected_config=candidate["config"])
        rows=json.loads((regression/"results.json").read_text())
        chosen=[r for r in rows if r["method"]=="B" and r["budget"]==candidate["budget"] and r["cache_state"]=="warm_index"]
        candidate["regression_run"]=str(regression)
        candidate["regression_complete"]=sum(r["complete_evidence"] for r in chosen if r["evidence_eligible"])
        candidate["regression_eligible"]=sum(r["evidence_eligible"] for r in chosen)
        candidate["regression_gate"]=all(r["complete_evidence"] for r in chosen if r["query_id"] in {"q22","q30"})
        candidates.append(candidate)
    def key(c):
        s=c["dev_result"]
        return (not c["regression_gate"],-s["complete_queries"],s["condition_missing_queries"],s["obsolete_only_queries"],s["first_repeat_units_total"])
    choice=min(candidates,key=key)
    choice["compared_runs"]=[c["development_run"] for c in candidates]
    choice["selection_protocol"]=plan
    choice["fixture_freeze"]=json.loads(Path("fixtures/phase2/FREEZE.json").read_text())
    choice["frozen_at"]=datetime.now(timezone.utc).isoformat()
    write_json(args.output/"candidates.json",candidates)
    write_json(args.output/"selection.json",choice)
    print(json.dumps({"selected":choice["config"],"budget":choice["budget"],"dev_complete":choice["dev_result"]["complete_queries"],"regression_complete":choice["regression_complete"],"regression_gate":choice["regression_gate"]},ensure_ascii=False))


if __name__=="__main__":
    main()
