# Phase 2 workflow fixture v1

This is a project-authored synthetic workflow diagnostic, not an independent benchmark. It is intended to test whether 16 distinct actors can reuse evidence safely across investigation, decision, handoff, update, and re-question waves.

`schema.json` defines the episode shape. `dev/episode-wf-dev-01.json` is a pre-implementation example only. Gold fields are offline grading data and must not be sent to retrieval, shared packets, or the answering model. The private source is visible only to `agent_04` and `agent_15` in the example. The r2 source supersedes r1; r1 remains preserved to test stale-decision handling.

Before bulk generation, this schema and example must pass structural and semantic review. After dev/final episodes are created, write a new `FREEZE.json` with hashes before changing retrieval or shared-packet code. Never overwrite this version; repairs use a new fixture directory.
