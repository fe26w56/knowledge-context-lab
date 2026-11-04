from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from context_lab.budget import BudgetExceeded, ExperimentBudget, nanodollars, token_cost


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "budget.sqlite"
        self.budget = ExperimentBudget(self.path, cap_usd="10")

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_distinct_instances_cannot_overspend(self):
        def reserve(n):
            budget = ExperimentBudget(self.path, cap_usd="10")
            try:
                budget.reserve(str(n), nanodollars("1"))
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=16) as pool:
            result = list(pool.map(reserve, range(16)))
        self.assertEqual(sum(result), 10)
        self.assertEqual(self.budget.report()["accounted"], nanodollars("10"))

    def test_crash_and_uncertain_failures_keep_reserved_cost(self):
        self.budget.reserve("interrupted", nanodollars("4"))
        self.budget.reserve("failed", nanodollars("5"))
        self.budget.mark_uncertain("failed")
        resumed = ExperimentBudget(self.path, cap_usd="10")
        with self.assertRaises(BudgetExceeded):
            resumed.reserve("retry", nanodollars("2"))
        with self.assertRaises(ValueError):
            resumed.reserve("interrupted", nanodollars("1"))
        with self.assertRaises(ValueError):
            resumed.settle("failed", 0, {"input_tokens": 0})

    def test_usage_releases_only_confirmed_difference_and_is_immutable(self):
        self.budget.reserve("ok", nanodollars("10"))
        usage = {"input_tokens": 100, "output_tokens": 50}
        self.budget.settle("ok", nanodollars("1"), usage)
        self.budget.settle("ok", nanodollars("1"), usage)
        self.budget.reserve("next", nanodollars("9"))
        with self.assertRaises(ValueError):
            self.budget.settle("ok", 0, usage)
        with self.assertRaises(ValueError):
            ExperimentBudget(self.path, cap_usd="11")

    def test_bad_bound_records_excess_then_halts(self):
        self.budget.reserve("bad-bound", nanodollars("1"))
        with self.assertRaises(BudgetExceeded):
            self.budget.settle("bad-bound", nanodollars("2"), {"input_tokens": 100})
        self.assertTrue(self.budget.report()["halted"])
        self.assertEqual(self.budget.report()["accounted"], nanodollars("2"))
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve("more", 1)

    def test_round_up_and_reject_nonfinite_costs(self):
        self.assertEqual(nanodollars("0.0000000001"), 1)
        self.assertEqual(token_cost(1, "0.10"), 100)
        for invalid in ("NaN", "Infinity", "-1"):
            with self.assertRaises(ValueError):
                nanodollars(invalid)


if __name__ == "__main__":
    unittest.main()
