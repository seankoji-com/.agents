"""Adverse transitions from the issue 94 repair reviews; all services are fixtures."""
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from argparse import Namespace
from unittest.mock import patch
from pathlib import Path

from tests.babysitter_continuous_fixtures import (
    AcceptedJob, install_legacy, legacy_source, plan, source_package,
)
from tests import test_babysitter_continuous as continuous_tests
from tests.test_babysitter_continuous import (
    ContinuousCase, FakeHost, H1, H2, HELPER, observation, pr, continuous_sweep,
)
from tests.test_rebuild_installed import Sandbox, tree_digest, worker_result

URL = 'https://github.com/fixture/widgets/pull/12'
NOW = '2026-10-22T14:05:00Z'


class WakeIdentityTest(ContinuousCase):
    def adapters(self):
        yield from UpdateAndResolutionTest.adapters(self)

    def seed(self, helper):
        self.start(helper=helper)
        self.cli('observe', '--now', NOW, '--wake-id', 'seed', helper=helper,
                 payload=observation(pr(), pr(number=13, owner={
                     'thread_id': 'self', 'status': 'running', 'fixer_in_flight': True,
                     'host_task_id': 'adopted-live'}), pr(number=14)))

    def assert_blocked(self, helper, adapter):
        before = self.state.read_bytes()
        for kind in ('schedule', 'event', 'manual', 'resume'):
            with self.subTest(wake=kind):
                refused = self.cli('observe', '--now', NOW, '--wake-kind', kind,
                    '--wake-id', 'blocked-' + kind, helper=helper,
                    payload=observation(pr()), ok=False)
                self.assertRegex(refused.stderr, 'migration required|integrity|manifest|state policy')
                host = FakeHost(observation(pr()))
                with patch.object(host, 'discover', side_effect=AssertionError('discovery ran')):
                    with self.assertRaises(adapter.continuous.ContinuousError):
                        adapter.handle_wake(host, self.state, NOW,
                                            {'wake_id': 'blocked-' + kind, 'kind': kind})
                self.assertEqual(host.dispatched, [])
                self.assertEqual(self.state.read_bytes(), before)
        for kind in ('fixer', 'merge', 'update-branch', 'resolution'):
            for flags in (('--reserve',), ()):
                with self.subTest(writer=kind, flags=flags):
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', 'blocked-' + kind, '--head', H1, *flags,
                        helper=helper, ok=False)
                    self.assertRegex(refused.stderr, 'migration required|integrity|manifest|state policy')
                    self.assertEqual(self.state.read_bytes(), before)
        self.cli('schedule-plan', helper=helper, ok=False)
        for command, flags in (
                ('schedule-record', ('--schedule-id', 'blocked-schedule',
                                     '--next-run-at', '2026-10-22T14:20:00Z')),
                ('scheduler', ('--available', 'yes', '--authorized', 'yes'))):
            refused = self.cli(command, '--now', NOW, *flags, helper=helper, ok=False)
            self.assertRegex(refused.stderr, 'migration required|integrity|manifest|state policy')
            self.assertEqual(self.state.read_bytes(), before)
        host = FakeHost(observation(pr()))
        with self.assertRaises(adapter.continuous.ContinuousError):
            adapter.arm(host, self.state, NOW)
        with patch.object(host, 'due', side_effect=AssertionError('host due ran')):
            with self.assertRaises(adapter.continuous.ContinuousError):
                adapter.tick(host, self.state, NOW)
        self.assertEqual(host.created, [])
        report = self.cli('status', '--now', NOW, helper=helper)
        self.assertEqual(report['coverage'], 'continuation-blocked')
        self.assertTrue(report['package_identity_gap'])
        self.assertNotIn(report['prs'][URL]['next_action']['kind'],
                         ('merge', 'dispatch-fixer', 'update-branch', 'resolution'))
        self.assertEqual(self.state.read_bytes(), before)

    def test_status_reports_blocked_identity_without_mutating_or_recommending_stale_work(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'status-{index}.json'
            self.seed(helper)
            self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                     '--next-run-at', '2026-10-22T14:15:00Z', helper=helper)
            initial = self.state.read_bytes()
            for field, value, gap in (('installed_digest', '0' * 64, 'installed-drift'),
                                      ('installed_digest', None, 'missing-package-identity'),
                                      ('policy_version', 'continuous-0', 'policy-version')):
                state = json.loads(initial)
                if field == 'policy_version':
                    state[field] = value
                else:
                    state['package'][field] = value
                self.state.write_text(json.dumps(state))
                before = self.state.read_bytes()
                report = self.cli('status', '--now', '2026-10-22T14:16:00Z', helper=helper)
                self.assertEqual(report['status'], 'continuation-blocked')
                self.assertEqual(report['coverage'], 'continuation-blocked')
                self.assertIn(gap, [item['kind'] for item in report['package_identity_gap']])
                self.assertEqual(report['package']['recorded'], state['package'])
                self.assertTrue(report['package']['running']['digest'])
                scheduler = report['scheduler']
                self.assertEqual(scheduler['package_identity_gap'], report['package_identity_gap'])
                self.assertIsNone(scheduler['next_run_at'])
                self.assertEqual(scheduler['historical_next_run_at'], '2026-10-22T14:15:00Z')
                self.assertEqual(scheduler['stop']['arguments']['scheduledTaskId'], 'owned-schedule')
                self.assertEqual(report['prs'][URL]['next_action']['kind'], 'migration-required')
                adopted = report['prs'][URL.replace('/12', '/13')]
                self.assertTrue(adopted['fixer']['in_flight'])
                self.assertEqual(adopted['next_action']['kind'], 'wait-fixer')
                self.assertEqual(self.state.read_bytes(), before)

    def test_source_contract_changes_are_part_of_identity(self):
        root = self.base / 'source'
        package = source_package(root)
        helper = package / 'scripts/continuous.py'
        spec = importlib.util.spec_from_file_location('source_contract_sweep',
                                                    helper.with_name('continuous_sweep.py'))
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        self.seed(helper)
        for relative in ('core/jobs/__init__.py', 'core/jobs/store.py',
                         'shared/job_coordinator.py', 'shared/worker_registry.py'):
            with self.subTest(contract=relative):
                path = root / relative
                original = path.read_bytes()
                before = self.state.read_bytes()
                try:
                    path.write_bytes(original + b'\n# Synthetic contract drift.\n')
                    self.assert_blocked(helper, adapter)
                finally:
                    path.write_bytes(original)
                    self.state.write_bytes(before)

    def test_status_reports_installed_tamper_without_saving_and_keeps_owned_stop(self):
        box = Sandbox(self.base / 'packages')
        package, _ = box.install('babysitter')
        helper = package / 'scripts/continuous.py'
        self.seed(helper)
        self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                 '--next-run-at', '2026-10-22T14:15:00Z', helper=helper)
        before = self.state.read_bytes()
        for relative in ('references/continuous.md', 'install-manifest.json'):
            path = package / relative
            original = path.read_bytes()
            try:
                path.write_bytes(original + (b'\nchanged\n' if relative.endswith('.md') else b'!'))
                report = self.cli('status', '--now', NOW, helper=helper)
                self.assertEqual(report['coverage'], 'continuation-blocked')
                self.assertEqual(report['package_identity_gap'][0]['kind'], 'package-integrity')
                self.assertIsNone(report['package']['running'])
                self.assertIsNone(report['scheduler']['next_run_at'])
                self.assertEqual(report['scheduler']['stop']['arguments']['scheduledTaskId'],
                                 'owned-schedule')
                self.assertEqual(report['prs'][URL]['next_action']['kind'], 'migration-required')
                self.assertEqual(self.state.read_bytes(), before)
            finally:
                path.write_bytes(original)

    def test_scheduler_reauthorization_is_blocked_but_demotion_stop_and_cancel_stay_available(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'scheduler-{index}.json'
            self.seed(helper)
            self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                     '--next-run-at', '2026-10-22T14:15:00Z', helper=helper)
            state = json.loads(self.state.read_text())
            state['package']['installed_digest'] = '0' * 64
            self.state.write_text(json.dumps(state))
            demoted = self.cli('scheduler', '--now', NOW, '--available', 'yes',
                               '--authorized', 'no', helper=helper)
            self.assertEqual(demoted['status'], 'event-only')
            self.assertEqual(demoted['scheduler_stop']['arguments']['scheduledTaskId'], 'owned-schedule')
            before = self.state.read_bytes()
            self.cli('scheduler', '--now', NOW, '--available', 'yes', '--authorized', 'yes',
                     helper=helper, ok=False)
            self.assertEqual(self.state.read_bytes(), before)
            self.cli('schedule-stop', '--now', NOW, '--schedule-id', 'owned-schedule',
                     '--verified', 'yes', helper=helper)
            stopped = self.state.read_bytes()
            self.cli('schedule-record', '--now', NOW, '--schedule-id', 'injected-schedule',
                     '--next-run-at', '2026-10-22T14:20:00Z', helper=helper, ok=False)
            self.assertEqual(self.state.read_bytes(), stopped)
            self.cli('cancel', '--now', NOW, '--reason', 'owner stop', helper=helper)
            final = json.loads(self.state.read_text())
            self.assertIsNone(final['scheduler']['schedule_id'])
            self.assertTrue(final['cancelled'])
            self.assertEqual(final['prs'], state['prs'])

    def test_policy_drift_allows_only_safe_late_reconciliation_and_disarm_even_after_cancel(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'late-policy-{index}.json'
            self.seed(helper)
            self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                     '--next-run-at', '2026-10-22T14:15:00Z', helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                     '--request-id', 'late-merge', '--head', H1, '--reserve', helper=helper)
            fixer_url = URL.replace('/12', '/14')
            request = f'late-policy-fixer-{index}'
            self.cli('dispatch', '--now', NOW, '--pr', fixer_url, '--kind', 'fixer',
                     '--request-id', request, '--head', H1, '--reserve', helper=helper)
            state = json.loads(self.state.read_text())
            state['policy_version'] = 'continuous-0'
            self.state.write_text(json.dumps(state))
            self.cli('scheduler', '--now', NOW, '--available', 'no', '--authorized', 'no',
                     helper=helper)
            self.cli('cancel', '--now', NOW, '--reason', 'owner stop', helper=helper)
            self.cli('schedule-stop', '--now', NOW, '--schedule-id', 'owned-schedule',
                     '--verified', 'yes', helper=helper)
            for url, kind, request_id, host in ((URL, 'merge', 'late-merge', 'merge-host'),
                                              (fixer_url, 'fixer', request, 'fixer-host')):
                self.assertTrue(self.cli('dispatch', '--now', NOW, '--pr', url, '--kind', kind,
                    '--request-id', request_id, '--host-task-id', host, helper=helper)['attached'])
            result = self.accepted_result(request, 'fixer-host')
            self.cli('fixer-done', '--now', NOW, '--pr', fixer_url, '--request-id', request,
                     '--host-task-id', 'fixer-host', '--result', str(result), helper=helper)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                     '--request-id', 'late-merge', '--host-task-id', 'merge-host',
                     '--status', 'cancelled', helper=helper)
            self.cli('resolve', '--now', NOW, '--pr', URL, '--head', H1,
                     '--resolution', 'closed', helper=helper)
            before = self.state.read_bytes()
            self.cli('dispatch', '--now', NOW, '--pr', fixer_url, '--kind', 'fixer',
                     '--request-id', 'new-work', '--head', H1, '--reserve', helper=helper, ok=False)
            self.cli('scheduler', '--now', NOW, '--available', 'yes', '--authorized', 'yes',
                     helper=helper, ok=False)
            self.assertEqual(self.state.read_bytes(), before)
            final = json.loads(before)
            self.assertEqual(final['policy_version'], 'continuous-0')
            self.assertEqual(final['prs'][URL]['state'], 'closed')
            self.assertFalse(final['prs'][fixer_url]['fixer']['in_flight'])
            self.assertTrue(final['prs'][URL.replace('/12', '/13')]['fixer']['in_flight'])
            self.assertTrue(final['cancelled'])
            self.assertIsNone(final['scheduler']['schedule_id'])

    def test_source_and_installed_missing_identity_digest_and_policy_refuse_all_continuations(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'identity-{index}.json'
            self.seed(helper)
            initial = self.state.read_bytes()
            state = json.loads(initial)
            for field, value in (('installed_digest', None), ('installed_digest', '0' * 64)):
                with self.subTest(helper=helper, value=value):
                    changed = deepcopy(state)
                    changed['package'][field] = value
                    self.state.write_text(json.dumps(changed))
                    self.assert_blocked(helper, adapter)
            changed = deepcopy(state)
            changed['policy_version'] = 'continuous-0'
            self.state.write_text(json.dumps(changed))
            self.assert_blocked(helper, adapter)
            self.state.write_bytes(initial)

    def test_unchanged_source_and_installed_packages_continue_each_wake_and_arm_once(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            for kind in ('schedule', 'event', 'manual'):
                self.state = self.base / f'valid-{index}-{kind}.json'
                self.start(helper=helper)
                host = FakeHost(observation(pr()))
                host.clock = NOW
                self.assertEqual(adapter.arm(host, self.state, NOW)['status'], 'armed')
                self.assertEqual(adapter.arm(host, self.state, NOW)['status'], 'already-scheduled')
                result = adapter.handle_wake(host, self.state, NOW,
                                             {'wake_id': 'valid', 'kind': kind})
                self.assertEqual(result['dispatched'][0]['status'], 'dispatched')
                self.assertEqual(len(host.created), 1)
                self.assertEqual(len(host.dispatched), 1)
                self.assertEqual(adapter.handle_wake(host, self.state, NOW,
                    {'wake_id': 'valid', 'kind': kind})['result']['status'], 'duplicate')
                self.assertEqual(len(host.dispatched), 1)

    def test_identity_is_checked_again_after_discovery_before_observation_changes_state(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'discovery-race-{index}.json'
            self.seed(helper)
            host = FakeHost(observation(pr()))
            state = json.loads(self.state.read_text())
            state['package']['installed_digest'] = '0' * 64
            changed = json.dumps(state).encode()

            def discover(scope, now):
                self.state.write_bytes(changed)
                return host.snapshot

            with patch.object(host, 'discover', side_effect=discover):
                with self.assertRaises(adapter.continuous.ContinuousError):
                    adapter.handle_wake(host, self.state, NOW,
                                        {'wake_id': 'changed-during-discovery', 'kind': 'event'})
            self.assertEqual(host.dispatched, [])
            self.assertEqual(self.state.read_bytes(), changed)

    def test_installed_content_manifest_and_policy_drift_stop_before_any_host_call(self):
        from shared.worker_registry import package_digest
        box = Sandbox(self.base / 'packages')
        package, _ = box.install('babysitter')
        helper = package / 'scripts/continuous.py'
        spec = importlib.util.spec_from_file_location('identity_installed_sweep',
                                                    package / 'scripts/continuous_sweep.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        self.seed(helper)
        manifest_path = package / 'install-manifest.json'
        doc = package / 'references/continuous.md'
        meta_path = package / 'plugin.json'
        originals = {path: path.read_bytes() for path in (manifest_path, doc, meta_path)}
        for case in ('valid-content-change', 'tampered-file', 'tampered-manifest',
                     'tampered-manifest-plugin', 'tampered-manifest-version',
                     'missing-manifest', 'unlisted-file', 'injected-symlink', 'valid-policy-change'):
            with self.subTest(case=case):
                manifest = json.loads(originals[manifest_path])
                if case in ('valid-content-change', 'tampered-file'):
                    doc.write_text(doc.read_text() + '\nSynthetic package change.\n')
                if case == 'valid-policy-change':
                    meta = json.loads(originals[meta_path])
                    meta['continuous']['policy_version'] = 'continuous-next'
                    meta_path.write_text(json.dumps(meta))
                if case.startswith('valid-'):
                    for entry in manifest['files']:
                        entry['sha256'] = hashlib.sha256((package / entry['path']).read_bytes()).hexdigest()
                    manifest['package_digest'] = package_digest(manifest)
                    manifest_path.write_text(json.dumps(manifest))
                elif case == 'tampered-manifest':
                    manifest['package_digest'] = '0' * 64
                    manifest_path.write_text(json.dumps(manifest))
                elif case.startswith('tampered-manifest-'):
                    manifest[case.removeprefix('tampered-manifest-')] = 'unrelated-package'
                    manifest_path.write_text(json.dumps(manifest))
                elif case == 'missing-manifest':
                    manifest_path.unlink()
                extra = package / 'unlisted.txt'
                if case == 'unlisted-file':
                    extra.write_text('Synthetic unlisted file.\n')
                elif case == 'injected-symlink':
                    extra.symlink_to(doc)
                self.assert_blocked(helper, adapter)
                extra.unlink(missing_ok=True)
                for path, data in originals.items():
                    path.write_bytes(data)

    def test_late_handles_and_accepted_results_reconcile_without_reopening_continuation(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'late-{index}.json'
            self.seed(helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                     '--request-id', 'late-merge', '--head', H1, '--reserve', helper=helper)
            fixer_url = URL.replace('/12', '/14')
            request = f'late-fixer-{index}'
            self.cli('dispatch', '--now', NOW, '--pr', fixer_url, '--kind', 'fixer',
                     '--request-id', request, '--head', H1, '--reserve', helper=helper)
            state = json.loads(self.state.read_text())
            state['package']['installed_digest'] = '0' * 64
            self.state.write_text(json.dumps(state))
            for url, kind, request_id, host in ((URL, 'merge', 'late-merge', 'merge-host'),
                                              (fixer_url, 'fixer', request, 'fixer-host')):
                self.assertTrue(self.cli('dispatch', '--now', NOW, '--pr', url, '--kind', kind,
                    '--request-id', request_id, '--host-task-id', host, helper=helper)['attached'])
            result = self.accepted_result(request, 'fixer-host')
            self.cli('fixer-done', '--now', NOW, '--pr', fixer_url, '--request-id', request,
                     '--host-task-id', 'fixer-host', '--result', str(result), helper=helper)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                     '--request-id', 'late-merge', '--host-task-id', 'merge-host',
                     '--status', 'cancelled', helper=helper)
            state = json.loads(self.state.read_text())
            self.assertFalse(state['prs'][fixer_url]['fixer']['in_flight'])
            self.assertTrue(state['prs'][URL.replace('/12', '/13')]['fixer']['in_flight'])
            self.assert_blocked(helper, adapter)


class InstalledImportIntegrityTest(ContinuousCase):
    def test_import_failures_report_integrity_and_block_continuation_before_host_calls(self):
        box = Sandbox(self.base / 'packages')
        package, manifest = box.install('babysitter')
        helper = package / 'scripts/continuous.py'
        WakeIdentityTest.seed(self, helper)
        self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                 '--next-run-at', '2026-10-22T14:15:00Z', helper=helper)
        before = self.state.read_bytes()
        snapshot = box.payload(observation(pr()))
        # A fresh process must import the installed contracts, without the test
        # runner's already-loaded source modules concealing damaged imports.
        probe = self.base / 'adapter_probe.py'
        probe.write_text('''import importlib.util
import json
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('installed_sweep', sys.argv[1])
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
state = Path(sys.argv[2])
before = state.read_bytes()
calls = []
class Host:
    def __getattr__(self, name):
        calls.append(name)
        raise AssertionError('host call before identity verification: ' + name)
host = Host()
errors = {}
operations = {'arm': lambda: adapter.arm(host, state, sys.argv[3]),
              'tick': lambda: adapter.tick(host, state, sys.argv[3])}
for kind in ('schedule', 'event', 'manual'):
    operations[kind] = lambda kind=kind: adapter.handle_wake(
        host, state, sys.argv[3], {'kind': kind, 'wake_id': 'damaged-' + kind})
for name, operation in operations.items():
    try:
        operation()
    except adapter.continuous.ContinuousError as exc:
        errors[name] = str(exc)
    else:
        raise AssertionError('damaged package continued: ' + name)
    assert state.read_bytes() == before
print(json.dumps({'errors': errors, 'host_calls': calls}))
''')
        listed = {entry['path'] for entry in manifest['files']}
        for relative in ('shared/worker_registry.py', 'core/jobs/store.py',
                         'shared/job_coordination.py'):
            path = package / relative
            self.assertIn(relative, listed)
            original = path.read_bytes()
            failures = ('missing', 'syntax', 'exports') if relative.endswith(
                'worker_registry.py') else ('missing', 'syntax')
            for failure in failures:
                with self.subTest(module=relative, failure=failure):
                    try:
                        if failure == 'missing':
                            path.unlink()
                        else:
                            path.write_bytes(b'def broken(:\n' if failure == 'syntax'
                                             else b'# Required exports are missing.\n')
                        status = box.run([sys.executable, helper, 'status', '--state',
                                          self.state, '--now', NOW])
                        self.assertNotIn('Traceback', status.stderr)
                        report = json.loads(status.stdout)
                        self.assertEqual(report['status'], 'continuation-blocked')
                        self.assertEqual(report['coverage'], 'continuation-blocked')
                        self.assertEqual(report['package_identity_gap'][0]['kind'],
                                         'package-integrity')
                        self.assertIn('installed package integrity failure',
                                      report['package_identity_gap'][0]['detail'])
                        self.assertIsNone(report['package']['running'])
                        self.assertIsNone(report['scheduler']['next_run_at'])
                        self.assertEqual(report['scheduler']['stop']['arguments']
                                         ['scheduledTaskId'], 'owned-schedule')
                        self.assertEqual(report['prs'][URL]['next_action']['kind'],
                                         'migration-required')
                        self.assertEqual(report['prs'][URL.replace('/12', '/13')]
                                         ['next_action']['kind'], 'wait-fixer')
                        commands = [('version', []), ('resume', ['--now', NOW]),
                            ('observe', ['--now', NOW, '--observation', snapshot]),
                            ('schedule-plan', []), ('schedule-record', ['--now', NOW,
                                '--schedule-id', 'injected', '--next-run-at', NOW]),
                            ('scheduler', ['--now', NOW, '--available', 'yes',
                                           '--authorized', 'yes'])]
                        commands.extend(('dispatch', ['--now', NOW, '--pr', URL,
                            '--kind', kind, '--request-id', 'blocked-' + kind,
                            '--head', H1, '--reserve']) for kind in
                            ('fixer', 'merge', 'update-branch', 'resolution'))
                        for command, flags in commands:
                            args = [] if command == 'version' else ['--state', self.state]
                            refused = box.run([sys.executable, helper, command, *args,
                                               *flags], check=False)
                            self.assertEqual(refused.returncode, 2, refused.stderr)
                            self.assertIn('continuous_error: installed package integrity failure:',
                                          refused.stderr)
                            self.assertNotIn('Traceback', refused.stderr)
                            self.assertEqual(self.state.read_bytes(), before)
                        result = box.run([sys.executable, probe,
                            helper.with_name('continuous_sweep.py'), self.state, NOW])
                        result = json.loads(result.stdout)
                        self.assertEqual(result['host_calls'], [])
                        self.assertEqual(set(result['errors']),
                                         {'arm', 'tick', 'schedule', 'event', 'manual'})
                        self.assertEqual(self.state.read_bytes(), before)
                    finally:
                        path.write_bytes(original)
        restored = json.loads(box.run([sys.executable, helper, 'version']).stdout)
        self.assertEqual(restored['digest'], manifest['package_digest'])
        self.assertEqual(self.cli('status', '--now', NOW, helper=helper)
                         ['package_identity_gap'], [])


class UnpinnedMigrationTest(ContinuousCase):
    def packages(self):
        box = Sandbox(self.base / 'packages')
        old, _ = box.install('babysitter')
        source = box.source_copy('babysitter')
        doc = source / 'plugins/babysitter/references/continuous.md'
        doc.write_text(doc.read_text() + '\nSynthetic package update.\n')
        new, _ = box.install('babysitter', source=source)
        self.state = self.base / 'run' / 'state.json'
        return box, old, new

    def decision(self, helper, decision_id='owner-migrate'):
        report = self.cli('resume', '--now', NOW, helper=helper)
        self.assertEqual(report['status'], 'migration-required')
        scope = report['owner_decision_scope']
        source = self.base / (decision_id + '.txt')
        quote = 'Approve this package migration: ' + scope
        source.write_text(quote)
        decision = {'id': decision_id, 'scope': scope, 'source': str(source),
                    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'quote': quote}
        path = self.base / (decision_id + '.json')
        path.write_text(json.dumps(decision))
        return path

    def migrate(self, helper, old, decision, *, ok=True, decision_id='owner-migrate', extra=()):
        return self.cli('resume', '--now', NOW, '--accept-migration',
            '--owner-decision-id', decision_id, '--previous-package', str(old),
            '--owner-decision', str(decision), *extra, helper=helper, ok=ok)

    def test_authorized_migration_restores_installed_wakes_and_keeps_existing_guards(self):
        _, old, new = self.packages()
        old_helper, helper = old / 'scripts/continuous.py', new / 'scripts/continuous.py'
        self.start(helper=old_helper)
        host = FakeHost(observation(pr(), pr(number=13, owner={
            'thread_id': 'self', 'status': 'running', 'fixer_in_flight': True,
            'host_task_id': 'adopted-live'})))
        spec = importlib.util.spec_from_file_location('migrated_installed_wake',
                                                    new / 'scripts/continuous_sweep.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                 '--next-run-at', '2026-10-22T14:15:00Z', helper=old_helper)
        self.cli('observe', '--now', NOW, '--wake-id', 'seed', helper=old_helper,
                 payload=host.snapshot)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                 '--request-id', 'live-merge', '--head', H1, '--reserve', helper=old_helper)
        before = json.loads(self.state.read_text())
        WakeIdentityTest.assert_blocked(self, helper, adapter)
        decision = self.decision(helper)
        self.migrate(helper, old, decision)
        migrated = json.loads(self.state.read_text())
        for field in ('run_id', 'scope', 'policy', 'scheduler', 'prs', 'events', 'discovery'):
            self.assertEqual(migrated[field], before[field], field)
        self.assertEqual(adapter.arm(host, self.state, NOW)['status'], 'already-scheduled')
        self.assertEqual(host.created, [])
        host.snapshot['prs'].append(pr(number=15))
        result = adapter.handle_wake(host, self.state, NOW,
                                    {'wake_id': 'after-migration', 'kind': 'schedule'})
        self.assertEqual([item['pr'] for item in host.dispatched], [URL.replace('/12', '/15')])
        self.assertEqual(result['dispatched'][0]['status'], 'dispatched')
        final = json.loads(self.state.read_text())
        self.assertEqual(final['scheduler']['schedule_id'], 'owned-schedule')
        self.assertEqual(final['prs'][URL]['dispatches'], before['prs'][URL]['dispatches'])
        self.assertEqual(final['prs'][URL.replace('/12', '/13')]['fixer'],
                         before['prs'][URL.replace('/12', '/13')]['fixer'])

    def test_real_installed_package_changes_preserve_schedule_progress_and_live_adopted_guards(self):
        box, old, new = self.packages()
        old_helper, helper = old / 'scripts/continuous.py', new / 'scripts/continuous.py'
        self.start(helper=old_helper)
        self.cli('schedule-record', '--now', NOW, '--schedule-id', 'owned-schedule',
                 '--next-run-at', '2026-10-22T14:15:00Z', helper=old_helper)
        rows = observation(pr(), pr(number=13, owner={'thread_id': 'self', 'status': 'running',
                                'fixer_in_flight': True, 'host_task_id': 'adopted-live'}),
                           pr(number=14))
        self.cli('observe', '--now', NOW, '--wake-id', 'before-upgrade', payload=rows, helper=old_helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge', '--request-id', 'live-merge',
                 '--head', H1, '--reserve', helper=old_helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge', '--request-id', 'live-merge',
                 '--host-task-id', 'merge-host', helper=old_helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL.replace('/12', '/14'), '--kind', 'fixer',
                 '--request-id', 'live-fixer', '--head', H1, '--reserve', helper=old_helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL.replace('/12', '/14'), '--kind', 'fixer',
                 '--request-id', 'live-fixer', '--host-task-id', 'fixer-host', helper=old_helper)
        before = json.loads(self.state.read_text())
        key = self.cli('schedule-plan', helper=old_helper)
        old_bytes = tree_digest(old)
        decision = self.decision(helper)
        resumed = self.migrate(helper, old, decision)
        self.assertEqual(resumed['status'], 'resumed')
        after = json.loads(self.state.read_text())
        for field in ('run_id', 'created_at', 'job_id', 'job', 'job_state_sha256', 'thread_id',
                      'scope', 'policy', 'scheduler', 'prs', 'events', 'discovery', 'cancelled'):
            self.assertEqual(after[field], before[field], field)
        self.assertIsNone(after['job_id'])
        resumed_plan = self.cli('schedule-plan', helper=helper)
        for field in ('status', 'schedule_id', 'next_run_at', 'stop'):
            self.assertEqual(resumed_plan.get(field), key.get(field), field)
        self.assertEqual(resumed_plan['request']['clientRequestId'], key['request']['clientRequestId'])
        self.assertEqual(resumed_plan['status'], 'already-scheduled')
        self.assertEqual(tree_digest(old), old_bytes)
        # Replaying the explicit migration writes nothing, including audit/progress clocks.
        migrated_bytes = self.state.read_bytes()
        self.assertEqual(self.migrate(helper, old, decision)['status'], 'duplicate')
        self.assertEqual(self.state.read_bytes(), migrated_bytes)
        for number in (12, 13, 14):
            refused = self.cli('dispatch', '--now', NOW, '--pr', URL.replace('/12', f'/{number}'),
                '--kind', 'fixer', '--request-id', 'racing-fixer', '--head', H1, '--reserve',
                helper=helper, ok=False)
            self.assertIn('may not race' if number == 12 else 'already in flight', refused.stderr)
        # A second real installation requires a new decision and retains both migrations.
        source = box.source_copy('babysitter')
        doc = source / 'plugins/babysitter/references/continuous.md'
        doc.write_text(doc.read_text() + '\nSecond synthetic package update.\n')
        third, manifest = box.install('babysitter', source=source)
        third_helper = third / 'scripts/continuous.py'
        stale = self.migrate(third_helper, old, decision, ok=False)
        self.assertIn('previous package identity', stale.stderr)
        decision2 = self.decision(third_helper, 'owner-migrate-2')
        before_second = self.state.read_bytes()
        self.migrate(third_helper, new, decision, ok=False)
        reused = json.loads(decision2.read_text())
        decision2.write_text(json.dumps({**reused, 'id': 'owner-migrate'}))
        self.migrate(third_helper, new, decision2, ok=False)
        self.assertEqual(self.state.read_bytes(), before_second)
        decision2.write_text(json.dumps(reused))
        self.migrate(third_helper, new, decision2, decision_id='owner-migrate-2')
        final = json.loads(self.state.read_text())
        self.assertEqual(final['prs'], before['prs'])
        self.assertEqual(final['scheduler'], before['scheduler'])
        self.assertEqual(len(final['migration_history']), 2)
        self.assertEqual(final['migration_history'][0], after['migration'])
        self.assertEqual(final['package']['installed_digest'], manifest['package_digest'])
        self.assertEqual(self.migrate(third_helper, new, decision2,
                                    decision_id='owner-migrate-2')['status'], 'duplicate')
        snapshot = self.state.read_bytes()
        self.migrate(third_helper, old, decision, ok=False)
        self.assertEqual(self.state.read_bytes(), snapshot)

    def test_adverse_owner_run_state_package_and_job_identities_leave_state_unchanged(self):
        _, old, new = self.packages()
        helper = new / 'scripts/continuous.py'
        self.start(helper=old / 'scripts/continuous.py')
        decision = self.decision(helper)
        valid = json.loads(decision.read_text())
        before = self.state.read_bytes()
        for field, value in (('id', 'another-owner'), ('scope', 'another-run'),
                             ('source_sha256', 'f' * 64), ('quote', 'not in source'),
                             ('source', str(self.state))):
            with self.subTest(field=field):
                decision.write_text(json.dumps({**valid, field: value}))
                self.migrate(helper, old, decision, ok=False)
                self.assertEqual(self.state.read_bytes(), before)
        decision.write_text(json.dumps(valid))
        for extra in (('--job', str(self.base / 'unrelated-job')),
                      ('--upgrade-receipt', str(decision)),
                      ('--package-version', '0.0.1')):
            self.migrate(helper, old, decision, ok=False, extra=extra)
            self.assertEqual(self.state.read_bytes(), before)
        self.migrate(helper, new, decision, ok=False)
        self.assertEqual(self.state.read_bytes(), before)
        # Same old digest on a different run, or changed progress on this run, needs fresh approval.
        state = json.loads(before)
        for patch_state in ({'run_id': 'different-run'}, {'updated_at': '2026-10-22T14:06:00Z'},
                            {'job_id': 'pinned-job'}, {'package': {'pinned_version': '1.3.0'}}):
            self.state.write_text(json.dumps({**state, **patch_state}))
            snapshot = self.state.read_bytes()
            self.migrate(helper, old, decision, ok=False)
            self.assertEqual(self.state.read_bytes(), snapshot)
        self.state.write_bytes(before)
        Path(valid['source']).write_text('changed owner evidence')
        self.migrate(helper, old, decision, ok=False)
        self.assertEqual(self.state.read_bytes(), before)

    def test_tampered_old_and_target_installed_packages_are_not_migration_authority(self):
        _, old, new = self.packages()
        helper = new / 'scripts/continuous.py'
        self.start(helper=old / 'scripts/continuous.py')
        decision = self.decision(helper)
        before = self.state.read_bytes()
        for package in (old, new):
            doc = package / 'references/continuous.md'
            original = doc.read_bytes()
            doc.write_text('tampered fixture')
            refused = self.migrate(helper, old, decision, ok=False)
            self.assertIn('integrity failure', refused.stderr)
            self.assertEqual(self.state.read_bytes(), before)
            doc.write_bytes(original)
        self.migrate(helper, old, decision)

    def test_cancelled_event_only_run_migrates_without_resuming_or_arming(self):
        _, old, new = self.packages()
        helper = new / 'scripts/continuous.py'
        self.start(helper=old / 'scripts/continuous.py', scheduler='event-only')
        self.cli('cancel', '--now', NOW, '--reason', 'owner stopped',
                 helper=old / 'scripts/continuous.py')
        before = json.loads(self.state.read_text())
        decision = self.decision(helper)
        self.assertEqual(self.migrate(helper, old, decision)['status'], 'cancelled')
        after = json.loads(self.state.read_text())
        self.assertEqual(after['scheduler'], before['scheduler'])
        self.assertEqual(after['cancelled'], before['cancelled'])
        self.assertEqual(self.cli('schedule-plan', helper=helper)['status'], 'cancelled')
        replay_bytes = self.state.read_bytes()
        self.assertEqual(self.migrate(helper, old, decision)['status'], 'cancelled')
        self.assertEqual(self.state.read_bytes(), replay_bytes)
        self.cli('resume', '--now', NOW, '--resume-cancelled', helper=helper)
        self.assertEqual(self.cli('schedule-plan', helper=helper)['status'], 'event-only')

    def test_previous_installed_helper_unpinned_state_recovers_without_job_or_schedule_reset(self):
        box = Sandbox(self.base / 'legacy-install')
        source = legacy_source(self.base, '17e636c1c24be77566f24062f93a8b1dc17d94c8')
        old, _ = install_legacy(box, source)
        current, _ = box.install('babysitter')
        self.state = self.base / 'run/state.json'
        self.start(helper=old / 'scripts/continuous.py')
        self.cli('schedule-record', '--now', NOW, '--schedule-id', 'legacy-schedule',
                 '--next-run-at', '2026-10-22T14:15:00Z', helper=old / 'scripts/continuous.py')
        before = json.loads(self.state.read_text())
        decision = self.decision(current / 'scripts/continuous.py')
        self.migrate(current / 'scripts/continuous.py', old, decision)
        after = json.loads(self.state.read_text())
        self.assertEqual(after['run_id'], before['run_id'])
        self.assertEqual(after['scheduler'], before['scheduler'])
        self.assertIsNone(after['job_id'])


class SourceIdentityTest(ContinuousCase):
    def test_real_legacy_source_fingerprint_requires_authorized_migration_and_keeps_guards(self):
        old_root = legacy_source(self.base, '17e636c1c24be77566f24062f93a8b1dc17d94c8')
        old = old_root / 'plugins/babysitter'
        target = source_package(self.base / 'target')
        old_helper, helper = old / 'scripts/continuous.py', target / 'scripts/continuous.py'
        self.state = self.base / 'run/state.json'
        self.start(helper=old_helper)
        self.cli('schedule-record', '--now', NOW, '--schedule-id', 'legacy-source-schedule',
                 '--next-run-at', '2026-10-22T14:15:00Z', helper=old_helper)
        self.cli('observe', '--now', NOW, '--wake-id', 'seed', helper=old_helper,
                 payload=observation(pr(number=13, owner={
                     'thread_id': 'self', 'status': 'running', 'fixer_in_flight': True,
                     'host_task_id': 'legacy-live'})))
        before = json.loads(self.state.read_text())
        self.assertEqual(before['package']['installed_digest'],
                         continuous_sweep.continuous.package_digest(old))
        self.assertNotIn('fingerprint_scheme', before['package'])
        preserved = self.state.read_bytes()
        self.cli('observe', '--now', NOW, '--wake-id', 'blocked', helper=helper,
                 payload=observation(pr()), ok=False)
        self.assertEqual(self.state.read_bytes(), preserved)
        decision = UnpinnedMigrationTest.decision(self, helper)
        UnpinnedMigrationTest.migrate(self, helper, old, decision)
        migrated = json.loads(self.state.read_text())
        self.assertEqual(migrated['package']['fingerprint_scheme'], 'source-contracts-1')
        for field in ('run_id', 'scheduler', 'prs', 'events', 'discovery'):
            self.assertEqual(migrated[field], before[field])
        self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['package_identity_gap'], [])
        self.cli('observe', '--now', NOW, '--wake-id', 'resumed', helper=helper,
                 payload=observation(pr(number=13)))
        self.assertTrue(json.loads(self.state.read_text())['prs'][URL.replace('/12', '/13')]
                        ['fixer']['in_flight'])

    def test_changed_source_contracts_need_retained_complete_source_and_owner_decision(self):
        old = source_package(self.base / 'old')
        target = source_package(self.base / 'target')
        contract = target.parents[1] / 'shared/worker_registry.py'
        contract.write_text(contract.read_text() + '\n# Synthetic new source contract.\n')
        helper = target / 'scripts/continuous.py'
        self.state = self.base / 'run/state.json'
        self.start(helper=old / 'scripts/continuous.py')
        before = json.loads(self.state.read_text())
        decision = UnpinnedMigrationTest.decision(self, helper)
        UnpinnedMigrationTest.migrate(self, helper, old, decision)
        self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['package_identity_gap'], [])
        migrated = json.loads(self.state.read_text())
        self.assertEqual(migrated['scheduler'], before['scheduler'])
        self.assertEqual(migrated['prs'], before['prs'])
        self.assertNotEqual(migrated['package']['installed_digest'], before['package']['installed_digest'])
        self.assertEqual(UnpinnedMigrationTest.migrate(self, helper, old, decision)['status'], 'duplicate')


class UpdateAndResolutionTest(ContinuousCase):
    def adapters(self):
        yield HELPER, continuous_sweep, HELPER.with_name('merge-pr.sh')
        package, _ = Sandbox(self.base / 'installed').install('babysitter')
        spec = importlib.util.spec_from_file_location('global9_installed_sweep',
                                                    package / 'scripts/continuous_sweep.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        yield package / 'scripts/continuous.py', adapter, package / 'scripts/merge-pr.sh'

    def row(self, shape, **kwargs):
        row = pr(required_contexts=['ci'], **kwargs)
        if shape == 'reader':
            row['head_oid'] = row.pop('head_sha')
            row.pop('checks')
            row.pop('required_contexts')
            row.update(pending_checks=[], failing=[], checks_complete=True,
                       required_contexts_known=False)
        return row

    def test_source_and_installed_adapter_update_is_reserved_before_helper_and_refreshes_gates(self):
        from tests import test_merge_pr as merge_fixture
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            for shape in ('full', 'reader'):
                with self.subTest(installed=index, shape=shape):
                    self.state = self.base / f'update-{index}-{shape}.json'
                    self.start(helper=helper)
                    test = self
                    initial_head, updated_head = merge_fixture.HEAD, 'b' * 40

                    class UpdateHost(FakeHost):
                        def dispatch(host, action, now):
                            state = json.loads(test.state.read_text())
                            row = state['prs'][URL]['dispatches'][-1]
                            test.assertEqual((row['kind'], row['status']), ('update-branch', 'reserved'))
                            for kind in ('fixer', 'merge', 'resolution', 'update-branch'):
                                refused = test.cli('dispatch', '--now', now, '--pr', URL,
                                    '--kind', kind, '--request-id', 'racing-' + kind,
                                    '--head', initial_head, '--reserve', helper=helper, ok=False)
                                test.assertIn('may not race', refused.stderr)
                            harness = merge_fixture.MergeTest()
                            harness.script = shell
                            result, calls = harness.run_helper('behind-then-green',
                                ['--update-only', '--expected-head', action['head']])
                            test.assertEqual(result.returncode, 0, result.stderr)
                            test.assertIn('UPDATED', result.stdout)
                            test.assertEqual([c for c in calls if not c.get('query')],
                                             [{'expected_head_sha': initial_head}])
                            test.assertFalse(any('mutation' in c.get('query', '') for c in calls))
                            return super().dispatch(action, now)

                    host = UpdateHost(observation(self.row(shape, head=initial_head,
                                                          merge_state='BEHIND')))
                    host.clock = '2026-10-22T14:00:00Z'
                    adapter.arm(host, self.state, host.clock)
                    result = adapter.tick(host, self.state, '2026-10-22T14:10:00Z')[0]
                    action = result['result']['actions'][0]
                    self.assertEqual(action['kind'], 'update-branch')
                    self.assertEqual(result['dispatched'][0]['recorded'], 'recorded')
                    self.assertEqual(len(host.dispatched), 1)
                    request = action['request_id']
                    again = adapter.tick(host, self.state, '2026-10-22T14:20:00Z')[0]
                    self.assertEqual(again['result']['actions'][0]['kind'], 'update-branch-pending')
                    self.assertEqual(len(host.dispatched), 1)
                    self.cli('observe', '--now', NOW, '--wake-id', 'early-green-new-head',
                        payload=observation(self.row(shape, head=updated_head)), helper=helper)
                    self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                             '--request-id', request, '--host-task-id', 'task-1',
                             '--status', 'succeeded', helper=helper)
                    self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                                     ['next_action']['kind'], 'wait-checks')
                    for head, checks_head, expected in (
                            (initial_head, initial_head, 'branch-update-refresh'),
                            (updated_head, initial_head, 'stale-head-checks')):
                        row = self.row(shape, head=head)
                        row['checks_head_sha'] = checks_head
                        report = self.cli('observe', '--now', NOW, '--wake-id', head,
                            payload=observation(row), helper=helper)
                        self.assertEqual(report['actions'][0]['blocked']['kind'], expected)
                        refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                            '--request-id', 'stale-landing', '--head', head, '--reserve',
                            helper=helper, ok=False)
                        self.assertIn('current action is wait-checks', refused.stderr)
                    fresh = self.cli('observe', '--now', NOW, '--wake-id', 'fresh',
                        payload=observation(self.row(shape, head=updated_head)), helper=helper)
                    self.assertEqual(fresh['actions'][0]['kind'], 'merge')
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'fresh-landing', '--head', updated_head, '--reserve', helper=helper)

    def test_update_reservation_rechecks_conflict_exclusion_ownership_and_inflight_writers(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'guards-{index}.json'
            self.start(helper=helper)
            for shape in ('full', 'reader'):
                for changed in (dict(mergeable='CONFLICTING'), dict(draft=True), dict(fork=True),
                                dict(owner={'thread_id': 'other', 'continuation': 'maintainer-live'})):
                    row = self.row(shape, merge_state='BEHIND', **changed)
                    self.cli('observe', '--now', NOW, '--wake-id', str(changed),
                             payload=observation(row), helper=helper)
                    before = self.state.read_bytes()
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                        '--request-id', 'retained-update', '--head', H1, '--reserve', helper=helper, ok=False)
                    self.assertEqual(self.state.read_bytes(), before)
                    self.cli('observe', '--now', NOW, '--wake-id', 'release-' + str(changed),
                        payload=observation(self.row(shape, merge_state='BEHIND',
                            owner={'thread_id': 'other', 'continuation': 'released'})), helper=helper)
            baseline = self.state.read_bytes()
            for kind in ('fixer', 'resolution', 'merge'):
                self.state.write_bytes(baseline)
                # A landing reserved on a clean head also excludes a later update.
                if kind == 'merge':
                    self.cli('observe', '--now', NOW, '--wake-id', 'clean',
                             payload=observation(pr()), helper=helper)
                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                    '--request-id', 'writer', '--head', H1, '--reserve', helper=helper)
                self.cli('observe', '--now', NOW, '--wake-id', 'behind',
                         payload=observation(pr(merge_state='BEHIND')), helper=helper)
                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                    '--request-id', 'racing-update', '--head', H1, '--reserve', helper=helper, ok=False)

    def test_uncertain_update_keeps_its_reservation_until_matching_host_receipt(self):
        class LostUpdateHost(FakeHost):
            def dispatch(self, action, now):
                super().dispatch(action, now)
                raise TimeoutError('update response lost')

        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'lost-update-{index}.json'
            self.start(helper=helper)
            host = LostUpdateHost(observation(pr(merge_state='BEHIND')))
            result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event'})
            request = result['result']['actions'][0]['request_id']
            report = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
            self.assertEqual(report['next_action']['dispatch_status'], 'uncertain')
            host.snapshot = observation(pr(head=H2))
            result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event', 'wake_id': 'new-head'})
            self.assertEqual(result['result']['actions'][0]['kind'], 'update-branch-pending')
            self.assertEqual(len(host.dispatched), 1)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', request, '--host-task-id', 'recovered-update', helper=helper)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', request, '--status', 'cancelled', helper=helper, ok=False)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', request, '--host-task-id', 'recovered-update',
                '--status', 'cancelled', helper=helper)
            self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                             ['next_action']['kind'], 'merge')

    def test_real_update_helper_receipts_hold_same_head_and_reconcile_fresh_heads_in_both_adapters(self):
        from tests.test_merge_pr import MergeTest, HEAD
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            for mode in ('update-accepted', 'update-response-lost', 'update-rejected', 'behind-then-green'):
                with self.subTest(installed=index, mode=mode):
                    self.state = self.base / f'transport-{index}-{mode}.json'
                    self.start(helper=helper)
                    test = self

                    class UpdateHost(FakeHost):
                        def dispatch(host, action, now):
                            saved = json.loads(test.state.read_text())['prs'][URL]['dispatches'][-1]
                            test.assertEqual(saved['status'], 'reserved')
                            harness = MergeTest()
                            harness.script = shell
                            result, calls = harness.run_helper(mode,
                                ['--update-only', '--expected-head', action['head']],
                                repo='fixture/widgets', number=12)
                            test.assertEqual([c for c in calls if not c.get('query')],
                                             [{'expected_head_sha': HEAD}])
                            test.assertFalse(any('mutation' in c.get('query', '') for c in calls))
                            super().dispatch(action, now)
                            host.helper_result = {'request_id': action['request_id'],
                                                  'returncode': result.returncode, 'stdout': result.stdout}
                            return {'helper_result': host.helper_result}

                    host = UpdateHost(observation(self.row('reader', head=HEAD, merge_state='BEHIND')))
                    result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event'})
                    request = result['result']['actions'][0]['request_id']
                    saved = json.loads(self.state.read_text())['prs'][URL]['dispatches'][0]
                    expected = {'update-rejected': 'rejected', 'behind-then-green': 'succeeded'}.get(mode, 'uncertain')
                    self.assertEqual(saved['status'], expected)
                    self.assertEqual(saved['update_outcome'], {
                        'update-accepted': 'accepted', 'update-response-lost': 'unknown',
                        'update-rejected': 'rejected', 'behind-then-green': 'updated'}[mode])
                    self.assertEqual(result['dispatched'][0]['status'], expected)
                    if expected == 'rejected':
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                            '--request-id', 'confirmed-rejection-retry', '--head', HEAD,
                            '--reserve', helper=helper)
                        continue
                    if expected == 'succeeded':
                        old = adapter.handle_wake(host, self.state, NOW,
                                                 {'kind': 'event', 'wake_id': 'old-head'})
                        self.assertEqual(old['result']['actions'][0]['blocked']['kind'], 'branch-update-refresh')
                        self.assertEqual(len(host.dispatched), 1)
                    for wake in (('same-head-1', 'same-head-2') if expected == 'uncertain' else ()):
                        again = adapter.handle_wake(host, self.state, NOW,
                                                     {'kind': 'event', 'wake_id': wake})
                        self.assertEqual(again['result']['actions'][0]['kind'], 'update-branch-pending')
                        self.assertEqual(len(host.dispatched), 1)
                        self.assertEqual(len(json.loads(self.state.read_text())['prs'][URL]['dispatches']), 1)
                        for kind in ('update-branch', 'merge', 'fixer', 'resolution'):
                            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                                '--request-id', wake + kind, '--head', HEAD, '--reserve',
                                helper=helper, ok=False)
                    transport = self.base / 'update-result.json'
                    transport.write_text(json.dumps(host.helper_result))
                    before = self.state.read_bytes()
                    for status in (('failed', 'cancelled', 'superseded', 'no-change', 'succeeded', 'rejected')
                                   if expected == 'uncertain' else ()):
                        for flags in ([], ['--result', str(transport)]):
                            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                                '--request-id', request, '--head', HEAD, '--status', status,
                                *flags, helper=helper, ok=False)
                            self.assertEqual(self.state.read_bytes(), before)
                    # A new head settles the synchronous PUT, but old-head check
                    # evidence must still block landing at that new head.
                    updated = 'b' * 40
                    stale = self.row('reader', head=updated)
                    stale['checks_head_sha'] = HEAD
                    host.snapshot = observation(stale)
                    later = adapter.handle_wake(host, self.state, NOW,
                                               {'kind': 'event', 'wake_id': 'new-head'})
                    self.assertEqual(later['result']['actions'][0]['blocked']['kind'], 'stale-head-checks')
                    self.assertEqual(len(host.dispatched), 1)
                    self.assertEqual(json.loads(self.state.read_text())['prs'][URL]
                                     ['dispatches'][0]['status'], 'succeeded')
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'stale-merge', '--head', updated, '--reserve', helper=helper, ok=False)
                    fresh = self.cli('observe', '--now', NOW, '--wake-id', 'fresh-new-head',
                        payload=observation(self.row('reader', head=updated)), helper=helper)
                    self.assertEqual(fresh['actions'][0]['kind'], 'merge')
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'fresh-merge', '--head', updated, '--reserve', helper=helper)
                    # Replaying the pending transport cannot reopen a settled update.
                    replay = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                        '--request-id', request, '--status', 'uncertain', '--result', str(transport), helper=helper)
                    self.assertEqual(replay['status'], 'stale')

    def test_uncertain_put_accepts_only_a_matching_confirmed_rejection(self):
        from tests.test_merge_pr import MergeTest, HEAD
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            self.state = self.base / f'confirmed-{index}.json'
            self.start(helper=helper)
            self.cli('observe', '--now', NOW,
                payload=observation(pr(head=HEAD, merge_state='BEHIND')), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                     '--request-id', 'put-1', '--head', HEAD, '--reserve', helper=helper)
            before = self.state.read_bytes()
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'failed', helper=helper, ok=False)
            self.assertEqual(self.state.read_bytes(), before)
            harness = MergeTest()
            harness.script = shell
            receipts = {}
            for mode in ('update-accepted', 'update-rejected'):
                result, _ = harness.run_helper(mode, ['--update-only', '--expected-head', HEAD],
                                              repo='fixture/widgets', number=12)
                receipts[mode] = {'request_id': 'put-1', 'returncode': result.returncode,
                                  'stdout': result.stdout}
            transport = self.base / 'confirmed-result.json'
            transport.write_text(json.dumps(receipts['update-accepted']))
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'uncertain', '--result', str(transport), helper=helper)
            for wrong in ('fixture/widgets#99', 'update_head=' + H1, 'wrong-request'):
                original = 'fixture/widgets#12' if '#' in wrong else 'update_head=' + HEAD
                bad = {**receipts['update-rejected'],
                       'stdout': receipts['update-rejected']['stdout'].replace(original, wrong)}
                if wrong == 'wrong-request':
                    bad = {**receipts['update-rejected'], 'request_id': wrong}
                transport.write_text(json.dumps(bad))
                before = self.state.read_bytes()
                self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                    '--request-id', 'put-1', '--status', 'rejected', '--result', str(transport), helper=helper, ok=False)
                self.assertEqual(self.state.read_bytes(), before)
            transport.write_text(json.dumps(receipts['update-rejected']))
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'rejected', '--result', str(transport), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-2', '--head', HEAD, '--reserve', helper=helper)
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                '--request-id', 'put-1', '--status', 'rejected', '--result', str(transport), helper=helper)
            saved = json.loads(self.state.read_text())['prs'][URL]['dispatches']
            self.assertEqual([row['status'] for row in saved], ['rejected', 'reserved'])
            # A host refusal before launching the helper is also a confirmed no-write.
            refused = adapter._close_dispatch(self.state, NOW,
                {'pr': URL, 'kind': 'update-branch', 'head': HEAD, 'request_id': 'put-2'},
                'rejected', 'host confirmed that the helper was never launched')
            self.assertEqual(refused['dispatch']['status'], 'rejected')

    def test_terminal_wrapper_does_not_prove_the_same_head_put_was_rejected(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'wrapper-{index}.json'
            self.start(helper=helper)
            self.cli('observe', '--now', NOW,
                payload=observation(pr(merge_state='BEHIND')), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                     '--request-id', 'wrapper', '--head', H1, '--reserve', helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                     '--request-id', 'wrapper', '--host-task-id', 'update-task', helper=helper)
            before = self.state.read_bytes()
            for status in ('failed', 'cancelled', 'rejected', 'succeeded', 'superseded', 'no-change'):
                self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                    '--request-id', 'wrapper', '--host-task-id', 'update-task',
                    '--status', status, helper=helper, ok=False)
                self.assertEqual(self.state.read_bytes(), before)

    def test_real_no_put_outcomes_settle_in_source_and_installed_adapters(self):
        from tests.test_merge_pr import MergeTest, HEAD
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            for mode, outcome in (('merged', 'merged'), ('closed', 'closed'),
                                  ('clean', 'not_behind'), ('conflict', 'conflict'),
                                  ('author-pushed', 'expected_head_mismatch')):
                with self.subTest(installed=index, mode=mode):
                    self.state = self.base / f'no-put-{index}-{mode}.json'
                    self.start(helper=helper)
                    test = self

                    class NoPutHost(FakeHost):
                        def dispatch(host, action, now):
                            saved = json.loads(test.state.read_text())['prs'][URL]['dispatches'][-1]
                            test.assertEqual(saved['status'], 'reserved')
                            harness = MergeTest()
                            harness.script = shell
                            result, calls = harness.run_helper(mode,
                                ['--update-only', '--expected-head', HEAD],
                                repo='fixture/widgets', number=12)
                            test.assertTrue(calls)
                            test.assertTrue(all(c.get('query', '').startswith('query') for c in calls))
                            super().dispatch(action, now)
                            return {'helper_result': {'request_id': action['request_id'],
                                'returncode': result.returncode, 'stdout': result.stdout}}

                    host = NoPutHost(observation(self.row('reader', head=HEAD, merge_state='BEHIND')))
                    result = adapter.handle_wake(host, self.state, NOW, {'kind': 'event'})
                    saved = json.loads(self.state.read_text())['prs'][URL]
                    self.assertEqual(result['dispatched'][0]['status'], 'no-change')
                    self.assertEqual(saved['dispatches'][0]['update_outcome'], outcome)
                    self.assertEqual(saved['dispatches'][0]['status'], 'no-change')
                    terminal = outcome in ('merged', 'closed')
                    self.assertEqual(saved['state'], outcome if terminal else 'open')
                    self.assertEqual(saved['next_action']['kind'], outcome if terminal else 'wait-checks')
                    if terminal:
                        self.assertIsNone(saved['blocked'])
                    else:
                        self.assertEqual(saved['blocked']['kind'], 'branch-update-refresh')
                    # Fresh same-head CLEAN evidence clears a no-PUT refresh. A
                    # completed update still requires a new head (covered above).
                    fresh = self.row('reader', head=HEAD,
                        state=outcome.upper() if terminal else 'OPEN')
                    report = self.cli('observe', '--now', NOW, '--wake-id', 'fresh-no-put',
                                      payload=observation(fresh), helper=helper)
                    after = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                    self.assertEqual(after['state'], outcome if terminal else 'open')
                    self.assertEqual(after['next_action']['kind'], outcome if terminal else 'merge')
                    self.assertEqual(len(after['dispatches']), 1)
                    self.assertEqual(len(host.dispatched), 1)
                    if not terminal:
                        self.assertEqual(report['actions'][0]['kind'], 'merge')
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                            '--request-id', 'fresh-landing', '--head', HEAD, '--reserve', helper=helper)

    def test_terminal_reads_close_lifecycle_but_preserve_unknown_launches_and_live_handles(self):
        from tests.test_merge_pr import MergeTest, HEAD
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            harness = MergeTest()
            harness.script = shell
            result, _ = harness.run_helper('update-accepted',
                ['--update-only', '--expected-head', HEAD], repo='fixture/widgets', number=12)
            transport = self.base / 'terminal-read-result.json'
            transport.write_text(json.dumps({'request_id': 'update',
                'returncode': result.returncode, 'stdout': result.stdout}))
            for terminal in ('merged', 'closed'):
                for via in ('observe', 'resolve'):
                    for launch in ('synchronous', 'attached', 'unknown-launch'):
                        with self.subTest(installed=index, terminal=terminal, via=via, launch=launch):
                            self.state = self.base / f'terminal-{index}-{terminal}-{via}-{launch}.json'
                            self.start(helper=helper)
                            self.cli('observe', '--now', NOW,
                                payload=observation(pr(head=HEAD, merge_state='BEHIND')), helper=helper)
                            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                                '--request-id', 'update', '--head', HEAD, '--reserve', helper=helper)
                            if launch == 'attached':
                                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                                    '--request-id', 'update', '--host-task-id', 'live-update', helper=helper)
                            flags = [] if launch == 'unknown-launch' else ['--result', str(transport)]
                            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'update-branch',
                                '--request-id', 'update', '--status', 'uncertain', *flags, helper=helper)
                            before = self.state.read_bytes()
                            if via == 'observe':
                                self.cli('observe', '--now', NOW, '--wake-id', 'terminal-read',
                                    payload=observation(pr(head=HEAD, state=terminal.upper(), draft=True)),
                                    helper=helper)
                            else:
                                self.cli('resolve', '--now', NOW, '--pr', URL, '--resolution', terminal,
                                    '--head', H2, helper=helper, ok=False)
                                self.assertEqual(self.state.read_bytes(), before)
                                self.cli('resolve', '--now', NOW, '--pr', URL, '--resolution', terminal,
                                    '--head', HEAD, helper=helper)
                            saved = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                            self.assertEqual(saved['state'], terminal)
                            self.assertEqual(saved['dispatches'][0]['status'],
                                             'superseded' if launch == 'synchronous' else 'uncertain')
                            self.assertEqual(saved['next_action']['kind'],
                                             terminal if launch == 'synchronous' else 'update-branch-pending')
                            self.assertIsNone(json.loads(self.state.read_text())['prs'][URL]['excluded'])
                            self.assertNotIn(URL, self.cli('status', '--now', NOW, helper=helper)['open_prs'])
                            if launch != 'synchronous':
                                # Explicit reopen does not discard the original exclusion.
                                self.cli('observe', '--now', NOW, '--wake-id', 'reopen',
                                    payload=observation(pr(head=HEAD)), helper=helper)
                                for kind in ('fixer', 'merge', 'resolution', 'update-branch'):
                                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                                        '--request-id', 'race-' + kind, '--head', HEAD, '--reserve',
                                        helper=helper, ok=False)

    def test_update_result_matrix_requires_identity_and_preserves_prior_uncertain_puts(self):
        for _, adapter, _ in self.adapters():
            module = adapter.continuous
            row = {'request_id': 'update', 'head': H1}
            target = {'repo': 'fixture/widgets', 'number': 12}
            blocked = 'BLOCKED fixture/widgets#12 reason={} blockers={} detail={} automerge=unavailable'
            cases = [
                (0, f'UPDATED fixture/widgets#12 previous_head={H1} head={H2} refresh_gates=required', 'succeeded', 'updated'),
                (0, 'MERGED fixture/widgets#12 via preexisting', 'no-change', 'merged'),
            ]
            for reason in ('closed', 'not_behind', 'conflict', 'expected_head_mismatch'):
                detail = (f'PR head {H2} is not the expected head {H1}; refresh'
                          if reason == 'expected_head_mismatch' else 'no PUT sent')
                cases.append((4, blocked.format(reason, reason, detail), 'no-change', reason))
            for reason, outcome, status in (('update_pending', 'accepted', 'uncertain'),
                    ('update_pending', 'unknown', 'uncertain'), ('update_rejected', 'rejected', 'rejected')):
                cases.append((4, blocked.format(reason, reason,
                    f'update_head={H1} update_outcome={outcome} fixture outcome'), status, outcome))
            for code, stdout, status, outcome in cases:
                with self.subTest(code=code, stdout=stdout):
                    result = {'request_id': 'update', 'returncode': code, 'stdout': stdout}
                    self.assertEqual(module.update_helper_receipt(target, row, result), (status, outcome))
                    for bad in ({**result, 'request_id': 'other'},
                                {**result, 'stdout': stdout.replace('widgets#12', 'widgets#99')},
                                {**result, 'returncode': 3}, {**result, 'stdout': stdout + '\nnoise'}):
                        self.assertEqual(module.update_helper_receipt(target, row, bad), ('uncertain', 'unknown'))
            for outcome in ('accepted', 'unknown'):
                previous = {**row, 'update_outcome': outcome}
                for reason in ('not_behind', 'conflict', 'expected_head_mismatch'):
                    detail = (f'PR head {H2} is not the expected head {H1}; refresh'
                              if reason == 'expected_head_mismatch' else 'no PUT sent')
                    result = {'request_id': 'update', 'returncode': 4,
                              'stdout': blocked.format(reason, reason, detail)}
                    self.assertEqual(module.update_helper_receipt(target, previous, result),
                                     ('uncertain', outcome))
            for code, stdout in ((0, ''), (2, ''), (3, ''), (4, ''),
                                 (0, f'UPDATED fixture/widgets#12 previous_head={H1} head={H1} refresh_gates=required')):
                self.assertEqual(module.update_helper_receipt(target, row,
                    {'request_id': 'update', 'returncode': code, 'stdout': stdout}), ('uncertain', 'unknown'))

    def test_live_resolution_is_next_action_until_matching_terminal_receipt_in_both_adapters(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            for shape in ('full', 'reader'):
                self.state = self.base / f'resolution-{index}-{shape}.json'
                self.start(helper=helper)
                host = FakeHost(observation(self.row(shape, threads=1)))
                host.clock = '2026-10-22T14:00:00Z'
                adapter.arm(host, self.state, host.clock)
                self.cli('observe', '--now', NOW, '--wake-id', 'threads',
                    payload=host.snapshot, helper=helper)
                self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                    '--request-id', 'reply-1', '--head', H1, '--reserve', helper=helper)
                for status in ('reserved', 'uncertain', 'pending'):
                    if status == 'uncertain':
                        self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                            '--request-id', 'reply-1', '--status', 'uncertain', helper=helper)
                    if status == 'pending':
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                            '--request-id', 'reply-1', '--host-task-id', 'reply-host', helper=helper)
                    host.snapshot = observation(self.row(shape, head=H2))
                    result = adapter.handle_wake(host, self.state, NOW,
                                                {'kind': 'event', 'wake_id': status})
                    action = result['result']['actions'][0]
                    self.assertEqual((action['kind'], action['request_id'], action['dispatch_status']),
                                     ('resolution-pending', 'reply-1', status))
                    self.assertEqual(action['host_task_id'], 'reply-host' if status == 'pending' else None)
                    self.assertEqual(host.dispatched, [])
                    report = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                    for key in ('kind', 'request_id', 'host_task_id', 'dispatch_status'):
                        self.assertEqual(report['next_action'][key], action[key])
                    self.assertEqual(report['dispatches'][0]['status'], status)
                before = self.state.read_bytes()
                for request, kind, handle in (('wrong', 'resolution', 'reply-host'),
                                              ('reply-1', 'merge', 'reply-host'),
                                              ('reply-1', 'resolution', 'wrong'),
                                              ('reply-1', 'resolution', None)):
                    flags = ['--host-task-id', handle] if handle else []
                    self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', request, '--status', 'succeeded', *flags, helper=helper, ok=False)
                    self.assertEqual(self.state.read_bytes(), before)
                # Exclusion and explicit lifecycle close never erase the live request.
                self.cli('observe', '--now', NOW, '--wake-id', 'excluded',
                    payload=observation(self.row(shape, head=H2, draft=True)), helper=helper)
                self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                                 ['next_action']['kind'], 'resolution-pending')
                if shape == 'reader':
                    self.cli('resolve', '--now', NOW, '--pr', URL, '--resolution', 'closed',
                             '--head', H2, helper=helper)
                self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                                 ['dispatches'][0]['status'], 'pending')
                self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                    '--request-id', 'reply-1', '--host-task-id', 'reply-host', '--status', 'succeeded',
                    helper=helper)
                settled = self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                if shape == 'full':
                    self.assertIsNone(settled['next_action'])
                    self.assertEqual(settled['state'], 'excluded')
                fresh = self.cli('observe', '--now', NOW, '--wake-id', 'released',
                    payload=observation(self.row(shape, head=H2)), helper=helper)
                self.assertEqual(fresh['actions'][0]['kind'], 'merge')

    def test_cancelled_run_keeps_live_resolution_visible_without_proposing_followup_on_receipt(self):
        for index, (helper, _, _) in enumerate(self.adapters()):
            self.state = self.base / f'cancel-resolution-{index}.json'
            self.start(helper=helper)
            self.cli('observe', '--now', NOW, payload=observation(pr()), helper=helper)
            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                     '--request-id', 'reply', '--reserve', helper=helper)
            self.cli('cancel', '--now', NOW, '--reason', 'owner stopped', helper=helper)
            self.assertEqual(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]
                             ['next_action']['kind'], 'resolution-pending')
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'resolution',
                     '--request-id', 'reply', '--status', 'cancelled', helper=helper)
            self.assertIsNone(self.cli('status', '--now', NOW, helper=helper)['prs'][URL]['next_action'])


