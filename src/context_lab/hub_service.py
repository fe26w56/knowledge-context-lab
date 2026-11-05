"""Authenticated shared Notion handoffs over Streamable HTTP MCP.

Machine credentials are provisioned by the operator, one per durable reader.
This is a single-instance service with a persistent local volume, not an OAuth
authorization server or a distributed SQLite deployment.
"""
from __future__ import annotations

import argparse
from contextvars import ContextVar
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit
from uuid import UUID

from .reader_handoff import ReaderHandoff


def private_read(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        if os.fstat(stream.fileno()).st_mode & 0o077:
            raise ValueError("credential/config file must have mode 0600")
        return stream.read()


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("state directory must be private (mode 0700), without symlinks")
    return path


def validate_url(url: str):
    parsed = urlsplit(url)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/mcp"):
        raise ValueError("server URL must be an absolute /mcp endpoint without credentials or query")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("remote bot connections require HTTPS")
    return parsed


class WriteJournal:
    """Commit an intent before touching Notion; never replay uncertain writes."""

    def __init__(self, directory: Path):
        self.path = private_dir(directory) / "writes.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS writes (reader TEXT, request_id TEXT, fingerprint TEXT, status TEXT, result TEXT, PRIMARY KEY(reader,request_id))")

    def status(self, reader: str, request_id: str) -> dict:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT status,result FROM writes WHERE reader=? AND request_id=?", (reader, request_id)).fetchone()
        if row is None:
            return {"status": "unknown", "request_id": request_id}
        return {"status": row[0], "request_id": request_id, "result": json.loads(row[1]) if row[1] else None}

    def execute(self, reader: str, request_id: str, operation: str, arguments: dict, action) -> dict:
        from .notion_hub import WriteRejected, WriteUncertain
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("request_id must contain 1 to 128 characters")
        fingerprint = hashlib.sha256(json.dumps([operation, arguments], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with closing(sqlite3.connect(self.path, timeout=120)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT fingerprint,status,result FROM writes WHERE reader=? AND request_id=?", (reader, request_id)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ValueError("request_id already belongs to different write arguments")
                return self.status(reader, request_id)
            db.execute("INSERT INTO writes VALUES (?,?,?,?,NULL)", (reader, request_id, fingerprint, "uncertain"))
        # Serialize writes across threads/processes on this volume. The intent is
        # already durable if this process dies at any point in the HTTP request.
        with closing(sqlite3.connect(self.path, timeout=120)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            status = "completed"
            try:
                result = action()
            except WriteRejected as exc:
                status, result = "rejected", {"reason": str(exc)}
            except WriteUncertain as exc:
                status, result = "uncertain", {"page_id": exc.page_id, "instruction": "Inspect this page before any new write."}
            except Exception:
                status, result = "uncertain", {"instruction": "Inspect Notion before submitting another write. This request will not be replayed."}
            db.execute("UPDATE writes SET status=?,result=? WHERE reader=? AND request_id=?",
                       (status, json.dumps(result, ensure_ascii=False), reader, request_id))
        return {"status": status, "request_id": request_id, "result": result}


class HubService:
    def __init__(self, config: dict, *, gateway_factory=None):
        from .notion_hub import NotionHub, RateLimiter
        self.config = config
        self.url = validate_url(config["public_url"])
        self.source = config["source"]
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("stable source identifier required")
        self.state = private_dir(Path(config["state_dir"]))
        self.journal = WriteJournal(self.state)
        token = private_read(Path(config["token_file"])).strip() if gateway_factory is None else None
        self.bots = {}
        limiter = RateLimiter()
        identities = set()
        for raw in config["bots"]:
            bot = dict(raw)
            digest = bot["token_sha256"]
            if (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                    or digest in self.bots or not bot["reader"] or not bot["actor"]
                    or bot["reader"] in identities or type(bot.get("write", False)) is not bool):
                raise ValueError("each bot requires a unique reader, credential digest, and boolean write policy")
            identities.add(bot["reader"])
            bot["roots"] = sorted({str(UUID(value)) for value in bot["roots"]})
            if not bot["roots"]:
                raise ValueError("each bot requires at least one allowed root")
            gateway = gateway_factory(bot["roots"]) if gateway_factory else NotionHub(token=token, roots=bot["roots"], limiter=limiter)
            bot["gateway"] = gateway
            bot["handoff"] = ReaderHandoff(self.state / "readers", source=self.source, actor=bot["actor"],
                                            reader=bot["reader"], scope="shared", current=gateway.current)
            self.bots[digest] = bot
        if not self.bots:
            raise ValueError("at least one bot credential is required")

    def authenticate(self, token: str) -> dict | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        for expected, bot in self.bots.items():
            if hmac.compare_digest(digest, expected):
                return bot
        return None

    def dispatch(self, bot: dict, name: str, arguments: dict) -> dict:
        if name == "identity":
            if arguments:
                raise ValueError("identity accepts no arguments")
            return {"source": self.source, "actor": bot["actor"], "reader": bot["reader"], "scope": "shared",
                    "roots": bot["roots"], "write": bot.get("write", False)}
        if name == "discover":
            if arguments:
                raise ValueError("discover accepts no arguments")
            return {"pages": bot["gateway"].discover(), "complete": True}
        if name == "read_changes":
            return bot["handoff"].read(**arguments)
        if name == "ack_changes":
            return bot["handoff"].acknowledge(**arguments)
        if name == "write_status":
            return self.journal.status(bot["reader"], **arguments)
        if name not in {"create_page", "replace_text"}:
            raise ValueError("unknown tool")
        if not bot.get("write", False):
            raise ValueError("this bot is read-only")
        arguments = dict(arguments)
        request_id = arguments.pop("request_id")
        method = getattr(bot["gateway"], name)
        return self.journal.execute(bot["reader"], request_id, name, arguments, lambda: method(**arguments))


def create_app(service: HubService):
    import anyio
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import JSONResponse

    principal = ContextVar("hub_bot", default=None)
    server = MCPServer("knowledge-context-hub", instructions="Use per-page deltas and durable bot-side application before acknowledgement.")

    async def call(name, args):
        bot = principal.get()
        if bot is None:
            raise ToolError("authenticated bot identity required")
        try:
            return await anyio.to_thread.run_sync(lambda: service.dispatch(bot, name, args))
        except (ValueError, TypeError, KeyError):
            raise ToolError("Request rejected; check arguments, scope, source state, or request_id.") from None
        except Exception:
            raise ToolError("Upstream unavailable; no successful delivery claimed.") from None

    @server.tool(structured_output=False)
    async def identity() -> dict:
        """Return the identity and roots bound to this machine credential."""
        return await call("identity", {})

    @server.tool(structured_output=False)
    async def discover() -> dict:
        """List true descendant pages under allowed roots; failure never means an empty successful tree."""
        return await call("discover", {})

    @server.tool(structured_output=False)
    async def read_changes(page_id: str, fresh: bool = False) -> dict:
        """Get changes since this bot last durably acknowledged this page."""
        return await call("read_changes", {"page_id": page_id, "fresh": fresh})

    @server.tool(structured_output=False)
    async def ack_changes(page_id: str, receipt: str, head: str) -> dict:
        """Acknowledge only after the bot has reconstructed, verified and saved the page."""
        return await call("ack_changes", {"page_id": page_id, "receipt": receipt, "head": head})

    @server.tool(structured_output=False)
    async def create_page(parent_id: str, title: str, markdown: str, request_id: str) -> dict:
        """Create a child page. Reuse request_id on retry; uncertain writes require inspection."""
        return await call("create_page", dict(parent_id=parent_id, title=title, markdown=markdown, request_id=request_id))

    @server.tool(structured_output=False)
    async def replace_text(page_id: str, expected_sha256: str, old_text: str, new_text: str, request_id: str) -> dict:
        """Replace one exact unique span after checking the current body hash. External editor races can still conflict."""
        return await call("replace_text", dict(page_id=page_id, expected_sha256=expected_sha256, old_text=old_text, new_text=new_text, request_id=request_id))

    @server.tool(structured_output=False)
    async def write_status(request_id: str) -> dict:
        """Recover the outcome of a write without submitting it again."""
        return await call("write_status", {"request_id": request_id})

    origin = f"{service.url.scheme}://{service.url.netloc}"
    app = server.streamable_http_app(stateless_http=True, json_response=True,
                                    transport_security=TransportSecuritySettings(allowed_hosts=[service.url.netloc], allowed_origins=[origin]))

    class Auth:
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await app(scope, receive, send)
            headers = scope.get("headers", [])
            auth = [value for key, value in headers if key.lower() == b"authorization"]
            bot = None
            if len(auth) == 1 and auth[0].startswith(b"Bearer "):
                try:
                    bot = service.authenticate(auth[0][7:].decode("ascii"))
                except UnicodeError:
                    pass
            if bot is None:
                return await JSONResponse({"error": "authentication_required"}, status_code=401,
                                          headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
            state = principal.set(bot)
            try:
                await app(scope, receive, send)
            finally:
                principal.reset(state)

    return Auth()


def initialize(directory: Path, token_file: Path, roots: list[str], url: str, count: int):
    validate_url(url)
    if not 1 <= count <= 256:
        raise ValueError("bots must be between 1 and 256")
    directory = directory.expanduser().resolve()
    package_root = Path(__file__).resolve().parent.parent
    # Source checkout: <repo>/src/context_lab. Wheel: <install>/context_lab.
    if package_root.name == "src" and (package_root.parent / "pyproject.toml").is_file():
        package_root = package_root.parent
    if directory.is_relative_to(package_root):
        raise ValueError("keep server and bot credentials outside the source repository")
    token_file = token_file.expanduser().resolve()
    if not token_file.is_file() or token_file.stat().st_mode & 0o077:
        raise ValueError("create a private Notion token file before initializing the hub")
    roots = [str(UUID(value)) for value in roots]
    if not roots:
        raise ValueError("at least one allowed root is required")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_dir(directory)
    def write_config(path: Path, value: dict):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2)
    config = {"source": "notion:" + secrets.token_hex(16), "public_url": url, "token_file": str(token_file),
              "state_dir": str(directory / "server-state"), "bots": []}
    for index in range(1, count + 1):
        reader = f"bot-{index:02}"
        token = secrets.token_urlsafe(32)
        config["bots"].append({"reader": reader, "actor": reader, "roots": roots,
                               "write": False, "token_sha256": hashlib.sha256(token.encode()).hexdigest()})
        destination = private_dir(directory / reader)
        write_config(destination / "client.json", {"url": url, "token": token, "state_dir": "state"})
    write_config(directory / "server.json", config)
    print(f"Created server.json and {count} private bot folders in {directory}. Credentials were not printed.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="context-lab-hub")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("init")
    setup.add_argument("--directory", type=Path, required=True)
    setup.add_argument("--token-file", type=Path, required=True)
    setup.add_argument("--root", action="append", required=True)
    setup.add_argument("--url", required=True)
    setup.add_argument("--bots", type=int, default=16)
    serve = sub.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.command == "init":
        initialize(args.directory, args.token_file, args.root, args.url, args.bots)
    else:
        import uvicorn
        config = json.loads(private_read(args.config))
        uvicorn.run(create_app(HubService(config)), host=args.host, port=args.port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
