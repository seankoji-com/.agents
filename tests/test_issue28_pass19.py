"""Pass 19 regressions completing R16-ST-01..03 through the public plan-revision path.

Synthetic data only, no live models. An unread terminal result is an obligation that
fresh preparation cannot bypass after a policy-only revision invalidates the stage: re-
preparing the launched request would clear its stale inputs and let a result produced
under the superseded policy be accepted. The late result stays importable, charged and
stale, and its finding is retained. Policy narrowing through revise_plan (not a raw state
edit) still lets already-launched uncertain work be recovered while fresh work is refused.
"""
import tempfile
import unittest

from core.jobs import _uningested, prepare, record_dispatch, retry_task, revise_plan
from shared.job_acceptance import AcceptanceError, _check_slots
from shared.job_coordinator import prepare_followup, record_observation
from tests.test_issue28_pass16 import followup_event
from tests.test_issue28_pass18 import Pass18Fixture, ok


class Pass19Fixture(Pass18Fixture):
    def revise_policy(self, store, revision_id, **policy):
        """A policy-only narrowing through the public revision API (no owner decision needed)."""
        plan = store.load()
        plan['policy'].update(policy)
        return revise_plan(store, self.caller, {'id': revision_id}, plan)

    def narrow_bytes(self, store):
        """Halve the artifact limit: a narrowing that leaves the launched request's brief bytes unchanged."""
        return self.revise_policy(store, 'narrow-bytes', max_artifact_bytes=store.load()['policy']['max_artifact_bytes'] // 2)

    def adverse(self, path):
        body = self.result_for(path)
        body.update(review_verdict='adverse', findings=[{'id': 'F1', 'severity': 'major', 'scenario': 'synthetic',
                                                         'source_evidence': ['fixture']}])
        return body


class Pass19UnreadResultFreshPreparationTests(Pass19Fixture):
    """R16-ST-01: fresh preparation cannot supersede or de-stale an unread terminal result."""

    def test_unread_result_blocks_fresh_preparation_after_policy_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = self.uningested(store)
            self.narrow_bytes(store)
            task = self.task(store, 't0')
            self.assertEqual((task['status'], task.get('inputs_stale')), ('stale', True))
            self.refused(store, lambda: prepare(store, self.caller, 't0', ok, ok), 'no ingested result')
            self.assertTrue(self.task(store, 't0').get('inputs_stale'))
            # The late result is still importable and charged, stays stale and keeps its finding.
            self.ingest(store, 't0', self.adverse(ref['path']))
            task = self.task(store, 't0')
            self.assertEqual((task['status'], task['attempt'], task.get('inputs_stale')), ('stale', 1, True))
            self.assertEqual([d['finding_id'] for d in task['finding_dispositions']], ['F1'])
            state = store.load()
            with self.assertRaisesRegex(AcceptanceError, 'inputs changed'):
                _check_slots(store, state, state['stages'][0])

    def test_never_launched_slot_is_still_prepared_after_the_same_revision(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, slots=[('t1', 'support', 'req1')])
            self.uningested(store)
            self.narrow_bytes(store)
            self.assertTrue(prepare(store, self.caller, 't1', ok, ok)['path'])
            self.assertFalse(self.task(store, 't1').get('inputs_stale'))

    def test_ingested_stale_result_takes_the_charged_retry_not_re_preparation(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = self.uningested(store)
            self.ingest(store, 't0', self.result_for(ref['path']))
            self.assertFalse(_uningested(self.task(store, 't0')))
            self.narrow_bytes(store)
            self.refused(store, lambda: prepare(store, self.caller, 't0', ok, ok), 'charged repair pass')
            retry_task(store, self.caller, 't0', 'stale after policy change')
            self.assertNotEqual(self.task(store, 't0')['request_id'], 'req0')
            self.assertTrue(prepare(store, self.caller, 't0', ok, ok)['path'])


class Pass19PublicPolicyNarrowingTests(Pass19Fixture):
    """R16-ST-02: public policy narrowing never strands known work nor authorizes fresh work."""

    def test_public_narrowing_recovers_a_known_uncertain_followup_and_refuses_a_fresh_one(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_followup(store)
            self.revise_policy(store, 'narrow-cycles', max_repair_cycles=0)
            self.assertTrue(self.task(store, 't0').get('inputs_stale'))
            record_dispatch(store, self.caller, 't0', followup_event('fu1', 'host-f'))
            task = self.task(store, 't0')
            self.assertEqual([h['request_id'] for h in task['followups']], ['fu1'])
            self.assertEqual(task['status'], 'stale')
            self.observe(store, 't0', 'reconciled', 'fu1', 'host-f')
            self.assertEqual(self.task(store, 't0')['followups'][0]['status'], 'completed')
            # Recovery granted no fresh authority: retry is exhausted under the narrowed policy.
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu2'), 'stale task contract')

    def test_public_narrowing_keeps_a_known_uncertain_original_recoverable(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_original(store, calls=2)
            self.revise_policy(store, 'narrow-cycles', max_repair_cycles=0)
            record_dispatch(store, self.caller, 't0', self.accepted_terminal('req0', 'host0'))
            task = self.task(store, 't0')
            self.assertEqual([h['task_id'] for h in task['handles']], ['host0'])
            self.assertTrue(_uningested(task))
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'fresh'), 'no ingested result')

    def test_uncorrelated_followup_is_refused_after_public_narrowing(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_followup(store)
            self.revise_policy(store, 'narrow-cycles', max_repair_cycles=0)
            self.refused(store, lambda: record_observation(store, self.caller, 't0', followup_event('fu-other', 'host-x')),
                         'stale, validated-pass or exhausted|prepared immutable brief')


if __name__ == '__main__':
    unittest.main()
