"""Observed host identity and non-accepting continued-review regressions."""
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs import JobError, cancel, create_job, prepare, record_dispatch, record_result, retry_task
from core.jobs.store import Store
from shared.job_coordinator import prepare_followup
from shared.job_acceptance import AcceptanceError, _check_slots
from shared.job_acceptance import _pending
from shared.job_coordinator import record_observation

def job_fixture():
    # Import lazily so unittest does not collect the fixture class as this module's tests.
    from tests.test_jobs_review import JobReviewTests
    return JobReviewTests()


STATUS = {'providerInstanceId': 'provider-a', 'model': 'model-a'}
TARGET = {'providerInstanceId': 'provider-a', 'model': 'model-a'}

def identity_for(event, target):
    from core.jobs import _record_identity
    task = {'task_id': 'fixture-task', 'target': target}
    handle = {'task_id': 'fixture-host', 'request_id': 'fixture-request', 'target': target}
    _record_identity({'blockers': []}, task, handle, event)
    return handle['observed_identity']


class ObservedIdentityTests(unittest.TestCase):
    def test_identity_uses_status_then_receipt_then_configuration_model(self):
        self.assertEqual(identity_for({'status_identity': STATUS}, TARGET)['status'], 'verified')
        self.assertEqual(identity_for({'status_identity': {**STATUS, 'model': None},
                                           'receipt_identity': {'model': 'model-a'}}, TARGET)['status'], 'verified')
        self.assertEqual(identity_for({'status_identity': {**STATUS, 'model': None},
                                           'receipt_identity': {'model': None},
                                           'configuration_identity': {'model': 'model-a'}}, TARGET)['status'], 'verified')

    def test_receipt_only_configuration_only_and_missing_model_are_unreported(self):
        for event in ({'receipt_identity': STATUS}, {'configuration_identity': STATUS},
                      {'status_identity': {'providerInstanceId': 'provider-a', 'model': None}}):
            with self.subTest(event=event):
                self.assertEqual(identity_for(event, TARGET)['status'], 'unreported')

    def test_provider_mismatch_is_retained_and_reconciled_without_losing_blocker(self):
        fixture = job_fixture(); job = fixture.base_job('identity-mismatch')
        job['tasks'][0]['target'] = TARGET
        with tempfile.TemporaryDirectory() as td:
            create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            task = store.load()['tasks'][0]
            self.assertEqual(task['handles'][0]['observed_identity']['status'], 'mismatched')
            self.assertEqual(task['handles'][0]['task_id'], 'host0')
            record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
            self.assertTrue(any(b['kind'] == 'identity-mismatch' and b['reconciled'] for b in store.load()['blockers']))

    def test_nonterminal_reconciliation_cannot_clear_obligation(self):
        fixture = job_fixture(); job = fixture.base_job('nonterminal-reconcile'); job['tasks'][0]['target'] = TARGET
        with tempfile.TemporaryDirectory() as td:
            create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
                'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False})
            self.assertFalse(next(b for b in store.load()['blockers'] if b['kind'] == 'identity-mismatch').get('reconciled'))

    def test_followup_observation_is_checked_against_its_own_target(self):
        # The per-execution target is passed to the identity matcher, including for a follow-up.
        self.assertEqual(identity_for({'status_identity': STATUS}, dict(TARGET, model='model-b'))['status'], 'mismatched')

    def test_followup_prepare_refuses_review_and_document_only_slots(self):
        fixture = job_fixture()
        for role, context in (('review', None), ('worker', 'document-only')):
            with self.subTest(role=role, context=context), tempfile.TemporaryDirectory() as td:
                job = fixture.base_job('forbidden-' + role + str(bool(context)))
                job['tasks'][0]['role'] = role
                if context:
                    job['tasks'][0]['context_policy'] = context
                create_job(job, td, job['pins']); store = Store(td, job['job_id'])
                with self.assertRaisesRegex(JobError, 'review rounds|document-only'):
                    prepare_followup(store, fixture.caller(), 't0', 'req-follow')

    def test_unprepared_forbidden_followup_is_quarantined_reconciled_and_retryable(self):
        fixture = job_fixture(); job = fixture.base_job('quarantine-review')
        job['tasks'][0].update(role='review', target=TARGET)
        job['pins']['ape']['effective_workers'] = {'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}}
        with tempfile.TemporaryDirectory() as td:
            create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
            brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': STATUS})
            original = fixture.valid_result(); frozen = json.loads(Path(brief['path']).read_text())
            original.update({key: frozen[key] for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id',
                            'worker_id', 'effective_brief_sha256')})
            original['binding'] = frozen['snapshot']
            record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original',
                                                'result': json.dumps(original).encode()})
            record_dispatch(store, caller, 't0', {'kind': 'completion', 'request_id': 'req0', 'host_task_id': 'host0',
                'completion_id': 'done0', 'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False,
                'status_identity': STATUS})
            event = {'kind': 'followup', 'request_id': 'req-forbidden', 'host_task_id': 'host-f',
                     'parent_host_task_id': 'host0', 'target': TARGET,
                     'scope': job['tasks'][0]['write_scope'], 'status_identity': STATUS}
            record_observation(store, caller, 't0', event)
            task = store.load()['tasks'][0]
            self.assertTrue(task['followups'][0]['forbidden_followup'])
            result = {'request_id': 'req-forbidden', 'completion_id': 'done-f', 'result': b'{"review_verdict":"approve"}'}
            record_result(store, caller, 't0', result)
            quarantine = store.path / 'results' / 'quarantine' / 'req-forbidden.json'
            self.assertTrue(quarantine.is_file())
            self.assertFalse(any(x.get('request_id') == 'req-forbidden' and x.get('accepted_execution') for x in store.load()['tasks'][0]['execution_history']))
            record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req-forbidden', 'host_task_id': 'host-f',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
            self.assertFalse(_pending(store.load(), store.load()['stages'][0]))
            retry_task(store, caller, 't0', 'discard forbidden continuation', 'review')
            self.assertEqual(store.load()['tasks'][0]['status'], 'pending')
            with self.assertRaises(AcceptanceError):
                _check_slots(store, store.load(), store.load()['stages'][0])

    def test_cancelled_job_retains_observed_forbidden_continuations(self):
        fixture = job_fixture()
        for role, context in (('review', None), ('worker', 'document-only')):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as td:
                job = fixture.base_job('cancelled-forbidden-' + role)
                job['tasks'][0].update(role=role, target=TARGET)
                if context:
                    job['tasks'][0]['context_policy'] = context
                create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
                record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0'})
                record_dispatch(store, caller, 't0', {'kind': 'completion', 'request_id': 'req0', 'host_task_id': 'host0',
                    'completion_id': 'done0', 'status': 'completed', 'work_state': 'result_available',
                    'has_pending_child_runs': False})
                cancel(store, caller, 'fixture cancellation')
                event = {'kind': 'followup', 'request_id': 'req-forbidden', 'host_task_id': 'host-f',
                         'parent_host_task_id': 'host0', 'target': TARGET,
                         'scope': job['tasks'][0]['write_scope'], 'status_identity': STATUS}
                record_observation(store, caller, 't0', event)
                self.assertTrue(store.load()['tasks'][0]['followups'][0]['forbidden_followup'])

    def test_redelivered_completion_ignores_its_observed_identity(self):
        fixture = job_fixture(); job = fixture.base_job('completion-identity')
        job['tasks'][0]['target'] = TARGET
        with tempfile.TemporaryDirectory() as td:
            create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0', 'status_identity': STATUS})
            completion = {'kind': 'completion', 'request_id': 'req0', 'host_task_id': 'host0', 'completion_id': 'done0',
                          'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False,
                          'status_identity': STATUS}
            record_dispatch(store, caller, 't0', completion)
            record_dispatch(store, caller, 't0', {**completion, 'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-z'}})
            observed = store.load()['tasks'][0]['handles'][0]['observed_identity']
            self.assertEqual((observed['providerInstanceId'], observed['model']), ('provider-a', 'model-a'))
