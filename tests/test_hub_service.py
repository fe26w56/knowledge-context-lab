"""Exercise authenticated HTTP transport and durable clients with synthetic pages."""
import concurrent.futures
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from context_lab.hub_service import HubService, WriteJournal, create_app, initialize, validate_url
from context_lab.bot_client import BotClient

ROOT = "00000000-0000-4000-8000-000000000001"
CHILD = "00000000-0000-4000-8000-000000000002"
AVAILABLE = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("uvicorn") is not None


class JournalTests(unittest.TestCase):
    def test_initialize_provisions_separate_usable_private_reader_configs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            token_file = base / "notion-token"
            token_file.write_text("synthetic-token")
            token_file.chmod(0o600)
            directory = base / "hub"
            initialize(directory, token_file, [ROOT], "http://127.0.0.1:8765/mcp", 2)
            server_file = directory / "server.json"
            service = HubService(json.loads(server_file.read_text()), gateway_factory=lambda _: Mock(spec=["current"]))
            for reader in ("bot-01", "bot-02"):
                client_file = directory / reader / "client.json"
                client = json.loads(client_file.read_text())
                self.assertEqual(client_file.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(client["token"], server_file.read_text())
                self.assertEqual(service.authenticate(client["token"])["reader"], reader)
            self.assertEqual(server_file.stat().st_mode & 0o777, 0o600)

    def test_lost_write_never_replays_and_ids_are_bound_to_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = WriteJournal(Path(directory))
            calls = []
            def lost():
                calls.append(1)
                raise OSError("response lost after remote commit")
            self.assertEqual(journal.execute("a", "id", "create", {"title": "test"}, lost)["status"], "uncertain")
            self.assertEqual(journal.execute("a", "id", "create", {"title": "test"}, lost)["status"], "uncertain")
            self.assertEqual(len(calls), 1)
            with self.assertRaises(ValueError):
                journal.execute("a", "id", "create", {"title": "other"}, lost)
            self.assertEqual(journal.status("b", "id")["status"], "unknown")

    def test_completed_write_replayed_without_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = WriteJournal(Path(directory))
            calls = []
            def action():
                calls.append(1)
                return {"page_id": CHILD}
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                results = list(pool.map(lambda _: journal.execute("a", "id", "create", {}, action), range(4)))
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(r["status"] in {"completed", "uncertain"} for r in results))
            self.assertEqual(journal.status("a", "id")["result"]["page_id"], CHILD)

    def test_remote_plaintext_rejected(self):
        for url in ("http://example.invalid/mcp", "https://user:pass@example.invalid/mcp", "https://example.invalid/mcp?token=x"):
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_scoped_watch_sync_deduplicates_and_never_discovers(self):
        client = object.__new__(BotClient)
        calls = []
        class Receiver:
            def sync(self, page_id):
                calls.append(page_id)
                if page_id == CHILD:
                    raise RuntimeError("revoked")
                return {"changed": True}
        client.receiver = Receiver()
        client.sync_hub = lambda: (_ for _ in ()).throw(AssertionError("discover called"))
        result = client.sync_pages([CHILD, ROOT, CHILD])
        self.assertEqual(result, {"complete": False, "count": 2, "changed": [ROOT], "failed": [CHILD]})
        self.assertEqual(calls, [ROOT, CHILD])

    def test_watch_page_cli_runs_one_scoped_cycle(self):
        import context_lab.bot_client as bot_client
        class FakeClient:
            calls = []
            def __init__(self, config):
                pass
            def sync_pages(self, page_ids):
                self.calls.append(page_ids)
                return {"complete": True, "count": 1, "changed": [], "failed": []}
            def sync_hub(self):
                raise AssertionError("discover called")
        output = io.StringIO()
        with patch.object(bot_client, "BotClient", FakeClient), \
             patch.object(bot_client.time, "sleep", side_effect=KeyboardInterrupt), \
             patch("sys.stdout", output):
            self.assertEqual(bot_client.main(["--config", "ignored", "watch", "--interval", "5", "--page", ROOT]), 0)
        self.assertEqual(FakeClient.calls, [[ROOT]])
        self.assertNotIn("body", output.getvalue())


