"""Offline preflight: collect setup failures before starting a long experiment."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile


def check(ok, message, **extra):
    return dict(status="ok" if ok else "error", problems=[] if ok else [message], **extra)


def run(root: Path, skip_write_probe=False, cache_dir=None):
    root=root.resolve()
    checks={}
    checks["python"]=check(sys.version_info >= (3,11),"Python >=3.11 required",version=platform.python_version())
    checks["venv"]=check(Path(sys.prefix).resolve()==(root/".venv").resolve(),"Run with .venv/bin/python")
    try:
        version=importlib.metadata.version("tiktoken")
    except importlib.metadata.PackageNotFoundError:
        version=None
    checks["tiktoken"]=check(version=="0.14.0","Install with .venv/bin/python -m pip install -e '.[tokens]'",version=version)
    cache=Path(cache_dir or os.environ.get("TIKTOKEN_CACHE_DIR") or root/"tokenizer-cache")
    key=hashlib.sha1(b"https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken").hexdigest()
    cached=cache/key
    exists=cached.is_file()
    checks["o200k_base_cache"]=check(exists,"Missing o200k_base cache; run the tokenizer setup command once",path=str(cached))
    if exists and version=="0.14.0":
        try:
            import tiktoken_ext.openai_public as encoder
            from tiktoken.load import load_tiktoken_bpe
            expected=re.search(r'expected_hash=["\']([0-9a-f]{64})',inspect.getsource(encoder.o200k_base)).group(1)
            actual=hashlib.sha256(cached.read_bytes()).hexdigest()
            if expected != actual:
                raise ValueError("Tokenizer cache checksum mismatch")
            # Local path only: this never invokes the remote encoder loader.
            ranks=load_tiktoken_bpe(str(cached),expected_hash=expected)
            checks["o200k_base_load"]=check(len(ranks)>=199000,"Incomplete cached tokenizer",entries=len(ranks))
        except Exception as exc:
            checks["o200k_base_load"]=check(False,str(exc))
    else:
        checks["o200k_base_load"]=check(False,"Package/cache unavailable; load was not attempted")
    if skip_write_probe:
        checks["write_probe"]=dict(status="skipped",problems=[],skipped=True)
    else:
        try:
            with tempfile.NamedTemporaryFile(prefix=".preflight-",dir=root) as f:
                f.write(b"probe");f.flush()
            checks["write_probe"]=check(True,"")
        except OSError as exc:
            checks["write_probe"]=check(False,str(exc))
    for label, manifest, base, predicate in (
        ("phase2_freeze",root/"fixtures/phase2/FREEZE.json",root/"fixtures/phase2",lambda name: True),
        ("phase1_protected",root/"BUNDLE_MANIFEST.json",root,lambda name: name.startswith(("fixtures/synthetic/","runs/synthetic-v1/"))),
    ):
        try:
            data=json.loads(manifest.read_text())
            if label=="phase2_freeze" and data.get("frozen_before_improvement") is not True:
                raise ValueError("Fixture was not frozen")
            selected={name:sha for name,sha in data["sha256"].items() if predicate(name)}
            if not selected:
                raise ValueError("No protected hashes found")
            for name,sha in selected.items():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError("Unsafe manifest path")
                if hashlib.sha256((base/name).read_bytes()).hexdigest()!=sha:
                    raise ValueError(f"Hash mismatch: {name}")
            checks[label]=check(True,"",files=len(selected))
        except Exception as exc:
            checks[label]=check(False,str(exc))
    problems=[p for value in checks.values() for p in value["problems"]]
    return dict(ok=all(v["status"] in {"ok","skipped"} for v in checks.values()),checks=checks,problems=problems,
                remediation_commands=["python3.11 -m venv .venv",".venv/bin/python -m pip install -e '.[tokens]'",
                "TIKTOKEN_CACHE_DIR=\"$PWD/tokenizer-cache\" .venv/bin/python -c 'import tiktoken; tiktoken.get_encoding(\"o200k_base\")'"] if problems else [])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path.cwd())
    p.add_argument("--skip-write-probe",action="store_true")
    p.add_argument("--cache-dir",type=Path)
    args=p.parse_args()
    result=run(args.root,args.skip_write_probe,args.cache_dir)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__=="__main__":
    main()
