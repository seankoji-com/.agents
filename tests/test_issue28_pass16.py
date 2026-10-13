"""Pass 16 regressions for the accepted pass 15 Stage 3 findings (R15-ST-01 and R15-ST-02).

Synthetic data only, no live models. R15-ST-01 keeps an already-launched, pre-prepared uncertain
follow-up reconcilable after its stage is invalidated, while a fresh stale-authority launch stays
refused. R15-ST-02 stops accepted-but-uningested terminal work from being removed or replaced to
evade the inherited execution budget or a late result obligation.
"""
import tempfile
import unittest

from core.jobs import JobError, _open_dispatch, _unsettled, create_job, prepare, record_dispatch, retry_task, revise_plan
from core.jobs.store import Store
from shared.job_coordinator import prepare_followup, record_observation
from tests.test_issue28_pass10 import Pass10Fixture
from tests.test_jobs_review import fixture_decision

SCOPE = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0'}


def ok(*_):
    return True


def followup_event(request='fu1', host='host-f', **extra):
    """A host follow-up observation that carries the frozen original authority verbatim."""
    event = {'kind': 'followup', 'request_id': request, 'host_task_id': host, 'parent_host_task_id': 'host0',
             'target': None, 'scope': SCOPE}
    event.update(extra)
    return event


