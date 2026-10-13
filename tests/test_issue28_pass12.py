"""Pass 12 regressions for the accepted pass 11 Stage 3 findings; synthetic data only, no live models."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import shared.job_acceptance as acceptance
from core.jobs import JobError, prepare, record_dispatch, record_result, revise_plan
from core.jobs.store import Store
from shared.job_acceptance import _pending, accept_stage, validate_final, validate_stage
from shared.job_coordinator import (create_pinned_job, prepare_followup, publish_observation, record_observation,
                                    verify_all_pins, verify_pinned_dependency)
from tests.test_issue28_pass10 import Pass10Fixture
from tests import test_jobs_review as review_fixtures
from tests.test_jobs_review import fixture_decision


def ok(*_):
    return True


class Pass12PlanRemovalTests(Pass10Fixture):
    """R11-ST-01: a plan decision is not evidence that owned host work ended or never started."""

    def ready(self, store, request='req0', host='host0'):
        ref = prepare(store, self.caller, 't0', ok, ok)
        self.observe(store, 't0', 'accepted', request, host)
        self.ingest(store, 't0', self.result_for(ref['path']))
        self.observe(store, 't0', 'completion', request, host)
        return ref

    def revise(self, store, revision_id, replace=False):
        """Owner-approved revision removing t0 (direct stage) or replacing it with a new slot."""
        fixture_decision(store, self.caller, {'id': 'd-' + revision_id, 'quote': 'Owner approves revising slot t0',
                                              'scope': 'plan:' + revision_id})
        plan = store.load()
        old = plan['tasks'][0]
        if replace:
            contract = {k: v for k, v in old.items() if k in ('stage_id', 'logical_slot_id', 'worker_id', 'dependency_key',
                                                              'target', 'write_scope', 'requirements', 'max_followups')}
            plan['tasks'] = [{**contract, 'task_id': 't0b', 'request_id': 'req0b',
                              'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/t0b'}}]
        else:
            plan['tasks'] = []
            plan['stages'][0]['execution_mode'] = 'direct'
        return lambda: revise_plan(store, self.caller, {'id': revision_id, 'owner_decision_id': 'd-' + revision_id}, plan)

    def refused(self, store, call, message):
        before = store.file.read_bytes()
        with self.assertRaisesRegex(JobError, message):
            call()
        self.assertEqual(store.file.read_bytes(), before)
        self.assertEqual([t['task_id'] for t in store.load()['tasks']], ['t0'])

    def test_r11_st_01_unreconciled_conflicting_host_blocks_slot_removal_and_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'h1')
            second = {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'h2', 'child_thread_id': 'child-h2',
                      'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False}
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                record_observation(store, self.caller, 't0', second)
            self.observe(store, 't0', 'completion', 'req0', 'h1')
            self.ingest(store, 't0', self.result_for(ref['path']))
            for replace in (False, True):
                with self.subTest(replace=replace):
                    self.refused(store, self.revise(store, 'conflict-' + str(replace), replace), 'conflicting host handle')
            # The job-level blocker alone (task copy already gone) still blocks removal.
            self.edit(store, lambda s: s['tasks'][0].pop('host_conflicts'))
            self.refused(store, self.revise(store, 'blocker-only'), 'conflicting host handle remains unreconciled in job blockers')
            state = store.load()
            state['tasks'][0]['task_id'] = 'gone'
            self.assertTrue(_pending(state, state['stages'][0]))  # an orphaned unreconciled blocker stays pending work

    def test_r11_st_01_uncertain_prepared_followup_blocks_slot_removal_and_contract_change(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            self.ready(store)
            prepare_followup(store, self.caller, 't0', 'req-f')
            record_observation(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'req-f'})
            self.assertEqual(store.load()['tasks'][0]['status'], 'awaiting-acceptance')
            for replace in (False, True):
                with self.subTest(replace=replace):
                    self.refused(store, self.revise(store, 'uncertain-' + str(replace), replace), 'uncertain follow-up dispatch')
            fixture_decision(store, self.caller, {'id': 'd-contract', 'quote': 'Owner approves a contract change', 'scope': 'plan:contract'})
            plan = store.load(); plan['tasks'][0]['max_followups'] = 2
            self.refused(store, lambda: revise_plan(store, self.caller, {'id': 'contract', 'owner_decision_id': 'd-contract'}, plan),
                         'cannot change a live task contract')

    def test_r11_st_01_uncertain_original_dispatch_blocks_slot_removal(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            prepare(store, self.caller, 't0', ok, ok)
            for _ in range(3):
                record_dispatch(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'req0'})
            self.assertEqual(store.load()['tasks'][0]['blocked_reason'], 'uncertain_dispatch')
            self.refused(store, self.revise(store, 'blocked'), 'uncertain or blocked dispatch')

    def test_r11_st_01_terminal_handle_still_working_blocks_slot_removal(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            ref = prepare(store, self.caller, 't0', ok, ok)
            self.observe(store, 't0', 'accepted', 'req0', 'host0')
            self.observe(store, 't0', 'reconciled', 'req0', 'host0', work_state='working')
            self.ingest(store, 't0', self.result_for(ref['path']))
            task = store.load()['tasks'][0]
            self.assertEqual((task['status'], task['handles'][0]['status']), ('awaiting-acceptance', 'completed'))
            for replace in (False, True):
                with self.subTest(replace=replace):
                    self.refused(store, self.revise(store, 'working-' + str(replace), replace), 'result_available')

    def test_r11_st_01_clean_slot_can_still_be_removed_or_replaced(self):
        for replace in (False, True):
            with self.subTest(replace=replace), tempfile.TemporaryDirectory() as td:
                store = self.fx.store(td)
                self.ready(store)
                self.revise(store, 'clean', replace)()
                state = store.load()
                self.assertEqual([t['task_id'] for t in state['tasks']], ['t0b'] if replace else [])
                self.assertEqual(state['history'][-1]['tasks'][0]['task_id'], 't0')


class Pass12ValidationRaceTests(unittest.TestCase):
    """R11-ST-02: validators run against a reserved generation that must survive the run."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.fx = review_fixtures.JobReviewTests()
        cls.version, cls.manifest, cls.prefix, cls.agents, cls.state_root = cls.fx.install(cls.base, 'ape')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def accepted_job(self, job_id):
        """One-stage job whose single slot has a terminal result_available host handle and current acceptance."""
        base = self.base / job_id
        base.mkdir()
        job = self.fx.base_job(job_id)
        job['stages'] = job['stages'][:1]
        job['installation_id'] = self.manifest['installation_id']
        job['pins'] = {}
        source = base / 'source.txt'; source.write_text('fixture source evidence\n')
        pin = {'id': 'src', 'url': 'https://example.invalid/source', 'revision': 'r1', 'path': str(source),
               'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        job['stages'][0]['validator_contract'] = {'sources': [pin]}
        create_pinned_job(job, self.state_root, self.prefix, self.agents, self.base / 'config' / 'workers.json')
        store = Store(self.state_root, job_id)
        caller = {'installation_id': self.manifest['installation_id'], 'workflow': job['workflow'],
                  'package_digest': self.manifest['package_digest'], 'actor': 'coordinator'}
        verify_all_pins(store)
        brief = json.loads(Path(prepare(store, caller, 't0', verify_pinned_dependency, ok)['path']).read_text())
        host = {'request_id': brief['request_id'], 'host_task_id': 'host0', 'child_thread_id': 'child-host0',
                'has_pending_child_runs': False}
        record_dispatch(store, caller, 't0', {**host, 'kind': 'accepted', 'status': 'running', 'work_state': 'working'})
        result = self.fx.valid_result()
        for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision'):
            result[key] = brief[key]
        result['binding'] = brief['snapshot']
        result['requirements'] = [{'id': r['id'], 'status': 'passed', 'evidence': ['fixture']} for r in brief['requirements']]
        record_result(store, caller, 't0', {'result': json.dumps(result).encode(), 'completion_id': 'host0-done',
                                            'request_id': brief['request_id']})
        record_dispatch(store, caller, 't0', {**host, 'kind': 'completion', 'completion_id': 'host0-done',
                                              'status': 'completed', 'work_state': 'result_available'})
        report = base / 'report.json'
        report.write_text(json.dumps({'sources': [pin], 'findings': [], 'criteria': [{'id': 'C1', 'kind': 'source-provenance'}]}))
        report = Path(publish_observation(store, caller, 's0', str(report))['path'])
        argv = [str(self.version / 'scripts' / 'validate_report.py'), '--input', str(report)]
        self.assertTrue(accept_stage(store, caller, 's0', argv, str(report), 's0-r1')['accepted'])
        self.assertTrue(validate_stage(store, 's0')['accepted'])  # positive control
        return store, caller, argv, report, host

    def during_invoke(self, call_number, change):
        """Patch _invoke so that `change` lands while the given validator invocation is running."""
        original = acceptance._invoke
        calls = []
        def invoke(*args, **kwargs):
            calls.append(1)
            outcome = original(*args, **kwargs)
            if len(calls) == call_number:
                change()
            return outcome
        return mock.patch.object(acceptance, '_invoke', side_effect=invoke), calls

    def running(self, store, caller, host):
        return lambda: record_dispatch(store, caller, 't0', {**host, 'kind': 'reconciled', 'status': 'running', 'work_state': 'working'})

    def tighten(self, store, caller):
        def change():
            plan = store.load(); plan['constraints'] = plan['constraints'] + ['no new network access']
            revise_plan(store, caller, {'id': 'tighten'}, plan)
        return change

    def test_r11_st_02_validate_stage_rejects_owned_host_running_after_its_validator(self):
        store, caller, argv, report, host = self.accepted_job('race-stage')
        patch, calls = self.during_invoke(1, self.running(store, caller, host))
        with patch:
            outcome = validate_stage(store, 's0')
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.load()['tasks'][0]['status'], 'running')
        self.assertFalse(outcome['accepted'], outcome)

    def test_r11_st_02_validate_final_rejects_owned_host_running_during_integrated_validator(self):
        store, caller, argv, report, host = self.accepted_job('race-final')
        positive = validate_final(store, caller, {'s0': argv}, {'s0': str(report)})
        self.assertTrue(positive['accepted'], positive)  # positive control
        patch, calls = self.during_invoke(2, self.running(store, caller, host))
        with patch:
            outcome = validate_final(store, caller, {'s0': argv}, {'s0': str(report)})
        state = store.load()
        self.assertEqual((len(calls), state['tasks'][0]['status']), (2, 'running'))
        self.assertFalse(outcome['accepted'], outcome)
        self.assertEqual(state['final_passes'], 2)  # each pass charged exactly once
        self.assertEqual((state['history'][-1]['kind'], state['history'][-1]['final_pass']), ('final-failure', 2))

    def test_r11_st_02_validate_final_rejects_owned_host_running_during_stage_recheck(self):
        store, caller, argv, report, host = self.accepted_job('race-final-stage')
        patch, calls = self.during_invoke(1, self.running(store, caller, host))
        with patch:
            outcome = validate_final(store, caller, {'s0': argv}, {'s0': str(report)})
        self.assertFalse(outcome['accepted'], outcome)
        self.assertEqual(store.load()['final_passes'], 1)

    def test_r11_st_02_concurrent_plan_revision_invalidates_stage_and_final_validation(self):
        store, caller, argv, report, _ = self.accepted_job('race-plan-final')
        patch, _ = self.during_invoke(2, self.tighten(store, caller))
        with patch:
            outcome = validate_final(store, caller, {'s0': argv}, {'s0': str(report)})
        self.assertFalse(outcome['accepted'], outcome)
        self.assertEqual(store.load()['final_passes'], 1)
        store, caller, argv, report, _ = self.accepted_job('race-plan-stage')
        patch, _ = self.during_invoke(1, self.tighten(store, caller))
        with patch:
            self.assertFalse(validate_stage(store, 's0')['accepted'])


if __name__ == '__main__':
    unittest.main()
