# Local knowledge workspace guide

This guide demonstrates the local migration candidate against the fictional raw-page fixture in `fixtures/phase2-migration-v2`. It is a diagnostic OSS example, not a production service or an independent benchmark. The fixture contains no private user material. Use an access-filtered source export; do not copy real Notion pages into a public package.

The workspace separates two things that are easy to mix in a page system:

- imported source pages, kept verbatim with page metadata, source version and history;
- reviewed topic records, which require explicit evidence and an explicit state. Importing a page never makes a decision adopted.

Task ownership and completion remain in the task manager used by the deployment. A `task_refs` value is a link, not proof that a task is complete. An approval field is a trusted assertion supplied by the caller; it is not cryptographic identity or an authentication service. The CLI and MCP actor is a trusted local process setting, not authentication. The local SQLite candidate is not a D1 or remote multi-agent deployment. Attachments are retained as source URLs and metadata; they are not downloaded.

## One-command demonstration

This command creates a new temporary workspace, calculates the exact evidence offset from the original page, publishes a proposed topic, corrects its source with an expected version, observes `needs_review`, reads the historical topic, exports and restores the bundle, and checks export parity. It exits nonzero if any assertion fails.

```bash
.venv/bin/python scripts/demo_workspace.py --workdir work/demo-workspace-v2-script
```

The target must be new or empty. Omit `--workdir` to use and remove a temporary directory automatically. No JSON side files, credentials, Notion access, or real documents are assumed.

## Reproduce the basic flow

Create a virtual environment and install the package as usual. The following commands use a new database and temporary JSON files. Keep the fixture and previous `runs/phase2-*` outputs unchanged.

```bash
DB=work/demo-workspace-v2/workspace.sqlite
ACTOR=ops-bot
mkdir -p work/demo-workspace-v2

# Use only pages visible to this local actor. The public fixture includes a
# private example that must not be imported under another actor's identity.
python3 -c 'import json; p=json.load(open("fixtures/phase2-migration-v2/pages.json")); json.dump({"pages":[x for x in p["pages"] if x["scope"]=="shared" and x["id"].startswith("dev-")]},open("work/demo-workspace-v2/pages.json","w"),ensure_ascii=False)'

.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  import-pages --input work/demo-workspace-v2/pages.json --request-id demo-import

.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  search 'Cedar 公開条件' --mode current

.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  source dev-cedar-main
```

`search` returns source IDs, source versions, exact section offsets and an explicit history omission list. `source` is the inspection path for the original page and its current version. Use `--mode raw` when preserving the full page is more useful than current-section routing; `--mode compact` removes duplicated storage wrappers while retaining the original page body and fields.

Use `--mode capture` only when an imported source contains a connector `raw_capture`. It returns the selected source ID/version/hash plus that capture exactly once, without duplicating the rendered body. Missing capture data is an explicit error; it is not silently replaced. This fictional example does not measure Notion network time or establish a database saving.

Ranking is `legacy` by default. `--ranking overlap` is an opt-in title/body term-overlap ranker; `--ranking bm25` is an opt-in BM25 ranker for exploratory history retrieval. Both preserve the full selected source payload and can be combined with `--mode compact`. The BM25 behavior has only a limited English external-history check; superiority for Japanese Notion migration has not been established.

For aggregate questions, use the separate `context` command so top-k search is not mistaken for complete coverage:

```bash
.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  context '合計で全件を確認' --coverage all
```

`coverage=all` returns every source visible in the supplied local snapshot, including full original bodies and metadata; it does not mean all external knowledge. `coverage=ranked` applies the candidate cap, and `auto` uses an exhaustive-language heuristic. Private pages remain excluded by the local actor boundary. MCP exposes the same `context` tool and coverage values.

## Opt-in observation

Optional redacted observations are off by default. Add `--observe-dir PATH --observation-kind diagnostic` to the CLI or MCP process to write one `0600` JSON event per search/context call into a `0700` directory. Events contain only digests, mode/settings, duration, result count and error type; they never contain the request, actor, source text, IDs or exception message. Summarize one kind at a time with `scripts/summarize_observations.py`; observation counts are never represented as measured business benefits. Duration covers the retrieval attempt before observation file I/O; p95 uses nearest rank. Hashes are pseudonymous, so keep event files in a private directory outside public artifacts. Existing directory permissions are preserved; newly created directories use 0700.

```bash
OBS_DIR=/path/outside/repository/observations
.venv/bin/context-lab-workspace --db "$DB" --actor "$ACTOR" \
  --observe-dir "$OBS_DIR" --observation-kind diagnostic \
  search "Cedar 公開条件" --mode current
.venv/bin/python scripts/summarize_observations.py \
  --directory "$OBS_DIR" --kind operational
```

Only calls through this workspace's `search` and `context` are observed. Direct Notion calls or other tools are outside this recorder. Zero operational events means no daily calls were recorded here, not that the agents performed no work.

Use `operational` only for actual daily use. Leave tests and replays labelled `diagnostic`. This option does not connect production agents, start monitoring Notion, enable a cache, or estimate a cost saving.

## Publish a reviewed topic

A topic payload contains `title`, `summary`, `conditions`, `state`, `as_of`, and `task_refs`. Evidence must pin `source_id`, `source_version`, character `start`/`end`, and the exact `quote`. An `adopted` topic additionally requires an approval record with `confirmed_by`; a proposal does not become adopted because it is imported or frequently retrieved.

For a real source, calculate offsets against the exact body returned by `source` and create two local files:

```json
{"title":"Cedarリリース","summary":"公開条件を3つ保持する。","conditions":["全テスト成功","脆弱性スキャン0件","担当者レビュー1名以上"],"state":"proposed","as_of":"2026-09-12","task_refs":["Task Cedar-41"]}
```

