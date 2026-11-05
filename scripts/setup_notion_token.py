"""Prompt privately for a Notion connection token and create a protected file."""
import argparse
import getpass
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    path = args.file.expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    if path.is_relative_to(root):
        parser.error("store this credential outside the source repository")
    os.umask(0o077)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        parser.error("the containing directory must have mode 0700")
    token = getpass.getpass("Notion connection token (hidden): ").strip()
    if not token or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
        parser.error("invalid credential format")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(token)
        output.flush()
        os.fsync(output.fileno())
    print("Credential saved privately. The value was not printed.")


if __name__ == "__main__":
    main()
