"""Export fictional measured traces without opaque provider reasoning or IDs.

Raw local traces are preserved. Requests, outputs, payloads, usage and accounting
remain available for reproducing mechanical and semantic analyses.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('output must be new')
    raw_path = args.run / 'results.json'
    rows = json.loads(raw_path.read_text())
    removed = ['provider_output', 'response_id', 'raw_output_text']
    removed_counts = {key: 0 for key in removed}
    for row in rows:
        metadata = row['response']['metadata']
        for key in removed:
            if key in metadata:
                del metadata[key]
                removed_counts[key] += 1
    args.output.mkdir(parents=True)
    (args.output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    for name in ['manifest.json', 'summary.json']:
        (args.output / name).write_bytes((args.run / name).read_bytes())
    receipt = {'schema': 'reuse-trace-export-v1', 'fictional_sources_only': True,
               'new_model_calls': 0, 'source_trace_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
               'exported_trace_sha256': hashlib.sha256((args.output / 'results.json').read_bytes()).hexdigest(),
               'removed_metadata_fields': removed_counts, 'request_output_usage_unchanged': True,
               'exporter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output / 'export.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
