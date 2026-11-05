"""Bounded live Notion acceptance test for the shared Hub service.

The command creates only a fresh synthetic test page below the operator-supplied
root. It never edits or deletes an existing page. Credentials and receipts stay
outside the source tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from uuid import UUID

from context_lab.bot_client import BotClient
from context_lab.bot_receiver import BotReceiver
from context_lab.handoff_delta import make_update, snapshot_digest
from context_lab.hub_service import HubService, create_app, private_read
from context_lab.notion_hub import NotionHub


REPO = Path(__file__).resolve().parents[1]
MARKER = "KCL_ACCEPTANCE_MARKER_2026_11_05"


def _canonical_json(value: dict) -> str:
    """The MCP text whose reference-token count is recorded in receipts."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _reference_tokens(value: dict) -> int:
    # Keep this independent of application token helpers: the acceptance
    # receipt is intended to be reproducible with the public tiktoken API.
    import tiktoken
    return len(tiktoken.get_encoding("o200k_base").encode_ordinary(
        _canonical_json(value)))


class _ReadChangesCapture:
    """Remote proxy retaining the exact decoded read_changes envelopes."""
    def __init__(self, remote):
        self.remote = remote
        self.responses: list[dict] = []

    def call(self, name: str, arguments: dict) -> dict:
        result = self.remote.call(name, arguments)
        if name == "read_changes":
            if not isinstance(result, dict) or not isinstance(result.get("receipt"), str):
                raise RuntimeError("read_changes returned no durable receipt")
            if result.get("page_id") != arguments.get("page_id"):
                raise RuntimeError("read_changes returned the wrong page")
            self.responses.append(result)
        return result

    def __getattr__(self, name):
        return getattr(self.remote, name)


def _uuid(value: str) -> str:
    result = str(UUID(value))
    if result != value:
        raise ValueError("--root must be a canonical hyphenated UUID")
    return result


