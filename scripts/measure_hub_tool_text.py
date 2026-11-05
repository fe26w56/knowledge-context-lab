"""Count actual bot MCP tool text by replaying a completed synthetic hub run. No API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import anyio
import tiktoken

from context_lab.bot_client import BotClient, stdio_server
from context_lab.handoff_delta import make_update, snapshot_digest


class RecordedRemote:
    def __init__(self, identity):
        self.identity = identity
        self.offer = None

    def call(self, name, args):
        if name == "identity":
            return self.identity
        if name == "read_changes" and args["page_id"] == self.offer["page_id"]:
            return self.offer
        if name == "ack_changes" and args == {
            "page_id": self.offer["page_id"], "receipt": self.offer["receipt"], "head": self.offer["packet"]["head"]
        }:
            return {"acknowledged": True, "page_id": args["page_id"], "head": args["head"]}
        raise ValueError("unexpected call in saved-response replay")


async def measure(run):
    def load(name):
        return json.loads((run / name).read_text())
    cases = {c["page_id"]:c for c in load("expanded_inputs.json") if c["group"] == "final"}
    offers = {(r["reader"],r["reply"]["page_id"]):r["reply"] for r in load("actual_reads.json")}
    warmups = {(r["reader"],r["reply"]["page_id"]):r["reply"] for r in load("warmup_reads.json")}
    enc = tiktoken.get_encoding("o200k_base")
    by_case = {c["label"]:{arm:0 for arm in ("full","legacy","auto")} for c in cases.values()}
    all_counts = {}
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for arm in ("full","legacy","auto"):
            for i in range(16):
                reader, actor = f"bot-{i:02}", f"actor-{i:02}"
                ident = dict(source="synthetic-phase2-hub-auto-v1", actor=actor, reader=reader, scope="shared")
                remote = RecordedRemote(ident)
                config = Path(tmp) / f"{arm}-{reader}.json"
                config.write_text(json.dumps(dict(url="http://127.0.0.1/mcp",token="fixture",state_dir=config.stem)))
                config.chmod(0o600)
                client = BotClient(config, remote=remote)
                server = stdio_server(client)
                for page, case in cases.items():
                    key = (reader,page)
                    if key in warmups:
                        remote.offer = warmups[key]
                        client.sync_page(page)
                    prev = client.receiver.local_page(page)
                    current = {"body/"+page:case["versions"]["3"]}
                    ctx = dict(principal=actor, scope="shared")
                    remote.offer = offers[key]
                    if arm != "auto":
                        base = prev if arm == "legacy" else None
                        packet = make_update(base, current, expected_base=snapshot_digest(base, **ctx) if base is not None else None, **ctx)
                        # Simulate exactly the canonical key order of the hub's wire text.
                        remote.offer = json.loads(json.dumps({**remote.offer,"packet":packet}, sort_keys=True))
                    response = await server.call_tool("sync_page", {"page_id":page})
                    if response.is_error or len(response.content) != 1 or response.content[0].type != "text":
                        raise ValueError("invalid bot MCP response")
                    text = response.content[0].text
                    parsed = json.loads(text)
                    assert parsed["packet"] == remote.offer["packet"] and parsed["acknowledged"] is True
                    assert parsed["changed"] == (prev != current) and client.receiver.local_page(page) == current
                    tokens = len(enc.encode_ordinary(text))
                    by_case[case["label"]][arm] += tokens
                    all_counts.setdefault(key,{})[arm] = tokens
                    rows.append(dict(reader=reader,case=case["label"],arm=arm,tokens=tokens,sha256=hashlib.sha256(text.encode()).hexdigest()))
    return {"method":"Final-only replay of saved synthetic hub offers in real BotClient/BotReceiver and actual MCP sync_page tool renderer; no model API or HTTP, excludes host prompts and tool schemas.",
            "model_calls":0,"encoding":"o200k_base","renders":len(rows),"reader_page_pairs":len(all_counts),
            "automatic_exceeds_min_rendered_pairs":sum(v["auto"] > min(v["legacy"],v["full"]) for v in all_counts.values()),
            "totals":{a:sum(v[a] for v in by_case.values()) for a in ("full","legacy","auto")}, "by_case":by_case,"rows":rows}


if __name__ == "__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("run",type=Path)
    cli.add_argument("new_output",type=Path)
    args=cli.parse_args()
    if args.new_output.exists():
        cli.error("use a new output name")
    data=anyio.run(measure,args.run)
    with args.new_output.open("x") as stream:
        stream.write(json.dumps(data,indent=2)+"\n")
    print(data["totals"])
