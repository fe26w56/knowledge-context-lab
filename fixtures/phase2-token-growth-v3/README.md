# Phase 2 token-growth fixture v3

Fictional, project-authored diagnostic fixture; not an independent benchmark. The exact
base size is 100 records: 37 essential current/history records supporting development and
held-out final topics, plus 63 scale records. `FREEZE.json` reports the generated family
counts rather than placing evaluator labels in source records.

For `mixed`, the 63 scale records contain 15 exact duplicate bodies, 15 historical records,
30 current records with explicit region/version conditions, and 3 unrelated remainder
records. `unrelated` uses unrelated project names and has no duplicate/variant injection.
`long` keeps the same source IDs at N=100 and appends distinct operational observations to
the same first relevant records; `length_multiplier` 1, 4, and 16 separate page-length
growth from document-count growth. `generate` supports 100, 1,000, and 10,000 records.

The retriever must receive only request text and allowed scope/filter settings. Do not pass
qid, gold quotes, required IDs, or family labels. Measure reference tokens, evidence recall,
stale/condition/private violations, selected source count, and retrieval time separately.
Token reduction with missing evidence is a regression.
