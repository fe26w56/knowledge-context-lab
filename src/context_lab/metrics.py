"""Unit counters. Reference encoding is never reported as provider usage."""
from __future__ import annotations

from functools import lru_cache


class UnitCounter:
    def __init__(self, unit: str = "chars"):
        self.unit = "unicode_chars" if unit == "chars" else f"reference_tokens:{unit}"
        self.name = self.unit
        self.encoding = None
        if unit != "chars":
            try:
                import tiktoken
            except ImportError as exc:
                raise RuntimeError("Install the tokens extra or explicitly select --unit chars. No silent token estimate is used.") from exc
            self.encoding = tiktoken.get_encoding(unit)

    @lru_cache(maxsize=8192)
    def __call__(self, text: str) -> int:
        if self.encoding is None:
            return len(text)
        return len(self.encoding.encode(text, disallowed_special=()))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * fraction
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)
