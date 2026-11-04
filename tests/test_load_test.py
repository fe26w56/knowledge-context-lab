import json
import tempfile
import unittest
from pathlib import Path

from context_lab.load_test import generate_corpus, run_load
from context_lab.metrics import UnitCounter


class LoadTestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parents[1]
        self.corpus = json.loads((self.root / "fixtures/phase2/corpus.json").read_text())
        self.queries = json.loads((self.root / "fixtures/phase2/dev.json").read_text())
        self.selection = {"stage": 2, "budget": 2000}

    def test_generation_is_exact_and_reproducible(self):
        a, pa = generate_corpus(self.corpus, 100, 17)
        b, pb = generate_corpus(self.corpus, 100, 17)
        self.assertEqual(len(a["documents"]), 100)
        self.assertEqual(a, b); self.assertEqual(pa, pb)
        self.assertGreaterEqual(pa["generated_labels"]["exact_duplicate"], 0)

    def test_native_counter_is_reference_token_count(self):
        counter = UnitCounter("o200k_base")
        text = "日本語の負荷測定"
        self.assertEqual(counter(text), len(counter.encoding.encode(text, disallowed_special=())))

    def test_100_document_run_records_cold_warm_and_parity(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_load(self.corpus, self.queries, self.selection, Path(temp) / "out", sizes=(100,), repeats=1, seed=19)
            self.assertGreater(result["trials"], 0)
            metadata = json.loads((Path(temp) / "out/metadata.json").read_text())
            self.assertEqual([100], metadata["sizes"])
            rows = [json.loads(line) for line in (Path(temp) / "out/trials.jsonl").read_text().splitlines()]
            self.assertEqual({"cold", "warm"}, {r["cache_state"] for r in rows})
            self.assertEqual({"A", "B", "C"}, {r["method"] for r in rows})
            self.assertTrue(all(r["backend_query_reads"] == 0 for r in rows))
            self.assertTrue(all(r["literal_quote_recall"] is not None for r in rows))
            self.assertTrue(all("source_ids" in r["source_quote_map"][0] for r in rows if r["source_quote_map"]))
            self.assertTrue((Path(temp) / "out/trials.csv").is_file())


if __name__ == "__main__": unittest.main()
