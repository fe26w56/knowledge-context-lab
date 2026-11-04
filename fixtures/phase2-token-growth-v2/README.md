# Phase 2 token-growth fixture v2

This is a fictional, project-authored diagnostic for measuring reference-token growth
without padding pages with one repeated paragraph. It is not an independent benchmark.
The source pages contain varied risk, rollout, review, constraint, alternative, measurement,
handoff, and access-boundary sections. The 12 development and 18 final questions are
inherited as frozen question wording from v1; final gold remains evaluator-only.

`author_fixture.py` writes the 100-page mixed corpus and freezes hashes before retrieval
implementation work. `generate(size, scenario, seed)` supports 100/1,000/10,000 pages.
The mixed 100-page corpus deliberately includes exact duplicate bodies, an old-version
record, and a similar current note; counts and body-hash duplication are reported in
`FREEZE.json` rather than hidden evaluator labels. `long` lengthens the same first relevant
records with distinct operational sections at fixed N=100, separating page-length growth
from document-count growth. `unrelated` adds unrelated projects.

The retriever must receive only request text and allowed scope/filter settings. It must not
receive qids, gold quotes, required source IDs, or evaluator labels. Report reference tokens,
required evidence recall, stale/condition/private violations, selected sources, and median/p95
retrieval separately. Token reduction with evidence loss is a regression.
