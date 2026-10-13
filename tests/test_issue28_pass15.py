"""Pass 15 regressions for the accepted pass 14 Stage 3 findings (R14-ST-01..02) and the
budget-charging and staleness sweeps they prompted; synthetic data only, no live models."""
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs import JobError, create_job, prepare, record_dispatch, record_result, retry_task, revise_plan
from core.jobs.store import Store
from shared.job_acceptance import _stale
from shared.job_coordinator import prepare_followup, publish_observation
from tests.test_issue28_pass14 import Pass14Fixture, ok
from tests.test_jobs_review import fixture_decision

SCOPE = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0'}


def followup(request, host, parent, scope=SCOPE):
    return {'kind': 'followup', 'request_id': request, 'host_task_id': host, 'parent_host_task_id': parent,
            'target': None, 'scope': scope}


class Pass15Fixture(Pass14Fixture):
    def fail_execution(self, store, task_id, completion):
        """Prepare the task's current request and ingest a malformed terminal result (one charged execution)."""
        prepare(store, self.caller, task_id, ok, ok)
        request = self.task(store, task_id)['request_id']
        return record_result(store, self.caller, task_id, {'request_id': request, 'completion_id': completion, 'result': b'{}'})

    def stage(self, store, stage_id='s0'):
        return next(s for s in store.load()['stages'] if s['id'] == stage_id)


