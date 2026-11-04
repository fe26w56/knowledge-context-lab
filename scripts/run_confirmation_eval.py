"""Re-evaluate existing frozen configurations on an audited confirmation set."""
from __future__ import annotations

import argparse
import ast
import json
import shutil
from pathlib import Path

from context_lab import release_eval
from context_lab.completion_eval import SOURCES
from context_lab.retrieval_completion import CompletionConfig, CompletionRetrieval
from context_lab.retrieval_adaptive import AdaptiveConfig, AdaptiveRetrieval


def load(path):
    return json.loads(Path(path).read_text())


def without_module_docstring(source):
    module = ast.parse(source)
    if module.body and isinstance(module.body[0], ast.Expr) and isinstance(module.body[0].value, ast.Constant) and isinstance(module.body[0].value.value, str):
        module.body.pop(0)
    return ast.dump(module, include_attributes=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--split', choices=('dev', 'final'), required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--reference-run', type=Path, required=True)
    parser.add_argument('--structural-audit', type=Path, required=True)
    parser.add_argument('--semantic-audit', type=Path, required=True)
    parser.add_argument('--datasets', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--adaptive', action='store_true', help='One-factor safe document packing ablation')
    parser.add_argument('--adaptive-selection', type=Path, help='Frozen adaptive selection required for final ablation')
    args = parser.parse_args(argv)
    freeze = load(args.fixture/'FREEZE.json')
    hashes = {name: release_eval.sha(args.fixture/name) for name in freeze['sha256']}
    if hashes != freeze['sha256']:
        raise ValueError('confirmation fixture changed after freeze')
    structural, semantic = load(args.structural_audit), load(args.semantic_audit)
    if not structural.get('structural_valid') or structural['hashes'] != hashes:
        raise ValueError('passing structural audit must bind the current fixture')
    question_ids = {q['id'] for split in ('dev', 'final') for q in load(args.fixture/(split+'.json'))['queries']}
    if semantic.get('overall_verdict') != 'pass' or semantic.get('fixture') != args.fixture.name:
        raise ValueError('passing semantic audit of this fixture is required')
    reviewed_ids = {q.get('id', q.get('query_id')) for q in semantic['questions']}
    if reviewed_ids != question_ids or any(q['verdict'] != 'pass' for q in semantic['questions']):
        raise ValueError('semantic audit must explicitly cover all questions')
    selection = load(args.selection)
    reference = load(args.reference_run/'metadata.json')
    if reference['variants']['selected'] != selection['config']:
        raise ValueError('reference configuration differs from frozen selection')
    current = release_eval.source_hashes(SOURCES)
    differences = {name: dict(selected=old, current=current[name]) for name, old in selection['source_sha256'].items() if current[name] != old}
    if set(differences) - {'__init__.py'}:
        raise ValueError('retrieval or generator changed after selection')
    if '__init__.py' in differences:
        original = args.reference_run/'source/context_lab/__init__.py'
        present = Path(release_eval.__file__).parent/'__init__.py'
        if release_eval.sha(original) != selection['source_sha256']['__init__.py'] or without_module_docstring(original.read_text()) != without_module_docstring(present.read_text()):
            raise ValueError('only a verified module docstring change is allowed')
    variants = reference['variants']
    engine_class, config_class, source_names = CompletionRetrieval, CompletionConfig, SOURCES
    if args.adaptive:
        source_names = SOURCES + ('retrieval_adaptive.py',)
        engine_class, config_class = AdaptiveRetrieval, AdaptiveConfig
        variants = {'control': reference['variants']['control'],
                    'previous': selection['config'],
                    'selected': dict(selection['config'], safe_document_packing=True)}
        if args.split == 'final':
            if args.adaptive_selection is None:
                raise ValueError('final adaptive comparison requires a frozen development selection')
            adaptive_selection = load(args.adaptive_selection)
            if (adaptive_selection['source_sha256'] != release_eval.source_hashes(source_names)
                    or adaptive_selection['config'] != variants['selected']
                    or adaptive_selection['fixture_freeze_sha256'] != release_eval.sha(args.fixture/'FREEZE.json')):
                raise ValueError('adaptive source, configuration or fixture differs from selection')
    elif args.adaptive_selection is not None:
        raise ValueError('--adaptive-selection requires --adaptive')
    # All checks precede creation of an output directory or measurement.
    summaries, metadata = release_eval.run(
        args.fixture/'corpus.json', args.fixture/(args.split+'.json'), args.output,
        variants, [tuple(map(int, item.split(':'))) for item in args.datasets.split(',')], args.repeats,
        engine_class=engine_class, config_class=config_class, source_names=source_names)
    metadata.update(confirmation=True, adaptive_ablation=args.adaptive, selection_changed=args.adaptive,
        selection_sha256=release_eval.sha(args.selection),
        selection_source_differences=differences, fixture_chronology=freeze,
        structural_audit_sha256=release_eval.sha(args.structural_audit),
        semantic_audit_sha256=release_eval.sha(args.semantic_audit),
        comparison='Frozen retrieval configurations on an additional project-authored diagnostic; not an independent benchmark.')
    if args.adaptive:
        metadata['comparison'] = 'One-factor safe document packing against unchanged previous configuration; control retained. Project-authored diagnostic.'
    if args.adaptive_selection:
        metadata['adaptive_selection_sha256'] = release_eval.sha(args.adaptive_selection)
        release_eval.write(args.output/'adaptive-selection-used.json', adaptive_selection)
    metadata['runner_sha256'] = release_eval.sha(Path(__file__))
    shutil.copyfile(__file__, args.output/'runner.py')
    release_eval.write(args.output/'metadata.json',metadata)
    release_eval.write(args.output/'selection-used.json',selection)
    print(json.dumps(dict(groups=len(summaries), parity_pairs=metadata['backend_payload_and_candidate_parity_pairs'], output=str(args.output))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
