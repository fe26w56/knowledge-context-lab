"""Opt-in, content-free local observation events and summaries."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import stat
import tempfile
import uuid
import math
from datetime import datetime, timezone
from statistics import median


KINDS = {"diagnostic", "operational"}
OPERATIONS = {"search", "context"}
MODES = {"raw", "normalized", "current", "compact", "capture", "context"}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


class ObservationSink:
    """Write one redacted event per atomically-created JSON file."""

    def __init__(self, directory: str | Path, *, kind: str):
        if kind not in KINDS:
            raise ValueError("observation kind must be diagnostic or operational")
        self.directory = Path(directory).expanduser().resolve()
        self.kind = kind
        if not self.directory.exists():
            self.directory.mkdir(parents=True, mode=0o700)
            os.chmod(self.directory, stat.S_IRWXU)

    def record(self, *, operation: str, actor: str, request: str, mode: str,
               settings: dict, started: float, result=None, error: Exception | None = None) -> None:
        import time
        event = {
            "event_id": str(uuid.uuid4()),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "kind": self.kind,
            "operation": operation if isinstance(operation, str) and operation in OPERATIONS else "invalid",
            "status": "error" if error else "ok",
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "mode": mode if isinstance(mode, str) and mode in MODES else "invalid",
            "settings_digest": _digest(settings),
            "request_digest": _digest(request),
            "actor_digest": _digest(actor),
            "payload_digest": None if error else _digest(result),
            "result_count": 0 if error else len(result.get("sources", [])) if isinstance(result, dict) else 0,
            "error_type": type(error).__name__ if error else None,
        }
        fd, temp_name = tempfile.mkstemp(prefix=".event-", suffix=".json", dir=self.directory)
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(event, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.directory / f"{event['event_id']}.json")
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise


def summarize(directory: str | Path, *, kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError("observation kind must be diagnostic or operational")
    rows = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            uuid.UUID(path.stem)
        except ValueError:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("kind") == kind:
            duration = data.get("duration_ms")
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                raise ValueError("observation duration must be a finite nonnegative number")
            if data.get("status") not in {"ok", "error"}:
                raise ValueError("invalid observation status")
            rows.append(data)
    successes = [row for row in rows if row.get("status") == "ok"]
    durations = sorted(row["duration_ms"] for row in rows)
    retrieval_keys = [(row.get("operation"), row.get("request_digest"),
                       row.get("payload_digest"), row.get("mode"), row.get("settings_digest"))
                      for row in successes]
    exact_keys = [(key, row.get("actor_digest")) for key, row in zip(retrieval_keys, successes)]
    actors_by_retrieval = {}
    for key, actor in exact_keys:
        actors_by_retrieval.setdefault(key, set()).add(actor)
    repeats = len(exact_keys) - len(set(exact_keys))
    p95 = durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None
    return {"kind": kind, "events": len(rows), "successes": len(successes),
            "failures": len(rows) - len(successes), "exact_repeat_events": repeats,
            "exact_repeat_rate": repeats / len(successes) if successes else 0.0,
            "actor_label_count": len({row.get("actor_digest") for row in rows}),
            "empty_result_successes": sum(row.get("result_count", 0) == 0 for row in successes),
            "same_retrieval_repeat_events": len(retrieval_keys) - len(set(retrieval_keys)),
            "cross_actor_overlap_groups": sum(len(actors) > 1 for actors in actors_by_retrieval.values()),
            "cross_actor_repeated_retrievals": sum(len(actors) - 1 for actors in actors_by_retrieval.values()),
            "duration_median_ms": median(durations) if durations else None,
            "duration_p95_ms": p95, "measured_business_benefit": False,
            "identity_note": "actor labels are trusted caller configuration, not authenticated identities",
            "repeat_note": "exact repeats are within one actor; cross-actor repeats count additional distinct actor labels for identical retrievals, not sharing authorization or saved work",
            "timing_note": "duration covers the operation attempt before observation file I/O"}
