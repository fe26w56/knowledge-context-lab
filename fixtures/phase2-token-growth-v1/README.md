# Phase 2 token-growth fixture

This is a project-authored diagnostic fixture for measuring how reference tokens,
evidence retention, stale-source handling, and access boundaries change as a knowledge
corpus grows. It is not an independent benchmark. It contains fictional Japanese
Notion-like pages only.

`author_fixture.py` is deterministic with seed `20261103`. It writes 100 source pages,
12 development requests, 18 final requests, and `FREEZE.json`. The final request set is
written before any retrieval implementation is evaluated and must be treated as held out
after freezing. The retrieval path receives only `text`, `project`, and `mode`; `qid`, gold
source IDs, required quotes, and forbidden material belong to the evaluator.

The request modes are `current`, `history`, and `all`. Cases cover current decisions,
conditions and exceptions, numeric values, cross-document evidence, handoff, historical
versions, exhaustive lists, absent evidence, and private-scope boundaries. Answerable
cases require multiple exact evidence spans where appropriate. Current questions must not
silently quote historical sources; private memos must not enter shared answers.

For scale work, call `generate(size, scenario, seed)` to create deterministic 100-,
1,000-, or 10,000-source corpora. `unrelated` adds unrelated projects, `mixed` adds
similar project notes, and `long` periodically adds long independent sections. The
generated scale records contain no evaluator labels. Keep each generated output in a new
`runs/phase2-token-growth-*` directory; never overwrite protected fixtures or runs.

Recommended measurements report, separately for each size and method: reference tokens,
selected source count, required evidence recall, stale/condition/private violations,
empty-evidence handling, retrieval median/p95, index/build time, and update cost. A lower
token count is not an improvement when required evidence is missing. Do not pass question
IDs, gold quotes, or expected source IDs to the retriever.
