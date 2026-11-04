import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from context_lab.budget import ExperimentBudget
from context_lab.workflow import (SingleFlight, WorkflowEngine, checked_record,
                                  context_item, digest, handoffs_for, visible_sources, normalize_answer)


class FakeClient:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()
        self.n = 0
        self.layouts = []

    def complete(self, kind, payload, schema, prompt, *, max_output_tokens, metadata, source_first=False, cache_boundary=False):
        with self._lock:
            self.calls.append((kind, copy.deepcopy(payload), metadata))
            self.layouts.append(source_first)
            self.n += 1
            ident = str(self.n)
        if kind == "evidence_record":
            output = {"excerpts": [{"source_id": s["source_id"], "quote": s["text"]} for s in payload["sources"]]}
        elif schema["properties"]["fields"]["type"] == "array":
            output = {"fields": [{"name": name, "value": None, "citations": []} for name in payload["requested_fields"]], "needs_more": False}
        else:
            output = {"fields": {name: {"value": None, "citations": []} for name in schema["properties"]["fields"]["properties"]}, "needs_more": False}
        return {"attempt_id": ident, "status": "ok", "ledger_status": "settled", "output": output}


def source(sid, body, *, scope="shared", owner="team", revision="r1", state="adopted", start="2026-01-01", end=None):
    return {"source_id": sid, "revision": revision, "title": sid, "body": body,
            "scope": scope, "owner": owner, "state": state, "effective_from": start, "effective_to": end}


def task(actor="alice", tid="t1", depends=None):
    return {"task_id": tid, "actor": actor, "topic": "policy", "area": "operations",
            "request": "What is the current policy?", "depends_on": depends or [],
            "output_spec": {"decision": {"type": "string", "description": "decision"}}}


