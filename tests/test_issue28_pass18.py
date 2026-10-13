"""Pass 18 regressions for the accepted pass 16 Stage 3 findings (R16-ST-01..03).

Synthetic data only, no live models. R16-ST-01 makes an unread terminal result an
obligation that blocks acceptance and every fresh supersession (retry, follow-up,
replacement), while preserving late import of already-owned accepted work.
R16-ST-02 separates fresh-execution permission from authoritative recovery of an
already-launched uncertain follow-up under a narrowed or exhausted repair policy.
R16-ST-03 permits a strictly correlated recovery of pre-existing original or
follow-up uncertainty after cancellation or discard, followed by real terminal
reconciliation, without reopening execution authority.
"""
import tempfile
import unittest

from core.jobs import (
    JobError, _live_handles, _uningested, cancel, discard, prepare, record_dispatch,
    retry_task, revise_plan,
)
from shared.job_acceptance import AcceptanceError, _check_slots, _pending
from shared.job_coordinator import prepare_followup, record_observation
from tests.test_issue28_pass16 import Pass16Fixture, followup_event


def ok(*_):
    return True


class Pass18Fixture(Pass16Fixture):
    def uningested(self, store, task_id='t0', request='req0', host='host0'):
        """Accept and terminally reconcile one host launch without reading its result."""
        ref = prepare(store, self.caller, task_id, ok, ok)
        self.observe(store, task_id, 'accepted', request, host)
        self.observe(store, task_id, 'completion', request, host)
        task = self.task(store, task_id)
        self.assertEqual(task.get('execution_history', []), [])
        self.assertTrue(_uningested(task))
        return ref

    def uncertain_followup(self, store, calls=1):
        """Ingest req0, stage fu1 and record its uncertain launch ``calls`` times."""
        self.ready(store)
        staged = prepare_followup(store, self.caller, 't0', 'fu1')
        for _ in range(calls):
            record_observation(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'fu1'})
        return staged

    def uncertain_original(self, store, calls=1):
        """Prepare the original request and record its uncertain launch ``calls`` times."""
        prepare(store, self.caller, 't0', ok, ok)
        for _ in range(calls):
            record_dispatch(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'req0'})

    def stage(self, store, stage_id='s0'):
        return next(s for s in store.load()['stages'] if s['id'] == stage_id)

    def narrow_policy(self, store, cycles, revision_id='narrow-policy'):
        """Owner-approved policy-only revision narrowing the repair budget."""
        plan = store.load()
        plan['policy']['max_repair_cycles'] = cycles
        return lambda: revise_plan(store, self.caller, {'id': revision_id}, plan)

    @staticmethod
    def accepted_terminal(request, host, status='completed', work_state='result_available'):
        return {'kind': 'accepted', 'request_id': request, 'host_task_id': host, 'status': status,
                'work_state': work_state, 'has_pending_child_runs': False}

    @staticmethod
    def completion(request, host, completion='c0'):
        return {'kind': 'completion', 'request_id': request, 'host_task_id': host, 'completion_id': completion,
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False}


