# Contributing

Contributions are welcome when they keep the project reproducible and evidence-led.

Please use only synthetic or clearly redistributable fixtures. Never add personal documents, credentials, sensitive API responses, customer data, or a local database to a commit. Keep `fixtures/synthetic/` and prior `runs/` immutable; create a new `runs/phase2-*` directory for a new measurement.

For retrieval changes, freeze a development and final fixture before tuning. Do not pass question IDs, expected quotes, or grading metadata into the retrieval request. Compare one change at a time, record the configuration and SHA256 hashes, and report failures alongside improvements. A smaller payload is not an improvement when required evidence is missing.

Synthetic model outputs may be included only after redaction and source review; never include headers, keys or private account details.

Run the local checks before opening a change:

```bash
export TIKTOKEN_CACHE_DIR="$PWD/tokenizer-cache"
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip install build
.venv/bin/python -m build --sdist --wheel
.venv/bin/python scripts/check_distribution.py \
  --sdist dist/*.tar.gz \
  --wheel dist/*.whl
```

Also run `.venv/bin/python scripts/preflight.py` to verify the tokenizer and the protected original fixture/results. The protected original fixture and results are included. Large historical model traces are not; see `docs/publication-scope.md` for the exported evidence and reproducible entry points. The GitHub Actions matrix is configured for Python 3.11–3.13; local release receipts state which versions were actually executed.

The evaluation fixture is a diagnostic created by this project, not an independent benchmark. Keep model quality, provider billing, D1 behavior, and human correction time marked as unmeasured unless those measurements were actually run and saved.

