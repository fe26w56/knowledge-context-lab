# Phase 2 completion fixture v4

Revision of v3 after semantic audit; v1–v3 are preserved. This is entirely
fictional and explicitly not an independent benchmark. It contains 80 opaque
hash-ID documents and 40 questions (20 dev, 20 final).

Multi-source questions now grade both constraints and the responsible-role
claims, with each role stated in the relevant document body. Insufficient
questions retain named topics (Dahlia, Ember, Xenon, Yonder) and ask for
abstention when their threshold/action/exception combination is absent.
Multi-source and condition prompts use different comparison, handoff, drill,
and exception structures. Condition documents include topic-specific long
matrices and over-budget audit notes; `TOKEN_REPORT.json` was generated with
the project venv's `tiktoken` 0.14.0 using `TIKTOKEN_CACHE_DIR=tokenizer-cache`.

`FREEZE.json` records hashes, tokenizer choice, implementation-blindness, and
the `independent_benchmark: false` boundary.
