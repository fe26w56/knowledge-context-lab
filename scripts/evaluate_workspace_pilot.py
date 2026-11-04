"""Measure a private-authorized workspace capture without exposing its content.

This is an offline pilot harness. It compares file-shaped source snapshots with
the SQLite workspace; it does not call Notion, a model, or a network service.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

from context_lab.workspace import Workspace, digest, notion_pages


ARMS = ("raw", "compact", "current", "compact_bm25")


def _outside_repo(path: Path, repo: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(repo)
    except ValueError:
        return resolved
    raise ValueError(f"{label} must be outside the public repository")


def _load_capture(path: Path, repo: Path) -> tuple[list[dict], str]:
    resolved = _outside_repo(path, repo, "input")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if data.get("privacy") != "private_authorized":
        raise ValueError("input privacy must be private_authorized")
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("input pages must be a nonempty list")
    return deepcopy(pages), hashlib.sha256(resolved.read_bytes()).hexdigest()


def _file_sources(pages: list[dict], actor: str) -> list[dict]:
    return [{"page": deepcopy(page), "version": 1, "sha256": digest(page),
             "revision_id": f"source:{page['id']}@1"}
            for page in pages if page.get("scope") == "private" and page.get("owner") == actor]


def _search_arms(ws: Workspace, file_sources: list[dict], requests: list[dict], candidate_pages: int) -> list[dict]:
    rows = []
    for request in requests:
        case, text = request["case"], request["request"]
        for arm in ARMS:
            mode, ranking = ("compact", "bm25") if arm == "compact_bm25" else (arm, "legacy")
            started = time.perf_counter()
            sqlite_result = ws.search(text, actor=request["actor"], mode=mode,
                                      candidate_pages=candidate_pages, ranking=ranking)
            sqlite_seconds = time.perf_counter() - started
            started = time.perf_counter()
            file_result = Workspace.search_sources(file_sources, text, mode=mode,
                                                   candidate_pages=candidate_pages, ranking=ranking)
            file_seconds = time.perf_counter() - started
            rows.append({"case": case, "arm": arm, "mode": mode, "ranking": ranking,
                         "sqlite_seconds": sqlite_seconds, "file_seconds": file_seconds,
                         "payload_equal": sqlite_result == file_result,
                         "sqlite_source_count": len(sqlite_result["sources"]),
                         "file_source_count": len(file_result["sources"]),
                         "sqlite_payload_chars": len(json.dumps(sqlite_result, ensure_ascii=False)),
                         "file_payload_chars": len(json.dumps(file_result, ensure_ascii=False)),
                         "payload": {"sqlite": sqlite_result, "file": file_result}})
            if arm == "raw" and all("raw_capture" in source["page"] for source in file_sources):
                native_sqlite = ws.search(text, actor=request["actor"], mode="capture",
                                          candidate_pages=candidate_pages, ranking="legacy")
                native_file = Workspace.search_sources(file_sources, text, mode="capture",
                                                       candidate_pages=candidate_pages, ranking="legacy")
                rows.append({"case": case, "arm": "native_capture", "mode": "connector_capture",
                             "ranking": "legacy", "payload_equal": native_sqlite == native_file,
                             "selected_source_ids": [item["source_id"] for item in native_sqlite["sources"]],
                             "native_payload_chars": len(json.dumps(native_sqlite, ensure_ascii=False)),
                             "native_capture_available": True,
                             "payload": {"sqlite": native_sqlite, "file": native_file}})
    return rows


def run(input_path: Path, requests_path: Path, output_path: Path, *, actor: str,
        candidate_pages: int = 3, repo: Path | None = None) -> dict:
    repo = (repo or Path(__file__).resolve().parents[1]).resolve()
    timings = {}
    started = time.perf_counter()
    pages, input_sha256 = _load_capture(input_path, repo)
    timings["input_load_seconds"] = time.perf_counter() - started
    requests_resolved = _outside_repo(requests_path, repo, "requests")
    started = time.perf_counter()
    requests_data = json.loads(requests_resolved.read_text(encoding="utf-8"))
    timings["requests_load_seconds"] = time.perf_counter() - started
    requests = requests_data.get("requests") if isinstance(requests_data, dict) else requests_data
    if not isinstance(requests, list) or not requests or any(
            not isinstance(r, dict) or not isinstance(r.get("case"), str) or
            not isinstance(r.get("request"), str) for r in requests):
        raise ValueError("requests must be a nonempty list of {case, request}")
    for request in requests:
        request["actor"] = actor
    output = _outside_repo(output_path, repo, "output")
    if output.exists():
        raise ValueError("output must be a new path")
    if not 1 <= candidate_pages <= 100:
        raise ValueError("candidate_pages must be between 1 and 100")
    if not output.parent.exists():
        output.parent.mkdir(parents=True, mode=0o700)
        os.chmod(output.parent, stat.S_IRWXU)
    source_pages = _file_sources(pages, actor)
    if len(source_pages) != len(pages):
        raise ValueError("pilot pages must all be private to the configured actor")
    with tempfile.TemporaryDirectory(prefix="workspace-pilot-") as temp:
        root = Path(temp)
        ws = Workspace(root / "pilot.sqlite")
        started = time.perf_counter()
        imported = ws.import_pages(pages, actor=actor, request_id="pilot-import")
        timings["db_import_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        arms = _search_arms(ws, source_pages, requests, candidate_pages)
        timings["search_seconds"] = time.perf_counter() - started
        read_request = requests[0]["request"]
        started = time.perf_counter()
        barrier = threading.Barrier(16)
        release_barrier = threading.Barrier(16)
        inflight = 0
        max_inflight = 0
        counter_lock = threading.Lock()

        def concurrent_read():
            nonlocal inflight, max_inflight
            barrier.wait()
            with counter_lock:
                inflight += 1
                max_inflight = max(max_inflight, inflight)
            try:
                release_barrier.wait()
                return ws.search(read_request, actor=actor, mode="compact",
                                 candidate_pages=candidate_pages)
            finally:
                with counter_lock:
                    inflight -= 1

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(concurrent_read) for _ in range(16)]
            reads = [future.result() for future in futures]
        local_reads = {"clients": 16, "completed": len(reads),
                       "all_payload_equal": all(result == reads[0] for result in reads),
                       "max_inflight": max_inflight,
                       "wall_seconds": time.perf_counter() - started}

        correction_pages = deepcopy(pages)
        page = correction_pages[0]
        lines = [line for line in page["body"].splitlines() if line.strip() and not line.lstrip().startswith("#")]
        quote = lines[0] if lines else page["body"][: min(80, len(page["body"]))]
        start = page["body"].index(quote)
        correction_projection = "body_fallback"
        payload = {"title": "Pilot topic", "summary": "Controlled private pilot record.",
                   "conditions": ["review source evidence"], "state": "proposed",
                   "as_of": "2026-11-03", "task_refs": ["pilot:controlled"]}
        correction_db = Workspace(root / "correction.sqlite")
        started = time.perf_counter()
        correction_db.import_pages(pages, actor=actor, request_id="correction-seed")
        source = correction_db.get_source(page["id"], actor=actor)
        evidence = {"source_id": page["id"], "source_version": source["version"],
                    "start": start, "end": start + len(quote), "quote": quote}
        correction_db.publish_topic("pilot-topic", payload, [evidence], actor=actor,
                                    expected_version=0, request_id="pilot-topic-publish",
                                    scope="private", owner=actor)
        timings["correction_setup_seconds"] = time.perf_counter() - started
        raw_capture = page.get("raw_capture")
        if (isinstance(page.get("capture_coverage"), str)
                and page["capture_coverage"].startswith("Connector-rendered page and metadata;")
                and isinstance(raw_capture, dict) and isinstance(raw_capture.get("text"), str)):
            marker = "\n</content>\n</page>"
            if marker not in raw_capture["text"]:
                raise ValueError("canonical Notion capture has no complete content boundary")
            corrected_snapshot = deepcopy(raw_capture)
            content_start_marker = "<content>\n"
            content_end_marker = "\n</content>\n</page>"
            content_start = corrected_snapshot["text"].find(content_start_marker)
            content_end = corrected_snapshot["text"].rfind(content_end_marker)
            if content_start < 0 or content_end < content_start:
                raise ValueError("canonical Notion capture has invalid content boundary")
            content_start += len(content_start_marker)
            content = corrected_snapshot["text"][content_start:content_end]
            quote_offset = content.index(quote) + len(quote)
            corrected_content = content[:quote_offset] + "\n\nControlled pilot correction." + content[quote_offset:]
            corrected_snapshot["text"] = (corrected_snapshot["text"][:content_start] +
                                          corrected_content + corrected_snapshot["text"][content_end:])
            corrected_page = notion_pages([corrected_snapshot], owner=actor)[0]
            correction_projection = "capture_reprojected"
        else:
            corrected_page = deepcopy(correction_pages[0])
            corrected_page["body"] += "\n\nControlled pilot correction."
        started = time.perf_counter()
        corrected = correction_db.import_pages(
            [corrected_page], actor=actor, request_id="pilot-correction",
            expected_versions={page["id"]: source["version"]})
        timings["correction_seconds"] = time.perf_counter() - started
        stale = correction_db.get_topic("pilot-topic", actor=actor)
        readback = correction_db.get_source(page["id"], actor=actor)
        capture_readback = (correction_db.search("Controlled pilot correction", actor=actor,
                                                mode="capture", candidate_pages=candidate_pages)
                            if correction_projection == "capture_reprojected" else None)
        old_readback = correction_db.get_source(page["id"], actor=actor, version=1)
        started = time.perf_counter()
        replay = correction_db.import_pages(
            [corrected_page], actor=actor, request_id="pilot-correction",
            expected_versions={page["id"]: source["version"]})
        timings["retry_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        bundle = correction_db.export_bundle(actor=actor)
        restored = Workspace.restore_bundle(bundle, root / "restored.sqlite")
        timings["export_restore_seconds"] = time.perf_counter() - started
        lifecycle = {"topic_status_after_correction": stale["status"],
                     "correction_committed": bool(corrected["committed"]),
                     "replay_unchanged": bool(replay["committed"] and replay["committed"][0].get("replayed")),
                     "export_restore_parity": bundle == restored.export_bundle(actor=actor),
                     "correction_projection": correction_projection,
                     "capture_body_readback_consistent": (
                         correction_projection != "capture_reprojected" or
                         "Controlled pilot correction." in readback["page"]["body"] and
                         "Controlled pilot correction." in readback["page"]["raw_capture"]["text"] and
                         capture_readback is not None and bool(capture_readback["sources"]) and
                         capture_readback["sources"][0]["source_id"] == page["id"] and
                         capture_readback["sources"][0]["capture"] == corrected_page["raw_capture"] and
                         capture_readback["sources"][0]["source_version"] == readback["version"]),
                     "readback_version": readback["version"],
                     "readback_sha256_matches_corrected": readback["sha256"] == digest(corrected_page),
                     "old_version_preserved": (
                         old_readback["version"] == 1 and
                         "Controlled pilot correction." not in old_readback["page"]["body"] and
                         "Controlled pilot correction." not in json.dumps(old_readback["page"].get("raw_capture", {}), ensure_ascii=False))}
    result = {"run": "phase2-workspace-pilot-v1", "source_scope": "private_authorized",
              "actor": actor, "input_sha256": input_sha256,
              "requests_sha256": hashlib.sha256(requests_resolved.read_bytes()).hexdigest(),
              "code_sha256": {name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
                              for name in ("scripts/evaluate_workspace_pilot.py", "src/context_lab/workspace.py")},
              "page_count": len(pages), "candidate_pages": candidate_pages,
              "request_count": len(requests), "controlled_change_simulation": True,
              "arms": arms, "local_reads": local_reads, "lifecycle": lifecycle,
              "timings": timings,
              "notion_network_measured": False, "model_quality_scored": False,
              "public_repo_input_output_rejected": True,
              "native_capture_available": all("raw_capture" in source["page"] for source in source_pages),
              "native_capture_reason": "raw_capture absent in input; native connector arm skipped" if not all(
                  "raw_capture" in source["page"] for source in source_pages) else "available"}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, stat.S_IRUSR | stat.S_IWUSR)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--candidate-pages", type=int, default=3)
    args = parser.parse_args()
    result = run(args.pages, args.requests, args.output, actor=args.actor,
                 candidate_pages=args.candidate_pages)
    print(json.dumps({"status": "ok", "page_count": result["page_count"],
                      "request_count": result["request_count"],
                      "arm_count": len(result["arms"]), "output_written": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
