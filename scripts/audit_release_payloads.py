"""Post-hoc audit of saved payloads; never reruns retrieval or edits its scores."""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil

from context_lab.release_eval import generate, source_hashes
from context_lab.retrieval_v2 import digest
from context_lab.metrics import UnitCounter


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def visible(document, request):
    scope, actor = request.get("scope"), request.get("actor", "")
    return ((scope is None or document["scope"] == scope)
            and (document["scope"] == "shared" or bool(actor) and document.get("owner") == actor))


def state_eligible(section, request):
    mode = request.get("mode", "search")
    if mode == "current" and section.get("kind") == "decision" and section.get("adoption_status") != "adopted":
        return False
    if mode in {"current", "history"}:
        point = date.fromisoformat(request["as_of"])
        start, end = section.get("valid_from"), section.get("valid_to")
        if start and date.fromisoformat(start) > point:
            return False
        if end and point >= date.fromisoformat(end):
            return False
    return True


def equivalent_ids(roots, lineage):
    return {key for key, (origin, kind) in lineage.items() if origin in roots and kind in {"base", "exact"}}


def condition_roots(quote, query):
    mapping = query.get("evidence_sources", {})
    if quote in mapping:
        return set(mapping[quote])
    contained = [set(ids) for expected, ids in mapping.items() if quote in expected]
    if contained:
        return set().union(*contained)
    return set(query.get("accepted_source_ids", []))


