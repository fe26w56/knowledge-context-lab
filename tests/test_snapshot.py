import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from context_lab.snapshot import documents_from_snapshot, read_snapshot, retrieval_documents
from context_lab.store import AccessDenied, KnowledgeStore, ValidationError


def commit(store, record_id, version, request_id, content, *, actor="writer", scope="shared", owner=None):
    return store.commit(record_id=record_id, content=content,
                        evidence=[{"source_id": "source", "source_revision": request_id}],
                        expected_version=version, request_id=request_id, actor=actor,
                        scope=scope, owner=owner)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(Path(self.tmp.name) / "store.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def doc(text):
        return {"title": "Policy", "body": text,
                "sections": [{"id": "section", "heading": "Rule", "text": text,
                              "kind": "decision", "adoption_status": "adopted"}]}

    def test_snapshot_has_one_current_revision_per_visible_record_and_digest(self):
        commit(self.store, "shared", 0, "r1", self.doc("old"))
        commit(self.store, "shared", 1, "r2", self.doc("new"))
        commit(self.store, "private", 0, "p1", self.doc("secret"), scope="private", owner="alice", actor="alice")
        snapshot = read_snapshot(self.store, actor="reader")
        self.assertEqual([(r["record_id"], r["version"]) for r in snapshot["records"]], [("shared", 2)])
        self.assertEqual(snapshot["manifest"][0]["revision_id"], "shared@2")
        self.assertEqual(len(snapshot["snapshot_sha256"]), 64)
        snapshot["records"][0]["content"]["body"] = "caller mutation"
        self.assertEqual(read_snapshot(self.store, actor="reader")["records"][0]["content"]["body"], "new")
        self.assertEqual(read_snapshot(self.store, actor="reader", record_ids=[])["records"], [])
        with self.assertRaises(ValidationError):
            read_snapshot(self.store, actor="reader", record_ids=[{"bad": "id"}])

    def test_private_rows_are_not_disclosed_and_adapter_binds_authority(self):
        commit(self.store, "public", 0, "r1", self.doc("public"))
        commit(self.store, "secret", 0, "p1", self.doc("secret"), scope="private", owner="alice", actor="alice")
        snapshot, docs = retrieval_documents(self.store, actor="alice")
        self.assertEqual({d["id"] for d in docs}, {"public", "secret"})
        self.assertEqual({d["scope"] for d in docs}, {"shared", "private"})
        self.assertEqual(snapshot["manifest"][1]["revision_id"], "secret@1")
        tampered = dict(snapshot)
        tampered["records"] = [dict(snapshot["records"][0], content=dict(snapshot["records"][0]["content"], id="stale"))]
        with self.assertRaises(ValidationError):
            documents_from_snapshot(tampered)
        self.assertEqual(len(read_snapshot(self.store, actor="bob")["records"]), 1)

    def test_concurrent_readers_observe_complete_revisions(self):
        commit(self.store, "shared", 0, "r0", self.doc("v1"))
        writer = KnowledgeStore(self.store.path)
        def write():
            for version in range(1, 17):
                commit(writer, "shared", version, f"r{version}", self.doc(f"v{version + 1}"))
        with ThreadPoolExecutor(max_workers=16) as pool:
            future = pool.submit(write)
            reader_futures = [pool.submit(read_snapshot, self.store, actor="reader") for _ in range(16)]
            snapshots = [item.result(timeout=10) for item in reader_futures]
            future.result(timeout=10)
        for snapshot in snapshots:
            records = snapshot["records"]
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["revision_id"], f"shared@{record['version']}")
            self.assertEqual(record["content"]["body"], f"v{record['version']}")


if __name__ == "__main__":
    unittest.main()
