# Phase 2 completion fixture v2

Revision of `phase2-completion-v1` after independent semantic review. v1 is
untouched. This bundle is fictional and explicitly not an independent
benchmark: 80 opaque-ID documents support 20 dev and 20 final questions.

Every document declares a `source_family`; multi-source questions list
`required_source_families` and require claims from at least two families, with
`no_single_document_satisfies_all_claims: true`. Condition questions quote an
authoritative topic-specific table containing the exact threshold, unit,
condition, and exception. Private-boundary questions asked by a non-owner use
only a shared denial policy as gold evidence and never require private note
content.

`rubric.atomic_claims` has `{key, value, evidence_quote, accepted_source_ids}`
and `rubric.abstain` is required for insufficient questions. `FREEZE.json`
records hashes and confirms the author was blind to implementation changes.
