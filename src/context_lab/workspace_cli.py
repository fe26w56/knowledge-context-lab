"""Command line interface for the local knowledge workspace.

The CLI is deliberately JSON-in/JSON-out so it can be used by a shell agent or
human without a second wire format.  It does not read credentials or start a
network listener.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .workspace import Workspace, notion_pages
from .observations import ObservationSink
from .handoff_delta import make_update, snapshot_digest
from .snapshot import read_snapshot


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

    handoff = sub.add_parser("handoff")
    handoff.add_argument("--base", help="private checkpoint acknowledged by the reader")
    handoff.add_argument("--next", required=True, dest="next_checkpoint", help="new private checkpoint path")
    handoff.add_argument("--scope", choices=("shared", "private"), default="shared")
    handoff.add_argument("--authorized-view", help="complete trusted current visible-page manifest JSON")
    return p


def _db_identity(path: str | Path) -> str:
    resolved = str(Path(path).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _handoff_pages(workspace: Workspace, actor: str, scope: str,
                   authorized_view: str | None = None) -> dict[str, str]:
    pages = {}
    for record in read_snapshot(workspace.store, actor=actor)["records"]:
        content = record.get("content", {})
        if record["scope"] != scope or content.get("kind") != "source":
            continue
        page = content["page"]
        if page.get("scope") != scope or (scope == "private" and record.get("owner") != actor):
            raise ValueError("source scope conflicts with the authorized record")
        page_id = page["id"]
        pages["body/" + page_id] = page["body"]
        pages["metadata/" + page_id] = json.dumps(
            {"title": page["title"], "version": record["version"], "revision_id": record["revision_id"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if authorized_view is None:
        return pages
    manifest = _read_json(authorized_view)
    if (not isinstance(manifest, dict) or manifest.get("actor") != actor or
            manifest.get("scope") != scope or manifest.get("complete") is not True or
            not isinstance(manifest.get("pages"), list)):
        raise ValueError("authorized view must be a complete actor/scope manifest")
    visible: dict[str, dict[str, str]] = {}
    for item in manifest["pages"]:
        if not isinstance(item, dict):
            raise ValueError("authorized view contains an invalid page")
        page_id, title, body_sha = item.get("id"), item.get("title"), item.get("body_sha256")
        if (not isinstance(page_id, str) or not page_id or not isinstance(title, str) or
                not isinstance(body_sha, str) or len(body_sha) != 64 or
                any(char not in "0123456789abcdef" for char in body_sha.lower())):
            raise ValueError("authorized view contains an incomplete page")
        if page_id in visible:
            raise ValueError("authorized view contains duplicate page IDs")
        visible[page_id] = {"title": title, "body_sha256": body_sha}
    local_ids = {key[5:] for key in pages if key.startswith("body/")}
    for page_id, expected in visible.items():
        if page_id not in local_ids:
            raise ValueError("authorized view includes a page not imported locally")
        body = pages["body/" + page_id]
        metadata = json.loads(pages["metadata/" + page_id])
        if (metadata.get("title") != expected["title"] or
                hashlib.sha256(body.encode("utf-8")).hexdigest() != expected["body_sha256"]):
            raise ValueError("authorized view differs from the local imported page")
    # The manifest is the complete visible set.  Omitted locally-imported pages
    # are intentionally removed so a lost authorization cannot leak old text.
    return {key: value for page_id in visible for key in ("body/" + page_id, "metadata/" + page_id)
            for value in (pages[key],)}


def _read_checkpoint(path: str, *, actor: str, db_identity: str, scope: str):
    try:
        data = _read_json(path)
        if (data["schema_version"] != 3 or data["actor"] != actor or
                data["db_identity"] != db_identity or data["scope"] != scope):
            return None, None, "checkpoint_identity_mismatch"
        pages, head = data["pages"], data["head"]
        if head != snapshot_digest(pages, principal=actor, scope=scope):
            return None, None, "checkpoint_head_mismatch"
        return pages, head, "accepted"
    except (OSError, KeyError, TypeError, ValueError):
        return None, None, "checkpoint_unreadable"


def _write_checkpoint(path: str, data: dict) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False,
                                         encoding="utf-8") as handle:
            temp = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, target)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> Any:
    if args.command == "restore":
        bundle = _read_json(args.input)
        Workspace.restore_bundle(bundle, args.destination)
        return {"restored": str(Path(args.destination).resolve())}

    observer = ObservationSink(args.observe_dir, kind=args.observation_kind) if args.observe_dir else None
    ws = Workspace(args.db, observer=observer)
    if args.command == "handoff":
        current = _handoff_pages(ws, args.actor, args.scope, args.authorized_view)
        db_identity = _db_identity(args.db)
        previous = expected_base = None
        base_status = "fresh_snapshot"
        if args.base:
            previous, expected_base, base_status = _read_checkpoint(
                args.base, actor=args.actor, db_identity=db_identity, scope=args.scope)
            if previous is None:
                base_status = "fresh_snapshot:" + base_status
        packet = make_update(previous, current, principal=args.actor, scope=args.scope, expected_base=expected_base)
        checkpoint = {"schema_version": 3, "actor": args.actor, "scope": args.scope,
                      "db_identity": db_identity, "head": packet["head"], "pages": current}
        _write_checkpoint(args.next_checkpoint, checkpoint)
        return {"packet": packet, "base_status": base_status}

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
