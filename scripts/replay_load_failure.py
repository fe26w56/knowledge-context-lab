"""Reconstruct load payloads and verify their hashes against the measured run."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from context_lab.load_test import generate_corpus, canonical_hash
from context_lab.metrics import UnitCounter
from context_lab.retrieval_v2 import Config, FileAdapter, RetrievalV2
from context_lab.phase2_eval import implementation_hash


def replay(output):
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    read = lambda name: json.loads((root / name).read_text())
    meta = read("runs/phase2-load-v1/metadata.json")
    assert implementation_hash() == meta["implementation_sha256"]
    original = read("fixtures/phase2/corpus.json")
    queries = {q["id"]: q for q in read("fixtures/phase2/dev.json")["queries"]}
    rows = [json.loads(line) for line in (root / "runs/phase2-load-v1/trials.jsonl").read_text().splitlines()]
    samples = []
    for size in (100, 1000, 10000):
        corpus, _ = generate_corpus(original, size, meta["seed"])
        generation = next(g for g in meta["generation"] if g["size"] == size)
        assert canonical_hash(corpus) == generation["corpus_sha256_before_update"]
        update = deepcopy(corpus["documents"][-1])
        old = update["sections"][0]["text"]
        update["sections"][0]["text"] = old + " 差分更新負荷テスト。"
        update["body"] = update["body"].replace(old, update["sections"][0]["text"], 1)
        update["recorded_at"] = "2026-04-21"
        corpus["documents"][-1] = update
        assert canonical_hash(corpus) == generation["corpus_sha256_after_update"]
        with tempfile.TemporaryDirectory(prefix="context-load-replay-") as temp:
            adapter = FileAdapter.create(Path(temp) / "index", corpus["documents"])
            engine = RetrievalV2(adapter, Config(**meta["config"]))
            for query_id in meta["selected_query_ids"]:
                result = engine.retrieve(dict(queries[query_id]["request"]), meta["budget"], UnitCounter("o200k_base"))
                measured = next(r for r in rows if r["size"] == size and r["method"] == "B" and r["query_id"] == query_id and r["cache_state"] == "warm" and r["repeat"] == 0)
                assert hashlib.sha256(result["payload"].encode()).hexdigest() == measured["payload_sha256"]
                samples.append(dict(size=size, query_id=query_id, request=queries[query_id]["request"],
                                    payload=json.loads(result["payload"]), candidate_documents=result["candidate_documents"],
                                    literal_quote_recall=measured["literal_quote_recall"], original_source_quote_recall=measured["original_source_quote_recall"],
                                    source_quote_map=measured["source_quote_map"], measured_payload_sha256=measured["payload_sha256"]))
            adapter.close()
    (output / "payloads.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2) + "\n")
    (output / "metadata.json").write_text(json.dumps(dict(samples=len(samples), measured_run="runs/phase2-load-v1", all_payload_hashes_matched=True,
        new_timing_measurement=False, implementation_sha256=implementation_hash(), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), indent=2) + "\n")
    print(json.dumps({"samples": len(samples), "all_payload_hashes_matched": True}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    replay(p.parse_args().output)
