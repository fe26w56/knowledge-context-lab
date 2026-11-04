# Reviewing saved model answers

This is the offline scoring protocol for the completion experiment. It was added before any live model response was available. Tests use fabricated outputs or a mocked HTTP transport; they do not measure model quality. The saved 0.4.0rc1 artifacts predate this scorer and the complete failure-recording fix; rebuild a later candidate after live validation.

The frozen fixture rubric, task inputs and retrieval configuration remain unchanged. Gold and rubric data are loaded only by this offline scorer. The request runner sends neither to the answering model.

## Evidence and judgments

`context_lab.model_quality prepare` binds every expected task to one saved model attempt, checking its key, index, request, context and completed output. It checks the fixture and generator hashes against the frozen retrieval run, regenerates the exact synthetic source corpus, and validates each citation against both the context actually supplied and the source body. An empty quote, unavailable source, wrong scope, missing citation, forbidden literal, wrong abstention flag or missing required source cannot be overridden by a passing review.

Generated conditional or similar documents are not automatically substitutes for a required canonical source. Only the base source and its exact copies can satisfy that source requirement. A genuine quote from the right source is still insufficient to establish a correct claim.

Review every required atomic claim and the following criteria using `pass`, `fail`, `uncertain` or `unreviewed`:

- State and time: distinguish current/adopted rules, past decisions and proposals, including conditions and exceptions.
- No unsupported claims: assess both the answer prose and the structured claims; a correct citation does not justify an unrelated assertion.
- No private leakage: also check paraphrased leakage, which a literal-string check cannot establish.
- Citations entail claims: the quotes and accepted source lineage must support each assertion, including every required condition; reject irrelevant quotes from an otherwise valid source.
- Abstention and missing information: for insufficient questions, identify all missing fields in the rubric; bare refusal is insufficient. For answerable questions, unwarranted abstention fails.

Supply a reviewer identity and a specific rationale. This may be an agent-assisted review; record that fact rather than claiming independent human assessment. `uncertain` and `unreviewed` never count as success. Automatic failure resolves a trial as failed but does not mean its semantic review is complete. File hashes check consistency, not provenance authentication or reviewer honesty.

The reviewer-facing `review-packets.json` withholds the variant/method labels and excludes costs and timing. The internal `result.json` includes the joining map and must not be provided for a label-withheld review. The packet still shows source identifiers and answer length; this is an aid against label bias, not proof of a fully blinded study.

Review packets also include `supplied_context` (the actual input, without its method label) and `canonical_sources` (the rubric's source documents, including section states). Canonical sources were not necessarily supplied to the answering model. Check both sets explicitly: a justified abstention caused by retrieval failure does not make the overall task successful, but it is not an unsupported assertion. Metadata can support a date statement without being a verbatim body quote. If the question, rubric, and source conflict, record the ambiguity; do not promote a draft into an adopted policy to satisfy a flawed rubric. These evidence fields were added after the first 320 live attempts; those initial reviews used a separately saved source-context sidecar, and the original packets remain unchanged.

## Commands

After actual responses have been saved to a new model run directory:

```bash
.venv/bin/python -m context_lab.model_quality prepare \
  --tasks runs/phase2-completion-model-inputs-v2/tasks.json \
  --mapping runs/phase2-completion-model-inputs-v2/mapping.json \
  --queries fixtures/phase2-completion-v7/final.json \
  --corpus fixtures/phase2-completion-v7/corpus.json \
  --retrieval-run runs/phase2-completion-final-v1 \
  --model-run runs/phase2-my-model-run \
  --output runs/phase2-my-review
```

Copy `reviews-template.json` to a separate new file and fill every judgment, reviewer and rationale. Do not modify the packets, fixture or response. Then:

```bash
.venv/bin/python -m context_lab.model_quality summarize \
  --prepared runs/phase2-my-review/result.json \
  --reviews runs/phase2-my-review/reviews-completed.json \
  --output runs/phase2-my-quality-summary
```

The output preserves missing/failed trials, counts independent question IDs separately from repeated trials, and compares selected B with selected A and both previous-context arms on the same question/dataset/repeat. A missing counterpart remains explicitly missing. The result is a finite synthetic comparison, not population noninferiority evidence.

Usage, estimates, median/p95 attempt latency and overlapping request intervals are separate from semantic quality. Unknown usage is recorded as unknown, not zero. Distinct concurrent actor identities are counted separately from overlapping attempts: sixteen workers do not establish sixteen agents. The saved overall wall clock covers the mixed-arm run; it is not an individual arm's isolated batch duration. Invoice/credit allocation and actual human correction time remain unmeasured unless separately observed.

## Sixteen-actor batches

The primary 320 planned quality comparisons contain only eight distinct actor identities. They cannot by themselves establish sixteen concurrent actors. `scripts/prepare_model_concurrency.py` therefore selects the first sixteen shared-scope final questions in frozen file order and substitutes sixteen synthetic actor names. It replays all four context arms and requires byte-identical payloads before saving any batch. No private-scope request is substituted.

`runs/phase2-completion-concurrency-inputs-v1/receipt.json` records 64 successful identity-invariance checks at 10,000 documents. Four files each contain sixteen different actors. These are derived regression probes, not additional independent quality questions. Run the arms separately using the same model, output limit and shared USD 10 ledger as the primary comparison. Inspect the observed peak of distinct actors and each batch wall clock; configured worker count is not execution evidence. The four prepared arms were each dispatched twice on 2026-11-02 (128 calls in eight batches). Saved interval analysis observed sixteen distinct overlapping actors in every batch; these older derived inputs are separate from the confirmation final-quality experiment.
