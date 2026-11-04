# Notion-shaped workspace migration: protocol

Status: development protocol, 2026-11-03. This extends the completed Phase 2/3 experiments; it does not replace their saved results. No publication or production cutover is authorized. The objective is a usable knowledge workspace for research, decisions, evidence and handoffs, with task execution remaining in the existing task manager.

## Decision and acceptance criteria

The migration candidate must preserve source content, metadata, links, historical versions, conditions, and access boundaries. An imported page is evidence, not an automatically approved decision. A page-level adoption flag must not promote every historical paragraph. Ambiguous or incomplete input must remain visible as such.

A useful candidate must support the complete sequence: import, find, inspect evidence, correct, retry after a lost acknowledgement, reuse, export and restore. A query-only token reduction is insufficient. The primary comparison uses identical sources, requests and model settings. We seek at least 30% less total model cost or completion time, including preparation and correction work, without new material answer failures in the measured cases. Break-even reuse count is reported rather than assuming preparation is free. Passing these internal cases is not population-level noninferiority or proof of long-term business value.

Release gates:

- All supplied source bytes and metadata survive an export/import round trip; unsupported attachments are inventoried, not represented as downloaded.
- Current decisions retain conditions and exact evidence references. Proposals, historical text, missing evidence and stale derived records are distinguishable.
- A source correction invalidates derived current views. Versions and successful request identities survive backup/restore. Conflicting updates cannot silently overwrite one another.
- Sixteen concurrent local clients exercise reads and updates. This is distinct from sixteen production agents, remote authentication, or D1 availability.
- CLI and MCP entry points are exercised from a clean installation. A person can inspect the same records and evidence locally.
- Public packages contain code and fictional examples only. Private evaluation inputs and outputs, if authorized, remain outside the public project tree.

## Fixed evaluation material

`fixtures/phase2-migration-v1` is a typed-record smoke fixture. It is too prestructured to establish value on mixed Notion pages and is not the primary migration benchmark. A separate raw-page fixture is authored and frozen before the new implementation. Development and final requests use distinct themes. Gold facts, expected source spans and request IDs are evaluator-only. The importer receives source pages; the query path receives the request and caller scope, never the gold.

The source corpus may be inspected for migration/schema compatibility. Final task outcomes are opened only after a candidate and evaluation configuration are fixed. Any subsequent tuning uses development data or a newly frozen test set; previously measured final data becomes regression material. These are project-authored diagnostic cases, not an independent benchmark.

## Comparisons and attribution

1. Complete candidate pages with original structure: baseline.
2. The same pages with metadata normalization only: serialization/organization contribution.
3. The same candidates with current-section routing and explicit history access: retrieval contribution.
4. The identical retrieval pipeline over SQLite: storage contribution, checked for exact output parity.
5. Reviewed, version-bound current topic records with original-source fallback: shared knowledge contribution, including initial construction, review and invalidation cost.

Compare sources before/after at every step. Do not credit filters, shorter JSON, current/history labels, or provider caching to the database. Local file/database timings do not measure Notion's network performance. Connector calls, model calls, local queries, ingestion, updates and human review are recorded separately. Repeated calls are not independent cases.

## Minimal candidate design

- Immutable source snapshots preserve original pages and links.
- Stable topic identities provide an entry point across folders and imported database rows.
- A current topic record stores a conclusion, conditions, decision state, information date and exact versioned evidence. Explicit task references link to the task manager; the knowledge store does not fabricate task completion.
- Every update carries an expected version and request identity. Existing local revision/retry storage is reused where appropriate.
- Current views are derived and invalidated when their sources change. The original source and history remain available.
- JSON/Markdown export provides an exit path. Local stdio MCP and a simple inspection surface make the implementation usable by agents and people before any hosted deployment.

SQLite is a local candidate, not a preselected production backend. Its WAL requires same-host shared state; remote agents would need a service boundary. MCP stdio uses newline-delimited JSON-RPC with protocol output separated from logs. References: [SQLite WAL](https://www.sqlite.org/wal.html), [MCP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [Notion block retrieval](https://developers.notion.com/reference/retrieve-a-block), checked 2026-11-03.

## Measurement and continuation

### Actual-workspace comparison prerequisites

The user authorized a separate private evaluation copy. Necessary source pages and model traces stay outside this public project; public receipts contain anonymous numeric aggregates only. The completed pilot used 14 pages, development six and final six requests, with the final comparison fixed before outcomes. Acquisition improved, but the 30% total completion-time/cost target was not established. This result selects acquisition improvements as a local candidate, not a full migration.

The first authorized comparison must resolve three operational questions before claiming a migration benefit:

1. **What information was actually captured?** Use the same captured source set in each arm. Compare body, metadata, linked resources and attachment references. Record omissions explicitly; absent connector truncation fields mean unknown. A reference-only attachment is not its content, and `coverage=all` covers only access-visible local snapshots. Record whether each actual question requires material outside that captured set.
2. **Whose access is represented?** The connector identity and the local trusted actor are different mechanisms. The adapter imports captures privately; promoting a source to shared requires explicit permission mapping. Sixteen local actor labels cannot establish sixteen authenticated Notion permission sets. Measure only identities for which real access evidence exists, and retain the remainder as unmeasured.
3. **What does keeping the copy current cost?** Include remote re-fetch, change detection, import, invalidation, retry and review in correction time. A local body edit is not evidence of remote synchronization. Source edits during the trial require a separately authorized disposable test area; no live operational page is changed merely to benchmark it. A missing fetch alone is not proof of deletion or permission revocation.

Report the current-source fetch, local retrieval, model generation, update propagation and human review separately, then sum the full episode. Reused model responses may support deterministic replay but cannot substitute for a new measured end-to-end trial. No additional paid call is authorized by a new ledger or by resetting uncertain reservations.

Save each experiment in a new `runs/phase2-migration-*` directory with source/config/fixture hashes, full failures, timings and token units. Use the existing USD 10 ledger for any additional paid model calls; uncertain previous reservations remain reserved. Do not retry the interrupted Phase 3 final run.

When a comparison fails, identify whether the cause is source fidelity, retrieval, interpretation, update propagation or operational work. Change one component and measure again on development cases. Missing access or an unmeasured metric is an unresolved measurement, not a reason to declare the migration problem impossible. Continue work that does not depend on that missing access. Do not claim a passed gate until its evidence is saved.

## Operational observation boundary

An additional disposable authenticated HTTPS diagnostic is recorded in
`experiments/network_probe/README.md`. It measures fictional known-ID bodies via a
Worker's baked snapshot and D1 primary-key query, with identical payloads and transport.
Remote acquisition and D1 read-after-ack were measured; full workspace search, Notion
synchronization, multiple geographic clients, and individual agent authorization were not.
The separate live Notion connector timings are not a matched denominator. The temporary
Worker and D1 were removed and absence verified; this is not a production migration.

Existing query/acquisition history is unknown or absent according to the user. The optional observer is off by default and records only digests, timings, result counts and error types. Keep its event files private. Diagnostic and operational kinds are separate; a controlled replay does not create an operational history. Exact repeats require the same request, actor, operation, mode, settings and returned payload. Source-version changes split groups. This describes repeated retrieval, not semantic duplication, answer reuse, business savings, or user-confirmation time. The first private observation diagnostic recorded 32 successful reads and one deliberate failure; actual operational events remain zero.
