# Phase 3: controlled workflow protocol

2026-11-02. Written before the workflow retrieval/reuse/record implementation and before new inference calls. The Phase 2 results remain unchanged. This experiment tests a bounded synthetic workflow, not production agents or an independent benchmark.

## Question and scope

Can evidence reuse lower total cost and elapsed time while preserving decisions, provenance, access control and handoffs across 16 actor requests? A case has four dependency waves of four actors. Tasks in one wave can run concurrently; dependent waves cannot. Sixteen actors does not mean sixteen simultaneous model calls.

The factorial fixture has eight development and eight final cases: short/long documents, low/high reuse, revision/withdrawal. Both splits share four controlled operation families; the effective sample size is eight cases per split, not 128 independent tasks. The fixture is accepted only after an independent structural and semantic audit. Rejected drafts remain separate. Freeze hashes must verify before any run. Gold stays in separate files and is loaded only by the grader.

## Arms and attribution

1. `full6`: original full-document retrieval, six candidates.
2. `full12`: same retrieval, twelve candidates, a strong baseline.
3. `reuse12`: full12 plus coalesced retrieval caching only. Same visible snapshot and query must yield byte-identical model context. Model inference still runs for every task.
4. `record12`: reuse12 plus an evidence record built from the same twelve candidates. It is built once per compatible visible snapshot/topic/area and includes quote provenance. All construction and rebuild calls count toward the case.
5. `fallback12`: record12 plus at most one original-context answer attempt when the first answer reports missing evidence or fails citation validation. Both attempts count. It cannot consult the grader to decide to retry.

Queries use the public topic and area, equally in every arm, rather than gold source IDs. State metadata remains visible: proposals and withdrawals must be answerable. A snapshot includes active heads at the specified time. Access filtering occurs before indexing. A cache key includes the entire visible corpus content, time, query and configuration, so additions, deletion, revision and permission changes invalidate reuse. Only identical visible snapshots may share records. Private sources partition the cache. Handoffs use actual predecessor outputs; a handoff with inaccessible source provenance is withheld in its entirety. The incoming-status field is graded against the actual handoff supplied, separately from current truth.

The first implementation uses conservative invalidation, not differential updates. It does not introduce a DB. Retrieval caching, generated records and fallback are separate changes; none is credited to storage.

## Development and selection

Run a small development smoke first, then the full eight-case development matrix as the shared USD10 envelope permits. Inspect failures and overhead using development data only. If a correction is needed, save a new run and implementation snapshot; never replace old responses. Changes to a method, output contract or selection rule must be explicit. The final comparison freezes methods, prompts, schemas, source hashes, pricing and grader rules before opening final metrics.

The final matrix compares both full baselines with the selected candidate; a second candidate is allowed only if development shows a materially different quality/cost tradeoff. Randomize method order per case with a fixed seed. Provider prompt cache is observed separately; order and cache counts are retained. API success is not answer success. Do not tune on final results. If final data invalidates the hypothesis, reject it or require another separately frozen dataset.

## Outcomes and decision rules

Report exact field correctness, required-source coverage, valid quote provenance, unauthorized-code leakage, current-state correctness and actual handoff fidelity. Report strict whole-case success and paired task differences, including failures with correct citations but wrong conclusions. Mechanical grades are audited against source text; ambiguous grades receive a separate review, preserving original outputs. A citation being an exact substring does not prove that a generated claim is entailed.

Count all model input, cached input, cache writes, output, unsuccessful attempts, record generation, retries, retrieval/index work and wave wall time. Save provider usage and rate-card estimates, with intervals when write detail is missing. The conservative budget ledger is not a bill. No human correction-time measurement is invented. Record reuse has to repay its construction cost; report short/low-reuse cases even when unfavorable.

The exploration target is 50% total cost reduction and 30% elapsed-time reduction with preserved quality. Candidate adoption requires no observed privacy/state regression, no strict case-success loss, and savings robust to the reported cost interval. With eight controlled cases, population noninferiority is not established even if all agree. Show paired case uncertainty (exact win/loss counts and bootstrap intervals for cost/time), and identify a conditional experimental option rather than claiming a universal optimum. A failed target is a valid result. No further method is added solely to force a positive conclusion.

## Budget, preservation and verification

Reuse `work/phase2-live-budget-20261102-v1.sqlite`, authorized cap USD10 across all phases. Starting conservative accounting is USD2.517592625 including a historical USD0.02 unresolved allowance. Reserve the verified full model input bound and the request output maximum before each call. No automatic transport retries; unresolved usage retains its reservation. Stop on budget or settlement uncertainty rather than hiding costs. Batch concurrency is at most four, further limited by safe reservation headroom.

