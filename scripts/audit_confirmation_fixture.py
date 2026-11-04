#!/usr/bin/env python3
"""Structural gate for the frozen confirmation fixture (never a semantic grader)."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import date
from pathlib import Path
from context_lab.retrieval_v2 import validate_documents

REQUEST_FIELDS = {"text", "actor", "scope", "mode", "as_of"}
MODES = {"current", "history", "search"}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def err(failures, where, message):
    failures.append({"where": where, "message": message})

def audit_fixture(fixture: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.mkdir(parents=True)
    failures = []
    files = ["corpus.json", "dev.json", "final.json", "grading.json"]
    freeze = json.loads((fixture / "FREEZE.json").read_text())
    actual_hashes = {}
    for name in files:
        path = fixture / name
        actual_hashes[name] = digest(path) if path.is_file() else None
        if freeze.get("sha256", {}).get(name) != actual_hashes[name]:
            err(failures, name, "FREEZE hash mismatch")

    corpus = json.loads((fixture / "corpus.json").read_text())
    docs = corpus.get("documents")
    if not isinstance(docs, list):
        err(failures, "corpus.documents", "must be a list")
        docs = []
    if not docs:
        err(failures, 'corpus.documents', 'at least one document is required')
    try:
        validate_documents(docs)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        err(failures, 'corpus.documents', 'runtime schema: ' + str(exc))
    by_id, section_by_id = {}, {}
    all_section_texts = []
    for i, doc in enumerate(docs):
        where = f"corpus.documents[{i}]"
        if not isinstance(doc, dict):
            err(failures, where, "document must be an object"); continue
        did = doc.get("id")
        if not isinstance(did, str) or not did or did in by_id:
            err(failures, where, "document ID must be unique and nonempty"); continue
        by_id[did] = doc
        body = doc.get("body")
        if not isinstance(body, str):
            err(failures, did, "body must be a string"); body = ""
        sections = doc.get("sections")
        if not isinstance(sections, list):
            err(failures, did, "sections must be a list"); sections = []
        covered = [False] * len(body)
        seen = set()
        for j, section in enumerate(sections):
            sw = f"{did}.sections[{j}]"
            if not isinstance(section, dict):
                err(failures, sw, "section must be an object"); continue
            sid, text = section.get("id"), section.get("text")
            if not isinstance(sid, str) or not sid or sid in section_by_id or sid in seen:
                err(failures, sw, "section ID must be unique and nonempty")
            seen.add(sid)
            if isinstance(sid, str): section_by_id[sid] = (doc, section)
            if not isinstance(text, str) or not text:
                err(failures, sw, "section text must be a nonempty string"); continue
            all_section_texts.append(text)
            start = body.find(text)
            if start < 0:
                err(failures, sw, "section text does not occur in document body")
            while start >= 0:
                for k in range(start, start + len(text)): covered[k] = True
                start = body.find(text, start + 1)
        offset = 0
        for line in body.splitlines(keepends=True):
            if not line.lstrip().startswith('#') and any(not ch.isspace() and not covered[offset+i] for i, ch in enumerate(line)):
                err(failures, did, "non-heading body paragraph is not covered by section interval")
            offset += len(line)

    questions, seen_ids = [], set()
    category_modes = {"current": "current", "history": "history"}
    for split in ("dev", "final"):
        data = json.loads((fixture / f"{split}.json").read_text())
        if not data.get('queries') or len(data['queries']) != freeze.get('question_counts', {}).get(split):
            err(failures, split, 'question count differs from nonempty frozen split')
        for i, q in enumerate(data.get("queries", [])):
            qw = f"{split}.queries[{i}]"; qid = q.get("id")
            if not isinstance(qid, str) or not qid or qid in seen_ids:
                err(failures, qw, "question ID must be unique across dev/final")
            seen_ids.add(qid); questions.append(q)
            req = q.get("request")
            if not isinstance(req, dict) or set(req) != REQUEST_FIELDS:
                err(failures, qid, "request must contain exactly allowed fields"); continue
            if not all(isinstance(req[k], str) for k in ("text", "actor", "scope", "mode", "as_of")):
                err(failures, qid, "request fields must be strings")
            mode, category = req.get("mode"), q.get("category")
            if mode not in MODES:
                err(failures, qid, "request mode must be current, history, or search")
            if category in category_modes and mode != category_modes[category]:
                err(failures, qid, f"{category} category requires mode={category_modes[category]}")
            try: asof = date.fromisoformat(req.get("as_of", ""))
            except Exception: asof = None; err(failures, qid, "as_of must be ISO date")
            rubric = q.get("rubric")
            if not isinstance(rubric, dict): err(failures, qid, "rubric must be object"); continue
            answerable, abstain = q.get("answerable"), rubric.get("abstain")
            if type(answerable) is not bool or type(abstain) is not bool:
                err(failures, qid, "answerable and rubric.abstain must be booleans")
            claims, missing = rubric.get("atomic_claims"), rubric.get("missing_information")
            if not isinstance(claims, list) or not isinstance(missing, list) or any(not isinstance(x, str) for x in missing):
                err(failures, qid, "atomic_claims and missing_information must be lists")
                claims = claims if isinstance(claims, list) else []
            if answerable is True and (abstain is True or not claims or missing):
                err(failures, qid, "answerable question has inconsistent abstention/claims")
            if answerable is False and (abstain is not True or claims or not missing):
                err(failures, qid, "insufficient question has inconsistent abstention/claims")
            for ci, claim in enumerate(claims):
                cw = f"{qid}.rubric.atomic_claims[{ci}]"
                if not isinstance(claim, dict):
                    err(failures, cw, "claim must be object"); continue
                quote, accepted = claim.get("evidence_quote"), claim.get("accepted_source_ids")
                if not isinstance(quote, str) or not quote or not isinstance(accepted, list) or not accepted:
                    err(failures, cw, "nonempty quote and accepted source IDs required"); continue
                found = False
                for did in accepted:
                    doc = by_id.get(did)
                    if doc is None:
                        err(failures, cw, f"accepted source does not exist: {did}"); continue
                    if doc.get("scope") != req.get("scope"):
                        err(failures, cw, f"source scope differs from request: {did}")
                    if doc.get("scope") == "private" and doc.get("owner") != req.get("actor"):
                        err(failures, cw, f"private source owner differs from request actor: {did}")
                    if quote not in doc.get("body", ""):
                        err(failures, cw, f"quote absent from source body: {did}"); continue
                    matching = [s for s in doc.get("sections", []) if isinstance(s, dict) and isinstance(s.get('text'), str) and quote in s['text']]
                    if not matching:
                        err(failures, cw, f"quote absent from indexed section: {did}"); continue
                    valid_match = False
                    for section in matching:
                        try:
                            vf = date.fromisoformat(section.get("valid_from")) if section.get("valid_from") else None
                            vt = date.fromisoformat(section.get("valid_to")) if section.get("valid_to") else None
                            valid = mode == 'search' or (asof is not None and (vf is None or vf <= asof) and (vt is None or asof < vt))
                        except Exception:
                            valid = False
                        if valid and (mode != 'current' or section.get('adoption_status') in {'adopted', 'na'}):
                            valid_match = True
                    if not valid_match:
                        err(failures, cw, f"quote section date interval invalid or state ineligible: {did}")
                    if valid_match: found = True
                if not found:
                    err(failures, cw, "no accepted source passed body/section/scope/date checks")
            if isinstance(claims, list) and all(isinstance(c, dict) and isinstance(c.get('evidence_quote'), str) and isinstance(c.get('accepted_source_ids'), list) for c in claims):
                expected = {}
                for c in claims:
                    expected.setdefault(c['evidence_quote'], set()).update(c['accepted_source_ids'])
                if set(q.get('expected_quotes', [])) != set(expected) or q.get('evidence_sources') != {k: sorted(v) for k, v in expected.items()}:
                    err(failures, qid, 'retrieval evidence requirements differ from answer rubric')
            boundary = rubric.get("access_boundary")
            if isinstance(boundary, dict) and boundary.get("attempting_actor") != req.get("actor"):
                err(failures, qid, "access_boundary.attempting_actor differs from request actor")
    counts = {"documents": len(docs), "sections": len(section_by_id), "questions": len(questions), "failures": len(failures)}
    global_counts = {}
    for text in all_section_texts: global_counts[text] = global_counts.get(text, 0) + 1
    result = {"fixture": str(fixture), "counts": counts, "hashes": actual_hashes,
              "diagnostics": {"duplicate_paragraph_extra_characters_corpuswide":
                              sum(len(t) * (n - 1) for t, n in global_counts.items() if n > 1)},
              "semantic_validated": False, "structural_valid": not failures, "failures": failures}
    (output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if failures: raise ValueError(f"structural audit failed with {len(failures)} failures")
    return result

def main(argv=None):
    p = argparse.ArgumentParser(); p.add_argument("--fixture", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        result = audit_fixture(args.fixture, args.output)
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)})); return 1
    print(json.dumps({"status": "pass", "output": str(args.output), "counts": result["counts"]})); return 0

if __name__ == "__main__":
    raise SystemExit(main())
