"""Transfer an authorized handoff relative to a reader's retained revision.

The caller supplies a freshly authorized, complete current view. The service
authenticates principal/scope and protects its cursors at its own boundary.
A purge refers to an ID the reader already held and carries no former content.
"""
from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher


def snapshot_digest(pages: dict[str, str], *, principal: str, scope: str) -> str:
    if not all(isinstance(value, str) and value.strip() for value in (principal, scope)):
        raise ValueError("a trusted principal and scope are required")
    if not isinstance(pages, dict) or not all(
        isinstance(key, str) and key and isinstance(body, str) for key, body in pages.items()
    ):
        raise ValueError("a complete authorized map of text documents is required")
    wire = json.dumps([principal, scope, pages], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode()).hexdigest()


def _line_patch(before: str, after: str, separate_edits: bool) -> dict:
    old = before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    prefix = 0
    common_length = min(len(old), len(new))
    while prefix < common_length and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < common_length - prefix and old[-1 - suffix] == new[-1 - suffix]:
        suffix += 1
    start = sum(map(len, old[:prefix]))
    old_band = old[prefix:len(old) - suffix]
    new_band = new[prefix:len(new) - suffix]
    single = {"start": start, "end": start + sum(map(len, old_band)), "text": "".join(new_band)}
    # Bound worst-case sequence matching work on repetitive pages. A larger
    # range still travels losslessly as the contiguous representation.
    if not separate_edits or not old_band or not new_band or len(old_band) * len(new_band) > 1_000_000:
        return single
    if not set(old_band).intersection(new_band):
        return single
    offsets = [start]
    for line in old_band:
        offsets.append(offsets[-1] + len(line))
    matching = SequenceMatcher(None, old_band, new_band)
    hunks = [{"start": offsets[i], "end": offsets[j], "text": "".join(new_band[a:b])}
             for tag, i, j, a, b in matching.get_opcodes() if tag != "equal"]
    if len(hunks) < 2:
        return single
    multi = {"hunks": hunks}
    def wire_bytes(patch):
        return len(json.dumps(patch, ensure_ascii=False, separators=(",", ":")).encode())
    return multi if wire_bytes(multi) < wire_bytes(single) else single


def make_update(previous: dict[str, str] | None, current: dict[str, str], *,
                principal: str, scope: str, expected_base: str | None,
                separate_edits: bool = True) -> dict:
    head = snapshot_digest(current, principal=principal, scope=scope)
    if previous is None or expected_base != snapshot_digest(previous, principal=principal, scope=scope):
        return {"mode": "snapshot", "head": head, "pages": dict(current)}
    changed = {key: _line_patch(previous[key], current[key], separate_edits)
               for key in sorted(current.keys() & previous.keys()) if previous[key] != current[key]}
    return {"mode": "delta", "base": expected_base, "head": head,
            "purge": sorted(previous.keys() - current.keys()),
            "added": {k: current[k] for k in sorted(current.keys() - previous.keys())},
            "patches": changed}


def _apply_patch(body: str, patch: dict) -> str:
    hunks = patch["hunks"] if "hunks" in patch else [patch]
    parts = []
    cursor = 0
    for hunk in hunks:
        start, end = hunk["start"], hunk["end"]
        if type(start) is not int or type(end) is not int or not cursor <= start <= end <= len(body):
            raise ValueError("invalid, overlapping, or out-of-order source offsets")
        parts.extend((body[cursor:start], hunk["text"]))
        cursor = end
    parts.append(body[cursor:])
    return "".join(parts)


def apply_update(previous: dict[str, str] | None, packet: dict, *, principal: str, scope: str) -> dict[str, str]:
    """Apply atomically in memory. On mismatch request a fresh snapshot."""
    if packet["mode"] == "snapshot":
        updated = dict(packet["pages"])
    elif packet["mode"] == "delta":
        if previous is None or packet["base"] != snapshot_digest(previous, principal=principal, scope=scope):
            raise ValueError("the accepted base has changed; fetch a fresh snapshot")
        updated = dict(previous)
        for key in packet["purge"]:
            del updated[key]
        for key, patch in packet["patches"].items():
            updated[key] = _apply_patch(updated[key], patch)
        if updated.keys() & packet["added"].keys():
            raise ValueError("addition collides with an existing document")
        updated.update(packet["added"])
    else:
        raise ValueError("unknown snapshot transfer mode")
    if snapshot_digest(updated, principal=principal, scope=scope) != packet["head"]:
        raise ValueError("snapshot integrity check failed")
    return updated
