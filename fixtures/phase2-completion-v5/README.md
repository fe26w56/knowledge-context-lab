# Phase 2 completion fixture v5

Revision of v4 after integration audit; v1–v4 remain untouched. This is
fictional synthetic material and is explicitly not an independent benchmark.
It contains 80 documents and 40 questions (20 dev, 20 final).

Every request clause is represented in the rubric and a visible source quote.
Multi-source items grade two constraints plus two responsible-role claims.
Condition subjects are explicit. Handoff requests distinguish receipt-
responsibility and rollback verification. History requests state the exact
historical date supported by the evidence. Insufficient items name their topic
and require `missing_information` fields, so bare abstention cannot pass.
Private-boundary requests use shared scope for the denial policy while their
access boundary explicitly excludes private note content.

`TOKEN_REPORT.json` uses the project venv's `tiktoken` 0.14.0 with
`TIKTOKEN_CACHE_DIR=tokenizer-cache`; `FREEZE.json` records hashes and the
implementation-blind, non-independent-benchmark boundary.
