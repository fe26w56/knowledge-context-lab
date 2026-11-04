# Local handoff deltas

## Agent-facing MCP

Install the [wheel](../releases/0.7.0rc4.dev0/knowledge_context_lab-0.7.0rc4.dev0-py3-none-any.whl) in a Python 3.11+ environment, or run `python -m pip install .` from the checked-out repository.

In development preview `0.7.0rc4.dev0`, start one stdio MCP process per independent consumer. `--actor` identifies the trusted access principal and `--reader` identifies a durable consumer such as `research-a`. Two consumers that share an access principal can share a state directory. The server keeps a separate acknowledged version for each source, actor, reader, scope, and page. Use different reader IDs for sessions that retain different context.

For Notion, share only the intended pages with a read-content connection and supply `NOTION_TOKEN` through the host's secret store/environment. Use the same stable workspace identifier across restarts and configure the allowed page UUIDs for each consumer. Restart with a revised allowlist when the intended scope changes. The connection itself determines what Notion permits it to read. A reader ID does not grant any Notion permissions. [Notion authorization](https://developers.notion.com/guides/authorization/overview) · [Markdown retrieval API](https://developers.notion.com/reference/retrieve-page-markdown)

```sh
context-lab-workspace-mcp --notion-workspace agent-hub \
  --notion-page 11111111-1111-4111-8111-111111111111 \
  --actor agent-hub-connection --reader research-a \
  --handoff-state /absolute/private/agent-hub-receipts
```

Replace the example UUID with a real page shared with the connection. Repeat `--notion-page` for additional pages. Configure the MCP host's command as the absolute path of the installed executable and pass the options above as its argument list. For the second agent change `research-a` to `research-b`. Use a dedicated state directory on a persistent local volume (created with mode `0700`). It contains current/previous private text and receipts. For an imported workspace, replace both Notion options with `--db /absolute/workspace.sqlite`. To enforce an external authority with imported data, also pass its trusted `--authorized-view` manifest, described below.

The agent sees two tools. It supplies a page ID, never an actor, reader, state path or API token.

1. Call `read_changes({"page_id":"<id>"})`. A new reader gets the current page as a snapshot. A returning reader gets a delta from **its own last acknowledged copy of that page**. A read by itself leaves the acknowledgement untouched. If your copy was lost, call with `"fresh":true`. The module returns one serialized copy of the packet.
2. The consuming host applies the packet to its saved copy using `apply_update` and persists the result. Only then call `ack_changes({"page_id":"<id>","receipt":"<delivery receipt>","head":"<reconstructed digest>"})`. An acknowledgement records the consumer's confirmation of receipt. It cannot establish whether a model understood the text. Retry a lost acknowledgement with the same values. A superseded delivery must be read again.

```python
from context_lab.handoff_delta import apply_update, snapshot_digest

# delivery is the parsed JSON from read_changes; previous is None on first use.
current = apply_update(previous, delivery["packet"], principal=actor, scope=scope)
head = snapshot_digest(current, principal=actor, scope=scope)
# Durably save current under this reader + page before calling ack_changes.
ack_arguments = {"page_id": delivery["page_id"], "receipt": delivery["receipt"], "head": head}
```

If A acknowledged v1 and B acknowledged v2, after an edit to v3 A gets v1→v3, B gets v2→v3, and a new reader gets v3 in full. Reading page P does not acknowledge page Q. These packets describe the net change to the current version; intermediate edits that were made and reverted are outside this protocol.

The Notion adapter makes one Markdown GET for the requested allowed page on every read, including retries. A confirmed `404 object_not_found` or removal from the operator allowlist yields a purge for a reader who held the page. A transport error, an incomplete or unsupported Markdown response, or an authorization error such as 401/403 returns an error instead of replaying a previous body. The adapter transfers page Markdown; attachments, comments, and separate page properties are outside this format. A Notion page can be opened at `https://www.notion.so/<page UUID without hyphens>`. This mode has no write tools and does not run a webhook. Direct Notion REST has been exercised with simulated responses; a connected credentialed REST run is pending.

For an offline check from the source checkout, run `python -m unittest tests.test_reader_mcp`. It covers separate versions under one account, restart, dropped responses, revocation, and 16 concurrent readers. The existing file-based CLI below remains useful when the caller already manages its own checkpoints.

## File-based CLI

`context-lab-workspace handoff` sends the current authorized source pages relative to a reader checkpoint. The packet keeps `body/<page_id>` as the original body text and `metadata/<page_id>` as a small JSON value containing title, workspace version, and revision ID. A body patch replaces complete lines. For separated edits the sender may send a list of ordered hunks with original offsets when that representation is smaller in bytes. The receiver verifies the digest of the reconstructed state. It does not synchronize authoring metadata, comments, attachments, linked-resource contents, or permissions.

Create the first private checkpoint with a fresh snapshot.

```sh
.venv/bin/python -m context_lab.workspace_cli \
  --db work/workspace.sqlite --actor agent-a handoff \
  --scope shared --next work/handoff/agent-a-001.json
```

After the reader has durably accepted that packet, use its checkpoint as `--base` and choose a new `--next` path.

```sh
.venv/bin/python -m context_lab.workspace_cli \
  --db work/workspace.sqlite --actor agent-a handoff \
  --scope shared --base work/handoff/agent-a-001.json \
  --next work/handoff/agent-a-002.json
```

The base checkpoint uses schema version 3 and is checked against the actor, database identity, scope, and its page head. A mismatched, incomplete, or modified base causes a fresh snapshot. The old page body is never copied into that response. Checkpoints are written to a new file through a temporary file and atomic no-clobber link with mode `0600`. An existing `--next` path is rejected, so the previous acknowledgement remains usable after a lost response.

Private pages require the page owner actor and `--scope private`. A private checkpoint cannot be reused by another actor. Deleted or no-longer-visible pages are represented as purges and their old content is not emitted.

## External visibility boundary

The database-only command describes the local imported scope; it does not prove that an external source such as Notion is still visible. To make a handoff reflect a freshly authorized complete external view, pass a local manifest supplied by the trusted caller:

```json
{"actor":"agent-a","scope":"shared","complete":true,
 "pages":[{"id":"page-1","title":"A","body_sha256":"<64 hex chars>"}]}
```

```sh
.venv/bin/python -m context_lab.workspace_cli \
  --db work/workspace.sqlite --actor agent-a handoff \
  --scope shared --authorized-view work/authorized-view.json \
  --base work/handoff/agent-a-001.json --next work/handoff/agent-a-002.json
```

The command fails closed, without writing the next checkpoint, when the manifest is unavailable or incomplete, actor/scope differs, page IDs are duplicated, a listed page is not locally imported, or its local title/body digest differs. The manifest is not a signature and is not equivalent to Notion connector authentication; the trusted local caller is responsible for obtaining it. A complete manifest is authoritative for visibility: omitted IDs become purges and their old text is not sent.
