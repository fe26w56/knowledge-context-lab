import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from context_lab.budget import ExperimentBudget, nanodollars
from context_lab.model_eval import ModelConfig, OUTPUT_SCHEMA, _extract_output, run_tasks, sanitize_request, sanitize_retrieved_payload


def response(answer="ok", input_tokens=10, output_tokens=5, response_id="resp-test"):
    value = {"answer": answer, "abstain": False, "claims": [], "missing_information": []}
    return {"id": response_id, "status": "completed", "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "output_text": json.dumps(value)}


class ModelEvalTests(unittest.TestCase):
    def config(self, **kwargs):
        values = {"model": "gpt-6-luna", "max_input_tokens": 1_050_000, "max_output_tokens": 20}
        values.update(kwargs)
        return ModelConfig(**values)

    def task(self, **kwargs):
        value = {"request": {"text": "synthetic question", "scope": "public", "mode": "answer", "as_of": "2026-01-01"},
                 "retrieved_payload": {"mode": "answer", "as_of": "2026-01-01", "items": [{"document_id": "d1", "text": "synthetic evidence"}], "sources": {}, "budget_limited": False, "warnings": []}}
        value.update(kwargs)
        return value

    def test_schema_is_strict_and_gold_is_rejected_before_http(self):
        self.assertFalse(OUTPUT_SCHEMA.get("additionalProperties"))
        with self.assertRaises(ValueError):
            sanitize_request({"text": "q", "gold": "answer"})
        with self.assertRaises(ValueError):
            sanitize_retrieved_payload("{not-json")
        with self.assertRaises(ValueError):
            sanitize_retrieved_payload({"mode": "answer", "as_of": "today", "items": [{"document_id": "d", "gold": "x"}], "sources": {}, "budget_limited": False, "warnings": []})

    def test_model_and_output_directory_are_explicit_and_non_overwriting(self):
        with self.assertRaises(ValueError):
            ModelConfig("other-model")
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            ledger = ExperimentBudget(Path(temp) / "ledger.sqlite", cap_usd="10")
            with patch("context_lab.model_eval._post", return_value=response()):
                run_tasks([self.task()], out, ledger, self.config(), api_key="secret")
                with self.assertRaises(FileExistsError):
                    run_tasks([self.task()], out, ledger, self.config(), api_key="secret")

    def test_success_persists_whitelisted_response_and_no_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            ledger = ExperimentBudget(Path(temp) / "ledger.sqlite", cap_usd="10")
            with patch("context_lab.model_eval._post", return_value=response()) as post:
                report = run_tasks([self.task()], out, ledger, self.config(), api_key="secret-not-artifact")
            post.assert_called_once()
            sent = post.call_args.args[0]
            self.assertNotIn("gold", json.dumps(sent))
            artifact = json.loads((out / "attempt-0000.json").read_text())
            self.assertEqual(artifact["status"], "ok")
            self.assertEqual(artifact["task_index"], 0)
            self.assertNotIn("secret-not-artifact", (out / "run.json").read_text())
            self.assertEqual(report["attempts"][0]["output"]["answer"], "ok")

    def test_invalid_and_budget_denied_attempts_are_persisted_and_mapped(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            ledger = ExperimentBudget(Path(temp) / "ledger.sqlite", cap_usd="0.6")
            tasks = [
                {"task_key": "invalid-0", "request": {"text": 123, "private_invalid": "do not persist"}},
                self.task(task_key="valid-1"),
                self.task(task_key="valid-2"),
            ]
            with patch("context_lab.model_eval._post", side_effect=OSError("private provider body")) as post:
                report = run_tasks(tasks, out, ledger, self.config(), max_workers=3, api_key="secret")

            self.assertEqual(len(report["attempts"]), len(tasks))
            self.assertEqual({row["task_index"] for row in report["attempts"]}, {0, 1, 2})
            self.assertEqual({row["task_key"] for row in report["attempts"]}, {"invalid-0", "valid-1", "valid-2"})
            statuses = {row["task_index"]: row["status"] for row in report["attempts"]}
            self.assertEqual(statuses[0], "invalid_input")
            self.assertEqual(sorted(statuses.values()).count("budget_exceeded"), 1)
            self.assertEqual(sorted(statuses.values()).count("error"), 1)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(sorted(p.name for p in out.glob("attempt-*.json")),
                             ["attempt-0000.json", "attempt-0001.json", "attempt-0002.json"])
            run_text = (out / "run.json").read_text()
            self.assertNotIn("do not persist", run_text)
            for index in range(3):
                artifact = json.loads((out / f"attempt-{index:04d}.json").read_text())
                self.assertEqual(artifact["task_index"], index)
                self.assertNotIn("do not persist", json.dumps(artifact))

    def test_invalid_task_key_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            ledger = ExperimentBudget(Path(temp) / "ledger.sqlite", cap_usd="10")
            private_sentinel = "PRIVATE_INVALID_TASK_KEY_SENTINEL"
            task = self.task(task_key={"private": private_sentinel})
            with patch("context_lab.model_eval._post") as post:
                report = run_tasks([task], out, ledger, self.config(), api_key="secret")

            post.assert_not_called()
            self.assertEqual(report["attempts"][0]["status"], "invalid_input")
            self.assertIsNone(report["attempts"][0]["task_key"])
            self.assertNotIn(private_sentinel, (out / "attempt-0000.json").read_text())
            self.assertNotIn(private_sentinel, (out / "run.json").read_text())

    def test_transport_failure_marks_uncertain_and_retains_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = ExperimentBudget(Path(temp) / "ledger.sqlite", cap_usd="1")
            with patch("context_lab.model_eval._post", side_effect=OSError("private provider body")):
                report = run_tasks([self.task()], Path(temp) / "out", ledger, self.config(), api_key="secret")
            self.assertEqual(report["attempts"][0]["status"], "error")
            self.assertEqual(ledger.report()["attempts"][0]["status"], "uncertain")
            self.assertNotIn("private provider body", (Path(temp) / "out" / "run.json").read_text())

    def test_usage_parser_rejects_missing_or_extra_output_fields(self):
        bad = response()
        value = json.loads(bad["output_text"])
        value["gold"] = "must not pass"
        bad["output_text"] = json.dumps(value)
        with self.assertRaises(ValueError):
            _extract_output(bad)

    def test_concurrent_reservations_stop_at_cap_without_redispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = ExperimentBudget(Path(temp) / "ledger.sqlite", cap_usd="0.001")
            config = self.config(max_output_tokens=20)
            with patch("context_lab.model_eval._post", side_effect=OSError("simulated transport failure")) as post:
                report = run_tasks([self.task() for _ in range(20)], Path(temp) / "out", ledger, config,
                                   max_workers=16, api_key="secret")
            statuses = [item["status"] for item in report["attempts"]]
            self.assertIn("budget_exceeded", statuses)
            self.assertLessEqual(post.call_count, 14)
            self.assertEqual(len({item["attempt_id"] for item in report["attempts"]}), 20)

    def test_real_retrieval_envelopes_pass_without_gold_or_task_key_sent(self):
        from context_lab.retrieval_v2 import FileAdapter
        from context_lab.retrieval_release import ReleaseRetrieval
        from context_lab.retrieval_completion import CompletionConfig, CompletionRetrieval
        with tempfile.TemporaryDirectory() as temp:
            document = dict(id="example", title="Audit", scope="shared", body="Keep audit records for 30 days.",
                sections=[dict(id="example-rule",heading="Rule",kind="decision",adoption_status="adopted",
                               text="Keep audit records for 30 days.")])
            adapter = FileAdapter.create(Path(temp)/"documents", [document])
            req = dict(text="audit records",actor="reader",mode="search")
            tasks=[]
            engines = [ReleaseRetrieval(adapter),CompletionRetrieval(adapter,CompletionConfig(compact_spans=True))]
            for index, engine in enumerate(engines):
                for full in (False,True):
                    payload = engine.retrieve(req,full=full)["payload"]
                    sanitize_retrieved_payload(payload)
                    tasks.append(dict(task_key=f"offline-{index}-{full}",request=req,retrieved_payload=payload))
            ledger=ExperimentBudget(Path(temp)/"ledger.sqlite",cap_usd="10")
            with patch("context_lab.model_eval._post",return_value=response()) as post:
                report=run_tasks(tasks,Path(temp)/"run",ledger,self.config(),api_key="test-secret")
            self.assertTrue(all(row["status"]=="ok" for row in report["attempts"]))
            self.assertEqual(4,post.call_count)
            for call in post.call_args_list:
                self.assertNotIn("offline-",json.dumps(call.args[0]))


if __name__ == "__main__":
    unittest.main()
