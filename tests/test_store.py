"""Local invariants only: these tests do not establish D1 or service availability."""

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from context_lab.store import (
    AccessDenied, IdempotencyConflict, KnowledgeStore, NotFound,
    StoreSchemaError, ValidationError, VersionConflict,
)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "knowledge.sqlite"
        self.store = KnowledgeStore(self.path)
        self.arguments = dict(
            record_id="example-policy",
            content={"conclusion": "Use option A", "adoption_status": "adopted"},
            evidence=[{"source_id": "source-1", "source_revision": "sha256:example-v1"}],
            expected_version=0,
            request_id="request-1",
            actor="writer-1",
        )

    def tearDown(self):
        self.directory.cleanup()

    def counts(self):
        with sqlite3.connect(self.path) as connection:
            return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in ("revisions", "heads", "requests")}

    def test_new_revision_preserves_original_content_and_evidence(self):
        self.store.commit(**self.arguments)
        self.store.commit(**dict(self.arguments, request_id="request-2", expected_version=1,
                                 content={"conclusion": "Use option B"},
                                 evidence=[{"source_id": "source-1", "source_revision": "v2"}]))
        first = self.store.get_revision("example-policy", 1, actor="reader")
        latest = self.store.get_current("example-policy", actor="reader")
        self.assertEqual(first["content"], self.arguments["content"])
        self.assertEqual(first["evidence"], self.arguments["evidence"])
        self.assertEqual(latest["version"], 2)
        self.assertEqual(latest["content"]["conclusion"], "Use option B")
        self.assertEqual(first["revision_id"], "example-policy@1")

    def test_lost_ack_retry_after_later_update_returns_original_result(self):
        # Discarding the response simulates a caller whose acknowledgement was lost.
        self.store.commit(**self.arguments)
        self.store.commit(**dict(self.arguments, request_id="request-2", expected_version=1,
                                 content={"conclusion": "Use option B"}))
        retried = self.store.commit(**self.arguments)
        self.assertTrue(retried["replayed"])
        self.assertEqual(retried["version"], 1)
        self.assertEqual(self.store.request_status("request-1", actor="writer-1"), retried)
        self.assertEqual(self.counts(), {"revisions": 2, "heads": 1, "requests": 2})
        with self.assertRaises(IdempotencyConflict):
            self.store.commit(**dict(self.arguments, content={"conclusion": "Unrelated content"}))
        with self.assertRaises(NotFound):
            self.store.request_status("request-1", actor="other-writer")

    def test_two_connections_cannot_both_commit_the_same_expected_version(self):
        self.store.commit(**self.arguments)
        other = KnowledgeStore(self.path)
        barrier = threading.Barrier(2)

        def update(store, number):
            barrier.wait(timeout=5)
            try:
                return store.commit(**dict(self.arguments, expected_version=1,
                                           request_id=f"concurrent-{number}",
                                           actor=f"writer-{number}",
                                           content={"conclusion": f"Candidate {number}"}))
            except VersionConflict:
                return "version-conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(update, store, number)
                       for store, number in ((self.store, 1), (other, 2))]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(results.count("version-conflict"), 1)
        self.assertEqual(self.store.get_current("example-policy", actor="reader")["version"], 2)
        self.assertEqual(self.counts(), {"revisions": 2, "heads": 1, "requests": 2})

    def test_sql_failure_after_revision_insert_rolls_back_all_three_tables(self):
        # Real SQLite failure after the first INSERT, before head/request insertion.
        with sqlite3.connect(self.path) as connection:
            connection.execute("""CREATE TRIGGER injected_head_failure
                BEFORE INSERT ON heads BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected failure"):
            self.store.commit(**self.arguments)
        self.assertEqual(self.counts(), {"revisions": 0, "heads": 0, "requests": 0})
        with self.assertRaises(NotFound):
            self.store.request_status("request-1", actor="writer-1")
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TRIGGER injected_head_failure")
        result = self.store.commit(**self.arguments)
        self.assertEqual(result["version"], 1)
        self.assertFalse(result["replayed"])

    def test_private_scope_applies_to_current_history_and_updates(self):
        private = dict(self.arguments, scope="private", owner="writer-1")
        self.store.commit(**private)
        self.assertEqual(self.store.get_current("example-policy", actor="writer-1")["owner"], "writer-1")
        with self.assertRaises(NotFound):
            self.store.get_current("example-policy", actor="writer-2")
        with self.assertRaises(NotFound):
            self.store.get_revision("example-policy", 1, actor="writer-2")
        with self.assertRaises(AccessDenied):
            self.store.commit(**dict(self.arguments, actor="writer-2", request_id="request-2",
                                     expected_version=1))
        with self.assertRaises(ValidationError):
            self.store.commit(**dict(self.arguments, request_id="request-3", expected_version=1))

    def test_immutable_rows_cannot_be_updated_or_deleted_by_normal_sql(self):
        self.store.commit(**self.arguments)
        for statement in (
            "UPDATE revisions SET content_json='{}'",
            "DELETE FROM revisions",
            "UPDATE requests SET payload_hash='changed'",
            "DELETE FROM requests",
        ):
            with self.subTest(statement=statement):
                with sqlite3.connect(self.path) as connection:
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                        connection.execute(statement)
        self.assertEqual(self.counts(), {"revisions": 1, "heads": 1, "requests": 1})

    def test_backup_restore_preserves_history_and_idempotency(self):
        self.store.commit(**self.arguments)
        self.store.commit(**dict(self.arguments, request_id="request-2", expected_version=1,
                                 content={"conclusion": "Use option B"}))
        backup = self.store.backup_to(self.root / "backup.sqlite")
        restored = KnowledgeStore.restore_from(backup, self.root / "restored.sqlite")
        self.assertEqual(restored.get_current("example-policy", actor="reader"),
                         self.store.get_current("example-policy", actor="reader"))
        self.assertEqual(restored.get_revision("example-policy", 1, actor="reader"),
                         self.store.get_revision("example-policy", 1, actor="reader"))
        self.assertTrue(restored.commit(**self.arguments)["replayed"])
        restored.commit(**dict(self.arguments, request_id="request-3", expected_version=2,
                               content={"conclusion": "Restore-only update"}))
        self.assertEqual(self.store.get_current("example-policy", actor="reader")["version"], 2)
        self.assertEqual(restored.get_current("example-policy", actor="reader")["version"], 3)
        with self.assertRaises(FileExistsError):
            self.store.backup_to(backup)

    def test_unrelated_database_is_rejected_without_schema_changes(self):
        unrelated = self.root / "unrelated.sqlite"
        with sqlite3.connect(unrelated) as connection:
            connection.execute("CREATE TABLE business_data (value TEXT)")
            connection.execute("INSERT INTO business_data VALUES ('keep')")
        with self.assertRaises(StoreSchemaError):
            KnowledgeStore(unrelated)
        with sqlite3.connect(unrelated) as connection:
            names = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(names, [("business_data",)])
            self.assertEqual(connection.execute("SELECT value FROM business_data").fetchone(), ("keep",))


if __name__ == "__main__":
    unittest.main()
