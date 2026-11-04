from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from context_lab.retrieval_completion import CompletionConfig, CompletionRetrieval
from context_lab.retrieval_release import ReleaseConfig, ReleaseRetrieval
from context_lab.retrieval_v2 import FileAdapter


def document(key, text, status="adopted"):
    return dict(id=key, title="Policy", scope="shared", body=text,
                sections=[dict(id=key+"_s",heading="Rules",text=text,kind="decision",adoption_status=status)])


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.request = dict(text="policy audit",actor="agent",mode="current",as_of="2026-10-30")

    def adapter(self, documents):
        return FileAdapter.create(Path(self.tmp.name)/"store", documents)

    def test_disabled_switches_preserve_control(self):
        adapter = self.adapter([document("a", "Audit policy keeps logs."), document("b", "Unrelated note.")])
        control = ReleaseRetrieval(adapter, ReleaseConfig(candidate_limit=6))
        candidate = CompletionRetrieval(adapter)
        self.assertEqual(control.retrieve(self.request), candidate.retrieve(self.request))

    def test_compact_spans_are_lossless_and_keep_attribution(self):
        text = "policy audit\n| row | rule |\n|---|---|\n" + "".join(f"| {n} | audit rule {n} |\n" for n in range(20)) + "Global exception: hold until approved."
        adapter = self.adapter([document("table", text)])
        engine = CompletionRetrieval(adapter, CompletionConfig(compact_spans=True, chunk_chars=100))
        result = engine.retrieve(self.request, budget=5000)
        payload = json.loads(result["payload"])
        self.assertEqual(1, len(payload["items"]))
        item = payload["items"][0]
        self.assertEqual(text, item["text"])
        self.assertEqual("table", item["document_id"])
        self.assertEqual("adopted", item["adoption_status"])
        self.assertEqual([[0, len(text)]], item["spans"])
        self.assertLessEqual(len(result["payload"]), 5000)
        self.assertEqual(engine.retrieve(self.request, full=True)["candidate_documents"], result["candidate_documents"])

    def test_ranking_does_not_use_ineligible_section_text(self):
        polluted = document("polluted", "Ordinary paragraph.")
        polluted["sections"].append(dict(id="old",heading="Old",text="audit policy "*50,
                kind="decision",adoption_status="superseded"))
        polluted["body"] += "\n" + polluted["sections"][1]["text"]
        adapter = self.adapter([polluted,document("current", "audit policy needs approval")])
        engine = CompletionRetrieval(adapter, CompletionConfig(eligible_section_ranking=True,candidate_limit=1))
        self.assertEqual(["current"], engine.retrieve(self.request)["candidate_documents"])
        def run(mode):
            return engine.retrieve(dict(self.request,mode=mode),full=True)["payload"]
        with ThreadPoolExecutor(max_workers=16) as pool:
            values = list(pool.map(run,["current","search"]*8))
        self.assertEqual(1,len(set(values[::2])))
        self.assertEqual(1,len(set(values[1::2])))
        for extra in ("id", "expected_quotes", "rubric"):
            with self.assertRaises(ValueError):
                engine.retrieve(dict(self.request,**{extra:"leak"}))

    def test_diversity_can_include_a_complementary_record_among_near_copies(self):
        documents = [document(f"copy{i}", "audit policy retention 30 days and logs " + f"local note {i}") for i in range(15)]
        documents += [document("handoff", "audit policy requires recipient receipt before transfer")]
        adapter = self.adapter(documents)
        engine = CompletionRetrieval(adapter, CompletionConfig(eligible_section_ranking=True, lexical_diversity=.8,candidate_limit=2))
        result = engine.retrieve(self.request,full=True)
        self.assertIn("handoff", result["candidate_documents"])
        self.assertEqual(2,len(result["candidate_documents"]))

    def test_imported_content_kind_cannot_bypass_explicit_nonadoption(self):
        draft = document("draft", "audit policy draft never adopted", status="draft")
        draft["sections"][0]["kind"] = "document_body"
        adapter = self.adapter([draft, document("current", "audit policy adopted")])
        engine = CompletionRetrieval(adapter, CompletionConfig(strict_current_state=True, eligible_section_ranking=True))
        self.assertEqual(["current"],engine.retrieve(self.request)["candidate_documents"])
        self.assertIn("draft",engine.retrieve(dict(self.request,mode="search"))["candidate_documents"])
