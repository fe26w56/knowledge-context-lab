# Phase 2 workflow fixture v3

v1 and v2 remain preserved as rejected drafts. v3 fixes source leakage, private-owner mismatch, incomplete grading, same-wave dependencies, date/quote ambiguity, and null-only output fields.

The sample keeps the whole available source set at each wave. Runtime filtering uses `scope=shared` or `scope=private` with `owner == actor`; task source IDs and gold are never runtime inputs. All 16 tasks have typed, objectively gradable fields. The private internal code is present only to test non-disclosure, and `agent_15` can answer the boundary from the shared policy without receiving that private source.

This is a project-authored synthetic diagnostic, not an independent benchmark. After third-party semantic/structural audit, generate 12 development and 12 final episodes with distinct domains, values, dependency graphs, reuse rates, document lengths, and distractors. Record that diversity in the final README and freeze hashes before implementation or measurement. Never overwrite v3 after freeze; repairs use v4.