class UnclockedQueueSafetyTest(ContinuousCase):
    adapters = UpdateAndResolutionTest.adapters
    reader_row = continuous_tests.ReaderPathTest.reader_row
    node = continuous_tests.ReaderPathTest.node

    def test_mixed_reader_queues_keep_unknown_reasons_in_public_diagnosis_and_status(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'mixed-queue-{index}.json'
            self.start(helper=helper)
            checks = [
                {'__typename': 'CheckRun', 'name': 'known', 'status': 'QUEUED',
                 'startedAt': None, 'conclusion': None,
                 'detailsUrl': 'https://github.com/fixture/repo/actions/runs/1/job/7'},
                {'__typename': 'CheckRun', 'name': 'unknown', 'status': 'QUEUED',
                 'startedAt': None, 'conclusion': None,
                 'detailsUrl': 'https://ci.example.invalid/build/7'},
            ]
            row = self.reader_row({'data': {'viewer': {'login': 'fixture'}, 'search': {
                'issueCount': 1, 'nodes': [self.node(checks=checks, checks_state='PENDING')]}}},
                job_payload={'created_at': '2026-10-22T12:00:00Z', 'head_sha': H1},
                reader=helper.with_name('list-prs.sh'))
            gaps = [{'name': 'unknown', 'reason': 'detailsUrl does not identify an Actions job'}]
            self.assertEqual(row['queue_clock_gaps'], gaps)
            host = FakeHost(observation(row))
            host.clock = '2026-10-22T14:00:00Z'
            adapter.arm(host, self.state, host.clock)
            for at, age in [('2026-10-22T14:10:00Z', 7800), ('2026-10-22T14:20:00Z', 8400)]:
                result = adapter.tick(host, self.state, at)[0]['result']
                action = result['actions'][0]
                self.assertEqual(action['kind'], 'diagnose-queue')
                self.assertEqual(action['blocked']['check'], 'known')
                self.assertEqual(action['blocked']['age_seconds'], age)
                self.assertEqual(action['blocked']['queue_clock_gaps'], gaps)
                self.assertIn(gaps[0]['reason'], action['reason'])
                self.assertIn('unknown', action['reason'])
                public = self.cli('status', '--now', at, helper=helper)['prs'][row['url']]['queue']
                for view in (result['queue'][0], public):
                    self.assertEqual(view['name'], 'known')
                    self.assertEqual(view['age_seconds'], age)
                    self.assertEqual(view['unknown_clock'], ['unknown'])
                    self.assertEqual(view['queue_clock_gaps'], gaps)
                saved = json.loads(self.state.read_text())['prs'][row['url']]
                self.assertEqual(saved['observation']['queue_clock_gaps'], gaps)
                self.assertEqual(saved['queue']['queue_clock_gaps'], gaps)
                self.assertEqual(saved['last_meaningful_progress_at'], '2026-10-22T14:10:00Z')
                self.assertEqual(result['human_questions'], [])
                self.assertGreater(action['next_check_at'], at)
            self.assertEqual(host.dispatched, [])

    def test_clockless_stall_is_not_hidden_by_other_incomplete_gates(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'clockless-gates-{index}.json'
            self.start(helper=helper)
            initial = json.loads(self.state.read_text())
            for gap in ({'checks_complete': False}, {'review_threads_complete': False},
                        {'review_decision': 'REVIEW_REQUIRED'}, {'merge_state_status': 'UNSTABLE'}):
                with self.subTest(installed=index, gap=gap):
                    state = deepcopy(initial)
                    row = pr(checks=[{'name': 'third-party', 'status': 'QUEUED'}],
                             merge_state='BLOCKED', checks_state='PENDING')
                    row.update(gap)
                    module = adapter.continuous
                    module.reconcile_observation(state, observation(row),
                        module.parse_time('2026-10-22T14:10:00Z'), 'first', 'schedule')
                    result = module.reconcile_observation(state, observation(row),
                        module.parse_time('2026-10-22T14:55:00Z'), 'stalled', 'schedule')
                    self.assertEqual(result['actions'][0]['kind'], 'diagnose-stall')
                    self.assertEqual(state['prs'][row['url']]['queue']['oldest'], None)

    def test_unchanged_unclocked_checks_reach_stall_on_source_and_installed_timer_wakes(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            with self.subTest(installed=index):
                self.state = self.base / f'unclocked-{index}.json'
                self.start(helper=helper)
                row = pr(checks=[{'name': 'third-party', 'status': 'QUEUED',
                                  'conclusion': None}], merge_state='BLOCKED', checks_state='PENDING')
                host = FakeHost(observation(row))
                host.clock = '2026-10-22T14:00:00Z'
                adapter.arm(host, self.state, host.clock)
                first = adapter.tick(host, self.state, '2026-10-22T14:10:00Z')[0]['result']
                self.assertEqual(first['actions'][0]['blocked']['kind'], 'queue-age-unknown')
                for at, elapsed in [('2026-10-22T14:20:00Z', 600),
                                    ('2026-10-22T14:40:00Z', 1800),
                                    ('2026-10-22T16:10:00Z', 7200)]:
                    result = adapter.tick(host, self.state, at)[0]['result']
                    action = result['actions'][0]
                    self.assertEqual(action['kind'], 'wait-checks' if elapsed < 1800
                                     else 'diagnose-stall')
                    self.assertEqual(action['blocked']['kind'], 'queue-age-unknown' if elapsed < 1800
                                     else 'stalled-work')
                    self.assertIn('queue age is unknown', action['reason'])
                    if elapsed >= 1800:
                        self.assertIn(f'no meaningful progress for {elapsed}s', action['reason'])
                    self.assertGreater(action['next_check_at'], at)
                    self.assertEqual(result['human_questions'], [])
                    self.assertFalse(result['progress']['meaningful'])
                    saved = json.loads(self.state.read_text())['prs'][row['url']]
                    self.assertEqual(saved['last_meaningful_progress_at'], '2026-10-22T14:10:00Z')
                    self.assertIsNone(saved['queue']['oldest'])
                    self.assertIsNone(saved['queue']['pending'][0]['age_seconds'])
                    self.assertFalse(saved['queue']['pending'][0]['age_known'])
                self.assertEqual(len(host.created), 1)
                self.assertEqual(host.dispatched, [])

    def test_reader_clock_gap_reasons_survive_wakes_and_do_not_starve_repairs(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            with self.subTest(installed=index):
                self.state = self.base / f'reader-gaps-{index}.json'
                self.start(helper=helper)
                checks = [
                    {'__typename': 'CheckRun', 'name': 'third-party', 'status': 'QUEUED',
                     'conclusion': None, 'startedAt': None,
                     'detailsUrl': 'https://ci.example.invalid/build/7'},
                    {'__typename': 'CheckRun', 'name': 'actions-clockless', 'status': 'QUEUED',
                     'conclusion': None, 'startedAt': None,
                     'detailsUrl': 'https://github.com/fixture/repo/actions/runs/1/job/7'},
                ]
                payload = {'data': {'viewer': {'login': 'fixture'}, 'search': {'issueCount': 1,
                    'nodes': [self.node(checks=checks, checks_state='PENDING')]}}}
                # Execute the source/installed reader itself, including its failed clock lookup.
                row = self.reader_row(payload, reader=helper.with_name('list-prs.sh'))
                gaps = [{'name': 'third-party', 'reason': 'detailsUrl does not identify an Actions job'},
                        {'name': 'actions-clockless', 'reason': 'Actions job API returned no created_at'}]
                self.assertCountEqual(row['queue_clock_gaps'], gaps)
                host = FakeHost(observation(row))
                host.clock = '2026-10-22T14:00:00Z'
                adapter.arm(host, self.state, host.clock)
                for at, kind in [('2026-10-22T14:10:00Z', 'wait-checks'),
                                 ('2026-10-22T14:55:00Z', 'diagnose-stall'),
                                 ('2026-10-22T16:10:00Z', 'diagnose-stall')]:
                    result = adapter.tick(host, self.state, at)[0]['result']
                    action = result['actions'][0]
                    self.assertEqual(action['kind'], kind)
                    self.assertEqual(action['blocked']['queue_clock_gaps'], row['queue_clock_gaps'])
                    for gap in gaps:
                        self.assertIn(gap['name'], action['reason'])
                        self.assertIn(gap['reason'], action['reason'])
                    saved = json.loads(self.state.read_text())['prs'][row['url']]
                    self.assertEqual(saved['observation']['queue_clock_gaps'], row['queue_clock_gaps'])
                    self.assertEqual(saved['queue']['queue_clock_gaps'], row['queue_clock_gaps'])
                    self.assertIsNone(saved['queue']['oldest'])
                    self.assertTrue(all(check['age_seconds'] is None for check in saved['queue']['pending']))
                    self.assertGreater(action['next_check_at'], at)
                    self.assertEqual(saved['last_meaningful_progress_at'], '2026-10-22T14:10:00Z')
                    if kind == 'diagnose-stall':
                        self.assertFalse(result['progress']['meaningful'])
                    # Clock-gap metadata and its ordering are evidence, not check progress.
                    row['queue_clock_gaps'] = [dict(gap) for gap in reversed(gaps)]
                    row['queue_clock_gaps'][0]['reason'] += '; retry still has no clock'

                # Another PR can repair while this PR remains stalled.
                host.snapshot = observation(row, pr(number=13, threads=1))
                independent = adapter.tick(host, self.state, '2026-10-22T16:20:00Z')[0]
                self.assertEqual(independent['result']['actions'][0]['kind'], 'diagnose-stall')
                self.assertEqual(independent['dispatched'][0]['action']['kind'], 'dispatch-fixer')
                self.assertEqual(independent['dispatched'][0]['recorded'], 'recorded')
                # A newly actionable failure on the queued PR also takes priority over diagnosis.
                row['failing'] = ['lint']
                row['checks_state'] = 'FAILURE'
                repaired = adapter.tick(host, self.state, '2026-10-22T16:30:00Z')[0]
                action = repaired['dispatched'][0]['action']
                self.assertEqual(action['pr'], row['url'])
                self.assertEqual(action['kind'], 'dispatch-fixer')
                self.assertIn('lint', action['reason'])
                self.assertEqual(repaired['result']['human_questions'], [])
                self.assertEqual(len(host.dispatched), 2)
                self.assertEqual(len(host.created), 1)


class MergeGateContractTest(ContinuousCase):
    adapters = UpdateAndResolutionTest.adapters
    row = UpdateAndResolutionTest.row

    def test_merge_state_rollup_review_and_mergeability_matrix_matches_landing_contract(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'merge-matrix-{index}.json'
            self.start(helper=helper)
            initial = json.loads(self.state.read_text())
            module = adapter.continuous
            for shape in ('full', 'reader'):
                for merge_state in ('CLEAN', 'UNSTABLE', 'BEHIND', 'BLOCKED', 'HAS_HOOKS',
                                    'UNKNOWN', 'DIRTY', 'DRAFT', '', None):
                    for mergeable in ('MERGEABLE', 'UNKNOWN', 'CONFLICTING'):
                        for rollup in ('SUCCESS', 'EXPECTED', 'PENDING', 'FAILURE', 'ERROR', None):
                            for review in ('APPROVED', 'REVIEW_REQUIRED', 'CHANGES_REQUESTED'):
                                with self.subTest(installed=index, shape=shape, merge_state=merge_state,
                                                  mergeable=mergeable, rollup=rollup, review=review):
                                    raw = self.row(shape, merge_state=merge_state,
                                                   mergeable=mergeable, checks_state=rollup)
                                    raw.update(required_contexts_observed=['ci'], review_decision=review)
                                    state = deepcopy(initial)
                                    action = module.reconcile_observation(state, observation(raw),
                                        module.parse_time(NOW), 'matrix', 'event')['actions'][0]
                                    eligible = mergeable == 'MERGEABLE' and review == 'APPROVED'
                                    landing = eligible and (merge_state == 'UNSTABLE'
                                                             or (merge_state == 'CLEAN' and rollup == 'SUCCESS'))
                                    updating = eligible and merge_state == 'BEHIND' and rollup == 'SUCCESS'
                                    self.assertEqual(action['kind'] == 'merge', landing)
                                    self.assertEqual(action['kind'] == 'update-branch', updating)
                                    if not landing and not updating:
                                        self.assertIn('next_check_at', action)
                                    self.assertEqual(state['prs'][URL]['dispatches'], [])

    def test_unstable_requires_nonempty_verified_required_contexts_in_both_shapes(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            self.state = self.base / f'required-matrix-{index}.json'
            self.start(helper=helper)
            initial = json.loads(self.state.read_text())
            module = adapter.continuous
            for shape in ('full', 'reader'):
                for required in (None, [], ['ci']):
                    for complete in (False, True):
                        for conclusion in ('SUCCESS', 'NEUTRAL', 'SKIPPED', 'FAILURE', None):
                            with self.subTest(installed=index, shape=shape, required=required,
                                              complete=complete, conclusion=conclusion):
                                check = {'name': 'ci', 'status': 'COMPLETED' if conclusion else 'PENDING',
                                         'conclusion': conclusion, 'head_sha': H1}
                                raw = self.row(shape, merge_state='UNSTABLE', checks_state='FAILURE')
                                raw.update(required_contexts=None, required_contexts_observed=required,
                                           required_contexts_known=False, checks_complete=complete)
                                if shape == 'full':
                                    raw['checks'] = [check]
                                else:
                                    raw['failing'] = ['ci'] if conclusion == 'FAILURE' else []
                                    raw['pending_checks'] = [check] if conclusion is None else []
                                action = module.reconcile_observation(deepcopy(initial), observation(raw),
                                    module.parse_time(NOW), 'required', 'event')['actions'][0]
                                self.assertEqual(action['kind'] == 'merge',
                                    bool(required) and complete and conclusion in ('SUCCESS', 'NEUTRAL', 'SKIPPED'))
            for configured, seen in ((['ci'], None), (['ci'], []), (['ci', 'missing'], ['ci'])):
                raw = self.row('reader', merge_state='UNSTABLE', checks_state='FAILURE')
                raw.update(required_contexts=configured, required_contexts_known=True,
                           required_contexts_observed=seen)
                action = module.reconcile_observation(deepcopy(initial), observation(raw),
                    module.parse_time(NOW), 'configured-only', 'event')['actions'][0]
                self.assertEqual(action['kind'], 'wait-checks')
                self.assertEqual(action['blocked']['kind'], 'unverified-required-checks')

    def test_hooks_remain_a_blocker_without_dispatching_or_spending_landing_attempts(self):
        from tests.test_merge_pr import MergeTest
        for index, (helper, adapter, shell) in enumerate(self.adapters()):
            harness = MergeTest()
            harness.script = shell
            result, calls = harness.run_helper('state-has_hooks', ['--no-auto'])
            self.assertEqual(result.returncode, 4)
            self.assertIn('reason=not_clean', result.stdout)
            self.assertTrue(all(c.get('query', '').startswith('query') for c in calls))
            for shape in ('full', 'reader'):
                self.state = self.base / f'hooks-{index}-{shape}.json'
                self.start(helper=helper)
                host = FakeHost(observation(self.row(shape, merge_state='HAS_HOOKS')))
                for wake in range(4):
                    report = adapter.handle_wake(host, self.state, NOW,
                                                {'kind': 'event', 'wake_id': f'hooks-{wake}'})
                    action = report['result']['actions'][0]
                    self.assertEqual((action['kind'], action['blocked']['kind']), ('diagnose-gate', 'has-hooks'))
                    self.assertIn('next_check_at', action)
                    self.assertEqual(report['dispatched'], [])
                    before = self.state.read_bytes()
                    self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'invalid-landing', '--head', H1, '--reserve', helper=helper, ok=False)
                    self.assertEqual(self.state.read_bytes(), before)
                self.assertEqual(json.loads(self.state.read_text())['prs'][URL]['dispatches'], [])
                host.snapshot = observation(self.row(shape))
                clean = adapter.handle_wake(host, self.state, NOW, {'kind': 'event', 'wake_id': 'clean'})
                self.assertEqual(clean['result']['actions'][0]['kind'], 'merge')
                self.assertEqual(len(host.dispatched), 1)


class ReservationSafetyTest(ContinuousCase):
    def reserve(self, kind, request, **kwargs):
        return self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', request, '--head', H1, '--reserve', **kwargs)

    def test_red_required_check_cannot_reserve_a_merge_or_block_its_fixer(self):
        self.start()
        red = pr(merge_state='BLOCKED', checks_state='FAILURE', required_contexts=['lint'],
                 checks=[{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE',
                          'head_sha': H1}])
        action = self.observe(NOW, observation(red), wake='red')['actions'][0]
        self.assertEqual(action['kind'], 'dispatch-fixer')
        before = self.state.read_bytes()
        refused = self.reserve('merge', 'stale-merge', ok=False)
        self.assertIn('current action is dispatch-fixer', refused.stderr)
        self.assertEqual(self.state.read_bytes(), before)
        reserved = self.reserve('fixer', action['request_id'])
        self.assertTrue(reserved['fixer']['in_flight'])

    def test_merge_dispatch_rechecks_gates_after_a_green_action_at_the_same_head(self):
        self.start()
        green = self.observe(NOW, observation(pr()), wake='green')['actions'][0]
        for index, changed in enumerate((
                pr(threads=1), pr(checks_state='PENDING', checks=[{
                    'name': 'ci', 'status': 'QUEUED', 'created_at': NOW}]),
                {**pr(), 'checks_complete': False},
                {**pr(), 'review_threads_complete': False},
                pr(merge_state=None))):
            with self.subTest(changed=changed):
                self.observe(NOW, observation(changed), wake=f'gate-{index}')
                before = self.state.read_bytes()
                # Both reserve-before-launch and the legacy direct-record path must
                # reject an action retained from the earlier green observation.
                for reserve in (('--reserve',), ()):
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', green['request_id'], '--head', H1, *reserve, ok=False)
                    self.assertIn('current action is', refused.stderr)
                    self.assertEqual(self.state.read_bytes(), before)

    def test_installed_helper_rejects_unknown_and_red_gates_but_keeps_a_green_landing_lock(self):
        box = Sandbox(self.base / 'installed')
        package, manifest = box.install('babysitter')
        source_version = json.loads((continuous_tests.PLUGIN / 'plugin.json').read_text())['version']
        self.assertEqual(manifest['version'].partition('+')[0], source_version)
        self.assertEqual(manifest['version'], package.name)
        self.assertEqual(manifest['version'],
                         json.loads((package / 'install-manifest.json').read_text())['version'])
        self.assertEqual(json.loads((package / 'plugin.json').read_text())['version'],
                         json.loads((continuous_tests.PLUGIN / 'plugin.json').read_text())['version'])
        helper = package / 'scripts/continuous.py'
        self.start(helper=helper)
        for index, gate in enumerate((None, '', 'UNKNOWN', 'BLOCKED')):
            row = pr(merge_state=gate)
            if gate == 'BLOCKED':
                row.update(checks_state='FAILURE', required_contexts=['lint'], checks=[{
                    'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE', 'head_sha': H1}])
            result = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
                '--wake-id', f'installed-{index}', payload=observation(row), helper=helper)
            self.assertEqual(result['actions'][0]['kind'],
                             'dispatch-fixer' if gate == 'BLOCKED' else 'diagnose-gate')
            before = self.state.read_bytes()
            refused = self.reserve('merge', 'bad-merge', helper=helper, ok=False)
            self.assertIn('current action is', refused.stderr)
            self.assertEqual(self.state.read_bytes(), before)
        self.cli('observe', '--now', NOW, '--wake-kind', 'event', '--wake-id', 'green',
                 payload=observation(pr()), helper=helper)
        self.reserve('merge', 'green-merge', helper=helper)
        self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                 '--request-id', 'green-merge', '--status', 'armed', helper=helper)
        refused = self.reserve('fixer', 'racing-fixer', helper=helper, ok=False)
        self.assertIn('a fixer may not race', refused.stderr)

    def test_reservation_rechecks_exclusion_ownership_and_closed_lifecycle(self):
        self.start()
        action = self.observe(NOW, observation(pr()), wake='green')['actions'][0]
        for index, changed in enumerate((pr(draft=True), pr(fork=True),
                pr(owner={'thread_id': 'other', 'status': 'running'}), pr(state='CLOSED'))):
            self.observe(NOW, observation(changed), wake=f'changed-{index}')
            before = self.state.read_bytes()
            refused = self.reserve('merge', action['request_id'], ok=False)
            self.assertRegex(refused.stderr, 'eligible|owned elsewhere')
            self.assertEqual(self.state.read_bytes(), before)
            self.observe(NOW, observation(pr(owner={'thread_id': 'other',
                'continuation': 'handed-back'})), wake=f'release-{index}')

    def test_resolution_reservations_exclude_every_other_write(self):
        self.start()
        self.observe(NOW, observation(pr()), wake='green')
        for first in ('resolution', 'merge', 'fixer'):
            for second in ('resolution', 'merge', 'fixer'):
                state = self.base / f'{first}-{second}.json'
                state.write_bytes(self.state.read_bytes())
                self.reserve(first, 'first', state=state)
                refused = self.reserve(second, 'second', state=state, ok=False)
                self.assertRegex(refused.stderr, 'race|in flight|pending')

    def test_lost_response_keeps_actual_started_writer_held_then_attaches_matching_handle(self):
        class LostResponseHost(FakeHost):
            def dispatch(self, action, now):
                super().dispatch(action, now)  # side effect succeeded; response was lost
                raise TimeoutError('lost response')

        host = LostResponseHost(observation(pr(checks=[{
            'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}])))
        host.clock = '2026-10-22T14:00:00Z'
        self.start()
        continuous_sweep.arm(host, self.state, host.clock)
        delivered = continuous_sweep.tick(host, self.state, '2026-10-22T14:10:00Z')
        action = delivered[0]['dispatched'][0]['action']
        self.assertEqual(len(host.dispatched), 1)
        green = self.observe('2026-10-22T14:11:00Z', observation(pr()), wake='green')
        self.assertEqual(green['actions'][0]['kind'], 'wait-fixer')
        fixture = AcceptedJob(self.base / 'recovered-job', action['request_id'], 'recovered-host')
        attached = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'fixer',
                            '--request-id', action['request_id'], '--host-task-id', fixture.host)
        self.assertTrue(attached['attached'])
        fixture.complete()
        self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', action['request_id'],
                 '--host-task-id', fixture.host, '--result', str(fixture.transport))
        self.assertEqual(self.observe(NOW, observation(pr()), wake='done')['actions'][0]['kind'], 'merge')


class AcceptedReceiptTest(ContinuousCase):
    adapters = UpdateAndResolutionTest.adapters

    def test_every_terminal_history_is_immutable_before_replay_validation_in_both_packages(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            fixture = AcceptedJob(self.base / f'accepted-replay-{index}', 'original', 'host-original')
            fixture.complete()
            for kind in ('merge', 'fixer', 'resolution', 'update-branch'):
                for terminal in sorted(adapter.continuous.TERMINAL_DISPATCH):
                    with self.subTest(installed=index, kind=kind, terminal=terminal):
                        self.state = self.base / f'terminal-{index}-{kind}-{terminal}.json'
                        self.start(helper=helper)
                        row = pr(merge_state='BEHIND' if kind == 'update-branch' else 'CLEAN')
                        self.cli('observe', '--now', NOW, '--wake-id', 'initial',
                                 payload=observation(row), helper=helper)
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                            '--request-id', 'original', '--head', H1, '--reserve', helper=helper)
                        flags = []
                        if kind == 'update-branch' and terminal in ('succeeded', 'no-change'):
                            result = self.base / 'update-terminal.json'
                            output = (f'UPDATED fixture/widgets#12 previous_head={H1} head={H2} '
                                      'refresh_gates=required' if terminal == 'succeeded'
                                      else 'MERGED fixture/widgets#12 via preexisting')
                            result.write_text(json.dumps({'request_id': 'original',
                                'returncode': 0, 'stdout': output}))
                            flags = ['--result', str(result)]
                        elif kind != 'update-branch' or terminal != 'rejected':
                            self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                                '--request-id', 'original', '--host-task-id', fixture.host, helper=helper)
                            flags = ['--host-task-id', fixture.host]
                            if kind == 'update-branch':
                                self.cli('observe', '--now', NOW, '--wake-id', 'new-head',
                                    payload=observation(pr(head=H2)), helper=helper)
                            if kind == 'fixer':
                                flags += ['--result', str(fixture.transport)]
                        command = 'fixer-done' if kind == 'fixer' and terminal == 'succeeded' else 'receipt'
                        receipt_flags = [] if command == 'fixer-done' else ['--kind', kind, '--status', terminal]
                        self.cli(command, '--now', '2026-10-22T14:06:00Z', '--pr', URL,
                            '--request-id', 'original', *receipt_flags, *flags, helper=helper)
                        saved = json.loads(self.state.read_text())['prs'][URL]
                        self.assertEqual(saved['dispatches'][0]['status'], terminal)
                        if kind == 'fixer' and terminal in ('succeeded', 'no-change'):
                            self.assertEqual(saved['last_meaningful_progress_at'], '2026-10-22T14:06:00Z')
                        # A later writer must remain protected from the entire old receipt history.
                        if saved['state'] == 'open':
                            self.cli('dispatch', '--now', '2026-10-22T14:07:00Z', '--pr', URL,
                                '--kind', 'fixer', '--request-id', 'later-writer', '--reserve', helper=helper)
                        before = self.state.read_bytes()
                        for replay in (*sorted(adapter.continuous.TERMINAL_DISPATCH), 'uncertain', 'armed'):
                            result = self.cli('receipt', '--now', '2026-10-22T14:30:00Z', '--pr', URL,
                                '--kind', kind, '--request-id', 'original', '--status', replay,
                                '--reason', 'replayed history', *flags, helper=helper)
                            self.assertEqual(result['status'], 'duplicate' if replay == terminal else 'stale')
                            self.assertFalse(result['changed'])
                            self.assertEqual(self.state.read_bytes(), before)
                        # Replays do not need old evidence to remain readable or validate again.
                        result = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', kind,
                            '--request-id', 'original', '--status', 'uncertain', '--result',
                            str(self.base / 'missing-result.json'), '--host-task-id', 'unrelated',
                            '--head', H2, helper=helper)
                        self.assertEqual(result['status'], 'stale')
                        self.assertEqual(self.state.read_bytes(), before)

    def test_adopted_identity_can_be_filled_but_never_replaced_and_needs_ingested_result(self):
        self.start()
        owner = {'thread_id': 'self', 'status': 'running', 'fixer_in_flight': True}
        self.observe(NOW, observation(pr(owner=owner)), wake='no-handle')
        owner['host_task_id'] = 'task-live'
        self.observe(NOW, observation(pr(owner=owner)), wake='identified')
        guard = json.loads(self.state.read_text())['prs'][URL]['fixer']
        self.assertEqual(guard['host_task_id'], 'task-live')
        self.observe(NOW, observation(pr(owner={**owner, 'thread_id': 'new-writer',
                                                'host_task_id': 'different-task'})), wake='other')
        self.assertEqual(json.loads(self.state.read_text())['prs'][URL]['fixer']['host_task_id'], 'task-live')
        bogus = self.base / 'bogus.txt'
        bogus.write_text('not a task result')
        before = self.state.read_bytes()
        refused = self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', 'unrelated',
                           '--host-task-id', 'task-live', '--result', str(bogus), ok=False)
        self.assertIn('accepted job', refused.stderr)
        self.assertEqual(self.state.read_bytes(), before)
        fixture = AcceptedJob(self.base / 'job', 'real-request', 'task-live')
        raw_result = fixture.box.private / 'unaccepted.json'
        raw_result.write_text(worker_result(fixture.brief))
        premature = self.cli('fixer-done', '--now', NOW, '--pr', URL,
            '--request-id', 'real-request', '--host-task-id', fixture.host,
            '--job', str(fixture.directory), '--result', str(raw_result), ok=False)
        self.assertIn('job-retained transport', premature.stderr)
        fixture.complete()
        wrong = self.cli('fixer-done', '--now', NOW, '--pr', URL,
            '--request-id', 'unrelated', '--host-task-id', fixture.host,
            '--result', str(fixture.transport), ok=False)
        self.assertIn('job-retained transport', wrong.stderr)
        self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', 'real-request',
                 '--host-task-id', fixture.host, '--result', str(fixture.transport))
        self.assertFalse(json.loads(self.state.read_text())['prs'][URL]['fixer']['in_flight'])

    def test_malformed_ingested_result_cannot_release_an_adopted_guard(self):
        fixture = AcceptedJob(self.base / 'job', 'real-request', 'task-live')
        fixture.complete(malformed=True)
        self.start()
        self.observe(NOW, observation(pr(owner={'thread_id': 'self', 'status': 'running',
            'fixer_in_flight': True, 'host_task_id': fixture.host})), wake='adopt')
        refused = self.cli('fixer-done', '--now', NOW, '--pr', URL, '--request-id', 'real-request',
            '--host-task-id', fixture.host, '--result', str(fixture.transport), ok=False)
        self.assertIn('no matching accepted', refused.stderr)
        # A correlated terminal malformed ingestion is a failed attempt, so routine
        # retry can proceed without pretending that the worker is still running.
        failed = self.cli('receipt', '--now', NOW, '--pr', URL, '--request-id', 'real-request',
            '--host-task-id', fixture.host, '--result', str(fixture.transport), '--status', 'failed',
            '--kind', 'fixer')
        self.assertFalse(failed['fixer']['in_flight'])

    def test_partial_owner_status_never_erases_identity_or_continuation(self):
        self.start()
        self.observe(NOW, observation(pr(owner={'thread_id': 'other', 'status': 'running',
            'continuation': 'maintainer-live'})), wake='live')
        partial = self.observe(NOW, observation(pr(owner={'status': 'completed'})), wake='partial')
        self.assertEqual(partial['actions'][0]['kind'], 'owned-elsewhere')
        owner = json.loads(self.state.read_text())['prs'][URL]['owner']
        self.assertEqual((owner['thread_id'], owner['continuation']), ('other', 'maintainer-live'))
        unknown = self.observe(NOW, observation(pr(owner={'status': 'completed',
            'thread_id': None, 'continuation': None})), wake='null-fields')
        self.assertEqual(unknown['actions'][0]['kind'], 'owned-elsewhere')


class OwnershipReleaseTest(ContinuousCase):
    STATUSES = (
        'active', 'preparing', 'queued', 'starting', 'running', 'waiting',
        'parked', 'idle', 'completed', 'failed', 'interrupted', 'cancelled',
        'rolled_back', 'stopped', 'handed-back', 'released', 'none',
        'unfamiliar-status', '', None, 'STOPPED', 'CANCELLED',
    )
    RELEASES = ('handed-back', 'released', 'none', 'stopped', 'cancelled')

    def test_status_continuation_matrix_requires_explicit_release_before_reservation(self):
        continuous = continuous_sweep.continuous
        self.start()
        initial = self.state.read_bytes()
        snapshot = self.base / 'owner-matrix.json'
        continuations = ({}, *({'continuation': value} for value in (
            None, '', 'maintainer-live', 'watching', 'unknown', 'still-maintaining',
            'RELEASED', *self.RELEASES)))
        for status in self.STATUSES:
            for continuation in continuations:
                with self.subTest(status=status, **continuation):
                    self.state.write_bytes(initial)
                    snapshot.write_text(json.dumps(observation(pr(owner={
                        'thread_id': 'other', 'status': status, **continuation}))))
                    result = continuous.cmd_observe(Namespace(state=str(self.state), now=NOW,
                        observation=str(snapshot), wake_id='matrix', wake_kind='event'))
                    released = continuation.get('continuation') in self.RELEASES
                    self.assertEqual(result['actions'][0]['kind'],
                                     'merge' if released else 'owned-elsewhere')
                    owner = json.loads(self.state.read_text())['prs'][URL]['owner']
                    self.assertEqual(owner['thread_id'], 'other')
                    before = self.state.read_bytes()
                    for kind in ('merge', 'fixer', 'resolution'):
                        args = Namespace(state=str(self.state), now=NOW, pr=URL, kind=kind,
                            request_id=f'takeover-{kind}', head=H1, reserve=True,
                            host_task_id=None, attempt=None, review_triage=False)
                        if released:
                            reserved = continuous.cmd_dispatch(args)
                            self.assertEqual(reserved['status'], 'recorded')
                            self.state.write_bytes(before)
                        else:
                            with self.assertRaisesRegex(continuous.ContinuousError, 'owned elsewhere'):
                                continuous.cmd_dispatch(args)
                            self.assertEqual(self.state.read_bytes(), before)

    def test_partial_terminal_updates_preserve_identity_and_live_continuation(self):
        self.start()
        for status in ('idle', 'completed', 'failed', 'interrupted', 'cancelled',
                       'rolled_back', 'stopped', 'handed-back', 'released'):
            for fields in ({}, {'thread_id': None},
                           {'thread_id': None, 'continuation': None}, {'continuation': ''}):
                with self.subTest(status=status, fields=fields):
                    self.observe(NOW, observation(pr(owner={'thread_id': 'other',
                        'status': 'running', 'continuation': 'maintainer-live',
                        'host_task_id': 'maintainer-task'})), wake=f'live-{status}-{fields}')
                    still = self.observe(NOW, observation(pr(owner={'status': status, **fields})),
                                         wake=f'partial-{status}-{fields}')
                    self.assertEqual(still['actions'][0]['kind'], 'owned-elsewhere')
                    owner = json.loads(self.state.read_text())['prs'][URL]['owner']
                    self.assertEqual((owner['thread_id'], owner['continuation'], owner['host_task_id']),
                                     ('other', 'maintainer-live', 'maintainer-task'))

    def test_installed_helper_refuses_terminal_status_takeover_until_explicit_handoff(self):
        box = Sandbox(self.base / 'installed')
        package, _ = box.install('babysitter')
        helper = package / 'scripts/continuous.py'
        self.start(helper=helper)
        for status in ('completed', 'failed', 'interrupted', 'cancelled', 'rolled_back',
                       'stopped', 'handed-back', 'released'):
            for continuation in ({}, {'continuation': 'maintainer-live'},
                                 {'continuation': 'still-maintaining'}):
                result = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
                    '--wake-id', f'installed-{status}-{continuation}',
                    payload=observation(pr(owner={'thread_id': 'other', 'status': status,
                                                  **continuation})), helper=helper)
                self.assertEqual(result['actions'][0]['kind'], 'owned-elsewhere')
                before = self.state.read_bytes()
                for kind in ('merge', 'fixer', 'resolution'):
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', f'takeover-{kind}', '--head', H1, '--reserve',
                        helper=helper, ok=False)
                    self.assertIn('owned elsewhere', refused.stderr)
                    self.assertEqual(self.state.read_bytes(), before)
        released = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
            '--wake-id', 'verified-handoff', payload=observation(pr(owner={
                'status': 'stopped', 'continuation': 'handed-back'})), helper=helper)
        self.assertEqual(released['actions'][0]['kind'], 'merge')
        self.assertEqual(json.loads(self.state.read_text())['prs'][URL]['owner']['thread_id'], 'other')
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', released['actions'][0]['request_id'], '--head', H1,
            '--reserve', helper=helper)


