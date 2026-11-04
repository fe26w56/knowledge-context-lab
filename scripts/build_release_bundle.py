"""Build a curated, local-only release review bundle."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("README.md", "pyproject.toml", "MANIFEST.in", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", ".gitignore", "BUNDLE_MANIFEST.json")
TREES = ("src/context_lab", "tests", "docs", "scripts", "configs", ".github", "fixtures/synthetic", "fixtures/phase2", "fixtures/phase2-release-v6", "fixtures/phase2-completion-v6", "fixtures/phase2-completion-v7", "fixtures/phase2-confirmation-v5", "fixtures/phase2-workflow-v5", "fixtures/phase2-workflow-v6", "runs/synthetic-v1", "fixtures/phase2-migration-v2", "fixtures/phase2-longmemeval-selection-v1")
RUNS = (
    'phase2-baseline',
    'phase2-dev-v1',
    'phase2-dev-v2',
    'phase2-dev-v3',
    'phase2-regression-v1',
    'phase2-final-v1',
    'phase2-load-v1',
    'phase2-load-diagnostic-v1',
    'phase2-faults-v3',
    'phase2-validation',
    'phase2-release-dev-v2',
    'phase2-release-dev-v3',
    'phase2-release-final-v1',
    'phase2-release-regression-original-v1',
    'phase2-release-regression-phase2-v1',
    'phase2-release-maintenance-v1',
    'phase2-release-audit-v4',
    'phase2-release-analysis-v1',
    'phase2-release-validation-v1',
    'phase2-confirmation-structural-audit-v5',
    'phase2-confirmation-fixture-audit-v5',
    'phase2-confirmation-dev-v2',
    'phase2-confirmation-final-v1',
    'phase2-confirmation-selection-v1',
    'phase2-confirmation-model-dev-inputs-v1',
    'phase2-confirmation-model-dev-v1',
    'phase2-confirmation-model-dev-review-v1',
    'phase2-confirmation-model-dev-semantic-v1',
    'phase2-confirmation-model-dev-quality-v1',
    'phase2-confirmation-model-final-inputs-v1',
    'phase2-confirmation-model-final-v1',
    'phase2-confirmation-model-final-review-v1',
    'phase2-confirmation-model-final-semantic-v1',
    'phase2-confirmation-model-final-quality-v1',
    'phase2-adaptive-dev-v1',
    'phase2-adaptive-dev-audit-v1',
    'phase2-model-concurrency-analysis-20261102-v1',
    'phase2-confirmation-final-audit-v1',
    'phase2-confirmation-analysis-v1',
    'phase2-confirmation-validation-v2',
    'phase2-live-accounting-20261102-v2',
    'phase2-live-source-snapshots-20261102-v1',
    'phase2-completion-concurrency-inputs-v1',
    'phase2-completion-model-smoke-20261102-v1',
    'phase2-completion-model-primary-20261102-v1',
    'phase2-model-quality-summary-20261102-v1',
    'phase2-model-concurrency-20261102-control-A-r1',
    'phase2-model-concurrency-20261102-control-A-r2',
    'phase2-model-concurrency-20261102-control-B-r1',
    'phase2-model-concurrency-20261102-control-B-r2',
    'phase2-model-concurrency-20261102-selected-A-r1',
    'phase2-model-concurrency-20261102-selected-A-r2',
    'phase2-model-concurrency-20261102-selected-B-r1',
    'phase2-model-concurrency-20261102-selected-B-r2',
    'phase2-workflow-audit-v5',
    'phase2-workflow-audit-v6',
    'phase2-workflow-dev-v1',
    'phase2-workflow-dev-v2',
    'phase2-workflow-dev-v3',
    'phase2-workflow-dev-analysis-v1',
    'phase2-workflow-dev-analysis-v2',
    'phase2-workflow-dev2-analysis-v1',
    'phase2-workflow-dev3-analysis-v1',
    'phase2-workflow-dev-pricing-v2',
    'phase2-workflow-dev-integrity-v1',
    'phase2-workflow-dev-integrity-v2',
    'phase2-workflow-dev-integrity-v3',
    'phase2-workflow-dev-semantic-v1',
    'phase2-workflow-handoff-safety-v1',
    'phase2-workflow-pricing-v3',
    'phase2-workflow-reuse-v2',
    'phase2-workflow-smoke-v1',
    'phase2-workflow-smoke-semantic-v1',
    'phase2-workflow-smoke-integrity-v1',
    'phase2-workflow-record-smoke-v1',
    'phase2-workflow-record-smoke-integrity-v1',
    'phase2-workflow-cache-smoke-v1',
    'phase2-workflow-cache-smoke-integrity-v1',
    'phase2-workflow-uniform-smoke-v1',
    'phase2-workflow-uniform-smoke-integrity-v1',
    'phase2-workflow-accounting-pre-final-v1',
    'phase2-workflow-selection-v1',
    'phase2-workflow-final-r1-v1',
    'phase2-workflow-final-r2-v1',
    'phase2-workflow-final-analysis-v1',
    'phase2-workflow-final-analysis-v2',
    'phase2-workflow-interruption-audit-v1',
    'phase2-workflow-final-review-r1-v1',
    'phase2-workflow-final-review-r2-v1',
    'phase2-workflow-final-semantic-v1',
    'phase2-workflow-final-integrity-r1-v1',
    'phase2-workflow-final-integrity-r2-v1',
    'phase2-workflow-accounting-final-v1',
    'phase2-workflow-validation-v3',
    'phase2-workflow-validation-v4',
    'phase2-workflow-packaging-v1',
)
COMPLETION_RUNS = ("phase2-completion-dev-v2", "phase2-completion-dev-v3", "phase2-completion-dev-v4", "phase2-completion-dev-v5", "phase2-completion-dev-v6", "phase2-completion-dev-large-v1", "phase2-completion-selection-v1", "phase2-completion-final-v1", "phase2-completion-analysis-v1", "phase2-completion-audit-dev-v2", "phase2-completion-audit-large-v2", "phase2-completion-audit-final-v2", "phase2-completion-snapshots-v3", "phase2-completion-compat-v3", "phase2-completion-validation-v1", "phase2-confirmation-validation-v3")
SINGLE_RUN_FILES = (
    "runs/phase2-development-plan.json", "runs/phase2-q22-diagnostic-v1.json", "runs/phase2-compat-network-restored-v1/public-receipt.json",
    # Phase 4 migration receipts and reviewed summaries only. Raw/model traces
    # remain outside the public candidate bundle.
    "runs/phase2-migration-guide-v1/receipt.json", "runs/phase2-migration-guide-v2/receipt.json",
    "runs/phase2-migration-dev-v2/summary.json", "runs/phase2-migration-dev-v2/arm-summary.json",
    "runs/phase2-longmemeval-selection-v1/selection.json",
    "runs/phase2-longmemeval-model-dev-overlap-quality-v3/review.json",
    "runs/phase2-longmemeval-model-final-v1/rows.json",
    "runs/phase2-longmemeval-model-final-v1/summary.json",
    "runs/phase2-longmemeval-model-final-quality-v2/review.json",
    "runs/phase2-longmemeval-coverage-replay-v2/summary.json",
    "runs/phase2-longmemeval-corpus-turn-v1/summary.json",
    "runs/phase2-longmemeval-corpus-turn-v1/metadata.json",
    "runs/phase2-longmemeval-date-audit-v1/summary.json",
    "runs/phase2-longmemeval-preparation-audit-v1/summary.json",
    "runs/phase2-migration-final-selection-v1/selection.json",
    "runs/phase2-migration-model-final-v1/config.json",
    "runs/phase2-migration-model-final-v1/summary.json",
    "runs/phase2-migration-model-final-v1/results.json",
    "runs/phase2-migration-model-final-quality-v1/review.json",
    "runs/phase2-migration-model-final-analysis-v1/summary.json",
    "runs/phase2-migration-html-audit-v1/summary.json",
    "runs/phase2-migration-html-audit-v2/summary.json",
    "runs/phase2-migration-validation-v2/python311.json",
    "runs/phase2-migration-validation-v2/python313.json",
    "runs/phase2-migration-validation-v3/python311.json",
    "runs/phase2-migration-validation-v3/python313.json",
    "runs/phase2-migration-validation-v3/distribution-check.json",
    "runs/phase2-migration-accounting-v3/summary.json",
    "runs/phase2-migration-readiness-v1/summary.json",
    "runs/phase2-longmemeval-verifier-review-v1/review.json",
    "runs/phase2-longmemeval-verified-regression-v1/summary.json",
    "runs/phase2-longmemeval-verified-regression-v2/summary.json",
    "runs/phase2-longmemeval-verified-regression-v3/summary.json",
    "runs/phase2-migration-private-pilot-v1/summary.json",
    "runs/phase2-migration-private-pilot-v1/paired-audit.json",
    "runs/phase2-migration-validation-v8/python311.json",
    "runs/phase2-migration-validation-v8/python313.json",
    "runs/phase2-migration-validation-v8/public-preflight.json",
    "runs/phase2-migration-validation-v8/model-audit-review.json",
    "runs/phase2-migration-html-audit-v3/summary.json",
    "runs/phase2-migration-html-audit-v5/summary.json",
    "runs/phase2-migration-private-pilot-integrity-v1/summary.json",
    "runs/phase2-migration-observation-pilot-v2/summary.json",
    "runs/phase2-migration-observation-validation-v3/python311.json",
    "runs/phase2-migration-observation-validation-v3/python313.json",
    "runs/phase2-migration-observation-validation-v3/cross-actor-diagnostic.json",
    "runs/phase2-migration-observation-validation-v1/public-preflight.json",
)
EXTENSIONS = {".py", ".json", ".jsonl", ".csv", ".md", ".html", ".toml", ".txt", ".yml", ".yaml"}
EXCLUDED_SCRIPTS = {"create_release_fixture.py", "create_release_fixture_v2.py", "create_release_fixture_v3.py", "create_release_fixture_v4.py", "create_release_fixture_v5.py", "create_release_fixture_v6.py", "freeze_release_fixture_v6.py", "generate_workflow_v3_episodes.py"}
EXCLUDED_TESTS = {"test_completion_fixture.py", "test_completion_fixture_v2.py", "test_completion_fixture_v3.py", "test_completion_fixture_v4.py", "test_completion_fixture_v5.py", "test_completion_fixture_v6.py"}
EXCLUDED_RELATIVE = {"runs/phase2-completion-compat-v3/receipt.json", "runs/phase2-workflow-final-semantic-v1/reviewer-a-r1.json", "runs/phase2-workflow-final-semantic-v1/reviewer-b-r1.json"}
SECRET = re.compile(rb"sk-[A-Za-z0-9]{24,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
PRIVATE_OR_RUNTIME_PATH = re.compile(rb"(?:^|[\s\"'])/(?:Users|private|tmp)/")


def _assert_public_path(path: Path, root: Path) -> None:
    rel = path.relative_to(root)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f"symlink or escaping export refused: {rel}")
    for parent in (root.joinpath(*rel.parts[:i]) for i in range(1, len(rel.parts))):
        if parent.is_symlink():
            raise ValueError(f"symlink export refused: {rel}")


def _validate_bytes(path: Path, data: bytes) -> None:
    notion_url = b"app.notion.com/" + b"p/"
    if SECRET.search(data) or PRIVATE_OR_RUNTIME_PATH.search(data) or notion_url in data:
        raise ValueError(f"private path, workspace URL, or credential in {path}")


def collect(root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    paths = []
    for name in ROOT_FILES:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        paths.append(path)
    for name in TREES:
        folder = root / name
        if folder.exists():
            paths.extend(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in EXTENSIONS and "__pycache__" not in path.parts)
    for name in RUNS + COMPLETION_RUNS:
        folder = root / "runs" / name
        if folder.exists():
            paths.extend(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in EXTENSIONS and "__pycache__" not in path.parts)
    for name in SINGLE_RUN_FILES:
        path = root / name
        if path.is_file():
            paths.append(path)
    result = []
    for path in sorted(set(paths)):
        _assert_public_path(path, root)
        if str(path.relative_to(root)) in EXCLUDED_RELATIVE:
            continue
        if path.name.startswith(".env") or path.name == "author_fixture.py" or (path.parent.name == "scripts" and path.name in EXCLUDED_SCRIPTS) or (path.parent.name == "tests" and path.name in EXCLUDED_TESTS):
            continue
        _validate_bytes(path, path.read_bytes())
        result.append(path)
    for name in ("fixtures/synthetic/corpus.json", "fixtures/phase2/corpus.json", "fixtures/phase2-release-v6/corpus.json", "fixtures/phase2-confirmation-v5/corpus.json"):
        if (root / name).is_file() and json.loads((root / name).read_text()).get("privacy") != "public_synthetic":
            raise ValueError(f"corpus is not explicitly public synthetic: {name}")
    for name in ("fixtures/phase2-completion-v6/corpus.json", "fixtures/phase2-completion-v7/corpus.json"):
        corpus = root / name
        if corpus.is_file() and json.loads(corpus.read_text()).get("privacy") != "public_synthetic":
            raise ValueError(f"corpus is not explicitly public synthetic: {name}")
    return result


def build(output: Path, root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    files = collect(root)
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    manifest = {"artifact_status": "local release candidate", "license": "MIT", "publication_performed": False, "data_scope": "fictional fixtures and model traces, reviewed external evaluation metadata and anonymous private-pilot aggregates; no private source text, private model traces, external corpus or external API transcripts", "sha256": hashes}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "knowledge-context-lab/" + str(path.relative_to(root)))
        archive.writestr("knowledge-context-lab/RELEASE_BUNDLE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(output) as archive:
        for name, expected in hashes.items():
            if hashlib.sha256(archive.read("knowledge-context-lab/" + name)).hexdigest() != expected:
                raise AssertionError(f"bundle readback hash mismatch: {name}")
    return {"files": len(files), "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "manifest": manifest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False))