class Pass16Fixture(Pass10Fixture):
    def store(self, root, slots=()):
        """t0 in slot s0/primary plus extra (task_id, slot, request) worker slots in s0."""
        job = self.fx.fx.base_job('identity')
        job['pins']['ape']['effective_workers'] = {
            'ape/source-researcher': {'bytes': 'synthetic pinned worker', 'sha256': 'b' * 64}}
        for task_id, slot, request in slots:
            job['tasks'].append({**job['tasks'][0], 'task_id': task_id, 'logical_slot_id': slot, 'request_id': request,
                                 'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id}})
        create_job(job, root, job['pins'])
        return Store(root, 'identity')

    def ready(self, store, task_id='t0', request='req0', host='host0', ingest=True):
        ref = prepare(store, self.caller, task_id, ok, ok)
        self.observe(store, task_id, 'accepted', request, host)
        if ingest:
            self.ingest(store, task_id, self.result_for(ref['path']))
        self.observe(store, task_id, 'completion', request, host)
        return ref

    def revision(self, store, revision_id, edit):
        fixture_decision(store, self.caller, {'id': 'd-' + revision_id, 'quote': 'Owner approves plan ' + revision_id,
                                              'scope': 'plan:' + revision_id})
        plan = store.load()
        edit(plan)
        return lambda: revise_plan(store, self.caller, {'id': revision_id, 'owner_decision_id': 'd-' + revision_id}, plan)

    def invalidate_stage(self, store, revision_id='invalidate', revision='s0-r2'):
        return self.revision(store, revision_id, lambda p: p['stages'][0].update(revision=revision))()

    def drop(self, store, revision_id, task_id):
        return self.revision(store, revision_id, lambda p: p.update(tasks=[t for t in p['tasks'] if t['task_id'] != task_id]))

    def replace_slot(self, store, revision_id, old, new):
        return self.revision(store, revision_id, lambda p: p.update(tasks=[t for t in p['tasks'] if t['task_id'] != old] + [new]))

    def slot(self, task_id, request, slot='primary'):
        return {'task_id': task_id, 'stage_id': 's0', 'logical_slot_id': slot, 'request_id': request,
                'worker_id': 'ape/source-researcher', 'dependency_key': 'ape',
                'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task_id}}

    def task(self, store, task_id):
        return next(t for t in store.load()['tasks'] if t['task_id'] == task_id)

    def refused(self, store, call, message):
        before = store.file.read_bytes()
        with self.assertRaisesRegex(JobError, message):
            call()
        self.assertEqual(store.file.read_bytes(), before)

    def stale_uncertain_followup(self, store, calls=1):
        """Stage fu1, record its uncertain launch ``calls`` times, then invalidate s0 so t0 goes stale."""
        self.ready(store)
        staged = prepare_followup(store, self.caller, 't0', 'fu1')
        for _ in range(calls):
            record_observation(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'fu1'})
        self.invalidate_stage(store)
        task = self.task(store, 't0')
        self.assertEqual(task['followup_dispatch']['uncertain_calls'], calls)
        self.assertEqual(task['status'], 'stale')
        self.assertTrue(task['inputs_stale'])
        self.assertEqual(_open_dispatch(task), 'uncertain follow-up dispatch lacks an authoritative host observation')
        return staged


class Pass16UncertainFollowupRecoveryTests(Pass16Fixture):
    """R15-ST-01: already-launched uncertain follow-up work is reconciled, fresh stale launches stay refused."""

    def test_r15_st_01_recovered_uncertain_followup_is_reconcilable_after_invalidation(self):
        for calls in (1, 2, 3):
            with self.subTest(uncertain_calls=calls), tempfile.TemporaryDirectory() as td:
                store = self.store(td)
                staged = self.stale_uncertain_followup(store, calls)
                record_dispatch(store, self.caller, 't0', followup_event())
                task = self.task(store, 't0')
                self.assertEqual(task['request_id'], 'fu1')                     # adopted under the frozen brief
                self.assertEqual([h['task_id'] for h in task['followups']], ['host-f'])
                self.assertEqual(task['status'], 'stale')                       # reconciliation never clears staleness
                self.assertTrue(task['inputs_stale'])
                self.assertEqual(_open_dispatch(task), '')                      # known host work is owned, not uncertain
                self.assertIn('owned host work is not terminal with result_available', _unsettled(store.load(), task))
                self.observe(store, 't0', 'completion', 'fu1', 'host-f')
                task = self.task(store, 't0')
                self.assertEqual(task['status'], 'stale')
                self.assertIn('owned terminal work has no ingested result', _unsettled(store.load(), task))
                self.ingest(store, 't0', self.result_for(staged['path']))
                task = self.task(store, 't0')
                self.assertEqual(task['status'], 'stale')                       # a stale task is never silently revived
                self.assertEqual([h['request_id'] for h in task['execution_history']], ['req0', 'fu1'])
                self.assertEqual(_unsettled(store.load(), task), '')

    def test_r15_st_01_recovered_followup_survives_a_validated_pass(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.stale_uncertain_followup(store)
            self.edit(store, lambda s: s['stages'][0].update(cycle=0, validated_cycle=0))  # s0 is a spent pass
            record_dispatch(store, self.caller, 't0', followup_event())
            self.assertEqual([h['task_id'] for h in self.task(store, 't0')['followups']], ['host-f'])

    def test_r15_st_01_fresh_followup_after_invalidation_is_still_refused(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')  # prepared, but never launched uncertainly
            self.invalidate_stage(store)
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', followup_event()),
                         'charged fresh preparation')
            self.assertEqual(self.task(store, 't0')['request_id'], 'req0')

    def test_r15_st_01_recovery_requires_the_uncertain_request_and_frozen_authority(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.stale_uncertain_followup(store)
            for name, event in (('other-request', followup_event('fu2')),
                                ('narrowed-scope', followup_event(scope={'mode': 'worker-evidence', 'path': 'artifacts/tasks/x'})),
                                ('widened-target', followup_event(target={'providerInstanceId': 'x', 'model': 'y'}))):
                with self.subTest(case=name):
                    self.refused(store, lambda e=event: record_dispatch(store, self.caller, 't0', e),
                                 'charged fresh preparation|changed identity, model or authority')
            self.assertEqual(self.task(store, 't0')['request_id'], 'req0')

    def test_r15_st_01_recovery_refuses_a_superseded_correlation(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.stale_uncertain_followup(store)
            self.edit(store, lambda s: s['tasks'][0].update(request_id='req-superseded'))
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', followup_event()),
                         'superseded request')

    def test_r15_st_01_recovered_handle_is_idempotent_and_conflicts_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.stale_uncertain_followup(store)
            record_dispatch(store, self.caller, 't0', followup_event())
            record_dispatch(store, self.caller, 't0', followup_event())  # same host stays idempotent
            self.assertEqual([h['task_id'] for h in self.task(store, 't0')['followups']], ['host-f'])
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_observation(store, self.caller, 't0', followup_event(host='host-g'))
            state = store.load()
            self.assertTrue(any(c['host_task_id'] == 'host-g' for c in state['tasks'][0]['host_conflicts']))
            self.assertTrue(any(b['kind'] == 'conflicting-host-handle' and b['host_task_id'] == 'host-g' for b in state['blockers']))

    def test_r15_st_01_exhausted_budget_refuses_a_fresh_launch_but_reconciles_known_work(self):
        # R16-ST-02: an exhausted ceiling still authorizes reconciliation of the already-launched,
        # pre-prepared uncertain follow-up, but never permits a fresh follow-up launch.
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.stale_uncertain_followup(store)
            self.edit(store, lambda s: s['tasks'][0].update(attempt=4))  # 1 + max_repair_cycles
            record_dispatch(store, self.caller, 't0', followup_event())  # known host work stays recoverable
            self.assertEqual(self.task(store, 't0')['request_id'], 'fu1')
            self.assertEqual([h['task_id'] for h in self.task(store, 't0')['followups']], ['host-f'])
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')  # prepared but never launched uncertainly
            self.edit(store, lambda s: s['tasks'][0].update(attempt=4))
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', followup_event()),
                         'charged fresh preparation|budget exhausted')
            self.assertEqual(self.task(store, 't0')['request_id'], 'req0')

    def test_r15_st_01_uncertain_dispatch_blocks_retry_until_reconciled(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.stale_uncertain_followup(store)
            self.refused(store, lambda: retry_task(store, self.caller, 't0', 'replacement without reconciliation'),
                         'uncertain follow-up dispatch')


class Pass16UningestedTerminalTests(Pass16Fixture):
    """R15-ST-02: accepted-but-uningested terminal work stays an obligation until its result is read."""

    def uningested(self, store, task_id, request, host):
        """Prepare, accept and observe a terminal host result without ingesting it."""
        ref = prepare(store, self.caller, task_id, ok, ok)
        self.observe(store, task_id, 'accepted', request, host)
        self.observe(store, task_id, 'completion', request, host)
        task = self.task(store, task_id)
        self.assertEqual(task['attempt'], 0)
        self.assertEqual(task.get('execution_history', []), [])
        self.assertEqual(_unsettled(store.load(), task), 'owned terminal work has no ingested result')
        return ref

    def test_r15_st_02_uningested_terminal_work_blocks_removal_for_every_slot(self):
        for task_id, slot, request, host in (('t0', 'primary', 'req0', 'host0'),
                                             ('t1', 'support', 'req1', 'host1'),
                                             ('t2', 'review', 'req2', 'host2')):
            with self.subTest(slot=slot), tempfile.TemporaryDirectory() as td:
                store = self.store(td, [('t1', 'support', 'req1'), ('t2', 'review', 'req2')])
                ref = self.uningested(store, task_id, request, host)
                self.refused(store, self.drop(store, 'drop-' + task_id, task_id), 'owned terminal work has no ingested result')
                self.ingest(store, task_id, self.result_for(ref['path']))
                self.assertEqual(_unsettled(store.load(), self.task(store, task_id)), '')
                self.drop(store, 'drop2-' + task_id, task_id)()
                self.assertNotIn(task_id, [t['task_id'] for t in store.load()['tasks']])

    def test_r15_st_02_uningested_terminal_work_blocks_same_slot_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.uningested(store, 't0', 'req0', 'host0')
            self.refused(store, self.replace_slot(store, 'replace-t0', 't0', self.slot('t1', 'req-t1')),
                         'owned terminal work has no ingested result')
            self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0'])

    def test_r15_st_02_late_major_result_cannot_be_evaded_by_replacement(self):
        def adverse(path):
            body = self.result_for(path)
            body.update(review_verdict='adverse', findings=[{'id': 'F1', 'severity': 'major', 'scenario': 'synthetic',
                                                             'source_evidence': ['fixture']}])
            return body
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = self.uningested(store, 't0', 'req0', 'host0')
            self.ingest(store, 't0', adverse(ref['path']))  # the late result arrives before any archival
            self.assertEqual(_unsettled(store.load(), self.task(store, 't0')), '')  # the result is now ingested
            self.refused(store, self.replace_slot(store, 'replace-t0', 't0', self.slot('t1', 'req-t1')),
                         'unresolved blocker or major finding')  # but its major obligation still blocks replacement
            self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0'])

    def test_r15_st_02_repeated_accepted_replacements_cannot_reset_the_inherited_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)  # first of 1 + max_repair_cycles executions
            executed, current = 1, 't0'
            for round in range(8):
                new_id = 't%d' % (round + 1)
                self.replace_slot(store, 'replace-%d' % round, current, self.slot(new_id, 'req-r%d' % round))()
                try:
                    retry_task(store, self.caller, new_id, 'charged replacement')
                    request = self.task(store, new_id)['request_id']
                    ref = prepare(store, self.caller, new_id, ok, ok)
                except JobError as exc:
                    self.assertIn('budget exhausted', str(exc))
                    break
                self.observe(store, new_id, 'accepted', request, 'host-%d' % round)
                self.ingest(store, new_id, self.result_for(ref['path']))
                self.observe(store, new_id, 'completion', request, 'host-%d' % round)
                executed, current = executed + 1, new_id
            self.assertEqual(executed, 4)  # more than five replacement attempts still yield one charged budget


if __name__ == '__main__':
    unittest.main()
