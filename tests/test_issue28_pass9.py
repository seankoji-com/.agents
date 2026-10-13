"""Pass 9 regressions for the confirmed pass 8 findings; synthetic data only, no live models."""
import tempfile
import unittest
from pathlib import Path

from core.jobs import prepare, record_dispatch, retry_task, revise_plan, JobError
from core.jobs.store import _atomic, canonical
from shared.job_acceptance import _check_slots, _stale, AcceptanceError
from tests import test_jobs_review_r3 as job_fixtures
from tests.test_issue28_pass8 import Pass8JobsTests
from tests.test_bench_v2 import model_policy
from tests.test_bench_container import host_observations

TARGET = {'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-0', 'options': {'thinking': False}}


class Pass9JobsTests(unittest.TestCase):
    def setUp(self):
        self.fx = job_fixtures.Stage3Repair5Tests(); self.fx.setUp()

    def test_s3_8_01_invalidation_cannot_reset_uncertain_dispatches(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td)
            prepare(store, self.fx.caller(), 't0', lambda *_: True, lambda *_: True)
            for _ in range(2):
                record_dispatch(store, self.fx.caller(), 't0', {'kind': 'uncertain', 'request_id': 'req0'})
            state = store.load(); _stale(state, 's0'); _atomic(store.file, canonical(state))
            before = store.file.read_bytes()
            with self.assertRaisesRegex(JobError, 'reconciled before retry'):
                retry_task(store, self.fx.caller(), 't0', 'replacement without authoritative absence')
            self.assertEqual(store.file.read_bytes(), before)
            self.assertEqual(store.load()['tasks'][0]['uncertain_calls'], 2)

    def test_s3_8_02_worker_cannot_approve_its_own_required_review(self):
        for verdict, message in ((None, 'independent review task IDs are absent'),
                                 ('approve', 'lacks a current ready result')):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as td:
                helper = Pass8JobsTests(); helper.setUp(); store = helper.fx.store(td)
                state = store.load(); state['tasks'][0]['review_required'] = True
                _atomic(store.file, canonical(state))
                result = helper.prepared(store); result['review_verdict'] = verdict
                helper.ingest(store, result)
                task = store.load()['tasks'][0]
                if verdict == 'approve':
                    self.assertEqual(task['execution_history'][-1]['reason'],
                                     'approval requires a declared independent review slot')
                state = store.load()
                with self.assertRaisesRegex(AcceptanceError, message):
                    _check_slots(store, state, state['stages'][0])

    def test_s3_8_03_stage_controls_need_owner_decision(self):
        changes = {'stop_conditions': ['a new arbitrary condition'], 'resources': {'cpu': 'unbounded'},
                   'validator_dependency': 'another-package'}
        for key, value in changes.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as td:
                store = self.fx.store(td); before = store.file.read_bytes()
                plan = store.load(); plan['stages'][0][key] = value
                with self.assertRaisesRegex(JobError, 'owner decision required'):
                    revise_plan(store, self.fx.caller(), {'id': 'change-' + key}, plan)
                self.assertEqual(store.file.read_bytes(), before)


class Pass9PolicyTests(unittest.TestCase):
    def test_b_8_05_and_c_8_10_integer_zero_is_not_boolean_false(self):
        catalog = {'providers': [{'providerInstanceId': 'claudeAgent', 'canRunChildTask': True,
                                  'models': [{'id': 'claude-haiku-0', 'options': [{'id': 'thinking', 'type': 'boolean'}]}]}]}
        with self.assertRaises(ValueError):
            model_policy.validate_target(catalog, dict(TARGET, options={'thinking': 0}))
        selection = {'instanceId': 'claudeAgent', 'model': 'claude-haiku-0', 'options': [{'id': 'thinking', 'value': 0}]}
        self.assertFalse(host_observations.selection_matches(selection, TARGET))
        selection['options'][0]['value'] = False
        self.assertTrue(host_observations.selection_matches(selection, TARGET))

    def test_c_8_05_null_native_result_fails_closed_without_crashing(self):
        native = {'origin': 'provider_native', 'threadId': 'p', 'id': 'native', 'prompt': 'ISSUE28_NATIVE_PROBE',
                  'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-0', 'childThreadId': 'c',
                  'status': 'completed', 'completedAt': 'synthetic', 'result': None}
        observations = {'parent_thread_id': 'p', 'tool_records': [], 'subagents': [native],
                        'threads': [{'id': 'c', 'modelSelection': {'instanceId': 'claudeAgent', 'model': 'claude-haiku-0',
                                                                    'options': [{'id': 'thinking', 'value': False}]}}]}
        outcome = host_observations.verify_owned_tasks(observations, [], TARGET, True, 'a' * 64)
        self.assertFalse(outcome['verified'])
        self.assertFalse(outcome['native_probe_checks']['native_hash_result'])
        self.assertTrue(outcome['native_child_visibility'].startswith('unverified'))


if __name__ == '__main__':
    unittest.main()
