"""Observed host identity and non-accepting continued-review regressions."""
import hashlib
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
    def _valid_result(self, fixture, brief):
        result = fixture.valid_result(); frozen = json.loads(Path(brief['path']).read_text())
        result.update({key: frozen[key] for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256')})
        result['binding'] = frozen['snapshot']; result['revision'] = frozen['revision']
        result['requirements'] = [{'id': x['id'], 'status': 'passed', 'evidence': ['fixture evidence']} for x in frozen['requirements']]
        return json.dumps(result).encode()

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

    def test_observed_aliases_reject_unknown_source_and_empty_target_is_unreported(self):
        self.assertEqual(identity_for({'observed': {'source': 'status', 'providerInstanceId': 'provider-b', 'model': 'model-a'}}, TARGET)['status'], 'mismatched')
        self.assertEqual(identity_for({'observed_identity': {'source': 'thread-configuration', 'model': 'model-a'}}, TARGET)['sources']['configuration']['model'], 'model-a')
        with self.assertRaises(KeyError):
            identity_for({'observed': {'source': 'mystery', 'providerInstanceId': 'provider-a'}}, TARGET)
        for target in ({}, None):
            self.assertEqual(identity_for({'receipt_identity': {}}, target)['status'], 'unreported')

    def test_mismatch_survives_reconciliation_but_verified_charged_retry_can_pass(self):
        fixture = job_fixture(); job = fixture.base_job('identity-mismatch')
        job['tasks'][0]['target'] = TARGET
        job['pins']['ape']['effective_workers'] = {'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}}
        with tempfile.TemporaryDirectory() as td:
            create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
            brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            task = store.load()['tasks'][0]
            self.assertEqual(task['handles'][0]['observed_identity']['status'], 'mismatched')
            self.assertEqual(task['handles'][0]['task_id'], 'host0')
            record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original', 'result': self._valid_result(fixture, brief)})
            record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])
            retry_task(store, caller, 't0', 'replace mismatched execution')
            brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
            request = store.load()['tasks'][0]['request_id']
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': request, 'host_task_id': 'host1',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False,
                'status_identity': STATUS})
            record_result(store, caller, 't0', {'request_id': request, 'completion_id': 'done-retry', 'result': self._valid_result(fixture, brief)})
            record_dispatch(store, caller, 't0', {'kind': 'completion', 'request_id': request, 'host_task_id': 'host1', 'completion_id': 'notify-retry',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
            self.assertEqual(store.load()['tasks'][0]['status'], 'awaiting-acceptance', store.load()['tasks'][0]['execution_history'][-1])
            _check_slots(store, store.load(), store.load()['stages'][0])

    def test_same_pass_followups_cannot_clear_mismatch(self):
        for observed in ({}, {'status_identity': STATUS}):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as td:
                fixture = job_fixture(); job = fixture.base_job('followup-mismatch')
                job['tasks'][0]['target'] = TARGET
                job['pins']['ape']['effective_workers'] = {'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}}
                create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
                brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
                record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
                    'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
                record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original', 'result': self._valid_result(fixture, brief)})
                record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
                    'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
                followup = prepare_followup(store, caller, 't0', 'followup-req')
                record_dispatch(store, caller, 't0', {'kind': 'followup', 'request_id': 'followup-req', 'host_task_id': 'host-f',
                    'parent_host_task_id': 'host0', 'target': TARGET, 'scope': job['tasks'][0]['write_scope'], **observed})
                record_result(store, caller, 't0', {'request_id': 'followup-req', 'completion_id': 'done-followup', 'result': self._valid_result(fixture, followup)})
                record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'followup-req', 'host_task_id': 'host-f',
                    'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
                blockers = [b for b in store.load()['blockers'] if b['kind'] == 'identity-mismatch']
                self.assertEqual(blockers[0]['cycle'], 0)
                with self.assertRaisesRegex(AcceptanceError, 'identity mismatch'):
                    _check_slots(store, store.load(), store.load()['stages'][0])

    def test_charged_retry_with_mismatched_identity_stays_refused(self):
        fixture = job_fixture(); job = fixture.base_job('mismatched-retry'); job['tasks'][0]['target'] = TARGET
        job['pins']['ape']['effective_workers'] = {'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}}
        with tempfile.TemporaryDirectory() as td:
            create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
            brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original', 'result': self._valid_result(fixture, brief)})
            record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
            retry_task(store, caller, 't0', 'retry with mismatched identity')
            brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
            request = store.load()['tasks'][0]['request_id']
            record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': request, 'host_task_id': 'host1',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            record_result(store, caller, 't0', {'request_id': request, 'completion_id': 'done-retry', 'result': self._valid_result(fixture, brief)})
            record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': request, 'host_task_id': 'host1',
                'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])

    def _verified_retry_after_unreported_original(self, td, name):
        fixture = job_fixture(); job = fixture.base_job(name); job['tasks'][0]['target'] = TARGET
        job['pins']['ape']['effective_workers'] = {'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}}
        create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
        brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
        record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0'})
        record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original', 'result': self._valid_result(fixture, brief)})
        record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
        retry_task(store, caller, 't0', 'replace unreported execution')
        brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
        request = store.load()['tasks'][0]['request_id']
        record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': request, 'host_task_id': 'host1',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False, 'status_identity': STATUS})
        record_result(store, caller, 't0', {'request_id': request, 'completion_id': 'done-retry', 'result': self._valid_result(fixture, brief)})
        record_dispatch(store, caller, 't0', {'kind': 'completion', 'request_id': request, 'host_task_id': 'host1', 'completion_id': 'notify-retry',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
        _check_slots(store, store.load(), store.load()['stages'][0])
        return store, caller, request

    def test_late_mismatch_on_retired_handle_keeps_verified_retry(self):
        # Issue #54: the blocker carries the retired execution's cycle, so the verified current pass stays acceptable.
        with tempfile.TemporaryDirectory() as td:
            store, caller, _ = self._verified_retry_after_unreported_original(td, 'late-retired-mismatch')
            record_dispatch(store, caller, 't0', {'kind': 'identity', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            job = store.load(); _check_slots(store, job, job['stages'][0])
            blockers = [b for b in job['blockers'] if b['kind'] == 'identity-mismatch']
            self.assertEqual([(b['request_id'], b['cycle']) for b in blockers], [('req0', 0)])
            self.assertEqual(([h['cycle'] for h in job['tasks'][0]['handles']], job['tasks'][0]['cycle']), ([0, 1], 1))

    def test_late_mismatch_on_current_handle_still_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            store, caller, request = self._verified_retry_after_unreported_original(td, 'late-current-mismatch')
            record_dispatch(store, caller, 't0', {'kind': 'identity', 'request_id': request, 'host_task_id': 'host1',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            self.assertEqual([b['cycle'] for b in store.load()['blockers'] if b['kind'] == 'identity-mismatch'], [1])
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])

    def _mismatched_execution(self, td, name, policy=None, **task):
        fixture = job_fixture(); job = fixture.base_job(name); job['tasks'][0].update(target=TARGET, **task)
        job['policy'].update(policy or {})
        job['pins']['ape']['effective_workers'] = {'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}}
        create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
        brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
        record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0',
            'status_identity': STATUS, 'receipt_identity': {'providerInstanceId': 'provider-a', 'model': 'model-b'}})
        record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original', 'result': self._valid_result(fixture, brief)})
        record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
        return store, caller

    def _identity_exception(self, store, caller, owner_dir, decision_id='exception-0', **change):
        from core.jobs import decision
        from shared.job_acceptance import identity_exception_binding
        source = Path(owner_dir) / (decision_id + '.txt'); source.write_text('Selected option: accept the reported identity\n')
        task = store.load()['tasks'][0]
        decision(store, caller, {'id': decision_id, 'quote': 'accept the reported identity', 'source': str(source),
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'scope': 'identity-exception:task:t0',
            'binding': {**identity_exception_binding(task, task['handles'][0]), **change}})
        return source

    def test_exact_owner_identity_exception_accepts_the_mismatched_execution_without_relabelling_it(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as owner:
            store, caller = self._mismatched_execution(td, 'identity-exception')
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])
            self._identity_exception(store, caller, owner)
            job = store.load(); _check_slots(store, job, job['stages'][0])
            self.assertEqual(job['tasks'][0]['handles'][0]['observed_identity']['status'], 'mismatched')
            self.assertEqual([(b['request_id'], b['cycle']) for b in job['blockers'] if b['kind'] == 'identity-mismatch'], [('req0', 0)])
            # A repeated reading of the same sources keeps the binding; a new reading voids the exception.
            record_dispatch(store, caller, 't0', {'kind': 'identity', 'request_id': 'req0', 'host_task_id': 'host0',
                'receipt_identity': {'providerInstanceId': 'provider-a', 'model': 'model-b'}})
            _check_slots(store, store.load(), store.load()['stages'][0])
            record_dispatch(store, caller, 't0', {'kind': 'identity', 'request_id': 'req0', 'host_task_id': 'host0',
                'configuration_identity': {'providerInstanceId': 'provider-a', 'model': 'model-c'}})
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])

    def test_identity_exception_for_another_execution_scope_or_changed_source_covers_nothing(self):
        cases = {'request': {'request_id': 'req1'}, 'host': {'host_task_id': 'host9'},
                 'target': {'target': {'providerInstanceId': 'provider-a', 'model': 'model-b'}},
                 'readings': {'observed_identity_sha256': '0' * 64}}
        for name, change in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as owner:
                store, caller = self._mismatched_execution(td, 'exception-' + name)
                self._identity_exception(store, caller, owner, **change)
                with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                    _check_slots(store, store.load(), store.load()['stages'][0])
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as owner:
            store, caller = self._mismatched_execution(td, 'exception-scope')
            from core.jobs import decision
            from shared.job_acceptance import identity_exception_binding
            source = Path(owner) / 'waiver.txt'; source.write_text('accept the reported identity\n'); task = store.load()['tasks'][0]
            decision(store, caller, {'id': 'other-scope', 'quote': 'accept the reported identity', 'source': str(source),
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'scope': 'lineage-waiver:task:t0',
                'binding': identity_exception_binding(task, task['handles'][0])})
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as owner:
            store, caller = self._mismatched_execution(td, 'exception-source')
            source = self._identity_exception(store, caller, owner)
            source.write_text('Selected option: keep it held\n')
            with self.assertRaisesRegex(AcceptanceError, 'sticky observed host identity mismatch'):
                _check_slots(store, store.load(), store.load()['stages'][0])

    def test_identity_exception_never_covers_review_or_author_independent_slots(self):
        cases = {'review': ({}, {'role': 'review'}), 'review-required': ({}, {'review_required': True}),
                 'independent': ({}, {'independent_of_author': True}), 'policy': ({'author_independence': True}, {}),
                 'observed-review': ({'identity': 'observed'}, {'role': 'review'})}
        for name, (policy, task) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as owner:
                store, caller = self._mismatched_execution(td, 'exception-' + name, policy, **task)
                self._identity_exception(store, caller, owner)
                with self.assertRaisesRegex(AcceptanceError, 'identity'):
                    _check_slots(store, store.load(), store.load()['stages'][0])

    def test_legacy_handle_without_cycle_falls_back_to_task_cycle(self):
        # Ledgers written before handles carried a cycle keep loading and keep the conservative refusal.
        with tempfile.TemporaryDirectory() as td:
            store, caller, _ = self._verified_retry_after_unreported_original(td, 'legacy-handle-cycle')
            store.mutate(caller, lambda job: [handle.pop('cycle', None) for handle in job['tasks'][0]['handles']] and None)
            record_dispatch(store, caller, 't0', {'kind': 'identity', 'request_id': 'req0', 'host_task_id': 'host0',
                'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
            self.assertEqual([b['cycle'] for b in store.load()['blockers'] if b['kind'] == 'identity-mismatch'], [1])
            with self.assertRaisesRegex(AcceptanceError, 'mismatch is a sticky blocker'):
                _check_slots(store, store.load(), store.load()['stages'][0])

    def _late_forbidden_mismatch(self, td, name, parent_host, legacy=False):
        # A document-only slot passes a verified retry, then a mismatched forbidden continuation of parent_host is observed.
        fixture = job_fixture(); job = fixture.base_job(name); document = Path(td) / 'document.md'; document.write_text('# Supplied document\n')
        job['tasks'][0].update(context_policy='document-only', target=TARGET,
                               document={'path': str(document), 'sha256': hashlib.sha256(document.read_bytes()).hexdigest()})
        job['pins']['ape'].update(bundle_digest='b' * 64, effective_workers={'ape/source-researcher': {'bytes': 'synthetic worker', 'sha256': 'b' * 64}})
        create_job(job, td, job['pins']); store = Store(td, job['job_id']); caller = fixture.caller()
        brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
        record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': 'req0', 'host_task_id': 'host0'})
        record_result(store, caller, 't0', {'request_id': 'req0', 'completion_id': 'done-original', 'result': self._valid_result(fixture, brief)})
        record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
        retry_task(store, caller, 't0', 'replace unreported execution')
        brief = prepare(store, caller, 't0', lambda *_: True, lambda *_: True)
        request = store.load()['tasks'][0]['request_id']
        record_dispatch(store, caller, 't0', {'kind': 'accepted', 'request_id': request, 'host_task_id': 'host1',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False, 'status_identity': STATUS})
        record_result(store, caller, 't0', {'request_id': request, 'completion_id': 'done-retry', 'result': self._valid_result(fixture, brief)})
        record_dispatch(store, caller, 't0', {'kind': 'completion', 'request_id': request, 'host_task_id': 'host1', 'completion_id': 'notify-retry',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
        _check_slots(store, store.load(), store.load()['stages'][0])
        if legacy:
            store.mutate(caller, lambda job: [handle.pop('cycle', None) for handle in job['tasks'][0]['handles']] and None)
        record_observation(store, caller, 't0', {'kind': 'followup', 'request_id': 'req-forbidden', 'host_task_id': 'host-f',
            'parent_host_task_id': parent_host, 'target': TARGET, 'scope': job['tasks'][0]['write_scope'],
            'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}})
        record_result(store, caller, 't0', {'request_id': 'req-forbidden', 'completion_id': 'done-f', 'result': b'{"review_verdict":"approve"}'})
        record_dispatch(store, caller, 't0', {'kind': 'reconciled', 'request_id': 'req-forbidden', 'host_task_id': 'host-f',
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False})
        job = store.load()
        return store, job, [b['cycle'] for b in job['blockers'] if b['kind'] == 'identity-mismatch']

    def test_late_forbidden_continuation_of_retired_parent_keeps_verified_retry(self):
        with tempfile.TemporaryDirectory() as td:
            store, job, cycles = self._late_forbidden_mismatch(td, 'late-forbidden-retired', 'host0')
            self.assertEqual((cycles, job['tasks'][0]['followups'][0]['cycle']), ([0], 0))
            _check_slots(store, job, job['stages'][0])

    def test_forbidden_continuation_of_current_or_legacy_parent_still_refuses(self):
        for parent, legacy in (('host1', False), ('host0', True)):
            with self.subTest(parent=parent, legacy=legacy), tempfile.TemporaryDirectory() as td:
                store, job, cycles = self._late_forbidden_mismatch(td, 'late-forbidden-' + parent, parent, legacy)
                self.assertEqual(cycles, [1])
                with self.assertRaisesRegex(AcceptanceError, 'identity mismatch'):
                    _check_slots(store, job, job['stages'][0])

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

    def test_mismatch_is_sticky_and_completion_without_identity_keeps_receipt(self):
        identity = identity_for({'status_identity': {'providerInstanceId': 'provider-b', 'model': 'model-a'}}, TARGET)
        handle = {'task_id': 'h', 'request_id': 'r', 'target': TARGET, 'observed_identity': identity}
        from core.jobs import _record_identity
        _record_identity({'blockers': []}, {'task_id': 't', 'target': TARGET}, handle,
                         {'status_identity': STATUS})
        self.assertEqual(handle['observed_identity']['status'], 'mismatched')
        handle = {'task_id': 'h', 'request_id': 'r', 'target': TARGET}
        _record_identity({'blockers': []}, {'task_id': 't', 'target': TARGET}, handle,
                         {'receipt_identity': {'model': 'model-a'}})
        _record_identity({'blockers': []}, {'task_id': 't', 'target': TARGET}, handle, {})
        self.assertEqual(handle['observed_identity']['sources']['receipt']['model'], 'model-a')