class WorkflowTests(unittest.TestCase):
    def test_uniform_wire_conversion_is_lossless_and_rejects_invalid_fields(self):
        spec = {"amount": {"type": "number", "description": "Measured amount"}}
        output = {"fields": [{"name": "amount", "value": 12, "citations": []}], "needs_more": False}
        self.assertEqual(normalize_answer(output, spec)["fields"]["amount"]["value"], 12)
        for invalid in (
            {"fields": output["fields"]*2, "needs_more": False},
            {"fields": [], "needs_more": False},
            {"fields": [{"name":"amount","value":True,"citations":[]}], "needs_more":False},
            {"fields": [{"name":"other","value":12,"citations":[]}], "needs_more":False}):
            with self.assertRaises(ValueError):normalize_answer(invalid, spec)

    def test_uniform_workflow_keeps_contract_after_cached_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("uniform12", client, Path(tmp)/"run")
            wave = {"wave":1,"as_of":"2026-02-01","available_source_ids":["s"],"tasks":[task()]}
            result = engine.run([source("s","Policy is available as an exact operational source.")], [wave])
            self.assertEqual(result["results"]["t1"]["output"]["fields"], {"decision":{"value":None,"citations":[]}})
            self.assertEqual(client.calls[0][1]["requested_fields"], task()["output_spec"])

    def test_public_handoff_is_withheld_after_privatization_or_deletion(self):
        old = source("old", "A formerly public operating rule."); old["logical_id"] = "rule"
        updated = source("new", "A now private operating rule.", scope="private", owner="alice"); updated["logical_id"] = "rule"
        previous = {"output": {"fields": {}}, "actor": "alice", "as_of": "2026-01-01", "private_source_ids": [],
                    "selected_source_permissions": [{"source_id": "old", "logical_id": "rule", "scope": "shared", "owner": "team"}]}
        child = task(actor="bob", depends=["prior"])
        self.assertEqual(handoffs_for(child, {"prior":previous}, [], [updated]), [])
        self.assertEqual(handoffs_for(child, {"prior":previous}, [], []), [])
        updated["scope"] = "shared"
        self.assertEqual(len(handoffs_for(child, {"prior":previous}, [updated], [updated])), 1)

    def test_unsafe_task_path_and_forward_dependency_rejected_before_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("full12", client, Path(tmp)/"run")
            for item in (task(tid="../escape"), task(depends=["future"])):
                with self.assertRaises(ValueError):engine.run([], [{"tasks":[item]}])
            self.assertEqual(client.calls, [])

    def test_singleflight_builds_identical_key_once_under_16_concurrent_calls(self):
        flight = SingleFlight(); gate = threading.Event(); builds = []
        def build():
            builds.append(1); gate.wait(2); return {"value": "same"}
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(flight.get, "key", build) for _ in range(16)]
            gate.set(); results = [future.result() for future in futures]
        self.assertEqual(len(builds), 1); self.assertEqual(flight.builds, 1); self.assertEqual(flight.hits, 15)
        self.assertTrue(all(item[0] == {"value": "same"} for item in results))

    def test_snapshot_content_revision_deletion_permission_and_asof_change_key(self):
        public = source("public", "Policy says keep records.")
        private = source("private", "Private policy says keep records.", scope="private", owner="alice")
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("reuse12", client, Path(tmp) / "base")
            base, key, _ = engine.retrieve([public, private], "policy", "operations", "2026-02-01", "alice")
            variants = []
            for changed in [
                [source("public", "Policy says archive records.")],
                [source("public", "Policy says keep records.", revision="r2")],
                [private],
            ]:
                _, changed_key, _ = engine.retrieve(changed, "policy", "operations", "2026-02-01", "alice")
                variants.append(changed_key)
            _, permission_key, _ = engine.retrieve(visible_sources([public, private], ["public", "private"], "bob", "2026-02-01"), "policy", "operations", "2026-02-01", "bob")
            _, asof_key, _ = engine.retrieve([public, private], "policy", "operations", "2027-02-01", "alice")
            self.assertEqual(key, engine.retrieve([public, private], "policy", "operations", "2026-02-01", "alice")[1])
            self.assertEqual(len(set([key, *variants, permission_key, asof_key])), 6)

    def test_visible_sources_and_private_handoff_are_separated(self):
        shared = source("shared", "Shared operational rule.")
        private = source("private", "Alice household detail.", scope="private", owner="alice")
        self.assertEqual([s["source_id"] for s in visible_sources([shared, private], ["shared", "private"], "bob", "2026-02-01")], ["shared"])
        result = {"output": {"fields": {}}, "actor": "alice", "as_of": "2026-01-01", "private_source_ids": ["private"]}
        self.assertEqual(handoffs_for({"depends_on": ["old"]}, {"old": result}, [shared]), [])
        self.assertEqual(len(handoffs_for({"depends_on": ["old"]}, {"old": result}, [shared, private])), 1)

    def test_checked_record_rejects_tampered_or_short_quotes_and_preserves_metadata(self):
        original = [source("s", "A sufficiently long exact operational quote.", revision="r7", state="adopted")]
        checked = checked_record({"excerpts": [{"source_id": "s", "quote": "A sufficiently long exact operational quote."}]}, original)
        self.assertEqual(checked[0]["revision"], "r7"); self.assertEqual(checked[0]["state"], "adopted")
        with self.assertRaises(ValueError): checked_record({"excerpts": [{"source_id": "s", "quote": "invented operational quote."}]}, original)
        with self.assertRaises(ValueError): checked_record({"excerpts": [{"source_id": "s", "quote": "short"}]}, original)

    def test_full12_and_reuse12_supply_identical_context_for_same_snapshot(self):
        sources = [source("s", "A sufficiently long exact operational rule for reuse.")]
        with tempfile.TemporaryDirectory() as tmp:
            fake_full, fake_reuse = FakeClient(), FakeClient()
            full = WorkflowEngine("full12", fake_full, Path(tmp) / "full")
            reuse = WorkflowEngine("reuse12", fake_reuse, Path(tmp) / "reuse")
            wave = {"wave": 1, "as_of": "2026-02-01", "available_source_ids": ["s"], "tasks": [task()]}
            full.run(sources, [wave], workers=1); reuse.run(sources, [wave], workers=1)
            full_payload = [p for k, p, _ in fake_full.calls if k == "operational_answer"][0]
            reuse_payload = [p for k, p, _ in fake_reuse.calls if k == "operational_answer"][0]
            self.assertEqual(full_payload["sources"], reuse_payload["sources"])
            self.assertEqual(full_payload["predecessor_handoffs"], reuse_payload["predecessor_handoffs"])

    def test_all_private_handoff_is_rejected_without_citation(self):
        private = source("private", "A sufficiently long private operational rule.", scope="private", owner="alice")
        result = {"output": {"fields": {}}, "actor": "alice", "as_of": "2026-01-01", "private_source_ids": ["private"]}
        self.assertEqual(handoffs_for({"depends_on": ["old"]}, {"old": result}, [],), [])

    def test_saved_record_rewrite_is_rejected_on_read(self):
        public = source("public", "A sufficiently long public operational rule.")
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("record12", client, Path(tmp) / "records")
            _, key, _ = engine.retrieve([public], "policy", "operations", "2026-02-01", "alice")
            record, _ = engine.record_context([public], key, "policy", "operations", "2026-02-01")
            path = Path(tmp) / "records" / ("record-" + key + ".json")
            tampered = copy.deepcopy(record); tampered["context"][0]["text"] = "tampered text that is not original"
            path.write_text(json.dumps(tampered))
            with self.assertRaises(ValueError): engine.record_context([public], key, "policy", "operations", "2026-02-01")

    def test_added_source_invalidates_record_key_and_rebuilds(self):
        public = source("public", "A sufficiently long public operational rule.")
        added = source("added", "A sufficiently long additional operational rule.")
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("record12", client, Path(tmp) / "records")
            selected1, key1, _ = engine.retrieve([public], "policy", "operations", "2026-02-01", "alice")
            engine.record_context(selected1, key1, "policy", "operations", "2026-02-01")
            selected2, key2, _ = engine.retrieve([public, added], "policy", "operations", "2026-02-01", "alice")
            self.assertNotEqual(key1, key2)
            engine.record_context(selected2, key2, "policy", "operations", "2026-02-01")
            self.assertEqual(client.n, 2)

    def test_shared_public_record_reuses_across_actor_but_private_record_is_separate(self):
        public = source("public", "A sufficiently long public operational rule.")
        private = source("private", "A sufficiently long private operational rule.", scope="private", owner="alice")
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("record12", client, Path(tmp) / "records")
            public_alice = [public]
            public_bob = [public]
            selected_a, key_a, _ = engine.retrieve(public_alice, "policy", "operations", "2026-02-01", "alice")
            selected_b, key_b, _ = engine.retrieve(public_bob, "policy", "operations", "2026-02-01", "bob")
            self.assertEqual(key_a, key_b)
            engine.record_context(selected_a, key_a, "policy", "operations", "2026-02-01")
            engine.record_context(selected_b, key_b, "policy", "operations", "2026-02-01")
            engine.record_context([private], digest([private]), "policy", "operations", "2026-02-01")
            self.assertEqual(client.n, 2)
            payloads = [payload for kind, payload, _ in client.calls if kind == "evidence_record"]
            self.assertTrue(any(any(item["source_id"] == "private" for item in payload["sources"]) for payload in payloads))
            self.assertTrue(any(all(item["source_id"] != "private" for item in payload["sources"]) for payload in payloads))

    def test_wave_update_rebuilds_record_after_revision_change(self):
        original = source("policy", "A sufficiently long adopted policy revision one.")
        updated = source("policy", "A sufficiently long adopted policy revision two.", revision="r2")
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(); engine = WorkflowEngine("record12", client, Path(tmp) / "records")
            selected1, key1, _ = engine.retrieve([original], "policy", "operations", "2026-02-01", "alice")
            engine.record_context(selected1, key1, "policy", "operations", "2026-02-01")
            selected2, key2, _ = engine.retrieve([updated], "policy", "operations", "2026-02-01", "alice")
            self.assertNotEqual(key1, key2)
            engine.record_context(selected2, key2, "policy", "operations", "2026-02-01")
            self.assertEqual(client.n, 2)


if __name__ == "__main__": unittest.main()
