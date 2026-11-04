"""Audits must check saved bytes with the measured unit and fail on replay drift."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from scripts.audit_completion_payloads import audit_run
from context_lab.completion_eval import SOURCES, VARIANTS
from context_lab.metrics import UnitCounter
from context_lab.release_eval import run
from context_lab.retrieval_completion import CompletionConfig, CompletionRetrieval
from context_lab.retrieval_adaptive import AdaptiveConfig, AdaptiveRetrieval


class CompletionAuditTests(unittest.TestCase):
    def _adaptive_run(self, root):
        fixture = root / "fixture"
        fixture.mkdir()
        corpus = {"documents": [{
            "id": "doc-1", "title": "Tiny source", "source_url": "https://example.test/tiny",
            "recorded_at": "2026-01-01", "verified_at": "2026-01-01", "scope": "shared",
            "body": "# Heading\nAlpha evidence phrase.\nBeta evidence phrase.\n",
            "sections": [
                {"id": "s1", "heading": "Heading", "kind": "fact", "text": "Alpha evidence phrase.", "adoption_status": "na", "valid_from": None, "valid_to": None, "verified_at": "2026-01-01"},
                {"id": "s2", "heading": "Heading", "kind": "fact", "text": "Beta evidence phrase.", "adoption_status": "na", "valid_from": None, "valid_to": None, "verified_at": "2026-01-01"},
            ],
        }]}
        queries = {"queries": [{"id": "q1", "category": "tiny", "request": {"text": "Alpha evidence", "actor": "tester", "scope": "shared", "mode": "search"}, "rubric": {"required": [], "forbidden": []}}]}
        (fixture / "corpus.json").write_text(json.dumps(corpus))
        (fixture / "dev.json").write_text(json.dumps(queries))
        run_path = root / "run"
        run(fixture / "corpus.json", fixture / "dev.json", run_path,
            {"adaptive": {"compact_spans": True, "safe_document_packing": True, "candidate_limit": 1}},
            [(1, 81234)], repeats=1, budgets=(1000,), engine_class=AdaptiveRetrieval,
            config_class=AdaptiveConfig, source_names=SOURCES + ("retrieval_adaptive.py",))
        metadata = json.loads((run_path / "metadata.json").read_text())
        metadata["adaptive_ablation"] = True
        (run_path / "metadata.json").write_text(json.dumps(metadata))
        return run_path

    def test_adaptive_document_body_audit_and_tamper_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_path = self._adaptive_run(root)
            self.assertEqual("pass", audit_run(run_path, root / "good", root / "fixture")["status"])
            original = [json.loads(line) for line in (run_path / "payloads.jsonl").read_text().splitlines()]
            for field, value, kind in (("text", "tampered", "document_body"), ("adoption_status", "adopted", "document_body"), ("spans", [[1, 2]], "document_body")):
                rows = deepcopy(original)
                item = json.loads(rows[0]["payload"])
                item["items"][0][field] = value
                rows[0]["payload"] = json.dumps(item)
                (run_path / "payloads.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
                result = audit_run(run_path, root / ("bad_" + field), root / "fixture")
                self.assertTrue(any(error["kind"] == kind for error in result["errors"]))
            rows = deepcopy(original)
            item = json.loads(rows[0]["payload"])
            item["sources"]["doc-1"]["source_url"] = "https://evil.example"
            rows[0]["payload"] = json.dumps(item)
            (run_path / "payloads.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
            result = audit_run(run_path, root / "bad_source", root / "fixture")
            self.assertTrue(any(error["kind"] == "source_metadata" for error in result["errors"]))
    def test_token_replay_and_consistently_rehashed_saved_payload_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = Path("fixtures/phase2-completion-v7")
            run_path = root/"run"
            run(fixture/"corpus.json", fixture/"dev.json", run_path,
                {"control": VARIANTS["control"]}, [(80, 81234)], repeats=1, budgets=(1000,),
                engine_class=CompletionRetrieval, config_class=CompletionConfig, source_names=SOURCES)
            self.assertEqual("pass", audit_run(run_path, root/"good")["status"])
            payloads = [json.loads(line) for line in (run_path/"payloads.jsonl").read_text().splitlines()]
            row = next(item for item in payloads if item["method"] == "A")
            row["payload"] += "\n"
            row["payload_sha256"] = hashlib.sha256(row["payload"].encode()).hexdigest()
            results = json.loads((run_path/"results.json").read_text())
            for result in results:
                if all(result[k] == row[k] for k in ("variant", "method", "budget", "size", "seed", "query_id")):
                    result["payload_sha256"] = row["payload_sha256"]
                    result["units"] = UnitCounter("o200k_base")(row["payload"])
            (run_path/"results.json").write_text(json.dumps(results))
            (run_path/"payloads.jsonl").write_text("".join(json.dumps(item)+"\n" for item in payloads))
            result = audit_run(run_path, root/"drift")
            self.assertEqual(0, result["error_count"])
            self.assertEqual(1, result["replay_mismatch_count"])
            self.assertEqual("fail", result["status"])
            row["payload"] += " "  # Now corrupt bytes without updating the stored hash.
            (run_path/"payloads.jsonl").write_text("".join(json.dumps(item)+"\n" for item in payloads))
            result = audit_run(run_path, root/"corrupt")
            self.assertEqual("fail", result["status"])
            self.assertTrue(any(error["kind"] == "saved_payload_hash" for error in result["errors"]))
