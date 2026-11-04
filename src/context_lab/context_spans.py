"""Lossless compaction of overlapping source spans in a retrieved context."""
from __future__ import annotations

from copy import deepcopy


def _validate_span(span):
    if not isinstance(span, dict) or set(span) != {"start", "end", "text"}:
        raise ValueError("span must contain exactly start, end, text")
    if isinstance(span.get("start"), bool) or isinstance(span.get("end"), bool) or not isinstance(span.get("start"), int) or not isinstance(span.get("end"), int):
        raise ValueError("span offsets must be integers")
    if span["start"] < 0 or span["end"] <= span["start"] or not isinstance(span.get("text"), str):
        raise ValueError("invalid span")
    if len(span["text"]) != span["end"] - span["start"]:
        raise ValueError("span text length does not match offsets")


def _merge_group(group):
    for span in group:
        _validate_span(span)
    group = sorted(group, key=lambda s: (s["start"], s["end"]))
    merged = []
    for span in group:
        if not merged:
            merged.append(dict(span)); continue
        cur = merged[-1]
        if span["start"] > cur["end"]:
            merged.append(dict(span)); continue
        overlap = cur["end"] - span["start"]
        if overlap == 0:
            suffix = span["text"]
        elif span["end"] <= cur["end"]:
            offset = span["start"] - cur["start"]
            if cur["text"][offset:offset + len(span["text"])] != span["text"]:
                raise ValueError("overlapping span text mismatch")
            suffix = ""
        else:
            if cur["text"][-overlap:] != span["text"][:overlap]:
                raise ValueError("overlapping span text mismatch")
            suffix = span["text"][overlap:]
        cur["text"] += suffix
        cur["end"] = max(cur["end"], span["end"])
    return merged


def compact_context(context):
    """Return a deep-copied context with losslessly merged same-source spans.

    Only overlapping, containing, or adjacent intervals are merged. Gaps stay
    as separate spans. Body records and all metadata are preserved.
    """
    if not isinstance(context, dict) or not isinstance(context.get("sources"), list):
        raise ValueError("context.sources must be a list")
    result = deepcopy(context)
    for record in result["sources"]:
        spans = record.get("spans")
        if spans is None:
            continue
        if not isinstance(spans, list):
            raise ValueError("source spans must be a list")
        record["spans"] = _merge_group(spans)
    return result
