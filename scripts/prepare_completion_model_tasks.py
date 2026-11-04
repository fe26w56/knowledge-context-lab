"""Prepare paired synthetic inputs from frozen retrieval outputs; no API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import random

from context_lab.model_eval import sanitize_request, sanitize_retrieved_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/phase2-completion-v7"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--datasets", required=True, help="Comma-separated size:seed pairs")
    parser.add_argument("--budget", type=int, default=4000)
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat must be positive")
    metadata = json.loads((args.run/"metadata.json").read_text())
    query_path = next((args.fixture/name for name in ("dev.json", "final.json")
                      if hashlib.sha256((args.fixture/name).read_bytes()).hexdigest() == metadata["queries_sha256"]), None)
    if query_path is None:
        parser.error("fixture queries do not match the frozen run")
    queries = {q["id"]: sanitize_request(q["request"]) for q in json.loads(query_path.read_text())["queries"]}
    datasets = {tuple(map(int, item.split(":"))) for item in args.datasets.split(",")}
    # C has exactly the same context as B; repeating identical model inputs
    # would not establish a database benefit. Storage measurements stay separate.
    arms = {("selected", "A"), ("selected", "B"), ("control", "A"), ("control", "B")}
    tasks, mapping = [], []
    for line in (args.run/"payloads.jsonl").read_text().splitlines():
        row = json.loads(line)
        if (row["size"], row["seed"]) not in datasets or row["budget"] != args.budget or (row["variant"],row["method"]) not in arms:
            continue
        if hashlib.sha256(row["payload"].encode()).hexdigest() != row["payload_sha256"]:
            raise ValueError("saved payload hash mismatch")
        payload = sanitize_retrieved_payload(row["payload"])
        for repeat in range(args.repeat):
            task_key = f"{row['size']}:{row['seed']}:{row['query_id']}:{row['variant']}:{row['method']}:{repeat}"
            tasks.append(dict(task_key=task_key, request=queries[row["query_id"]],retrieved_payload=payload))
            mapping.append({k:row[k] for k in ("variant","method","size","seed","query_id","budget","payload_sha256")}
                           | dict(task_key=task_key,repeat=repeat))
    expected = len(datasets)*len(queries)*len(arms)*args.repeat
    if len(tasks) != expected or len({task["task_key"] for task in tasks}) != expected:
        raise ValueError("requested paired comparison is incomplete or duplicated")
    random.Random(29100).shuffle(tasks)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/"tasks.json").write_text(json.dumps(tasks,ensure_ascii=False)+"\n")
    (args.output/"mapping.json").write_text(json.dumps(mapping,ensure_ascii=False,indent=2)+"\n")
    receipt = dict(tasks=len(tasks),distinct_questions=len(queries),repeats=args.repeat,
        task_order_seed=29100,model_called=False,gold_sent=False,task_key_sent=False,
        retrieval_run=str(args.run),queries_sha256=metadata["queries_sha256"],
        tasks_sha256=hashlib.sha256((args.output/"tasks.json").read_bytes()).hexdigest(),
        comparison="same-candidate full vs bounded for both selected and previous retrieval; C equals B")
    (args.output/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
