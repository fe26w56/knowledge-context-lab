"""Replay and audit saved synthetic completion payloads without model calls."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import tempfile
from collections import defaultdict
from copy import deepcopy
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(errors: list[dict], kind: str, row: dict) -> None:
    errors.append({"kind": kind, "id": row.get("query_id"), "variant": row.get("variant"),
                   "method": row.get("method"), "budget": row.get("budget"), "dataset": row.get("size"), "seed": row.get("seed")})


class MemoryAdapter:
    def __init__(self, documents):
        self.documents = deepcopy(documents)
        self.read_calls = 0

    def read(self):
        self.read_calls += 1
        return deepcopy(self.documents)

    def close(self):
        pass


def _body_indexed(doc: dict) -> bool:
    body = doc.get("body")
    if not isinstance(body, str):
        return False
    covered = [False] * len(body)
    for section in doc.get("sections", []):
        text = section.get("text") if isinstance(section, dict) else None
        if not isinstance(text, str) or not text:
            return False
        start = body.find(text)
        if start < 0:
            return False
        while start >= 0:
            covered[start:start + len(text)] = [True] * len(text)
            start = body.find(text, start + 1)
    offset = 0
    for line in body.splitlines(keepends=True):
        if not line.lstrip().startswith("#"):
            if any(not char.isspace() and not covered[offset + i] for i, char in enumerate(line)):
                return False
        offset += len(line)
    return True


def _body_sections_eligible(doc: dict, request: dict, config: dict) -> bool:
    mode = request.get("mode", "search")
    as_of = request.get("as_of")
    scope = request.get("scope")
    actor = request.get("actor", "")
    if scope is not None and doc.get("scope") != scope:
        return False
    if doc.get("scope") == "private" and doc.get("owner") != actor:
        return False
    sections = doc.get("sections", [])
    if not sections or not _body_indexed(doc):
        return False
    states = []
    for section in sections:
        status = section.get("adoption_status", "na")
        if config.get("strict_current_state", False) and mode == "current" and status in {"draft", "proposed", "superseded"}:
            return False
        # Complete-document packing is stricter than ordinary section retrieval:
        # a current body must not combine draft/proposed/superseded sections,
        # regardless of the ordinary retrieval switch.
        if mode == "current" and status not in {"adopted", "na"}:
            return False
        if mode == "current" and section.get("kind") == "decision" and status != "adopted":
            return False
        if mode in {"current", "history"}:
            start, end = section.get("valid_from"), section.get("valid_to")
            if start and as_of and start > as_of:
                return False
            if end and as_of and not as_of < end:
                return False
        states.append(tuple(section.get(key) for key in
                            ("adoption_status", "valid_from", "valid_to", "verified_at")))
    return len(set(states)) == 1


def _audit_document_body(item: dict, doc: dict, request: dict, config: dict) -> bool:
    if item.get("kind") != "document_body" or item.get("source_format") != "document_body":
        return False
    if "section_id" in item or "parent_section_id" in item:
        return False
    body = doc.get("body", "")
    if item.get("text") != body or item.get("spans") != [[0, len(body)]]:
        return False
    if not _body_sections_eligible(doc, request, config):
        return False
    expected = tuple(doc["sections"][0].get(key) for key in
                     ("adoption_status", "valid_from", "valid_to", "verified_at"))
    return tuple(item.get(key) for key in
                 ("adoption_status", "valid_from", "valid_to", "verified_at")) == expected


def audit_run(run: Path, output: Path, fixture: Path | None = None) -> dict:
    if output.exists():
        raise FileExistsError(output)
    metadata = json.loads((run / "metadata.json").read_text())
    fixture = fixture or Path("fixtures/phase2-completion-v7")
    source_dir = run / "source"
    source_hash_ok = all(sha(source_dir / "context_lab" / name) == expected
                         for name, expected in metadata["source_sha256"].items())
    query_path = next((fixture/name for name in ("dev.json", "final.json") if sha(fixture/name) == metadata["queries_sha256"]), None)
    fixture_hash_ok = sha(fixture / "corpus.json") == metadata["corpus_sha256"] and query_path is not None
    freeze_ok = metadata.get("fixture_freeze_sha256") is None or sha(fixture / "FREEZE.json") == metadata["fixture_freeze_sha256"]
    if not (source_hash_ok and fixture_hash_ok and freeze_ok):
        result = {"run": str(run), "status": "source_or_fixture_mismatch",
                  "source_hash_ok": source_hash_ok, "fixture_hash_ok": fixture_hash_ok,
                  "freeze_hash_ok": freeze_ok, "replayed": 0, "errors": []}
        output.mkdir(parents=True, exist_ok=False)
        (output / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    cached_context_modules = {name: module for name, module in sys.modules.items()
                              if name == "context_lab" or name.startswith("context_lab.")}
    for name in cached_context_modules:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(source_dir))
    try:
        release_eval = importlib.import_module("context_lab.release_eval")
        completion = importlib.import_module("context_lab.retrieval_completion")
        adaptive = importlib.import_module("context_lab.retrieval_adaptive") if metadata.get("adaptive_ablation") else None
        metrics = importlib.import_module("context_lab.metrics")
        loaded_root = Path(completion.__file__).parent
        if not all(sha(loaded_root/name) == expected for name, expected in metadata["source_sha256"].items()):
            raise ValueError("loaded replay modules do not match recorded source hashes")
        corpus = json.loads((fixture / "corpus.json").read_text())
        questions = {q["id"]: q for q in json.loads(query_path.read_text())["queries"]}
        saved_rows = [json.loads(line) for line in (run / "payloads.jsonl").read_text().splitlines() if line]
        result_rows = json.loads((run / "results.json").read_text())
        result_by_key = {(r["variant"], r["method"], r["budget"], r["size"], r["seed"], r["query_id"]): r for r in result_rows if r["repeat"] == 0}
        groups = defaultdict(dict)
        for row in saved_rows:
            groups[(row["variant"], row["budget"], row["size"], row["seed"], row["query_id"])][row["method"]] = row
        datasets = {(item["size"], item["seed"]): item for item in metadata["datasets"]}
        errors: list[dict] = []
        replay_mismatches: list[dict] = []
        replay_mismatch_count = 0
        counts = defaultdict(int)
        with tempfile.TemporaryDirectory(prefix="completion-audit-"):
            engines = {}
            engine_configs = {}
            engine_class = adaptive.AdaptiveRetrieval if adaptive else completion.CompletionRetrieval
            config_class = adaptive.AdaptiveConfig if adaptive else completion.CompletionConfig
            for (size, seed), dataset_meta in datasets.items():
                documents, _, generated = release_eval.generate(corpus, size, seed)
                if generated.get("corpus_hash") != dataset_meta.get("corpus_hash"):
                    errors.append({"kind": "generated_corpus_hash", "size": size, "seed": seed})
                    continue
                for variant, config in metadata["variants"].items():
                    engines[(variant, size, seed)] = engine_class(MemoryAdapter(documents), config_class(**config))
                    engine_configs[(variant, size, seed)] = config
            for key, methods in groups.items():
                variant, budget, size, seed, query_id = key
                query = questions.get(query_id)
                engine = engines.get((variant, size, seed))
                if query is None or engine is None or set(methods) != {"A", "B", "C"}:
                    fail(errors, "missing_replay_inputs", dict(query_id=query_id, variant=variant, size=size, seed=seed))
                    continue
                replayed = {}
                for method in ("A", "B", "C"):
                    row = methods[method]
                    counter = metrics.UnitCounter("o200k_base")
                    value = engine.retrieve(dict(query["request"]), budget, counter, full=method == "A")
                    payload = value["payload"]
                    replayed[method] = (value, json.loads(payload), counter(payload))
                    expected = result_by_key.get((variant, method, budget, size, seed, query_id))
                    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["payload_sha256"]:
                        fail(errors, "saved_payload_hash", row)
                    if expected is None or expected["payload_sha256"] != row["payload_sha256"] or expected["units"] != counter(row["payload"]):
                        fail(errors, "saved_result_hash_or_units", row)
                    if hashlib.sha256(payload.encode()).hexdigest() != row["payload_sha256"]:
                        replay_mismatch_count += 1
                        if len(replay_mismatches) < 40:
                            replay_mismatches.append({"query_id": row.get("query_id"), "variant": row.get("variant"),
                                                      "method": row.get("method"), "budget": budget, "size": row.get("size"), "seed": row.get("seed")})
                    if expected and value["candidate_documents"] != expected["candidates"]:
                        fail(errors, "candidate_replay", row)
                    if method != "A" and counter(row["payload"]) > budget:
                        fail(errors, "budget", row)
                    counts[f"{method.lower()}_payloads"] += 1
                    envelope = json.loads(row["payload"])
                    docs = engine.docs
                    for source_id, source in envelope.get("sources", {}).items():
                        doc = docs.get(source_id)
                        if not doc or any(source.get(k) != doc.get(k) for k in ("title", "source_url", "recorded_at", "verified_at")) or source.get("revision") != release_eval.digest(doc["body"]):
                            fail(errors, "source_metadata", row)
                    for item in envelope.get("items", []):
                        doc = docs.get(item.get("document_id"))
                        if not doc:
                            fail(errors, "item_document", row)
                            continue
                        actor = query["request"]["actor"]
                        scope = query["request"].get("scope")
                        if (scope is not None and doc["scope"] != scope) or (doc["scope"] == "private" and doc.get("owner") != actor):
                            fail(errors, "saved_scope", row)
                        if method == "A":
                            if item.get("text") != doc["body"]:
                                fail(errors, "full_body", row)
                            continue
                        if adaptive and item.get("kind") == "document_body":
                            if not _audit_document_body(item, doc, query["request"], engine_configs[(variant, size, seed)]):
                                fail(errors, "document_body", row)
                            continue
                        parent = next((s for s in doc["sections"] if s["id"] == item.get("parent_section_id")), None)
                        if not parent or item.get("kind") != parent.get("kind") or item.get("adoption_status") != parent.get("adoption_status") or item.get("valid_from") != parent.get("valid_from") or item.get("valid_to") != parent.get("valid_to"):
                            fail(errors, "section_metadata", row)
                            continue
                        spans = item.get("spans", [])
                        if any(not (0 <= a <= b <= len(parent["text"])) for a, b in spans) or "".join(parent["text"][a:b] for a, b in spans) != item.get("text"):
                            fail(errors, "section_spans", row)
                if replayed["A"][0]["candidate_documents"] != replayed["B"][0]["candidate_documents"] or replayed["B"][0]["candidate_documents"] != replayed["C"][0]["candidate_documents"]:
                    fail(errors, "candidate_parity", dict(query_id=query_id, variant=variant, size=size, seed=seed))
                    counts["candidate_parity_failures"] += 1
                if replayed["B"][0]["payload"] != replayed["C"][0]["payload"]:
                    fail(errors, "bc_payload_parity", dict(query_id=query_id, variant=variant, size=size, seed=seed))
                    counts["bc_payload_parity_failures"] += 1
                if methods["B"]["payload"] != methods["C"]["payload"]:
                    fail(errors, "saved_bc_payload_parity", dict(query_id=query_id, variant=variant,size=size,seed=seed))
                counts["replayed_groups"] += 1
            # MemoryAdapter has no external resources; grouped adapters are
            # intentionally left to the temporary process lifetime.
        status = "pass" if not errors and not replay_mismatch_count else "fail"
        result = {"run": str(run), "status": status, "source_hash_ok": source_hash_ok,
                  "fixture_hash_ok": fixture_hash_ok, "freeze_hash_ok": freeze_ok,
                  "saved_rows": len(saved_rows), "groups": len(groups), "counts": dict(counts),
                  "error_count": len(errors), "errors": errors[:40], "replay_mismatch_count": replay_mismatch_count,
                  "replay_mismatch_ids": replay_mismatches}
    finally:
        sys.path.pop(0)
        for name in list(sys.modules):
            if name == "context_lab" or name.startswith("context_lab."):
                sys.modules.pop(name, None)
        sys.modules.update(cached_context_modules)
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/phase2-completion-v7"))
    args = parser.parse_args()
    result = audit_run(args.run, args.output, args.fixture)
    print(json.dumps({k: result[k] for k in ("run", "status", "saved_rows", "groups", "counts") if k in result}, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
