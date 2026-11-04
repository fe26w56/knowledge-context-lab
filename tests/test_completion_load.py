import unittest
from context_lab.release_eval import generate
from context_lab.retrieval_v2 import validate_documents


class LoadTests(unittest.TestCase):
    def test_mutation_preserves_overlapping_source_sections(self):
        snippet = "Subject rule has 45 days."
        text = "Preface. " + snippet + " End."
        corpus = {"documents": [dict(id="d", title="Subject", scope="shared", body=text,
                    sections=[dict(id="s1",heading="Rule",text=snippet,adoption_status="adopted"),
                              dict(id="s2",heading="Body",text=text,adoption_status="adopted")])]}
        documents, lineage, _ = generate(corpus, 200, 18101)
        validate_documents(documents)
        self.assertTrue({"near", "condition"} <= {kind for _, kind in lineage.values()})
