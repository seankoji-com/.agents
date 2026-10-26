"""Loop warnings use retained history, never reinterpret or refund a review."""
from pathlib import Path
import json
import unittest

from tests import test_planning_review as fixtures
from tests.test_rebuild_installed import tree_digest


class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PlanningReviewTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.PlanningReviewTests.tearDownClass()

    def setUp(self):
        self.f = fixtures.PlanningReviewTests()
        self.f.setUp()
        spare = next(p['target'] for p in self.f.selection_data['profiles']['models']
                     if p['target']['providerInstanceId'] == 'fixture-spare')
        self.f.selection_data['review_replacements'].append(
            fixtures.replacement(self.f.selection_data, spare, review=True))
        self.f.add_self()
        self.f.create(installed=True)

    def progress(self, installed=False):
        before = tree_digest(self.f.box.state)
        out = self.f.cli('progress', installed=installed)
        self.assertEqual(tree_digest(self.f.box.state), before)
        self.assertFalse(out['acceptance'])
        self.assertIsNone(out['delivery_and_spend']['value'])
        return out

    def incomplete(self, edit):
        out = self.f.result(self.f.attempt(), edit=edit)
        self.assertEqual(out['outcome'], 'incomplete')
        return self.f.cli('finish')

    def test_different_transport_failures_and_metadata_revisions_still_warn(self):
        first = self.incomplete(lambda r: r['planning_review'].update(coverage=[]))
        self.assertFalse(first['accepted'])
        self.assertFalse(first['progress']['stop_recommended'])
        self.assertEqual(first['progress']['next_action'], 'repair_then_begin')
        # Metadata churn must not look like a repair of the authored plan.
        data = dict(self.f.snapshot_data, repository_head='fixture-head-after')
        snapshot = self.f.cli('capture', data)
        self.assertNotEqual(snapshot['sha256'], self.f.snapshot['sha256'])
        self.assertEqual(snapshot['content_sha256'], self.f.snapshot['content_sha256'])
        self.f.cli('begin', {'snapshot': snapshot})
        second = self.incomplete(lambda r: r.update(commands=[{'argv': 'not-an-array'}]))
        self.assertTrue(second['progress']['stop_recommended'])
        for installed in (False, True):
            out = self.progress(installed)
            self.assertEqual(out['budgets']['content'], {'used': 2, 'limit': 5, 'remaining': 3})
            self.assertIn('consecutive_incomplete_rounds', out['signals'])
            self.assertIn('unchanged_content_without_complete_approval', out['signals'])
            self.assertEqual(out['next_action'], 'diagnose_before_dispatch')
            errors = [p['error'] for r in json.loads(Path(self.f.created['subject_file']).read_text())['rounds']
                      for p in r['passes']]
            self.assertEqual(len(set(errors)), 2)

    def test_live_work_and_unfinished_round_take_priority_over_retry_advice(self):
        attempt = self.f.attempt()
        self.assertEqual(self.progress()['next_action'], 'reconcile_owned_work')
        self.f.result(attempt, edit=lambda r: r['planning_review'].update(coverage=[]))
        self.assertEqual(self.progress()['next_action'], 'finish_current_round')
        self.f.cli('finish')

    def test_technical_failures_are_visible_without_charging_content(self):
        for _ in range(2):
            self.f.unavailable(self.f.attempt())
        out = self.progress(installed=True)
        self.assertEqual(out['budgets']['content']['used'], 0)
        self.assertEqual(out['budgets']['technical']['used'], 2)
        self.assertIn('consecutive_unavailable_attempts', out['signals'])
        self.f.cli('release')
        self.assertEqual(self.progress()['next_action'], 'subject_released')

    def test_completed_review_is_reused_and_warning_is_never_acceptance(self):
        self.f.result(self.f.attempt())
        reference = self.f.finish()
        out = self.progress()
        self.assertFalse(out['stop_recommended'])
        self.assertEqual(out['next_action'], 'inspect_existing_receipt')
        self.assertEqual(out['latest_round']['receipt'], reference)
        self.f.cli('validate', {'reference': reference})

    def test_successful_direct_fallback_ends_the_technical_failure_streak(self):
        for _ in range(2):
            self.f.unavailable(self.f.attempt())
        self.assertTrue(self.progress()['stop_recommended'])
        self.f.direct()
        finished = self.f.cli('finish')
        self.assertTrue(finished['accepted'])
        self.assertFalse(finished['progress']['stop_recommended'])
        self.assertEqual(finished['progress']['consecutive_unavailable_attempts'], 0)
        self.f.plan.write_text('# Plan\nChanged authored content with explicit recovery.\n')
        snapshot = self.f.cli('capture', self.f.snapshot_data)
        self.f.cli('begin', {'snapshot': snapshot})
        self.assertFalse(self.progress(installed=True)['stop_recommended'])

    def test_one_adverse_round_recommends_repair_instead_of_receipt_reuse(self):
        self.f.result(self.f.attempt(), findings=[self.f.finding()], verdict='adverse')
        finished = self.f.cli('finish')
        self.assertFalse(finished['accepted'])
        self.assertEqual(finished['progress']['next_action'], 'repair_then_begin')

    def test_stale_inputs_do_not_hide_diagnostic_or_gain_acceptance(self):
        self.f.result(self.f.attempt())
        reference = self.f.finish()
        self.f.source.write_text('VALUE = 2\n')
        out = self.progress()
        self.assertEqual(out['next_action'], 'inspect_existing_receipt')
        self.assertIn('drift', self.f.cli('validate', {'reference': reference}, ok=False))

    def test_exhaustion_does_not_recommend_an_automatic_budget_increase(self):
        for index in range(5):
            if index:
                self.f.cli('begin', {'requested_rereview': True})
            self.incomplete(lambda r: r['planning_review'].update(coverage=[]))
        out = self.progress(installed=True)
        self.assertIn('budget_exhausted', out['signals'])
        self.assertEqual(out['budgets']['content'], {'used': 5, 'limit': 5, 'remaining': 0})
        self.assertEqual(out['next_action'], 'diagnose_before_dispatch')
        self.assertIn('budget exhausted', self.f.cli('begin', {'requested_rereview': True}, ok=False))

    def test_real_content_change_and_success_end_unchanged_content_warning(self):
        for index in range(2):
            if index:
                self.f.cli('begin', {'requested_rereview': True})
            self.incomplete(lambda r: r['planning_review'].update(coverage=[]))
        self.f.plan.write_text('# Plan\nRead the fixture; interrupted reads fail closed.\n')
        snapshot = self.f.cli('capture', self.f.snapshot_data)
        self.f.cli('begin', {'snapshot': snapshot})
        self.f.result(self.f.attempt())
        self.f.finish()
        out = self.progress()
        self.assertFalse(out['stop_recommended'])
        self.assertEqual(out['budgets']['content']['used'], 3)

    def test_adverse_findings_cannot_become_a_transport_retry_or_disappear(self):
        for index in range(2):
            if index:
                self.f.cli('begin', {'requested_rereview': True})
            self.assertEqual(self.f.result(self.f.attempt(), findings=[self.f.finding()],
                                          verdict='adverse')['outcome'], 'adverse')
            self.f.finish(accepted=False)
        out = self.progress()
        self.assertNotIn('consecutive_incomplete_rounds', out['signals'])
        self.assertIn('unchanged_content_without_complete_approval', out['signals'])
        self.assertEqual(out['open_adverse_findings'], 1)


if __name__ == '__main__':
    unittest.main()
