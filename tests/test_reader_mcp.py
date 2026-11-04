import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from context_lab.handoff_delta import apply_update
from context_lab.notion_reader import NotionPages
from context_lab.reader_handoff import ReaderHandoff
from context_lab.workspace import Workspace


class ReaderMcpTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "workspace.sqlite"
        self.ws = Workspace(self.db)
        self.actor = "shared-account"

    def revise(self, page_id, version, body):
        page = {"id": page_id, "title": page_id, "body": body, "scope": "shared"}
        self.ws.import_pages([page], actor=self.actor, request_id=f"{page_id}-{version}",
                             expected_versions={page_id: version-1})

    def call(self, reader, tool, args, *, error=False):
        # Launch a fresh process for every call, including acknowledgements.
        requests = [{"method": "initialize", "params": {}},
                    {"method": "tools/list", "params": {}},
                    {"method": "tools/call", "params": {"name": tool, "arguments": args}}]
        wire = "".join(json.dumps(dict(q, id=i+1, jsonrpc="2.0"))+"\n" for i, q in enumerate(requests))
        cmd = [sys.executable, "-m", "context_lab.workspace_mcp", "--db", str(self.db),
               "--actor", self.actor, "--reader", reader, "--handoff-state", str(self.root/"state")]
        proc = subprocess.run(cmd, input=wire, capture_output=True, text=True, check=True, timeout=30)
        _, listing, response = map(json.loads, proc.stdout.splitlines())
        self.assertEqual({x["name"] for x in listing["result"]["tools"]}, {"read_changes", "ack_changes"})
        result = response.get("result", {})
        if error:
            self.assertTrue(result.get("isError") or response.get("error"), response)
            return
        self.assertFalse(result.get("isError") or response.get("error"), response)
        return json.loads(result["content"][0]["text"])

    def ack(self, reader, offer, **kwargs):
        args = {"receipt": offer["receipt"], "head": offer["packet"]["head"], "page_id": offer["page_id"]}
        return self.call(reader, "ack_changes", args, **kwargs)

    def test_divergent_readers_and_pages_with_loss_restart_and_stale_ack(self):
        self.revise("rules", 1, "Keep this line.\nOne reviewer.\nDue Friday.\n")
        self.revise("other", 1, "Other page.\n")
        args = {"page_id": "rules"}
        first = self.call("A", "read_changes", args)
        self.assertEqual(first, self.call("A", "read_changes", args))
        self.ack("B", first, error=True)
        self.ack("A", first)
        self.ack("A", first)  # lost ack response
        self.call("A", "ack_changes", dict(page_id="other", receipt=first["receipt"],
                                          head=first["packet"]["head"]), error=True)
        self.revise("rules", 2, "Keep this line.\nTwo reviewers.\nDue Friday.\n")
        second = self.call("B", "read_changes", args)
        self.ack("B", second)
        missed = self.call("A", "read_changes", args)
        latest = "Keep this line.\nTwo reviewers.\nDue Monday.\n"
        self.revise("rules", 3, latest)
        for agent, base in [("A", first), ("B", second), ("C", None)]:
            offer = self.call(agent, "read_changes", args)
            packet = offer["packet"]
            if base:
                self.assertEqual(packet["base"], base["packet"]["head"])
                previous = base["packet"]["pages"]
                self.assertNotIn("Keep this line.", json.dumps(packet))
                patch = packet["patches"]["body/rules"]["text"]
                self.assertEqual(patch, "Two reviewers.\nDue Monday.\n" if agent == "A" else "Due Monday.\n")
            else:
                self.assertEqual(packet["mode"], "snapshot")
                previous = None
            after = apply_update(previous, packet, principal=self.actor, scope="shared")
            self.assertEqual(after["body/rules"], latest)
            if agent == "A":
                self.ack(agent, missed, error=True)
            self.ack(agent, offer)
        self.assertEqual(self.call("A", "read_changes", {"page_id":"other"})["packet"]["mode"], "snapshot")
        reset = self.call("B", "read_changes", dict(args, fresh=True))
        self.assertEqual(reset["packet"]["mode"], "snapshot")
        self.assertEqual(reset, self.call("B", "read_changes", args))
        self.call("A", "read_changes", dict(args, reader="B"), error=True)
        self.call("A", "get_source", args, error=True)

    def test_sixteen_readers_midstream_and_concurrent_duplicate_delivery(self):
        pages = {"body/p": "version 1"}
        def build(i):
            return ReaderHandoff(self.root/"state", source="s", actor=self.actor, reader=str(i),
                                 scope="shared", current=lambda page: dict(pages))
        readers = [build(i) for i in range(16)]
        bases = {}
        def accept(i):
            r = readers[i]
            offer = r.read(page_id="p")
            r.acknowledge(page_id="p", receipt=offer["receipt"], head=offer["packet"]["head"])
            bases[i] = offer["packet"]
        with ThreadPoolExecutor(16) as pool:
            list(pool.map(accept, range(5)))
            pages["body/p"] = "version 2"
            list(pool.map(accept, range(5,11)))
            pages["body/p"] = "version 3"
            deliveries = list(pool.map(lambda i: build(i).read(page_id="p"), range(16)))
            repeats = list(pool.map(lambda _: build(0).read(page_id="p"), range(8)))
        self.assertTrue(all(r == deliveries[0] for r in repeats))
        for i, offer in enumerate(deliveries):
            packet = offer["packet"]
            if i in bases:
                self.assertEqual(packet["base"], bases[i]["head"])
            else:
                self.assertEqual(packet["mode"], "snapshot")
            before = bases[i]["pages"] if i in bases else None
            self.assertEqual(apply_update(before, packet, principal=self.actor, scope="shared"), pages)

    @patch.dict(os.environ, {"NOTION_TOKEN": "fictional-test-credential"})
    @patch("context_lab.notion_reader.http.client.HTTPSConnection")
    def test_notion_reader_refetches_and_fails_closed(self, connect):
        page = "5f02a745-37cc-4e15-8c38-d19655bc34de"
        response = connect.return_value.getresponse.return_value
        def reply(status, value):
            response.status = status
            response.read.return_value = json.dumps(value).encode()
        source = NotionPages([page])
        reader = ReaderHandoff(self.root/"state", source="notion:fixture", actor="bot", reader="first",
                               scope="shared", current=source)
        data = {"object":"page_markdown", "id":page, "markdown":"Visible only before revocation.",
                "truncated":False, "unknown_block_ids":[]}
        reply(200, data)
        first = reader.read(page_id=page)
        reader.acknowledge(page_id=page, receipt=first["receipt"], head=first["packet"]["head"])
        connect.assert_called_with("api.notion.com", timeout=20)
        self.assertEqual(connect.return_value.request.call_args.args,
                         ("GET", f"/v1/pages/{page}/markdown?markdown_version=v2"))
        for status, value in [(429, {}), (401, {}), (403, {}), (503, {}), (404, {}),
                              (200, dict(data, truncated=True)), (200, dict(data, unknown_block_ids=[page]))]:
            reply(status, value)
            with self.assertRaises(ValueError):
                reader.read(page_id=page)
        reply(404, {"code":"object_not_found"})
        purge = reader.read(page_id=page)["packet"]
        self.assertEqual(purge["purge"], ["body/"+page])
        self.assertNotIn(data["markdown"], json.dumps(purge))
        self.assertEqual(apply_update(first["packet"]["pages"], purge, principal="bot", scope="shared"), {})
        calls = connect.call_count
        self.assertEqual(source("721bfbba-cbe2-444b-b34b-d5455eca2e58"), {})
        self.assertEqual(connect.call_count, calls)
