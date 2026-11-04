"""One-factor development ablations. Final evaluation requires a frozen selection."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from . import release_eval
from .retrieval_completion import CompletionConfig, CompletionRetrieval

SOURCES = release_eval.SOURCE_NAMES + ("retrieval_completion.py", "completion_eval.py")
VARIANTS = {
    "control": asdict(CompletionConfig()),
    "eligible": asdict(CompletionConfig(eligible_section_ranking=True)),
    "compact": asdict(CompletionConfig(compact_spans=True)),
    "eligible_compact": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True)),
    "diverse_half": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.5)),
    "diverse_strong": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.8)),
    "diverse_half_three": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.5, candidate_limit=3)),
    "diverse_half_twelve": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.5, candidate_limit=12)),
    "diverse_strong_twelve": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.8, candidate_limit=12)),
    "state_six": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.5, strict_current_state=True)),
    "state_twelve": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.8, candidate_limit=12, strict_current_state=True)),
    "balanced_six": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.5, strict_current_state=True, document_round_robin=True)),
    "balanced_twelve": asdict(CompletionConfig(eligible_section_ranking=True, compact_spans=True, lexical_diversity=.8, candidate_limit=12, strict_current_state=True, document_round_robin=True)),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dev", "final"), required=True)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/phase2-completion-v7"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--datasets", required=True, help="Comma-separated size:seed")
    parser.add_argument("--variants", default="control,eligible,compact,eligible_compact")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    variants = {name: VARIANTS[name] for name in args.variants.split(",")}
    if args.mode == "final":
        if not args.selection:
            parser.error("a frozen development selection is required")
        selection = json.loads(args.selection.read_text())
        if selection["source_sha256"] != release_eval.source_hashes(SOURCES):
            parser.error("source changed after selection")
        variants = {"control": VARIANTS["control"], "selected": selection["config"]}
    summaries, metadata = release_eval.run(
        args.fixture/"corpus.json", args.fixture/(args.mode+".json"), args.output,
        variants, [tuple(map(int, item.split(":"))) for item in args.datasets.split(",")], args.repeats,
        engine_class=CompletionRetrieval, config_class=CompletionConfig, source_names=SOURCES)
    metadata.update(fixture_chronology="questions frozen before implementation; mechanical corpus repair after first implementation, before measurements",
                    model_quality_measured=False, comparison="source-aware literal coverage only")
    release_eval.write(args.output/"metadata.json", metadata)
    if args.mode == "dev":
        selected = release_eval.select(args.output, summaries, metadata)
        selected["engine"] = "completion"
        release_eval.write(args.output/"selection.json", selected)
        print(json.dumps(selected))
    else:
        release_eval.write(args.output/"selection-used.json", selection)
        print(json.dumps({"groups": len(summaries), "parity_pairs": metadata["backend_payload_and_candidate_parity_pairs"]}))


if __name__ == "__main__":
    main()
