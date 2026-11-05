"""Measure automatic HubService read selection against full/delta oracles.

This benchmark intentionally uses the real loopback MCP server and BotClient,
but a synthetic gateway.  The fixture is the only source of expanded content;
the gateway merely exposes the frozen version currently selected by the run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import uuid

import tiktoken

from context_lab.bot_client import BotClient, RemoteHub
from context_lab.handoff_delta import apply_update, make_update, snapshot_digest


FIXTURE_SHA = "1afcc1c1f40fdcfa4be50ab302c93d3e898da24740c4031168062ebd10709791"
# Pinned after deterministic materialization review; changing fixture expansion
# must deliberately produce a new benchmark version.
EXPANDED_SHA = "c5c774b3d3ef467f40dac001d876d7fcb7bbb27c35398a4c0f470f010898ecad"
ROOT = "00000000-0000-4000-8000-000000000001"
EXPECTED_BOTS = (5, 6, 5)


def _load_fixture(path: Path) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FIXTURE_SHA:
        raise ValueError(f"fixture SHA mismatch: {digest}")
    return json.loads(raw)


def _body(spec: dict, label: str, count: int, version: int, edit_name: str) -> str:
    template = spec["template"]
    lines = [template.replace("{n % 7}", str(n % 7)).replace("{n}", str(n)).replace("{label}", label)
             for n in range(1, count + 1)]
    rule = spec["edits"][edit_name]
    if rule == "all three versions are identical":
        return "".join(lines)
    marker = f"Version {version} decision for {label}."
    if rule.startswith("append"):
        return "".join(lines) + "".join(f"Version {v} decision for {label}.\n" for v in range(2, version + 1))
    if rule.startswith("replace the middle"):
        index = len(lines) // 2
        if version > 1:
            lines[index] = marker + "\n"
        return "".join(lines)
    if rule.startswith("replace first and last"):
        if version > 1:
            lines[0] = marker + "\n"
            lines[-1] = marker + "\n"
        return "".join(lines)
    if rule.startswith("replace every"):
        return "".join(marker + f" line {n}.\n" for n in range(1, count + 1)) if version > 1 else "".join(lines)
    raise ValueError(f"unsupported fixture edit rule: {rule}")


def expand(spec: dict) -> list[dict]:
    rows = []
    serial = 0
    for group in ("dev", "final"):
        for label, count, spec_name_value in spec[group]:
            serial += 1
            page_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"phase2-hub-auto-v1/{group}/{serial}"))
            versions = {str(v): _body(spec, label, count, v, spec_name_value) for v in (1, 2, 3)}
            rows.append({"case": f"{group}-{serial:02}", "group": group, "label": label,
                         "count": count, "edit": spec_name_value, "page_id": page_id,
                         "versions": versions,
                         "sha256": {v: hashlib.sha256(body.encode()).hexdigest() for v, body in versions.items()}})
    return rows


def _compact_tokens(value: dict, enc) -> int:
    wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return len(enc.encode_ordinary(wire))


class Gateway:
    def __init__(self, pages: dict[str, str], roots: list[str]):
        self.pages, self.roots = pages, roots

    def current(self, page_id: str) -> dict[str, str]:
        body = self.pages.get(page_id)
        return {"body/" + page_id: body} if body is not None else {}

    def discover(self):
        return [{"page_id": page_id, "title": "Synthetic"} for page_id in sorted(self.pages)]


class CaptureRemote:
    """Forward every call while retaining the pre-receiver read envelope."""
    def __init__(self, remote: RemoteHub, log: list[dict], lock: threading.Lock, reader: str):
        self.remote, self.log, self.lock, self.reader = remote, log, lock, reader

    def call(self, name: str, arguments: dict) -> dict:
        result = self.remote.call(name, arguments)
        if name == "read_changes":
            with self.lock:
                self.log.append({"reader": self.reader, "arguments": dict(arguments), "reply": json.loads(json.dumps(result))})
        return result


def _server(pages: dict[str, str], directory: Path):
    import uvicorn
    from context_lab.hub_service import HubService, create_app
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0)); sock.listen(128)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
    bots = []
    for i in range(16):
        token = f"phase2-hub-auto-{i:02}"
        bots.append({"reader": f"bot-{i:02}", "actor": f"actor-{i:02}", "roots": [ROOT], "write": False,
                     "token_sha256": hashlib.sha256(token.encode()).hexdigest()})
    config = {"source": "synthetic-phase2-hub-auto-v1", "public_url": url,
              "state_dir": str(directory / "server"), "bots": bots}
    service = HubService(config, gateway_factory=lambda roots: Gateway(pages, roots))
    server = uvicorn.Server(uvicorn.Config(create_app(service), log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(.01)
    if not server.started:
        raise RuntimeError("loopback HubService did not start")
    return url, server, thread


def run(fixture: Path, out: Path):
    spec = _load_fixture(fixture)
    cases = expand(spec)
    enc = tiktoken.get_encoding("o200k_base")
    out.mkdir(parents=True, exist_ok=False)
    (out / "expanded_inputs.json").write_text(json.dumps(cases, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    (out / "expanded_inputs.sha256").write_text(hashlib.sha256((out / "expanded_inputs.json").read_bytes()).hexdigest() + "\n")
    manifest = {"fixture": str(fixture), "fixture_sha256": FIXTURE_SHA,
                "expanded_sha256": hashlib.sha256((out / "expanded_inputs.json").read_bytes()).hexdigest(),
                "versions": {case["case"]: case["sha256"] for case in cases}}
    if manifest["expanded_sha256"] != EXPANDED_SHA:
        raise ValueError(f"expanded materialization SHA mismatch: {manifest['expanded_sha256']}")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    pages = {case["page_id"]: case["versions"]["1"] for case in cases}
    with tempfile.TemporaryDirectory(prefix="phase2-hub-auto-") as temp:
        temp_path = Path(temp)
        url, server, thread = _server(pages, temp_path)
        logs, lock, clients = [], threading.Lock(), []
        for i in range(16):
            cfg = temp_path / f"client-{i:02}.json"
            cfg.write_text(json.dumps({"url": url, "token": f"phase2-hub-auto-{i:02}", "state_dir": f"bot-{i:02}"}))
            cfg.chmod(0o600)
            remote = CaptureRemote(RemoteHub(url, f"phase2-hub-auto-{i:02}"), logs, lock, f"bot-{i:02}")
            clients.append(BotClient(cfg, remote=remote))
        # Warm-up establishes exactly the requested 5/6/5 retained baselines.
        for case in cases:
            for i in range(11):
                version = "1" if i < EXPECTED_BOTS[0] else "2"
                pages[case["page_id"]] = case["versions"][version]
                clients[i].sync_page(case["page_id"], fresh=True)
        warmup_end = len(logs)
        for case in cases:
            pages[case["page_id"]] = case["versions"]["3"]
        def measure(i):
            return clients[i].sync_pages([case["page_id"] for case in cases])
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(measure, range(16)))
        for i, result in enumerate(results):
            if not result.get("complete"):
                raise AssertionError(f"bot-{i:02} did not complete all page applications: {result}")
            for case in cases:
                saved = clients[i].receiver.local_page(case["page_id"])
                expected = {"body/" + case["page_id"]: case["versions"]["3"]}
                if saved != expected:
                    raise AssertionError(f"bot-{i:02}/{case['case']} saved body mismatch")
        server.should_exit = True; thread.join(10)
        if thread.is_alive():
            raise RuntimeError("loopback HubService did not stop")

    warmup_reads = logs[:warmup_end]
    actual_reads = logs[warmup_end:]
    case_by_page = {case["page_id"]: case for case in cases}
    expected_pairs = {(f"bot-{i:02}", case["page_id"]) for i in range(16) for case in cases}
    observed_pairs = {(entry["reader"], entry["arguments"]["page_id"]) for entry in actual_reads}
    if observed_pairs != expected_pairs or len(actual_reads) != len(expected_pairs):
        raise AssertionError("measured reader/page pairs are not exactly once")
    rows = []
    for entry in actual_reads:
        reply = entry["reply"]; page_id = entry["arguments"]["page_id"]
        case = case_by_page[page_id]
        i = int(entry["reader"].rsplit("-", 1)[1])
        current = {"body/" + page_id: case["versions"]["3"]}
        previous = None if i >= 11 else {"body/" + page_id: case["versions"]["1" if i < 5 else "2"]}
        base = snapshot_digest(previous, principal=f"actor-{i:02}", scope="shared") if previous else None
        full_packet = make_update(None, current, principal=f"actor-{i:02}", scope="shared", expected_base=None)
        delta_packet = make_update(previous, current, principal=f"actor-{i:02}", scope="shared", expected_base=base) if previous else full_packet
        receipt = reply["receipt"]
        full_wire = {"page_id": page_id, "receipt": receipt, "packet": full_packet}
        delta_wire = {"page_id": page_id, "receipt": receipt, "packet": delta_packet}
        full_tokens, delta_tokens = _compact_tokens(full_wire, enc), _compact_tokens(delta_wire, enc)
        # ReaderHandoff's automatic selector keeps delta on equal cost (< for
        # snapshot), so the oracle uses the same deterministic tie-break.
        oracle_kind = "full" if full_tokens < delta_tokens else "delta"
        oracle_packet = full_packet if oracle_kind == "full" else delta_packet
        actual_wire = {"page_id": page_id, "receipt": receipt, "packet": reply["packet"]}
        if apply_update(None, full_packet, principal=f"actor-{i:02}", scope="shared") != current:
            raise AssertionError("full candidate reconstruction mismatch")
        if apply_update(previous, delta_packet, principal=f"actor-{i:02}", scope="shared") != current:
            raise AssertionError("delta candidate reconstruction mismatch")
        chosen_wire = full_wire if oracle_kind == "full" else delta_wire
        row = {"reader": entry["reader"], "case": case["case"], "group": case["group"], "page_id": page_id,
               "receipt": receipt, "actual_mode": reply["packet"]["mode"],
               "actual_tokens": _compact_tokens(actual_wire, enc), "full_tokens": full_tokens,
               "delta_tokens": delta_tokens, "oracle_mode": oracle_packet["mode"],
               "actual_equals_oracle": reply == chosen_wire,
               "full_head": full_packet["head"], "delta_head": delta_packet["head"],
               "actual_packet": reply["packet"], "oracle_packet": oracle_packet}
        rows.append(row)
    if not rows or not all(row["actual_equals_oracle"] for row in rows):
        bad = [row["reader"] + "/" + row["case"] for row in rows if not row["actual_equals_oracle"]]
        raise AssertionError("automatic packets differ from oracle-min: " + ", ".join(bad))
    # Preserve raw replies and the independently constructed oracle rows.
    (out / "actual_reads.json").write_text(json.dumps(actual_reads, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    (out / "warmup_reads.json").write_text(json.dumps(warmup_reads, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    (out / "oracle_rows.json").write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    warm_tokens = sum(_compact_tokens(entry["reply"], enc) for entry in warmup_reads)
    warmup_by_group = {"dev": {"reads": 0, "tokens": 0}, "final": {"reads": 0, "tokens": 0}}
    for entry in warmup_reads:
        group = case_by_page[entry["arguments"]["page_id"]]["group"]
        warmup_by_group[group]["reads"] += 1
        warmup_by_group[group]["tokens"] += _compact_tokens(entry["reply"], enc)
    modes = {"all_full": [], "legacy_delta_if_warm": [], "actual_automatic": []}
    for row in rows:
        modes["all_full"].append(row["full_tokens"])
        modes["legacy_delta_if_warm"].append(row["delta_tokens"])
        modes["actual_automatic"].append(row["actual_tokens"])
    summary = {"fixture_sha256": FIXTURE_SHA, "expanded_sha256": manifest["expanded_sha256"],
               "cases": len(cases), "actual_reads": len(actual_reads), "warmup_reads": len(warmup_reads),
               "warmup_tokens": warm_tokens, "warmup_by_group": warmup_by_group,
               "mode_counts": {}, "results": results,
               "saved_and_acknowledged": True, "reader_page_pairs_exactly_once": True,
               "totals": {name: {"measurement_reads": len(values), "measurement_tokens": sum(values),
                                  "total_tokens_including_warmup": warm_tokens + sum(values)}
                          for name, values in modes.items()},
               "by_group": {}, "by_case": {}, "oracle_min_verified": True}
    for row in rows:
        mode = row["actual_mode"]
        summary["mode_counts"][mode] = summary["mode_counts"].get(mode, 0) + 1
        group = summary["by_group"].setdefault(row["group"], {name: 0 for name in modes})
        group["all_full"] += row["full_tokens"]
        group["legacy_delta_if_warm"] += row["delta_tokens"]
        group["actual_automatic"] += row["actual_tokens"]
        case_totals = summary["by_case"].setdefault(row["case"], {"group": row["group"],
            "all_full": 0, "legacy_delta_if_warm": 0, "actual_automatic": 0,
            "mode_counts": {"snapshot": 0, "delta": 0}})
        case_totals["all_full"] += row["full_tokens"]
        case_totals["legacy_delta_if_warm"] += row["delta_tokens"]
        case_totals["actual_automatic"] += row["actual_tokens"]
        case_totals["mode_counts"][row["actual_mode"]] += 1
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/phase2-hub-auto-v1/cases.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.fixture, args.out), ensure_ascii=False, sort_keys=True))
