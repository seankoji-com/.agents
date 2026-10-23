"""Offline behavior checks for bounded resumes, admission and coordination metrics."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core.jobs import create_job, revise_plan
from shared.job_coordinator import record_observation as record_dispatch
from shared.job_coordination import COMPACT_MAX_BYTES, admission, coordination_metrics, occupancy, overview
from core.jobs.store import JobError, Store, canonical


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_jobs_review import JobReviewTests
        self.fixture = JobReviewTests()

    def job(self, count=3):
        job = self.fixture.base_job('coordination')
        job['policy']['max_live_workers'] = None
        task = job['tasks'][0]
        job['tasks'] = [{**copy.deepcopy(task), 'task_id': f't{i}', 'request_id': f'req{i}',
                         'logical_slot_id': f'slot{i}', 'write_scope': {'mode': 'coordinator-only'},
                         'target': {'providerInstanceId': 'fixture-a' if i < 2 else 'fixture-b', 'model': 'fixture-model'}}
                        for i in range(count)]
        job['pins']['ape']['effective_workers'] = {
            'ape/source-researcher': {'bytes': 'fixture worker', 'sha256': 'b' * 64}}
        return job

    def store(self, directory, job):
        from shared.job_coordination import freeze_provider_limits
        freeze_provider_limits(job, job['pins'])
        create_job(job, directory, job['pins'])
        return Store(directory, job['job_id'])

    def prepare(self, store, task='t0'):
        from shared.job_coordinator import prepare_task
        return prepare_task(store, self.fixture.caller(), task, lambda *_: True, lambda *_: True)

    def event(self, store, task, kind, **fields):
        return record_dispatch(store, self.fixture.caller(), task,
                               {'kind': kind, 'request_id': 'req' + task[1:], **fields})

    def test_compact_is_bounded_paginated_and_read_only(self):
        job = self.job(140)
        job['decisions'] = [{'id': 'owner', 'quote': 'private long history ' * 10000}]
        job['blockers'] = [{'kind': 'fixture-blocker', 'reason': 'long reason ' * 20000}]
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            before = store.file.read_bytes()
            page = overview(store,compact=True, limit=100)
            seen = []
            while True:
                self.assertLessEqual(len(canonical(page)) + 1, COMPACT_MAX_BYTES)
                self.assertNotIn('private long history', canonical(page).decode())
                self.assertNotIn('long reason ' * 20000, canonical(page).decode())
                seen.extend(page['records'])
                if not page['next_cursor']:
                    break
                page = overview(store,compact=True, cursor=page['next_cursor'], limit=100)
            self.assertEqual(len(seen), page['total_records'])
            self.assertTrue(any(row.get('task_id') == 't139' for row in seen))
            self.assertNotIn('private long history', canonical(page).decode())
            self.assertEqual(store.file.read_bytes(), before)
            self.assertEqual(len(overview(store,)['handles']), 140)
            small = self.job(1); small['job_id'] = 'single-page'
            small['decisions'] = job['decisions']; small['blockers'] = job['blockers']
            single = overview(self.store(directory, small), compact=True)
            self.assertIsNone(single['next_cursor'])
            self.assertLessEqual(len(canonical(single)) + 1, COMPACT_MAX_BYTES)
            self.assertNotIn('private long history', canonical(single).decode())
            self.assertNotIn('long reason ' * 20000, canonical(single).decode())

    def test_since_and_cursor_detect_changed_inputs_and_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, self.job())
            page = overview(store,compact=True, limit=1)
            same = overview(store,compact=True, since=page['view_sha256'])
            self.assertFalse(same['changed'])
            self.assertLess(len(canonical(same)), 256)
            store.mutate(self.fixture.caller(), lambda job: job['tasks'][0]['target'].update(model='changed-model'))
            self.assertTrue(overview(store,compact=True, since=page['view_sha256'])['changed'])
            with self.assertRaisesRegex(JobError, 'stale.*cursor'):
                overview(store,compact=True, cursor=page['next_cursor'])
            for kwargs in ({'since': 'bad'}, {'limit': 0}, {'limit': 101}):
                with self.assertRaises(JobError):
                    overview(store,compact=True, **kwargs)

    def test_provider_cap_reserves_preparations_but_does_not_block_other_providers(self):
        job = self.job()
        job['policy']['max_live_workers_by_provider'] = {'fixture-a': 1}
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            first = self.prepare(store)
            self.assertEqual(first, self.prepare(store))
            with self.assertRaisesRegex(JobError, 'provider_worker_limit'):
                self.prepare(store, 't1')
            self.prepare(store, 't2')
            self.assertEqual(len(occupancy(store.load())), 2)
            by_task = {row['task_id']: row for row in admission(store.load())['tasks']}
            self.assertFalse(by_task['t1']['eligible'])
            self.assertEqual(by_task['t1']['reason'], 'provider_worker_limit')

    def test_core_create_inherits_consistent_provider_pins_without_adapter(self):
        job = self.job()
        caps = {'fixture-a': 1}
        job['pins']['ape']['limits'] = {'max_live_workers_by_provider': caps}
        job['pins']['second'] = copy.deepcopy(job['pins']['ape'])
        job['dependencies'].append({'key': 'second', 'plugin': 'ape'})
        original = copy.deepcopy(job)
        with tempfile.TemporaryDirectory() as directory:
            # Exercise the public core API without freeze_provider_limits.
            create_job(job, directory, job['pins'])
            store = Store(directory, job['job_id'])
            self.prepare(store)
            with self.assertRaisesRegex(JobError, 'provider_worker_limit'):
                self.prepare(store, 't1')
            self.assertEqual(store.load()['policy'].get('max_live_workers_by_provider'), caps)
            self.prepare(store, 't2')
            store.mutate(self.fixture.caller(), lambda j:
                         j['policy']['max_live_workers_by_provider'].update({'fixture-b': 1}))
            self.assertEqual(store.load()['pins']['ape']['limits']['max_live_workers_by_provider'], caps)
            self.assertEqual(job, original)

    def test_core_create_preserves_explicit_provider_policy_and_validates_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.job()
            job['pins']['ape']['limits'] = {'max_live_workers_by_provider': {'fixture-a': 1}}
            job['pins']['second'] = {**copy.deepcopy(job['pins']['ape']),
                                     'limits': {'max_live_workers_by_provider': {'fixture-a': 2}}}
            job['dependencies'].append({'key': 'second', 'plugin': 'ape'})
            with self.assertRaisesRegex(JobError, 'conflicting pin limits'):
                create_job(job, directory, job['pins'])
            job['policy']['max_live_workers_by_provider'] = {}
            create_job(job, directory, job['pins'])
            store = Store(directory, job['job_id'])
            self.prepare(store); self.prepare(store, 't1')
            self.assertEqual(store.load()['policy']['max_live_workers_by_provider'], {})
            for value in (0, True, -1):
                job = self.job()
                job['job_id'] = 'invalid-' + str(value)
                job['pins']['ape']['limits'] = {'max_live_workers_by_provider': {'fixture-a': value}}
                with self.subTest(value=value), self.assertRaises(JobError):
                    create_job(job, directory, job['pins'])

    def test_compact_admission_matches_readiness_instead_of_capacity_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, self.job())
            for reason in ('predecessor_acceptance_required', 'reconcile_owned_work',
                           'task_not_pending', 'execution_or_retry_checks_required'):
                with self.subTest(reason=reason):
                    job = store.load()
                    task = job['tasks'][0]
                    if reason == 'predecessor_acceptance_required':
                        job['stages'].append({**copy.deepcopy(job['stages'][0]), 'id': 'predecessor'})
                        job['stages'][0]['depends_on'] = ['predecessor']
                    elif reason == 'reconcile_owned_work':
                        task['handles'] = [{'task_id': 'owned', 'request_id': task['request_id'],
                                            'status': 'running', 'work_state': 'working'}]
                    elif reason == 'task_not_pending':
                        task['status'] = 'completed'
                    else:
                        task['attempt'] = 1
                    advice = admission(job)['tasks'][0]
                    page = overview(store, job, compact=True, limit=100)
                    row = next(row for row in page['records'] if row['kind'] == 'tasks' and row['task_id'] == 't0')
                    self.assertEqual(row['admission'], {key: value for key, value in advice.items()
                                                      if key not in ('task_id', 'request_id')})
                    self.assertEqual(row['admission']['reason'], reason)
                    self.assertFalse(row['admission']['eligible'])
                    self.assertNotEqual(row['next_action'], 'prepare_if_admitted')

    def test_missing_host_duplicate_cannot_create_a_phantom_capacity_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, self.job())
            self.event(store, 't0', 'accepted', host_task_id='owned')
            before = store.file.read_bytes()
            with self.assertRaisesRegex(JobError, 'already has an accepted host handle'):
                self.event(store, 't0', 'accepted')
            self.assertEqual(store.file.read_bytes(), before)
            self.assertEqual([row['host_task_id'] for row in occupancy(store.load())], ['owned'])
            legacy = store.load()
            legacy['blockers'] = [{'kind': 'conflicting-host-handle', 'task_id': 't0', 'host_task_id': None}]
            self.assertEqual(len(occupancy(legacy)), 1)

    def test_compact_pages_show_archived_and_conflicting_capacity_holders(self):
        job = self.job()
        archived = {**copy.deepcopy(job['tasks'][0]), 'task_id': 'archived', 'request_id': 'old-request'}
        archived['handles'] = [{'task_id': 'old-host', 'request_id': 'old-request', 'status': 'completed',
                                'work_state': 'waiting_for_children', 'has_pending_child_runs': True}]
        job['history'] = [{'tasks': [archived]}]
        job['blockers'] = [{'kind': 'conflicting-host-handle', 'task_id': 't0',
                            'request_id': 'req0', 'host_task_id': 'conflicting-host'}]
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            page = overview(store, compact=True, limit=1)
            rows = list(page['records'])
            while page['next_cursor']:
                page = overview(store, compact=True, cursor=page['next_cursor'], limit=1)
                self.assertLessEqual(len(canonical(page)), COMPACT_MAX_BYTES)
                rows.extend(page['records'])
            holders = [row for row in rows if row['kind'] == 'occupants']
            self.assertEqual(len(holders), admission(store.load())['occupied'])
            self.assertEqual({row['host_task_id'] for row in holders}, {'old-host', 'conflicting-host'})
            self.assertTrue(all(row['details'] == str(store.file) for row in holders))
            self.assertIsNone(next(row for row in holders if row['host_task_id'] == 'conflicting-host')['provider'])

    def test_preparations_are_serialized_across_processes(self):
        job = self.job()
        job['policy']['max_live_workers_by_provider'] = {'fixture-a': 1}
        with tempfile.TemporaryDirectory() as directory:
            self.store(directory, job)
            script = '''import sys,json
from shared.job_coordinator import prepare_task as prepare
from core.jobs.store import Store,JobError
caller=json.loads(sys.argv[3])
try: prepare(Store(sys.argv[1],'coordination'),caller,sys.argv[2],lambda *_:True,lambda *_:True)
except JobError as exc: print(exc);sys.exit(2)
'''
            children = [subprocess.Popen([sys.executable, '-B', '-c', script, directory, task,
                                           json.dumps(self.fixture.caller())], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        for task in ('t0', 't1')]
            results = [(child.communicate(), child.returncode) for child in children]
            self.assertEqual(sorted(code for _, code in results), [0, 2])
            self.assertIn(b'provider_worker_limit', b''.join(out for (out, _), _ in results))

    def test_global_cap_unknown_provider_and_terminal_pending_children(self):
        job = self.job()
        job['policy'].update(max_live_workers=1, max_live_workers_by_provider={'fixture-a': 1})
        task = job['tasks'][0]
        task['handles'] = [{'task_id': 'host0', 'request_id': 'req0', 'status': 'completed',
                            'work_state': 'waiting_for_children', 'has_pending_child_runs': True,
                            'target': task['target']}]
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            with self.assertRaisesRegex(JobError, 'global_worker_limit'):
                self.prepare(store, 't2')
            self.event(store, 't0', 'completion', host_task_id='host0', completion_id='done0',
                       status='completed', work_state='result_available', has_pending_child_runs=False)
            self.prepare(store, 't2')
        job['policy']['max_live_workers'] = None
        job['tasks'][1].pop('target')
        self.assertEqual(admission(job)['tasks'][1]['reason'], 'provider_identity_required')

    def test_capacity_or_rate_limit_deferral_requires_new_owned_completion(self):
        job = self.job()
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            self.prepare(store)
            self.event(store, 't0', 'capacity-deferred', reason='rate-limit')
            self.assertFalse(occupancy(store.load()))
            with self.assertRaisesRegex(JobError, 'owned_completion_required'):
                self.prepare(store)
            with self.assertRaisesRegex(JobError, 'was not observed'):
                self.event(store, 't0', 'capacity-deferred', completion_id='invented')
            self.prepare(store, 't2')
            self.event(store, 't2', 'accepted', host_task_id='host2')
            self.event(store, 't2', 'completion', host_task_id='host2', completion_id='done2',
                       status='completed', work_state='result_available', has_pending_child_runs=False)
            self.event(store, 't0', 'capacity-deferred', completion_id='done2', reason='rate-limit')
            self.prepare(store)
            self.assertEqual(store.load()['tasks'][0]['attempt'], 0)
            self.event(store, 't1', 'capacity-deferred')
            with self.assertRaisesRegex(JobError, 'new owned completion'):
                self.event(store, 't1', 'capacity-deferred', completion_id='done2')

    def test_observed_over_capacity_handles_are_retained(self):
        job = self.job()
        job['policy']['max_live_workers_by_provider'] = {'fixture-a': 1}
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            self.event(store, 't0', 'accepted', host_task_id='host0')
            self.event(store, 't1', 'accepted', host_task_id='host1')
            self.assertEqual(len(occupancy(store.load())), 2)
            self.assertEqual(len(store.load()['tasks'][1]['handles']), 1)

    def test_uncertain_launch_cannot_release_capacity_by_claiming_a_deferral(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, self.job())
            self.prepare(store)
            self.event(store, 't0', 'uncertain')
            with self.assertRaisesRegex(JobError, 'uncertain launch must be reconciled'):
                self.event(store, 't0', 'capacity-deferred')
            self.assertEqual(len(occupancy(store.load())), 1)

    def test_existing_large_repair_allowance_is_preserved(self):
        job = self.job();job['policy']['max_repair_cycles'] = 1000
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            self.assertEqual(overview(store,compact=True)['limits']['max_repair_cycles'], 1000)

    def test_followup_preparation_reserves_and_obeys_the_same_provider_capacity(self):
        from shared.job_coordinator import prepare_followup
        job = self.job();job['policy']['max_live_workers_by_provider'] = {'fixture-a': 1}
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            self.prepare(store)
            self.event(store, 't0', 'accepted', host_task_id='host0')
            self.event(store, 't0', 'completion', host_task_id='host0', completion_id='done0',
                       status='completed', work_state='result_available', has_pending_child_runs=False)
            def ingested(state):
                state['tasks'][0]['status'] = 'awaiting-followup'
                state['tasks'][0]['execution_history'] = [{'request_id': 'req0', 'result_bytes': 1}]
            store.mutate(self.fixture.caller(), ingested)
            self.prepare(store, 't1')
            with self.assertRaisesRegex(JobError, 'provider_worker_limit'):
                prepare_followup(store, self.fixture.caller(), 't0', 'follow0')
            self.event(store, 't1', 'capacity-deferred')
            prepare_followup(store, self.fixture.caller(), 't0', 'follow0')
            self.assertEqual(len(occupancy(store.load())), 1)

    def test_conflicting_provider_pins_require_an_explicit_policy(self):
        job = self.job()
        job['pins']['ape']['limits'] = {'max_live_workers_by_provider': {'fixture-a': 1}}
        job['pins']['second'] = {**copy.deepcopy(job['pins']['ape']),
                                 'limits': {'max_live_workers_by_provider': {'fixture-a': 2}}}
        job['dependencies'].append({'key': 'second', 'plugin': 'ape'})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(JobError, 'conflicting pin limits'):
                self.store(directory, job)
            job['policy']['max_live_workers_by_provider'] = {'fixture-a': 1}
            self.assertEqual(self.store(directory, job).load()['policy']['max_live_workers_by_provider'], {'fixture-a': 1})

    def test_provider_limits_validate_and_raising_or_removing_needs_owner_decision(self):
        from core.jobs.store import validate
        from core.schema import errors, load_schema_file
        from shared.job_coordination import provider_limits
        schemas = [load_schema_file(Path(__file__).resolve().parents[1] / 'shared/agents' / name)
                   for name in ('job.schema.json', 'workers-config.schema.json')]
        caps_schemas = [schemas[0]['properties']['policy']['properties']['max_live_workers_by_provider'],
                        schemas[1]['properties']['max_live_workers_by_provider']]
        for value in ({'fixture-a': 0}, {'fixture-a': True}, {'': 1}, {' \t\n': 1},
                      {'x' * 129: 1}, [], {'fixture-a': None}):
            for schema in caps_schemas:
                self.assertTrue(errors(value, schema), value)
            with self.subTest(value=value), self.assertRaises(JobError):
                job = self.job();job['policy']['max_live_workers_by_provider'] = value;provider_limits(value);validate(job)
        valid = {'fixture-a': 1, 'x' * 128: 2}
        provider_limits(valid)
        self.assertTrue(all(not errors(valid, schema) for schema in caps_schemas))
        job = self.job();job['policy']['max_live_workers_by_provider'] = {'fixture-a': 2}
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, job)
            for value in ({'fixture-a': 3}, {}):
                with self.assertRaisesRegex(JobError, 'undeclared_expansion'):
                    revise_plan(store, self.fixture.caller(), {'id': 'raise'},
                                {'policy': {**job['policy'], 'max_live_workers_by_provider': value}})
            revise_plan(store, self.fixture.caller(), {'id': 'narrow'},
                        {'policy': {**job['policy'], 'max_live_workers_by_provider': {'fixture-a': 1}}})
            self.assertEqual(store.load()['policy']['max_live_workers_by_provider'], {'fixture-a': 1})
            revise_plan(store, self.fixture.caller(), {'id': 'add-narrowing-cap'},
                        {'policy': {**job['policy'], 'max_live_workers_by_provider': {'fixture-a': 1, 'fixture-b': 1}}})
            self.assertEqual(store.load()['policy']['max_live_workers_by_provider'], {'fixture-a': 1, 'fixture-b': 1})

    def test_snapshot_history_does_not_double_count_capacity_results_or_metrics(self):
        job = self.job()
        task = job['tasks'][0]
        task.update(handles=[{'task_id': 'host0', 'request_id': 'req0', 'status': 'completed',
                              'work_state': 'result_available', 'has_pending_child_runs': False}],
                    execution_history=[{'request_id': 'req0', 'result_bytes': 123}])
        job['history'] = [{'tasks': copy.deepcopy(job['tasks']), 'stages': copy.deepcopy(job['stages'])}]
        job['history'][0]['tasks'][0]['handles'][0].update(status='running', work_state='working')
        self.assertEqual(occupancy(job), [])
        self.assertEqual(coordination_metrics(job)['result_bytes'], 123)

    def test_metrics_record_decision_waits_and_unchanged_observations_without_charging_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, self.job())
            self.event(store, 't0', 'accepted', host_task_id='host0')
            with mock.patch('shared.job_coordination.observed_now', return_value='2026-01-01T00:00:00+00:00'):
                self.event(store, 't0', 'approval-wait', wait_id='owner-choice')
            with mock.patch('shared.job_coordination.observed_now', return_value='2026-01-01T00:00:30+00:00'):
                self.event(store, 't0', 'approval-resolved', wait_id='owner-choice')
            for _ in range(2):
                self.event(store, 't0', 'reconciled', host_task_id='host0', status='running',
                           work_state='working', has_pending_child_runs=False)
            self.event(store, 't0', 'completion', host_task_id='host0', completion_id='done0',
                       status='completed', work_state='result_available', has_pending_child_runs=False)
            before = store.file.read_bytes()
            self.event(store, 't0', 'completion', host_task_id='host0', completion_id='done0',
                       status='completed', work_state='result_available', has_pending_child_runs=False)
            self.assertEqual(store.file.read_bytes(), before)
            metrics = overview(store,)['coordination_metrics']
            self.assertEqual((metrics['decision_requests'], metrics['resolved_decision_wait_seconds']), (1, 30))
            self.assertEqual(metrics['unchanged_observations'], 1)
            self.assertEqual(metrics['repair_cycles'], 0)
            self.assertIsNone(metrics['tokens']['value'])

    def test_observation_rejects_supplied_receipt_time_without_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, self.job())
            before = store.file.read_bytes()
            for stamp in ('2026-01-01T00:00:00Z', 'invalid', None):
                with self.subTest(stamp=stamp), self.assertRaisesRegex(JobError, 'local receipt time'):
                    self.event(store, 't0', 'accepted', host_task_id='host0', recorded_at=stamp)
                self.assertEqual(store.file.read_bytes(), before)

    def test_missing_historical_metric_fields_are_unknown(self):
        job = self.job()
        job['tasks'][0]['execution_history'] = [{'request_id': 'req0'}]
        job['tasks'][0]['dispatch_history'] = [
            {'kind': 'approval-wait', 'wait_id': 'old'}, {'kind': 'approval-resolved', 'wait_id': 'old'}]
        metrics = coordination_metrics(job)
        self.assertIsNone(metrics['result_bytes']['value'])
        self.assertIsNone(metrics['resolved_decision_wait_seconds']['value'])

    def test_decision_metrics_allow_reused_wait_ids_without_double_counting_redelivery(self):
        job = self.job()
        job['tasks'][0]['dispatch_history'] = [
            {'kind': kind, 'wait_id': 'choice', 'recorded_at': f'2026-01-01T00:00:{second:02d}+00:00'}
            for kind, second in [('approval-wait', 0), ('approval-wait', 1), ('approval-resolved', 10),
                                 ('approval-wait', 20), ('approval-resolved', 30)]]
        metrics = coordination_metrics(job)
        self.assertEqual((metrics['decision_requests'], metrics['resolved_decision_wait_seconds']), (2, 20))

    def test_installed_cli_compact_since_admission_and_external_receipt_drift(self):
        from shared.job_coordinator import create_pinned_job
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version, manifest, prefix, agents, state = self.fixture.install(root)
            job = self.job();job['installation_id'] = manifest['installation_id'];job['pins'] = {}
            config = root / 'workers.json'
            config.write_text(json.dumps({'schema_version': 1, 'max_live_workers': 3,
                'max_live_workers_by_provider': {'fixture-a': 1}, 'max_repair_cycles': 7, 'overrides': []}))
            job['policy'].pop('max_live_workers', None);job['policy'].pop('max_repair_cycles')
            create_pinned_job(job, state, prefix, agents, config)
            store = Store(state, job['job_id']);original = store.load()
            self.assertEqual(original['policy']['max_repair_cycles'], 7)
            self.assertEqual(original['policy']['max_live_workers_by_provider'], {'fixture-a': 1})
            def invoke(command, *args):
                result = subprocess.run([sys.executable, '-B', str(version / 'shared/job_cli.py'), command,
                    '--state-root', str(state), '--job', job['job_id'], *args],
                    cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)
            first = invoke('overview', '--compact')
            self.assertFalse(invoke('status', '--compact', '--since', first['view_sha256'])['changed'])
            self.assertEqual(invoke('admission')['tasks'][0]['provider_limit'], 1)
            self.assertEqual(store.load(), original)
            # An accepted-looking stage with missing external receipt must be derived stale.
            # This setup is synthetic and does not mint acceptance or run a validator.
            original['stages'][0].update(status='accepted-at-snapshot',
                acceptance={'path': str(root / 'missing-receipt.json'), 'sha256': '0' * 64})
            from core.jobs.store import _atomic
            _atomic(store.file, canonical(original))
            unsafe_digest = overview(store,compact=True)['view_sha256']
            snapshot = store.file.read_bytes()
            stale = invoke('status', '--compact', '--since', unsafe_digest)
            self.assertTrue(stale['changed'])
            self.assertEqual(stale['metrics']['accepted_stages'], 0)
            self.assertEqual(store.file.read_bytes(), snapshot)


if __name__ == '__main__':
    unittest.main()
