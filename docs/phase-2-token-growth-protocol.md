# Token growth diagnostic protocol

Fixed before new retrieval measurements on 2026-11-03. The objective is to find
whether input requirements stay bounded as the knowledge collection grows **while
retaining required source evidence**. A positive result is not required. The new
Japanese cases are project-authored diagnostics, not an independent benchmark.

## Evidence and units

Count every returned source title, ID, status, excerpt and wrapper, plus the common
instruction and ordinary user request. Use `o200k_base` from tiktoken 0.14.0. Report
the sum of separately encoded message contents as reference input tokens; provider
message framing, reasoning/output tokens and invoice usage are not measured by
this offline diagnostic. Full-context input may exceed any usable model window;
such rows describe input requirements, not successful paid model requests.

Keep storage independent: file, SQLite, D1 and remote transport do not change these
counts when the serialized context is identical. A read cache can save fetches
without reducing the bytes/tokens passed to a model. Do not multiply single-query
savings by sixteen and call it measured multi-agent business savings.

## Data gate

The first fixture version failed review: repetitive padding, non-distinct growth
scenarios and development/final topic overlap. Preserve it and its audit; do not
use it to claim successful token scaling. Freeze corrected source/generator,
development and final requests before implementing a new retrieval candidate.
Open final grading only after development selection is saved.

Use 100, 1,000 and 10,000 documents with explicit unrelated-growth and mixed-growth
scenarios. Test longer documents at fixed collection size separately. Record
source byte/token distributions, current/historical/private proportions and exact
duplicate body rate. Repeated seeds change distractors, not the number of
independent questions. Exact duplicate evidence is interchangeable only when body,
project, status and access scope agree; a similar but conditionally different page
is not an equivalent source.

## Incremental comparisons

All arms apply the same actor permission and explicitly requested current/history
mode before content selection. The user-supplied project field is an ordinary
scope constraint, never inferred from a grading label.

1. All visible document bodies: full-collection reference baseline.
2. All bodies in the requested project: scope-only contribution.
3. Up to six ranked complete documents in that project: candidate selection.
4. The same pipeline with exact-duplicate removal: deduplication contribution.
5. Rank complete Markdown sections instead of complete documents, preserving
   exact source text, offsets and status; impose a context-token budget.
6. Suppress exactly repeated sections after ranking, retaining the actual source
   ID of each representative. This is candidate suppression, not equivalence of
   whole sources.
7. Deduplicate sections before building BM25 statistics, to isolate the effect of
   repetition on ranking from its effect on payload size.
8. Prefer lexically diverse sections before near copies: a Jaccard similarity of
   at least 0.8 over the existing lexical tokens defers a candidate until all
   diverse representatives have been considered. Deferred sections remain
   candidates; different conditions are never declared equivalent. This is a
   development-only response to repetitive, slightly changed distractors. The
   threshold is fixed before final evaluation and will not be tuned on it.

Steps 6, 7 and 8 were added sequentially after development runs v1, v2 and v3;
each earlier code version and its results are preserved. Step 7 did not improve
development evidence retention. These additions were made without opening the
final requests. Corpus v1-v3 failed fixture audits and are excluded; v4 passed
with template-distribution limitations, recorded in its independent audit.

Measure 2,000, 4,000 and 8,000 context-token budgets on development data. Select
the smallest that retains all required evidence on the measured development
growth conditions without privacy violations. If none qualifies, retain the
failure and compare the most complete candidate; do not silently relax the gate.
Exhaustive `mode=all` requests use complete project context unless an independently
verified aggregate operation exists. Its growing token requirement must remain
visible, not be hidden by a top-k cutoff.

The retriever accepts only ordinary request fields and source records. IDs of
questions, required quotes, expected source IDs and scoring criteria are loaded
only by the evaluator after each retrieval result has been produced.

## Acceptance and reporting

- Report token median/p95 and paired ratios together with complete-evidence cases,
  missed spans, stale/private-source exposure and explicit context overflow.
- Unknown-answer cases are separate: an empty retrieval is not automatically a
  correct abstaining model answer. Retrieval completeness is not model correctness.
- For point questions, target <=25% token growth when document count grows 100x,
  while retaining all the case's required evidence at every measured size.
- Compare against project-scoped full context as well as the larger global full
  context, so simple scope filtering is not credited to passage selection or a DB.
- Report exhaustive questions separately: when the answer itself expands, a fixed
  input budget cannot be assumed to preserve completeness.
- Save unsuccessful versions and all failed cases; do not tune on final failures.
  Existing external LongMemEval 500-case results remain a separate validity check.
- New paid calls, if needed, use the existing USD 10 ledger without resetting it.
  This experiment may establish input-count/evidence behavior without claiming new
  real-model answer quality or business savings.
