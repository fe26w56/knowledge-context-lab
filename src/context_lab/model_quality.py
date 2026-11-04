"""Offline citation audits and explicit semantic reviews of saved model attempts.

Literal citation checks never establish answer correctness. Semantic judgments
must be supplied separately; absent or uncertain judgments cannot pass a task.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

from .model_eval import _validate_output, sanitize_request, sanitize_retrieved_payload
from .release_eval import generate

CRITERIA = ("state_and_time", "no_unsupported_claims", "no_private_leakage",
            "citations_entail_claims", "abstention_and_missing_information")
JUDGMENTS = {"pass", "fail", "uncertain", "unreviewed"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def measurements(attempts):
    """Observed intervals/usage only; missing usage is not zero billed usage."""
    events, latencies, totals = [], [], Counter()
    unknown_usage = 0
    for row in attempts:
        if row["status"] in {"invalid_input", "budget_exceeded"}:
            continue
        usage = row.get("usage")
        if usage is None:
            unknown_usage += 1
        else:
            for key in ("input_tokens", "output_tokens"):
                if type(usage.get(key)) is not int or usage[key] < 0:
                    raise ValueError("invalid observed usage")
                totals[key] += usage[key]
        for key in ("nominal_cost_estimate_nanodollars", "conservative_cost_nanodollars"):
            value = row.get(key)
            if value is not None:
                if type(value) is not int or value < 0:
                    raise ValueError("invalid observed cost estimate")
                totals[key] += value
        latency = row.get("latency_seconds")
        if latency is not None:
            if not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
                raise ValueError("invalid observed latency")
            latencies.append(latency)
        start, end = row.get("started_at"), row.get("ended_at")
        if start is not None and end is not None:
            if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (start, end)) or end < start:
                raise ValueError("invalid observed interval")
            actor = row.get("request", {}).get("actor")
            if end > start:
                events.extend(((start, 1, actor), (end, -1, actor)))
    active, active_actors, peak, peak_actors = 0, Counter(), 0, 0
    for _, change, actor in sorted(events, key=lambda e: (e[0], e[1])):
        active += change
        if actor is not None:
            active_actors[actor] += change
        peak = max(peak, active)
        peak_actors = max(peak_actors, sum(n > 0 for n in active_actors.values()))
    return dict(observed_totals=dict(totals), usage_unknown_attempts=unknown_usage,
                timed_attempts=len(latencies), median_latency_seconds=statistics.median(latencies) if latencies else None,
                p95_latency_seconds=sorted(latencies)[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
                peak_overlapping_attempt_intervals=peak, peak_overlapping_distinct_actors=peak_actors,
                invoice_measured=False)


def audit_answer(attempt, question, documents, lineage):
    failures, citations = [], []
    if attempt.get("status") != "ok":
        return {"failures": ["model_attempt_failed"], "citations": []}
    answer = attempt.get("output")
    try:
        _validate_output(answer)
    except (ValueError, TypeError):
        return {"failures": ["invalid_output_schema"], "citations": []}
    payload = sanitize_retrieved_payload(attempt["retrieved_payload"])
    if answer["abstain"] != question["rubric"]["abstain"]:
        failures.append("incorrect_abstention_flag")
    if not answer["answer"].strip():
        failures.append("empty_answer")
    if not answer["abstain"] and not answer["claims"]:
        failures.append("answer_without_claims")
    if answer["abstain"] and not answer["missing_information"]:
        failures.append("abstention_without_missing_information")
    serialized = json.dumps(answer, ensure_ascii=False)
    if any(quote and quote in serialized for quote in question.get("forbidden_quotes", [])):
        failures.append("forbidden_literal_in_answer")
    req = question["request"]
    for item in payload["items"]:
        doc = documents.get(item["document_id"])
        if not doc or (doc.get("scope") == "private" and doc.get("owner") != req.get("actor")) or (req.get("scope") is not None and doc.get("scope") != req["scope"]):
            failures.append("unavailable_or_out_of_scope_model_context")
    for ci, claim in enumerate(answer["claims"]):
        if not claim["statement"].strip() or not claim["citations"]:
            failures.append(f"claim_{ci}_empty_or_uncited")
        for qi, citation in enumerate(claim["citations"]):
            did, quote = citation["document_id"], citation["quote"]
            doc = documents.get(did)
            supplied = bool(quote.strip()) and any(
                item["document_id"] == did and quote in item["text"] for item in payload["items"])
            authentic = bool(doc and quote.strip() and quote in doc["body"])
            allowed = bool(doc and not (doc.get("scope") == "private" and doc.get("owner") != req.get("actor"))
                           and (req.get("scope") is None or doc.get("scope") == req["scope"]))
            if not (supplied and authentic and allowed):
                failures.append(f"citation_{ci}_{qi}_not_supplied_authentic_or_allowed")
            origin, kind = lineage.get(did, (None, None))
            citations.append(dict(claim=ci, citation=qi, document_id=did, quote=quote,
                                  in_supplied_context=supplied, in_source_body=authentic, scope_allowed=allowed,
                                  origin_document_id=origin, transformation=kind,
                                  source_body_sha256=hashlib.sha256(doc["body"].encode()).hexdigest() if doc else None,
                                  accepted_source_for_claims=[c["key"] for c in question["rubric"]["atomic_claims"]
                                     if origin in c["accepted_source_ids"] and kind in {"base", "exact"}]))
    for claim in question["rubric"]["atomic_claims"]:
        if not any(claim["key"] in c["accepted_source_for_claims"] and c["in_supplied_context"]
                   and c["in_source_body"] and c["scope_allowed"] for c in citations):
            failures.append("required_source_not_cited_" + claim["key"])
    return {"failures": failures, "citations": citations,
            "semantic_correctness_established": False}


def prepare(tasks, mapping, queries, corpus, retrieval_run, model_run):
    """Bind attempts to frozen inputs, then hide arm labels from the review packet."""
    metadata = load(retrieval_run / "metadata.json")
    if file_hash(queries) != metadata["queries_sha256"] or file_hash(corpus) != metadata["corpus_sha256"]:
        raise ValueError("fixture does not match frozen retrieval run")
    for name in ("release_eval.py", "retrieval_release.py", "retrieval_v2.py", "retrieval.py", "metrics.py"):
        if file_hash(Path(__file__).parent / name) != metadata["source_sha256"][name]:
            raise ValueError("generator dependencies differ from frozen run")
    task_rows, map_rows = load(tasks), load(mapping)
    task_by_key = {row["task_key"]: row for row in task_rows}
    map_by_key = {row["task_key"]: row for row in map_rows}
    if not task_rows or len(task_by_key) != len(task_rows) or len(map_by_key) != len(map_rows) or set(task_by_key) != set(map_by_key):
        raise ValueError("task mapping is missing or duplicated")
    coordinates = [tuple(m[k] for k in ("size", "seed", "query_id", "variant", "method", "budget", "repeat")) for m in map_rows]
    if len(set(coordinates)) != len(coordinates) or len({m["budget"] for m in map_rows}) != 1:
        raise ValueError("comparison requires unique trials at one selected budget")
    report = load(model_run / "run.json")
    attempts = report["attempts"]
    by_key = {row.get("task_key"): row for row in attempts}
    if len(by_key) != len(attempts) or set(by_key) != set(task_by_key):
        raise ValueError("every planned task must have exactly one recorded attempt")
    for index, task in enumerate(task_rows):
        if type(by_key[task["task_key"]].get("task_index")) is not int or by_key[task["task_key"]]["task_index"] != index:
            raise ValueError("attempt index does not match task order")
        if by_key[task["task_key"]].get("status") not in {"ok", "error", "invalid_input", "budget_exceeded"}:
            raise ValueError("unknown model attempt status")
    questions = {q["id"]: q for q in load(queries)["queries"]}
    raw_rows = [json.loads(line) for line in (retrieval_run / "payloads.jsonl").read_text().splitlines() if line]
    raw = {(r["size"], r["seed"], r["query_id"], r["variant"], r["method"], r["budget"]): r for r in raw_rows}
    corpus_data = load(corpus)
    canonical_documents = {doc["id"]: doc for doc in corpus_data["documents"]}
    datasets = {}
    for m in map_rows:
        key = (m["size"], m["seed"])
        if key not in datasets:
            docs, lineage, info = generate(corpus_data, *key)
            expected = next(d for d in metadata["datasets"] if (d["size"], d["seed"]) == key)
            if info["corpus_hash"] != expected["corpus_hash"]:
                raise ValueError("generated source corpus differs from recorded corpus")
            datasets[key] = ({d["id"]: d for d in docs}, lineage)
    packets, bindings = [], []
    for key, task in task_by_key.items():
        m, attempt = map_by_key[key], by_key[key]
        question = questions[m["query_id"]]
        saved = raw[(m["size"], m["seed"], m["query_id"], m["variant"], m["method"], m["budget"])]
        if hashlib.sha256(saved["payload"].encode()).hexdigest() != m["payload_sha256"]:
            raise ValueError("saved payload hash mismatch")
        req = sanitize_request(question["request"])
        payload = sanitize_retrieved_payload(saved["payload"])
        if sanitize_request(task["request"]) != req or sanitize_retrieved_payload(task["retrieved_payload"]) != payload:
            raise ValueError("planned task differs from frozen input")
        if attempt["status"] not in {"invalid_input", "budget_exceeded"}:
            if attempt.get("request") != req or attempt.get("retrieved_payload") != payload:
                raise ValueError("recorded model input differs from planned task")
        if attempt["status"] == "ok" and (attempt.get("response_status") != "completed" or
                json.loads(attempt.get("output_text") or "null") != attempt.get("output")):
            raise ValueError("parsed answer does not match completed provider output")
        review_id = digest({"task": key, "attempt": attempt})[:24]
        packet = dict(review_id=review_id, request=req, rubric=question["rubric"],
                      output=attempt.get("output"), automatic=audit_answer(attempt, question, *datasets[(m["size"], m["seed"])]))
        # Quotes alone cannot show whether a rule was draft, expired, or absent
        # from the answering model's context. Keep the two evidence sets distinct.
        packet["supplied_context"] = {k: v for k, v in payload.items() if k != "method"}
        required_sources = {source for claim in question["rubric"]["atomic_claims"]
                            for source in claim["accepted_source_ids"]}
        packet["canonical_sources"] = [canonical_documents[source] for source in sorted(required_sources)]
        packets.append(packet)
        bindings.append(dict(review_id=review_id, packet_sha256=digest(packet), task_key=key,
                             mapping=m, attempt_sha256=digest(attempt), attempt=attempt))
    packets.sort(key=lambda p: p["review_id"])
    return dict(packets=packets, bindings=bindings, model_run_sha256=file_hash(model_run / "run.json"),
                input_hashes={"tasks": file_hash(tasks), "mapping": file_hash(mapping), "queries": file_hash(queries),
                              "corpus": file_hash(corpus), "grader": file_hash(__file__)},
                total_wallclock_seconds=report.get("total_wallclock_seconds"),
                measurements=measurements(attempts),
                semantic_review_complete=False, invoice_measured=False)


def grade_template(packet):
    return dict(review_id=packet["review_id"], packet_sha256=digest(packet), reviewer="", notes="",
                judgments={**{c["key"]: "unreviewed" for c in packet["rubric"]["atomic_claims"]},
                           **{c: "unreviewed" for c in CRITERIA}})


def summarize(prepared, reviews):
    packets = {p["review_id"]: p for p in prepared["packets"]}
    binding_ids = [b["review_id"] for b in prepared["bindings"]]
    if not packets or len(packets) != len(prepared["packets"]) or len(set(binding_ids)) != len(binding_ids) or set(binding_ids) != set(packets):
        raise ValueError("packets and bindings must be nonempty and one to one")
    grades = {g["review_id"]: g for g in reviews}
    if len(grades) != len(reviews) or set(grades) - set(packets):
        raise ValueError("unknown or duplicate semantic review")
    rows, semantic_completed = [], []
    for binding in prepared["bindings"]:
        rid = binding["review_id"]
        p = packets[rid]
        if digest(p) != binding["packet_sha256"] or digest(binding["attempt"]) != binding["attempt_sha256"]:
            raise ValueError("review packet or bound attempt was modified")
        g = grades.get(rid)
        status = "pending"
        reviewed = False
        if g is not None:
            expected = set(grade_template(p)["judgments"])
            if g.get("packet_sha256") != digest(p) or set(g.get("judgments", {})) != expected:
                raise ValueError("review must cover the exact packet and every criterion")
            values = g["judgments"].values()
            if any(v not in JUDGMENTS for v in values):
                raise ValueError("unknown judgment")
            if not isinstance(g.get("reviewer"), str) or not isinstance(g.get("notes"), str):
                raise ValueError("reviewer and rationale must be strings")
            if any(v != "unreviewed" for v in values) and (not g.get("reviewer", "").strip() or not g.get("notes", "").strip()):
                raise ValueError("a semantic judgment requires reviewer identity and rationale")
            reviewed = all(v in {"pass", "fail"} for v in values)
            if "fail" in values:
                status = "fail"
            elif all(v == "pass" for v in values):
                status = "pass"
        if p["automatic"]["failures"]:
            status = "fail"
        semantic_completed.append(reviewed)
        rows.append(dict(review_id=rid, status=status, **binding["mapping"]))
    arms = defaultdict(list)
    for row in rows:
        arms[(row["variant"], row["method"])].append(row)
    aggregates = [dict(variant=v, method=m, trials=len(group), unique_questions=len({r["query_id"] for r in group}),
                       outcomes=dict(Counter(r["status"] for r in group)),
                       measurements=measurements([b["attempt"] for b in prepared["bindings"]
                                                  if (b["mapping"]["variant"], b["mapping"]["method"]) == (v, m)]))
                  for (v, m), group in sorted(arms.items())]
    paired = []
    lookup = {(r["size"], r["seed"], r["query_id"], r["repeat"], r["variant"], r["method"]): r for r in rows}
    for baseline in (("selected", "A"), ("control", "A"), ("control", "B")):
        counts = Counter()
        for row in arms.get(("selected", "B"), []):
            other = lookup.get((row["size"], row["seed"], row["query_id"], row["repeat"], *baseline))
            if other is None or "pending" in (row["status"], other["status"]):
                counts["pending_or_missing"] += 1
            else:
                counts[f"candidate_{row['status']}_baseline_{other['status']}"] += 1
        paired.append(dict(baseline=list(baseline), counts=dict(counts)))
    return dict(arms=aggregates, paired=paired, rows=rows,
                mixed_arm_total_wallclock_seconds=prepared.get("total_wallclock_seconds"),
                measurements=prepared.get("measurements"),
                semantic_review_complete=all(semantic_completed),
                trial_outcomes_resolved=all(r["status"] != "pending" for r in rows),
                invoice_measured=False, independent_benchmark=False,
                population_noninferiority_established=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for name in ("tasks", "mapping", "queries", "corpus", "retrieval-run", "model-run"):
        prep.add_argument("--" + name, type=Path, required=True)
    grade = sub.add_parser("summarize")
    grade.add_argument("--prepared", type=Path, required=True)
    grade.add_argument("--reviews", type=Path, required=True)
    for command in (prep, grade):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.command == "prepare":
        result = prepare(args.tasks, args.mapping, args.queries, args.corpus, args.retrieval_run, args.model_run)
    else:
        result = summarize(load(args.prepared), load(args.reviews))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.command == "prepare":
        (args.output / "review-packets.json").write_text(json.dumps(result["packets"], ensure_ascii=False, indent=2) + "\n")
        (args.output / "reviews-template.json").write_text(json.dumps([grade_template(p) for p in result["packets"]], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "semantic_review_complete": result["semantic_review_complete"]}))


if __name__ == "__main__":
    main()
