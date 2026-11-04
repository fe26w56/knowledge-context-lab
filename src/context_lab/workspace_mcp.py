"""Minimal stdio JSON-RPC MCP adapter for the local workspace.

Only stdin/stdout are used for protocol messages.  This is a trusted local
adapter; authentication and remote transport are intentionally out of scope.
"""
from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path
import sys
from typing import Any

from .workspace import Workspace
from .store import StoreError, ValidationError
from .observations import ObservationSink
from .reader_handoff import ReaderHandoff
from .notion_reader import NotionPages
from .workspace_cli import _handoff_pages

PROTOCOL = "2025-11-25"
TOOLS = {
    "search": "Search visible imported source pages",
    "context": "Return full-body source context under an explicit coverage policy",
    "import_pages": "Import or update source pages with explicit version checks",
    "get_source": "Read an imported source page or version",
    "list_topics": "List visible topic records",
    "get_topic": "Read a topic record",
    "publish_topic": "Write an explicitly reviewed topic record",
    "export_bundle": "Export a portable workspace bundle",
}
READER_TOOLS = {
    "read_changes": {
        "description": "Read one page since this reader last acknowledged it. Request fresh if your retained copy is missing.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["page_id"],
                        "properties": {"page_id": {"type": "string"}, "fresh": {"type": "boolean"}}}},
    "ack_changes": {
        "description": "After retaining and verifying the packet, acknowledge its receipt and reconstructed head.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["page_id", "receipt", "head"],
                        "properties": {"page_id": {"type": "string"}, "receipt": {"type": "string"}, "head": {"type": "string"}}}},
}


def _result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}], "structuredContent": value}


