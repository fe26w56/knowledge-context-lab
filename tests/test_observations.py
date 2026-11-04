from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from context_lab.observations import ObservationSink, summarize
from context_lab.store import ValidationError
from context_lab.workspace import Workspace


class ObservationTests(unittest.TestCase):
    def _page(self):
        return [{"id": "obs-page", "title": "fictional", "body": "Current diagnostic text.",
                 "scope": "shared", "owner": None, "properties": {}}]

    def test_default_off_and_redacted_concurrent_events(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "workspace.sqlite"
            ws = Workspace(db)
            ws.import_pages(self._page(), actor="agent-a", request_id="seed")
            ws.search("private question text", actor="agent-a")
            self.assertEqual(list(Path(td).glob("*.json")), [])
            events = Path(td) / "events"
            observer = ObservationSink(events, kind="diagnostic")
            observed = Workspace(db, observer=observer)
            observed.import_pages(self._page(), actor="agent-a", request_id="same-seed")
            with ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(lambda _: observed.search("private question text", actor="agent-a"), range(16)))
            with self.assertRaises(ValidationError):
                observed.search("", actor="agent-a")
            files = list(events.glob("*.json"))
            self.assertEqual(len(files), 17)
            serialized = "\n".join(path.read_text() for path in files)
            self.assertNotIn("private question text", serialized)
            self.assertNotIn("agent-a", serialized)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in files))
            summary = summarize(events, kind="diagnostic")
            self.assertEqual(summary["events"], 17)
            self.assertEqual(summary["failures"], 1)
            self.assertGreater(summary["exact_repeat_rate"], 0)
            self.assertFalse(summary["measured_business_benefit"])
            self.assertEqual(summarize(events, kind="operational")["measured_business_benefit"], False)

    def test_observer_rejects_unknown_kind_and_aggregate_has_no_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                ObservationSink(Path(td) / "events", kind="unknown")
            events = Path(td) / "events"
            sink = ObservationSink(events, kind="diagnostic")
            sink.record(operation="search", actor="named-agent", request="secret request",
                        mode="current", settings={"candidate_pages": 3}, started=0.0,
                        result={"sources": []})
            aggregate = summarize(events, kind="diagnostic")
            self.assertNotIn("request_digest", json.dumps(aggregate))
            self.assertNotIn("named-agent", json.dumps(aggregate))

    def test_percentile_temp_filter_mode_redaction_and_kind_settings_separation(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "events"
            events.mkdir(mode=0o755)
            os.chmod(events, 0o755)
            sink = ObservationSink(events, kind="diagnostic")
            self.assertEqual(events.stat().st_mode & 0o777, 0o755)
            sink.record(operation="search", actor="agent", request="q", mode="current",
                        settings={"candidate_pages": 1}, started=time.perf_counter() - 0.01,
                        result={"sources": [{"version": 1}]})
            sink.record(operation="search", actor="agent", request="q", mode="current",
                        settings={"candidate_pages": 1}, started=time.perf_counter() - 0.02,
                        result={"sources": [{"version": 2}]})
            sink.record(operation="search", actor="other-agent", request="q", mode="current",
                        settings={"candidate_pages": 1}, started=time.perf_counter(),
                        result={"sources": [{"version": 2}]})
            sink.record(operation="search", actor="agent", request="q", mode="SECRET-MODE",
                        settings={"source_version": 2}, started=time.perf_counter(),
                        error=ValueError("secret exception message"))
            (events / ".event-incomplete.json").write_text('{"kind":"diagnostic"}')
            summary = summarize(events, kind="diagnostic")
            self.assertEqual(summary["events"], 4)
            self.assertEqual(summary["exact_repeat_events"], 0)
            self.assertEqual(summary["actor_label_count"], 2)
            self.assertEqual(summary["same_retrieval_repeat_events"], 1)
            self.assertEqual(summary["cross_actor_overlap_groups"], 1)
            self.assertEqual(summary["cross_actor_repeated_retrievals"], 1)
            self.assertGreaterEqual(summary["duration_p95_ms"], summary["duration_median_ms"])
            serialized = "\n".join(path.read_text() for path in events.glob("*.json"))
            self.assertNotIn("SECRET-MODE", serialized)
            self.assertNotIn("secret exception message", serialized)
            operational = ObservationSink(events, kind="operational")
            operational.record(operation="search", actor="agent", request="q", mode="current",
                               settings={"source_version": 1}, started=time.perf_counter(),
                               result={"sources": []})
            self.assertEqual(summarize(events, kind="operational")["events"], 1)
            self.assertEqual(summarize(events, kind="diagnostic")["events"], 4)

    def test_p95_uses_nearest_rank_for_sixteen_events(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "events"
            events.mkdir()
            for index in range(1, 17):
                event_id = f"00000000-0000-4000-8000-{index:012d}"
                (events / f"{event_id}.json").write_text(json.dumps({
                    "event_id": event_id, "kind": "diagnostic", "status": "ok",
                    "duration_ms": index, "request_digest": str(index),
                    "actor_digest": "actor", "payload_digest": str(index),
                    "mode": "current", "settings_digest": "settings",
                }))
            summary = summarize(events, kind="diagnostic")
            self.assertEqual(summary["duration_median_ms"], 8.5)
            self.assertEqual(summary["duration_p95_ms"], 16)
            malformed = events / "00000000-0000-4000-8000-000000000017.json"
            malformed.write_text(json.dumps({"kind": "diagnostic", "status": "ok",
                                             "duration_ms": "PRIVATE-CONTENT"}))
            with self.assertRaisesRegex(ValueError, "finite nonnegative number") as caught:
                summarize(events, kind="diagnostic")
            self.assertNotIn("PRIVATE-CONTENT", str(caught.exception))

    def test_cli_and_mcp_observation_are_opt_in(self):
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            db = base / "workspace.sqlite"
            pages = base / "pages.json"
            pages.write_text(json.dumps({"pages": self._page()}), encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(root / "src")}
            subprocess.run([sys.executable, "-m", "context_lab.workspace_cli", "--db", str(db), "--actor", "agent-a",
                            "import-pages", "--input", str(pages), "--request-id", "seed"], cwd=root, env=env, check=True,
                           capture_output=True, text=True)
            observe = base / "cli-events"
            subprocess.run([sys.executable, "-m", "context_lab.workspace_cli", "--db", str(db), "--actor", "agent-a",
                            "--observe-dir", str(observe), "search", "Current diagnostic"], cwd=root, env=env,
                           check=True, capture_output=True, text=True)
            self.assertEqual(len(list(observe.glob("*.json"))), 1)
            mcp_events = base / "mcp-events"
            messages = ('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}\n'
                        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search","arguments":{"request":"Current diagnostic"}}}\n')
            subprocess.run([sys.executable, "-m", "context_lab.workspace_mcp", "--db", str(db), "--actor", "agent-a",
                            "--observe-dir", str(mcp_events)], cwd=root, env=env, input=messages,
                           check=True, capture_output=True, text=True)
            self.assertEqual(len(list(mcp_events.glob("*.json"))), 1)

