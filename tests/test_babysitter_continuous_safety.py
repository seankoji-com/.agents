"""Adverse transitions from the issue 94 repair reviews; all services are fixtures."""
import hashlib
import json
import sys
from unittest.mock import patch
from pathlib import Path

from tests.babysitter_continuous_fixtures import AcceptedJob, legacy_source, plan
from tests.test_babysitter_continuous import (
    ContinuousCase, FakeHost, H1, H2, HELPER, observation, pr, continuous_sweep,
)
from tests.test_rebuild_installed import Sandbox, tree_digest, worker_result

URL = 'https://github.com/fixture/widgets/pull/12'
NOW = '2026-10-22T14:05:00Z'


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
        self.assertTrue(manifest['version'].startswith('1.3.0'))
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
    def test_unfamiliar_continuations_keep_ownership_until_explicit_release(self):
        self.start()
        for index, release in enumerate(('handed-back', 'released', 'none', 'stopped', 'cancelled')):
            self.observe(NOW, observation(pr(owner={'thread_id': 'other', 'status': 'running',
                'continuation': 'maintainer-live'})), wake=f'live-{index}')
            for status in ('completed', 'idle', 'failed', 'interrupted'):
                still = self.observe(NOW, observation(pr(owner={'thread_id': 'other',
                    'status': status, 'continuation': 'still-maintaining'})),
                    wake=f'unknown-{index}-{status}')
                self.assertEqual(still['actions'][0]['kind'], 'owned-elsewhere')
                before = self.state.read_bytes()
                for kind in ('merge', 'fixer', 'resolution'):
                    refused = self.cli('dispatch', '--now', NOW, '--pr', URL, '--kind', kind,
                        '--request-id', f'takeover-{kind}', '--head', H1, '--reserve', ok=False)
                    self.assertIn('owned elsewhere', refused.stderr)
                    self.assertEqual(self.state.read_bytes(), before)
            released = self.observe(NOW, observation(pr(owner={'thread_id': 'other',
                'status': 'completed', 'continuation': release})), wake=f'release-{index}')
            self.assertEqual(released['actions'][0]['kind'], 'merge')


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
        old, old_manifest = box.install('babysitter', source=source)
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
