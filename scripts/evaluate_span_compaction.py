"""Post-hoc span compaction audit; never calls a model or mutates source runs."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import tiktoken
from context_lab.context_spans import compact_context


def ser(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def digest(v): return hashlib.sha256(ser(v).encode()).hexdigest()


def evidence_retained(before, after):
    amap = {s["id"]: s for s in after["sources"]}
    for src in before["sources"]:
        if "spans" not in src: continue
        targets = amap.get(src["id"], {}).get("spans", [])
        for span in src["spans"]:
            if not any(span["start"] >= t["start"] and span["end"] <= t["end"] and span["text"] == t["text"][span["start"]-t["start"]:span["end"]-t["start"]] for t in targets):
                return False
    return True


def main():
    p = argparse.ArgumentParser(); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): raise ValueError("output must be new")
    root = Path(__file__).resolve().parents[1]
    paths = [root / "runs/phase2-stability-model-v1/api", root / "runs/phase2-stability-scale-model-v1/api"]
    enc = tiktoken.get_encoding("o200k_base")
    rows=[]
    for directory in paths:
        for path in sorted(directory.glob("*.json")):
            attempt=json.loads(path.read_text())
            if attempt.get("metadata",{}).get("arm") != "parent8000" or "payload" not in attempt: continue
            context=attempt["payload"]["context"]; before_wire=ser(context); compact=compact_context(context)
            original_wire=before_wire; compact_wire=ser(compact)
            before_sources={s["id"]: s for s in context.get("sources", [])}
            after_sources={s["id"]: s for s in compact.get("sources", [])}
            source_set_metadata_preserved=(set(before_sources)==set(after_sources) and all(
                {k:v for k,v in before_sources[i].items() if k != "spans"} ==
                {k:v for k,v in after_sources[i].items() if k != "spans"} for i in before_sources))
            rows.append({"run": directory.parent.name, "attempt_id": attempt.get("attempt_id"),
                         "metadata": attempt.get("metadata"), "payload_sha256": digest(attempt["payload"]),
                         "original_context_sha256": digest(context), "compact_context_sha256": digest(compact),
                         "original_context_tokens": len(enc.encode(original_wire, disallowed_special=())),
                         "compact_context_tokens": len(enc.encode(compact_wire, disallowed_special=())),
                         "original_source_count": len(context.get("sources",[])),
                         "compact_source_count": len(compact.get("sources",[])),
                         "original_span_count": sum(len(s.get("spans",[])) for s in context.get("sources",[])),
                         "compact_span_count": sum(len(s.get("spans",[])) for s in compact.get("sources",[])),
                         "evidence_retained": evidence_retained(context, compact),
                         "source_set_metadata_preserved": source_set_metadata_preserved,
                         "input_unchanged": ser(context) == before_wire})
    if not rows: raise ValueError("no parent payloads")
    reductions=[r["original_context_tokens"]-r["compact_context_tokens"] for r in rows]
    unique_payloads = len({r["payload_sha256"] for r in rows})
    summary={"schema":"span-compaction-audit-v2", "api_calls":0, "rows":len(rows), "unique_parent_payloads":unique_payloads,
             "all_evidence_retained":all(r["evidence_retained"] for r in rows),
             "all_source_set_metadata_preserved":all(r["source_set_metadata_preserved"] for r in rows),
             "all_inputs_unchanged":all(r["input_unchanged"] for r in rows),
             "original_context_tokens_total":sum(r["original_context_tokens"] for r in rows),
             "compact_context_tokens_total":sum(r["compact_context_tokens"] for r in rows),
             "token_reduction_total":sum(reductions), "token_reduction_ratio":sum(reductions)/sum(r["original_context_tokens"] for r in rows), "rows_with_token_reduction":sum(x>0 for x in reductions),
             "rows_with_overlap_or_adjacency":sum(r["original_span_count"]>r["compact_span_count"] for r in rows),
             "limitations":["post-hoc payload transformation, not a new model result", "token reduction is JSON/span compaction only, not a DB effect", "rows repeat the same request payloads; do not treat 90 rows as 90 independent examples"]}
    a.output.mkdir(parents=True); (a.output/"rows.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n"); (a.output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
