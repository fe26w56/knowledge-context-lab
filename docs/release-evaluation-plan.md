# Release evaluation plan (before implementation)

Date: 2026-10-30. Goal: a useful local OSS release, without publishing to GitHub or using private source material.

The previous small-corpus final questions are now regression data. The previously measured large-corpus failure is candidate crowding by repeated documents. The adopted fixture is `fixtures/phase2-release-v6/`, with 20 development and 20 final questions with separate topic families. It is homemade, not an independent benchmark.

Fixture drafts v1–v5 are retained but rejected. v1 lacked category balance and opaque IDs; v2 mislabeled single-source questions and contained an ungrounded condition/shared table topic; v3 had additional answer/source/mode defects; v4/v5 had private-question topic mismatches and missing current-mode positives. v6 corrects these with a separate semantic review. The source implementation was written after v3 freeze but before v6 freeze; v6 authors/reviewers did not see that implementation, and v6 was frozen before any valid experiment. The v3 development run was completed but invalidated before its results were inspected or used for tuning. This chronology is recorded explicitly, not described as v6 predating implementation.

## Changes to compare separately

1. Control: previous selected Phase 2 pipeline (stage2, split, definition intent, cosine, 3 candidates).
2. Exact document grouping before indexing. Group only identical title, body, section contents and semantic metadata, including scope and owner. Source IDs/URLs may differ. Return a real representative source, never invent an original-source attribution.
3. Candidate diversity after grouping. Penalize repeated section content when selecting documents; do not treat similar but different conditions as equal. Compare diversity weights 0.5 and 1.0 separately.
4. Only if needed on development failures, compare candidate limits 6/12 as a separate factor. Changes to packing or general semantic interpretation require a separate declared comparison.

Development follow-up (after valid dev-v2, before final): missing source-aware evidence was absent from the candidate set, including named multi-topic questions. Compare exact-grouping + 6 candidates, + 12 candidates, and separately replace cosine with the existing shared BM25 scorer at 3 candidates. No final question or result is consulted.

Both stores must use the same pipeline. A and B must use identical candidates; B/C must have byte-identical payloads. Existing retrieval_v2 stays unchanged so prior snapshots and selections remain reproducible.

## Selection and data

Evaluate budgets 1000/2000/4000 on development data, including 1000-document synthetic mixtures with seeds 8101 and 8102. Select maximum complete source-aware evidence, then minimum forbidden/scope violations (must be zero), missing conditions, tokens, and simplest configuration. Known Phase 2 and original questions are regression gates; no new final question is used to tune.

After freezing configuration and source hashes, evaluate final questions at base size and 100/1000/10000 documents with seeds 9101/9102/9103. Time repeats and seed changes are not additional independent question counts. Preserve old runs and use new `runs/phase2-release-*` paths.

Grade literal quotes and source-aware quotes separately. Accept explicitly declared equivalent exact copies; reject a copied quote embedded in a different condition or proposal. Preserve one evidence requirement per quote/source-set. Empty unanswerable responses are not credited as correct answers. No expected quote, source-set, question ID, family or generator label reaches the retriever.

Record all payloads/hashes, failures, source-aware completeness, conditions, scopes, token counts, median/p95 query time, import/index time, and one-document update + reindex cost. Randomize query/method order. Use an in-process warm index, clear token-count cache each trial; report index reconstruction separately and do not claim cold OS caches. Capture source snapshots and fixture hashes.

## Release acceptance

The release must expose a runnable, documented API/CLI with deterministic examples, tests, installable wheel/sdist, CI configuration, a license text and limitations, synthetic evidence and commands that can be repeated from the exported artifact. A failed architecture hypothesis can be a useful documented result; an unmeasured answer-quality/cost claim cannot. Real model quality, provider charges, D1, external authentication and production taskflow remain separate measurements unless configured and executed.
