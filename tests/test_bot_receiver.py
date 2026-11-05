import tempfile
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from context_lab.bot_receiver import BotReceiver
from context_lab.reader_handoff import ReaderHandoff


class BotReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pages = {"body/rules": "one\n"}
        self.upstream = ReaderHandoff(self.root / "upstream", source="notion:test",
                                      actor="bot", reader="r1", scope="shared",
                                      current=lambda _page: dict(self.pages))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, args):
        if name == "read_changes":
            return self.upstream.read(**args)
        return self.upstream.acknowledge(**args)

    def test_commits_before_ack_and_restarts(self):
        receiver_dir = self.root / "receiver"
        receiver = BotReceiver(receiver_dir, source="notion:test", actor="bot",
                               reader="r1", scope="shared", call=self.call)
        first = receiver.sync("rules")
        self.assertEqual(receiver.local_page("rules")["body/rules"], "one\n")
        self.pages["body/rules"] = "two\n"
        lost = {"value": True}
        def dropping(name, args):
            value = self.call(name, args)
            if name == "ack_changes" and lost["value"]:
                lost["value"] = False
                raise OSError("response lost")
            return value
        receiver = BotReceiver(receiver_dir, source="notion:test", actor="bot",
                               reader="r1", scope="shared", call=dropping)
        with self.assertRaises(OSError):
            receiver.sync("rules")
        self.assertEqual(receiver.local_page("rules"), {"body/rules": "two\n"})
        # A new process retries the durable ACK, then reads the current state.
        receiver = BotReceiver(receiver_dir, source="notion:test", actor="bot",
                               reader="r1", scope="shared", call=self.call)
        result = receiver.sync("rules")
        self.assertTrue(result["acknowledged"])
        self.assertEqual(receiver.local_page("rules"), {"body/rules": "two\n"})

    def test_revocation_is_a_purge_and_transport_failure_is_not(self):
        receiver = BotReceiver(self.root / "receiver", source="notion:test", actor="bot",
                               reader="r1", scope="shared", call=self.call)
        receiver.sync("rules")
        def unavailable(_name, _args):
            raise OSError("network down")
        broken = BotReceiver(self.root / "broken", source="notion:test", actor="bot",
                             reader="r1", scope="shared", call=unavailable)
        with self.assertRaises(OSError):
            broken.sync("rules")
        self.assertIsNone(broken.local_page("rules"))
        self.pages.clear()
        result = receiver.sync("rules")
        self.assertEqual(receiver.local_page("rules"), {})

    def test_identities_are_separate(self):
        one = BotReceiver(self.root / "receiver", source="notion:test", actor="bot", reader="one",
                          scope="shared", call=self.call)
        two = BotReceiver(self.root / "receiver", source="notion:test", actor="bot", reader="two",
                          scope="shared", call=self.call)
        one.sync("rules")
        self.assertIsNone(two.local_page("rules"))
        self.assertNotEqual(one.path, two.path)

    def test_corruption_requests_fresh_and_invalid_keys_or_ack_are_rejected(self):
        receiver_dir = self.root / "receiver"
        receiver = BotReceiver(receiver_dir, source="notion:test", actor="bot", reader="r1",
                               scope="shared", call=self.call)
        receiver.sync("rules")
        with sqlite3.connect(receiver.path) as db:
            db.execute("UPDATE receiver_pages SET pages=? WHERE page_id=?", (json.dumps({"body/rules": "tampered"}), "rules"))
        result = receiver.sync("rules")
        self.assertTrue(result["changed"])
        self.assertEqual(receiver.local_page("rules"), {"body/rules": "one\n"})

        def invalid(_name, _args):
            offer = self.upstream.read(page_id="rules")
            offer["packet"]["pages"] = {"body/other": "secret"}
            return offer
        bad = BotReceiver(self.root / "bad", source="notion:test", actor="bot", reader="r1",
                          scope="shared", call=invalid)
        with self.assertRaises(ValueError):
            bad.sync("rules")

        def bad_ack(name, args):
            if name == "ack_changes":
                return {"acknowledged": True, "page_id": "other", "head": args["head"]}
            return self.upstream.read(**args)
        malformed = BotReceiver(self.root / "malformed", source="notion:test", actor="bot", reader="r1",
                                scope="shared", call=bad_ack)
        with self.assertRaises(Exception):
            malformed.sync("rules")

    def test_two_instances_serialize_same_identity(self):
        directory = self.root / "same"
        receivers = [BotReceiver(directory, source="notion:test", actor="bot", reader="r1",
                                 scope="shared", call=self.call) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda r: r.sync("rules"), receivers))
        self.assertEqual(results[0]["head"], results[1]["head"])
        self.assertEqual(receivers[0].known_pages(), ["rules"])

    def test_server_backup_rollback_recovers_with_fresh_snapshot(self):
        receiver = BotReceiver(self.root / "receiver", source="notion:test", actor="bot", reader="r1",
                               scope="shared", call=self.call)
        receiver.sync("rules")
        with sqlite3.connect(self.upstream.path) as db:
            old = db.execute("SELECT * FROM reader_state").fetchone()
        self.pages["body/rules"] = "two\n"
        receiver.sync("rules")
        with sqlite3.connect(self.upstream.path) as db:
            db.execute("DELETE FROM reader_state")
            db.execute("INSERT INTO reader_state VALUES (?,?,?,?,?,?,?,?)", old)
        self.pages["body/rules"] = "three\n"
        result = receiver.sync("rules")
        self.assertEqual(result["packet"]["mode"], "snapshot")
        self.assertEqual(receiver.local_page("rules"), self.pages)


if __name__ == "__main__":
    unittest.main()