class Pass15StageCycleTests(Pass15Fixture):
    """R14-ST-01: an execution belongs to the stage pass it was prepared in."""

    def test_r14_st_01_slot_first_executed_in_an_exhausted_pass_cannot_retry_in_that_pass(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.fail_execution(store, 't0', 'c0')
            for n in range(1, 4):  # three charged repairs exhaust max_repair_cycles=3
                retry_task(store, self.caller, 't0', 'primary repair %d' % n)
                self.fail_execution(store, 't0', 'c%d' % n)
            self.assertEqual(self.stage(store)['cycle'], 3)
            self.fail_execution(store, 't1', 'c-support')  # first execution of the support slot, in pass 3
            self.refused(store, lambda: retry_task(store, self.caller, 't1', 'support repair', 'support'),
                         'shared stage repair cycle budget exhausted')
            self.assertEqual((self.task(store, 't1').get('cycle'), self.task(store, 't1')['attempt']), (3, 1))
            self.assertEqual(self.stage(store)['attempts'], {'primary': 3, 'support': 0, 'review': 0, 'final': 0})

    def test_r14_st_01_slot_first_executed_in_a_later_pass_charges_the_next_pass(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.fail_execution(store, 't0', 'c0')
            retry_task(store, self.caller, 't0', 'primary repair')
            self.fail_execution(store, 't1', 'c-support')  # t1 runs for the first time in pass 1
            retry_task(store, self.caller, 't1', 'support repair', 'support')
            stage = self.stage(store)
            self.assertEqual((stage['cycle'], stage['attempts']['support']), (2, 1))
            self.assertEqual(self.task(store, 't1')['cycle'], 2)

    def test_r14_st_01_positive_control_slots_failing_in_the_same_pass_share_one_charge(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.fail_execution(store, 't0', 'c0')
            self.fail_execution(store, 't1', 'c-support')
            retry_task(store, self.caller, 't0', 'primary repair')
            retry_task(store, self.caller, 't1', 'support repair in the same pass', 'support')
            stage = self.stage(store)
            self.assertEqual((stage['cycle'], stage['attempts']['primary'], stage['attempts']['support']), (1, 1, 0))
            self.assertEqual(self.task(store, 't0')['cycle'], self.task(store, 't1')['cycle'])

    def test_r14_st_01_unbound_executed_slot_is_never_treated_as_pass_zero(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.fail_execution(store, 't0', 'c0')
            retry_task(store, self.caller, 't0', 'primary repair')
            self.fail_execution(store, 't1', 'c-support')
            self.edit(store, lambda s: s['tasks'][1].pop('cycle', None))  # state recorded without the execution's pass
            retry_task(store, self.caller, 't1', 'support repair', 'support')
            self.assertEqual((self.stage(store)['cycle'], self.stage(store)['attempts']['support']), (2, 1))


class Pass15ValidatedPassTests(Pass15Fixture):
    """Sweep: a pass that was already validated admits no new execution without a charged pass."""

    def validated_after_partial_repair(self, store):
        """Pass 0: t0 and t1 ready, validation fails; only t0 is repaired in pass 1, which is validated too."""
        self.ready(store)
        self.ready(store, 't1', 'req1', 'host1')
        self.edit(store, lambda s: s['stages'][0].update(validated_cycle=0, status='failed'))
        retry_task(store, self.caller, 't0', 'repair after failed validation')
        self.ready(store, 't0', self.task(store, 't0')['request_id'], 'host0b')
        self.edit(store, lambda s: s['stages'][0].update(validated_cycle=1, status='failed'))

    def test_sweep_retry_cannot_join_a_validated_pass_uncharged(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.validated_after_partial_repair(store)
            retry_task(store, self.caller, 't1', 'support repair', 'support')
            self.assertEqual((self.stage(store)['cycle'], self.stage(store)['attempts']['support']), (2, 1))

    def test_sweep_exhausted_validated_pass_refuses_a_join_retry(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.validated_after_partial_repair(store)
            self.edit(store, lambda s: s['stages'][0].update(cycle=3, validated_cycle=3) or s['tasks'][0].update(cycle=3))
            self.refused(store, lambda: retry_task(store, self.caller, 't1', 'support repair', 'support'),
                         'shared stage repair cycle budget exhausted')

    def test_sweep_capacity_deferral_cannot_bypass_the_charged_pass_for_a_stale_slot(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            # A slot added after pass 0 was validated: stale, never executed.
            self.edit(store, lambda s: s['stages'][0].update(validated_cycle=0) or s['tasks'][1].update(status='stale'))
            record_dispatch(store, self.caller, 't1', {'kind': 'capacity-deferred', 'request_id': 'req1'})
            self.assertEqual(self.task(store, 't1')['status'], 'stale')
            self.refused(store, lambda: prepare(store, self.caller, 't1', ok, ok), 'charged repair pass')
            self.edit(store, lambda s: s['tasks'][1].update(status='pending'))
            self.refused(store, lambda: prepare(store, self.caller, 't1', ok, ok), 'charged repair pass')
            self.edit(store, lambda s: s['tasks'][1].update(status='stale'))
            # Positive control: a charged retry opens pass 1, where the first execution is allowed.
            retry_task(store, self.caller, 't1', 'charged pass for the added slot', 'support')
            self.assertEqual(self.stage(store)['cycle'], 1)
            prepare(store, self.caller, 't1', ok, ok)
            self.assertEqual(self.task(store, 't1')['cycle'], 1)

    def test_sweep_executed_request_cannot_become_a_capacity_deferral(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store, observe=False)
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', {'kind': 'capacity-deferred', 'request_id': 'req0'}),
                         'executed request cannot become a capacity deferral')
            self.assertEqual(self.task(store, 't0')['status'], 'awaiting-acceptance')

    def test_sweep_followup_needs_an_unvalidated_pass_and_execution_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            self.edit(store, lambda s: s['stages'][0].update(validated_cycle=0, status='failed'))
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'validated pass')
            self.edit(store, lambda s: [s['stages'][0].pop('validated_cycle'), s['tasks'][0].update(attempt=4)])
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'execution budget')
            self.edit(store, lambda s: s['tasks'][0].update(attempt=1))
            prepare_followup(store, self.caller, 't0', 'fu1')  # positive control
            self.edit(store, lambda s: s['stages'][0].update(validated_cycle=0, status='failed'))
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', followup('fu1', 'host-f', 'host0')),
                         'charged fresh preparation')
            self.assertEqual(self.task(store, 't0')['request_id'], 'req0')


class Pass15StaleAuthorityTests(Pass15Fixture):
    """R14-ST-02: a stale task cannot regain acceptance status or continue under withdrawn authority."""

    def narrow(self, store, revision_id='narrow-t0'):
        return self.revision(store, revision_id, lambda p: p['tasks'][0].update(write_scope={'mode': 'coordinator-only'}))

    def restage(self, store, revision_id='s0-r2'):
        return self.revision(store, revision_id, lambda p: p['stages'][0].update(revision=revision_id))

    def test_r14_st_02_replayed_terminal_observation_cannot_reopen_a_stale_task(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            self.narrow(store)()
            task = self.task(store, 't0')
            self.assertEqual((task['status'], task['inputs_stale'], task['write_scope']), ('stale', True, {'mode': 'coordinator-only'}))
            self.observe(store, 't0', 'reconciled', 'req0', 'host0')
            self.assertEqual(self.task(store, 't0')['status'], 'stale')
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'stale task contract')
            self.assertNotIn('prepared_followup', self.task(store, 't0'))
            # Positive control: a charged retry prepares a fresh brief under the current contract.
            retry_task(store, self.caller, 't0', 'charged repair after narrowing')
            ref = self.ready(store, 't0', self.task(store, 't0')['request_id'], 'host1')
            self.assertEqual(json.loads(Path(ref['path']).read_text())['write_scope'], {'mode': 'coordinator-only'})
            staged = prepare_followup(store, self.caller, 't0', 'fu1')
            self.assertEqual(json.loads(Path(staged['path']).read_text())['write_scope'], {'mode': 'coordinator-only'})

    def test_r14_st_02_staged_followup_cannot_be_adopted_after_its_contract_was_narrowed(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')
            self.narrow(store)()
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', followup('fu1', 'host-f', 'host0')),
                         'changed identity, model or authority')
            self.assertEqual(self.task(store, 't0')['request_id'], 'req0')

    def test_r14_st_02_staged_followup_cannot_be_adopted_by_a_stale_task(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'fu1')
            self.restage(store)()  # same task authority, stale stage inputs
            self.assertTrue(self.task(store, 't0')['inputs_stale'])
            self.refused(store, lambda: record_dispatch(store, self.caller, 't0', followup('fu1', 'host-f', 'host0')),
                         'charged fresh preparation')

    def test_r14_st_02_live_execution_invalidated_by_revision_finishes_stale(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.restage(store)()
            self.assertEqual((self.task(store, 't0')['status'], self.task(store, 't0')['inputs_stale']), ('running', True))
            self.ingest(store, 't0', self.result_for(ref['path']))
            self.assertEqual(self.task(store, 't0')['status'], 'stale')
            self.observe(store, 't0', 'completion', 'req0', 'host0')
            self.assertEqual(self.task(store, 't0')['status'], 'stale')
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'stale task contract')

    def test_r14_st_02_followup_brief_authority_comes_from_the_current_contract(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.ready(store)
            # Contract drift that did not pass through a stale-marking revision still cannot be copied.
            self.edit(store, lambda s: s['tasks'][0].update(write_scope={'mode': 'coordinator-only'}))
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'current task contract')
            self.edit(store, lambda s: s['tasks'][0].update(write_scope=SCOPE))
            brief = json.loads(Path(prepare_followup(store, self.caller, 't0', 'fu1')['path']).read_text())
            self.assertEqual((brief['write_scope'], brief['worker_id'], brief['followup_of']), (SCOPE, 'ape/source-researcher', 'req0'))


class Pass15StalenessSweepTests(Pass15Fixture):
    """Sweep: every invalidation path marks live work stale; every new execution uses the current contract."""

    def test_sweep_replaced_worker_pin_invalidates_its_slots(self):
        with tempfile.TemporaryDirectory() as td:
            job = self.fx.fx.base_job('identity')
            worker = {'ape/source-researcher': {'bytes': 'synthetic pinned worker', 'sha256': 'b' * 64}}
            job['pins']['ape']['effective_workers'] = worker
            job['dependencies'].append({'key': 'bee', 'plugin': 'bee'})
            job['pins']['bee'] = {'package_digest': 'b' * 64, 'effective_workers': worker}
            job['tasks'][0]['dependency_key'] = 'bee'  # validator dependency of s0 stays 'ape'
            create_job(job, td, job['pins'])
            store = Store(td, 'identity')
            self.ready(store)
            fixture_decision(store, self.caller, {'id': 'd-adopt-bee', 'quote': 'Owner adopts bee', 'scope': 'plan:adopt-bee'})
            replaced = {'ape/source-researcher': {'bytes': 'replacement worker', 'sha256': 'c' * 64}}
            revise_plan(store, self.caller, {'id': 'adopt-bee', 'owner_decision_id': 'd-adopt-bee', 'adopt_keys': ['bee']},
                        store.load(), lambda j, deps: {**j['pins'], 'bee': {**j['pins']['bee'], 'effective_workers': replaced}})
            task = self.task(store, 't0')
            self.assertEqual((task['status'], task.get('inputs_stale')), ('stale', True))
            self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'stale task contract')

    def test_sweep_upstream_observation_marks_live_downstream_work_stale(self):
        with tempfile.TemporaryDirectory() as td:
            job = self.fx.fx.base_job('identity')
            job['pins']['ape']['effective_workers'] = {
                'ape/source-researcher': {'bytes': 'synthetic pinned worker', 'sha256': 'b' * 64}}
            job['tasks'].append({**job['tasks'][0], 'task_id': 't2', 'stage_id': 's1', 'request_id': 'req2',
                                 'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t2'}})
            create_job(job, td, job['pins'])
            store = Store(td, 'identity')
            prepare(store, self.caller, 't2', ok, ok)
            self.observe(store, 't2', 'accepted', 'req2', 'host2')
            source = Path(td) / 'coordinator-observation.json'
            source.write_text('{"observed": true}')
            publish_observation(store, self.caller, 's0', str(source))
            self.assertEqual((self.task(store, 't2')['status'], self.task(store, 't2').get('inputs_stale')), ('running', True))
            self.observe(store, 't2', 'completion', 'req2', 'host2')
            self.assertEqual(self.task(store, 't2')['status'], 'stale')

    def test_sweep_final_reopen_marks_live_work_stale(self):
        job = {'stages': [{'id': 's0', 'status': 'accepted-at-snapshot', 'acceptance': None}],
               'tasks': [{'task_id': 't0', 'stage_id': 's0', 'status': 'running'},
                         {'task_id': 't1', 'stage_id': 's0', 'status': 'awaiting-acceptance'}]}
        _stale(job, 's0')
        self.assertEqual([(t['status'], t.get('inputs_stale')) for t in job['tasks']], [('running', True), ('stale', True)])

    def test_sweep_fresh_preparation_clears_staleness_only_for_an_unexecuted_slot(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td, [('t1', 'support', 'req1')])
            self.ready(store)
            self.revision(store, 's0-r2', lambda p: p['stages'][0].update(revision='s0-r2'))()
            self.assertTrue(all(t['inputs_stale'] for t in store.load()['tasks']))
            prepare(store, self.caller, 't1', ok, ok)  # never executed: a fresh brief binds the current contract
            self.assertNotIn('inputs_stale', self.task(store, 't1'))
            self.refused(store, lambda: prepare(store, self.caller, 't0', ok, ok), 'charged repair pass')



class Pass15ObservationOrderTests(Pass15Fixture):
    """Sweep: the ingested current result alone decides acceptance status; observation order cannot change it."""

    def test_sweep_terminal_observation_never_overrides_the_ingested_result_status(self):
        expected = {'ready-for-acceptance': 'awaiting-acceptance', 'needs-followup': 'awaiting-followup',
                    'blocked': 'blocked', 'failed': 'failed', 'malformed': 'failed'}
        for result_status, task_status in expected.items():
            for order in ('observation-last', 'observation-first'):
                with self.subTest(result=result_status, order=order), tempfile.TemporaryDirectory() as td:
                    store = self.store(td)
                    ref = prepare(store, self.caller, 't0', ok, ok)
                    self.observe(store, 't0', 'accepted', 'req0', 'host0')
                    body = self.result_for(ref['path'])
                    body['status'] = result_status
                    raw = b'{}' if result_status == 'malformed' else json.dumps(body).encode()
                    ingest = lambda: record_result(store, self.caller, 't0', {'request_id': 'req0', 'completion_id': 'req0-done', 'result': raw})
                    if order == 'observation-first':
                        self.observe(store, 't0', 'completion', 'req0', 'host0')
                        ingest()
                    else:
                        ingest()
                        self.observe(store, 't0', 'completion', 'req0', 'host0')
                    self.observe(store, 't0', 'reconciled', 'req0', 'host0')  # a re-presented terminal observation
                    self.assertEqual(self.task(store, 't0')['status'], task_status)
                    # A needs-followup result funds one declared follow-up; every other non-acceptance
                    # status must refuse preparation instead of a synthetic test-only error.
                    if task_status == 'awaiting-followup':
                        prepare_followup(store, self.caller, 't0', 'fu1')
                    elif task_status != 'awaiting-acceptance':
                        self.refused(store, lambda: prepare_followup(store, self.caller, 't0', 'fu1'), 'requires reconciled terminal parent work')


if __name__ == '__main__':
    unittest.main()