def _private_output(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_relative_to(REPO) or path.exists():
        raise ValueError("--output must be a new directory outside the repository")
    path.mkdir(mode=0o700, parents=True)
    if path.stat().st_mode & 0o077:
        raise ValueError("--output parent must be private")
    return path


def _write_private(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


class _MutationReceipt:
    """Durable intent/result journal for every live mutation."""
    def __init__(self, output: Path):
        self.path = output / "mutations.json"
        self.items: list[dict] = []

    def _save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(self.items, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def begin(self, operation: str, request_id: str, arguments: dict) -> None:
        self.items.append({"operation": operation, "request_id": request_id,
                           "arguments": {key: value for key, value in arguments.items()
                                          if key not in {"markdown", "old_text", "new_text"}},
                           "status": "pending"})
        self._save()

    def finish(self, request_id: str, status: str, result: dict | None = None,
               error: str | None = None) -> None:
        for item in reversed(self.items):
            if item["request_id"] == request_id and item["status"] == "pending":
                item["status"] = status
                if isinstance(result, dict):
                    safe = {key: value for key, value in result.items() if key != "markdown"}
                    item["result"] = safe
                if error:
                    item["error"] = error[:240]
                break
        self._save()


def _mutate(journal: _MutationReceipt, operation: str, arguments: dict, action) -> dict:
    request_id = arguments["request_id"]
    journal.begin(operation, request_id, arguments)
    try:
        result = action()
    except Exception as exc:
        journal.finish(request_id, "uncertain", error=type(exc).__name__)
        raise RuntimeError(f"{operation} was uncertain; inspect Notion and mutations.json before retrying") from exc
    status = result.get("status") if isinstance(result, dict) else None
    journal.finish(request_id, status or "uncertain", result if isinstance(result, dict) else None)
    if status != "completed":
        raise RuntimeError(f"{operation} did not complete: {status}")
    return result


def _server(config: dict):
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
    config = dict(config, public_url=url)
    server = uvicorn.Server(uvicorn.Config(create_app(HubService(config)), access_log=False,
                                            log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(5)
        raise RuntimeError("local acceptance server did not start")
    return server, thread, url


def _stop(server, thread):
    server.should_exit = True
    thread.join(15)
    if thread.is_alive():
        raise RuntimeError("local acceptance server did not stop")


def _config(directory: Path, token_file: Path, roots: list[str], *, url: str = "") -> tuple[dict, list[Path]]:
    bots, clients = [], []
    for index in range(16):
        token = secrets.token_urlsafe(32)
        reader = f"acceptance-bot-{index:02}"
        bots.append({"reader": reader, "actor": reader, "roots": roots, "write": index == 0,
                     "token_sha256": hashlib.sha256(token.encode()).hexdigest()})
        path = directory / f"bot-{index:02}" / "client.json"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_private(path, json.dumps({"url": url, "token": token, "state_dir": "state"}))
        clients.append(path)
    return {"source": "notion-live-acceptance", "public_url": url,
            "token_file": str(token_file), "state_dir": str(directory / "server-state"),
            "bots": bots}, clients


def _result_page(result: dict) -> str:
    if result.get("status") != "completed":
        raise RuntimeError(f"page creation did not complete: {result.get('status')}")
    page_id = (result.get("result") or {}).get("page_id")
    if not isinstance(page_id, str):
        raise RuntimeError("page creation returned no page ID")
    return page_id


def _verify_root(token_file: Path, root: str) -> NotionHub:
    """Check root existence/scope without traversing the user's hierarchy."""
    gateway = NotionHub(token=private_read(token_file).strip(), roots=[root])
    if not gateway._allowed(root):  # bounded metadata/access check only
        raise RuntimeError("supplied root is not accessible to the Notion connection")
    return gateway


def _recover_first_create(path: Path, gateway: NotionHub, args: dict) -> dict:
    """Read back the resource recorded by the first failed attempt, without POST."""
    entries = json.loads(private_read(path))
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("recovery requires the isolated first creation receipt")
    entry = entries[0]
    if (entry.get("operation") != "create_page" or entry.get("status") != "uncertain"
            or entry["arguments"].get("parent_id") != args["parent_id"]
            or entry["arguments"].get("title") != args["title"]):
        raise ValueError("receipt does not identify this test creation")
    page_id = _uuid(entry["result"]["result"]["page_id"])
    verified = gateway.verify_created_page(page_id, args["parent_id"], args["title"], args["markdown"])
    return {"original_request_id": entry["request_id"], **verified}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--root", required=True, type=_uuid,
                        help="Agent Hub root UUID; only a new synthetic child is written")
    parser.add_argument("--output", type=Path, required=True,
                        help="new private directory outside this repository")
    parser.add_argument("--recover-first-create", type=Path,
                        help="private mutations.json for a single uncertain test page creation with a known ID")
    args = parser.parse_args(argv)
    token_file = args.token_file.expanduser().resolve()
    if token_file.is_relative_to(REPO) or not token_file.is_file():
        parser.error("--token-file must be an existing file outside the repository")
    output = _private_output(args.output)
    if token_file.stat().st_mode & 0o077:
        parser.error("--token-file must have mode 0600")

    # The token is passed to the gateway only through HubService's private file
    # reader. It is never printed, serialized into receipts, or sent to bots.
    private_dir = output / "server"
    private_dir.mkdir(mode=0o700)
    config, client_paths = _config(private_dir, token_file, [args.root])
    server = thread = None
    created: list[str] = []
    journal = _MutationReceipt(output)
    try:
        server, thread, url = _server(config)
        for path in client_paths:
            data = json.loads(path.read_text())
            data["url"] = url
            path.write_text(json.dumps(data))
            path.chmod(0o600)
        writer = BotClient(client_paths[0])
        # Read-only scope check before any mutation; do not traverse the user's
        # hierarchy just to preflight a root.
        gateway = _verify_root(token_file, args.root)
        body = (f"# Knowledge Context Lab synchronization check\n\n{MARKER}\n\n"
                "Stable line retained across the partial update.\n")
        create_args = {"parent_id": args.root, "title": "Knowledge Context Lab synchronization check",
                       "markdown": body, "request_id": secrets.token_hex(16)}
        if args.recover_first_create:
            recovery = _recover_first_create(args.recover_first_create, gateway, create_args)
            _write_private(output / "reconciled-create.json", json.dumps(recovery))
            created_page = recovery["page_id"]
        else:
            created_page = _result_page(_mutate(journal, "create_page", create_args,
                                                lambda: writer.remote.call("create_page", create_args)))
        created.append(created_page)

        child_args = {"parent_id": created_page, "title": "Synthetic child topic",
                      "markdown": f"# Synthetic child topic\n\n{MARKER}\n",
                      "request_id": secrets.token_hex(16)}
        child = _result_page(_mutate(journal, "create_page", child_args,
                                     lambda: writer.remote.call("create_page", child_args)))
        created.append(child)
        # Notion may normalize the parent while inserting the child-page link.
        # Bind all later byte-level assertions to the authoritative readback,
        # never to the submitted Markdown.
        authoritative = writer.get_page(created_page)
        body = authoritative.get("markdown")
        if not isinstance(body, str):
            raise RuntimeError("created test page readback was incomplete")
        # Apply edits to the exact source returned by Notion's Markdown renderer.
        forms = [MARKER, MARKER.replace("_", r"\_")]
        marker_lines = [line for line in body.splitlines() if line in forms]
        if len(marker_lines) != 1:
            raise RuntimeError("could not identify the original synthetic marker line")
        marker = marker_lines[0]
        updated_marker, final_marker = marker + " updated", marker + " final"
        if "Stable line retained across the partial update." not in body:
            raise RuntimeError("created test page readback lost unrelated content")
        _stop(server, thread)
        server = thread = None

        # Rebind the service to the newly-created test page. This bounds discovery
        # to the test subtree and avoids scanning the user's whole Agent Hub.
        config, client_paths = _config(private_dir / "subtree", token_file, [created_page])
        server, thread, url = _server(config)
        for path in client_paths:
            data = json.loads(path.read_text())
            data["url"] = url
            path.write_text(json.dumps(data))
            path.chmod(0o600)
        # Keep the decoded server envelopes so the receipt can prove the token
        # count from each real page_id/receipt pair, rather than a reconstructed
        # packet or a guessed receipt.
        from context_lab.bot_client import RemoteHub
        captures: list[_ReadChangesCapture] = []
        clients = []
        for path in client_paths:
            config_data = json.loads(path.read_text())
            capture = _ReadChangesCapture(RemoteHub(config_data["url"], config_data["token"]))
            captures.append(capture)
            clients.append(BotClient(path, remote=capture))
        for client in clients[:5]:
            client.sync_page(created_page)
        v1_group = [(client.receiver.local_page(created_page) or {})["body/" + created_page]
                    for client in clients[:5]]
        if v1_group != [body] * 5:
            raise RuntimeError("initial reader group did not share one byte baseline")
        current = clients[0].get_page(created_page)
        preserved = "Stable line retained across the partial update."
        update_args = {
            "page_id": created_page, "expected_sha256": current["sha256"],
            "old_text": marker, "new_text": updated_marker,
            "request_id": secrets.token_hex(16)}
        _mutate(journal, "replace_text", update_args,
                lambda: clients[0].remote.call("replace_text", update_args))
        for client in clients[5:11]:
            client.sync_page(created_page)
        v2_group = [(client.receiver.local_page(created_page) or {})["body/" + created_page]
                    for client in clients[5:11]]
        expected_v2 = body.replace(marker, updated_marker, 1)
        if v2_group != [expected_v2] * 6:
            raise RuntimeError("updated reader group did not share one byte baseline")
        current = clients[5].get_page(created_page)
        update_args = {
            "page_id": created_page, "expected_sha256": current["sha256"],
            "old_text": updated_marker, "new_text": final_marker,
            "request_id": secrets.token_hex(16)}
        _mutate(journal, "replace_text", update_args,
                lambda: clients[0].remote.call("replace_text", update_args))
        # Check the actual durable baselines immediately before convergence;
        # obtaining the write hash must not have advanced a v1 reader to v2.
        expected_baselines = [body] * 5 + [expected_v2] * 6 + [None] * 5
        for client, expected in zip(clients, expected_baselines):
            saved = client.receiver.local_page(created_page)
            actual = saved.get("body/" + created_page) if saved is not None else None
            if actual != expected:
                raise RuntimeError("reader baselines changed before final synchronization")
        expected_body = body.replace(marker, final_marker, 1)
        delivery_modes = {"delta": 0, "snapshot": 0}
        final_tokens = {"all_full": 0, "legacy": 0, "automatic": 0}
        for client, previous, capture in zip(clients, expected_baselines, captures, strict=True):
            before_reads = len(capture.responses)
            sync_result = client.sync_page(created_page)
            if len(capture.responses) != before_reads + 1:
                raise RuntimeError("final sync did not capture exactly one read_changes envelope")
            offer = capture.responses[-1]
            previous_pages = None if previous is None else {"body/" + created_page: previous}
            current_pages = {"body/" + created_page: expected_body}
            principal = client.identity["actor"]
            scope = client.identity["scope"]
            expected_base = (None if previous_pages is None else
                             snapshot_digest(previous_pages, principal=principal, scope=scope))
            forced_full = make_update(None, current_pages, principal=principal, scope=scope,
                                      expected_base=None)
            legacy = make_update(previous_pages, current_pages, principal=principal, scope=scope,
                                 expected_base=expected_base)
            actual = offer["packet"]
            forced_envelope = {"page_id": offer["page_id"], "receipt": offer["receipt"],
                               "packet": forced_full}
            legacy_envelope = {"page_id": offer["page_id"], "receipt": offer["receipt"],
                              "packet": legacy}
            forced_tokens = _reference_tokens(forced_envelope)
            legacy_tokens = _reference_tokens(legacy_envelope)
            expected = forced_envelope if previous_pages is None or forced_tokens < legacy_tokens else legacy_envelope
            if offer != expected or sync_result.get("acknowledged") is not True:
                raise RuntimeError("final offer was not the smallest valid response or was not acknowledged")
            final_tokens["all_full"] += forced_tokens
            final_tokens["legacy"] += legacy_tokens
            final_tokens["automatic"] += _reference_tokens(offer)
            mode = actual["mode"]
            delivery_modes[mode] += 1
            page = client.receiver.local_page(created_page) or {}
            final_body = page.get("body/" + created_page, "")
            if final_body != expected_body:
                raise RuntimeError("all readers did not converge on the exact final body")
            if preserved not in final_body:
                raise RuntimeError("partial update did not preserve unrelated content")
            expected_head = snapshot_digest(
                {"body/" + created_page: expected_body},
                principal=client.identity["actor"], scope=client.identity["scope"])
            if sync_result.get("head") != expected_head:
                raise RuntimeError("reader integrity head did not match its principal-bound snapshot")

        tree = clients[0].remote.call("discover", {})
        discovered = {item["page_id"] for item in tree.get("pages", [])}
        if tree.get("complete") is not True or discovered != {created_page, child}:
            raise RuntimeError("bounded subtree discovery was incomplete")

        # Simulate a lost ACK response, then restart the receiver from the same
        # durable directory. The remote read and ACK are real; only the response
        # is intentionally dropped in this local wrapper.
        child_client = clients[0]
        child_client.sync_page(child)
        state_dir = child_client.receiver.directory / "lost-ack"
        identity = child_client.identity
        dropped = {"done": False}
        def call(name, arguments):
            value = child_client.remote.call(name, arguments)
            if name == "ack_changes" and not dropped["done"]:
                dropped["done"] = True
                raise OSError("synthetic response loss after ACK request")
            return value
        lost = BotReceiver(state_dir, source=identity["source"], actor=identity["actor"],
                           reader=identity["reader"], scope=identity["scope"], call=call)
        try:
            lost.sync(child)
        except OSError:
            pass
        else:
            raise RuntimeError("synthetic ACK response loss was not observed")
        restarted_state = lost.local_page(child) or {}
        if not restarted_state.get("body/" + child):
            raise RuntimeError("lost ACK did not persist the reconstructed page")
        restarted = BotReceiver(state_dir, source=identity["source"], actor=identity["actor"],
                                reader=identity["reader"], scope=identity["scope"],
                                call=child_client.remote.call)
        recovered = restarted.sync(child)
        if recovered.get("acknowledged") is not True:
            raise RuntimeError("lost ACK recovery did not complete")
        receipt = {"status": "pass", "created_test_pages": len(created) - int(bool(args.recover_first_create)),
                   "reconciled_prior_pages": int(bool(args.recover_first_create)),
                   "delivery_modes": delivery_modes,
                   "final_read_changes_tokens": final_tokens,
                   "read_changes_encoding": "o200k_base",
                   "reader_count": len(clients), "bounded_discovered_pages": len(discovered),
                   "pre_sync_baselines": {"v1": 5, "v2": 6, "unread": 5},
                   "partial_update_preserved_unrelated_line": True,
                   "final_body_sha256": hashlib.sha256(expected_body.encode()).hexdigest(),
                   "principal_bound_heads_verified": True,
                   "lost_ack_restart_recovered": True,
                   "page_urls": [f"https://app.notion.com/p/{page_id.replace('-', '')}" for page_id in created],
                   "live_notion_connection": True, "models_called": 0,
                   "initial_root_verified_read_only": True}
        (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in receipt.items() if k != "page_urls"}, ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"status": "failed", "error": type(exc).__name__,
                   "created_test_pages": len(created), "models_called": 0}
        (output / "receipt.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n")
        raise
    finally:
        if server is not None:
            _stop(server, thread)


if __name__ == "__main__":
    raise SystemExit(main())