def _error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tools() -> list[dict[str, Any]]:
    return [
        {"name": "search", "description": TOOLS["search"], "inputSchema": {"type": "object", "additionalProperties": False, "required": ["request"], "properties": {"request": {"type": "string"}, "mode": {"type": "string", "enum": ["raw", "normalized", "current", "compact", "capture"]}, "candidate_pages": {"type": "integer"}, "ranking": {"type": "string", "enum": ["legacy", "overlap", "bm25"]}}}},
        {"name": "context", "description": TOOLS["context"], "inputSchema": {"type": "object", "additionalProperties": False, "required": ["request"], "properties": {"request": {"type": "string"}, "coverage": {"type": "string", "enum": ["auto", "all", "ranked"]}, "candidate_pages": {"type": "integer"}, "ranking": {"type": "string", "enum": ["legacy", "overlap", "bm25"]}}}},
        {"name": "import_pages", "description": TOOLS["import_pages"], "inputSchema": {"type": "object", "additionalProperties": False, "required": ["pages", "request_id"], "properties": {"pages": {"type": "array", "items": {"type": "object"}}, "request_id": {"type": "string"}, "expected_versions": {"type": "object", "additionalProperties": {"type": "integer"}}}}},
        {"name": "get_source", "description": TOOLS["get_source"], "inputSchema": {"type": "object", "additionalProperties": False, "required": ["page_id"], "properties": {"page_id": {"type": "string"}, "version": {"type": "integer"}}}},
        {"name": "list_topics", "description": TOOLS["list_topics"], "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
        {"name": "get_topic", "description": TOOLS["get_topic"], "inputSchema": {"type": "object", "additionalProperties": False, "required": ["topic_id"], "properties": {"topic_id": {"type": "string"}, "version": {"type": "integer"}}}},
        {"name": "publish_topic", "description": TOOLS["publish_topic"], "inputSchema": {"type": "object", "additionalProperties": False, "required": ["topic_id", "payload", "evidence", "expected_version", "request_id"], "properties": {"topic_id": {"type": "string"}, "payload": {"type": "object", "required": ["title", "summary", "conditions", "state", "as_of", "task_refs"], "properties": {"title": {"type": "string"}, "summary": {"type": "string"}, "conditions": {"type": "array", "items": {"type": "string"}}, "state": {"type": "string", "enum": ["proposed", "adopted", "reference", "superseded"]}, "as_of": {"type": "string"}, "task_refs": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": True}, "evidence": {"type": "array", "items": {"type": "object"}}, "expected_version": {"type": "integer"}, "request_id": {"type": "string"}, "scope": {"type": "string", "enum": ["shared", "private"]}, "owner": {"type": "string"}}}},
        {"name": "export_bundle", "description": TOOLS["export_bundle"], "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    ]


def dispatch(method: str, params: dict[str, Any], workspace: Workspace) -> Any:
    if params.pop("__actor_conflict", False):
        raise ValueError("actor is process configuration, not a tool argument")
    actor = params.pop("actor", None)
    if not isinstance(actor, str) or not actor:
        raise ValueError("actor is required for local MCP calls")
    if method == "search":
        request = params.pop("request")
        mode = params.pop("mode", "current")
        candidate_pages = params.pop("candidate_pages", 6)
        ranking = params.pop("ranking", "legacy")
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.search(request, actor=actor, mode=mode, candidate_pages=candidate_pages, ranking=ranking)
    if method == "context":
        request = params.pop("request")
        coverage = params.pop("coverage", "auto")
        candidate_pages = params.pop("candidate_pages", 6)
        ranking = params.pop("ranking", "bm25")
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.context(request, actor=actor, coverage=coverage,
                                candidate_pages=candidate_pages, ranking=ranking)
    if method == "import_pages":
        pages = params.pop("pages")
        request_id = params.pop("request_id")
        expected_versions = params.pop("expected_versions", None)
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.import_pages(pages, actor=actor, request_id=request_id,
                                      expected_versions=expected_versions)
    if method == "get_source":
        page_id = params.pop("page_id")
        version = params.pop("version", None)
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.get_source(page_id, actor=actor, version=version)
    if method == "list_topics":
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.list_topics(actor=actor)
    if method == "get_topic":
        topic_id = params.pop("topic_id")
        version = params.pop("version", None)
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.get_topic(topic_id, actor=actor, version=version)
    if method == "publish_topic":
        topic_id = params.pop("topic_id")
        payload = params.pop("payload")
        evidence = params.pop("evidence")
        expected_version = params.pop("expected_version")
        request_id = params.pop("request_id")
        scope = params.pop("scope", "shared")
        owner = params.pop("owner", None)
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.publish_topic(topic_id, payload, evidence, actor=actor, expected_version=expected_version, request_id=request_id, scope=scope, owner=owner)
    if method == "export_bundle":
        if params:
            raise ValueError(f"unknown arguments: {', '.join(sorted(params))}")
        return workspace.export_bundle(actor=actor)
    raise ValueError(f"unknown tool: {method}")


def handle(message: dict[str, Any], workspace: Workspace | None, *, initialized: bool = False,
           reader: ReaderHandoff | None = None) -> dict[str, Any] | None:
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(-32600, "invalid JSON-RPC request", message.get("id"))
    request_id = message.get("id")
    if request_id is None:  # notification
        return None
    method = message["method"]
    try:
        if method == "initialize":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("initialize params must be an object")
            requested = params.get("protocolVersion")
            supported = {PROTOCOL, "2025-06-18", "2024-11-05"}
            negotiated = requested if requested in supported else PROTOCOL
            return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": negotiated, "capabilities": {"tools": {}}, "serverInfo": {"name": "knowledge-context-lab", "version": version("knowledge-context-lab")}}}
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            tools = _tools() if reader is None else [{"name": k, **v} for k, v in READER_TOOLS.items()]
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
        if method == "tools/call":
            params = dict(message.get("params") or {})
            name = params.pop("name", "")
            arguments = params.pop("arguments", {})
            if params or not isinstance(arguments, dict) or name not in (READER_TOOLS if reader else TOOLS):
                raise ValueError("invalid tool call")
            if reader is not None:
                action = reader.read if name == "read_changes" else reader.acknowledge
                try:
                    text = json.dumps(action(**arguments), ensure_ascii=False)
                    result = {"content": [{"type": "text", "text": text}]}
                except (OSError, ValueError) as exc:
                    result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
                return {"jsonrpc": "2.0", "id": request_id, "result": result}
            assert workspace is not None
            try:
                value = dispatch(name, arguments, workspace)
            except StoreError as exc:
                if isinstance(exc, ValidationError):
                    raise
                return {"jsonrpc": "2.0", "id": request_id, "result": {**_result({"error": str(exc)}), "isError": True}}
            return {"jsonrpc": "2.0", "id": request_id, "result": _result(value)}
        raise ValueError(f"unknown method: {method}")
    except Exception as exc:
        return _error(-32602 if method in {"tools/call", "initialize"} else -32601, str(exc), request_id)


def main(argv: list[str] | None = None) -> int:
    # Configuration is passed as process arguments, never per-tool secret data.
    import argparse
    p = argparse.ArgumentParser(prog="context-lab-workspace-mcp")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--db")
    source.add_argument("--notion-page", action="append", help="allowed Notion page UUID; repeat per page")
    p.add_argument("--actor", required=True)
    p.add_argument("--reader", help="stable agent/consumer identity; exposes only the handoff tools")
    p.add_argument("--handoff-state", type=Path, help="private directory for durable reader receipts")
    p.add_argument("--notion-workspace", help="stable workspace identifier for Notion receipt isolation")
    p.add_argument("--authorized-view", help="trusted complete manifest for an imported workspace")
    p.add_argument("--scope", choices=("shared", "private"), default="shared")
    p.add_argument("--observe-dir")
    p.add_argument("--observation-kind", choices=("diagnostic", "operational"), default="diagnostic")
    args = p.parse_args(argv)
    if bool(args.reader) != bool(args.handoff_state):
        p.error("--reader and --handoff-state are required together")
    if args.notion_page and not (args.reader and args.notion_workspace):
        p.error("--notion-page requires --reader, --handoff-state and --notion-workspace")
    if args.authorized_view and not (args.db and args.reader):
        p.error("--authorized-view applies only to imported workspace reader mode")
    if args.notion_workspace and not args.notion_page:
        p.error("--notion-workspace requires --notion-page")
    observer = ObservationSink(args.observe_dir, kind=args.observation_kind) if args.observe_dir else None
    ws = Workspace(args.db, observer=observer) if args.db else None
    reader = None
    if args.reader:
        if ws is None:
            source_id = "notion:" + args.notion_workspace
            try:
                current = NotionPages(args.notion_page)
            except ValueError as exc:
                p.error(str(exc))
        else:
            source_id = "workspace:" + str(ws.store.path)
            def current(page_id):
                visible = _handoff_pages(ws, args.actor, args.scope, args.authorized_view)
                return {k: visible[k] for k in ("body/" + page_id, "metadata/" + page_id) if k in visible}
        reader = ReaderHandoff(args.handoff_state, source=source_id, actor=args.actor,
                               reader=args.reader, scope=args.scope, current=current)
    initialized = False
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            # Bind configured actor; a caller cannot override it in arguments.
            if reader is None and isinstance(message.get("params"), dict):
                message["params"] = dict(message["params"])
                if message.get("method") == "tools/call":
                    call_args = message["params"].get("arguments")
                    if not isinstance(call_args, dict):
                        call_args = {}
                    else:
                        call_args = dict(call_args)
                    # The process-level identity is authoritative; a tool
                    # argument cannot impersonate another local caller.
                    if "actor" in call_args:
                        call_args["__actor_conflict"] = True
                    call_args["actor"] = args.actor
                    message["params"]["arguments"] = call_args
                else:
                    message["params"]["actor"] = args.actor
            if message.get("method") not in {"initialize", "ping", "notifications/initialized"} and not initialized:
                response = _error(-32002, "initialize is required before tools", message.get("id"))
            else:
                response = handle(message, ws, initialized=initialized, reader=reader)
            if message.get("method") == "initialize" and response and "result" in response:
                initialized = True
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps(_error(-32700, str(exc)), separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
