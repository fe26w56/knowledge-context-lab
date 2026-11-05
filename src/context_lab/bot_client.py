"""Durable local MCP bridge and unattended poller for a shared Notion hub."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time

from .hub_service import private_read, validate_url


class RemoteHub:
    def __init__(self, url: str, token: str):
        validate_url(url)
        self.url, self.token = url, token

    async def acall(self, name: str, arguments: dict) -> dict:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client, httpx2
        from .bot_receiver import RemoteToolError
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + self.token}, timeout=180,
                                     follow_redirects=False) as http:
            async with streamable_http_client(self.url, http_client=http) as streams:
                async with ClientSession(streams[0], streams[1], read_timeout_seconds=180) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
        # Decode after transport task groups exit so a deliberate tool rejection
        # remains distinguishable from an ExceptionGroup caused by network loss.
        if result.is_error:
            raise RemoteToolError("remote tool rejected the request")
        value = result.structured_content
        if value is None:
            texts = [entry.text for entry in result.content if entry.type == "text"]
            if len(texts) != 1:
                raise ValueError("invalid tool response")
            value = json.loads(texts[0])
        if not isinstance(value, dict):
            raise ValueError("invalid tool result")
        return value

    def call(self, name: str, arguments: dict) -> dict:
        import anyio
        return anyio.run(self.acall, name, arguments)


class BotClient:
    def __init__(self, config_path: Path, *, remote=None):
        from .bot_receiver import BotReceiver
        config_path = config_path.expanduser().resolve()
        config = json.loads(private_read(config_path))
        self.remote = remote or RemoteHub(config["url"], config["token"])
        identity = self.remote.call("identity", {})
        state = Path(config.get("state_dir", "state"))
        if not state.is_absolute():
            state = config_path.parent / state
        self.receiver = BotReceiver(state, source=identity["source"], actor=identity["actor"],
                                    reader=identity["reader"], scope=identity["scope"], call=self.remote.call)
        self.identity = identity

    def sync_page(self, page_id: str, fresh: bool = False) -> dict:
        return self.receiver.sync(page_id, fresh=fresh)

    def get_page(self, page_id: str) -> dict:
        """Check current access before returning a cached body to a fresh model context."""
        result = self.receiver.sync(page_id)
        pages = self.receiver.local_page(page_id)
        body = pages.get("body/" + page_id) if pages else None
        return {"page_id": page_id, "head": result["head"], "markdown": body,
                "sha256": hashlib.sha256(body.encode()).hexdigest() if body is not None else None}

    def sync_hub(self) -> dict:
        tree = self.remote.call("discover", {})
        if tree.get("complete") is not True or not isinstance(tree.get("pages"), list):
            raise ValueError("incomplete hub listing; no bulk reconciliation performed")
        current = {entry["page_id"] for entry in tree["pages"]}
        # Also recheck previously retained pages which are no longer in the tree.
        # Their authoritative current() response, not a missing list entry,
        # decides whether to purge the local copy.
        result = self.sync_pages(list(current | set(self.receiver.known_pages())))
        result.pop("count")
        return {**result, "discovered": len(current)}

    def sync_pages(self, page_ids: list[str]) -> dict:
        """Refresh only explicitly assigned pages, preserving per-page isolation."""
        unique = sorted(set(page_ids))
        changed, failed = [], []
        for page_id in unique:
            try:
                result = self.receiver.sync(page_id)
                if result["changed"]:
                    changed.append(page_id)
            except Exception:
                failed.append(page_id)
        return {"complete": not failed, "count": len(unique), "changed": changed, "failed": failed}

    def dispatch(self, name: str, arguments: dict):
        if name in {"sync_page", "get_page", "sync_hub"}:
            return getattr(self, name)(**arguments)
        if name in {"discover", "create_page", "replace_text", "write_status"}:
            return self.remote.call(name, arguments)
        raise ValueError("unknown tool")


def stdio_server(client: BotClient):
    import anyio
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    server = MCPServer("knowledge-context-bot", instructions=(
        "sync_page stores and applies changes automatically. Use get_page when starting a fresh model context; "
        "a durable local copy does not mean the model has read it. Inspect uncertain write_status before any new write."))

    async def invoke(name, args):
        try:
            return await anyio.to_thread.run_sync(lambda: client.dispatch(name, args))
        except Exception:
            raise ToolError("Operation failed; retained state is preserved. Check connectivity and retry reads; inspect write_status before resubmitting writes.") from None

    @server.tool(structured_output=False)
    async def discover() -> dict:
        """List currently accessible pages under this bot's configured hub roots."""
        return await invoke("discover", {})

    @server.tool(structured_output=False)
    async def sync_page(page_id: str, fresh: bool = False) -> dict:
        """Apply and durably save a page delta, then acknowledge it. Use get_page for full context."""
        return await invoke("sync_page", dict(page_id=page_id, fresh=fresh))

    @server.tool(structured_output=False)
    async def get_page(page_id: str) -> dict:
        """Refresh access and return the full saved page for a model that has not read it."""
        return await invoke("get_page", dict(page_id=page_id))

    @server.tool(structured_output=False)
    async def sync_hub() -> dict:
        """Discover and persist all allowed descendants; return counts and changed IDs, not all bodies."""
        return await invoke("sync_hub", {})

    @server.tool(structured_output=False)
    async def create_page(parent_id: str, title: str, markdown: str, request_id: str) -> dict:
        """Create a page under an allowed parent, using a stable request ID for recovery."""
        return await invoke("create_page", dict(parent_id=parent_id, title=title, markdown=markdown, request_id=request_id))

    @server.tool(structured_output=False)
    async def replace_text(page_id: str, expected_sha256: str, old_text: str, new_text: str, request_id: str) -> dict:
        """Replace a unique exact span using the hash returned by get_page; preserve unrelated content."""
        return await invoke("replace_text", dict(page_id=page_id, expected_sha256=expected_sha256,
                                                 old_text=old_text, new_text=new_text, request_id=request_id))

    @server.tool(structured_output=False)
    async def write_status(request_id: str) -> dict:
        """Query a previously submitted write without repeating it."""
        return await invoke("write_status", dict(request_id=request_id))
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="context-lab-bot")
    parser.add_argument("--config", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp")
    sub.add_parser("discover")
    sync = sub.add_parser("sync")
    sync.add_argument("--page")
    watch = sub.add_parser("watch")
    watch.add_argument("--interval", type=float, default=60)
    watch.add_argument("--page", action="append", dest="pages", default=[],
                       help="watch a known page without discovering the tree; repeat for other pages")
    read = sub.add_parser("read")
    read.add_argument("page_id")
    args = parser.parse_args(argv)
    os.umask(0o077)
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("httpx2").setLevel(logging.ERROR)
    client = BotClient(args.config)
    if args.command == "mcp":
        stdio_server(client).run(transport="stdio")
        return 0
    if args.command == "watch":
        if args.interval < 5:
            parser.error("watch interval must be at least 5 seconds")
        try:
            while True:
                try:
                    result = client.sync_pages(args.pages) if args.pages else client.sync_hub()
                    print(json.dumps(result), flush=True)
                except Exception:
                    print(json.dumps({"complete": False, "error": "sync_failed_retrying"}), flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0
    if args.command == "discover":
        result = client.remote.call("discover", {})
    elif args.command == "read":
        result = client.get_page(args.page_id)
    else:
        result = client.sync_page(args.page) if args.page else client.sync_hub()
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("complete") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
