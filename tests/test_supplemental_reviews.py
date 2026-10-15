"""Optional reviews: offline pricing, lifetime, gate isolation and installed CLI.

Synthetic capabilities and prices only. No provider or GitHub calls.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import supplemental_reviews as reviews
from tests.test_rebuild_installed import Sandbox

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture(now=NOW):
    models = ['opencode/sample-a-free', 'opencode/sample-b-free', 'opencode/sample-c-free',
              'opencode/sample-d-free', 'opencode/paid', 'opencode-go/included']
    stamp = now.isoformat()
    return {
        'permissions': {'delegate': True, 'share_with_opencode': True},
        'catalog_observed_at': stamp,
        'capabilities': {
            'runtimeMode': 'full-access', 'inheritedProviderInstanceId': 'parent', 'parentThreadId': 'parent-thread',
            'features': {'appOwnedSubagents': True, 'asyncPolling': True, 'cancellation': True},
            'providers': [{'providerInstanceId': 'gateway', 'driverKind': 'opencode',
                           'canRunChildTask': True, 'canRunCrossProviderChildTask': True,
                           'constraints': [], 'runtimeModes': ['auto', 'full-access'],
                           'models': [{'id': m} for m in models]}]},
        'pricing': [{'model': m, 'source': reviews.SOURCES[m.split('/')[0]], 'observed_at': stamp,
                     'all_charges_covered': True, 'eligible': True,
                     'costs': {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'request': 0},
                     'evidence': 'Synthetic official row mapped to exact ID; all charges covered'} for m in models[:4]],
        'context': {'round_id': 'job-fixture/review-1', 'revision': 'a' * 40,
                    'base_revision': 'b' * 40, 'base_ref': 'origin/trunk',
                    'scope': 'Synthetic repository combined diff; inspect source and callers',
                    'constraints': 'Read only. No live calls. Preserve unrelated work.',
                    'permissions': 'Authorised read-only review; fixture sharing allowed.',
                    'prior_feedback': 'None'},
    }


def observation(state, status='completed', summary=None, task='task-fixture'):
    request = state['requests'][0]
    if summary is None:
        summary = json.dumps({'revision': 'a' * 40, 'base_revision': 'b' * 40,
                              'coverage': 'Inspected synthetic source and callers',
                              'findings': [{'severity': 'major', 'path': 'module.py', 'line': 3,
                                            'evidence': 'Fixture reproduces missing validation',
                                            'suggestion': 'Validate the input'}]})
    return {'request_id': request['request_id'], 'kind': 'status',
            'current_revision': 'a' * 40, 'current_base_revision': 'b' * 40,
            'observation': {'taskId': task, 'childThreadId': 'child-fixture', 'childRunId': 'run-fixture',
                            **request['dispatch']['target'], 'status': status, 'workState': 'result_available',
                            'hasPendingChildRuns': False, 'summary': summary}}


class SelectionTest(unittest.TestCase):
    def test_dynamic_selection_three_total_and_no_fixed_roster(self):
        data = fixture()
        selected, skipped = reviews.select(data, NOW)
        self.assertEqual([r['target']['model'] for r in selected],
                         ['opencode/sample-a-free', 'opencode/sample-b-free', 'opencode/sample-c-free'])
        self.assertTrue(any(r.get('model') == 'opencode-go/included' for r in skipped))
        # Another instance and the Go alias must not increase the cap or repeat a model.
        other = deepcopy(data['capabilities']['providers'][0])
        other['providerInstanceId'] = 'another-gateway'
        data['capabilities']['providers'].insert(0, other)
        alias = deepcopy(data['pricing'][0])
        alias.update(model='opencode-go/sample-a', source=reviews.SOURCES['opencode-go'])
        data['pricing'].append(alias)
        other['models'].append({'id': alias['model']})
        selected, _ = reviews.select(data, NOW)
        self.assertEqual(len(selected), 3)
        self.assertEqual(len({r['target']['model'].split('/')[1].removesuffix('-free') for r in selected}), 3)
        data['capabilities']['providers'].reverse()
        self.assertEqual(reviews.select(data, NOW)[0], selected)

    def test_permissions_runnable_modes_features_and_freshness_fail_closed(self):
        changes = [lambda d: d.update(enabled=False),
                   lambda d: d['permissions'].update(delegate=False),
                   lambda d: d['permissions'].update(share_with_opencode=False),
                   lambda d: d['capabilities'].update(runtimeMode='auto'),
                   lambda d: d['capabilities'].update(inheritedProviderInstanceId=None),
                   lambda d: d['capabilities'].update(parentThreadId=None),
                   lambda d: d['capabilities']['features'].update(cancellation=False),
                   lambda d: d['capabilities']['providers'][0].update(canRunChildTask=False),
                   lambda d: d['capabilities']['providers'][0].update(canRunCrossProviderChildTask=False),
                   lambda d: d['capabilities']['providers'][0].update(runtimeModes=None),
                   lambda d: d['capabilities']['providers'][0].update(runtimeModes='full-access'),
                   lambda d: d['capabilities']['providers'][0].update(constraints=['disabled']),
                   lambda d: d.update(catalog_observed_at=(NOW - timedelta(minutes=6)).isoformat()),
                   lambda d: d.update(catalog_observed_at=(NOW + timedelta(seconds=1)).isoformat())]
        for change in changes:
            data = fixture()
            change(data)
            with self.subTest(change=change):
                self.assertEqual(reviews.select(data, NOW)[0], [])
        data = fixture()
        data['capabilities']['inheritedProviderInstanceId'] = 'gateway'
        data['capabilities']['providers'][0]['canRunCrossProviderChildTask'] = False
        self.assertEqual(len(reviews.select(data, NOW)[0]), 3)

    def test_pricing_requires_explicit_fresh_all_zero_evidence_for_exact_namespace(self):
        changes = [lambda p: p.update(costs={'input': .1, 'output': 0}),
                   lambda p: p['costs'].update(cache_write=.1),
                   lambda p: p['costs'].update(request=.1),
                   lambda p: p['costs'].update(input=False),
                   lambda p: p.update(costs={'output': 0}),
                   lambda p: p.update(all_charges_covered=False),
                   lambda p: p.update(eligible=False),
                   lambda p: p.update(source='https://invalid.example/pricing'),
                   lambda p: p.update(source=reviews.SOURCES['opencode-go']),
                   lambda p: p.update(observed_at=(NOW - timedelta(minutes=6)).isoformat()),
                   lambda p: p.update(evidence='')]
        for change in changes:
            data = fixture()
            data['pricing'] = data['pricing'][:1]
            change(data['pricing'][0])
            self.assertEqual(reviews.select(data, NOW)[0], [])
        data = fixture()
        data['pricing'] = []
        self.assertEqual(reviews.select(data, NOW)[0], [], 'a -free suffix alone is insufficient')
        proof = deepcopy(fixture()['pricing'][0])
        proof.update(model='opencode-go/included', source=reviews.SOURCES['opencode-go'])
        data['pricing'] = [proof]
        self.assertEqual(reviews.select(data, NOW)[0][0]['target']['model'], 'opencode-go/included')
        data['pricing'].append(deepcopy(proof))
        self.assertEqual(reviews.select(data, NOW)[0], [], 'conflicting or duplicate pricing is uncertain')
        for advertised in ({'input': 1, 'output': 0}, {'free': True}, None):
            data = fixture()
            data['pricing'] = data['pricing'][:1]
            data['capabilities']['providers'][0]['models'][0]['cost'] = advertised
            self.assertEqual(reviews.select(data, NOW)[0], [], 'conflicting/unknown catalog prices skip')


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.state = reviews.prepare(fixture(), NOW)

    def test_brief_pins_authority_scope_base_feedback_and_request(self):
        dispatch = self.state['requests'][0]['dispatch']
        self.assertEqual(dispatch['mode'], 'async')
        self.assertEqual(dispatch['runtimeMode'], 'full-access')
        for phrase in ('read-only', 'Do not edit', 'never the required evaluator', 'No live calls.',
                       'origin/trunk', 'job-fixture/review-1', 'prior_feedback', 'a' * 40, 'b' * 40):
            self.assertIn(phrase, dispatch['task'])
        self.assertEqual(dispatch, reviews.prepare(fixture(), NOW)['requests'][0]['dispatch'])
        new = fixture()
        new['context']['round_id'] += '/next'
        self.assertNotEqual(dispatch['clientRequestId'], reviews.prepare(new, NOW)['requests'][0]['request_id'])

    def test_valid_findings_only_become_untrusted_evidence(self):
        reviews.record(self.state, observation(self.state))
        request = self.state['requests'][0]
        self.assertEqual(request['outcome'], 'untrusted-evidence')
        self.assertEqual(request['findings'][0]['severity'], 'major')
        self.assertNotIn('accepted', self.state)
        self.assertNotIn('attempt', self.state)
        self.assertEqual(reviews.overview(self.state)['mandatory_acceptance'], 'unchanged')
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        reviews.close(self.state)
        self.assertEqual(request['result']['findings'][0]['path'], 'module.py')

    def test_failures_malformed_stale_late_and_pending_are_skips(self):
        changes = [lambda e: e['observation'].update(status='failed'),
                   lambda e: e['observation'].update(summary='overloaded'),
                   lambda e: e['observation'].update(summary='```json\n{}\n```'),
                   lambda e: e['observation'].update(summary='{"revision":1,"revision":2}'),
                   lambda e: e['observation'].update(summary='x' * 32769),
                   lambda e: e['observation'].update(summary=None),
                   lambda e: e.update(current_revision='c' * 40),
                   lambda e: e.update(current_base_revision='c' * 40),
                   lambda e: e['observation'].update(providerInstanceId='other'),
                   lambda e: e['observation'].update(model=None),
                   lambda e: e['observation'].update(childRunId=None),
                   lambda e: e['observation'].update(hasPendingChildRuns=True),
                   lambda e: e['observation'].update(workState='waiting_for_children')]
        for change in changes:
            state = deepcopy(self.state)
            event = observation(state)
            change(event)
            reviews.record(state, event)
            self.assertTrue(state['requests'][0]['outcome'].startswith('skipped-'))
            self.assertEqual(state['requests'][0]['findings'], [])
        state = deepcopy(self.state)
        reviews.close(state)
        reviews.record(state, observation(state))
        self.assertEqual(state['requests'][0]['outcome'], 'skipped-closed')

    def test_wrong_revision_in_result_and_invalid_finding_rejected(self):
        valid = json.loads(observation(self.state)['observation']['summary'])
        changes = [lambda v: v.update(revision='c' * 40),
                   lambda v: v.update(base_revision='c' * 40),
                   lambda v: v['findings'][0].update(path='../escape.py'),
                   lambda v: v['findings'][0].update(line=True),
                   lambda v: v['findings'][0].update(evidence='')]
        for change in changes:
            value = deepcopy(valid)
            change(value)
            with self.assertRaises(ValueError):
                reviews.result(json.dumps(value), self.state['context'])

    def test_every_handle_kept_mismatch_sticky_and_cancel_does_not_prove_stop(self):
        event = observation(self.state)
        event['kind'] = 'receipt'
        event['observation']['model'] = 'wrong-model'
        reviews.record(self.state, event)
        request = self.state['requests'][0]
        reviews.record(self.state, observation(self.state))
        self.assertEqual(request['outcome'], 'skipped-identity-or-handle-mismatch')
        later = observation(self.state, task='conflicting-task')
        later['observation']['hasPendingChildRuns'] = True
        reviews.record(self.state, later)
        self.assertEqual(len(request['handles']), 2)
        reviews.close(self.state)
        reviews.record(self.state, {'request_id': request['request_id'], 'kind': 'cancel-requested',
                                    'task_id': 'conflicting-task'})
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['conflicting-task'])
        later['observation']['hasPendingChildRuns'] = False
        later['observation']['status'] = 'cancelled'
        reviews.record(self.state, later)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        self.assertEqual(request['findings'], [])

    def test_original_run_binding_and_owned_cancellation(self):
        event = observation(self.state)
        event['kind'] = 'receipt'
        reviews.record(self.state, event)
        event['kind'] = 'status'
        event['observation']['childRunId'] = 'later-run'
        reviews.record(self.state, event)
        self.assertEqual(self.state['requests'][0]['outcome'], 'skipped-identity-or-handle-mismatch')
        reviews.record(self.state, observation(self.state))
        self.assertEqual(self.state['requests'][0]['outcome'], 'skipped-identity-or-handle-mismatch')
        with self.assertRaises(ValueError):
            reviews.record(self.state, {'request_id': event['request_id'], 'kind': 'cancel-requested',
                                        'task_id': 'unrelated-task'})

    def test_uncertain_launch_retained_definite_rejection_resolved(self):
        request = self.state['requests'][0]
        event = {'request_id': request['request_id'], 'kind': 'launch-error', 'error': 'do-not-store-secret'}
        reviews.record(self.state, event)
        reviews.close(self.state)
        self.assertIn(request['request_id'], reviews.overview(self.state)['unresolved_request_ids'])
        self.assertNotIn('do-not-store-secret', json.dumps(self.state))
        # Late recovered receipt stays owned and needs cleanup, never result intake.
        late = observation(self.state)
        late['kind'] = 'receipt'
        reviews.record(self.state, late)
        self.assertIn('task-fixture', reviews.overview(self.state)['cancel_task_ids'])
        second = self.state['requests'][1]
        reviews.record(self.state, {'request_id': second['request_id'], 'kind': 'launch-rejected'})
        self.assertNotIn(second['request_id'], reviews.overview(self.state)['unresolved_request_ids'])


class InstalledTest(unittest.TestCase):
    def test_relocated_installed_round_resume_failure_cleanup_and_mandatory_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            source = box.source_copy('ralph')
            package, manifest = box.install('ralph', source=source)
            shutil.rmtree(source)
            relocated = box.base / 'relocated-package'
            shutil.copytree(package, relocated)
            helper = relocated / 'shared' / 'supplemental_reviews.py'
            self.assertTrue(helper.is_file())
            self.assertTrue((relocated / 'shared' / 'supplemental-reviews.md').is_file())
            self.assertIn('shared/supplemental_reviews.py', [f['path'] for f in manifest['files']])
            # Byte-level proof that the optional CLI does not touch mandatory state/counters.
            mandatory = box.private / 'mandatory.json'
            mandatory.write_text('{"accepted":false,"attempt":1,"requiredReviewer":"primary"}')
            pinned = mandatory.read_bytes()
            ledger = box.private / 'supplemental.json'
            input_file = box.private / 'input.json'

            def run(command, data=None):
                argv = [sys.executable, helper, command, '--state', ledger]
                if data is not None:
                    input_file.write_text(json.dumps(data))
                    argv += ['--input', input_file]
                proc = box.run(argv)
                self.assertEqual(proc.returncode, 0)
                self.assertEqual(mandatory.read_bytes(), pinned)
                return json.loads(proc.stdout)

            data = fixture(datetime.now(timezone.utc))
            first = run('prepare', data)
            self.assertEqual(len(first['dispatches']), 3)
            saved = json.loads(ledger.read_text())
            self.assertEqual(run('prepare', data)['dispatches'], [])
            self.assertEqual(json.loads(ledger.read_text())['requests'], saved['requests'])
            self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)
            bad = deepcopy(data)
            bad['context']['revision'] = 'c' * 40
            self.assertIn('optional_error', run('prepare', bad))
            event = observation(saved, status='failed')
            run('record', event)
            ended = run('close')
            self.assertTrue(ended['closed'])
            self.assertEqual(ended['dispatches'], [])
            self.assertEqual(run('prepare', data)['dispatches'], [])
            run('record', observation(saved))
            self.assertEqual(run('status')['requests'][0]['outcome'], 'skipped-closed')
            # Contention must skip immediately, never make optional work wait on a lock.
            with open(ledger.with_suffix('.lock'), 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                proc = subprocess.run([sys.executable, helper, 'status', '--state', ledger],
                                      cwd=box.base, env=box.env, capture_output=True, text=True, timeout=5)
                self.assertEqual(proc.returncode, 0)
                self.assertIn('optional_error', json.loads(proc.stdout))
            ledger.write_text('malformed')
            self.assertIn('optional_error', run('status'))
            self.assertEqual(ledger.read_text(), 'malformed', 'never reset a damaged ledger to relaunch')

    def test_workflow_hooks_ship_in_installed_packages(self):
        hooks = {'ralph': 'playbooks/loop.md', 'imps': 'references/delegation.md',
                 'babysitter': 'playbooks/maintain.md', 'agent-tuneup': 'references/job-plan.md',
                 'elephant-goldfish': 'references/document-jobs.md'}
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            for plugin, hook in hooks.items():
                package, _ = box.install(plugin)
                self.assertIn('PKG/shared/supplemental-reviews.md', (package / hook).read_text())
                self.assertTrue((package / 'shared' / 'supplemental_reviews.py').is_file())


if __name__ == '__main__':
    unittest.main()
