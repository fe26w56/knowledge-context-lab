"""Command line interface for the local knowledge workspace.

The CLI is deliberately JSON-in/JSON-out so it can be used by a shell agent or
human without a second wire format.  It does not read credentials or start a
network listener.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .workspace import Workspace, notion_pages
from .observations import ObservationSink


def _json(value: Any) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="context-lab-workspace")
    p.add_argument("--db", required=True, help="new or existing local workspace database")
    p.add_argument("--actor", required=True, help="trusted local caller identity")
    p.add_argument("--observe-dir", help="opt-in redacted local observation directory")
    p.add_argument("--observation-kind", choices=("diagnostic", "operational"), default="diagnostic")
    sub = p.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import-pages")
    imp.add_argument("--input", required=True, help="JSON file containing {pages:[...]}")
    imp.add_argument("--request-id", required=True)
    imp.add_argument("--expected-versions", help="JSON mapping of page IDs to expected current versions")

    search = sub.add_parser("search")
    search.add_argument("request")
    search.add_argument("--mode", choices=("raw", "normalized", "current", "compact", "capture"), default="current")
    search.add_argument("--ranking", choices=("legacy", "overlap", "bm25"), default="legacy")

    context = sub.add_parser("context")
    context.add_argument("request")
    context.add_argument("--coverage", choices=("auto", "all", "ranked"), default="auto")
    context.add_argument("--candidate-pages", type=int, default=6)
    context.add_argument("--ranking", choices=("legacy", "overlap", "bm25"), default="bm25")
    search.add_argument("--candidate-pages", type=int, default=6)

    source = sub.add_parser("source")
    source.add_argument("page_id")
    source.add_argument("--version", type=int)

    topics = sub.add_parser("topics")

    topic = sub.add_parser("topic")
    topic.add_argument("topic_id")
    topic.add_argument("--version", type=int)

    publish = sub.add_parser("publish")
    publish.add_argument("topic_id")
    publish.add_argument("--payload", required=True)
    publish.add_argument("--evidence", required=True)
    publish.add_argument("--expected-version", type=int, required=True)
    publish.add_argument("--request-id", required=True)
    publish.add_argument("--scope", choices=("shared", "private"), default="shared")
    publish.add_argument("--owner")

    export = sub.add_parser("export")
    export.add_argument("--output", help="optional JSON output path; stdout remains the result")

    restore = sub.add_parser("restore")
    restore.add_argument("--input", required=True)
    restore.add_argument("--destination", required=True)
    return p


def run(args: argparse.Namespace) -> Any:
    if args.command == "restore":
        bundle = _read_json(args.input)
        Workspace.restore_bundle(bundle, args.destination)
        return {"restored": str(Path(args.destination).resolve())}

    observer = ObservationSink(args.observe_dir, kind=args.observation_kind) if args.observe_dir else None
    ws = Workspace(args.db, observer=observer)
    if args.command == "import-pages":
        source = _read_json(args.input)
        if isinstance(source, dict) and "snapshots" in source:
            pages = notion_pages(source["snapshots"], owner=args.actor)
        else:
            pages = source.get("pages", source) if isinstance(source, dict) else source
        expected = _read_json(args.expected_versions) if args.expected_versions else None
        return ws.import_pages(pages, actor=args.actor, request_id=args.request_id,
                               expected_versions=expected)
    if args.command == "search":
        return ws.search(args.request, actor=args.actor, mode=args.mode, candidate_pages=args.candidate_pages, ranking=args.ranking)
    if args.command == "context":
        return ws.context(args.request, actor=args.actor, coverage=args.coverage,
                          candidate_pages=args.candidate_pages, ranking=args.ranking)
    if args.command == "source":
        return ws.get_source(args.page_id, actor=args.actor, version=args.version)
    if args.command == "topics":
        return ws.list_topics(actor=args.actor)
    if args.command == "topic":
        return ws.get_topic(args.topic_id, actor=args.actor, version=args.version)
    if args.command == "publish":
        payload = _read_json(args.payload)
        evidence = _read_json(args.evidence)
        return ws.publish_topic(args.topic_id, payload, evidence, actor=args.actor,
                                expected_version=args.expected_version,
                                request_id=args.request_id, scope=args.scope, owner=args.owner)
    if args.command == "export":
        result = ws.export_bundle(actor=args.actor)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        result = run(parser.parse_args(argv))
        _json(result)
        return 0
    except Exception as exc:  # concise CLI error; library keeps typed exception
        sys.stderr.write(f"error: {type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
