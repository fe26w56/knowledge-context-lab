"""Execute the declared development comparisons and freeze a final choice."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from context_lab.phase2_eval import implementation_hash, run, select, write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=2)
    args=p.parse_args()
    if args.repeats < 1:
        p.error("repeats must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    plan=json.loads(Path("runs/phase2-development-plan.json").read_text())
    write_json(args.output/"plan.json",plan)
    candidates=[]
    for comparison in plan["next_comparisons"]:
        destination=args.output/comparison["name"]
        run(Path("fixtures/phase2/corpus.json"),Path("fixtures/phase2/dev.json"),destination,
            stages=comparison["stages"],repeats=args.repeats,config_overrides=comparison["config"])
        candidates.append(select(destination))
    def key(candidate):
        s=candidate["dev_result"]
        return (-s["complete_queries"],s["condition_missing_queries"],s["obsolete_only_queries"],s["first_repeat_units_total"],s["stage"],s["budget"])
    choice=min(candidates,key=key)
    choice["compared_runs"]=[c["development_run"] for c in candidates]
    choice["frozen_at"]=datetime.now(timezone.utc).isoformat()
    choice["implementation_sha256"]=implementation_hash()
    choice["fixture_freeze"]=json.loads(Path("fixtures/phase2/FREEZE.json").read_text())
    write_json(args.output/"selection.json",choice)
    print(json.dumps({"selected_run":choice["development_run"],"config":choice["config"],"budget":choice["budget"],"complete":choice["dev_result"]["complete_queries"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