class MergeCompletionSafetyTest(ContinuousCase):
    adapters = UpdateAndResolutionTest.adapters

    def wake(self, adapter, host, name, at=NOW):
        return adapter.handle_wake(host, self.state, at, {'kind': 'event', 'wake_id': name})

    def finish(self, helper, action, status):
        self.cli('receipt', '--now', '2026-10-22T14:06:00Z', '--pr', URL, '--kind', 'merge',
            '--request-id', action['request_id'], '--host-task-id', f'task-{action["attempt"]}',
            '--status', status, helper=helper)

    def test_superseded_and_mixed_terminal_retries_share_the_head_budget_in_both_adapters(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            for statuses in (('superseded',) * 3, ('rejected', 'failed', 'cancelled'),
                             ('superseded', 'cancelled', 'rejected'),
                             ('rejected', 'superseded', 'succeeded'),
                             ('failed', 'cancelled', 'no-change')):
                with self.subTest(installed=index, statuses=statuses):
                    self.state = self.base / f'merge-budget-{index}-{statuses[0]}-{statuses[1]}.json'
                    self.start(helper=helper)
                    host = FakeHost(observation(pr()))
                    for attempt, status in enumerate(statuses, 1):
                        result = self.wake(adapter, host, f'attempt-{attempt}')
                        action = result['result']['actions'][0]
                        self.assertEqual(action['kind'], 'merge')
                        self.assertTrue(action['request_id'].endswith(f'-a{attempt}'))
                        self.assertEqual(result['dispatched'][0]['recorded'], 'recorded')
                        self.finish(helper, {**action, 'attempt': attempt}, status)
                    for wake in range(3):
                        result = self.wake(adapter, host, f'exhausted-{wake}')
                        self.assertEqual(result['result']['actions'][0]['blocked']['kind'],
                            'merge-observation-required' if statuses[-1] in ('succeeded', 'no-change')
                            else 'merge-rejected')
                        self.assertEqual(result['dispatched'], [])
                    # A real reopen permits reconciliation, but cannot reset the same-head budget.
                    host.snapshot = observation(pr(state='CLOSED'))
                    self.wake(adapter, host, 'closed', '2026-10-22T14:07:00Z')
                    host.snapshot = observation(pr())
                    reopened = self.wake(adapter, host, 'reopened', '2026-10-22T14:08:00Z')
                    self.assertEqual(reopened['result']['actions'][0]['blocked']['kind'], 'merge-rejected')
                    before = self.state.read_bytes()
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                        '--request-id', 'forced-fourth', '--head', H1, '--reserve', helper=helper, ok=False)
                    self.assertIn('merge attempts exhausted', refused.stderr)
                    self.assertEqual(self.state.read_bytes(), before)
                    self.assertEqual(len(host.dispatched), 3)
                    host.snapshot = observation(pr(head=H2))
                    fresh = self.wake(adapter, host, 'new-head')
                    self.assertEqual(fresh['result']['actions'][0]['kind'], 'merge')
                    self.assertTrue(fresh['result']['actions'][0]['request_id'].endswith('-a1'))

    def test_success_and_no_change_wait_for_authoritative_lifecycle_or_new_head(self):
        for index, (helper, adapter, _) in enumerate(self.adapters()):
            for status in ('succeeded', 'no-change'):
                for evidence in ('new-head', 'merged', 'reopened'):
                    with self.subTest(installed=index, status=status, evidence=evidence):
                        self.state = self.base / f'merge-complete-{index}-{status}-{evidence}.json'
                        self.start(helper=helper)
                        host = FakeHost(observation(pr()))
                        action = self.wake(adapter, host, 'initial')['result']['actions'][0]
                        self.finish(helper, {**action, 'attempt': 1}, status)
                        terminal = deepcopy(json.loads(self.state.read_text())['prs'][URL]['dispatches'][0])
                        for wake in range(4):
                            result = self.wake(adapter, host, f'unchanged-{wake}', '2026-10-22T14:10:00Z')
                            action = result['result']['actions'][0]
                            self.assertEqual(action['kind'], 'reconcile-merge')
                            self.assertEqual(action['blocked']['kind'], 'merge-observation-required')
                            self.assertEqual(result['dispatched'], [])
                            self.assertFalse(result['result']['progress']['meaningful'])
                        before = self.state.read_bytes()
                        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
                            '--request-id', 'repeat-completed', '--head', H1, '--reserve', helper=helper, ok=False)
                        self.assertEqual(self.state.read_bytes(), before)
                        self.assertEqual(len(host.dispatched), 1)
                        if evidence in ('merged', 'reopened'):
                            host.snapshot = observation(pr(state='MERGED' if evidence == 'merged' else 'CLOSED'))
                            result = self.wake(adapter, host, 'terminal-pr', '2026-10-22T14:11:00Z')
                            self.assertEqual(result['result']['actions'][0]['kind'],
                                             'merged' if evidence == 'merged' else 'closed')
                            self.assertEqual(result['dispatched'], [])
                        if evidence != 'merged':
                            # A changed lifecycle/head still needs fresh current-head gates.
                            head = H2 if evidence == 'new-head' else H1
                            host.snapshot = observation(pr(head=head, merge_state='BLOCKED', checks_state='PENDING',
                                checks=[{'name': 'ci', 'status': 'QUEUED', 'head_sha': H1}]))
                            result = self.wake(adapter, host, 'fresh-red', '2026-10-22T14:12:00Z')
                            self.assertNotEqual(result['result']['actions'][0]['kind'], 'merge')
                            self.assertEqual(result['dispatched'], [])
                            host.snapshot = observation(pr(head=head))
                            result = self.wake(adapter, host, 'fresh-green', '2026-10-22T14:13:00Z')
                            self.assertEqual(result['result']['actions'][0]['kind'], 'merge')
                            self.assertEqual(len(host.dispatched), 2)
                        self.assertEqual(json.loads(self.state.read_text())['prs'][URL]['dispatches'][0], terminal)


