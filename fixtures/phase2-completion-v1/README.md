# Phase 2 completion fixture v1

This is a fully fictional completion fixture, not an independent benchmark. It
contains 80 opaque-ID documents and 40 questions (20 `dev`, 20 `final`). Each
question's `request` has exactly `text`, `actor`, `scope`, `mode`, and `as_of`.

The answer contract is explicit in `grading.json` and each query's `rubric`:

```json
{
  "atomic_claims": [{
    "key": "stable claim name",
    "value": "required claim",
    "evidence_quote": "exact quote in an accepted document",
    "accepted_source_ids": ["opaque document id"]
  }],
  "abstain": false
}
```

An answerable question must satisfy every atomic claim with its quote. An
unanswerable question has `answerable: false`, an empty `expected_quotes`, and
`abstain: true`. `author_fixture.py` is the deterministic authoring source;
`FREEZE.json` records the frozen hashes and states that the fixture is not an
independent benchmark.
