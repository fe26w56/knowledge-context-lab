# Reviewed source ranges for known topics

This experimental local library returns reviewed **original text**, its version
and offsets for an explicit `project` and `topic_id`. It is useful when an agent
already knows which task or policy it is checking. It does not infer a topic from
an arbitrary question. The measured results and limitations are in the
[reuse findings](phase-2-reuse-findings.md).

Run the fictional example from a source distribution:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[tokens]'
.venv/bin/python scripts/demo_reviewed_context.py
```

The example creates a temporary SQLite workspace, imports a source, records the
reviewed range, resolves its citation, changes the source, and verifies that a
fresh read withholds the old result. It makes no network or model calls and
deletes its temporary workspace on exit.

## Contract

1. Store the original source with explicit scope, owner when private, project,
   topic, source version and state. Importing or reviewing a proposal does not
   adopt it.
2. Have a content reviewer select original ranges with all relevant decisions,
   conditions, exceptions, evidence and update rules. `publish(...,
   confirmed=True)` records the caller's assertion of review. It cannot verify
   that a human actually reviewed the material or that the selection is complete.
3. Include every visible source for that topic in the review manifest. Each
   range supplies `source_id`, external `source_version`, `body_sha256`, `start`,
   `end`, `scope`, `topic_id` and `reviewed=True`. Offsets are Python Unicode
   character offsets, not UTF-8 byte offsets. Store versions are separate from
   the external source's version label.
4. Use `ReviewedWorkspace(workspace).snapshot(actor=...)` and
   `view.context(project, topic_id)` to obtain one consistent observation.
   `available` supplies the ranges; `needs_review` supplies no sources after a
   relevant change or missing review; `unavailable` supplies no sources when
   that caller cannot see an applicable topic. A changed body, version or topic
   membership invalidates the reviewed result in a **fresh** view.
5. After checking changed sources, publish again with the review record's
   `expected_version`. Request IDs provide replay protection. Retain the
   original source and prior versions for audit.

The actor is a trusted local identity string, not a remotely authenticated
principal. Scope/owner transitions are currently rejected by the underlying
store; this API is not an implementation of revocation or a hosted permission
service. Multiple topic labels, hierarchy, synonym resolution and automatic
Notion synchronization are outside this API.

## Snapshot lifetime and cost

An existing view deliberately stays unchanged after updates. Share that view
within a bounded task when all readers must use the same observation, then
refresh at the next freshness boundary. Do not call an old view “latest”.
Snapshot construction currently scans the visible workspace. At 10,000 sources,
constructing a fresh snapshot for each of 16 local readers cost 14.73 seconds
in one diagnostic; reading an already constructed view excluded that cost.
There is no automatic invalidation of an in-memory view.

Other topics growing do not enlarge a known topic's response. New relevant
sources do invalidate its review; after re-review they can increase its size.
This is a scope property, not a universal constant-token guarantee.

## Citation and answer quality

`render_citations(context, citation_ids)` returns exact text from the provided
ranges and rejects unknown IDs. It proves membership of the citation in that
context, not that the selected text supports a generated claim. The model-based
citation-ID arm omitted required facts twice in the saved diagnostic, so it is
not the recommended default answer format. The measured candidate is reviewed
raw ranges with the existing answer format.

If generated claims use `source_id` and a `quote`, validate the quote against the
returned body/span. Metadata claims need a separate field provenance policy:
a quote of JSON `status` or `version` can be truthful without being a literal
quotation of the document body. Preserve that distinction during scoring.

No claim of lower total operational cost includes unmeasured reviewer labor.
Use the same topic and actor scope for comparison with a full-source baseline.