```json
[{"source_id":"dev-cedar-main","source_version":1,"start":0,"end":10,"quote":"exact substring from source body"}]
```

The evidence example above is intentionally schematic: replace the offsets and quote with an exact substring from the source inspection output. The command is:

```bash
.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  publish cedar --payload work/demo-workspace-v2/topic.json --evidence work/demo-workspace-v2/evidence.json \
  --expected-version 0 --request-id demo-publish
```

## Correct a source and detect stale knowledge

An existing page correction requires an explicit mapping of page ID to the version that was read. A missing or stale mapping is rejected. After a source changes, a topic whose evidence points at the old version is returned as `needs_review` without an actionable payload; its history remains available by requesting `topic --version 1`.

For a connector-rendered Notion capture, correct the capture's `<content>` and pass it through `notion_pages` again. Editing only the derived `body` while leaving `raw_capture.text` unchanged is rejected; opaque non-Notion `raw_capture` values remain compatible.

```bash
printf '{"dev-cedar-main":1}\n' > work/demo-workspace-v2/expected-versions.json
.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  import-pages --input work/demo-workspace-v2/corrected-page.json \
  --expected-versions work/demo-workspace-v2/expected-versions.json --request-id demo-correction

.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  topic cedar
```

The correction path preserves the old source revision and prevents a stale approved or proposed summary from being treated as current. Repeating the same request ID is idempotent; reusing it for different content is rejected.

## Export and restore

Export is a portable, integrity-hashed bundle containing visible revisions, heads, and request receipts. Restore always targets a new path and verifies the hash, contiguous history, source identity, and request bindings.

```bash
.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  export --output work/demo-workspace-v2/bundle.json
.venv/bin/python -m context_lab.workspace_cli --db "$DB" --actor "$ACTOR" \
  restore --input work/demo-workspace-v2/bundle.json --destination work/demo-workspace-v2/restored.sqlite
```

The repository's interface test runs this import → search → source → publish → correction → `needs_review` → export → restore sequence against the fictional fixture. It does not claim a remote 16-agent production deployment, D1 semantics, human correction-time savings, or Notion API equivalence.

## MCP stdio

The MCP adapter is local stdio JSON-RPC and does not open a network port:

```bash
.venv/bin/python -m context_lab.workspace_mcp --db "$DB" --actor "$ACTOR"
```

Send `initialize`, then `notifications/initialized`, then `tools/list` and `tools/call`. Available tools are `import_pages`, `search`, `get_source`, `list_topics`, `get_topic`, `publish_topic`, and `export_bundle`. The process-level actor is authoritative for this local adapter; passing an actor inside a tool argument is rejected. MCP protocol negotiation and error behavior are covered by `tests/test_workspace_interfaces.py`.

## Private authorized pilot

Keep authorized connector captures and all model transcripts outside the public repository. The pilot accepts a `pages.json` object with `privacy: "private_authorized"` and pages produced by `notion_pages(captures, owner="pilot-owner")`. It requires every page to remain private to that actor. It does not infer access rights from a connector response or make a Notion write.

Freeze separate development and final request files before choosing improvements. Each request has an evaluator-only `case` and ordinary `request`; gold stays in a separate file. Model payloads contain only the request and selected sources. `run_workspace_pilot_model.py` verifies the source and request hashes, requires an existing USD 10 ledger for `--live`, and does not automatically retry errors. Its freeze file uses `source_freeze_sha256` for the pages file hash and a `sha256` map for request filenames. Source captures may include old and new statements; a page-level adopted flag does not approve every paragraph.

```bash
# Replace this with a separately authorized directory outside the repository.
PILOT_DIR=/path/outside/repository/private-pilot
PYTHONPATH=src:. .venv/bin/python scripts/evaluate_workspace_pilot.py \
  --pages "$PILOT_DIR/pages.json" --requests "$PILOT_DIR/requests-dev.json" \
  --output "$PILOT_DIR/offline-new.json" --actor pilot-owner --candidate-pages 1
```

The offline harness compares file and SQLite output, sixteen local reads, controlled private correction, stale-topic withholding, retry, old-version preservation and restore. Its correction is a simulation on the copy, not remote Notion synchronization. A later `capture` read must return the corrected capture and version. The command refuses repository-contained inputs/outputs and existing output files.

For a paired model experiment, save a private manifest containing one entry per call: `case`, `condition` (`notion_fetch` or `file_mirror`), private `run` directory, and `acquisition`. A Notion entry records `fetch_ms` and `exact_capture_equal`; a file entry records `local_acquisition_seconds` and `payload_equal`. Remote re-fetch must match the frozen source before using its captured input. Alternate condition order, and keep model input/prompt/schema identical. This compares acquisition routes over the same local ranking; it does not benchmark native Notion search.

```bash
PYTHONPATH=src:. .venv/bin/python -m scripts.audit_workspace_model_results \
  --manifest "$PILOT_DIR/paired-manifest.json" \
  --output runs/phase2-private-pilot-reproduction-new/paired-audit.json
```

The audit checks complete request hashes and exact source quotations and exports anonymous numeric rows only. It does not score meaning. Review factual correctness, fixed-gold completeness and quotation support separately; preserve misses. Private material is not part of the public evidence bundle, so other users reproduce the method with their own authorized material or the included fictional examples.

The summary separates repeats within one actor from matching retrievals across actor labels. Cross-actor overlap requires the same request, operation, mode, settings and returned payload; it is not permission to share private answers. Empty-result counts are included so repeated failed searches are not mistaken for successful knowledge reuse. Actor labels come from trusted local configuration, not remote authentication.
