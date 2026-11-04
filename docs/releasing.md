# Preparing a local release

The release consists of three different artifacts:

| Artifact | Purpose | Includes measured runs? |
|---|---|---|
| `knowledge_context_lab-0.4.0rc1-py3-none-any.whl` | Install the library, CLI demo and both profiles | No |
| `knowledge_context_lab-0.4.0rc1.tar.gz` | Run tests, experiments and completion replays | Completion series |
| `knowledge-context-lab-0.4.0rc1-review.zip` | Inspect and reproduce saved measurements and source snapshots | Yes |

Build from a reviewed source tree after tests and measurements are complete. Do not reuse an old output filename for a new artifact; increment the version or choose a fresh directory. The build does not publish anything.

```bash
.venv/bin/python -m pip install build
.venv/bin/python -m build --sdist --wheel
.venv/bin/python scripts/check_distribution.py \
  --sdist dist/knowledge_context_lab-0.4.0rc1.tar.gz \
  --wheel dist/knowledge_context_lab-0.4.0rc1-py3-none-any.whl
.venv/bin/python scripts/check_wheel.py \
  --wheel dist/knowledge_context_lab-0.4.0rc1-py3-none-any.whl \
  --output wheel-check.json
.venv/bin/python scripts/build_release_bundle.py \
  --output dist/knowledge-context-lab-0.4.0rc1-review.zip
```

`check_wheel.py` creates an isolated temporary venv, installs only the supplied wheel with no index or dependencies, verifies the actual import path, runs the old explicit profile and the packaged default and completion profiles/demo with file and SQLite, and checks all console entry points. It uses character counting to avoid a dependency download and never represents that check as a token measurement.

`check_distribution.py` inspects archive paths and credential-like content, rejects symlinks and local databases, and checks required package content. `build_release_bundle.py` exports an explicit allowlist, rejects personal paths and workspace URLs, excludes rejected fixture drafts and the invalid release development run, and writes a SHA256 manifest. Readback verifies every included file.

The source package includes curated completion run directories, and excludes runtime databases, credential files and rejected draft generators. Completion v6 is included only to verify the documented v7 structural repair; rejected v1–v6 fixture tests remain in the workspace but are not distributed. The evidence bundle carries the adopted fixture bytes, freeze metadata, selected configuration, run outputs and source snapshots needed for reproduction. Its historical reports may mention rejected local drafts that are intentionally not distributed.

A release receipt must state the local Python/platform actually tested, artifact hashes, test count, install checks, and any failed or unmeasured gates. GitHub Actions is configuration until an actual run is recorded. This task prepared local artifacts only; upload, production changes and input-rights confirmation are separate release-owner actions.
