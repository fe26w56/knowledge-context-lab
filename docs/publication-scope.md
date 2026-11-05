# Initial public preview scope

The `0.7.0rc4.dev1` development preview adds only the scoped Notion Hub runtime modules, setup/acceptance scripts, related tests, CI dependency wiring and [Notion Hub operations guide](notion-hub-operations.md). The earlier reader handoff mode remains available separately. The dev1 wheel is built from this staged source.

The 0.7.0rc4.dev0 update adds the reader MCP, its required delta library, tests and [setup guide](workspace-handoff.md). The following scope describes the earlier 0.7.0rc3 preview.

The first public source tree is an explicit export of the research workspace. The workspace itself contains private-copy references, credentials outside the project, local databases, Python environments, rejected development attempts and very large intermediate traces. It is not a directory to upload wholesale.

## Supported reproduction

The source tree carries the library, CLI/MCP adapter, tests, fictional fixtures, selected measurement artifacts, MIT license and CI configuration. The current reproducible entry points are:

- `scripts/demo_reviewed_context.py`: source review, citation and update invalidation, with no model calls.
- `scripts/demo_workspace.py`: general local workspace lifecycle.
- `scripts/evaluate_reuse.py`: frozen development/final retrieval comparison, including corpus growth.
- `scripts/exercise_reviewed_context_v2.py`: the lifecycle-v3 measurement contract.
- `scripts/analyze_reuse_model.py`: mechanical analysis of included sanitized fictional model responses.
- `python -m unittest discover -s tests`: the preserved regression suite.

Protected `fixtures/synthetic/`, `runs/synthetic-v1/`, frozen fixtures and selected-code hashes stay unchanged. The measured code is not retroactively rewritten for release. Package metadata and the MCP-reported version advance to 0.7.0rc3; the latter is outside the selected retrieval implementation.

## Evidence boundaries

Current reuse evidence includes fixed inputs, source-first review ranges, selection hashes, row-level offline measurements, sanitized requests/answers/usage, semantic reviews, accounting summaries and lifecycle receipts. Sanitization removed opaque provider reasoning and response identifiers; requests, answers, payloads, usage and the calculated metrics are unchanged.

Historical reports remain useful context, but their full original run directories are not all distributed. In the public export, omitted historical local links are marked explicitly. A report mentioning an older raw API run does not imply that its full transcripts are included. Those reports are not the primary reproduction instructions for this release. External benchmark source text and private Notion copies are not distributed.

No new model calls are required to run the tests, demos or saved-response analysis. Re-generating paid answers requires a separately configured key and an existing budget ledger; do not reset a spent ledger or release unresolved reservations to make another run fit.

## Publication checks

Before publishing the initial tree, verify the exported files, credentials/path scan, links in supported documentation, all tests from the export, fresh installation, distribution contents and saved-response analysis. A successful local run is distinct from a GitHub Actions result; cloud CI is confirmed only after the repository exists and the actual workflow completes.

The CI workflow uses full commit pins resolved from the official releases of [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1), [setup-python v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0) and [cache v6.1.0](https://github.com/actions/cache/releases/tag/v6.1.0). Its token has read-only repository permissions, and checkout does not persist credentials. The test matrix is Python 3.11–3.13.

## Release status

0.7.0rc3 is an experimental preview. It supports local inspection and reproduction; it is not a production migration recommendation. GitHub publication status, public commit and CI outcome are recorded separately from the measurement results.
