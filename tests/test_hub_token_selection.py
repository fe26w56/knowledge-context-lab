import tempfile
import unittest
from pathlib import Path

from context_lab.bot_receiver import BotReceiver
from context_lab.reader_handoff import ReaderHandoff, reference_token_counter


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.key = "body/test"
        self.large = "stable line\n" * 140
        self.pages = {self.key: self.large}
        self.who = dict(source="test", actor="agent", reader="r1", scope="shared")
        self.counter = reference_token_counter()
        self.reader = self.restart()

    def restart(self):
        return ReaderHandoff(self.state / "reader", **self.who, current=lambda _: self.pages.copy(),
                             count_tokens=self.counter)

    def read(self, fresh=False):
        return self.reader.read(page_id="test", fresh=fresh)

    def ack(self, offer):
        self.reader.acknowledge(page_id="test", receipt=offer["receipt"], head=offer["packet"]["head"])

    def test_unacknowledged_automatic_full_does_not_force_next_revision_full(self):
        self.ack(self.read())
        self.pages = {self.key: "短い。"}
        tiny = self.read()
        self.assertEqual(tiny["packet"]["mode"], "snapshot")
        self.reader = self.restart()
        self.assertEqual(self.read(), tiny)
        self.pages[self.key] = self.large + "追記。\n"
        native_delta = self.read()
        self.assertEqual(native_delta["packet"]["mode"], "delta")
        with self.assertRaises(ValueError):
            self.ack(tiny)
        forced = self.read(fresh=True)
        self.assertNotEqual(forced["receipt"], native_delta["receipt"])
        self.assertEqual(forced["packet"]["mode"], "snapshot")
        self.reader = self.restart()
        self.assertEqual(self.read(), forced)
        self.pages[self.key] += "再追記。\n"
        newer = self.read()
        self.assertEqual(newer["packet"]["mode"], "snapshot")
        self.ack(newer)
        self.assertEqual(self.read()["packet"]["mode"], "delta")

    def test_unchanged_small_snapshots_and_revocation_report_actual_content_change(self):
        def call(name, args):
            return (self.reader.read if name == "read_changes" else self.reader.acknowledge)(**args)
        receiver = BotReceiver(self.state / "client", **self.who, call=call)
        self.pages = {self.key: "短い。"}
        self.assertTrue(receiver.sync("test")["changed"])
        again = receiver.sync("test")
        self.assertEqual(again["packet"]["mode"], "snapshot")
        self.assertFalse(again["changed"])
        self.pages.clear()
        purged = receiver.sync("test")
        self.assertTrue(purged["changed"])
        self.assertEqual(receiver.local_page("test"), {})
        self.assertNotIn("短い", str(purged["packet"]))
        self.assertFalse(receiver.sync("test")["changed"])

    def test_equal_cost_prefers_delta_only_for_acknowledged_baseline(self):
        self.counter = lambda _: 10
        self.reader = self.restart()
        first = self.read()
        self.assertEqual(first["packet"]["mode"], "snapshot")
        self.ack(first)
        self.assertEqual(self.read()["packet"]["mode"], "delta")
