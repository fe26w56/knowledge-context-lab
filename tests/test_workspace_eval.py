import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_workspace import file_sources, load_fixture, query


class WorkspaceEvaluationHarnessTest(unittest.TestCase):
    def setUp(self):
        self.pages, self.dev = load_fixture(Path("fixtures/phase2-migration-v2"))
        self.sources = file_sources(self.pages, "evaluator")

    def test_fixture_is_raw_pages_and_has_distinct_splits(self):
        self.assertEqual(len(self.pages), 16)
        self.assertEqual(len(self.dev["tasks"]), 8)
        self.assertTrue(all("body" in page and "properties" in page for page in self.pages))

    def test_query_does_not_use_gold(self):
        task = self.dev["tasks"][0]
        result = query("current", self.sources, task)
        self.assertIn(result["status"], {"found", "not_found"})
        self.assertNotIn("gold", json.dumps(result["result"], ensure_ascii=False))

    def test_raw_and_current_have_same_source_identity(self):
        task = self.dev["tasks"][0]
        raw = query("raw", self.sources, task)["result"]
        current = query("current", self.sources, task)["result"]
        raw_ids = {x["page"]["id"] for x in raw["sources"]}
        cur_ids = {x["source_id"] for x in current["sources"]}
        self.assertTrue(cur_ids.issubset(raw_ids))


if __name__ == "__main__":
    unittest.main()
