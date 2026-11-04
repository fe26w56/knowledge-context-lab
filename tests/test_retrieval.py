"""Behavioral safeguards for the offline retrieval experiment."""

from copy import deepcopy
import json
import unittest

from context_lab.retrieval import BudgetTooSmallError, RetrievalEngine


def document(identifier, title, sections, *, scope="shared", owner=None):
    return {
        "id": identifier, "title": title, "scope": scope, "owner": owner,
        "source_url": "https://example.invalid/" + identifier,
        "recorded_at": "2026-10-29", "verified_at": "2026-10-29",
        "body": "\n\n".join("## " + s["heading"] + "\n" + s["text"] for s in sections),
        "sections": sections,
    }


def section(identifier, text, **properties):
    return dict(id=identifier, heading="保存方針", text=text, kind="decision", adoption_status="adopted", **properties)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.docs = [document("public", "D1 保存方針", [
            section("old", "D1の保存は旧方針を使う。", valid_from="2026-01-01", valid_to="2026-10-01"),
            section("new", "D1の保存は根拠と版を必ず残す。", valid_from="2026-10-01"),
        ])]
        self.request = {"text": "D1 保存方針", "actor": "reader", "mode": "current", "as_of": "2026-10-29"}

    def test_private_documents_are_filtered_before_candidate_selection(self):
        private = document("private", "D1 保存方針", [section("secret", "D1 保存方針 secret-canary")], scope="private", owner="other")
        with RetrievalEngine([private] + self.docs) as engine:
            for method in "ABC":
                result = engine.retrieve(method, self.request, 10000)
                self.assertNotIn("private", result["candidate_documents"])
                self.assertNotIn("secret-canary", result["payload"])
            permitted = engine.retrieve("C", dict(self.request, actor="other"), 10000)
            self.assertIn("secret", permitted["selected_sections"])

    def test_current_filters_do_not_remove_history_from_comparison_baselines(self):
        with RetrievalEngine(self.docs) as engine:
            for method in "AB":
                result = engine.retrieve(method, self.request, 10000)
                self.assertIn("old", result["selected_sections"])
            result = engine.retrieve("C", self.request, 10000)
            self.assertNotIn("old", result["selected_sections"])
            self.assertIn("new", result["selected_sections"])
            historical = engine.retrieve("C", dict(self.request, mode="history", as_of="2026-05-01"), 10000)
            self.assertIn("old", historical["selected_sections"])
            self.assertNotIn("new", historical["selected_sections"])

    def test_proposals_are_not_current_decisions(self):
        docs = deepcopy(self.docs)
        docs[0]["sections"][1]["adoption_status"] = "proposed"
        with RetrievalEngine(docs) as engine:
            current = engine.retrieve("C", self.request, 10000)
            self.assertEqual([], current["selected_sections"])
            searching = engine.retrieve("C", dict(self.request, mode="search"), 10000)
            self.assertIn("new", searching["selected_sections"])

    def test_budget_is_checked_on_serialized_payload_and_never_cuts_a_section(self):
        long_text = "D1保存の例外条件を保持する。" * 300
        docs = [document("long", "D1 保存方針", [section("whole", long_text)])]
        with RetrievalEngine(docs) as engine:
            for method in "BC":
                result = engine.retrieve(method, self.request, 1000)
                self.assertLessEqual(len(result["payload"]), 1000)
                self.assertEqual(len(result["payload"]), result["returned_units"])
                self.assertEqual([], result["selected_sections"])
                self.assertEqual(1, result["omitted_sections"])
                self.assertFalse(result["truncated"])
                self.assertTrue(json.loads(result["payload"])["budget_limited"])
            full = engine.retrieve("A", self.request, 1000)
            self.assertTrue(full["budget_exceeded"])
            self.assertIn("whole", full["selected_sections"])

    def test_short_ascii_and_japanese_queries_are_searchable(self):
        docs = [document("x", "運用", [section("x1", "D1とDBの容量を調べる。")])]
        with RetrievalEngine(docs) as engine:
            for query in ["D1", "DB", "容量"]:
                result = engine.retrieve("C", dict(self.request, text=query), 10000)
                self.assertEqual(["x1"], result["selected_sections"])

    def test_custom_counter_covers_the_actual_context_payload(self):
        def byte_counter(value):
            return len(value.encode("utf-8"))
        byte_counter.unit_name = "utf8_bytes"
        with RetrievalEngine(self.docs) as engine:
            result = engine.retrieve("B", self.request, 3000, byte_counter)
            self.assertEqual("utf8_bytes", result["unit"])
            self.assertEqual(len(result["payload"].encode("utf-8")), result["returned_units"])
            self.assertLessEqual(result["returned_units"], 3000)

    def test_evidence_is_verbatim_and_corpus_is_frozen(self):
        docs = deepcopy(self.docs)
        with RetrievalEngine(docs) as engine:
            docs[0]["sections"][1]["text"] = "changed after construction"
            result = engine.retrieve("C", self.request, 10000)
            items = json.loads(result["payload"])["items"]
            self.assertEqual("D1の保存は根拠と版を必ず残す。", items[0]["text"])

    def test_missing_candidates_are_not_reported_as_proven_absence(self):
        with RetrievalEngine(self.docs) as engine:
            result = engine.retrieve("C", dict(self.request, text="quasar987654"), 1000)
            self.assertEqual([], result["selected_sections"])
            self.assertTrue(any("not_proof_of_absence" in warning for warning in result["warnings"]))

    def test_invalid_or_impossible_budgets_fail_explicitly(self):
        with RetrievalEngine(self.docs) as engine:
            with self.assertRaises(BudgetTooSmallError):
                engine.retrieve("B", self.request, 1)
            with self.assertRaises(ValueError):
                engine.retrieve("C", self.request, -1)

    def test_source_spans_must_match_the_original(self):
        docs = deepcopy(self.docs)
        docs[0]["sections"][0]["text"] = "invented summary"
        with self.assertRaises(ValueError):
            RetrievalEngine(docs)

    def test_missing_scope_is_not_implicitly_shared(self):
        docs = deepcopy(self.docs)
        del docs[0]["scope"]
        with self.assertRaises(ValueError):
            RetrievalEngine(docs)

    def test_one_candidate_is_shared_by_all_methods_and_invalid_limits_fail(self):
        other = document("other", "D1 保存方針の参考資料", [section("other_1", "D1の保存例を説明する。")])
        with RetrievalEngine(self.docs + [other], candidate_limit=1) as engine:
            results = [engine.retrieve(method, self.request, 10000) for method in "ABC"]
            self.assertEqual(1, len(results[0]["candidate_documents"]))
            for result in results[1:]:
                self.assertEqual(results[0]["candidate_documents"], result["candidate_documents"])
            for result in results:
                self.assertEqual(result["candidate_documents"], result["selected_documents"])
        for invalid in (0, -1, True, 1.5, []):
            with self.assertRaises(ValueError):
                RetrievalEngine(self.docs, candidate_limit=invalid)
        with self.assertRaises(ValueError):
            RetrievalEngine([])


if __name__ == "__main__":
    unittest.main()
