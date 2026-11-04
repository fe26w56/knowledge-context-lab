from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from context_lab.retrieval_release import ReleaseConfig, ReleaseRetrieval, document_signature
from context_lab.retrieval_v2 import FileAdapter, SQLiteAdapter


def document(key, text, **extra):
    return dict(id=key, title="Beacon storage policy", scope="shared", owner=None,
                source_url="https://example.invalid/"+key, body=text,
                sections=[dict(id=key+"_s", heading="Storage policy", text=text,
                               kind="decision", adoption_status="adopted", valid_from="2026-01-01", valid_to=None)], **extra)


class ReleaseRetrievalTests(unittest.TestCase):
    def test_exact_grouping_preserves_different_conditions_dates_and_access(self):
        a = document("a", "Keep records for 7 days.")
        b = document("b", a["body"])
        self.assertEqual(document_signature(a), document_signature(b))
        for changed in (dict(body=a["body"]+" Exclude test records."), dict(title="Other department"), dict(scope="private", owner="bot_02")):
            self.assertNotEqual(document_signature(a), document_signature(dict(a, **changed)))
        c = deepcopy(a); c["sections"][0]["valid_to"] = "2026-02-01"
        self.assertNotEqual(document_signature(a), document_signature(c))

    def test_parity_provenance_and_private_filter_with_shared_reader_threads(self):
        docs = [document("z-copy", "Keep records for 7 days."), document("a-copy", "Keep records for 7 days.")]
        private = document("private", "PRIVATE_CANARY Keep records for 7 days.")
        private.update(scope="private", owner="bot_02"); docs.append(private)
        request = dict(text="Beacon storage records", actor="bot_01", mode="current", as_of="2026-05-20")
        with tempfile.TemporaryDirectory() as temp:
            payloads = []
            for name, cls in (("file", FileAdapter), ("sqlite", SQLiteAdapter)):
                adapter = cls.create(Path(temp)/name, docs)
                try:
                    engine = ReleaseRetrieval(adapter, ReleaseConfig(candidate_diversity=1))
                    self.assertEqual(3, engine.documents_read)
                    self.assertEqual(2, engine.documents_indexed)
                    with ThreadPoolExecutor(max_workers=16) as pool:
                        values = list(pool.map(lambda _: engine.retrieve(request, 3000), range(32)))
                    self.assertTrue(all(value == values[0] for value in values))
                    value = values[0]
                    self.assertNotIn("PRIVATE_CANARY", value["payload"])
                    self.assertEqual(["a-copy"], value["candidate_documents"])
                    payload = json.loads(value["payload"])
                    self.assertEqual("https://example.invalid/a-copy", payload["sources"]["a-copy"]["source_url"])
                    self.assertEqual(value["candidate_documents"], engine.retrieve(request, 3000, full=True)["candidate_documents"])
                    for key in ("accepted_source_ids", "evidence_sources", "family"):
                        with self.assertRaises(ValueError):
                            engine.retrieve(dict(request, **{key: "not allowed"}))
                    payloads.append(payload)
                finally:
                    adapter.close()
            self.assertEqual(payloads[0], payloads[1])

    def test_diversity_can_retain_a_second_source_without_merging_near_copies(self):
        docs = [document("copy"+str(i), "Beacon storage policy includes retention.") for i in range(6)]
        for i, doc in enumerate(docs):
            doc["body"] += f"\nAnnotation {i}."
        docs.append(document("distinct", "Beacon storage policy requires a separate approval record."))
        request = dict(text="Beacon storage policy", actor="bot_01", mode="current", as_of="2026-05-20")
        with tempfile.TemporaryDirectory() as temp:
            adapter = FileAdapter.create(Path(temp)/"store", docs)
            engine = ReleaseRetrieval(adapter, ReleaseConfig(candidate_diversity=1))
            self.assertEqual(7, engine.documents_indexed)
            self.assertIn("distinct", engine.retrieve(request, 5000)["candidate_documents"])
