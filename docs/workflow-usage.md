# Reproduce the controlled workflow experiment

The experimental workflow runner evaluates sixteen distinct actor requests in four dependency waves. It is a local research harness, not a deployed multi-agent service. Each actor gets its own request, eligible sources and the actual direct predecessor's answer. The final protocol selected three concurrent API workers, eight cases and two repetitions. The first repetition completed all 384 calls. The second stopped after 19 successful calls and one transport error with unknown usage; it is excluded from the complete paired comparison. Repetitions share cases and do not increase the number of independent cases.

## Offline verification

Use the source distribution or review ZIP for the fixtures, scripts and measured responses. The wheel contains the Python library and command entry points. Python 3.11 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[tokens]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/audit_workflow_run.py \
  --fixture fixtures/phase2-workflow-v6 \
  --run runs/phase2-workflow-final-r1-v1 \
  --output runs/phase2-my-workflow-replay-r1
.venv/bin/python scripts/analyze_workflow.py \
  --run runs/phase2-workflow-final-r1-v1 \
  --output runs/phase2-my-workflow-analysis
```

These commands do not call the model. The interrupted r2 directory is preserved as failure evidence, not represented as a completed replay. Replay checks fixture and source hashes, actual API input, model-response binding, source availability, scope, literal quotes and saved grades. It imports the source snapshot saved with the run. It does not turn literal quote validity into a semantic entailment judgment. A model's invalid quote can be a correctly recorded quality failure without corrupting the experiment.

All output directories must be new. Preserve fixtures, responses and earlier results. Repeating these already measured final cases is a regression exercise, not an unseen evaluation.

## Paid reproduction

Use an externally configured `OPENAI_API_KEY`. The runner never writes the key. It records synthetic requests, outputs and token usage; do not substitute private or real documents into this public evaluation kit.

```bash
.venv/bin/context-lab-workflow \
  --fixture fixtures/phase2-workflow-v6 --split final \
  --arms handoff6 handoff12 cache12 --workers 3 --seed 74101 \
  --selection runs/phase2-workflow-selection-v1/selection.json \
  --ledger work/my-authorized-experiment.sqlite \
  --output runs/phase2-my-live-r1 --live
```

This command spends API credit. Its spending envelope is USD10; it is not a statement that USD10 will be billed. Reserve the full verified model input limit and output limit before dispatch, then settle a conservative upper price estimate from observed usage. Keep the **same ledger for every invocation within one authorized envelope**, including repeats, development, retries and failed requests. Do not replace a ledger to reset a limit. Transport failures retain the reservation and do not retry automatically. A second repetition uses seed `74102`, a new output directory and the same ledger and selection.

The exported selection must match the installed implementation and fixture hashes. A mismatch after editing code is intentional: prepare a new development protocol and selection rather than bypassing the check. A saved final run can always be replayed offline against its own snapshot. Prices, model availability and API schema can change; the saved price snapshot supports historical estimates only. Verify current provider documentation before another paid experiment.

## Compared methods

| Arm | Change | What is counted |
| --- | --- | --- |
| `full6`, `full12` | Six or twelve complete candidates | Retrieval, all answer calls and wave time |
| `reuse12` | Coalesce identical retrieval requests | Local index/retrieval work; answer calls still occur |
| `record12` | Generate a reusable exact-excerpt record | Record construction/rebuild plus every answer |
| `fallback12` | One original-context retry on detected insufficiency | Both answer attempts; detection never consults gold |
| `handoff6`, `handoff12` | Clarify copying the direct predecessor's current status | Same candidate bodies and answer contract |
| `prefix12` | Serialize sources before actor/task/handoff | Observed provider cache usage, with no assumed hit |
| `cache12` | Explicit cache boundary after sources | Cache writes, reads, output and elapsed time |
| `uniform12` | Fixed response schema; field instructions in request tail | Same typed values, with strict lossless normalization |

The final selection contains `handoff6`, `handoff12` and `cache12`. Other arms remain available to reproduce rejected development hypotheses; their presence is not a recommendation. No arm changes the storage backend to a DB.

Reuse keys include the full visible snapshot, time, query and configuration. Revision, addition, deletion and permission changes invalidate the application cache. A private-tainted predecessor answer is withheld from a recipient without access; previously public material also becomes unavailable after privatization or deletion. These local checks trust the caller-provided identity. They are not a hosted authentication or tenant-isolation implementation.

## Evidence boundaries

The v5 fixture design preceded the workflow implementation. A necessary/sufficient-condition wording repair produced v6 after implementation and v5 smoke, before the valid development comparison. The final selection preceded final model calls. Both splits are project-authored controlled diagnostics with related task templates, not an independent benchmark. Repeated model calls can reveal variability; they cannot establish general quality equivalence on real work.

Provider-reported usage, rate-card estimates, the conservative budget ledger, invoice charges and credit balances are different quantities. The last two were not measured. See the phase findings for exact quality-review coverage and actual measured outcomes.
