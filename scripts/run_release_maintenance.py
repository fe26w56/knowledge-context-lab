"""Measure local rebuild/update and 16 concurrent readers on the frozen profile."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import tempfile
import time

from context_lab.metrics import UnitCounter, percentile
from context_lab.release_eval import FIXTURE, generate, source_hashes, write
from context_lab.retrieval_release import ReleaseConfig, ReleaseRetrieval
from context_lab.retrieval_v2 import ADAPTERS


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sizes", default="100,1000,10000")
    args = p.parse_args()
    selected = json.loads(args.selection.read_text())
    assert selected["source_sha256"] == source_hashes()
    corpus = json.loads((FIXTURE/"corpus.json").read_text())
    request = dict(json.loads((FIXTURE/"dev.json").read_text())["queries"][0]["request"], scope="shared")
    cfg = ReleaseConfig(**selected["config"])
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.output/"source/context_lab"
    source.mkdir(parents=True)
    for name in source_hashes():
        shutil.copyfile(Path("src/context_lab")/name, source/name)
    shutil.copyfile(__file__, args.output/"run_release_maintenance.py")
    counter = UnitCounter("o200k_base")
    counter("Dictionary warmup")
    events = []
    with tempfile.TemporaryDirectory(prefix="release-maintenance-") as temp:
        for size in map(int, args.sizes.split(",")):
            documents, _, generated = generate(corpus, size, 9201)
            outputs = {}
            for backend in random.Random(size).sample(list(ADAPTERS), len(ADAPTERS)):
                path = Path(temp)/f"{size}-{backend}"
                start = time.perf_counter()
                adapter = ADAPTERS[backend].create(path, documents)
                import_ms = (time.perf_counter()-start)*1000
                start = time.perf_counter()
                engine = ReleaseRetrieval(adapter, cfg)
                index_ms = (time.perf_counter()-start)*1000
                reopen = []
                for _ in range(3):
                    start = time.perf_counter()
                    other = ADAPTERS[backend](path)
                    cold = ReleaseRetrieval(other, cfg)
                    other.close()
                    reopen.append((time.perf_counter()-start)*1000)
                    del cold
                def query(worker):
                    count = UnitCounter("o200k_base")
                    start = time.perf_counter()
                    result = engine.retrieve(dict(request, actor=f"bot_{worker+1:02}"), selected["budget"], count)
                    return dict(worker=worker, ms=(time.perf_counter()-start)*1000,
                        payload_sha256=hashlib.sha256(result["payload"].encode()).hexdigest(), backend_reads=result["backend_calls_during_query"])
                start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=16) as pool:
                    concurrent = list(pool.map(query, range(16)))
                batch_ms = (time.perf_counter()-start)*1000
                assert len({r["payload_sha256"] for r in concurrent}) == 1
                assert all(r["backend_reads"] == 0 for r in concurrent)
                outputs[backend] = concurrent[0]["payload_sha256"]
                changed = deepcopy(next(d for d in documents if d["scope"] == "shared" and len(d["sections"][0]["text"]) < 300))
                original = changed["sections"][0]["text"]
                changed["sections"][0]["text"] += " 更新確認 RELEASEDELTAMARKER。"
                changed["body"] = changed["body"].replace(original, changed["sections"][0]["text"], 1)
                start = time.perf_counter()
                adapter.update([changed])
                update_ms = (time.perf_counter()-start)*1000
                assert next(d for d in adapter.read() if d["id"] == changed["id"]) == changed
                start = time.perf_counter()
                updated = ReleaseRetrieval(adapter, cfg)
                reindex_ms = (time.perf_counter()-start)*1000
                reply = updated.retrieve(dict(text="RELEASEDELTAMARKER", actor="bot_01", scope="shared", mode="search"), 2000, counter)
                assert any(item["document_id"] == changed["id"] and "RELEASEDELTAMARKER" in item["text"] for item in json.loads(reply["payload"])["items"])
                events.append(dict(size=size, backend=backend, corpus_hash=generated["corpus_hash"], import_ms=import_ms, index_ms=index_ms,
                    indexed_documents=engine.documents_indexed, reopen_index_ms=reopen, update_commit_ms=update_ms,
                    reindex_ms=reindex_ms, update_readback_and_query_verified=True,
                    reader_batch_ms=batch_ms, reader_median_ms=statistics.median(r["ms"] for r in concurrent),
                    reader_p95_ms=percentile([r["ms"] for r in concurrent], .95), readers=concurrent))
                adapter.close()
                del engine, updated
            assert outputs["file"] == outputs["sqlite"]
    write(args.output/"results.json", events)
    write(args.output/"metadata.json", dict(source_sha256=source_hashes(), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        selection=selected, seed=9201, concurrent_readers=16, update_repeats=1, reopen_repeats=3, actual_model_agents=False,
        query_io=False, dictionary_prewarmed=True, os_cache_flushed=False, scope="shared", provider_cost_measured=False, d1_measured=False))
    print(json.dumps({"events": len(events), "all_updates_and_backend_parity_verified": True}))


if __name__ == "__main__":
    main()