@unittest.skipUnless(AVAILABLE, "install .[hub] to exercise real MCP HTTP transport")
class HubHTTPTests(unittest.TestCase):
    def setUp(self):
        import uvicorn
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.pages = {ROOT: "# Shared rules\n\nReviewer: A\n" + "unchanged content\n" * 100}
        pages = self.pages
        self.creates = []
        creates = self.creates
        class Gateway:
            def __init__(self, roots):
                self.roots = roots
            def current(self, page_id):
                return {"body/" + page_id: pages[page_id]} if page_id in pages else {}
            def discover(self):
                return [{"page_id": key, "title": "Synthetic"} for key in pages]
            def create_page(self, parent_id, title, markdown):
                creates.append(title)
                pages[CHILD] = markdown
                return {"page_id": CHILD}
            def replace_text(self, page_id, expected_sha256, old_text, new_text):
                if hashlib.sha256(pages[page_id].encode()).hexdigest() != expected_sha256:
                    raise ValueError("conflict")
                pages[page_id] = pages[page_id].replace(old_text, new_text)
                return {"page_id": page_id, "sha256": hashlib.sha256(pages[page_id].encode()).hexdigest()}
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        self.url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
        config = {"source": "synthetic-hub", "public_url": self.url, "state_dir": str(self.directory / "server"),
                  "bots": [{"reader": f"bot-{i}", "actor": f"actor-{i}", "roots": [ROOT], "write": i == 0,
                            "token_sha256": hashlib.sha256(f"synthetic-{i}".encode()).hexdigest()} for i in range(16)]}
        self.service = HubService(config, gateway_factory=Gateway)
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.service), log_level="error", access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.started)

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        self.tmp.cleanup()

    def client_config(self, i):
        path = self.directory / f"client-{i}.json"
        path.write_text(json.dumps({"url": self.url, "token": f"synthetic-{i}", "state_dir": f"bot-{i}"}))
        path.chmod(0o600)
        return path

    def test_http_authentication_and_identity_cannot_be_spoofed(self):
        from context_lab.bot_client import RemoteHub
        from context_lab.bot_receiver import RemoteToolError
        with self.assertRaises(urllib.error.HTTPError) as result:
            urllib.request.urlopen(self.url)
        self.assertEqual(result.exception.code, 401)
        a = RemoteHub(self.url, "synthetic-0")
        b = RemoteHub(self.url, "synthetic-1")
        self.assertEqual(a.call("identity", {})["reader"], "bot-0")
        self.assertEqual(b.call("identity", {})["reader"], "bot-1")
        from context_lab.handoff_delta import snapshot_digest
        offer = a.call("read_changes", {"page_id": ROOT, "actor": "actor-1"})
        self.assertEqual(offer["packet"]["head"], snapshot_digest({"body/" + ROOT: self.pages[ROOT]}, principal="actor-0", scope="shared"))
        with self.assertRaises(RemoteToolError):
            b.call("ack_changes", {"page_id": ROOT, "receipt": offer["receipt"], "head": offer["packet"]["head"]})
        with self.assertRaises(RemoteToolError):
            b.call("create_page", {"parent_id": ROOT, "title": "test", "markdown": "x", "request_id": "one"})
        self.assertEqual(self.creates, [])

    def test_16_http_readers_with_different_baselines_reconstruct_and_restart(self):
        from context_lab.bot_client import BotClient
        clients = [BotClient(self.client_config(i)) for i in range(16)]
        for client in clients[:5]:
            client.sync_page(ROOT)
        self.pages[ROOT] = self.pages[ROOT].replace("Reviewer: A", "Reviewer: B")
        for client in clients[5:11]:
            client.sync_page(ROOT)
        self.pages[ROOT] += "Deadline: Friday\n"
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda client: client.sync_page(ROOT), clients))
        self.assertEqual(sum(result["packet"]["mode"] == "snapshot" for result in results), 5)
        for client in clients:
            self.assertEqual(client.receiver.local_page(ROOT)["body/" + ROOT], self.pages[ROOT])
        restarted = BotClient(self.directory / "client-0.json")
        unchanged = restarted.sync_page(ROOT)
        self.assertFalse(unchanged["changed"])
        self.assertNotIn("unchanged content", json.dumps(unchanged))
        self.pages.clear()
        result = restarted.sync_hub()
        self.assertTrue(result["complete"])
        self.assertEqual(restarted.receiver.local_page(ROOT), {})

    def test_write_replay_and_new_child_sync(self):
        from context_lab.bot_client import BotClient
        client = BotClient(self.client_config(0))
        args = dict(parent_id=ROOT, title="new synthetic page", markdown="test body", request_id="create-once")
        first = client.remote.call("create_page", args)
        again = client.remote.call("create_page", args)
        self.assertEqual(first, again)
        self.assertEqual(self.creates, ["new synthetic page"])
        self.assertTrue(client.sync_hub()["complete"])
        self.assertEqual(client.get_page(CHILD)["markdown"], "test body")

    def test_stdio_bridge_automatically_saves_and_acknowledges(self):
        import anyio
        import sys
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        config = self.client_config(0)
        async def exercise():
            params = StdioServerParameters(command=sys.executable, args=["-m", "context_lab.bot_client", "--config", str(config), "mcp"])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("get_page", {"page_id": ROOT})
                    self.assertFalse(result.is_error)
                    body = json.loads(result.content[0].text)
                    self.assertEqual(body["markdown"], self.pages[ROOT])
        anyio.run(exercise)
        from context_lab.bot_client import BotClient
        self.assertFalse(BotClient(config).sync_page(ROOT)["changed"])


if __name__ == "__main__":
    unittest.main()
