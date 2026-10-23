"""Continuous babysitter coordination (issue #94).

Deterministic, offline tests for the source helper, the shipped `list-prs.sh`
transport (separately) and the installed package path. A fake clock moves while a
check stays queued and no native event exists; the scheduled wake must diagnose the
queue rather than claim monitoring continues.

These are simulated integration tests. They do not prove a live T3 schedule or wake.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'babysitter'
HELPER = PLUGIN / 'scripts' / 'continuous.py'
H1, H2 = '1' * 40, '2' * 40
REPO_A, REPO_B = 'fixture/widgets', 'fixture/gadgets'


def pr(repo=REPO_A, number=12, *, head=H1, checks=None, mergeable='MERGEABLE',
       merge_state='CLEAN', checks_state='SUCCESS', threads=0, owner=None,
       draft=False, fork=False, state='OPEN', required_contexts=None, human_blocker=None):
    return {
        'repo': repo, 'number': number, 'url': f'https://github.com/{repo}/pull/{number}',
        'state': state, 'head_sha': head, 'draft': draft, 'fork': fork,
        'mergeable': mergeable, 'merge_state_status': merge_state,
        'checks_state': checks_state, 'unresolved_threads': threads,
        'checks': checks if checks is not None else [
            {'name': 'ci', 'status': 'COMPLETED', 'conclusion': 'SUCCESS',
             'created_at': '2026-10-22T13:00:00Z'}],
        'required_contexts': required_contexts or [],
        'owner': owner,
        'human_blocker': human_blocker,
    }


def queued(created='2026-10-22T14:12:00Z', name='Validate compose files', status='QUEUED'):
    return {'name': name, 'status': status, 'conclusion': None,
            'created_at': created, 'started_at': None if status == 'QUEUED' else created}


def observation(*prs, complete=True, gaps=None):
    return {'complete': complete, 'gaps': gaps or [], 'prs': list(prs)}


class ContinuousCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state.json'
        self.request = self.base / 'request.txt'
        self.request.write_text('/t3-babysitter org fixture owner authorised continuous coverage\n')

    def cli(self, command, *args, ok=True, helper=HELPER, payload=None):
        argv = [sys.executable, str(helper), command, '--state', str(self.state), *args]
        if payload is not None:
            path = self.base / f'input-{len(list(self.base.glob("input-*")))}.json'
            path.write_text(json.dumps(payload))
            argv += ['--observation', str(path)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def start(self, *, scheduler='scheduled', cadence=600, threshold=900, stall=1800,
              kind='org', value='fixture', exclusions=()):
        args = ['--now', '2026-10-22T14:00:00Z', '--scope-kind', kind,
                '--scope-value', value, '--cadence-seconds', str(cadence),
                '--queue-threshold-seconds', str(threshold),
                '--stall-threshold-seconds', str(stall), '--thread-id', 'self']
        if scheduler == 'scheduled':
            args += ['--scheduler', 'scheduled', '--authorization-source', str(self.request)]
        else:
            args += ['--scheduler', 'event-only']
        for excluded in exclusions:
            args += ['--exclude', excluded]
        return self.cli('start', *args)

    def observe(self, at, snapshot, *, wake='w1', kind='schedule'):
        return self.cli('observe', '--now', at, '--wake-kind', kind, '--wake-id', wake,
                        payload=snapshot)

    def record_schedule(self, schedule_id='sched-1', next_run='2026-10-22T14:10:00Z',
                        at='2026-10-22T14:00:00Z'):
        return self.cli('schedule-record', '--now', at, '--schedule-id', schedule_id,
                        '--next-run-at', next_run)


class QueuedJobCausalTest(ContinuousCase):
    def test_scheduled_wake_diagnoses_a_queued_job_that_emits_no_event(self):
        self.start()
        self.record_schedule()
        first = self.observe('2026-10-22T14:13:00Z', observation(pr(checks=[queued()])), wake='boot')
        self.assertEqual(first['actions'][0]['kind'], 'wait-checks')
        self.assertIn('waiting-for-runner', first['actions'][0]['reason'])
        self.assertEqual(first['human_questions'], [])

        # Same unchanged job, no native event. Only the fake clock and a host wake move.
        second = self.observe('2026-10-22T14:27:01Z', observation(pr(checks=[queued()])), wake='sched-2')
        action = second['actions'][0]
        self.assertEqual(action['kind'], 'diagnose-queue')
        self.assertEqual(action['blocked']['kind'], 'waiting-for-runner')
        self.assertEqual(action['blocked']['check'], 'Validate compose files')
        self.assertEqual(second['queue'][0]['age_seconds'], 901)
        self.assertTrue(second['queue'][0]['over_threshold'])
        self.assertEqual(second['coverage'], 'scheduled')
        self.assertIsNotNone(action['next_check_at'])
        self.assertEqual(second['human_questions'], [])
        self.assertFalse(second['progress']['meaningful'])

    def test_running_stall_and_aggregate_gate_have_distinct_diagnoses(self):
        self.start(threshold=900, stall=1800)
        running = self.observe('2026-10-22T14:28:00Z',
                               observation(pr(checks=[queued(status='IN_PROGRESS')])), wake='run')
        self.assertEqual(running['queue'][0]['diagnosis'], 'running-tests')
        self.assertEqual(running['actions'][0]['kind'], 'diagnose-queue')

        missing = self.observe('2026-10-22T14:17:00Z',
                               observation(pr(required_contexts=['ci', 'integration'])), wake='missing')
        self.assertEqual(missing['actions'][0]['kind'], 'wait-checks')
        self.assertEqual(missing['actions'][0]['blocked']['kind'], 'missing-contexts')
        self.assertEqual(missing['actions'][0]['blocked']['detail'], ['integration'])

        gate = self.observe('2026-10-22T14:18:00Z',
                            observation(pr(merge_state='BLOCKED', checks_state='SUCCESS')), wake='gate')
        self.assertEqual(gate['actions'][0]['kind'], 'diagnose-gate')
        self.assertEqual(gate['actions'][0]['blocked']['kind'], 'stuck-aggregate-gate')

        stale = pr(checks=[queued()])
        stale['checks_head_sha'] = H2
        stale_result = self.observe('2026-10-22T14:19:00Z', observation(stale), wake='stale')
        self.assertEqual(stale_result['actions'][0]['kind'], 'wait-checks')
        self.assertEqual(stale_result['actions'][0]['blocked']['kind'], 'stale-head-checks')

    def test_event_only_mode_reports_its_idle_gap(self):
        self.start(scheduler='event-only')
        result = self.observe('2026-10-22T14:13:00Z', observation(pr()))
        self.assertEqual(result['coverage'], 'event-only')
        self.assertIn('event-only', result['scheduler']['gap'])
        plan = self.cli('schedule-plan')
        self.assertEqual(plan['status'], 'event-only')
        self.assertIsNone(plan['request'])


class DiscoveryAdmissionTest(ContinuousCase):
    def test_new_matching_pr_is_admitted_while_exclusions_and_ownership_hold(self):
        self.start(exclusions=['fixture/gadgets#99'])
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='first')
        second = self.observe('2026-10-22T14:15:00Z', observation(
            pr(),
            pr(REPO_B, 78, head=H2),
            pr(REPO_B, 99),
            pr(REPO_B, 100, draft=True),
            pr(REPO_B, 101, fork=True),
            pr(REPO_B, 102, owner={'thread_id': 'other', 'status': 'active',
                                   'continuation': 'in-flight'}),
        ), wake='second')
        self.assertEqual([row['number'] for row in second['admitted']], [78, 102])
        self.assertEqual({row['url'] for row in second['admitted']},
                         {'https://github.com/fixture/gadgets/pull/78',
                          'https://github.com/fixture/gadgets/pull/102'})
        actions = {row['pr']: row for row in second['actions']}
        self.assertEqual(actions['https://github.com/fixture/gadgets/pull/78']['kind'], 'merge')
        owned = actions['https://github.com/fixture/gadgets/pull/102']
        self.assertEqual(owned['kind'], 'owned-elsewhere')
        status = self.cli('status')
        self.assertNotIn('https://github.com/fixture/gadgets/pull/99', status['prs'])
        self.assertNotIn('https://github.com/fixture/gadgets/pull/100', status['prs'])
        self.assertNotIn('https://github.com/fixture/gadgets/pull/101', status['prs'])
        self.assertEqual(second['human_questions'], [])

    def test_partial_discovery_preserves_known_prs_and_keeps_the_gap_visible(self):
        self.start(cadence=600)
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='complete')
        partial_snapshot = observation(
            pr(REPO_B, 78), complete=False,
            gaps=[{'kind': 'rate-limit', 'detail': 'search omitted fixture/widgets#12'}])
        partial = self.observe('2026-10-22T14:15:00Z', partial_snapshot, wake='partial')
        self.assertTrue(partial['discovery']['omitted'])
        self.assertEqual(partial['discovery']['attempts'], 1)
        actions = {row['pr']: row for row in partial['actions']}
        self.assertEqual(actions['https://github.com/fixture/widgets/pull/12']['kind'],
                         'reconcile-discovery')
        status = self.cli('status')
        self.assertEqual(status['discovery']['last_complete_at'], '2026-10-22T14:05:00Z')
        for attempt in range(2, 5):
            last = self.observe(f'2026-10-22T14:{15 + attempt:02d}:00Z', partial_snapshot,
                                wake=f'partial-{attempt}')
        kinds = [row['kind'] for row in last['actions']]
        self.assertIn('discovery-blocked', kinds)
        self.assertEqual(last['coverage'], 'scheduled')

    def test_ownership_continuation_releases_only_after_handoff(self):
        self.start()
        live = self.observe('2026-10-22T14:05:00Z', observation(
            pr(owner={'thread_id': 'other', 'status': 'parked',
                      'continuation': 'maintainer-live'})), wake='live')
        self.assertEqual(live['actions'][0]['kind'], 'owned-elsewhere')

        released = self.observe('2026-10-22T14:15:00Z', observation(
            pr(owner={'thread_id': 'other', 'status': 'parked',
                      'continuation': 'handed-back'})), wake='released')
        self.assertEqual(released['actions'][0]['kind'], 'merge')

    def test_list_prs_line_shape_is_accepted_without_reinterpretation(self):
        self.start()
        row = {
            'repo': REPO_A, 'number': 12, 'url': 'https://github.com/fixture/widgets/pull/12',
            'state': 'OPEN', 'head_oid': H1, 'draft': False, 'fork': False,
            'mergeable': 'MERGEABLE', 'merge_state_status': 'BLOCKED',
            'checks_state': 'PENDING', 'unresolved_threads': 0,
            'pending_checks': [queued()], 'failing': [],
        }
        result = self.observe('2026-10-22T14:27:01Z', observation(row), wake='reader-line')
        self.assertEqual(result['actions'][0]['kind'], 'diagnose-queue')
        self.assertEqual(result['queue'][0]['age_seconds'], 901)

    def test_partial_reader_allows_unstable_when_required_contexts_pass(self):
        self.start()
        row = {'repo': REPO_A, 'number': 12, 'state': 'OPEN', 'head_oid': H1,
               'draft': False, 'fork': False, 'mergeable': 'MERGEABLE',
               'merge_state_status': 'UNSTABLE', 'checks_state': 'FAILURE',
               'unresolved_threads': 0, 'pending_checks': [],
               'failing': ['optional-lint'], 'required_contexts': ['ci']}
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='unstable')
        self.assertEqual(result['actions'][0]['kind'], 'merge')

        row['failing'] = ['ci']
        refused = self.observe('2026-10-22T14:06:00Z', observation(row), wake='required-fail')
        self.assertEqual(refused['actions'][0]['kind'], 'dispatch-fixer')
        self.assertIn('ci', refused['actions'][0]['reason'])

    def test_explicit_resolution_closes_an_omitted_pr(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='seen')
        omitted = self.observe('2026-10-22T14:15:00Z', observation(), wake='omitted')
        self.assertEqual(omitted['actions'][0]['kind'], 'reconcile-discovery')
        status = self.cli('status')
        self.assertEqual(status['open_prs'], [url])
        resolved = self.cli('resolve', '--now', '2026-10-22T14:20:00Z', '--pr', url,
                            '--resolution', 'merged', '--head', H1)
        self.assertEqual(resolved['state'], 'merged')
        self.assertEqual(self.cli('status')['open_prs'], [])

    def test_missing_scheduler_capability_and_authorization_are_explicit(self):
        self.start(scheduler='event-only')
        unavailable = self.cli('scheduler', '--now', '2026-10-22T14:05:00Z',
                              '--available', 'no', '--authorized', 'no')
        self.assertEqual(unavailable['status'], 'event-only')
        self.assertIn('scheduler unavailable', unavailable['gap'])
        refused = self.cli('scheduler', '--now', '2026-10-22T14:06:00Z',
                           '--available', 'yes', '--authorized', 'yes', ok=False)
        self.assertIn('recorded owner source', refused.stderr)

    def test_human_only_blocker_asks_one_explicit_question(self):
        self.start()
        blocked = pr(human_blocker={
            'kind': 'missing-authorization',
            'detail': 'the owner must grant repository access',
            'question': 'Grant read access to the fixture repository?',
            'recommended': 'Grant read access'})
        result = self.observe('2026-10-22T14:05:00Z', observation(blocked), wake='human')
        self.assertEqual(result['actions'][0]['kind'], 'needs-human')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'missing-authorization')
        self.assertEqual(len(result['human_questions']), 1)
        self.assertEqual(result['human_questions'][0]['recommended'], 'Grant read access')
        self.assertIn('Grant read access', result['human_questions'][0]['question'])

    def test_stalled_unchanged_work_is_named_with_a_next_check(self):
        self.start(stall=120)
        self.observe('2026-10-22T14:05:00Z', observation(pr(
            checks=[], mergeable='UNKNOWN', merge_state='UNKNOWN', checks_state=None)),
            wake='start')
        stalled = self.observe('2026-10-22T14:10:00Z', observation(pr(
            checks=[], mergeable='UNKNOWN', merge_state='UNKNOWN', checks_state=None)),
            wake='later')
        self.assertEqual(stalled['actions'][0]['kind'], 'diagnose-stall')
        self.assertEqual(stalled['actions'][0]['blocked']['kind'], 'stalled-work')
        self.assertIsNotNone(stalled['actions'][0]['next_check_at'])


class IdempotencyTest(ContinuousCase):
    def test_requested_changes_block_merge_without_a_new_question(self):
        self.start()
        changed = pr(merge_state='BLOCKED')
        changed['review_decision'] = 'CHANGES_REQUESTED'
        changed['changes_requested_by'] = ['fixture-reviewer']
        result = self.observe('2026-10-22T14:05:00Z', observation(changed), wake='review')
        self.assertEqual(result['actions'][0]['kind'], 'wait-review')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'requested-changes')
        self.assertEqual(result['human_questions'], [])

    def test_merge_needs_an_exact_head_and_a_green_current_head(self):
        self.start()
        short = pr(head='abc123')
        result = self.observe('2026-10-22T14:05:00Z', observation(short), wake='short-head')
        self.assertEqual(result['actions'][0]['kind'], 'wait-checks')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'missing-head')

    def test_schedules_dispatches_and_writers_are_not_duplicated(self):
        self.start()
        first = self.record_schedule('sched-1')
        self.assertFalse(first['duplicate'])
        again = self.record_schedule('sched-1')
        self.assertTrue(again['duplicate'])
        refused = self.cli('schedule-record', '--now', '2026-10-22T14:05:00Z',
                           '--schedule-id', 'sched-2',
                           '--next-run-at', '2026-10-22T14:20:00Z', ok=False)
        self.assertIn('stop it before creating another', refused.stderr)

        failing = [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE',
                    'created_at': '2026-10-22T14:00:00Z'}]
        dispatched = self.observe('2026-10-22T14:06:00Z', observation(pr(checks=failing)), wake='a')
        action = dispatched['actions'][0]
        self.assertEqual(action['kind'], 'dispatch-fixer')
        request = action['request_id']
        self.cli('dispatch', '--now', '2026-10-22T14:06:00Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12',
                 '--request-id', request, '--kind', 'fixer', '--host-task-id', 'task-1')
        duplicate = self.cli('dispatch', '--now', '2026-10-22T14:07:00Z',
                             '--pr', 'https://github.com/fixture/widgets/pull/12',
                             '--request-id', request, '--kind', 'fixer', '--host-task-id', 'task-1')
        self.assertEqual(duplicate['status'], 'duplicate')

        # A green observation while the fixer is live must not merge or branch-update.
        guarded = self.observe('2026-10-22T14:08:00Z', observation(pr()), wake='green')
        self.assertEqual(guarded['actions'][0]['kind'], 'wait-fixer')
        self.assertEqual(guarded['actions'][0]['blocked']['kind'], 'fixer-in-flight')

        self.cli('fixer-done', '--now', '2026-10-22T14:09:00Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12')
        landed = self.observe('2026-10-22T14:10:00Z', observation(pr()), wake='clear')
        self.assertEqual(landed['actions'][0]['kind'], 'merge')
        self.cli('dispatch', '--now', '2026-10-22T14:10:30Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12',
                 '--request-id', 'merge-1', '--kind', 'merge')
        pending = self.observe('2026-10-22T14:11:00Z', observation(pr()), wake='merge-in-flight')
        self.assertEqual(pending['actions'][0]['kind'], 'merge-pending')
        resolution = self.cli('dispatch', '--now', '2026-10-22T14:11:30Z',
                              '--pr', 'https://github.com/fixture/widgets/pull/12',
                              '--request-id', 'reply-1', '--kind', 'resolution')
        self.assertEqual(resolution['status'], 'recorded')
        repeated = self.cli('dispatch', '--now', '2026-10-22T14:12:00Z',
                            '--pr', 'https://github.com/fixture/widgets/pull/12',
                            '--request-id', 'reply-1', '--kind', 'resolution')
        self.assertEqual(repeated['status'], 'duplicate')

    def test_duplicate_wake_is_a_no_op_and_unchanged_read_is_not_progress(self):
        self.start()
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='same')
        duplicate = self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='same')
        self.assertEqual(duplicate['status'], 'duplicate')
        self.assertEqual(duplicate['actions'], [])
        later = self.observe('2026-10-22T14:20:00Z', observation(pr()), wake='different')
        self.assertFalse(later['progress']['meaningful'])
        self.assertEqual(later['actions'][0]['kind'], 'merge')


class CancelResumeTest(ContinuousCase):
    def test_cancelled_run_stops_and_resume_from_an_older_package_is_explicit(self):
        self.start()
        self.record_schedule()
        cancelled = self.cli('cancel', '--now', '2026-10-22T14:05:00Z', '--reason', 'owner stopped')
        self.assertEqual(cancelled['status'], 'cancelled')
        stopped = self.observe('2026-10-22T14:10:00Z', observation(pr()), wake='wake-after-cancel')
        self.assertEqual(stopped['status'], 'cancelled')
        self.assertEqual(stopped['actions'], [])

        state = json.loads(self.state.read_text())
        state['policy_version'] = 'continuous-0'
        state['package'] = {'pinned_version': '1.2.2+content.abc123'}
        self.state.write_text(json.dumps(state))
        required = self.cli('resume', '--now', '2026-10-22T14:15:00Z',
                            '--package-version', '1.2.2+content.abc123')
        self.assertEqual(required['status'], 'migration-required')
        self.assertIn('installed-drift', [g['kind'] for g in required['gaps']])
        self.assertFalse(required['changed'])

        migrated = self.cli('resume', '--now', '2026-10-22T14:15:00Z',
                            '--package-version', '1.2.2+content.abc123',
                            '--accept-migration', '--owner-decision-id', 'owner-approve-upgrade',
                            '--resume-cancelled')
        self.assertEqual(migrated['status'], 'resumed')
        self.assertTrue(migrated['changed'])
        self.assertEqual(migrated['policy_version'], 'continuous-1')
        self.assertEqual(migrated['migration']['owner_decision_id'], 'owner-approve-upgrade')
        resumed = self.observe('2026-10-22T14:20:00Z', observation(pr()), wake='resume')
        self.assertEqual(resumed['status'], 'ok')

    def test_unknown_state_and_malformed_observation_are_refused(self):
        self.start()
        bad = self.cli('observe', '--now', '2026-10-22T14:05:00Z', '--wake-kind', 'event',
                       payload={'complete': True, 'prs': [{'repo': 'bad', 'number': 1}]}, ok=False)
        self.assertIn('continuous_error', bad.stderr)
        duplicate = self.cli('observe', '--now', '2026-10-22T14:05:00Z', '--wake-kind', 'event',
                             payload={'complete': True,
                                      'prs': [pr(), pr()]}, ok=False)
        self.assertIn('more than once', duplicate.stderr)


class InstalledPackageTest(unittest.TestCase):
    def test_installed_helper_exposes_the_same_policy_and_state_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            env = {**os.environ, 'HOME': str(base / 'home'),
                   'XDG_CONFIG_HOME': str(base / 'config'),
                   'XDG_STATE_HOME': str(base / 'xdg-state')}
            proc = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'babysitter',
                 '--prefix', str(base / 'prefix'), '--agents-root', str(base / 'agents')],
                capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            version_dir = Path(json.loads(proc.stdout)['data']['version_dir'])
            helper = version_dir / 'scripts' / 'continuous.py'
            self.assertTrue(helper.is_file())
            version = subprocess.run([sys.executable, str(helper), 'version'],
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(version.returncode, 0, version.stderr)
            identity = json.loads(version.stdout)
            self.assertEqual(identity['policy_version'], 'continuous-1')
            self.assertTrue(identity['version'].startswith('1.3.0'), identity['version'])

            request = base / 'request.txt'
            request.write_text('owner request\n')
            state = base / 'installed-state.json'
            started = subprocess.run(
                [sys.executable, str(helper), 'start', '--state', str(state),
                 '--now', '2026-10-22T14:00:00Z', '--scope-kind', 'org',
                 '--scope-value', 'fixture', '--scheduler', 'scheduled',
                 '--authorization-source', str(request), '--thread-id', 'self'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(started.returncode, 0, started.stderr)
            observation_path = base / 'obs.json'
            observation_path.write_text(json.dumps(observation(pr(checks=[queued()]))))
            observed = subprocess.run(
                [sys.executable, str(helper), 'observe', '--state', str(state),
                 '--now', '2026-10-22T14:27:01Z', '--wake-kind', 'schedule',
                 '--wake-id', 'installed-wake', '--observation', str(observation_path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertEqual(json.loads(observed.stdout)['actions'][0]['kind'], 'diagnose-queue')

    def test_manifest_declares_the_continuous_policy(self):
        meta = json.loads((PLUGIN / 'plugin.json').read_text())
        self.assertEqual(meta['version'], '1.3.0')
        continuous = meta['continuous']
        self.assertEqual(continuous['policy_version'], 'continuous-1')
        self.assertEqual(continuous['default_cadence_seconds'], 600)
        self.assertEqual(continuous['default_queue_threshold_seconds'], 900)
        self.assertEqual(continuous['state_helper'], 'scripts/continuous.py')
        for rel in ('entry.md', 'playbooks/maintain.md', 'references/scope.md'):
            self.assertIn('continuous', (PLUGIN / rel).read_text().lower())


if __name__ == '__main__':
    unittest.main()
