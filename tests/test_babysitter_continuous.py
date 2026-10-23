"""Continuous babysitter coordination (issue #94).

Deterministic, offline tests for the source helper, the shipped `list-prs.sh`
transport (separately) and the installed package path. A fake clock moves while a
check stays queued and no native event exists; the scheduled wake must diagnose the
queue rather than claim monitoring continues.

The causal test drives a fake host adapter: its timer delivers a scheduled wake to the
coordinator entry point, which reconciles discovery and reserves the resulting action.
These are simulated integration tests; they do not prove a live T3 schedule or wake.
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'babysitter'
HELPER = PLUGIN / 'scripts' / 'continuous.py'

sys.path.insert(0, str(PLUGIN / 'scripts'))
import continuous_sweep  # noqa: E402
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
        'review_threads_complete': True,
        'checks': checks if checks is not None else [
            {'name': 'ci', 'status': 'COMPLETED', 'conclusion': 'SUCCESS',
             'created_at': '2026-10-22T13:00:00Z'}],
        'required_contexts': required_contexts,
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

    def cli(self, command, *args, ok=True, helper=HELPER, payload=None, state=None):
        argv = [sys.executable, str(helper), command, '--state', str(state or self.state), *args]
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
              kind='org', value='fixture', exclusions=(), helper=HELPER, job_id=None):
        args = ['--now', '2026-10-22T14:00:00Z', '--scope-kind', kind,
                '--scope-value', value, '--cadence-seconds', str(cadence),
                '--queue-threshold-seconds', str(threshold),
                '--stall-threshold-seconds', str(stall), '--thread-id', 'self']
        if job_id:
            args += ['--job-id', job_id]
        if scheduler == 'scheduled':
            args += ['--scheduler', 'scheduled', '--authorization-source', str(self.request)]
        else:
            args += ['--scheduler', 'event-only']
        for excluded in exclusions:
            args += ['--exclude', excluded]
        return self.cli('start', *args, helper=helper)

    def observe(self, at, snapshot, *, wake='w1', kind='schedule'):
        return self.cli('observe', '--now', at, '--wake-kind', kind, '--wake-id', wake,
                        payload=snapshot)

    def record_schedule(self, schedule_id='sched-1', next_run='2026-10-22T14:10:00Z',
                        at='2026-10-22T14:00:00Z'):
        return self.cli('schedule-record', '--now', at, '--schedule-id', schedule_id,
                        '--next-run-at', next_run)

    def accepted_result(self, request, host='host-fixer'):
        from tests.babysitter_continuous_fixtures import AcceptedJob
        fixture = AcceptedJob(self.base / ('accepted-' + request), request, host)
        fixture.complete()
        return fixture.transport


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
        self.record_schedule()
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
            'review_threads_complete': True, 'checks_complete': True,
            'pending_checks': [queued()], 'failing': [],
        }
        result = self.observe('2026-10-22T14:27:01Z', observation(row), wake='reader-line')
        self.assertEqual(result['actions'][0]['kind'], 'diagnose-queue')
        self.assertEqual(result['queue'][0]['age_seconds'], 901)

    def test_partial_reader_allows_unstable_when_required_contexts_pass(self):
        self.start()
        # A normal search-reader row carries no required-context names. GitHub's
        # mergeStateStatus UNSTABLE means every required check passed and an optional
        # one failed, so the optional failure must not become a repair dispatch.
        # StatusCheckRollup.state has no UNSTABLE value, so the rollup is FAILURE.
        row = {'repo': REPO_A, 'number': 12, 'state': 'OPEN', 'head_oid': H1,
               'draft': False, 'fork': False, 'mergeable': 'MERGEABLE',
               'merge_state_status': 'UNSTABLE', 'checks_state': 'FAILURE',
               'unresolved_threads': 0, 'review_threads_complete': True,
               'checks_complete': True, 'pending_checks': [], 'failing': ['optional-lint']}
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='unstable')
        self.assertEqual(result['actions'][0]['kind'], 'merge')

        row['merge_state_status'] = 'BLOCKED'
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
    def test_requested_changes_are_triaged_before_waiting_for_re_review(self):
        self.start()
        changed = pr(merge_state='BLOCKED')
        changed['review_decision'] = 'CHANGES_REQUESTED'
        changed['changes_requested_by'] = ['fixture-reviewer']
        result = self.observe('2026-10-22T14:05:00Z', observation(changed), wake='review')
        action = result['actions'][0]
        self.assertEqual(action['kind'], 'dispatch-fixer')
        self.assertTrue(action['review_triage'])
        self.assertEqual(result['human_questions'], [])
        url = 'https://github.com/fixture/widgets/pull/12'
        self.cli('dispatch', '--now', '2026-10-22T14:05:30Z', '--pr', url,
                 '--request-id', action['request_id'], '--kind', 'fixer', '--head', H1,
                 '--host-task-id', 'host-fixer')
        result_path = self.accepted_result(action['request_id'])
        self.cli('receipt', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                 '--request-id', action['request_id'], '--status', 'no-change',
                 '--result', str(result_path), '--host-task-id', 'host-fixer')
        waiting = self.observe('2026-10-22T14:07:00Z', observation(changed), wake='re-review')
        self.assertEqual(waiting['actions'][0]['kind'], 'wait-review')
        self.assertEqual(waiting['actions'][0]['blocked']['kind'], 'requested-changes')
        self.assertEqual(waiting['human_questions'], [])

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

        result_path = self.accepted_result(request, 'task-1')
        self.cli('fixer-done', '--now', '2026-10-22T14:09:00Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12',
                 '--request-id', request, '--result', str(result_path), '--host-task-id', 'task-1')
        landed = self.observe('2026-10-22T14:10:00Z', observation(pr()), wake='clear')
        self.assertEqual(landed['actions'][0]['kind'], 'merge')
        self.cli('dispatch', '--now', '2026-10-22T14:10:30Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12',
                 '--request-id', 'merge-1', '--kind', 'merge', '--head', H1)
        pending = self.observe('2026-10-22T14:11:00Z', observation(pr()), wake='merge-in-flight')
        self.assertEqual(pending['actions'][0]['kind'], 'merge-pending')
        resolution = self.cli('dispatch', '--now', '2026-10-22T14:11:30Z',
                              '--pr', 'https://github.com/fixture/widgets/pull/12',
                              '--request-id', 'reply-1', '--kind', 'resolution', ok=False)
        self.assertIn('may not race', resolution.stderr)
        self.cli('receipt', '--now', '2026-10-22T14:11:40Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12',
                 '--request-id', 'merge-1', '--status', 'rejected')
        self.cli('dispatch', '--now', '2026-10-22T14:11:50Z',
                 '--pr', 'https://github.com/fixture/widgets/pull/12',
                 '--request-id', 'reply-1', '--kind', 'resolution')
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
        state['package']['pinned_version'] = '1.3.0+content.abc123'
        self.state.write_text(json.dumps(state))
        required = self.cli('resume', '--now', '2026-10-22T14:15:00Z',
                            '--package-version', '1.3.0+content.abc123')
        self.assertEqual(required['status'], 'migration-required')
        self.assertIn('policy-version', [g['kind'] for g in required['gaps']])
        self.assertFalse(required['changed'])

        refused = self.cli('resume', '--now', '2026-10-22T14:15:00Z',
                            '--package-version', '1.3.0+content.abc123',
                            '--accept-migration', '--owner-decision-id', 'owner-approve-upgrade',
                            '--resume-cancelled', ok=False)
        self.assertIn('upgrade receipt', refused.stderr)
        # Cancellation can be resumed independently when the package is unchanged.
        state['policy_version'] = 'continuous-1'
        state['package']['pinned_version'] = '1.3.0'
        self.state.write_text(json.dumps(state))
        resumed_state = self.cli('resume', '--now', '2026-10-22T14:15:00Z', '--resume-cancelled')
        self.assertEqual(resumed_state['status'], 'resumed')
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


def _moment(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def _iso(moment):
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


class FakeHost:
    """Deterministic stand-in for the T3 scheduler and discovery tools."""

    def __init__(self, snapshot, cadence_seconds=600):
        self.snapshot = snapshot
        self.cadence = cadence_seconds
        self.clock = None
        self.tasks = {}
        self.created = []
        self.dispatched = []
        self.counter = 0

    def create_schedule(self, request):
        self.created.append(request)
        self.counter += 1
        schedule_id = f'sched-{self.counter}'
        self.tasks[schedule_id] = _moment(self.clock) + timedelta(seconds=self.cadence)
        return {'schedule_id': schedule_id, 'next_run_at': _iso(self.tasks[schedule_id]),
                'stop': {'tool': 'delete_scheduled_task',
                         'arguments': {'scheduledTaskId': schedule_id}}}

    def delete_schedule(self, stop):
        schedule_id = stop['arguments']['scheduledTaskId']
        self.tasks.pop(schedule_id, None)
        return {'verified': True}

    def due(self, now):
        moment = _moment(now)
        wakes = []
        for schedule_id, next_run in list(self.tasks.items()):
            if next_run <= moment:
                self.tasks[schedule_id] = moment + timedelta(seconds=self.cadence)
                wakes.append({'wake_id': f'wake-{schedule_id}-{_iso(moment)}',
                              'kind': 'schedule', 'schedule_id': schedule_id})
        return wakes

    def discover(self, scope, now):
        return self.snapshot

    def dispatch(self, action, now):
        self.dispatched.append(dict(action))
        return {'status': 'accepted', 'host_task_id': f'task-{len(self.dispatched)}'}


class CausalSchedulerTest(ContinuousCase):
    def test_timer_wake_reaches_the_coordinator_without_a_native_event(self):
        self.start()
        queued_pr = pr(checks=[queued()])
        host = FakeHost(observation(queued_pr))
        host.clock = '2026-10-22T14:00:00Z'
        armed = continuous_sweep.arm(host, self.state, '2026-10-22T14:00:00Z')
        self.assertEqual(armed['status'], 'armed')
        self.assertEqual(len(host.created), 1)
        # A second arm must not create a second schedule.
        self.assertEqual(continuous_sweep.arm(host, self.state, '2026-10-22T14:00:01Z')['status'],
                         'already-scheduled')
        self.assertEqual(len(host.created), 1)

        # The fake clock advances past the cadence while the job stays queued and no
        # native PR event arrives. Only host.due delivers the wake.
        first = continuous_sweep.tick(host, self.state, '2026-10-22T14:27:00Z')
        self.assertEqual(len(first), 1)
        action = first[0]['result']['actions'][0]
        self.assertEqual(action['kind'], 'diagnose-queue')
        self.assertEqual(action['blocked']['kind'], 'waiting-for-runner')
        self.assertEqual(action['blocked']['age_seconds'], 900)
        self.assertEqual(first[0]['result']['human_questions'], [])

        # A new matching PR opened during the idle interval is discovered and admitted
        # by the next delivered wake, and its permitted merge is reserved.
        host.snapshot = observation(queued_pr, pr(REPO_B, 78, head=H2))
        second = continuous_sweep.tick(host, self.state, '2026-10-22T14:37:00Z')
        self.assertEqual([row['number'] for row in second[0]['result']['admitted']], [78])
        self.assertEqual(second[0]['dispatched'][0]['action']['kind'], 'merge')
        self.assertEqual(second[0]['dispatched'][0]['recorded'], 'recorded')
        self.assertEqual(len(host.created), 1)

        # The same delivered wake is a no-op: no duplicate dispatch or writer.
        duplicate = continuous_sweep.handle_wake(
            host, self.state, '2026-10-22T14:37:01Z', second[0]['wake'])
        self.assertEqual(duplicate['result']['status'], 'duplicate')
        self.assertEqual(duplicate['dispatched'], [])
        self.assertEqual(len(host.dispatched), 1)


class RecordingHost(FakeHost):
    """Fake host that observes the state at the moment a real launch would happen."""

    def __init__(self, snapshot, state_path, *, refuse=False, raise_error=False):
        super().__init__(snapshot)
        self.state_path = Path(state_path)
        self.refuse = refuse
        self.raise_error = raise_error
        self.seen_statuses = []
        self.competing_returncode = None
        self.competing_stderr = ''

    def dispatch(self, action, now):
        state = json.loads(self.state_path.read_text())
        pr_state = state['prs'][action['pr']]
        row = next(item for item in pr_state['dispatches']
                   if item['request_id'] == action['request_id'])
        self.seen_statuses.append(row['status'])
        # A competing writer must be refused while the reservation is the only record.
        proc = subprocess.run(
            [sys.executable, str(HELPER), 'dispatch', '--state', str(self.state_path),
             '--now', now, '--pr', action['pr'], '--request-id', 'competing-fixer',
             '--kind', 'fixer', '--head', action.get('head')],
            capture_output=True, text=True, timeout=30)
        self.competing_returncode = proc.returncode
        self.competing_stderr = proc.stderr
        if self.raise_error:
            raise RuntimeError('scheduler unavailable')
        if self.refuse:
            return {'status': 'rejected', 'reason': 'host refused'}
        return super().dispatch(action, now)


class DispatchReservationTest(ContinuousCase):
    def failing(self):
        return [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]

    def arm(self, host):
        host.clock = '2026-10-22T14:00:00Z'
        self.start()
        return continuous_sweep.arm(host, self.state, '2026-10-22T14:00:00Z')

    def test_the_reservation_exists_before_the_host_launch_and_refusal_is_reconciled(self):
        host = RecordingHost(observation(pr(checks=self.failing())), self.state, refuse=True)
        self.assertEqual(self.arm(host)['status'], 'armed')
        result = continuous_sweep.tick(host, self.state, '2026-10-22T14:10:00Z')
        self.assertEqual(host.seen_statuses, ['reserved'])
        self.assertNotEqual(host.competing_returncode, 0)
        self.assertIn('already in flight', host.competing_stderr)
        self.assertEqual(result[0]['dispatched'][0]['status'], 'rejected')
        state = json.loads(self.state.read_text())
        pr_state = state['prs']['https://github.com/fixture/widgets/pull/12']
        self.assertFalse(pr_state['fixer']['in_flight'])
        self.assertEqual(pr_state['dispatches'][0]['status'], 'rejected')
        retried = self.observe('2026-10-22T14:11:00Z',
                               observation(pr(checks=self.failing())), wake='retry')
        self.assertEqual(retried['actions'][0]['kind'], 'dispatch-fixer')
        self.assertIn('-a2', retried['actions'][0]['request_id'])

    def test_a_lost_launch_response_keeps_the_writer_guard_until_reconciled(self):
        host = RecordingHost(observation(pr(checks=self.failing())), self.state,
                             raise_error=True)
        self.arm(host)
        result = continuous_sweep.tick(host, self.state, '2026-10-22T14:10:00Z')
        self.assertEqual(result[0]['dispatched'][0]['status'], 'launch-error')
        self.assertEqual(result[0]['dispatched'][0]['reconciled'], 'recorded')
        state = json.loads(self.state.read_text())
        pr_state = state['prs']['https://github.com/fixture/widgets/pull/12']
        self.assertTrue(pr_state['fixer']['in_flight'])
        self.assertEqual(pr_state['dispatches'][0]['status'], 'uncertain')
        green = self.observe('2026-10-22T14:11:00Z', observation(pr()), wake='green')
        self.assertEqual(green['actions'][0]['kind'], 'wait-fixer')


class ReceiptKindTest(ContinuousCase):
    URL = 'https://github.com/fixture/widgets/pull/12'

    def test_armed_is_not_a_fixer_outcome_and_does_not_release_the_writer_guard(self):
        self.start()
        failing = [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
        action = self.observe('2026-10-22T14:05:00Z', observation(pr(checks=failing)),
                              wake='fail')['actions'][0]
        self.cli('dispatch', '--now', '2026-10-22T14:05:00Z', '--pr', self.URL,
                 '--request-id', action['request_id'], '--kind', 'fixer',
                 '--head', H1, '--reserve')
        refused = self.cli('receipt', '--now', '2026-10-22T14:05:30Z', '--pr', self.URL,
                           '--request-id', action['request_id'], '--status', 'armed',
                           ok=False)
        self.assertIn('not a terminal outcome', refused.stderr)
        state = json.loads(self.state.read_text())
        self.assertTrue(state['prs'][self.URL]['fixer']['in_flight'])
        guarded = self.observe('2026-10-22T14:06:00Z', observation(pr()), wake='green')
        self.assertEqual(guarded['actions'][0]['kind'], 'wait-fixer')

    def test_an_armed_merge_stays_pending_and_keeps_writers_out(self):
        self.start()
        action = self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='green')['actions'][0]
        self.assertEqual(action['kind'], 'merge')
        self.cli('dispatch', '--now', '2026-10-22T14:05:00Z', '--pr', self.URL,
                 '--request-id', action['request_id'], '--kind', 'merge', '--head', H1)
        armed = self.cli('receipt', '--now', '2026-10-22T14:05:30Z', '--pr', self.URL,
                         '--request-id', action['request_id'], '--status', 'armed')
        self.assertEqual(armed['status'], 'recorded')
        state = json.loads(self.state.read_text())
        self.assertEqual(state['prs'][self.URL]['dispatches'][0]['status'], 'armed')
        pending = self.observe('2026-10-22T14:06:00Z', observation(pr()), wake='watching')
        self.assertEqual(pending['actions'][0]['kind'], 'merge-pending')
        refused = self.cli('dispatch', '--now', '2026-10-22T14:06:30Z', '--pr', self.URL,
                           '--request-id', 'fixer-race', '--kind', 'fixer',
                           '--head', H1, ok=False)
        self.assertIn('may not race', refused.stderr)


class OwnerContinuationTest(ContinuousCase):
    def test_a_missing_continuation_field_never_releases_a_live_maintainer(self):
        self.start()
        live = pr(owner={'thread_id': 'other', 'status': 'running',
                         'continuation': 'maintainer-live'})
        first = self.observe('2026-10-22T14:05:00Z', observation(live), wake='live')
        self.assertEqual(first['actions'][0]['kind'], 'owned-elsewhere')
        partial = pr(owner={'thread_id': 'other', 'status': 'completed'})
        still = self.observe('2026-10-22T14:06:00Z', observation(partial), wake='partial')
        self.assertEqual(still['actions'][0]['kind'], 'owned-elsewhere')
        state = json.loads(self.state.read_text())
        self.assertEqual(state['prs'][live['url']]['owner']['continuation'], 'maintainer-live')
        handoff = pr(owner={'thread_id': 'other', 'status': 'completed',
                            'continuation': 'handed-back'})
        released = self.observe('2026-10-22T14:07:00Z', observation(handoff), wake='handoff')
        self.assertEqual(released['actions'][0]['kind'], 'merge')


class ReaderCompletenessTest(ContinuousCase):
    def row(self, **overrides):
        row = {'repo': REPO_A, 'number': 12, 'state': 'OPEN', 'head_oid': H1,
               'draft': False, 'fork': False, 'mergeable': 'MERGEABLE',
               'merge_state_status': 'CLEAN', 'checks_state': 'SUCCESS',
               'unresolved_threads': 0, 'review_threads_complete': True,
               'checks_complete': False, 'pending_checks': [], 'failing': []}
        row.update(overrides)
        return row

    def test_reader_completeness_false_blocks_landing_with_a_continuation(self):
        self.start()
        result = self.observe('2026-10-22T14:05:00Z', observation(self.row()), wake='partial')
        action = result['actions'][0]
        self.assertEqual(action['kind'], 'wait-checks')
        self.assertEqual(action['blocked']['kind'], 'incomplete-checks')
        self.assertIn('re-read', action['blocked']['continuation'])

    def test_an_unseen_queued_check_in_a_partial_reader_is_named_not_unknown(self):
        self.start()
        result = self.observe('2026-10-22T14:05:00Z',
                              observation(self.row(checks_state='PENDING')), wake='pending')
        action = result['actions'][0]
        self.assertEqual(action['kind'], 'wait-checks')
        self.assertEqual(action['blocked']['kind'], 'incomplete-checks')

    def test_missing_null_and_unknown_merge_states_require_gate_diagnosis(self):
        self.start()
        for index, state in enumerate(('missing', None, '', 'UNKNOWN')):
            with self.subTest(merge_state=state):
                row = self.row(checks_complete=True, required_contexts_known=False)
                if state == 'missing':
                    row.pop('merge_state_status')
                else:
                    row['merge_state_status'] = state
                result = self.observe('2026-10-22T14:05:00Z', observation(row),
                                      wake=f'unknown-gate-{index}')
                action = result['actions'][0]
                self.assertEqual(action['kind'], 'diagnose-gate')
                self.assertEqual(action['blocked']['kind'], 'stuck-aggregate-gate')
                self.assertEqual(action['blocked']['detail'], 'UNKNOWN')
                self.assertIsNotNone(action['next_check_at'])


class SchedulerCoverageTest(ContinuousCase):
    def test_losing_scheduler_capability_hides_the_historic_wake(self):
        self.start()
        self.record_schedule('sched-1', next_run='2026-10-22T14:10:00Z')
        revoked = self.cli('scheduler', '--now', '2026-10-22T14:05:00Z',
                           '--available', 'no', '--authorized', 'yes')
        self.assertEqual(revoked['status'], 'event-only')
        self.assertIsNone(revoked['scheduler']['next_run_at'])
        self.assertEqual(revoked['scheduler']['historical_next_run_at'],
                         '2026-10-22T14:10:00Z')
        observed = self.observe('2026-10-22T14:06:00Z', observation(pr()), wake='event', kind='event')
        self.assertEqual(observed['coverage'], 'stop-unverified')
        self.assertIsNone(observed['next_wake_at'])
        self.assertIsNone(observed['scheduler']['next_run_at'])
        self.assertFalse(observed['scheduler']['overdue'])

    def test_schedule_key_is_stable_per_run_and_distinct_between_runs(self):
        self.start(cadence=600)
        second = self.base / 'second-state.json'
        self.cli('start', '--now', '2026-10-22T14:00:00Z', '--scope-kind', 'org',
                 '--scope-value', 'fixture', '--scheduler', 'scheduled',
                 '--authorization-source', str(self.request), '--thread-id', 'self',
                 '--cadence-seconds', '900', state=second)
        first_plan = self.cli('schedule-plan')
        again = self.cli('schedule-plan')
        other_plan = self.cli('schedule-plan', state=second)
        self.assertEqual(first_plan['request']['clientRequestId'],
                         again['request']['clientRequestId'])
        self.assertNotEqual(first_plan['request']['clientRequestId'],
                            other_plan['request']['clientRequestId'])
        first_state = json.loads(self.state.read_text())
        self.assertIn(first_state['run_id'], first_plan['request']['clientRequestId'])
        self.assertIn(json.loads(second.read_text())['run_id'],
                      other_plan['request']['clientRequestId'])


class StateSafetyTest(ContinuousCase):
    def test_start_never_replaces_an_existing_run(self):
        self.start()
        self.record_schedule()
        before = self.state.read_bytes()
        refused = self.cli('start', '--now', '2026-10-22T14:00:00Z', '--scope-kind', 'org',
                           '--scope-value', 'fixture', '--scheduler', 'scheduled',
                           '--authorization-source', str(self.request), '--thread-id', 'self',
                           ok=False)
        self.assertIn('already exists', refused.stderr)
        self.assertEqual(self.state.read_bytes(), before)

    def test_transaction_lock_serialises_a_read_modify_write(self):
        self.start()
        lock_path = Path(str(self.state) + '.lock')
        held = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaises(subprocess.TimeoutExpired):
                subprocess.run([sys.executable, str(HELPER), 'status', '--state', str(self.state)],
                               capture_output=True, timeout=0.5)
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
            os.close(held)
        self.assertEqual(self.cli('status')['status'], 'active')

    def test_dispatch_rejects_a_second_fixer_and_a_racing_merge(self):
        self.start()
        failing = [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
        action = self.observe('2026-10-22T14:05:00Z', observation(pr(checks=failing)),
                              wake='fail')['actions'][0]
        url = 'https://github.com/fixture/widgets/pull/12'
        self.cli('dispatch', '--now', '2026-10-22T14:05:00Z', '--pr', url,
                 '--request-id', action['request_id'], '--kind', 'fixer', '--head', H1)
        second = self.cli('dispatch', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                          '--request-id', 'fixer-2', '--kind', 'fixer', '--head', H1, ok=False)
        self.assertIn('already in flight', second.stderr)
        merge = self.cli('dispatch', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                         '--request-id', 'merge-1', '--kind', 'merge', '--head', H1, ok=False)
        self.assertIn('may not race', merge.stderr)
        missing_head = self.cli('dispatch', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                                '--request-id', 'merge-2', '--kind', 'merge', ok=False)
        self.assertIn('exact head', missing_head.stderr)

    def test_stale_fixer_receipt_is_harmless_and_does_not_clear_the_next_writer(self):
        self.start()
        failing = [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
        url = 'https://github.com/fixture/widgets/pull/12'
        first = self.observe('2026-10-22T14:05:00Z', observation(pr(checks=failing)),
                             wake='fail')['actions'][0]
        self.cli('dispatch', '--now', '2026-10-22T14:05:00Z', '--pr', url,
                 '--request-id', first['request_id'], '--kind', 'fixer', '--head', H1,
                 '--host-task-id', 'host-fixer')
        result = self.accepted_result(first['request_id'])
        self.cli('fixer-done', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                 '--request-id', first['request_id'], '--result', str(result),
                 '--host-task-id', 'host-fixer')
        second = self.observe('2026-10-22T14:07:00Z', observation(pr(checks=failing)),
                              wake='fail-2')['actions'][0]
        self.assertEqual(second['kind'], 'dispatch-fixer')
        self.cli('dispatch', '--now', '2026-10-22T14:07:00Z', '--pr', url,
                 '--request-id', second['request_id'], '--kind', 'fixer', '--head', H1)
        with_progress = json.loads(self.state.read_text())['prs'][url]['last_meaningful_progress_at']
        replay = self.cli('receipt', '--now', '2026-10-22T14:08:00Z', '--pr', url,
                          '--request-id', first['request_id'], '--status', 'succeeded',
                          '--result', str(result))
        self.assertEqual(replay['status'], 'duplicate')
        state = json.loads(self.state.read_text())
        self.assertEqual(state['prs'][url]['fixer']['request_id'], second['request_id'])
        self.assertTrue(state['prs'][url]['fixer']['in_flight'])
        self.assertEqual(state['prs'][url]['last_meaningful_progress_at'], with_progress)


class AdoptedGuardTest(ContinuousCase):
    def test_an_observed_writer_can_be_closed_only_by_its_recorded_handle(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        observed = pr(owner={'thread_id': 'self', 'status': 'active',
                             'continuation': 'in-flight', 'fixer_in_flight': True,
                             'host_task_id': 'host-fixer-7'})
        held = self.observe('2026-10-22T14:05:00Z', observation(observed), wake='adopted')
        self.assertEqual(held['actions'][0]['kind'], 'wait-fixer')
        result = self.base / 'adopted-result.json'
        result.write_text('{"outcome":"fixed"}')
        # An arbitrary historical request id and an unrelated result are not evidence
        # about the observed writer.
        unrelated = self.cli('fixer-done', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                             '--request-id', 'unrelated-old-task', '--result', str(result),
                             ok=False)
        self.assertIn('does not match the adopted writer', unrelated.stderr)
        wrong_handle = self.cli('fixer-done', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                                '--request-id', 'adopted-handle', '--result', str(result),
                                '--host-task-id', 'some-other-task', ok=False)
        self.assertIn('does not match the adopted writer', wrong_handle.stderr)
        state = json.loads(self.state.read_text())
        progress = state['prs'][url]['last_meaningful_progress_at']
        self.assertTrue(state['prs'][url]['fixer']['in_flight'])
        still = self.observe('2026-10-22T14:06:30Z', observation(pr()), wake='still-held')
        self.assertEqual(still['actions'][0]['kind'], 'wait-fixer')
        self.assertEqual(json.loads(self.state.read_text())['prs'][url][
            'last_meaningful_progress_at'], progress)
        accepted = self.accepted_result('adopted-handle', 'host-fixer-7')
        cleared = self.cli('fixer-done', '--now', '2026-10-22T14:07:00Z', '--pr', url,
                           '--request-id', 'adopted-handle', '--result', str(accepted),
                           '--host-task-id', 'host-fixer-7')
        self.assertEqual(cleared['status'], 'recorded')
        landed = self.observe('2026-10-22T14:08:00Z', observation(pr()), wake='after')
        self.assertEqual(landed['actions'][0]['kind'], 'merge')

    def test_an_adopted_writer_without_a_handle_cannot_be_released(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        observed = pr(owner={'thread_id': 'self', 'status': 'active',
                             'continuation': 'in-flight', 'fixer_in_flight': True})
        self.observe('2026-10-22T14:05:00Z', observation(observed), wake='adopted')
        result = self.base / 'adopted-result.json'
        result.write_text('{"outcome":"fixed"}')
        refused = self.cli('fixer-done', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                           '--request-id', 'adopted-handle', '--result', str(result),
                           ok=False)
        self.assertIn('no recorded host handle', refused.stderr)


class RepairAndMergeTest(ContinuousCase):
    def test_terminal_repair_attempts_are_bounded_not_treated_as_in_flight(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        failing = [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
        for attempt in range(1, 4):
            result = self.observe(f'2026-10-22T14:0{attempt}:00Z',
                                  observation(pr(checks=failing)), wake=f'wake-{attempt}')
            action = result['actions'][0]
            self.assertEqual(action['kind'], 'dispatch-fixer')
            self.cli('dispatch', '--now', f'2026-10-22T14:0{attempt}:30Z', '--pr', url,
                     '--request-id', action['request_id'], '--kind', 'fixer', '--head', H1)
            self.cli('receipt', '--now', f'2026-10-22T14:0{attempt}:45Z', '--pr', url,
                     '--request-id', action['request_id'], '--status', 'rejected')
        exhausted = self.observe('2026-10-22T14:09:00Z', observation(pr(checks=failing)),
                                 wake='after-exhaustion')
        self.assertEqual(exhausted['actions'][0]['kind'], 'blocked')
        self.assertEqual(exhausted['actions'][0]['blocked']['kind'], 'repair-exhausted')

    def test_merge_attempts_are_bound_to_the_exact_head(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        first = self.observe('2026-10-22T14:05:00Z', observation(pr(head=H1)), wake='green-1')
        self.assertEqual(first['actions'][0]['kind'], 'merge')
        self.cli('dispatch', '--now', '2026-10-22T14:05:30Z', '--pr', url,
                 '--request-id', 'merge-h1', '--kind', 'merge', '--head', H1)
        moved = self.observe('2026-10-22T14:06:00Z', observation(pr(head=H2)), wake='new-head')
        self.assertEqual(moved['actions'][0]['kind'], 'merge-pending')
        self.assertEqual(moved['actions'][0]['head'], H1)
        state = json.loads(self.state.read_text())
        old = next(row for row in state['prs'][url]['dispatches']
                   if row['request_id'] == 'merge-h1')
        self.assertEqual(old['status'], 'pending')
        self.assertEqual(old['stale_at_head'], H2)
        self.cli('receipt', '--now', '2026-10-22T14:06:10Z', '--pr', url,
                 '--request-id', 'merge-h1', '--status', 'rejected', '--head', H1)
        settled = self.observe('2026-10-22T14:06:20Z', observation(pr(head=H2)), wake='settled')
        self.assertEqual(settled['actions'][0]['kind'], 'merge')
        self.assertEqual(settled['actions'][0]['head'], H2)
        self.cli('dispatch', '--now', '2026-10-22T14:06:30Z', '--pr', url,
                 '--request-id', 'merge-h2', '--kind', 'merge', '--head', H2)
        self.cli('receipt', '--now', '2026-10-22T14:07:00Z', '--pr', url,
                 '--request-id', 'merge-h2', '--status', 'rejected', '--head', H2)
        retried = self.observe('2026-10-22T14:08:00Z', observation(pr(head=H2)), wake='retry')
        self.assertEqual(retried['actions'][0]['kind'], 'merge')
        self.assertIn('-a2', retried['actions'][0]['request_id'])

    def test_excluded_rows_stay_visible_and_lose_their_action(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='green')
        excluded = self.observe('2026-10-22T14:06:00Z', observation(pr(draft=True)), wake='draft')
        self.assertEqual(excluded['actions'], [])
        self.assertEqual(excluded['excluded'][0]['pr'], url)
        status = self.cli('status')
        self.assertEqual(status['prs'][url]['state'], 'excluded')
        self.assertIsNone(status['prs'][url]['next_action'])
        self.assertIsNone(status['prs'][url]['blocked'])
        self.assertEqual(status['open_prs'], [])
        returned = self.observe('2026-10-22T14:07:00Z', observation(pr()), wake='ready')
        self.assertEqual(returned['actions'][0]['kind'], 'merge')
        self.assertEqual(self.cli('status')['prs'][url]['state'], 'open')

    def test_ownership_evidence_is_not_replaced_by_an_omitted_owner(self):
        self.start()
        owned = pr(owner={'thread_id': 'other', 'status': 'running',
                          'continuation': 'in-flight'})
        live = self.observe('2026-10-22T14:05:00Z', observation(owned), wake='owned')
        self.assertEqual(live['actions'][0]['kind'], 'owned-elsewhere')
        without = pr()
        without.pop('owner')
        still = self.observe('2026-10-22T14:06:00Z', observation(without), wake='no-owner')
        self.assertEqual(still['actions'][0]['kind'], 'owned-elsewhere')
        self.assertEqual(self.cli('status')['prs'][owned['url']]['owner']['thread_id'], 'other')
        released = pr(owner={'thread_id': 'other', 'status': 'completed',
                             'continuation': 'handed-back'})
        after = self.observe('2026-10-22T14:07:00Z', observation(released), wake='released')
        self.assertEqual(after['actions'][0]['kind'], 'merge')

    def test_finished_check_evidence_from_another_head_never_authorises_a_merge(self):
        self.start()
        check = {'name': 'ci', 'status': 'COMPLETED', 'conclusion': 'SUCCESS',
                 'head_sha': H2}
        result = self.observe('2026-10-22T14:05:00Z',
                              observation(pr(head=H1, checks=[check])), wake='wrong-head')
        self.assertEqual(result['actions'][0]['kind'], 'wait-checks')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'stale-head-checks')
        header = pr(head=H1)
        header['checks_head_sha'] = H2
        result = self.observe('2026-10-22T14:06:00Z', observation(header), wake='wrong-header')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'stale-head-checks')

    def test_incomplete_check_context_page_blocks_landing(self):
        self.start()
        row = pr()
        row['checks_complete'] = False
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='checks')
        self.assertEqual(result['actions'][0]['kind'], 'wait-checks')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'incomplete-checks')

    def test_incomplete_thread_read_blocks_landing(self):
        self.start()
        row = pr()
        row['review_threads_complete'] = False
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='threads')
        self.assertEqual(result['actions'][0]['kind'], 'wait-threads')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'incomplete-threads')
        page = pr()
        page['review_threads_complete'] = None
        missing = self.observe('2026-10-22T14:06:00Z', observation(page), wake='no-thread-read')
        self.assertEqual(missing['actions'][0]['kind'], 'wait-threads')

    def test_queue_diagnosis_does_not_starve_a_failed_check(self):
        self.start()
        checks = [queued(created='2026-10-22T13:00:00Z'),
                  {'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
        result = self.observe('2026-10-22T14:27:00Z',
                              observation(pr(checks=checks, checks_state='FAILURE')),
                              wake='both')
        self.assertEqual(result['actions'][0]['kind'], 'dispatch-fixer')
        self.assertIn('lint', result['actions'][0]['reason'])

    def test_startup_failure_is_a_repairable_failed_check(self):
        self.start()
        check = {'name': 'ci', 'status': 'COMPLETED', 'conclusion': 'STARTUP_FAILURE'}
        row = pr(checks=[check], checks_state='FAILURE', merge_state='BLOCKED',
                 required_contexts=['ci'])
        row['head_sha'] = H1
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='startup')
        self.assertEqual(result['actions'][0]['kind'], 'dispatch-fixer')
        self.assertIn('ci', result['actions'][0]['reason'])

    def test_reordered_checks_do_not_reset_the_progress_clock(self):
        self.start()
        first = queued(name='a', created='2026-10-22T14:00:00Z')
        second = queued(name='b', created='2026-10-22T14:01:00Z')
        self.observe('2026-10-22T14:05:00Z', observation(pr(checks=[first, second])),
                     wake='order-1')
        before = json.loads(self.state.read_text())['prs'][
            'https://github.com/fixture/widgets/pull/12']['last_meaningful_progress_at']
        again = self.observe('2026-10-22T14:06:00Z', observation(pr(checks=[second, first])),
                             wake='order-2')
        self.assertFalse(again['progress']['meaningful'])
        after = json.loads(self.state.read_text())['prs'][
            'https://github.com/fixture/widgets/pull/12']['last_meaningful_progress_at']
        self.assertEqual(before, after)


class SchedulerLifecycleTest(ContinuousCase):
    def test_reported_coverage_distinguishes_authorization_receipt_and_delivery(self):
        self.start()
        unverified = self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='early')
        self.assertEqual(unverified['coverage'], 'scheduled-unverified')
        self.assertIsNone(unverified['scheduler']['schedule_id'])
        self.assertIsNone(unverified['next_wake_at'])
        self.assertIn('no host schedule receipt', unverified['scheduler']['gap'])

        self.record_schedule('sched-1', next_run='2026-10-22T14:10:00Z')
        overdue = self.observe('2026-10-22T14:20:00Z', observation(pr()), wake='manual-late',
                               kind='event')
        self.assertTrue(overdue['scheduler']['overdue'])
        self.assertEqual(overdue['next_wake_at'], '2026-10-22T14:10:00Z')

        delivered = self.observe('2026-10-22T14:21:00Z', observation(pr()), wake='sched-1-wake')
        self.assertEqual(delivered['coverage'], 'scheduled')
        self.assertFalse(delivered['scheduler']['overdue'])
        self.assertIsNone(delivered['next_wake_at'])
        self.assertTrue(delivered['scheduler']['awaiting_receipt'])
        self.assertEqual(delivered['scheduler']['last_wake_at'], '2026-10-22T14:21:00Z')


    def test_event_only_mode_never_reports_a_future_wake(self):
        started = self.start(scheduler='event-only')
        self.assertEqual(started['scheduler']['gap'].count('event-only'), 1)
        observed = self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='event-only')
        self.assertEqual(observed['coverage'], 'event-only')
        self.assertIsNone(observed['next_wake_at'])
        self.assertIsNone(observed['scheduler']['schedule_id'])

    def test_cancellation_blocks_new_work_but_not_late_receipts(self):
        self.start()
        failing = [{'name': 'lint', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]
        url = 'https://github.com/fixture/widgets/pull/12'
        action = self.observe('2026-10-22T14:05:00Z', observation(pr(checks=failing)),
                              wake='fail')['actions'][0]
        self.cli('dispatch', '--now', '2026-10-22T14:05:30Z', '--pr', url,
                 '--request-id', action['request_id'], '--kind', 'fixer', '--head', H1)
        self.cli('cancel', '--now', '2026-10-22T14:06:00Z', '--reason', 'owner stopped')
        plan = self.cli('schedule-plan')
        self.assertEqual(plan['status'], 'cancelled')
        self.assertIsNone(plan['request'])
        refused = self.cli('dispatch', '--now', '2026-10-22T14:06:30Z', '--pr', url,
                           '--request-id', 'new-worker', '--kind', 'fixer', '--head', H1,
                           ok=False)
        self.assertIn('cancelled', refused.stderr)
        late = self.cli('receipt', '--now', '2026-10-22T14:07:00Z', '--pr', url,
                        '--request-id', action['request_id'], '--status', 'rejected')
        self.assertEqual(late['status'], 'recorded')

    def test_verified_stop_allows_a_safe_rearm_that_preserves_history(self):
        self.start()
        self.record_schedule('sched-1')
        unverified = self.cli('schedule-stop', '--now', '2026-10-22T14:06:00Z',
                              '--schedule-id', 'sched-1', '--verified', 'no')
        self.assertEqual(unverified['status'], 'stop-unverified')
        blocked = self.cli('schedule-plan')
        self.assertEqual(blocked['status'], 'stop-unverified')
        self.assertIsNone(blocked['request'])
        replaced = self.cli('schedule-record', '--now', '2026-10-22T14:06:30Z',
                            '--schedule-id', 'sched-2',
                            '--next-run-at', '2026-10-22T14:16:00Z', ok=False)
        self.assertIn('verify the previous schedule', replaced.stderr)

        verified = self.cli('schedule-stop', '--now', '2026-10-22T14:07:00Z',
                            '--schedule-id', 'sched-1', '--verified', 'yes')
        self.assertEqual(verified['status'], 'stopped')
        plan = self.cli('schedule-plan')
        self.assertEqual(plan['status'], 'plan')
        self.assertEqual(plan['generation'], 2)
        self.assertIn('-g2', plan['request']['key'])
        recorded = self.record_schedule('sched-2', next_run='2026-10-22T14:18:00Z',
                                        at='2026-10-22T14:08:00Z')
        self.assertEqual(recorded['status'], 'recorded')
        state = json.loads(self.state.read_text())
        self.assertEqual(len(state['scheduler']['history']), 2)
        self.assertIsNone(state['scheduler']['stopped'])
        self.assertEqual(self.cli('status')['scheduler']['schedule_id'], 'sched-2')

    def test_cancelled_run_requires_resume_before_rearming(self):
        self.start()
        self.record_schedule('sched-1')
        self.cli('cancel', '--now', '2026-10-22T14:05:00Z', '--reason', 'stop')
        self.assertEqual(self.cli('schedule-plan')['status'], 'cancelled')
        self.cli('schedule-stop', '--now', '2026-10-22T14:06:00Z',
                 '--schedule-id', 'sched-1', '--verified', 'yes')
        self.assertEqual(self.cli('schedule-plan')['status'], 'cancelled')
        self.cli('resume', '--now', '2026-10-22T14:07:00Z', '--resume-cancelled')
        self.assertEqual(self.cli('schedule-plan')['status'], 'plan')


class DiscoveryCoverageTest(ContinuousCase):
    def test_partial_scope_does_not_block_a_pr_with_its_own_fresh_evidence(self):
        self.start()
        self.record_schedule()
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='complete')
        partial = observation(pr(), complete=False,
                              gaps=[{'kind': 'rate-limit', 'detail': 'repository B'}])
        result = self.observe('2026-10-22T14:15:00Z', partial, wake='partial')
        actions = {row.get('pr'): row for row in result['actions']}
        self.assertEqual(actions['https://github.com/fixture/widgets/pull/12']['kind'], 'merge')
        self.assertIn('rate-limit', result['discovery']['gaps'][0]['kind'])
        for attempt in range(2, 5):
            last = self.observe(f'2026-10-22T14:{15 + attempt:02d}:00Z', partial,
                                wake=f'partial-{attempt}')
        kinds = [row['kind'] for row in last['actions']]
        self.assertIn('discovery-blocked', kinds)
        self.assertIn('merge', kinds)

    def test_current_discovery_gaps_describe_an_omitted_pr(self):
        self.start()
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='complete')
        partial = observation(complete=False,
                              gaps=[{'kind': 'rate-limit', 'detail': 'search page 2'}])
        result = self.observe('2026-10-22T14:15:00Z', partial, wake='partial')
        action = result['actions'][0]
        self.assertEqual(action['kind'], 'reconcile-discovery')
        self.assertEqual(action['blocked']['kind'], 'discovery-omission')
        self.assertEqual(action['blocked']['detail'][0]['kind'], 'rate-limit')

    def test_closed_pr_reopens_from_an_explicit_observation(self):
        self.start()
        url = 'https://github.com/fixture/widgets/pull/12'
        self.observe('2026-10-22T14:05:00Z', observation(pr()), wake='seen')
        self.cli('resolve', '--now', '2026-10-22T14:06:00Z', '--pr', url,
                 '--resolution', 'closed', '--head', H1)
        self.assertEqual(self.cli('status')['open_prs'], [])
        reopened = self.observe('2026-10-22T14:07:00Z', observation(pr()), wake='reopened')
        self.assertEqual(self.cli('status')['open_prs'], [url])
        self.assertEqual(reopened['actions'][0]['kind'], 'merge')
        state = json.loads(self.state.read_text())
        self.assertEqual(len(state['prs'][url]['reopens']), 1)


class PackagePreflightTest(ContinuousCase):
    def test_resume_detects_a_swapped_running_package_without_a_version_flag(self):
        copied = self.base / 'plugin-copy'
        shutil.copytree(PLUGIN, copied)
        helper = copied / 'scripts' / 'continuous.py'
        self.start(helper=helper)
        state = json.loads(self.state.read_text())
        self.assertEqual(state['package']['pinned_version'], '1.3.0')
        self.assertTrue(state['package']['installed_digest'])
        (copied / 'references' / 'continuous.md').write_text(
            (copied / 'references' / 'continuous.md').read_text() + '\nchanged snapshot\n')
        migration = self.cli('resume', '--now', '2026-10-22T14:10:00Z', helper=helper)
        self.assertEqual(migration['status'], 'migration-required')
        self.assertIn('installed-drift', [gap['kind'] for gap in migration['gaps']])
        self.assertFalse(migration['changed'])

    def test_package_drift_needs_the_supported_upgrade_receipt_for_the_target_package(self):
        copied = self.base / 'plugin-copy'
        shutil.copytree(PLUGIN, copied)
        helper = copied / 'scripts' / 'continuous.py'
        self.start(helper=helper)
        (copied / 'references' / 'continuous.md').write_text(
            (copied / 'references' / 'continuous.md').read_text() + '\nchanged snapshot\n')
        identity = json.loads(subprocess.run(
            [sys.executable, str(helper), 'version'], capture_output=True, text=True,
            timeout=30).stdout)
        refused = self.cli('resume', '--now', '2026-10-22T14:10:00Z',
                           '--accept-migration', '--owner-decision-id', 'owner-one',
                           helper=helper, ok=False)
        self.assertIn('upgrade receipt', refused.stderr)
        wrong = self.base / 'wrong-receipt.json'
        wrong.write_text(json.dumps({'job_id': 'job-1', 'package_digest': '0' * 64,
                                     'owner_decision_id': 'owner-one'}))
        bad = self.cli('resume', '--now', '2026-10-22T14:10:00Z',
                       '--accept-migration', '--owner-decision-id', 'owner-one',
                       '--upgrade-receipt', str(wrong), helper=helper, ok=False)
        self.assertIn('does not name the running package digest', bad.stderr)
        receipt = self.base / 'upgrade-receipt.json'
        receipt.write_text(json.dumps({'job_id': 'job-1', 'package_digest': identity['digest'],
                                       'package_dir': str(copied),
                                       'owner_decision_id': 'owner-one'}))
        refused = self.cli('resume', '--now', '2026-10-22T14:11:00Z',
                            '--accept-migration', '--owner-decision-id', 'owner-one',
                            '--upgrade-receipt', str(receipt), helper=helper, ok=False)
        self.assertIn('requires --job', refused.stderr)

    def test_a_legacy_state_without_a_package_identity_is_a_migration_gap(self):
        self.start()
        state = json.loads(self.state.read_text())
        state['package'] = {'pinned_version': None}
        self.state.write_text(json.dumps(state))
        migration = self.cli('resume', '--now', '2026-10-22T14:10:00Z')
        self.assertEqual(migration['status'], 'migration-required')
        self.assertIn('missing-package-identity', [gap['kind'] for gap in migration['gaps']])
        self.assertFalse(migration['changed'])
        refused = self.cli('resume', '--now', '2026-10-22T14:10:00Z',
                           '--accept-migration', '--owner-decision-id', 'owner-one',
                           ok=False)
        self.assertIn('upgrade receipt', refused.stderr)

    def test_an_upgrade_receipt_for_a_different_pinned_job_is_refused(self):
        self.start(job_id='job-legacy')
        copied = self.base / 'plugin-copy'
        shutil.copytree(PLUGIN, copied)
        helper = copied / 'scripts' / 'continuous.py'
        state = json.loads(self.state.read_text())
        state['package']['installed_digest'] = 'f' * 64
        self.state.write_text(json.dumps(state))
        identity = json.loads(subprocess.run(
            [sys.executable, str(helper), 'version'], capture_output=True, text=True,
            timeout=30).stdout)
        receipt = self.base / 'wrong-job.json'
        receipt.write_text(json.dumps({'job_id': 'job-other',
                                       'package_digest': identity['digest'],
                                       'package_dir': str(copied)}))
        refused = self.cli('resume', '--now', '2026-10-22T14:10:00Z',
                           '--accept-migration', '--owner-decision-id', 'owner-one',
                           '--upgrade-receipt', str(receipt), helper=helper, ok=False)
        self.assertIn('is not the pinned job', refused.stderr)

    def test_migration_refuses_a_runner_that_is_not_the_pinned_package(self):
        self.start()
        state = json.loads(self.state.read_text())
        state['policy_version'] = 'continuous-0'
        state['package']['pinned_version'] = '1.2.2+content.abc123'
        self.state.write_text(json.dumps(state))
        refused = self.cli('resume', '--now', '2026-10-22T14:10:00Z',
                           '--package-version', '1.2.2+content.abc123',
                           '--accept-migration', '--owner-decision-id', 'owner-approve',
                           ok=False)
        self.assertIn('upgrade-package', refused.stderr)
        self.assertEqual(json.loads(self.state.read_text())['policy_version'], 'continuous-0')

    def test_legacy_pinned_job_preflight_preserves_every_artifact(self):
        job_dir = self.base / 'job'
        job_dir.mkdir()
        old_package = self.base / 'old-package'
        (old_package / 'scripts').mkdir(parents=True)
        (old_package / 'plugin.json').write_text(json.dumps(
            {'name': 'babysitter', 'version': '1.2.2'}))
        job = {'job_id': 'job-legacy', 'workflow': 'babysitter/org',
               'pins': {'babysitter': {'version': '1.2.2+content.332f8b2d43b5',
                                       'package_dir': str(old_package)}}}
        (job_dir / 'job.json').write_text(json.dumps(job))
        before = {path.name: path.read_bytes() for path in job_dir.iterdir()}
        result = self.cli('preflight', '--job', str(job_dir),
                          '--now', '2026-10-22T14:05:00Z')
        self.assertEqual(result['status'], 'legacy-job')
        self.assertFalse(result['pinned_package_has_helper'])
        self.assertEqual(result['gaps'][0]['kind'], 'pinned-package-without-continuous')
        self.assertFalse(result['changed'])
        self.assertIn('upgrade-package', result['instruction'])
        self.assertEqual({path.name: path.read_bytes() for path in job_dir.iterdir()}, before)


class ReaderPathTest(ContinuousCase):
    """Feed the shipped reader's own row into the helper, not a hand-written shape."""

    def reader_row(self, payload, job_payload=None, pr_number=None):
        directory = self.base / 'bin'
        directory.mkdir(exist_ok=True)
        curl = '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
