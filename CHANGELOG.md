# Changelog

## 0.7.0rc4.dev1 — Notion Hub development preview

- Add the scoped shared Hub service, durable bot client, guarded Notion operations and synthetic integration tests.
- Add setup and bounded acceptance-test commands; see [Notion Hub operations](docs/notion-hub-operations.md).


## 0.7.0rc4.dev0 — per-reader handoffs

- Add read-only MCP tools for page changes and independent acknowledgements per reader.
- Support complete Markdown reads from operator-selected Notion pages and a local workspace source.
- Add lossless handoff packets, multiple-reader tests and a setup guide. Credentialed live Notion REST validation is pending.

## 0.7.0rc3 — initial public preview

- Add explicit-topic reviewed source ranges with source-set and revision invalidation in fresh snapshots.
- Add exact citation reconstruction and lossless overlap compaction as separate library helpers.
- Include frozen fictional fixtures, 108 sanitized model responses, semantic review, failure cases and offline analysis commands.
- Keep the citation-ID response format experimental after two observed completeness failures.
- Preserve the local workspace, source history, optimistic writes, replay protection, export/restore, CLI and stdio MCP.
- Reduce distribution scope to source, tests, fixtures and curated evidence; exclude large intermediate model traces and local runtime artifacts.
- Report the installed package version in the MCP initialize response and document contribution/build commands without hard-coded old archive versions.

Earlier 0.7.0rc2 archives were local validation artifacts. This preview does not claim production authentication, Notion synchronization, universal retrieval completeness, or statistically established answer-quality improvement.
