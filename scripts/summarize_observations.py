"""Summarize one explicitly selected observation kind without exposing hashes."""
from __future__ import annotations
import argparse
import json
from context_lab.observations import summarize

parser = argparse.ArgumentParser()
parser.add_argument("--directory", required=True)
parser.add_argument("--kind", choices=("diagnostic", "operational"), required=True)
args = parser.parse_args()
print(json.dumps(summarize(args.directory, kind=args.kind), ensure_ascii=False, sort_keys=True))