class Pass18UningestedResultTests(Pass18Fixture):
    """R16-ST-01: an unread terminal result blocks acceptance and any fresh supersession."""

    def test_r16_st_01_unread_terminal_result_blocks_retry(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uningested(store)
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'supersede an unread result'),
                         'no ingested result')

    def test_r16_st_01_unread_terminal_result_blocks_followup_supersession(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uningested(store)
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'no ingested result')

    def test_r16_st_01_unread_terminal_result_blocks_acceptance_for_every_slot(self):
        for slot in ('primary', 'support', 'review'):
            with self.subTest(slot=slot), tempfile.TemporaryDirectory() as td:
                store = self.store(td)
                self.edit(store, lambda s, slot=slot: s['tasks'][0].update(logical_slot_id=slot))
                self.uningested(store)
                state = store.load(); stage = state['stages'][0]
                self.assertTrue(_pending(store.load(), stage))
                with self.assertRaisesRegex(AcceptanceError, 'unread terminal result'):
                    _check_slots(store, state, stage)

    def test_r16_st_01_late_owned_result_is_importable_after_a_budget_change(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.observe(store, 't0', 'completion', 'req0', 'host0')
            # The recorded launch survives a policy/budget change that consumes the window.
            self.edit(store, lambda s: s['tasks'][0].update(attempt=1) or s['policy'].update(max_repair_cycles=0))
            self.ingest(store, 't0', self.result_for(ref['path']))
            task = self.task(store, 't0')
            self.assertEqual([h['request_id'] for h in task['execution_history']], ['req0'])
            self.assertEqual(task['attempt'], 2)

    def test_r16_st_01_terminal_failure_without_a_result_creates_no_obligation(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.edit(store, lambda s: s['tasks'][0]['handles'][0].update(status='failed', work_state='failed'))
            self.assertFalse(_uningested(self.task(store, 't0')))

    def test_r16_st_01_accepted_execution_count_stays_within_the_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)                                            # accepted execution 1 of 4
            staged = prepare_followup(store, self.caller, 't0', 'fu1')
            record_dispatch(store, self.caller, 't0', followup_event())
            self.ingest(store, 't0', self.result_for(staged['path']))    # accepted execution 2 of 4
            self.observe(store, 't0', 'completion', 'fu1', 'host-f')
            accepted = 2
            for round in range(8):
                try:
                    retry_task(store, self.caller, 't0', 'charged repair %d' % round)
                except JobError as exc:
                    self.assertIn('budget exhausted', str(exc))
                    break
                request = self.task(store, 't0')['request_id']
                ref = prepare(store, self.caller, 't0', ok, ok)
                self.observe(store, 't0', 'accepted', request, 'host-%d' % round)
                self.ingest(store, 't0', self.result_for(ref['path']))
                self.observe(store, 't0', 'completion', request, 'host-%d' % round)
                accepted += 1
            self.assertEqual(accepted, 4)


class Pass18PolicyNarrowingRecoveryTests(Pass18Fixture):
    """R16-ST-02: policy narrowing or exhaustion never hides an already-launched host."""

    def test_r16_st_02_policy_narrowing_does_not_strand_a_known_uncertain_followup(self):
        for cycles in (0, 1):
            with self.subTest(max_repair_cycles=cycles), tempfile.TemporaryDirectory() as td:
                store = self.store(td)
                self.uncertain_followup(store)                            # attempt stays 1
                self.narrow_policy(store, cycles)()
                task = self.task(store, 't0')
                self.assertTrue(task.get('inputs_stale'))
                self.assertEqual(self.stage(store)['status'], 'stale')
                record_dispatch(store, self.caller, 't0', followup_event())
                task = self.task(store, 't0')
                self.assertEqual(task['request_id'], 'fu1')
                self.assertEqual([h['task_id'] for h in task['followups']], ['host-f'])
                self.assertTrue(task['inputs_stale'])                     # discovery never silently revives

    def test_r16_st_02_recovery_holds_even_above_the_current_ceiling(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_followup(store)
            self.edit(store, lambda s: s['tasks'][0].update(attempt=4))
            record_dispatch(store, self.caller, 't0', followup_event())
            self.assertEqual(self.task(store, 't0')['request_id'], 'fu1')

    def test_r16_st_02_recovery_still_requires_the_frozen_correlation(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_followup(store)
            self.narrow_policy(store, 0)()
            for name, event in (
                    ('other-request', followup_event('fu2')),
                    ('narrowed-scope', followup_event(scope={'mode': 'worker-evidence', 'path': 'artifacts/tasks/x'})),
                    ('widened-target', followup_event(target={'providerInstanceId': 'x', 'model': 'y'}))):
                with self.subTest(case=name):
                    self.refused(store, lambda e=event: record_dispatch(store, self.caller, 't0', e),
                                 'charged fresh preparation|changed identity, model or authority')
            self.assertEqual(self.task(store, 't0')['request_id'], 'req0')

    def test_r16_st_02_recovered_launch_is_bounded_and_conflicts_are_retained(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_followup(store)
            self.narrow_policy(store, 0)()
            record_dispatch(store, self.caller, 't0', followup_event())
            record_dispatch(store, self.caller, 't0', followup_event())    # same host stays idempotent
            self.assertEqual([h['task_id'] for h in self.task(store, 't0')['followups']], ['host-f'])
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_observation(store, self.caller, 't0', followup_event(host='host-g'))
            state = store.load()
            self.assertTrue(any(c['host_task_id'] == 'host-g' for c in state['tasks'][0]['host_conflicts']))


class Pass18CancelDiscardRecoveryTests(Pass18Fixture):
    """R16-ST-03: cancel/discard still permits correlated recovery of pre-existing uncertainty."""

    def test_r16_st_03_cancelled_original_uncertainty_is_recovered_and_reconciled(self):
        for stop in (cancel, discard):
            with self.subTest(stop=stop.__name__), tempfile.TemporaryDirectory() as td:
                store = self.store(td)
                self.uncertain_original(store)
                stop(store, self.caller, 'operator stop')
                record_dispatch(store, self.caller, 't0', self.accepted_terminal('req0', 'host0'))
                task = self.task(store, 't0')
                self.assertEqual([h['task_id'] for h in task['handles']], ['host0'])
                self.assertEqual(task['handles'][0]['status'], 'completed')
                record_dispatch(store, self.caller, 't0', self.completion('req0', 'host0', 'c0'))
                state = store.load()
                self.assertEqual([n['completion_id'] for n in state['notifications']], ['c0'])
                self.assertTrue(state.get('status') == 'cancelled' or state.get('discard_requested'))

    def test_r16_st_03_cancelled_followup_uncertainty_is_recovered_and_reconciled(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')
            record_observation(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'fu1'})
            cancel(store, self.caller, 'operator stop')
            record_dispatch(store, self.caller, 't0', followup_event())
            task = self.task(store, 't0')
            self.assertEqual(task['request_id'], 'fu1')
            self.assertEqual([h['task_id'] for h in task['followups']], ['host-f'])
            record_dispatch(store, self.caller, 't0', self.completion('fu1', 'host-f', 'cf'))

    def test_r16_st_03_live_discovery_is_retained_for_cleanup_not_asserted_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_original(store)
            cancel(store, self.caller, 'operator stop')
            record_dispatch(store, self.caller, 't0',
                            self.accepted_terminal('req0', 'host0', status='running', work_state='working'))
            handle = self.task(store, 't0')['handles'][0]
            self.assertEqual((handle['status'], handle['work_state']), ('running', 'working'))
            self.assertTrue(_live_handles(self.task(store, 't0')))

    def test_r16_st_03_fresh_or_uncorrelated_recovery_stays_refused(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_original(store)
            cancel(store, self.caller, 'operator stop')
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0',
                         self.accepted_terminal('req-other', 'host-x')),
                         'cancelled job permits only terminal reconciliation')
            self.assertEqual(self.task(store, 't0').get('handles', []), [])

    def test_r16_st_03_terminal_reconciliation_needs_the_recovered_handle(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_original(store)
            cancel(store, self.caller, 'operator stop')
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', self.completion('req0', 'host0', 'c0')),
                         'not for an owned original handle')

    def test_r16_st_03_cancellation_does_not_reopen_execution_authority(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_original(store)
            cancel(store, self.caller, 'operator stop')
            record_dispatch(store, self.caller, 't0', self.accepted_terminal('req0', 'host0'))
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'reopen'), 'cancelled or discarded')
            self.refused(store, lambda: prepare(store, self.caller, 't0', ok, ok), 'cancelled or discarded')

    def test_r16_st_03_discovery_before_cancellation_also_reconciles(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uncertain_original(store)
            record_dispatch(store, self.caller, 't0', self.accepted_terminal('req0', 'host0'))
            cancel(store, self.caller, 'operator stop')
            record_dispatch(store, self.caller, 't0', self.completion('req0', 'host0', 'c0'))
            self.assertEqual([n['completion_id'] for n in store.load()['notifications']], ['c0'])


if __name__ == '__main__':
    unittest.main()