def audit_payload(payload, query, docs, lineage, original, method):
    value = json.loads(payload)
    items, sources = value["items"], value["sources"]
    request = query["request"]
    source_errors, metadata_errors, span_errors = [], [], []
    state_violations = 0
    item_ids = {item["document_id"] for item in items}
    if item_ids != set(sources):
        source_errors.append("source_set")
    for key in ("mode", "as_of"):
        if value.get(key) != request.get(key, "search" if key == "mode" else None):
            metadata_errors.append("envelope_" + key)
    for document_id, source in sources.items():
        doc = docs.get(document_id)
        if doc is None:
            source_errors.append("unknown_source")
            continue
        for key in ("title", "source_url", "recorded_at", "verified_at"):
            if source.get(key) != doc.get(key):
                source_errors.append("source_" + key)
        if source.get("revision") != digest(doc["body"]):
            source_errors.append("source_revision")
    scope_violations = 0
    for item in items:
        doc = docs.get(item["document_id"])
        if doc is None:
            source_errors.append("unknown_document")
            continue
        scope_violations += not visible(doc, request)
        if method == "A":
            if item["text"] != doc["body"]:
                source_errors.append("full_body")
            continue
        sections = {section["id"]: section for section in doc["sections"]}
        sec = sections.get(item.get("parent_section_id"))
        if sec is None:
            source_errors.append("unknown_parent_section")
            continue
        for key in ("heading", "kind", "adoption_status", "valid_from", "valid_to", "verified_at"):
            if item.get(key) != sec.get(key):
                metadata_errors.append(key)
        section_id = item.get("section_id", "")
        if section_id != sec["id"] and not (section_id.startswith(sec["id"] + "~") and section_id[len(sec["id"])+1:].isdigit()):
            metadata_errors.append("section_id")
        text, spans = sec["text"], item.get("spans", [])
        valid_spans = (isinstance(spans, list) and bool(spans)
            and all(isinstance(s, list) and len(s) == 2
                    and all(type(n) is int for n in s) and 0 <= s[0] < s[1] <= len(text) for s in spans))
        if not valid_spans or "".join(text[a:b] for a, b in spans) != item["text"]:
            span_errors.append("text_span")
        state_violations += not state_eligible(sec, request)
    grounded = []
    for quote in query.get("expected_quotes", []):
        roots = query.get("evidence_sources", {}).get(quote, query.get("accepted_source_ids", []))
        accepted = equivalent_ids(roots, lineage)
        grounded.append(any(i["document_id"] in accepted and quote in i["text"] for i in items))
    condition_unknown = condition_missing = condition_wrong_source = 0
    for quote in query.get("condition_quotes", []):
        roots = condition_roots(quote, query)
        # A condition must be attributable to at least one declared source.
        roots = {d["id"] for d in original if d["id"] in roots and quote in d["body"]}
        accepted = equivalent_ids(roots, lineage)
        matches = [i for i in items if quote in i["text"]]
        if not roots:
            condition_unknown += 1
        elif not matches:
            condition_missing += 1
        elif not any(i["document_id"] in accepted for i in matches):
            condition_wrong_source += 1
    obsolete_hits = sum(any(q in i["text"] for i in items) for q in query.get("obsolete_quotes", []))
    forbidden_hits = sum(q in payload for q in query.get("forbidden_quotes", []))
    eligible = bool(query.get("answerable", True) and grounded)
    strict = None if method == "A" else bool(eligible and all(grounded)
        and not source_errors and not metadata_errors and not span_errors and not scope_violations
        and not state_violations and not forbidden_hits and not obsolete_hits
        and not condition_wrong_source and not condition_missing and not condition_unknown)
    return dict(eligible=eligible, strict_complete=strict, state_checked=method != "A",
        state_violations=None if method == "A" else state_violations, scope_violations=scope_violations,
        obsolete_hits=obsolete_hits, condition_missing=condition_missing, condition_wrong_source=condition_wrong_source,
        condition_source_unknown=condition_unknown, source_errors=dict(Counter(source_errors)),
        metadata_errors=dict(Counter(metadata_errors)), span_errors=dict(Counter(span_errors)), forbidden_hits=forbidden_hits,
        source_quotes=sum(grounded), required_quotes=len(grounded))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "corpus", "queries", "output"):
        ap.add_argument("--"+name, type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    initial_sources = source_hashes()
    corpus = json.loads(args.corpus.read_text())
    queries = {q["id"]: q for q in json.loads(args.queries.read_text())["queries"]}
    metadata = json.loads((args.run/"metadata.json").read_text())
    assert metadata["source_sha256"] == initial_sources
    assert metadata["corpus_sha256"] == sha256(args.corpus)
    assert metadata["queries_sha256"] == sha256(args.queries)
    generation_hashes = {(r["size"], r["seed"]): r["corpus_hash"] for r in metadata["datasets"]}
    results = json.loads((args.run/"results.json").read_text())
    keys = ("variant", "method", "budget", "size", "seed", "query_id")
    expected = {tuple(r[k] for k in keys): r for r in results if r["repeat"] == 0}
    cache, rows, payloads = {}, [], {}
    counter = UnitCounter("o200k_base")
    for line in (args.run/"payloads.jsonl").read_text().splitlines():
        p = json.loads(line)
        key = tuple(p[k] for k in keys)
        assert key not in payloads, "Duplicate payload row"
        payloads[key] = p["payload"]
        generation_key = (p["size"], p["seed"])
        if generation_key not in cache:
            docs, lineage, info = generate(corpus, *generation_key)
            assert info["corpus_hash"] == generation_hashes[generation_key]
            cache[generation_key] = ({d["id"]: d for d in docs}, lineage)
        docs, lineage = cache[generation_key]
        audited = audit_payload(p["payload"], queries[p["query_id"]], docs, lineage, corpus["documents"], p["method"])
        original = expected[key]
        measured_hash = hashlib.sha256(p["payload"].encode()).hexdigest()
        measured_units = counter(p["payload"])
        row = {k: p[k] for k in keys}
        row.update(audited, original_complete=original["complete"],
            record_hash_ok=measured_hash == p["payload_sha256"] == original["payload_sha256"],
            token_count_ok=measured_units == original["units"], budget_ok=p["method"] == "A" or measured_units <= p["budget"])
        rows.append(row)
    assert set(payloads) == set(expected), "Missing or additional payload rows"
    pairs = 0
    for key, payload in payloads.items():
        if key[1] == "B":
            peer = (key[0], "C", *key[2:])
            assert payload == payloads[peer], "B/C payload mismatch"
            assert expected[key]["candidates"] == expected[peer]["candidates"]
            pairs += 1
    groups = {}
    for row in rows:
        group_key = tuple(row[k] for k in ("variant", "method", "budget", "size", "seed"))
        groups.setdefault(group_key, []).append(row)
    aggregates = []
    for key, group in sorted(groups.items()):
        aggregates.append(dict(zip(("variant", "method", "budget", "size", "seed"), key)) | dict(
            eligible=sum(r["eligible"] for r in group), original_complete=sum(r["original_complete"] for r in group),
            strict_complete=None if key[1] == "A" else sum(r["strict_complete"] for r in group),
            obsolete_hits=sum(r["obsolete_hits"] for r in group), condition_missing=sum(r["condition_missing"] for r in group),
            condition_wrong_source=sum(r["condition_wrong_source"] for r in group)))
    summary = dict(rows=len(rows), state_checked_rows=sum(r["state_checked"] for r in rows),
        state_violations=sum(r["state_violations"] or 0 for r in rows),
        scope_violations=sum(r["scope_violations"] for r in rows),
        record_hash_errors=sum(not r["record_hash_ok"] for r in rows), token_count_errors=sum(not r["token_count_ok"] for r in rows),
        budget_errors=sum(not r["budget_ok"] for r in rows), source_errors=sum(bool(r["source_errors"]) for r in rows),
        metadata_errors=sum(bool(r["metadata_errors"]) for r in rows), span_errors=sum(bool(r["span_errors"]) for r in rows),
        obsolete_hits_A=sum(r["obsolete_hits"] for r in rows if r["method"] == "A"),
        obsolete_hits_B_C=sum(r["obsolete_hits"] for r in rows if r["method"] != "A"),
        condition_missing=sum(r["condition_missing"] for r in rows), condition_wrong_source=sum(r["condition_wrong_source"] for r in rows),
        condition_source_unknown=sum(r["condition_source_unknown"] for r in rows),
        payload_b_c_equal=pairs, posthoc=True, original_results_unchanged=True)
    manifest = dict(run=str(args.run), corpus_sha256=sha256(args.corpus), queries_sha256=sha256(args.queries),
        payloads_sha256=sha256(args.run/"payloads.jsonl"), results_sha256=sha256(args.run/"results.json"),
        source_sha256=initial_sources, script_sha256=sha256(__file__), posthoc=True)
    for filename, data in (("rows.json", rows), ("summary.json", summary), ("groups.json", aggregates), ("manifest.json", manifest)):
        (args.output/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
    shutil.copyfile(__file__, args.output/"audit_release_payloads.py")
    assert initial_sources == source_hashes()
    assert not any(summary[k] for k in ("record_hash_errors", "token_count_errors", "budget_errors", "source_errors", "metadata_errors", "span_errors", "scope_violations", "state_violations")), summary
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