sys.stdin.read()
url = next(arg for arg in args if arg.startswith('https://'))
if '/actions/jobs/' in url:
    body = os.environ['FIXTURE_JOB_PAYLOAD']
else:
    body = os.environ['FIXTURE_PAYLOAD']
Path(args[args.index('-o') + 1]).write_text(body)
print('200', end='')
'''
        for name, body in {'gh': '#!/bin/sh\nprintf fixture-token',
                           'sleep': '#!/bin/sh\nexit 0', 'curl': curl}.items():
            path = directory / name
            path.write_text(body)
            path.chmod(0o755)
        env = {**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
               'FIXTURE_PAYLOAD': json.dumps(payload),
               'FIXTURE_JOB_PAYLOAD': json.dumps(job_payload or {})}
        argv = ['bash', str(PLUGIN / 'scripts' / 'list-prs.sh'), '--repo', 'fixture/repo']
        if pr_number is not None:
            argv += ['--pr', str(pr_number)]
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def node(self, *, checks, checks_state, merge_state='BLOCKED', review_threads_complete=True):
        return {
            'number': 12, 'title': 'Reader PR', 'url': 'https://github.com/fixture/repo/pull/12',
            'state': 'OPEN', 'isDraft': False, 'isCrossRepository': False,
            'mergeable': 'MERGEABLE', 'mergeStateStatus': merge_state,
            'author': {'login': 'fixture'}, 'headRefName': 'topic', 'baseRefName': 'main',
            'baseRef': {'target': {'oid': '1' * 40}},
            'repository': {'nameWithOwner': 'fixture/repo'},
            'commits': {'nodes': [{'commit': {'oid': H1, 'statusCheckRollup': {
                'state': checks_state,
                'contexts': {'totalCount': len(checks), 'pageInfo': {'hasNextPage': False},
                             'nodes': checks}}}}]},
            'comments': {'nodes': []}, 'reviews': {'nodes': []}, 'reviewDecision': 'APPROVED',
            'latestReviews': {'nodes': []},
            'reviewThreads': {'totalCount': 0,
                              'pageInfo': {'hasNextPage': not review_threads_complete},
                              'nodes': []},
        }

    def test_reader_queue_clock_reaches_queue_diagnosis(self):
        checks = [
            {'__typename': 'CheckRun', 'name': 'Validate compose files', 'status': 'QUEUED',
             'conclusion': None, 'startedAt': None,
             'detailsUrl': 'https://github.com/fixture/repo/actions/runs/39793710469/job/119875753605'},
            {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED',
             'conclusion': 'SUCCESS', 'startedAt': '2026-10-22T13:00:00Z', 'detailsUrl': None},
        ]
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'search': {'issueCount': 1,
                                       'nodes': [self.node(checks=checks, checks_state='PENDING')]}}}
        row = self.reader_row(payload, {'id': 119875753605, 'created_at': '2026-10-22T14:12:00Z'})
        self.start()
        result = self.observe('2026-10-22T14:27:00Z', observation(row), wake='reader-queue')
        self.assertEqual(result['queue'][0]['age_seconds'], 900)
        self.assertEqual(result['actions'][0]['kind'], 'diagnose-queue')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'waiting-for-runner')

    def test_reader_null_aggregate_gate_reaches_diagnosis(self):
        node = self.node(checks=[], checks_state='SUCCESS', merge_state=None)
        payload = {'data': {'viewer': {'login': 'fixture'},
                           'repository': {'pullRequest': node}}}
        row = self.reader_row(payload, pr_number=12)
        self.assertIsNone(row['merge_state_status'])
        self.start()
        action = self.observe('2026-10-22T14:05:00Z', observation(row),
                              wake='null-reader')['actions'][0]
        self.assertEqual(action['kind'], 'diagnose-gate')
        self.assertEqual(action['blocked']['detail'], 'UNKNOWN')

    def test_pr_reader_required_status_context_reaches_repair(self):
        checks = [
            {'__typename': 'StatusContext', 'context': 'required-ci', 'state': 'FAILURE',
             'createdAt': '2026-10-22T13:00:00Z', 'isRequired': True},
            {'__typename': 'CheckRun', 'name': 'optional-lint', 'status': 'COMPLETED',
             'conclusion': 'FAILURE', 'startedAt': '2026-10-22T13:00:00Z',
             'detailsUrl': None, 'isRequired': False},
        ]
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'repository': {'pullRequest': self.node(
                                checks=checks, checks_state='FAILURE')}}}
        row = self.reader_row(payload, pr_number=12)
        self.assertEqual(row['required_contexts_observed'], ['required-ci'])
        self.assertFalse(row['required_contexts_known'])
        self.start()
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='pr-reader')
        action = result['actions'][0]
        self.assertEqual(action['kind'], 'dispatch-fixer')
        self.assertIn('required-ci', action['reason'])
        self.assertNotIn('optional-lint', action['reason'])

    def test_reader_optional_failure_does_not_dispatch_a_repair(self):
        checks = [
            {'__typename': 'CheckRun', 'name': 'ci', 'status': 'COMPLETED',
             'conclusion': 'SUCCESS', 'startedAt': '2026-10-22T13:00:00Z', 'detailsUrl': None},
            {'__typename': 'CheckRun', 'name': 'optional-lint', 'status': 'COMPLETED',
             'conclusion': 'FAILURE', 'startedAt': '2026-10-22T13:00:00Z', 'detailsUrl': None},
        ]
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'search': {'issueCount': 1,
                                       'nodes': [self.node(checks=checks, checks_state='FAILURE',
                                                           merge_state='UNSTABLE')]}}}
        row = self.reader_row(payload)
        self.assertIsNone(row['required_contexts'])
        self.assertFalse(row['required_contexts_known'])
        self.start()
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='reader-unstable')
        self.assertEqual(result['actions'][0]['kind'], 'merge')

    def test_optional_failure_with_an_unsatisfied_protection_is_diagnosed_not_repaired(self):
        checks = [{'__typename': 'CheckRun', 'name': 'optional-lint', 'status': 'COMPLETED',
                   'conclusion': 'FAILURE', 'startedAt': '2026-10-22T13:00:00Z',
                   'detailsUrl': None, 'isRequired': False}]
        payload = {'data': {'viewer': {'login': 'fixture'}, 'repository': {'pullRequest':
            self.node(checks=checks, checks_state='FAILURE', merge_state='BLOCKED')}}}
        row = self.reader_row(payload, pr_number=12)
        self.assertEqual(row['required_contexts_observed'], [])
        self.assertEqual(row['optional_contexts_observed'], ['optional-lint'])
        self.start()
        result = self.observe('2026-10-22T14:05:00Z', observation(row), wake='optional')
        self.assertEqual(result['actions'][0]['kind'], 'diagnose-gate')
        self.assertEqual(result['actions'][0]['blocked']['kind'], 'stuck-aggregate-gate')


class InstalledPackageTest(unittest.TestCase):
    def install(self, base):
        env = {**os.environ, 'HOME': str(base / 'home'),
               'XDG_CONFIG_HOME': str(base / 'config'),
               'XDG_STATE_HOME': str(base / 'xdg-state')}
        proc = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'babysitter',
             '--prefix', str(base / 'prefix'), '--agents-root', str(base / 'agents')],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return Path(json.loads(proc.stdout)['data']['version_dir']), env

    def start_state(self, helper, base, *extra):
        request = base / 'request.txt'
        request.write_text('owner request\n')
        state = base / 'installed-state.json'
        proc = subprocess.run(
            [sys.executable, str(helper), 'start', '--state', str(state),
             '--now', '2026-10-22T14:00:00Z', '--scope-kind', 'org',
             '--scope-value', 'fixture', '--scheduler', 'scheduled',
             '--authorization-source', str(request), '--thread-id', 'self', *extra],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return state

    def test_installed_helper_exposes_the_same_policy_and_state_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            version_dir, _ = self.install(base)
            helper = version_dir / 'scripts' / 'continuous.py'
            self.assertTrue(helper.is_file())
            self.assertTrue((version_dir / 'scripts' / 'continuous_sweep.py').is_file())
            version = subprocess.run([sys.executable, str(helper), 'version'],
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(version.returncode, 0, version.stderr)
            identity = json.loads(version.stdout)
            self.assertEqual(identity['policy_version'], 'continuous-1')
            self.assertTrue(identity['version'].startswith('1.3.0'), identity['version'])

            state = self.start_state(helper, base)
            observation_path = base / 'obs.json'
            observation_path.write_text(json.dumps(observation(pr(checks=[queued()]))))
            observed = subprocess.run(
                [sys.executable, str(helper), 'observe', '--state', str(state),
                 '--now', '2026-10-22T14:27:01Z', '--wake-kind', 'schedule',
                 '--wake-id', 'installed-wake', '--observation', str(observation_path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertEqual(json.loads(observed.stdout)['actions'][0]['kind'], 'diagnose-queue')

    def test_installed_adapter_delivers_the_causal_scheduled_wake(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            version_dir, _ = self.install(base)
            helper = version_dir / 'scripts' / 'continuous.py'
            adapter = version_dir / 'scripts' / 'continuous_sweep.py'
            state = self.start_state(helper, base)
            spec = importlib.util.spec_from_file_location('installed_sweep', adapter)
            installed_sweep = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(installed_sweep)
            queued_pr = pr(checks=[queued()])
            host = FakeHost(observation(queued_pr))
            host.clock = '2026-10-22T14:00:00Z'
            armed = installed_sweep.arm(host, state, '2026-10-22T14:00:00Z')
            self.assertEqual(armed['status'], 'armed')
            first = installed_sweep.tick(host, state, '2026-10-22T14:27:00Z')
            self.assertEqual(first[0]['result']['actions'][0]['kind'], 'diagnose-queue')
            host.snapshot = observation(queued_pr, pr(REPO_B, 78, head=H2))
            second = installed_sweep.tick(host, state, '2026-10-22T14:37:00Z')
            self.assertEqual([row['number'] for row in second[0]['result']['admitted']], [78])
            self.assertEqual(second[0]['dispatched'][0]['recorded'], 'recorded')

    def test_installed_helper_refuses_a_fabricated_legacy_upgrade_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            version_dir, _ = self.install(base)
            helper = version_dir / 'scripts' / 'continuous.py'
            old_package = base / 'legacy-package'
            (old_package / 'scripts').mkdir(parents=True)
            (old_package / 'plugin.json').write_text(json.dumps(
                {'name': 'babysitter', 'version': '1.2.2'}))
            job_dir = base / 'job'
            job_dir.mkdir()
            brief = job_dir / 'brief.md'
            brief.write_text('# frozen brief\n')
            evidence = job_dir / 'evidence.json'
            evidence.write_text('{"pr": "fixture/widgets#12"}\n')
            (job_dir / 'job.json').write_text(json.dumps({
                'job_id': 'job-legacy', 'workflow': 'babysitter/org',
                'pins': {'babysitter': {'version': '1.2.2+content.332f8b2d43b5',
                                        'package_dir': str(old_package)}}}))
            before = {path.name: path.read_bytes() for path in job_dir.iterdir()}
            preflight = subprocess.run(
                [sys.executable, str(helper), 'preflight', '--job', str(job_dir),
                 '--now', '2026-10-22T14:05:00Z'], capture_output=True, text=True, timeout=30)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            report = json.loads(preflight.stdout)
            self.assertEqual(report['status'], 'legacy-job')
            self.assertFalse(report['pinned_package_has_helper'])
            self.assertIn('scripts/continuous.py', report['gaps'][0]['detail'])
            self.assertEqual({path.name: path.read_bytes() for path in job_dir.iterdir()}, before)

            identity = json.loads(subprocess.run(
                [sys.executable, str(helper), 'version'], capture_output=True, text=True,
                timeout=30).stdout)
            state = base / 'legacy-state.json'
            state.write_text(json.dumps({
                'schema_version': 1, 'policy_version': 'continuous-0', 'job_id': 'job-legacy',
                'package': {'pinned_version': '1.2.2+content.332f8b2d43b5'}, 'prs': {}}))
            first = subprocess.run(
                [sys.executable, str(helper), 'resume', '--state', str(state),
                 '--now', '2026-10-22T14:06:00Z'], capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_report = json.loads(first.stdout)
            self.assertEqual(first_report['status'], 'migration-required')
            kinds = {gap['kind'] for gap in first_report['gaps']}
            self.assertEqual(kinds, {'policy-version', 'missing-package-identity'})
            receipt = base / 'upgrade-receipt.json'
            receipt.write_text(json.dumps({
                'job_id': 'job-legacy', 'package_digest': identity['digest'],
                'package_dir': str(version_dir), 'owner_decision_id': 'owner-one'}))
            migrated = subprocess.run(
                [sys.executable, str(helper), 'resume', '--state', str(state),
                 '--now', '2026-10-22T14:07:00Z', '--accept-migration',
                 '--owner-decision-id', 'owner-one', '--upgrade-receipt', str(receipt)],
                capture_output=True, text=True, timeout=30)
            self.assertNotEqual(migrated.returncode, 0)
            self.assertIn('requires --job', migrated.stderr)
            self.assertEqual({path.name: path.read_bytes() for path in job_dir.iterdir()},
                             before)
            self.assertEqual((old_package / 'plugin.json').read_text(),
                             json.dumps({'name': 'babysitter', 'version': '1.2.2'}))

    def test_manifest_declares_the_continuous_policy(self):
        meta = json.loads((PLUGIN / 'plugin.json').read_text())
        self.assertEqual(meta['version'], '1.3.0')
        continuous = meta['continuous']
        self.assertEqual(continuous['policy_version'], 'continuous-1')
        self.assertEqual(continuous['default_cadence_seconds'], 600)
        self.assertEqual(continuous['default_queue_threshold_seconds'], 900)
        self.assertEqual(continuous['state_helper'], 'scripts/continuous.py')
        self.assertEqual(continuous['sweep_adapter'], 'scripts/continuous_sweep.py')
        self.assertEqual(continuous['max_repair_attempts'], 3)
        for rel in ('entry.md', 'playbooks/maintain.md', 'references/scope.md'):
            self.assertIn('continuous', (PLUGIN / rel).read_text().lower())


if __name__ == '__main__':
    unittest.main()
