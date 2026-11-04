# Knowledge Context Lab

**Evidence-preserving context retrieval for local AI agents.** Keep original sources, return reviewed source ranges for known topics, and withhold stale context when supporting documents change.

Development preview **0.7.0rc4.dev0** · Python 3.11+ · [MIT](LICENSE) · [日本語](README.ja.md)

## Per-agent Notion handoffs

Each agent keeps its own acknowledged version of each page. `read_changes` returns a full first read or a delta since that agent's last receipt. `ack_changes` records successful delivery after the host has retained and verified the result. Configure a separate reader ID for each agent. The stdio server runs on the MCP host and stores receipts on its persistent disk.

[Setup and read/ack example](docs/workspace-handoff.md#agent-facing-mcp) · [Installable wheel](releases/0.7.0rc4.dev0/knowledge_context_lab-0.7.0rc4.dev0-py3-none-any.whl) · [Reader tests](tests/test_reader_mcp.py)

## Try it

From a checkout or extracted source distribution:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/demo_reviewed_context.py
```

The fictional demo imports a document, records a reviewed range, returns an exact source citation, changes the document, and verifies that a fresh read returns `needs_review` with no old content. It uses a temporary local SQLite database and makes no model calls. Installation may use the network; the demo does not.

For the general workspace, including source history, optimistic writes, replay-safe requests, export/restore, CLI and local stdio MCP:

```sh
.venv/bin/python scripts/demo_workspace.py --workdir work/workspace-demo-new
```

## What it does

- Preserves original source text, source revisions and evidence offsets.
- Retrieves **reviewed raw text**, rather than generating a summary, for an explicit project/topic key.
- Invalidates a reviewed result in a fresh snapshot after a relevant source revision or a newly added topic member.
- Gives readers a consistent snapshot; an existing snapshot deliberately remains historical after updates.
- Compares retrieval changes separately from file/SQLite storage, using frozen fixtures and saved results.

The reviewed-range path is an opt-in Python API. It does not silently replace the older workspace topic or search APIs. Content review is not approval of a policy. [Reviewed-context guide](docs/reviewed-context-guide.md) · [Workspace guide](docs/workspace-guide.md)

## Measured result

One authored diagnostic used 12 final intents, three repetitions and three response formats: 108 model calls in total. All calls used the same 10,000-source corpus and explicit topic scope.

| Metric, 36 calls per arm | Reviewed full sources | Reviewed source ranges |
|---|---:|---:|
| Required facts or appropriate abstention | 36/36 | 36/36 |
| Actual API input tokens | 24,801 | **21,969 (-11.4%)** |
| Output tokens, including reasoning | 15,917 | 14,162 |
| Usage-based cost estimate, USD | 0.010273215 | 0.009277900 |

With other topics growing from 100 to 10,000 sources, reference input for the fixed topics stayed at a median of 382 tokens. Topic-filtered full sources also stayed constant: growth isolation comes from explicit scope, not from SQLite or raw-range selection alone.

A third citation-ID response format omitted required facts twice and is **not the recommended default answer format**. Exact quotations do not prove answer completeness. Earlier parent-section expansion also failed to improve final quality. Failures are retained alongside the successful comparison.

These are project-authored diagnostics, not an independent benchmark, 36 independent questions, statistical proof of non-inferiority, or a production performance guarantee. Reviewer labor and arbitrary-question routing are unmeasured. [Detailed findings](docs/phase-2-reuse-findings.md) · [Saved responses](runs/phase2-reuse-model-public-v1/results.json) · [Semantic review](runs/phase2-reuse-model-root-review-v1/review.json)

## Reproduce without model spending

```sh
.venv/bin/python -m pip install -e '.[tokens]'
export TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache"
.venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
.venv/bin/python scripts/preflight.py
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/analyze_reuse_model.py \
  --run runs/phase2-reuse-model-public-v1 \
  --fixture fixtures/phase2-reuse-v1 \
  --output runs/phase2-reuse-analysis-my-run
```

Use a new output directory each time. First-time tokenizer setup downloads a dictionary. The saved-response analysis makes no model calls. [Full retrieval and lifecycle reproduction](docs/phase-2-reuse-findings.md#再現方法) uses the frozen fixture and selection manifest. Previously exposed final questions are regression tests, not a new unseen evaluation.

## Boundaries

The Notion reader fetches complete Markdown on demand from explicitly selected pages. Caller identities are trusted local settings. The MCP process runs on the agent host and uses its persistent disk for acknowledgements. Keep the workspace behind your own authorization boundary. Scope/owner transitions are currently rejected; this is not a complete revocation service. Fresh snapshots scan the visible store, and an old in-memory snapshot is not automatically refreshed.

A token ceiling can lose required evidence. The older search and experimental retrieval modules remain available for comparisons, but no profile guarantees completeness. SQLite supplies history and consistent updates; retrieval savings are not database savings. [Security](SECURITY.md)

## Distribution and contributions

The wheel contains the library and command-line entry points. The source distribution adds tests, fictional fixtures, reproducible demos and selected evidence. Large intermediate traces, private source copies, credentials, local databases and runtime environments are excluded. Historical reports describe earlier experiments; some historical raw runs are retained only in the research workspace. [Publication scope](docs/publication-scope.md) identifies the supported reproduction paths.

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [License](LICENSE)
