"""Create a minimal, auditable public source tree without touching the repo.

The output is a staging tree, not a Git operation.  It deliberately copies
source, tests, synthetic fixtures, and curated aggregate evidence, while
excluding private/build directories and historical raw run payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import re
from pathlib import Path

if __package__:
    from .build_release_bundle import _assert_public_path
    from .check_distribution import check_content, FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES
else:
    from build_release_bundle import _assert_public_path
    from check_distribution import check_content, FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES


TOP_FILES = ("README.md", "README.ja.md", "CHANGELOG.md", "CONTRIBUTING.md",
             "SECURITY.md", "LICENSE", "pyproject.toml", "MANIFEST.in",
             "BUNDLE_MANIFEST.json", ".gitignore")
RUN_FILES = (
    "runs/phase2-reuse-selection-v1/selection.json",
    "runs/phase2-reuse-analysis-v1/accounting.json",
    "runs/phase2-reuse-analysis-v1/summary.json",
    "runs/phase2-reuse-model-public-v1/export.json",
    "runs/phase2-reuse-model-public-v1/manifest.json",
    "runs/phase2-reuse-model-public-v1/results.json",
    "runs/phase2-reuse-model-public-v1/summary.json",
    "runs/phase2-reuse-model-analysis-public-v1/rows.json",
    "runs/phase2-reuse-model-analysis-public-v1/summary.json",
    "runs/phase2-reuse-model-root-review-v1/review.json",
    "runs/phase2-reuse-semantic-agent-v1.json",
    "runs/phase2-reuse-lifecycle-v3/receipt.json",
    "runs/phase2-reuse-existing-gap-v1/receipt.json",
    "runs/phase2-span-compaction-v3/summary.json",
    "runs/phase2-span-compaction-v3/rows.json",
    "runs/phase2-reuse-validation-v1/receipt.json",
) + tuple(f"runs/{run}/{name}" for run in ("phase2-reuse-dev-v2", "phase2-reuse-final-v1")
          for name in ("rows.jsonl", "datasets.json", "concurrency.json", "summary.json", "manifest.json"))
EXCLUDED_SCRIPT_PREFIXES = ("create_release_fixture", "freeze_release_fixture_v6")


def copy_file(root: Path, out: Path, rel: str) -> None:
    src = root / rel
    _assert_public_path(src, root)
    if not src.is_file():
        raise FileNotFoundError(rel)
    check_content(rel, src.read_bytes())
    dest = out / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def copy_tree(root: Path, out: Path, dirname: str, suffixes: set[str]) -> int:
    count = 0
    for src in sorted((root / dirname).rglob("*")):
        if not src.is_file() or src.name == "__pycache__" or any(
                part == "__pycache__" for part in src.parts):
            continue
        if src.suffix not in suffixes:
            continue
        rel = src.relative_to(root)
        copy_file(root, out, rel.as_posix())
        count += 1
    return count


def mark_unbundled_links(out: Path) -> dict[str, list[str]]:
    """Mark historical evidence omissions without editing measured artifacts."""
    changed = {}
    for path in sorted((out / 'docs').glob('*.md')):
        missing = []
        def replace(match):
            label, target = match.groups()
            if re.match(r'^[a-z]+:', target) or target.startswith('#'):
                return match.group(0)
            relative = target.split('#', 1)[0]
            if not relative or (path.parent / relative).exists():
                return match.group(0)
            missing.append(target)
            return f'{label} (`{target}`; historical artifact not included in this preview)'
        body = re.sub(r'\[([^\]\n]+)\]\(([^)\n]+)\)', replace, path.read_text())
        if missing:
            path.write_text(body)
            changed[path.relative_to(out).as_posix()] = missing
    return changed


def audit_tree(out: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(out.rglob('*')):
        if not path.is_file():
            continue
        _assert_public_path(path, out)
        relative = path.relative_to(out).as_posix()
        parts = set(Path(relative).parts)
        if parts & FORBIDDEN_PARTS or path.suffix in FORBIDDEN_SUFFIXES or any(p.startswith('.env') for p in path.parts):
            raise ValueError(f'forbidden export file: {relative}')
        data = path.read_bytes()
        check_content(relative, data)
        hashes[relative] = hashlib.sha256(data).hexdigest()
    return hashes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    out = args.output.resolve()
    if args.receipt.exists():
        raise SystemExit('receipt must be new')
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing output: {out}")
    out.mkdir(parents=True)

    for rel in TOP_FILES:
        copy_file(root, out, rel)
    counts = {
        "src": copy_tree(root, out, "src/context_lab", {".py", ".json"}),
        "tests": copy_tree(root, out, "tests", {".py"}),
        "fixtures": copy_tree(root, out, "fixtures", {".json", ".jsonl", ".md", ".py"}),
        "configs": copy_tree(root, out, "configs", {".json"}),
        "docs": copy_tree(root, out, "docs", {".md"}),
        "scripts": 0,
        "github": copy_tree(root, out, ".github", {".yml", ".yaml"})
        if (root / ".github").exists() else 0,
    }
    for src in sorted((root / "scripts").glob("*.py")):
        if src.name.startswith(EXCLUDED_SCRIPT_PREFIXES):
            continue
        copy_file(root, out, str(src.relative_to(root)))
        counts["scripts"] += 1
    for rel in RUN_FILES:
        copy_file(root, out, rel)
    for rel in ("runs/synthetic-v1/SUMMARY.md", "runs/synthetic-v1/metadata.json",
                "runs/synthetic-v1/payloads.jsonl", "runs/synthetic-v1/results.csv",
                "runs/synthetic-v1/results.json", "runs/synthetic-v1/summary.json"):
        copy_file(root, out, rel)

    changed_docs = mark_unbundled_links(out)
    hashes = audit_tree(out)
    files = sorted(hashes)
    digest = hashlib.sha256("\n".join(files).encode()).hexdigest()
    receipt = {
        "schema": "phase2-publication-preparation-v3",
        "output": str(args.output),
        "source_root": "workspace root (absolute path intentionally omitted)",
        "counts": counts,
        "file_count": len(files),
        "file_list_sha256": digest,
        "file_sha256": hashes,
        "document_links_marked_as_unbundled": changed_docs,
        "run_allowlist_count": len(RUN_FILES),
        "protected_baseline": "runs/synthetic-v1 (six files)",
        "excluded": [".git", ".venv", "private", "work", "SQLite files",
                     "raw historical runs", "rejected fixture generators"],
        "fixture_policy": "fictional diagnostics are included; phase2-longmemeval-selection-v1 is metadata-only external-evaluation selection, not source text",
        "publication_performed": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    (out/'PUBLICATION_MANIFEST.json').write_text(json.dumps({k:v for k,v in receipt.items() if k not in {'output'}}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'file_count':len(files), 'bytes':sum((out/f).stat().st_size for f in files), 'marked_historical_docs':len(changed_docs)}))


if __name__ == "__main__":
    main()
