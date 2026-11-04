# Phase 2 workflow fixture v2

v1 is preserved as an intentionally rejected draft. v2 fixes its evaluation leakage and grading ambiguity:

- tasks contain no source IDs; each wave exposes the whole available corpus and execution applies actor/scope filtering;
- private records use `owner == actor`, while a shared policy explains the safe boundary;
- every task has 3–5 typed output fields and every field is graded in the separate `dev/gold.json` file;
- exact quotes are stored as `{source_id, quote}` and are never runtime inputs;
- dependencies point only to earlier waves;
- unknown fields use JSON `null`.

This is synthetic, project-authored diagnostic data, not an independent benchmark. The sample is for semantic review before bulk generation. Do not alter this directory after freeze; repairs use a new fixture version.