class LiveMergeHeadChangeTest(ContinuousCase):
    def exercise_live_merge(self, status, helper=HELPER):
        self.start(helper=helper)
        self.cli('observe', '--now', NOW, '--wake-kind', 'event', '--wake-id', 'green',
                 payload=observation(pr()), helper=helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--head', H1, '--reserve', helper=helper)
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--host-task-id', 'merge-host-1', helper=helper)
        if status == 'armed':
            self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                '--request-id', 'merge-a', '--status', 'armed', helper=helper)
        red = pr(head=H2, merge_state='BLOCKED', checks_state='FAILURE',
            required_contexts=['lint'], checks=[{'name': 'lint', 'status': 'COMPLETED',
                'conclusion': 'FAILURE', 'head_sha': H2}])
        for index, row in enumerate((pr(head=H2), red)):
            moved = self.cli('observe', '--now', NOW, '--wake-kind', 'event',
                '--wake-id', f'moved-{index}', payload=observation(row), helper=helper)
            self.assertEqual(moved['actions'][0]['kind'], 'merge-pending')
            dispatch = json.loads(self.state.read_text())['prs'][URL]['dispatches'][0]
            self.assertEqual(dispatch['status'], status)
            self.assertNotIn('completed_at', dispatch)
            self.assertEqual(dispatch['stale_at_head'], H2)
            for kind in ('merge', 'fixer', 'resolution'):
                before = self.state.read_bytes()
                refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                    '--request-id', f'racing-{kind}', '--head', H2, '--reserve',
                    helper=helper, ok=False)
                self.assertIn('merge merge-a', refused.stderr)
                self.assertEqual(self.state.read_bytes(), before)
        before = self.state.read_bytes()
        for handle in ((), ('--host-task-id', 'unrelated-host')):
            refused = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
                '--request-id', 'merge-a', '--head', H1, '--status', 'cancelled',
                *handle, helper=helper, ok=False)
            self.assertIn('handle', refused.stderr)
            self.assertEqual(self.state.read_bytes(), before)
        terminal = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--host-task-id', 'merge-host-1', '--head', H1,
            '--status', 'cancelled', helper=helper)
        self.assertEqual(terminal['dispatch']['status'], 'cancelled')
        self.assertIn('completed_at', terminal['dispatch'])
        ready = self.cli('observe', '--now', NOW, '--wake-kind', 'event', '--wake-id', 'settled',
            payload=observation(red), helper=helper)
        self.assertEqual(ready['actions'][0]['kind'], 'dispatch-fixer')
        self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', 'fixer',
            '--request-id', ready['actions'][0]['request_id'], '--head', H2,
            '--reserve', helper=helper)
        before = self.state.read_bytes()
        duplicate = self.cli('receipt', '--now', NOW, '--pr', URL, '--kind', 'merge',
            '--request-id', 'merge-a', '--host-task-id', 'merge-host-1', '--head', H1,
            '--status', 'cancelled', helper=helper)
        self.assertEqual(duplicate['status'], 'duplicate')
        self.assertEqual(self.state.read_bytes(), before)
        self.assertTrue(json.loads(before)['prs'][URL]['fixer']['in_flight'])

    def test_pending_merge_handle_survives_green_and_red_head_changes(self):
        self.exercise_live_merge('pending')

    def test_armed_merge_handle_survives_green_and_red_head_changes(self):
        self.exercise_live_merge('armed')

    def test_installed_helper_preserves_an_armed_stale_merge_until_matching_terminal_receipt(self):
        box = Sandbox(self.base / 'installed')
        package, _ = box.install('babysitter')
        self.exercise_live_merge('armed', helper=package / 'scripts/continuous.py')


