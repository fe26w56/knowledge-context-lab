import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('workflow_analysis', Path(__file__).parents[1] / 'scripts/analyze_workflow.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def row(case, cost=100, seconds=10, score=16):
    return {'case': case, 'elapsed_seconds': seconds,
            'usage': {'cost_lower_nanodollars': cost, 'cost_upper_nanodollars': cost},
            'quality': {'strict_pass_count': score, 'case_pass': score == 16}}


class WorkflowAnalysisTests(unittest.TestCase):
    def test_repeats_cluster_by_case(self):
        result = analysis.compare([row('a'), row('a'), row('b'), row('b')],
                                  [row('a', 50, 5), row('a', 50, 5), row('b', 50, 5), row('b', 50, 5)])
        self.assertEqual(result['paired_cases'], 2)
        self.assertEqual(result['cost_saving_fraction_interval'], [.5, .5])
        self.assertEqual(result['case_bootstrap_time_saving_95_interval'], [.5, .5])

    def test_unbalanced_repeats_and_disjoint_cases_rejected(self):
        for right in [[row('a'), row('a')], [row('b')]]:
            with self.assertRaises(ValueError):
                analysis.compare([row('a')], right)

    def test_quality_regressions_are_not_hidden_by_equal_total(self):
        result = analysis.compare([row('a', score=16), row('b', score=15)],
                                  [row('a', score=15), row('b', score=16)])
        self.assertEqual(result['paired_outcomes']['case_pass_wins'], 1)
        self.assertEqual(result['paired_outcomes']['case_pass_losses'], 1)
        self.assertFalse(result['noninferiority_established'])

    def test_task_regression_is_visible_when_case_scores_tie(self):
        a, b = row('a', score=15), row('a', score=15)
        a['quality']['tasks'] = [
            {'task_id': 't1', 'strict_pass': True, 'field_values': {'limit': True}},
            {'task_id': 't2', 'strict_pass': False, 'field_values': {'limit': False}}]
        b['quality']['tasks'] = [
            {'task_id': 't1', 'strict_pass': False, 'field_values': {'limit': False}},
            {'task_id': 't2', 'strict_pass': True, 'field_values': {'limit': True}}]
        result = analysis.compare([a], [b])
        self.assertEqual(result['paired_outcomes']['task_score_ties'], 1)
        self.assertEqual(result['paired_tasks']['wins'], 1)
        self.assertEqual(result['paired_tasks']['losses'], 1)
        self.assertEqual(result['paired_tasks']['new_field_errors'][0]['task_id'], 't1')


if __name__ == '__main__':
    unittest.main()
