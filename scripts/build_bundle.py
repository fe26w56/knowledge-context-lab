"""Package only public source, synthetic fixtures and synthetic results."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = ("src", "tests", "docs", "fixtures/synthetic", "scripts", "runs/synthetic-v1")
SINGLE = ("README.md", "pyproject.toml", ".gitignore", "runs/obsolete-candidates.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads((ROOT / "fixtures/synthetic/corpus.json").read_text())
    metadata = json.loads((ROOT / "runs/synthetic-v1/metadata.json").read_text())
    if fixture.get("privacy") != "public_synthetic" or metadata.get("privacy") != "public_synthetic":
        raise SystemExit("The export allowlist may only contain synthetic evaluation data")
    files = [ROOT / name for name in SINGLE if (ROOT / name).is_file()]
    for name in ALLOWED:
        files.extend(p for p in (ROOT / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".sqlite", ".sqlite3"})
    files = sorted(set(files))
    for path in files:
        if path.is_symlink():
            raise SystemExit("Symlink export refused")
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "knowledge-context-lab/" + str(path.relative_to(ROOT)))
        archive.writestr("knowledge-context-lab/BUNDLE_MANIFEST.json", json.dumps({"public_synthetic_only": True, "license_selected": False, "sha256": hashes}, ensure_ascii=False, indent=2))
    print(json.dumps({"files": len(files), "output": str(args.output.resolve()), "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
