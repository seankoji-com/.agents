"""Deterministic T3 launch/arming with real continuous writer reservations."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_babysitter_org_scan import pr, check, FixtureAPI, HEAD

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/babysitter/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('org_execute', SCRIPTS / 'org_execute.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Host:
    def __init__(self):
        self.calls = []
        self.lose_response = False
        self.identity = 'selected-model'
        self.threads = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == 'orchestrator_capabilities':
            return {'parentThreadId': 'parent', 'providers': [{'providerInstanceId': 'fixture',
                'canRunChildTask': True, 'models': [{'id': 'selected-model', 'options': []}]}]}
        if tool == 't3_thread_list':
            return {'threads': self.threads, 'nextCursor': None}
        if tool == 'delegate_task':
            if self.lose_response:
                raise runner.ExecutionError('lost-response')
            return {'taskId': 'host-task', 'childThreadId': 'child', 'status': 'running',
                    'workState': 'working', 'hasPendingChildRuns': False,
                    'providerInstanceId': 'fixture', 'model': self.identity, 'options': []}
        if tool == 'task_status':
            return {'taskId': arguments['taskId'], 'status': 'running', 'workState': 'working',
                    'hasPendingChildRuns': False}
        return {}


class Jobs:
    def __init__(self, directory):
        self.directory = directory
        self.handles, self.events = {}, []
        self.bad_workspace = False
        self.workspace_calls = 0

    def prepare(self, row):
        return {'request_id': 'fix-request', 'target': {'providerInstanceId': 'fixture',
            'model': 'selected-model', 'options': {}}, 'attempt': 1,
            'retry_usage': {'attempts': [], 'max_attempts': 3, 'max_seconds': 300}, 'prior_findings': [],
            'brief': {'path': str(self.directory / 'brief.json'), 'sha256': 'a' * 64},
            'job_id': 'job', 'task_id': 'maintain', 'package': str(SCRIPTS.parent)}

    def retained(self, row):
        return self.handles.get(row['url'], [])

    def workspace(self, row, prepared):
        self.workspace_calls += 1
        if self.bad_workspace:
            raise runner.ExecutionError('pr-workspace-unavailable')
        return str(self.directory / 'pr-worktree')

    def record(self, prepared, event):
        self.events.append(event)
        if event['kind'] == 'accepted':
            self.handles['https://github.com/fixture/repo/pull/1'] = [event['host_task_id']]


class API:
    def __init__(self):
        self.calls = []
        self.draft = False
        self.move_head = False
        self.merge_on_arm = False
        self.state = 'OPEN'

    def query(self, query, variables, **kwargs):
        self.calls.append((query, variables, kwargs))
        if query.startswith('mutation'):
            return {'enablePullRequestAutoMerge': {'pullRequest': {
                'state': 'MERGED' if self.merge_on_arm else 'OPEN', 'autoMergeRequest': {'enabledAt': 'observed'}}}}
        return {'node': {'id': variables['id'], 'state': self.state, 'isDraft': self.draft,
                        'headRefOid': 'b' * 40 if self.move_head else HEAD,
                        'autoMergeRequest': None,
                        'repository': {'squashMergeAllowed': True, 'mergeCommitAllowed': True}}}

    def report(self):
        return {'requests': len(self.calls)}


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        source = self.directory / 'owner.txt'
        source.write_text('Maintain all non-draft PRs in fixture, arm auto-merge and dispatch selected fixers.')
        self.config = {'org': 'fixture', 'thread_id': 'parent', 'run_id': 'run',
            'authorization_source': str(source),
            'authorization_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'continuous_state': str(self.directory / 'continuous.json')}
        args = runner.continuous.build_parser().parse_args(['start', '--state', self.config['continuous_state'],
            '--now', runner.org_scan.utc_now(), '--scope-kind', 'org', '--scope-value', 'fixture',
            '--thread-id', 'parent', '--authorization-source', str(source)])
        args.func(args)
        self.config['run_id'] = runner.continuous.read_state(self.config['continuous_state'])['run_id']
        self.host, self.jobs, self.api = Host(), Jobs(self.directory), API()

    def report(self, **changes):
        node = pr(contexts=[check('FAILURE')], autoMergeRequest=changes.pop('autoMergeRequest', None), **changes)
        node['commits']['nodes'][0]['commit']['oid'] = node['headRefOid']
        return runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]}), 'fixture')

    def execute(self, report=None):
        return runner.execute(report or self.report(), self.api, self.host, self.jobs, self.config)

    def observe(self, report=None, blocker=None, reviewers=None):
        data = runner.observation(report or self.report(), {})
        if blocker:
            data.pop('preserve_human_blockers')
            data['prs'][0]['human_blocker'] = blocker
        if reviewers is not None:
            data['prs'][0]['changes_requested_by'] = reviewers
        file = self.directory / 'saved-observation.json'
        runner.continuous.save_json(file, data)
        self.config['wake_id'] = str(len(runner.continuous.read_state(
            self.config['continuous_state'])['events']))
        return runner.continuous_command(self.config, 'observe', observation=str(file),
            wake_kind='manual', wake_id=self.config['wake_id'])

    def settle(self, request, status='failed'):
        # Fixture the accepted job evidence, retaining the real ledger transition.
        with patch.object(runner.continuous, 'accepted_fixer_result', return_value='a' * 64):
            runner.continuous_command(self.config, 'receipt', pr=pr()['url'], request_id=request,
                kind='fixer', head=HEAD, status=status, host_task_id=None, result=None, reason='fixture terminal result')

    def assert_exhausted_repairs_held(self, report=None, reviewers=None):
        for index in range(3):
            action = self.observe(report, reviewers=reviewers)['actions'][0]
            self.assertEqual(action['attempt'], index + 1)
            runner.continuous_command(self.config, 'dispatch', pr=pr()['url'],
                request_id=action['request_id'], kind='fixer', head=HEAD, reserve=True,
                host_task_id=None, attempt=action['attempt'], review_triage=False)
            self.settle(action['request_id'])
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        self.assertIn('exhausted', result['outcomes'][0]['reason'])
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_persisted_exhausted_repairs_prevent_arming_and_dispatch(self):
        self.assert_exhausted_repairs_held()

    def test_detailed_to_lightweight_observation_keeps_exhausted_identity(self):
        report = self.report(reviewDecision='CHANGES_REQUESTED')
        self.assert_exhausted_repairs_held(report, reviewers=['fixture-reviewer'])
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['observation']['changes_requested_by'], ['fixture-reviewer'])

    def test_reviewer_detail_can_be_explicitly_cleared_and_is_not_carried_to_new_head(self):
        self.observe(reviewers=['fixture-reviewer'])
        self.observe(reviewers=[])
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['observation']['changes_requested_by'], [])
        self.observe(reviewers=['fixture-reviewer'])
        self.observe(self.report(headRefOid='b' * 40))
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['observation']['changes_requested_by'], [])

    def assert_incomplete_history_held(self, kind):
        contexts = [check('FAILURE', 'ci')]
        threads = []
        if kind == 'checks':
            contexts += [check('SUCCESS', 'pass-' + str(i)) for i in range(99)]
            contexts += [check('FAILURE', 'lint')]
        else:
            threads = [{'id': str(i), 'isResolved': True, 'isOutdated': False} for i in range(100)]
            threads += [{'id': 'unread', 'isResolved': False, 'isOutdated': False}]
        node = pr(contexts=contexts, threads=threads, autoMergeRequest=None)
        source = FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]},
            {(node['id'], 'checks'): contexts, (node['id'], 'threads'): threads})
        full = runner.org_scan.scan(source, 'fixture')
        self.assert_exhausted_repairs_held(full)
        before = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        query = source.query
        def failed_tail(text, variables=None, estimate=1):
            if variables and variables.get('cursor') == '100':
                raise runner.org_scan.ScanError('request-budget')
            return query(text, variables, estimate)
        with patch.object(source, 'query', side_effect=failed_tail):
            partial = runner.org_scan.scan(source, 'fixture')
        self.assertEqual(partial['prs'][0]['unknowns'], [kind + ':request-budget'])
        for wake in ('partial-1', 'partial-2'):
            self.config['wake_id'] = wake
            result = self.execute(partial)
            self.assertEqual(result['outcomes'][0]['status'], 'held', result)
            self.assertIn('incomplete-pr-observation', result['outcomes'][0]['reason'])
            saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
            self.assertEqual(saved['observation'], before['observation'])
            self.assertEqual(saved['dispatches'], before['dispatches'])
            self.assertTrue(saved['discovery_gap'])
        self.config['wake_id'] = 'complete-again'
        result = self.execute(full)
        self.assertIn('exhausted', result['outcomes'][0]['reason'])
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_incomplete_check_tail_cannot_reset_exhausted_history(self):
        self.assert_incomplete_history_held('checks')

    def test_incomplete_thread_tail_cannot_reset_exhausted_history(self):
        self.assert_incomplete_history_held('threads')

    def test_new_pr_with_incomplete_evidence_is_held_without_admission(self):
        report = self.report(mergeable='UNKNOWN')
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        self.assertEqual(runner.continuous.read_state(self.config['continuous_state'])['prs'], {})
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t in {'delegate_task', 'link_pull_request'} for t, _ in self.host.calls))

    def test_incomplete_pr_does_not_starve_another_complete_pr(self):
        nodes = [pr(mergeable='UNKNOWN', contexts=[check('FAILURE')], autoMergeRequest=None),
                 pr(number=2, contexts=[check('FAILURE')], autoMergeRequest=None)]
        report = runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': nodes}), 'fixture')
        result = self.execute(report)
        self.assertEqual([o['status'] for o in result['outcomes']], ['held', 'dispatched'], result)
        saved = runner.continuous.read_state(self.config['continuous_state'])
        self.assertEqual(list(saved['prs']), [nodes[1]['url']])
        self.assertFalse(saved['discovery']['complete'])
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 1)

    def test_job_requests_count_toward_continuous_repair_budget(self):
        prepare = self.jobs.prepare
        self.config['retry_usage'] = {pr()['url']: {'attempts': [{'elapsed_seconds': 1}],
            'max_attempts': 3, 'max_seconds': 300}}
        self.config['prior_findings'] = {pr()['url']: [{'id': 'retained-finding'}]}
        for index in range(3):
            self.config['wake_id'] = 'repair-' + str(index)
            prepared = prepare(self.report()['prs'][0])
            prepared['request_id'] = 'job-request-' + str(index)
            with patch.object(self.jobs, 'prepare', return_value=prepared):
                result = self.execute()
            self.assertEqual(result['outcomes'][0]['status'], 'dispatched', result)
            saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
            dispatch = saved['dispatches'][-1]
            self.assertEqual(dispatch['attempt'], index + 1)
            self.assertTrue(dispatch['reconciliation_request_id'].endswith('-a' + str(index + 1)))
            self.settle(prepared['request_id'])
            # Stand in for coordinator ingestion/disposition and preparation of
            # the next request; owned terminal handles are never self-accepted.
            self.jobs.handles.clear()
        self.config['wake_id'] = 'exhausted'
        self.assertIn('exhausted', self.execute()['outcomes'][0]['reason'])
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 3)

    def test_new_job_cannot_reset_missing_retry_history(self):
        action = self.observe()['actions'][0]
        runner.continuous_command(self.config, 'dispatch', pr=pr()['url'],
            request_id=action['request_id'], kind='fixer', head=HEAD, reserve=True,
            host_task_id=None, attempt=1, review_triage=False)
        self.settle(action['request_id'])
        self.assertEqual(self.execute()['outcomes'][0]['reason'], 'retry-needs-retained-counters-and-findings')
        self.assertEqual(self.api.calls, [])

    def test_hold_added_during_preparation_is_checked_at_reservation(self):
        prepare = self.jobs.prepare
        def revoke(row):
            self.observe(blocker={'kind': 'missing-authorization', 'detail': 'Revoked during preparation.'})
            return prepare(row)
        with patch.object(self.jobs, 'prepare', side_effect=revoke):
            result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_authorization_hold_survives_repeated_lightweight_wakes(self):
        blocker = {'kind': 'missing-authorization', 'detail': 'Owner revoked this PR.'}
        self.observe(blocker=blocker)
        for index in range(2):
            self.config['wake_id'] = 'held-' + str(index)
            result = self.execute()
            self.assertEqual(result['outcomes'][0]['status'], 'held', result)
            saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
            self.assertEqual(saved['observation']['human_blocker'], blocker)
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))
        data = runner.observation(self.report(), {})
        data.pop('preserve_human_blockers')
        data['prs'][0]['human_blocker'] = None  # Explicit coordinator disposition.
        file = self.directory / 'clear-hold.json'
        runner.continuous.save_json(file, data)
        runner.continuous_command(self.config, 'observe', observation=str(file),
            wake_kind='manual', wake_id='authority-cleared')
        self.assertEqual(self.execute()['outcomes'][0]['status'], 'dispatched')

    def test_review_triage_identity_and_wait_review_are_preserved(self):
        node = pr(contexts=[check('SUCCESS')], autoMergeRequest=None, reviewDecision='CHANGES_REQUESTED')
        report = runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]}), 'fixture')
        self.assertEqual(self.execute(report)['outcomes'][0]['status'], 'dispatched')
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertTrue(saved['dispatches'][-1]['review_triage'])
        self.assertIn('-review-', saved['dispatches'][-1]['reconciliation_request_id'])
        self.settle('fix-request', status='succeeded')
        self.jobs.handles.clear()
        self.config['wake_id'] = 'review-still-required'
        self.api.calls.clear()
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        self.assertIn('re-review', result['outcomes'][0]['reason'])
        self.assertEqual(self.api.calls, [])
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 1)

    def test_auto_merge_is_default_and_one_fix_launch_uses_frozen_target(self):
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'dispatched', result)
        self.assertEqual(result['outcomes'][0]['auto_merge'], 'enabled')
        mutation = [c for c in self.api.calls if c[0].startswith('mutation')][0]
        self.assertEqual(mutation[1]['head'], HEAD)
        launch = next(args for tool, args in self.host.calls if tool == 'delegate_task')
        self.assertEqual(launch['target'], {'providerInstanceId': 'fixture', 'model': 'selected-model', 'options': {}})
        self.assertEqual(launch['clientRequestId'], 'fix-request')
        self.assertEqual(launch['isolation'], 'worktree')
        self.assertIn('pr-worktree', launch['task'])
        snapshot, = self.directory.glob('fix-request-*-dispatch.json')
        self.assertEqual(json.loads(snapshot.read_text())['reasons'], ['failing-checks'])
        self.assertIn(hashlib.sha256(snapshot.read_bytes()).hexdigest(), launch['task'])
        state = runner.continuous.read_state(self.config['continuous_state'])
        row = next(iter(state['prs'].values()))
        self.assertEqual(row['fixer']['host_task_id'], 'host-task')
        self.assertFalse(any(w['kind'] == 'auto-merge' and w['status'] in runner.continuous.OPEN_DISPATCH for w in row['dispatches']))
        self.assertTrue((self.directory / 'fix-request-receipt.json').is_file())

    def test_repeated_sweeps_read_owned_handle_and_never_launch_again(self):
        self.execute()
        again = self.execute()
        self.assertEqual(again['outcomes'][0]['status'], 'active-fixer', again)
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertEqual(sum(tool == 'task_status' for tool, _ in self.host.calls), 1)
        self.assertEqual(sum(q.startswith('mutation') for q, _, _ in self.api.calls), 1)

    def test_terminal_handle_needing_ingestion_is_not_execution_complete(self):
        self.execute()
        call = self.host.call
        def terminal(tool, arguments):
            if tool == 'task_status':
                return {'status': 'completed', 'workState': 'result_available', 'hasPendingChildRuns': False}
            return call(tool, arguments)
        with patch.object(self.host, 'call', side_effect=terminal):
            result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'needs-result-reconciliation')
        self.assertFalse(result['complete'])
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 1)

    def test_cli_can_map_job_request_to_reconciled_attempt(self):
        action = self.observe()['actions'][0]
        args = runner.continuous.build_parser().parse_args(['dispatch',
            '--state', self.config['continuous_state'], '--now', runner.org_scan.utc_now(),
            '--pr', pr()['url'], '--request-id', 'cli-job-request', '--kind', 'fixer',
            '--head', HEAD, '--attempt', '1', '--reserve',
            '--reconciliation-request-id', action['request_id']])
        self.assertEqual(args.func(args)['status'], 'recorded')
        self.settle('cli-job-request')
        self.assertEqual(self.observe()['actions'][0]['attempt'], 2)

    def test_lost_launch_response_holds_reservation(self):
        self.host.lose_response = True
        first, second = self.execute(), self.execute()
        self.assertEqual(first['outcomes'][0]['status'], 'held')
        self.assertEqual(second['outcomes'][0]['status'], 'held')
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertEqual(self.jobs.events[-1]['kind'], 'uncertain')
        row = next(iter(runner.continuous.read_state(self.config['continuous_state'])['prs'].values()))
        self.assertTrue(row['fixer']['in_flight'])
        self.assertEqual(self.jobs.workspace_calls, 1, 'an uncertain writer must not have its checkout reset')

    def test_other_thread_ownership_prevents_every_mutation(self):
        self.host.threads = [{'threadId': 'sibling', 'parentThreadId': None, 'title': 'Other work',
                             'pullRequests': [{'url': pr()['url']}]}]
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'owned-elsewhere')
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_title_only_ownership_and_nullable_titles(self):
        row = self.report()['prs'][0]
        for title in (row['url'], 'Fix PR #1', 'Work on ' + row['head_ref']):
            self.host.threads = [{'threadId': 'sibling', 'title': title}]
            self.assertIn(row['url'], runner.ownership(self.host, 'parent', [row]))
        self.host.threads = [{'threadId': 'sibling', 'title': None}]
        self.assertEqual(runner.ownership(self.host, 'parent', [row]), {})

    def test_repository_transferred_out_of_org_is_not_admitted(self):
        node = pr(repo='another-org/repo', contexts=[check('FAILURE')], autoMergeRequest=None)
        report = runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]}), 'fixture')
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'excluded-by-saved-scope')
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t in {'delegate_task', 'link_pull_request'} for t, _ in self.host.calls))

    def test_draft_and_head_changes_stop_arming_and_dispatch(self):
        for flag in ('draft', 'move_head'):
            with self.subTest(flag=flag):
                self.api = API()
                setattr(self.api, flag, True)
                result = self.execute()
                self.assertEqual(result['outcomes'][0]['status'], 'held')
                self.assertEqual(result['outcomes'][0]['reason'], 'pr-no-longer-non-draft'
                    if flag == 'draft' else 'head-changed-before-auto-merge')
                self.assertFalse(any(q.startswith('mutation') for q, _, _ in self.api.calls))
                self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def assert_armed_lifecycle_stops_launch(self, state='OPEN', draft=False):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        workspace = self.jobs.workspace
        def changed(row, prepared):
            path = workspace(row, prepared)
            self.api.state, self.api.draft = state, draft
            return path
        with patch.object(self.jobs, 'workspace', side_effect=changed):
            result = self.execute(report)
        expected = 'excluded-by-current-lifecycle' if draft else state.lower() + '-observed'
        self.assertEqual(result['outcomes'][0]['status'], expected, result)
        self.assertTrue(self.api.calls, 'already-armed PRs need a current lifecycle read')
        self.assertFalse(any(q.startswith('mutation') for q, _, _ in self.api.calls))
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['state'], 'excluded' if draft else state.lower())
        self.assertFalse(saved['fixer']['in_flight'])

    def test_already_armed_draft_after_workspace_is_excluded(self):
        self.assert_armed_lifecycle_stops_launch(draft=True)

    def test_already_armed_closed_after_workspace_is_reconciled(self):
        self.assert_armed_lifecycle_stops_launch(state='CLOSED')

    def test_already_armed_merged_after_workspace_is_reconciled(self):
        self.assert_armed_lifecycle_stops_launch(state='MERGED')

    def test_already_armed_head_change_holds_launch(self):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        self.api.move_head = True
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['reason'], 'head-changed-before-fixer')
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_already_armed_unavailable_lifecycle_holds_launch(self):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        with patch.object(self.api, 'query', side_effect=runner.org_scan.ScanError('request-budget')):
            result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_draft_read_preserves_a_racing_reservation_and_handle_attachment(self):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        self.observe(report)
        runner.continuous_command(self.config, 'dispatch', pr=pr()['url'], request_id='racing-fixer',
            kind='fixer', head=HEAD, reserve=True, host_task_id=None, attempt=1, review_triage=False)
        runner.exclude_current_draft(self.config, report['prs'][0])
        attached = runner.continuous_command(self.config, 'dispatch', pr=pr()['url'], request_id='racing-fixer',
            kind='fixer', head=HEAD, reserve=False, host_task_id='retained-host', attempt=1, review_triage=False)
        self.assertTrue(attached['attached'])
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['state'], 'excluded')
        self.assertTrue(saved['fixer']['in_flight'])
        self.assertEqual(saved['fixer']['host_task_id'], 'retained-host')
        self.assertEqual(saved['next_action']['kind'], 'wait-fixer')
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_head_change_during_reservation_is_read_before_launch_and_rejected(self):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        command = runner.continuous_command
        def changed(config, operation, **values):
            result = command(config, operation, **values)
            if operation == 'dispatch' and values.get('reserve') and values['kind'] == 'fixer':
                self.api.move_head = True
            return result
        with patch.object(runner, 'continuous_command', side_effect=changed):
            result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        self.assertEqual(result['outcomes'][0]['reason'], 'head-changed-before-fixer')
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['dispatches'][-1]['status'], 'rejected')
        self.assertFalse(saved['fixer']['in_flight'])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_authority_revoked_during_final_remote_read_rejects_unlaunched_reservation(self):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        query = self.api.query
        def revoked(text, variables, **kwargs):
            self.observe(report, blocker={'kind': 'missing-authorization', 'detail': 'Owner revoked writes.'})
            return query(text, variables, **kwargs)
        with patch.object(self.api, 'query', side_effect=revoked):
            result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['status'], 'held', result)
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['dispatches'][-1]['status'], 'rejected')
        self.assertEqual(saved['observation']['human_blocker']['kind'], 'missing-authorization')
        self.assertFalse(saved['fixer']['in_flight'])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_scope_revoked_during_final_remote_read_rejects_unlaunched_reservation(self):
        report = self.report(autoMergeRequest={'enabledAt': 'observed'})
        query = self.api.query
        def revoked(text, variables, **kwargs):
            path = runner.continuous.state_path(self.config['continuous_state'])
            with runner.continuous.locked_state(path) as state:
                state['scope']['exclusions'].append(pr()['url'])
                runner.continuous.save_json(path, state)
            return query(text, variables, **kwargs)
        with patch.object(self.api, 'query', side_effect=revoked):
            result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['reason'], 'pr-outside-saved-scope')
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertEqual(saved['dispatches'][-1]['status'], 'rejected')
        self.assertFalse(saved['fixer']['in_flight'])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_workspace_failure_keeps_unlaunched_request_retryable(self):
        self.jobs.bad_workspace = True
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'held')
        row = next(iter(runner.continuous.read_state(self.config['continuous_state'])['prs'].values()))
        self.assertFalse(row['fixer']['in_flight'])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))
        self.jobs.bad_workspace = False
        self.assertEqual(self.execute()['outcomes'][0]['status'], 'dispatched')

    def test_identity_mismatch_retains_actual_owned_handle(self):
        self.host.identity = 'different-model'
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['reason'], 'host-identity-mismatch')
        self.assertEqual(result['outcomes'][0]['task_id'], 'host-task')
        self.assertEqual(self.execute()['outcomes'][0]['status'], 'active-fixer')
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 1)

    def test_missing_machine_transport_does_not_run_provider_cli(self):
        with patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(runner.ExecutionError, 'transport-unavailable'):
                runner.T3Host()
            run.assert_not_called()

    def test_auto_merge_reservation_blocks_competing_writes(self):
        report = self.report()
        file = self.directory / 'snapshot.json'
        runner.continuous.save_json(file, runner.observation(report, {}))
        runner.continuous_command(self.config, 'observe', observation=str(file), wake_kind='manual', wake_id=None)
        row = report['prs'][0]
        runner.continuous_command(self.config, 'dispatch', pr=row['url'], request_id='arm', kind='auto-merge',
            head=HEAD, reserve=True, host_task_id=None, attempt=1, review_triage=False)
        with self.assertRaisesRegex(runner.continuous.ContinuousError, 'auto-merge write is pending'):
            runner.continuous_command(self.config, 'dispatch', pr=row['url'], request_id='fix', kind='fixer',
                head=HEAD, reserve=True, host_task_id=None, attempt=1, review_triage=False)
        runner.continuous_command(self.config, 'receipt', pr=row['url'], request_id='arm', kind='auto-merge',
            head=HEAD, status='uncertain', host_task_id=None, result=None, reason='Fixture lost response.')
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][row['url']]
        self.assertEqual(saved['next_action']['kind'], 'auto-merge-pending')
        self.assertEqual(self.execute()['outcomes'][0]['status'], 'held')
        self.assertEqual(self.api.calls, [])
        runner.continuous_command(self.config, 'receipt', pr=row['url'], request_id='arm', kind='auto-merge',
            head=HEAD, status='rejected', host_task_id=None, result=None, reason='Fixture confirms no submission.')
        saved = runner.continuous.read_state(self.config['continuous_state'])['prs'][row['url']]
        self.assertEqual(saved['next_action']['kind'], 'dispatch-fixer')

    def test_arming_with_unresolved_threads_still_launches_the_fixer(self):
        node = pr(contexts=[check('QUEUED')], autoMergeRequest=None,
            threads=[{'id': 'thread', 'isResolved': False, 'isOutdated': True}])
        report = runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]}), 'fixture')
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['auto_merge'], 'enabled')
        self.assertEqual(result['outcomes'][0]['status'], 'dispatched')

    def test_auto_merge_only_does_not_launch_a_repair(self):
        node = pr(contexts=[check('QUEUED')], autoMergeRequest=None)
        report = runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]}), 'fixture')
        result = self.execute(report)
        self.assertEqual(result['outcomes'][0]['auto_merge'], 'enabled')
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_late_scheduled_wake_cannot_execute_event_only_run(self):
        self.config['wake_kind'] = 'schedule'
        with self.assertRaisesRegex(runner.ExecutionError, 'scheduled-continuation-revoked'):
            self.execute()
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

    def test_merge_observed_while_arming_never_launches_a_fixer(self):
        self.api.merge_on_arm = True
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'merged-observed', result)
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))


class InstalledJobsTest(unittest.TestCase):
    def test_factory_creates_and_prepares_new_pr_through_installed_job_gates(self):
        from test_rebuild_installed import Sandbox
        from babysitter_continuous_fixtures import plan
        from model_selection_fixtures import attach_selection
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            box = Sandbox(root)
            package, manifest = box.install('babysitter')
            template = plan(manifest, 'template')
            template['workflow'] = 'babysitter/org'
            template['authorization']['actions'] = ['read', 'push', 'communicate', 'merge']
            template['stages'][0]['validator_contract'] = {
                'pr': pr()['url'], 'head_sha': HEAD, 'required_contexts': [], 'optional_contexts': [],
                'allow_empty_required_contexts': False,
                'authorized_endstate': {'requested': 'merged', 'observed': 'open', 'authorization_ref': 'owner-invocation'}}
            attach_selection(template)
            config = {'run_id': 'fixture-run', 'package': str(package), 'jobs_root': str(box.jobs),
                'prefix': str(box.prefix), 'agents_root': str(box.agents), 'job_template': template,
                'caller': box.caller(manifest, 'babysitter/org')}
            jobs = runner.Jobs(config, root / 'executor')
            report = runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}],
                {'r': [pr(contexts=[check('FAILURE')])]}), 'fixture')
            with patch.dict(os.environ, box.env, clear=True):
                prepared = jobs.prepare(report['prs'][0])
                again = jobs.prepare(report['prs'][0])
            self.assertEqual(prepared['request_id'], again['request_id'])
            self.assertEqual(prepared['brief']['sha256'], again['brief']['sha256'])
            stored = json.loads((box.jobs / prepared['job_id'] / 'job.json').read_text())
            self.assertEqual(set(stored['authorization']['prs']), {pr()['url']})
            brief = json.loads(Path(prepared['brief']['path']).read_text())
            self.assertIn('org_triage', brief['resources'])
            self.assertEqual(brief['target']['model'], prepared['target']['model'])
            self.assertEqual(brief['target']['providerInstanceId'], prepared['target']['providerInstanceId'])


@unittest.skipUnless(shutil.which('node'), 'Node required only to fixture the code-mode JS adapter')
class CodeModeBridgeTest(unittest.TestCase):
    def bridge(self, mode='normal'):
        source = r'''
const fs = require('fs');
const invoke = new Function('tools', 'options', fs.readFileSync(process.argv[1], 'utf8'));
const mode = process.argv[2], calls = [];
let clock = 0;
Date.now = () => clock;
const tools = {
  async exec_command(args) {
    calls.push({kind:'exec', ...args});
    if (args.cmd.startsWith('kill ')) return {output:'',exit_code:0};
    return {session_id:17,output:'T3_READY {"pid":123}\nT3_CALL '+JSON.stringify({
      tool:mode==='forbidden'?'t3_thread_launch':'orchestrator_capabilities',arguments:{}})+'\n'};
  },
  async mcp__t3_code__orchestrator_capabilities(args) {
    calls.push({kind:'tool',arguments:args});
    if (mode === 'late') clock = 100;
    return {structuredContent:{parentThreadId:'fixture-parent'}};
  },
  async write_stdin(args) {
    calls.push({kind:'stdin',...args});
    if (JSON.parse(args.chars).structuredContent.parentThreadId !== 'fixture-parent') throw new Error('response changed');
    return {exit_code:0,output:'T3_RESULT {"complete":true}\n'};
  }
};
(async()=>{
  try {
    const result=await invoke(tools,{argv:['python3','/fixture/space path/runner.py',"a'$(not-a-command)"],workdir:'/fixture',deadlineMs:50});
    process.stdout.write(JSON.stringify({result,calls}));
  } catch(error) {process.stdout.write(JSON.stringify({error:error.message,calls}));}
})();
'''
        result = subprocess.run(['node', '-e', source, str(SCRIPTS / 'org_bridge.js'), mode],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fixed_native_tool_bridge_preserves_result_and_quotes_argv(self):
        out = self.bridge()
        self.assertEqual(out['result'], {'exit_code': 0, 'tool_requests': 1, 'result': {'complete': True}})
        self.assertEqual(out['calls'][0]['cmd'], "'python3' '/fixture/space path/runner.py' 'a'\\''$(not-a-command)'")
        self.assertEqual(sum(c['kind'] == 'tool' for c in out['calls']), 1)

    def test_unapproved_tool_is_rejected_and_only_owned_helper_is_stopped(self):
        out = self.bridge('forbidden')
        self.assertIn('allowlist', out['error'])
        self.assertFalse(any(c['kind'] == 'tool' for c in out['calls']))
        self.assertEqual(out['calls'][-1]['cmd'], 'kill 123')

    def test_returned_host_receipt_is_delivered_after_deadline(self):
        out = self.bridge('late')
        self.assertEqual(out['result']['exit_code'], 0, out)
        self.assertTrue(any(c['kind'] == 'stdin' for c in out['calls']))
        self.assertFalse(any(c.get('cmd', '').startswith('kill ') for c in out['calls']))


if __name__ == '__main__':
    unittest.main()
