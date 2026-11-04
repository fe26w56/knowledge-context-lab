"""Measure retrieval-cache reuse without paid duplicate model requests.

These are local retrieval timings and context byte comparisons, not measured
model quality or complete workflow latency. All index builds count in timings.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import tempfile
import time

from context_lab.workflow import WorkflowEngine, context_item, digest, visible_sources
from context_lab.workflow_eval import verify_fixture


def main():
    p = argparse.ArgumentParser(); p.add_argument("--fixture", required=True)
    p.add_argument("--output", required=True); p.add_argument("--repeats", type=int, default=3)
    a = p.parse_args(); fixture, out = Path(a.fixture), Path(a.output)
    verify_fixture(fixture); out.mkdir(parents=True, exist_ok=False)
    rows, pairs = [], []; rng = random.Random(63105)
    with tempfile.TemporaryDirectory() as temporary:
        for path in sorted((fixture/"dev").glob("*/episode.json")):
            episode = json.loads(path.read_text())
            for repeat in range(a.repeats):
                results = {}; arms = ["full12", "reuse12"]; rng.shuffle(arms)
                for arm in arms:
                    engine = WorkflowEngine(arm, None, Path(temporary)/f"{path.parent.name}-{repeat}-{arm}")
                    samples = {}; start = time.perf_counter()
                    def retrieve(wave, task):
                        t = time.perf_counter()
                        visible = visible_sources(episode["sources"],wave["available_source_ids"],task["actor"],wave["as_of"])
                        selected, _, hit = engine.retrieve(visible,task["topic"],task["area"],wave["as_of"],task["actor"])
                        return task["task_id"], {"context_sha256":digest([context_item(s) for s in selected]),
                                                  "seconds":time.perf_counter()-t,"hit":hit}
                    for wave in episode["waves"]:
                        with ThreadPoolExecutor(max_workers=4) as pool:
                            futures=[pool.submit(retrieve,wave,task) for task in wave["tasks"]]
                            samples.update(f.result() for f in futures)
                    rows.append({"case":path.parent.name,"repeat":repeat,"arm":arm,"design":episode["design"],
                                 "elapsed_seconds":time.perf_counter()-start,"index_builds":engine.indexes.builds,
                                 "retrieval_hits":engine.retrievals.hits,"tasks":samples})
                    results[arm]=samples
                for tid, sample in results["full12"].items():
                    same=sample["context_sha256"]==results["reuse12"][tid]["context_sha256"]
                    pairs.append({"case":path.parent.name,"repeat":repeat,"task_id":tid,"equal":same})
    report={"status":"pass" if all(p["equal"] for p in pairs) else "fail", "pairs":pairs,"rows":rows,
            "api_calls":0,"model_quality_measured":False,"end_to_end_model_latency_measured":False,
            "attribution":"Only local retrieval coalescing. Same model context; no inference calls removed."}
    (out/"results.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"pairs":len(pairs),"rows":len(rows)}))
    return 0 if report["status"]=="pass" else 2


if __name__ == "__main__":raise SystemExit(main())
