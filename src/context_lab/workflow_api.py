"""Bounded Responses API client for synthetic workflow experiments.

This module is deliberately small: it keeps provider I/O, durable budget
reservations, and an auditable local trace together without deciding how a
workflow should retrieve or share evidence.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib import request, error
import uuid

from .budget import ExperimentBudget, token_cost

API_URL = "https://api.openai.com/v1/responses"
PRICING_URL = "https://developers.openai.com/api/docs/pricing"
MODEL = "gpt-6-luna"
DEFAULT_INPUT_RATE = "0.55"
DEFAULT_OUTPUT_RATE = "0.825"
FORBIDDEN_PARTS = ("gold", "rubric", "qid", "question_id", "expected", "answer_key", "fixture")


def _reject_eval_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_PARTS):
                raise ValueError("evaluation-only fields cannot be sent to the model")
            _reject_eval_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_eval_keys(child)


def _json_value(value):
    if not isinstance(value, (dict, list)):
        raise ValueError("payload must be an object or array")
    _reject_eval_keys(value)
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _post(body: dict, *, api_key: str, url: str = API_URL) -> dict:
    encoded = json.dumps(body, ensure_ascii=False).encode()
    req = request.Request(url, data=encoded, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())


def _text(body: dict) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    pieces = []
    for item in body.get("output", []):
        for part in item.get("content", []):
            if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                pieces.append(part["text"])
    if not pieces:
        raise ValueError("response has no output text")
    return "".join(pieces)


def _usage(body: dict) -> dict:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("provider usage is unavailable")
    result = {}
    for key, value in usage.items():
        if key.endswith("tokens") and type(value) is int and value >= 0:
            result[key] = value
        elif key.endswith("_tokens_details") and isinstance(value, dict):
            result[key] = json.loads(json.dumps(value))
    if type(result.get("input_tokens")) is not int or type(result.get("output_tokens")) is not int:
        raise ValueError("provider usage is incomplete")
    return result


def _flat_usage(value, prefix=""):
    flat = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}_{key}" if prefix else key
            flat.update(_flat_usage(child, name))
    elif type(value) is int and value >= 0 and prefix.endswith("tokens"):
        flat[prefix] = value
    return flat


def _validate_schema_definition(schema):
    if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ValueError("schema must describe an object with properties")
    if schema.get("additionalProperties") is not False or not isinstance(schema.get("required"), list):
        raise ValueError("schema must be strict and declare required fields")
    def check(spec):
        if not isinstance(spec, dict):
            raise ValueError("schema property is invalid")
        if "anyOf" in spec:
            if set(spec) != {"anyOf"} or not isinstance(spec["anyOf"], list) or not spec["anyOf"]:
                raise ValueError("invalid anyOf schema")
            for alternative in spec["anyOf"]: check(alternative)
            return
        types = spec.get("type")
        types = types if isinstance(types, list) else [types]
        if not types or any(t not in {"object", "array", "string", "number", "integer", "boolean", "null"} for t in types):
            raise ValueError("unsupported schema type")
        if "object" in types:
            props, required = spec.get("properties"), spec.get("required")
            if not isinstance(props, dict) or not isinstance(required, list) or spec.get("additionalProperties") is not False or set(required) != set(props):
                raise ValueError("every strict object property must be required")
            for key, child in props.items():
                if not isinstance(key, str): raise ValueError("schema keys must be strings")
                check(child)
        if "array" in types:
            check(spec.get("items"))
        if "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]):
            raise ValueError("enum must be nonempty")
    check(schema)


def nominal_cost_bounds(usage, *, write_ttl=None):
    """Default global endpoint rate card, 2026-11-02; never an invoice.

    Absent cache-write detail yields an interval rather than a zero-write guess.
    Reasoning tokens are already contained in output_tokens, not added again.
    """
    total, output = usage["input_tokens"], usage["output_tokens"]
    if write_ttl not in {None, "30m", "12h"}:
        raise ValueError("unsupported known write lifetime")
    details = usage.get("input_tokens_details", {})
    cached = details.get("cached_tokens", 0)
    if type(cached) is not int or not 0 <= cached <= total:
        raise ValueError("invalid cached token count")
    long = total > 272_000
    ordinary_rate, cached_rate, write30_rate, write12_rate, output_rate = (
        ("0.20", "0.02", "0.25", "0.50", "0.75") if long else
        ("0.10", "0.01", "0.125", "0.25", "0.50"))
    base = token_cost(cached, cached_rate) + token_cost(output, output_rate)
    writes = details.get("cache_write_tokens")
    if writes is None:
        return {"lower_nanodollars": base + token_cost(total-cached, ordinary_rate),
                "upper_nanodollars": base + token_cost(total-cached, write30_rate if write_ttl == "30m" else write12_rate),
                "point_nanodollars": None, "reason": "provider cache-write count unavailable"}
    if type(writes) is not int or writes < 0 or cached + writes > total:
        raise ValueError("invalid cache write token count")
    ordinary_cost = token_cost(total-cached-writes, ordinary_rate)
    if writes == 0:
        amount = base + ordinary_cost
        return {"lower_nanodollars": amount, "upper_nanodollars": amount,
                "point_nanodollars": amount, "reason": "provider explicitly reports zero writes"}
    parts = details.get("cache_write_tokens_details", {})
    w30, w12 = parts.get("ttl_30m_tokens"), parts.get("ttl_12h_tokens")
    if type(w30) is int and type(w12) is int and min(w30, w12) >= 0 and w30+w12 == writes:
        amount = base + ordinary_cost + token_cost(w30, write30_rate) + token_cost(w12, write12_rate)
        return {"lower_nanodollars": amount, "upper_nanodollars": amount,
                "point_nanodollars": amount, "reason": "provider write lifetimes complete"}
    if write_ttl is not None:
        amount = base + ordinary_cost + token_cost(writes, write30_rate if write_ttl == "30m" else write12_rate)
        return {"lower_nanodollars": amount, "upper_nanodollars": amount,
                "point_nanodollars": amount, "reason": "write lifetime from documented request setting: " + write_ttl}
    return {"lower_nanodollars": base + ordinary_cost + token_cost(writes, write30_rate),
            "upper_nanodollars": base + ordinary_cost + token_cost(writes, write12_rate),
            "point_nanodollars": None, "reason": "provider cache-write lifetime split unavailable"}


def _validate_output(value, schema):
    _validate_schema_definition(schema)
    def check(current, spec):
        if "anyOf" in spec:
            for alternative in spec["anyOf"]:
                try:
                    check(current, alternative)
                    return
                except ValueError:
                    continue
            raise ValueError("no anyOf type accepts the output")
        typ = spec.get("type")
        if isinstance(typ, list):
            if "null" in typ and current is None:
                if "enum" in spec and None not in spec["enum"]: raise ValueError("null absent from enum")
                return
            if not any(t != "null" and _matches_type(current, t) for t in typ): raise ValueError("structured output union type mismatch")
            typ = next(t for t in typ if t != "null" and _matches_type(current, t))
        elif typ == "null":
            if current is not None: raise ValueError("structured output null expected")
        if "enum" in spec and current not in spec["enum"]: raise ValueError("structured output enum mismatch")
        if typ == "object":
            if not isinstance(current, dict): raise ValueError("structured output object expected")
            props = spec.get("properties", {}); required = spec.get("required", [])
            if spec.get("additionalProperties") is False and set(current) - set(props): raise ValueError("structured output has extra fields")
            if any(k not in current for k in required): raise ValueError("structured output misses required field")
            for key, child in current.items():
                if key in props: check(child, props[key])
        elif typ == "array":
            if not isinstance(current, list): raise ValueError("structured output array expected")
            if isinstance(spec.get("items"), dict):
                for child in current: check(child, spec["items"])
        elif typ == "string" and not isinstance(current, str): raise ValueError("structured output string expected")
        elif typ == "boolean" and type(current) is not bool: raise ValueError("structured output boolean expected")
        elif typ == "number" and (type(current) not in (int, float) or not math.isfinite(current)): raise ValueError("structured output finite number expected")
        elif typ == "integer" and type(current) is not int: raise ValueError("structured output integer expected")
    check(value, schema)


def _matches_type(value, typ):
    return {"object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": type(value) is bool,
            "number": type(value) in (int, float), "integer": type(value) is int,
            "null": value is None}.get(typ, False)


def _atomic_json(path: Path, value: dict):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    except OSError:
        pass


class BudgetedClient:
    """One non-retrying API client whose attempts are durable and budgeted."""

    def __init__(self, ledger: ExperimentBudget, output_dir: str | Path, api_key: str | None = None,
                 *, input_rate: str = DEFAULT_INPUT_RATE, output_rate: str = DEFAULT_OUTPUT_RATE,
                 max_input_tokens: int = 1_050_000, model: str = MODEL):
        if model != MODEL:
            raise ValueError("only the verified gpt-6-luna model is supported")
        if not all(Decimal(rate).is_finite() for rate in (input_rate, output_rate)) or Decimal(input_rate) < Decimal(DEFAULT_INPUT_RATE) or Decimal(output_rate) < Decimal(DEFAULT_OUTPUT_RATE):
            raise ValueError("rates cannot be below the conservative verified floor")
        if max_input_tokens != 1_050_000:
            raise ValueError("workflow experiments reserve the verified full 1050000-token input bound")
        self.ledger = ledger
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required in memory")
        self.input_rate, self.output_rate = input_rate, output_rate
        self.max_input_tokens, self.model = max_input_tokens, model
        self._write_lock = threading.Lock()
        snapshot = {
            "model": model, "api_url": API_URL, "pricing_url": PRICING_URL,
            "pricing_date": "2026-11-02", "conservative_rates_usd_per_million": {
                "input": input_rate, "output": output_rate},
            "max_input_tokens": max_input_tokens, "automatic_retries": False,
            "invoice_measured": False, "credit_balance_measured": False,
            "pricing_snapshot": "runs/phase2-workflow-pricing-v3/pricing.json",
            "write_lifetime_basis": "documented default 30m; no ttl overrides are sent, including on explicit breakpoints",
            "nominal_short_rates_usd_per_million": {"input":"0.10", "cached":"0.01", "write_30m":"0.125", "write_12h":"0.25", "output":"0.50"},
            "long_context": "above 272000 input tokens: input/cache rates x2, output x1.5",
        }
        (self.output_dir / "pricing-snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")

    @property
    def reservation(self) -> int:
        return token_cost(self.max_input_tokens, self.input_rate) + token_cost(128000, self.output_rate)

    def complete(self, kind: str, payload, schema: dict, developer_prompt: str,
                 *, max_output_tokens: int = 4096, metadata: dict | None = None, source_first: bool = False,
                 cache_boundary: bool = False) -> dict:
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind is required")
        if not isinstance(schema, dict) or not isinstance(developer_prompt, str) or not developer_prompt:
            raise ValueError("schema and developer_prompt are required")
        _validate_schema_definition(schema)
        if type(max_output_tokens) is not int or max_output_tokens <= 0 or max_output_tokens > 128000:
            raise ValueError("max_output_tokens must be between 1 and 128000")
        safe_payload = _json_value(payload)
        if type(source_first) is not bool:
            raise ValueError("source_first must be boolean")
        if type(cache_boundary) is not bool or (cache_boundary and not source_first):
            raise ValueError("cache_boundary requires source_first")
        serialized_payload = safe_payload
        if source_first:
            if not isinstance(safe_payload, dict) or "sources" not in safe_payload:
                raise ValueError("source-first layout requires a sources array")
            serialized_payload = {"sources": safe_payload["sources"], **{k:v for k,v in safe_payload.items() if k != "sources"}}
        user_content = json.dumps(serialized_payload, ensure_ascii=False)
        if cache_boundary:
            user_content = [
                {"type": "input_text", "text": json.dumps({"sources": safe_payload["sources"]}, ensure_ascii=False),
                 "prompt_cache_breakpoint": {"mode": "explicit"}},
                {"type": "input_text", "text": json.dumps({k:v for k,v in safe_payload.items() if k != "sources"}, ensure_ascii=False)}]
        attempt_id = f"workflow-{uuid.uuid4().hex}"
        self.ledger.reserve(attempt_id, token_cost(self.max_input_tokens, self.input_rate) + token_cost(max_output_tokens, self.output_rate))
        request_body = {"model": self.model, "store": False, "service_tier": "default",
                        "max_output_tokens": max_output_tokens,
                        "input": [{"role": "developer", "content": developer_prompt},
                                  {"role": "user", "content": user_content}],
                        "text": {"format": {"type": "json_schema", "name": kind, "strict": True, "schema": schema}}}
        request_meta = {"attempt_id": attempt_id, "kind": kind, "source_version": (metadata or {}).get("source_version"),
                        "request_sha256": hashlib.sha256(json.dumps(request_body, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                        "prompt_sha256": hashlib.sha256(developer_prompt.encode()).hexdigest(),
                        "schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
                        "request": request_body, "metadata": metadata or {},
                        "client_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "status": "reserved", "reserved_at": time.time()}
        pending = self.output_dir / f"attempt-{attempt_id}.pending.json"
        _atomic_json(pending, request_meta)
        started = time.time(); start = time.perf_counter()
        body = None; usage = None; output_text = None; parsed = None; status = "error"; error_type = None
        conservative_cost = None; nominal_cost = None
        nominal_cost_reason = "provider usage unavailable"
        costs = None; ledger_status = "reserved"; http_status = None
        try:
            body = _post(request_body,
                         api_key=self.api_key)
            http_status = 200
            usage = _usage(body)
            conservative_cost = token_cost(usage["input_tokens"], self.input_rate) + token_cost(usage["output_tokens"], self.output_rate)
            self.ledger.settle(attempt_id, conservative_cost, _flat_usage(usage))
            ledger_status = "settled"
            # This client never emits TTL overrides. Explicit breakpoints
            # inherit the same documented 30m default.
            # The verified Responses API default is 30m; this remains an
            # estimate from usage/rate card, never a provider invoice.
            costs = nominal_cost_bounds(usage, write_ttl="30m")
            nominal_cost = costs["point_nanodollars"]
            nominal_cost_reason = costs["reason"]
            output_text = _text(body)
            parsed = json.loads(output_text)
            _validate_output(parsed, schema)
            if body.get("status") not in (None, "completed"):
                raise ValueError("provider response did not complete")
            status = "ok"
        except Exception as exc:
            error_type = type(exc).__name__
            if isinstance(exc, error.HTTPError): http_status = exc.code
            if usage is None:
                self.ledger.mark_uncertain(attempt_id)
                ledger_status = "uncertain"
            elif ledger_status != "settled":
                ledger_status = "settlement_failed_check_ledger"
        artifact = {"attempt_id": attempt_id, "kind": kind, "status": status,
                    "model": self.model, "metadata": metadata if isinstance(metadata, dict) else {},
                    "source_first": source_first, "cache_boundary": cache_boundary,
                    "payload": safe_payload, "usage": usage, "output": parsed, "output_text": output_text,
                    "nominal_cost_estimate_nanodollars": nominal_cost,
                    "conservative_cost_nanodollars": conservative_cost,
                    "nominal_cost_reason": nominal_cost_reason,
                    "nominal_cost_bounds": costs, "ledger_status": ledger_status, "http_status": http_status,
                    "request": request_body, "client_source_sha256": request_meta["client_source_sha256"],
                    "error_type": error_type, "started_at": started, "ended_at": time.time(),
                    "latency_seconds": time.perf_counter() - start,
                    "request_sha256": request_meta["request_sha256"], "prompt_sha256": request_meta["prompt_sha256"],
                    "schema_sha256": request_meta["schema_sha256"], "source_version": request_meta["source_version"],
                    "response_id": body.get("id") if isinstance(body, dict) else None,
                    "response_status": body.get("status") if isinstance(body, dict) else None,
                    "incomplete_details": body.get("incomplete_details") if isinstance(body, dict) and isinstance(body.get("incomplete_details"), dict) else None}
        with self._write_lock:
            _atomic_json(self.output_dir / f"attempt-{attempt_id}.json", artifact)
            pending.unlink(missing_ok=True)
        return artifact
