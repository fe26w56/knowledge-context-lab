"""Fail-closed, counted-input Responses client for the live stability experiment.

This module is intentionally separate from ``workflow_api.BudgetedClient``.
It counts the exact input/schema first, reserves only that bound plus slack, and
never retries a request whose provider usage is uncertain.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from urllib import request

from .budget import ExperimentBudget, BudgetExceeded, token_cost
from .workflow_api import (
    API_URL, MODEL, DEFAULT_INPUT_RATE, DEFAULT_OUTPUT_RATE, _atomic_json,
    _flat_usage, _json_value, _text, _usage, _validate_output, _validate_schema_definition,
    nominal_cost_bounds,
)

COUNT_URL = API_URL + "/input_tokens"
MAX_OUTPUT_TOKENS = 2048
MAX_CONTEXT_TOKENS = 1_050_000


def _default_transport(body: dict, url: str, api_key: str) -> dict:
    encoded = json.dumps(body, ensure_ascii=False).encode()
    req = request.Request(url, data=encoded, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())


def _ceil_ten_percent(tokens: int) -> int:
    return max(1024, int((Decimal(tokens) * Decimal("0.10")).to_integral_value(rounding=ROUND_CEILING)))


class CountedClient:
    """One counted, non-retrying Responses request with durable accounting."""

    def __init__(self, ledger: ExperimentBudget, output_dir: str | Path, api_key: str,
                 *, input_rate: str = DEFAULT_INPUT_RATE, output_rate: str = DEFAULT_OUTPUT_RATE,
                 model: str = MODEL, transport=None):
        if model != MODEL:
            raise ValueError("only the verified gpt-6-luna model is supported")
        if not api_key or not isinstance(api_key, str):
            raise ValueError("an API key held in memory is required")
        if Decimal(input_rate) < Decimal(DEFAULT_INPUT_RATE) or Decimal(output_rate) < Decimal(DEFAULT_OUTPUT_RATE):
            raise ValueError("rates cannot be below the conservative verified floor")
        self.ledger, self.output_dir, self.api_key = ledger, Path(output_dir), api_key
        self.input_rate, self.output_rate, self.model = input_rate, output_rate, model
        self.transport = transport or _default_transport
        self._count_cache = {}
        self.output_dir.mkdir(parents=True, exist_ok=False)
        _atomic_json(self.output_dir / "config.json", {
            "model": model, "count_url": COUNT_URL, "responses_url": API_URL,
            "automatic_retries": False, "store": False, "service_tier": "default",
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "conservative_rates_usd_per_million": {"input": input_rate, "output": output_rate},
            "key_stored": "in_memory_only", "invoice_measured": False,
        })

    def _request_bodies(self, prompt, payload, schema, max_output_tokens):
        safe_payload = _json_value(payload)
        user_content = json.dumps(safe_payload, ensure_ascii=False, sort_keys=True)
        text = {"format": {"type": "json_schema", "name": "stability_result",
                            "strict": True, "schema": schema}}
        common = {"model": self.model,
                  "input": [{"role": "developer", "content": prompt},
                             {"role": "user", "content": user_content}],
                  "text": text}
        count_body = common
        generation_body = {**common, "store": False, "service_tier": "default",
                           "max_output_tokens": max_output_tokens}
        return count_body, generation_body, safe_payload

    def _count(self, body):
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if digest in self._count_cache:
            return self._count_cache[digest], digest
        response = self.transport(body, COUNT_URL, self.api_key)
        count = response.get("input_tokens") if isinstance(response, dict) else None
        if type(count) is not int or count < 0:
            raise ValueError("input token count is unavailable")
        self._count_cache[digest] = count
        _atomic_json(self.output_dir / f"count-{digest}.json", {
            "count_request_sha256": digest, "input_tokens": count, "model": self.model})
        return count, digest

    def _halt_budget(self):
        with sqlite3.connect(self.ledger.path, timeout=30, isolation_level=None) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE experiment_budget SET halted=1")
            db.execute("COMMIT")

    def estimate(self, prompt, payload, schema, max_output_tokens=MAX_OUTPUT_TOKENS):
        """Count and bound a request without reserving or dispatching generation."""
        if not isinstance(prompt, str) or not prompt or not isinstance(schema, dict):
            raise ValueError("prompt and schema are required")
        if type(max_output_tokens) is not int or max_output_tokens <= 0 or max_output_tokens > MAX_OUTPUT_TOKENS:
            raise ValueError("max_output_tokens is outside the stability limit")
        _validate_schema_definition(schema)
        count_body, _, _ = self._request_bodies(prompt, payload, schema, max_output_tokens)
        counted, count_hash = self._count(count_body)
        if counted == 0 and count_body["input"]:
            raise ValueError("nonempty input was counted as zero")
        if counted + max_output_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError("counted input exceeds context limit")
        slack = _ceil_ten_percent(counted)
        input_bound = counted + slack
        reservation = token_cost(input_bound, self.input_rate) + token_cost(max_output_tokens, self.output_rate)
        return {"count": counted, "input_bound": input_bound, "reservation_nanodollars": reservation,
                "count_request_sha256": count_hash}

    def complete(self, prompt, payload, schema, max_output_tokens=MAX_OUTPUT_TOKENS, metadata=None):
        if not isinstance(prompt, str) or not prompt or not isinstance(schema, dict):
            raise ValueError("prompt and schema are required")
        if type(max_output_tokens) is not int or max_output_tokens <= 0 or max_output_tokens > MAX_OUTPUT_TOKENS:
            raise ValueError("max_output_tokens is outside the stability limit")
        _validate_schema_definition(schema)
        try:
            estimate = self.estimate(prompt, payload, schema, max_output_tokens)
        except Exception as exc:
            _atomic_json(self.output_dir / f"count-failure-{uuid.uuid4().hex}.json", {
                "status": "count_failed", "error_type": type(exc).__name__,
                "http_status": getattr(exc, "code", None) if isinstance(getattr(exc, "code", None), int) else None,
                "generation_dispatched": False})
            raise
        count_body, generation_body, safe_payload = self._request_bodies(prompt, payload, schema, max_output_tokens)
        counted = estimate["count"]
        input_bound = estimate["input_bound"]
        count_hash = estimate["count_request_sha256"]
        attempt_id = f"stability-{uuid.uuid4().hex}"
        reservation = token_cost(input_bound, self.input_rate) + token_cost(max_output_tokens, self.output_rate)
        self.ledger.reserve(attempt_id, reservation)
        request_hash = hashlib.sha256(json.dumps(generation_body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        pending = {"attempt_id": attempt_id, "status": "reserved", "model": self.model,
                   "request_sha256": request_hash, "count_request_sha256": count_hash,
                   "counted_input_tokens": counted, "input_bound": input_bound,
                   "reservation_nanodollars": reservation, "metadata": metadata or {},
                   "created_at": time.time()}
        pending_path = self.output_dir / f"attempt-{attempt_id}.pending.json"
        _atomic_json(pending_path, pending)
        body = None; usage = None; status = "error"; output = None; error_type = None
        ledger_status = "reserved"; conservative_cost = None; costs = None
        try:
            body = self.transport(generation_body, API_URL, self.api_key)
            usage = _usage(body)
            actual_input = usage["input_tokens"]
            conservative_cost = token_cost(actual_input, self.input_rate) + token_cost(usage["output_tokens"], self.output_rate)
            if actual_input > input_bound:
                # Settle the actual conservative cost, then halt independently.
                try:
                    self.ledger.settle(attempt_id, conservative_cost, _flat_usage(usage))
                finally:
                    self._halt_budget()
                raise BudgetExceeded("actual input exceeded counted reservation")
            self.ledger.settle(attempt_id, conservative_cost, _flat_usage(usage))
            ledger_status = "settled"
            costs = nominal_cost_bounds(usage, write_ttl="30m")
            parsed = json.loads(_text(body))
            _validate_output(parsed, schema)
            if body.get("status") not in (None, "completed"):
                raise ValueError("provider response did not complete")
            output, status = parsed, "ok"
        except Exception as exc:
            error_type = type(exc).__name__
            overshoot = usage is not None and usage["input_tokens"] > input_bound and error_type == "BudgetExceeded"
            if overshoot:
                ledger_status = "halted_input_overshoot"
            elif usage is None:
                try:
                    self.ledger.mark_uncertain(attempt_id)
                    ledger_status = "uncertain"
                except Exception:
                    ledger_status = "uncertain_unverified"
            elif ledger_status != "settled":
                ledger_status = "settlement_failed_check_ledger"
        artifact = {"attempt_id": attempt_id, "status": status, "model": self.model,
                    "output": output, "usage": usage, "ledger_status": ledger_status,
                    "conservative_cost_nanodollars": conservative_cost,
                    "nominal_cost_bounds": costs, "error_type": error_type,
                    "request_sha256": request_hash, "count_request_sha256": count_hash,
                    "counted_input_tokens": counted, "input_bound": input_bound,
                    "request": generation_body, "payload": safe_payload,
                    "metadata": metadata or {}, "response_id": body.get("id") if isinstance(body, dict) else None,
                    "response_model": body.get("model") if isinstance(body, dict) else None,
                    "system_fingerprint": body.get("system_fingerprint") if isinstance(body, dict) else None,
                    "raw_output_text": body.get("output_text") if isinstance(body, dict) and isinstance(body.get("output_text"), str) else None,
                    "provider_output": body.get("output") if isinstance(body, dict) else None,
                    "response_status": body.get("status") if isinstance(body, dict) else None,
                    "incomplete_details": body.get("incomplete_details") if isinstance(body, dict) and isinstance(body.get("incomplete_details"), dict) else None}
        _atomic_json(self.output_dir / f"attempt-{attempt_id}.json", artifact)
        pending_path.unlink(missing_ok=True)
        return {"output": output, "status": status, "usage": usage,
                "request_sha256": request_hash, "count_request_sha256": count_hash,
                "counted_input_tokens": counted, "input_bound": input_bound,
                "metadata": artifact}
