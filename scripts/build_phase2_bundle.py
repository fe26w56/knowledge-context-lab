"""Build a local review bundle from an explicit public-synthetic allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TREE=("src/context_lab","tests","docs","scripts","fixtures/synthetic","fixtures/phase2","configs","runs/synthetic-v1")
RUNS=("phase2-baseline","phase2-dev-v1","phase2-dev-v2","phase2-dev-v3","phase2-regression-v1",
      "phase2-final-v1","phase2-load-v1","phase2-load-diagnostic-v1","phase2-faults-v3","phase2-validation")
SINGLE=("README.md","pyproject.toml",".gitignore","BUNDLE_MANIFEST.json","runs/phase2-development-plan.json","runs/phase2-q22-diagnostic-v1.json")
EXTENSIONS={".py",".json",".jsonl",".csv",".md",".toml",".txt"}
SECRET=re.compile(rb"sk-[A-Za-z0-9]{24,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def collect(root=ROOT):
    paths=[root/name for name in SINGLE if (root/name).is_file()]
    for name in TREE+tuple("runs/"+r for r in RUNS):
        folder=root/name
        if folder.exists():
            paths.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix in EXTENSIONS and "__pycache__" not in p.parts)
    files=sorted(set(paths))
    for p in files:
        relative=p.relative_to(root)
        if not p.resolve().is_relative_to(root.resolve()) or any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)):
            raise ValueError(f"Symlink export refused: {relative}")
        data=p.read_bytes()
        if SECRET.search(data):
            raise ValueError(f"Potential credential in {relative}; export refused")
        if b"/" + b"Users/" in data or b"app.notion.com/" + b"p/" in data:
            raise ValueError(f"Personal path or workspace URL in {relative}; export refused")
    for name in ("fixtures/synthetic/corpus.json","fixtures/phase2/corpus.json"):
        if json.loads((root/name).read_text()).get("privacy")!="public_synthetic":
            raise ValueError("Only explicitly public synthetic corpora may be packaged")
    return files


def build(output, root=ROOT):
    files=collect(root)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    manifest=dict(public_synthetic_only=True,license_selected=False,publication_authorized=False,
                  artifact_status="local review candidate",sha256=hashes)
    with zipfile.ZipFile(output,"x",zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p,"knowledge-context-lab/"+str(p.relative_to(root)))
        archive.writestr("knowledge-context-lab/PHASE2_BUNDLE_MANIFEST.json",json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    with zipfile.ZipFile(output) as archive:
        for name,sha in hashes.items():
            if hashlib.sha256(archive.read("knowledge-context-lab/"+name)).hexdigest()!=sha:
                raise AssertionError("Bundle readback hash mismatch")
    return dict(files=len(files),bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest())


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(build(args.output)))