Keep `fixtures/synthetic/`, `runs/synthetic-v1/`, earlier fixtures and run directories untouched. New outputs use `runs/phase2-workflow-*`. Save a source snapshot and manifest with each measured run. Additional local tests exercise concurrent coalescing, revision/addition/deletion/permission invalidation, corrupted records and private handoff rejection. Run Python 3.11 and the current Python suite, wheel/sdist installation and replay checks for the final local release. No publication, production use, D1 deployment or real/private documents are authorized.

## Development addendum: handoff interpretation and provider prefix reuse

2026-11-03 JST, after v6 development cases 1–7 began and before this change or final metrics. The original v5 fixture was frozen before implementation; v6 is a necessary/sufficient-condition wording repair after v5 smoke, frozen before valid comparison. The old smoke measurements are retained with diagnostic-only status.

An independent review of 64 full12 tasks found six direct-predecessor copying errors: actors copied the predecessor's older `incoming_status` rather than its current `status`. This is an instruction/reading failure shared by storage methods. Test `handoff12` against full12 by adding only an explicit instruction to distinguish these two fields. Also test `handoff6` so a compact full-document baseline receives the same clarification. Do not credit this improvement to record reuse or a DB.

Then test `prefix12` against handoff12 by changing only the serialization order: identical source evidence comes first, followed by actor, request and actual handoff. Provider cache usage is observed rather than assumed. The output schema, source candidates, model, answer requirements and handoff instruction stay identical. Retrieval-cache coalescing is already checked separately with 384 byte-equal context pairs across eight development cases and three timing repeats; no duplicate paid answer runs are needed for that local-only property.

Development selects promising configurations; final evaluation compares clarified six/twelve-document baselines with a candidate only if there is a plausible quality/cost/time advantage. Record methods that lose on construction cost, time or evidence completeness may be rejected at the development gate. Final claims remain bounded by eight controlled cases. Any final sample size, repetition and comparison configuration is written into the selection artifact before final execution.

## Development addendum: explicit cache boundary

After dev-v2, all 384 calls reported zero cached input. Ordering JSON keys alone did not create a reusable provider cache boundary. The official prompt-caching guide (verified 2026-11-03 JST) specifies that GPT-5.6 and later implicitly select eligible message endings; explicit `prompt_cache_breakpoint` on an input-text block can select the shared prefix. Add `cache12` as the next single configuration: the same handoff12 source/task data in two text blocks, with an explicit boundary after the sources. Implicit end-of-message caching remains enabled, and default 30m lifetime remains unchanged. Record actual usage; block segmentation may affect model reading, so quality is tested independently. No cache-hit or savings claim is made before measurement.

The same guide documents default 30m write pricing when TTL overrides are absent. Raw old intervals remain unchanged; a separate recalculation uses saved requests plus observed write counts to derive rate-card estimates. It is not an invoice or credit-balance measurement.

## Development addendum: stable response schema

The explicit-boundary smoke produced actual cached input (10,788 tokens in short/high reuse and 23,032 in long/high reuse), with 16/16 strict task success in each case. Different task-specific response schemas still precede the shared source prefix and can prevent sharing across task types. Test one further change, `uniform12`: keep the cache12 sources and boundary, use a fixed array-of-fields response schema, and move the same public typed field descriptions into the request tail. Values and citations are converted losslessly into the existing answer representation; missing, duplicate, extra or mistyped fields are rejected, never filled or coerced. The authoritative gold and decision semantics are unchanged. This is a response-contract placement experiment, not a DB or generated-memory effect. The schema subset was checked in the official Structured Outputs guide before use. Complete development comparison before selecting final arms.

## Execution deviation: interrupted second final repetition

After freezing the selection for two repetitions, r1 completed all 384 calls. In r2, one case-arm completed (16 calls), followed by three successful and one failed concurrent requests in the next arm. The URLError returned no response ID or usage. The predeclared stop-on-uncertainty rule ended paid execution; the full USD0.5808792 reservation remains. No retry or replacement run was dispatched. The complete paired analysis therefore uses only r1; r2 remains failure evidence. Repetition stability is unverified. No model/retrieval configuration, fixture or primary grade was changed after final opening. A post-hoc analysis addition reports task-level wins/losses and new field errors so equal case totals cannot conceal individual regressions; it does not change responses or the primary grading rule.
