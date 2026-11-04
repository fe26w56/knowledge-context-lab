import unittest
from context_lab.context_policy import coverage_policy


class CoverageTests(unittest.TestCase):
    def test_exhaustive_requests_are_not_treated_as_top_k_evidence(self):
        for request in ('How many furniture pieces did I buy?', 'What is the total cost?',
                        '過去の購入件数は何件？','全件の条件を確認して','Have I ever approved this?'):
            self.assertEqual('all',coverage_policy(request)['selected'])
        self.assertEqual('ranked',coverage_policy('What color are my walls?')['selected'])

    def test_callers_can_override_heuristics_and_unknown_values_fail(self):
        self.assertEqual('all',coverage_policy('Summarize releases', 'all')['selected'])
        self.assertEqual('ranked',coverage_policy('total cost', 'ranked')['selected'])
        with self.assertRaises(ValueError):coverage_policy('question','unknown')