class RevocationTest(ContinuousCase):
    def test_revoke_blocks_a_due_host_wake_until_owned_stop_is_verified(self):
        host = FakeHost(observation(pr()))
        host.clock = '2026-10-22T14:00:00Z'
        self.start()
        continuous_sweep.arm(host, self.state, host.clock)
        revoked = self.cli('scheduler', '--now', NOW, '--available', 'yes', '--authorized', 'no')
        self.assertEqual(revoked['coverage'], 'stop-unverified')
        self.assertTrue(revoked['scheduler_stop'])
        delivered = continuous_sweep.tick(host, self.state, '2026-10-22T14:10:00Z')
        self.assertEqual(delivered[0]['result']['status'], 'scheduled-continuation-blocked')
        self.assertEqual(host.dispatched, [])
        blocked = self.observe(NOW, observation(pr()), wake='late-timer')
        self.assertEqual(blocked['status'], 'scheduled-continuation-blocked')
        self.assertEqual(host.delete_schedule(revoked['scheduler_stop']), {'verified': True})
        self.cli('schedule-stop', '--now', NOW, '--schedule-id', revoked['scheduler']['schedule_id'],
                 '--verified', 'yes')
        self.assertEqual(self.cli('status')['coverage'], 'event-only')

    def test_identical_run_inputs_still_create_unique_persistent_schedule_keys(self):
        first = self.start()
        other = self.base / 'other.json'
        second = self.cli('start', '--now', '2026-10-22T14:00:00Z', '--scope-kind', 'org',
            '--scope-value', 'fixture', '--thread-id', 'self', '--scheduler', 'scheduled',
            '--authorization-source', str(self.request), state=other)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertNotEqual(self.cli('schedule-plan')['request']['key'],
                            self.cli('schedule-plan', state=other)['request']['key'])


