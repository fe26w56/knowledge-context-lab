"""Fictional reviewed-topic lifecycle; temporary database, no network or model."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from context_lab.reviewed_context import ReviewedWorkspace, render_citations
from context_lab.workspace import Workspace


def main():
    with TemporaryDirectory() as folder:
        workspace = Workspace(Path(folder) / 'demo.sqlite')
        review = ReviewedWorkspace(workspace)
        body = '# Shipping\nShip after inspection. Hold if a measurement is missing.\n\n## Background\nTeam notes.\n'
        page = {'id': 'shipping', 'title': 'Shipping', 'body': body, 'scope': 'shared',
                'properties': {'project': 'demo', 'topic_id': 'shipping',
                               'version': 'v1', 'status': 'current'}}
        workspace.import_pages([page], actor='editor', request_id='import-v1')
        # In real use a reviewer chooses this range before answering requests.
        end = body.index('\n\n## Background')
        review.publish('demo', 'shipping', [{
            'source_id': 'shipping', 'source_version': 'v1',
            'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'start': 0, 'end': end, 'topic_id': 'shipping',
            'scope': 'shared', 'reviewed': True,
        }], actor='editor', request_id='review-v1', confirmed=True)
        fixed = review.snapshot(actor='reader')
        context = fixed.context('demo', 'shipping')
        assert context['status'] == 'available'
        citation = render_citations(context, [context['sources'][0]['spans'][0]['citation_id']])
        assert citation[0]['quote'] == body[:end]
        changed = deepcopy(page)
        changed['body'] = body.replace('inspection', 'inspection and signature')
        changed['properties']['version'] = 'v2'
        workspace.import_pages([changed], actor='editor', request_id='import-v2',
                               expected_versions={'shipping': 1})
        fresh = review.snapshot(actor='reader').context('demo', 'shipping')
        assert fresh['status'] == 'needs_review' and fresh['sources'] == []
        assert fixed.context('demo', 'shipping') == context  # Historical view stays fixed.
        print(json.dumps({'before_update': context, 'resolved_citation': citation,
                          'fresh_after_update': fresh, 'old_view_is_not_current': True},
                         ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
