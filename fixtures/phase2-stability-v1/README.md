# Phase 2 stability diagnostic v1

This is a newly authored, synthetic diagnostic for measuring retrieval stability
as context grows. It is not an independent benchmark. The fixture was frozen
before the next retrieval implementation.

`dev.json` contains eight intents and `final.json` contains twelve different
intents. Each intent has three genuinely different Japanese requests for the
same facts. The cases cover current policy, conditions and exceptions,
cross-document evidence, history, proposals that are not approved, exhaustive
lists, unknown evidence, and shared/private access boundaries.

`corpus.json` is the 100-source frozen corpus. `author_fixture.py` can generate
exactly 100, 1,000, or 10,000 sources. The core evidence records do not depend
on the seed; `seed` changes only unrelated distractors and `order_seed` only
shuffles record order. Historical, private, same-project, and unrelated
distractors retain real metadata. The generator is synthetic and contains no
private or external material.

The evaluator may use `required_source_ids`, exact `required_quotes`, expected
answer fragments, forbidden fragments, and the explicit `answerable` field.
Those are grading-only fields in the question files and are not present in the
corpus. Negative cases intentionally have empty required evidence.

Reproduction:

```sh
.venv/bin/python fixtures/phase2-stability-v1/author_fixture.py
```

The resulting files must match `FREEZE.json`. Run generation with different
`order_seed` values to test order invariance, and with sizes 100, 1,000, and
10,000 to test monotone corpus growth. The authored corpus and questions are a
diagnostic for this project, not a claim about general benchmark performance.