class RealLegacyUpgradeTest(ContinuousCase):
    def test_historical_source_extraction_works_without_git_or_subprocesses(self):
        with patch('subprocess.run', side_effect=AssertionError('fixture extraction must be offline')):
            source = legacy_source(self.base)
        self.assertEqual(json.loads((source / 'plugins/babysitter/plugin.json').read_text())['version'],
                         '1.2.10')

    def test_real_legacy_pin_upgrade_retains_evidence_and_resumes_with_verified_receipt(self):
        self.exercise_upgrade()

    def test_previous_helper_state_migrates_its_real_legacy_fingerprint(self):
        self.exercise_upgrade('17e636c1c24be77566f24062f93a8b1dc17d94c8')

    def exercise_upgrade(self, revision=None):
        box = Sandbox(self.base / 'sandbox')
        source = legacy_source(self.base, revision) if revision else legacy_source(self.base)
        refused = box.install('babysitter', source=source, check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn('full operation review matrix is missing or inconsistent', refused.stderr)
        before_source = tree_digest(source / 'plugins', source / 'core', source / 'shared')
        old, old_manifest = install_legacy(box, source)
        self.assertEqual(tree_digest(source / 'plugins', source / 'core', source / 'shared'), before_source)
        caller = box.caller(old_manifest, 'babysitter/repo')
        job_id = 'legacy-upgrade'
        box.create(old, plan(old_manifest, job_id))
        self.assertEqual(box.pinned_package(job_id, 'babysitter'), old)
        self.assertEqual((old / 'scripts/continuous.py').exists(), bool(revision))
        if revision:
            self.start(helper=old / 'scripts/continuous.py', job_id=job_id)
        brief = box.dispatch(old, job_id, caller, 'fix', 'old-host')
        box.complete(old, job_id, caller, 'fix', brief, 'old-host', worker_result(brief))
        box.job(old, 'decision', job_id, {'caller': caller, 'decision': box.owner_decision(
            'owner-upgrade', 'Upgrade this synthetic job.', 'plan:upgrade-1')})
        job_file = box.jobs / job_id / 'job.json'
        before_job = job_file.read_bytes()
        before_evidence = tree_digest(job_file.parent / 'briefs', job_file.parent / 'results', old)
        current, manifest = box.install('babysitter')
        helper = current / 'scripts/continuous.py'
        identity_proc = box.run([sys.executable, helper, 'version'])
        identity = json.loads(identity_proc.stdout)
        self.assertEqual(identity['digest'], manifest['package_digest'])
        preflight = self.cli('preflight', '--job', str(job_file), '--now', NOW, helper=helper)
        self.assertEqual(preflight['status'], 'ready' if revision else 'legacy-job')
        self.assertEqual(job_file.read_bytes(), before_job)
        self.assertEqual(box.pinned_package(job_id, 'babysitter'), old)
        upgrade = box.job(current, 'upgrade-package', job_id, {
            'caller': caller, 'revision': {'id': 'upgrade-1', 'owner_decision_id': 'owner-upgrade',
                'reason': 'Adopt continuous mode while retaining original evidence.'},
            'dependency_key': 'babysitter',
            'expected_state_sha256': hashlib.sha256(before_job).hexdigest(),
            'expected_package_digest': manifest['package_digest']},
            extra=('--prefix', box.prefix, '--agents-root', box.agents))
        self.assertEqual(box.pinned_package(job_id, 'babysitter'), current)
        self.assertEqual(Path(upgrade['previous_state']['path']).read_bytes(), before_job)
        self.assertEqual(tree_digest(job_file.parent / 'briefs', job_file.parent / 'results', old),
                         before_evidence)
        receipt = self.base / 'upgrade.json'
        receipt.write_text(json.dumps(upgrade))  # exact supported CLI result, no fabricated fields
        if not revision:
            self.start(helper=helper)
        state = json.loads(self.state.read_text())
        if not revision:
            # The original continuous-1 helper wrote no fingerprint or job identity.
            state['package'] = {'pinned_version': old_manifest['version']}
            state.pop('job_id', None)
            state.pop('job', None)
            self.state.write_text(json.dumps(state))
        original_state = self.state.read_bytes()
        required = self.cli('resume', '--now', NOW, helper=helper)
        self.assertEqual(required['status'], 'migration-required')
        for decision_id, error in [('never-recorded', 'no matching supported'),
                                   ('owner-upgrade', None)]:
            if error:
                refused = self.cli('resume', '--now', NOW, '--accept-migration',
                    '--owner-decision-id', decision_id, '--upgrade-receipt', str(receipt),
                    '--job', str(job_file), helper=helper, ok=False)
                self.assertIn(error, refused.stderr)
                self.assertEqual(self.state.read_bytes(), original_state)
            else:
                resumed = self.cli('resume', '--now', NOW, '--accept-migration',
                    '--owner-decision-id', decision_id, '--upgrade-receipt', str(receipt),
                    '--job', str(job_file), helper=helper)
                self.assertEqual(resumed['status'], 'resumed')
                self.assertEqual(resumed['migration']['upgrade_receipt']['job_id'], job_id)
        after_job = job_file.read_bytes()
        self.assertEqual(tree_digest(job_file.parent / 'briefs', job_file.parent / 'results', old),
                         before_evidence)
        self.assertEqual(self.cli('resume', '--now', NOW, helper=helper)['status'], 'resumed')
        self.assertEqual(job_file.read_bytes(), after_job)
        self.assertEqual(self.cli('status', helper=helper)['run_id'], state['run_id'])
        # The actual installed package rejects tampering instead of inventing another identity.
        (current / 'references/continuous.md').write_text('tampered fixture')
        tampered = box.run([sys.executable, helper, 'version'], check=False)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn('integrity failure', tampered.stderr)
