# Migration acceptance fixture v1

This is a self-authored, fictional diagnostic fixture for comparing a current-page knowledge layout with a candidate migrated layout. It is not an independent benchmark, a production corpus, or evidence about the user's private Notion workspace.

The fixture is frozen before the migration implementation. `corpus.json` contains versioned knowledge records. `dev.json` and `final.json` contain distinct task episodes and were authored with disjoint topic names. `gold` fields, expected evidence, and task identifiers are evaluator-only; a retriever receives only each task's `request`.

Each record has: `record_id`, `topic`, `title`, `version`, `state` (`current`, `historical`, `proposal`, or `reference`), `effective_from`, `effective_to`, `visibility`, `updated_at`, and `sections`. Each section has a stable `section_id`, heading, and text. A task has `task_id`, `request`, `kind`, and evaluator-only `gold` containing expected facts, required evidence, and forbidden stale/proposal facts. `operations` exercise correction, supersession, repeat retrieval, and export/import; they are not sent to the retriever as answer keys.

The eight task kinds are: current decision with conditions, unresolved-items listing, source/version lookup, correction and invalidation, explicit-approval supersession, repeat retrieval, historical preservation, and roundtrip export/import. The records intentionally contain near matches, stale versions, proposals, and unrelated notes, while keeping the facts internally consistent.

The `dev` and `final` splits use different fictional entities and values. They are small diagnostic samples, not statistically powered evidence. A migration result is meaningful only when it preserves current-state selection, conditions, evidence links, historical access, visibility boundaries, and update semantics while reducing retrieval/update work under the same task set.

`FREEZE.json` records file hashes. Any repair requires a new fixture version; do not edit these files in place after measurements begin.
