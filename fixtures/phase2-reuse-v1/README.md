# Phase 2 reuse diagnostic v1

This is a newly authored synthetic diagnostic, not an independent benchmark
and not evidence of real human review. It tests whether sixteen agents can
reuse one reviewed decision with its conditions, exceptions, and provenance.

The source-first phase creates `corpus.json` and `review_manifest.json` before
questions are authored. The manifest records the exact source version, body
hash, byte range, topic key, scope, and synthetic review state. Only current
shared records are marked `synthetic_reviewed`; private, proposal, and
historical records are excluded from the reviewed scope. `stage1_hashes.json`
records the source-first hashes before `dev.json` and `final.json` were made.

Questions use operational `topic_id` keys rather than question IDs or gold
terms. They request the decision, applicability, exception, and evidence
together. Two-source dependencies are present. One private topic is
unavailable to a non-owner, one topic is unknown, and one is explicitly
`needs_review`. `mutations.json` is reserved for update scenarios such as
correction, added dependency, and retirement.

The generator contains sources and growth generation only; it contains no
questions or gold. It can generate 100, 1,000, or 10,000 sources. Growth
distractors remain inside the two projects but use unrelated topic keys, so
project scoping is measured separately from any database effect.
