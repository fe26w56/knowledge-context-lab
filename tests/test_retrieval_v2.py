import json
from pathlib import Path
import tempfile
import unittest

from context_lab.retrieval import BudgetTooSmallError
from context_lab.retrieval_v2 import ADAPTERS, Config, RetrievalV2, split_spans


def doc(i, text, **kw):
    return dict(id=i, title="Cache 保存方針", scope=kw.pop("scope", "shared"), owner=kw.pop("owner", None),
                source_url="https://example.invalid/" + i, body=text,
                sections=[dict(id=i+"_s", heading="保存", text=text, kind="decision", adoption_status="adopted", **kw)])


class RetrievalV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = dict(text="Cache 保存方針", actor="bot_01", mode="current", as_of="2026-10-30")

    def tearDown(self):
        self.tmp.cleanup()

    def engines(self, docs, config=Config()):
        adapters = [ADAPTERS[name].create(self.root/name, docs) for name in ADAPTERS]
        self.addCleanup(lambda: [a.close() for a in adapters])
        return [RetrievalV2(a, config) for a in adapters]

    def test_backends_identical_and_private_filtered_before_top_n(self):
        docs = [doc("public", "Cache 保存方針は版を照合。")]
        docs += [doc(f"p{i}", "Cache 保存方針 SECRET_CANARY", scope="private", owner="bot_02") for i in range(8)]
        a, b = self.engines(docs)
        results = [e.retrieve(self.request, 2000) for e in (a, b)]
        self.assertEqual(results[0], results[1])
        self.assertEqual(["public"], results[0]["candidate_documents"])
        self.assertNotIn("SECRET_CANARY", results[0]["payload"])

    def test_state_prefilter_defeats_obsolete_document_crowding_and_keeps_history(self):
        docs = [doc("current", "Cache 保存方針は10分。", valid_from="2026-10-01")]
        docs += [doc(f"old{i}", "Cache 保存方針は旧版。", valid_to="2026-10-01") for i in range(10)]
        a, _ = self.engines(docs, Config(stage=2))
        self.assertEqual(["current"], a.retrieve(self.request, 2000)["candidate_documents"])
        historical = a.retrieve(dict(self.request, mode="history", as_of="2026-09-01"), 2000)
        self.assertNotIn("current", historical["candidate_documents"])
        self.assertIn("旧版", historical["payload"])

    def test_long_table_retains_columns_units_and_global_exception(self):
        text = "保存時間表（単位: 分）\n| 条件 | 時間 | 例外 |\n|---|---:|---|\n" + "".join(f"| 条件{i:02} | {i*5}分 | 承認{i:02} |\n" for i in range(60)) + "全行共通: 本番には適用しない。"
        chunks = split_spans(text, 100)
        self.assertGreater(len(chunks), 2)
        for spans in chunks:
            value = "".join(text[a:b] for a,b in spans)
            self.assertIn("| 条件 | 時間 | 例外 |", value)
            self.assertIn("単位: 分", value)
            self.assertIn("全行共通: 本番には適用しない。", value)
        a, _ = self.engines([doc("table", text)], Config(stage=5, chunk_chars=100))
        result = a.retrieve(dict(self.request, text="条件32 承認32"), 1200)
        self.assertLessEqual(len(result["payload"]), 1200)
        self.assertIn("| 条件32 | 160分 | 承認32 |", result["payload"])

    def test_full_and_sections_use_identical_candidates_and_gold_is_rejected(self):
        a, _ = self.engines([doc("public", "Cache 保存方針は版を照合。")])
        self.assertEqual(a.retrieve(self.request, 2000)["candidate_documents"], a.retrieve(self.request, 2000, full=True)["candidate_documents"])
        for extra in ("id", "expected_quotes", "rubric"):
            with self.assertRaises(ValueError):
                a.retrieve(dict(self.request, **{extra:"do not use"}))
        with self.assertRaises(BudgetTooSmallError):
            a.retrieve(self.request, 1)

    def test_unknown_is_not_proof_of_absence(self):
        a, _ = self.engines([doc("public", "Cache 保存方針は版を照合。")])
        value = json.loads(a.retrieve(dict(self.request, text="zzyyxx987"))["payload"])
        self.assertEqual([], value["items"])
        self.assertIn("not_proof_of_absence", value["warnings"][0])

    def test_draft_is_searchable_but_never_current_rule(self):
        proposal = doc("draft", "Cache 保存方針の自動削除案は草案。")
        proposal["sections"][0]["adoption_status"] = "draft"
        a, _ = self.engines([proposal], Config(stage=2))
        self.assertEqual([], a.retrieve(self.request)["candidate_documents"])
        result = json.loads(a.retrieve(dict(self.request, mode="search"))["payload"])
        self.assertEqual("draft", result["items"][0]["adoption_status"])

    def test_storage_roundtrip_delta_update_and_existing_destination_refused(self):
        initial = [doc("a", "Cache 保存方針v1。"), doc("b", "Cache 第二文書。")]
        for name, cls in ADAPTERS.items():
            with self.subTest(name=name):
                path = self.root/name
                adapter = cls.create(path, initial)
                adapter.update([doc("a", "Cache 保存方針v2。")])
                self.assertEqual(["Cache 保存方針v2。", "Cache 第二文書。"], [d["body"] for d in adapter.read()])
                adapter.close()
                reopened = cls(path)
                self.assertEqual(2, len(reopened.read()))
                reopened.close()
                with self.assertRaises(FileExistsError):
                    cls.create(path, initial)

    def test_definition_intent_is_generic_and_does_not_embed_an_answer(self):
        target = doc("glossary", "架空の呼称ZXQは、装置の部品一覧を指す。")
        target["title"] = "装置の用語と略語の定義"
        a, b = self.engines([target, doc("policy", "部品一覧の保存方針と監査の予定。")],
                            Config(stage=2, definition_expansion=True))
        request = dict(self.request, text="部品一覧をこの部署では何と呼ぶ？")
        result = a.retrieve(request, 2000)
        self.assertIn("架空の呼称ZXQ", result["payload"])
        self.assertNotIn("ZXQ", " ".join(result["query_expansion_terms"]))
        self.assertEqual(result, b.retrieve(request, 2000))

