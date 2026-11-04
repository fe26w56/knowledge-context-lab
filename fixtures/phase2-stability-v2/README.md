# Phase 2 stability diagnostic v2

This newly authored synthetic diagnostic is frozen before retrieval changes. It
is not an independent benchmark. `author_fixture.py` contains source records
and the growth generator only; it contains no questions, gold spans, or answer
labels.

The 8 development and 12 final intents use disjoint projects and facts. Every
intent has three distinct Japanese requests for the same complete fact set.
Cases cover current policy, sibling conditions and exceptions, history,
unapproved proposals, exhaustive lists, cross-record evidence, unknown
evidence, and private/shared access. Core documents use `##` topic sections
with `###` decision, condition, evidence, and handoff subsections, plus an
unrelated context section.

`corpus.json` is the 100-source frozen corpus. `author_fixture.py` generates
100, 1,000, or 10,000 sources; the core prefix is seed-independent, while the
seed affects only unrelated distractors and `order_seed` only shuffles order.
Metadata retains current/historical and shared/private boundaries. No private
or external material is included.

The evaluator-only fields live in `dev.json` and `final.json`, not in the
generator or corpus. Negative cases intentionally have no required evidence.

Reproduction:

```sh
.venv/bin/python fixtures/phase2-stability-v2/author_fixture.py
```

The resulting files must match `FREEZE.json`. Run generation with different
`order_seed` values to test order invariance, and with sizes 100, 1,000, and
10,000 to test monotone corpus growth.
