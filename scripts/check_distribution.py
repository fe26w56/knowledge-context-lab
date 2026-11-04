"""Check that source distributions contain only intended public review material."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import tarfile
import zipfile


FORBIDDEN_PARTS = {
    ".venv", ".phase1-original", "tokenizer-cache", "private", "work",
    ".git", ".codex", ".agents", ".aws", "__pycache__",
}
FORBIDDEN_SUFFIXES = {".sqlite", ".sqlite3", ".sqlite-shm", ".sqlite-wal", ".db", ".zip", ".tar", ".gz"}
SECRET = re.compile(rb"sk-[A-Za-z0-9]{24,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
# Match filesystem paths, not URL paths such as
# ``https://example.invalid/private/contact`` in a fictional fixture.
PRIVATE_OR_RUNTIME_PATH = re.compile(rb"(?:^|[\s\"'])/(?:Users|private|tmp)/")


TEXT_SUFFIXES = {".py", ".json", ".jsonl", ".md", ".toml", ".txt", ".yml", ".yaml", ".cfg", ".ini"}


def normalize_name(name: str) -> str:
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"absolute path in distribution: {name}")
    parts = name.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe path in distribution: {name}")
    return "/".join(parts)


def check_names(names: list[str], *, source_distribution: bool) -> list[str]:
    normalized = [normalize_name(name) for name in names]
    if source_distribution:
        roots = {name.split("/", 1)[0] for name in normalized}
        if len(roots) != 1:
            raise ValueError("source distribution must have exactly one top-level directory")
        root = next(iter(roots))
        normalized = [name[len(root) + 1:] if name != root else "" for name in normalized]
    for name in normalized:
        parts = set(Path(name).parts)
        if parts & FORBIDDEN_PARTS:
            raise ValueError(f"forbidden private/build path in distribution: {name}")
        if Path(name).suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"forbidden archive/database file in distribution: {name}")
        if any(part.startswith(".env") for part in Path(name).parts):
            raise ValueError(f"forbidden environment file in distribution: {name}")
        if SECRET.search(name.encode()):
            raise ValueError(f"credential-like path in distribution: {name}")
    required = ("pyproject.toml", "README.md", "src/context_lab", "tests", "fixtures") if source_distribution else ("context_lab",)
    for prefix in required:
        if not any(n == prefix or n.startswith(prefix + "/") for n in normalized):
            raise ValueError(f"required distribution content missing: {prefix}")
    return normalized


def check_content(name: str, data: bytes) -> None:
    if Path(name).suffix.lower() not in TEXT_SUFFIXES and Path(name).name not in {"LICENSE", "METADATA", "PKG-INFO"}:
        return
    if SECRET.search(data):
        raise ValueError(f"credential-like content in distribution: {name}")
    if PRIVATE_OR_RUNTIME_PATH.search(data):
        raise ValueError(f"private or runtime path in distribution: {name}")


def check_archive(path: Path) -> dict:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            normalized = check_names(names, source_distribution=False)
            for info, name in zip(infos, normalized):
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError(f"symlink is not allowed in a distribution: {name}")
                check_content(name, archive.read(info))
            return {"kind": "wheel", "files": len(names)}
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if any(not (member.isfile() or member.isdir()) for member in members):
                raise ValueError("symlinks and special files are not allowed in a distribution")
            names = [member.name for member in members]
            normalized = check_names(names, source_distribution=True)
            for member, name in zip(members, normalized):
                check_content(name, archive.extractfile(member).read() if member.isfile() else b"")
            return {"kind": "sdist", "files": len(names)}
    raise ValueError(f"unsupported distribution: {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"sdist": check_archive(args.sdist), "wheel": check_archive(args.wheel)}
    print(result)


if __name__ == "__main__":
    main()
