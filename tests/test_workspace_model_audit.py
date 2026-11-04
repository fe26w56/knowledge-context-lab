import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_workspace_model_results import audit


class PrivateModelAuditTests(unittest.TestCase):
    def test_paired_equality_citation_failures_and_private_content_exclusion(self):
        secret_label = "PRIVATE-SOURCE-SENTINEL"
        case = "private-evaluation-case-42"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {"request": secret_label, "sources": [
                {"source_id": secret_label, "capture": {"text": secret_label}}]}
            request = {"input": payload, "model": "test-model"}
            request_hash = hashlib.sha256(json.dumps(request, sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest()
            entries = []
            for condition in ("notion_fetch", "file_mirror"):
                run = root / condition
                run.mkdir()
                response = {"status": "ok", "request": request, "request_sha256": request_hash,
                            "payload": payload, "output": {"claims": [
                                {"source_id": secret_label, "quote": secret_label},
                                {"source_id": secret_label, "quote": "invented quotation"}]},
                            "usage": {"input_tokens": 100, "output_tokens": 50},
                            "latency_seconds": 2.0, "nominal_cost_estimate_nanodollars": 10,
                            "conservative_cost_nanodollars": 20}
                (run / "results.json").write_text(json.dumps([{"case": case, "response": response}]))
                entries.append({"case": case, "condition": condition, "run": str(run),
                                "acquisition": {"exact_capture_equal": True, "fetch_ms": 500,
                                                "payload_equal": True, "local_acquisition_seconds": .01}})
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(entries))
            result = audit(manifest)
            self.assertEqual(result["byte_equal_api_requests"], 1)
            for aggregate in result["aggregates"].values():
                self.assertEqual(aggregate["exact_capture_quotes"], 1)
                self.assertEqual(aggregate["all_quotes_exact"], 0)
            serialized = json.dumps(result)
            for private in (secret_label, case, str(root), "invented quotation"):
                self.assertNotIn(private, serialized)
            self.assertFalse(result["scope"]["semantic_quality_scored"])
            entries[1]["acquisition"]["payload_equal"] = False
            manifest.write_text(json.dumps(entries))
            with self.assertRaisesRegex(ValueError, "local payload mismatch"):
                audit(manifest)


if __name__ == "__main__":
    unittest.main()
