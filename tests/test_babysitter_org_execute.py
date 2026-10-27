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
            prepared['retry_usage']['attempts'] = [{'request_id': 'prior-' + str(n)} for n in range(index)]
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

    def test_identity_mismatch_is_evidence_but_never_an_owned_handle(self):
        self.host.identity = 'different-model'
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['reason'], 'host-identity-mismatch')
        self.assertNotIn('task_id', result['outcomes'][0])
        receipts = list(self.jobs.directory.glob('*-receipt.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())['receipt']['taskId'], 'host-task')
        self.assertEqual(self.jobs.handles, {})
        self.assertFalse(any(event.get('kind') == 'accepted' for event in self.jobs.events))
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 1)

    def test_missing_machine_transport_does_not_run_provider_cli(self):
        with patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(runner.ExecutionError, 'transport-unavailable'):
                runner.T3Host()
            run.assert_not_called()

    def test_malformed_receipt_options_keep_specific_diagnostic_and_returned_handle(self):
        for options in ([None], [{}], [{'id': 'effort'}], 'invalid', None):
            with self.subTest(options=options):
                # Each launch needs an independent reservation and fixture state.
                self.setUp()
                original = self.host.call
                def malformed(tool, arguments):
                    receipt = original(tool, arguments)
                    if tool == 'delegate_task':
                        receipt['options'] = options
                    return receipt
                with patch.object(self.host, 'call', side_effect=malformed):
                    result = self.execute()
                self.assertEqual(result['outcomes'][0]['reason'], 'host-options-unreported-or-mismatched')
                self.assertFalse(any(event.get('kind') == 'accepted' for event in self.jobs.events))
                receipt_path = next(self.jobs.directory.glob('*-receipt.json'))
                self.assertEqual(json.loads(receipt_path.read_text())['receipt']['taskId'], 'host-task')

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


from test_rebuild_installed import Sandbox, worker_result
from babysitter_continuous_fixtures import plan
from model_selection_fixtures import attach_selection


class AdvanceHost(Host):
    def __init__(self):
        super().__init__()
        self.statuses = {}

    def call(self, tool, arguments):
        if tool == 'orchestrator_capabilities':
            return {'parentThreadId': 'parent', 'providers': [{'providerInstanceId': 'fixture-provider',
                'canRunChildTask': True, 'models': [{'id': 'fixture-worker', 'options': []}]}]}
        if tool == 'delegate_task':
            self.calls.append((tool, arguments))
            host_id = 'host-' + str(len(self.statuses))
            receipt = {'taskId': host_id, 'childThreadId': 'child-' + host_id,
                'childRunId': 'run-' + host_id, 'status': 'running', 'workState': 'working',
                'hasPendingChildRuns': False, 'providerInstanceId': 'fixture-provider',
                'model': 'fixture-worker', 'options': [], 'summary': None}
            self.statuses[host_id] = receipt
            if self.lose_response:
                raise runner.ExecutionError('lost-response')
            return dict(receipt)
        if tool == 'task_status':
            self.calls.append((tool, arguments))
            return dict(self.statuses[arguments['taskId']])
        return super().call(tool, arguments)


class AdvanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.box = Sandbox(self.root / 'installation')
        # A relocated source copy is removed after installation. Every subprocess
        # below uses packaged contracts, never the repository's shared/core imports.
        source = self.box.source_copy('babysitter')
        self.package, manifest = self.box.install('babysitter', source=source)
        shutil.rmtree(source)
        template = plan(manifest, 'template')
        template['workflow'] = 'babysitter/org'
        template['authorization']['actions'] = ['read', 'push', 'communicate', 'merge']
        template['stages'][0]['validator_contract'] = {
            'pr': pr()['url'], 'head_sha': HEAD, 'required_contexts': ['ci'], 'optional_contexts': [],
            'allow_empty_required_contexts': False,
            'authorized_endstate': {'requested': 'merged', 'observed': 'open', 'authorization_ref': 'owner'}}
        attach_selection(template)
        owner = self.root / 'owner.txt'
        owner.write_text('Maintain fixture PRs through merge.')
        self.config = {'org': 'fixture', 'thread_id': 'parent', 'continuous_state': str(self.root / 'continuous.json'),
            'authorization_source': str(owner), 'authorization_sha256': hashlib.sha256(owner.read_bytes()).hexdigest(),
            'package': str(self.package), 'jobs_root': str(self.box.jobs), 'prefix': str(self.box.prefix),
            'agents_root': str(self.box.agents), 'job_template': template,
            'caller': self.box.caller(manifest, 'babysitter/org')}
        args = runner.continuous.build_parser().parse_args(['start', '--state', self.config['continuous_state'],
            '--now', runner.org_scan.utc_now(), '--scope-kind', 'org', '--scope-value', 'fixture',
            '--thread-id', 'parent', '--authorization-source', str(owner)])
        args.func(args)
        self.config['run_id'] = runner.continuous.read_state(self.config['continuous_state'])['run_id']
        self.host, self.api = AdvanceHost(), API()
        self.jobs = runner.Jobs(self.config, self.root / 'executor')
        # Workspace transport and the guarded shell have separate real-Git/curl
        # fixture suites. This fixture exercises their coordinator boundary.
        self.workspace = patch.object(self.jobs, 'workspace', return_value=str(self.root / 'prepared-pr'))
        self.workspace.start()
        self.addCleanup(self.workspace.stop)
        self.guard = patch.object(self.jobs, 'guard', return_value={'path': str(self.root / 'prepared-pr')})
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.env = patch.dict(os.environ, self.box.env, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.wake = 0

    def report(self, *nodes):
        return runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': list(nodes)}), 'fixture')

    def node(self, number=1, state='FAILURE', **changes):
        node = pr(number=number, contexts=[check(state)], autoMergeRequest={'enabledAt': 'observed'}, **changes)
        node['commits']['nodes'][0]['commit']['oid'] = node['headRefOid']
        return node

    def advance(self, *nodes):
        self.wake += 1
        self.config['wake_id'] = 'wake-' + str(self.wake)
        return runner.execute(self.report(*nodes), self.api, self.host, self.jobs, self.config)

    def stored(self, number=1):
        row = self.report(self.node(number))['prs'][0]
        return self.jobs.context(row)['job']

    def finish(self, number=1, status='ready-for-acceptance', findings=None, summary=None, pending=False):
        task = self.stored(number)['tasks'][0]
        brief = json.loads(Path(task['brief']['path']).read_text())
        result = json.loads(worker_result(brief, status=status))
        result['findings'] = findings or []
        host_id = task['handles'][-1]['task_id']
        self.host.statuses[host_id].update(status='completed', workState='result_available',
            hasPendingChildRuns=pending, summary=json.dumps(result) if summary is None else summary)
        return host_id

    def test_concurrent_completion_retry_and_duplicate_result_converge(self):
        first = self.advance(self.node(1), self.node(2))
        self.assertEqual([o['status'] for o in first['outcomes']], ['dispatched', 'dispatched'])
        host = self.finish(1, status='failed')
        second = self.advance(self.node(1), self.node(2))
        by_url = {o['url']: o for o in second['outcomes']}
        self.assertEqual(by_url[pr()['url']]['status'], 'dispatched', second)
        self.assertEqual(by_url[pr(number=2)['url']]['status'], 'active-fixer')
        job = self.stored()
        task = job['tasks'][0]
        self.assertEqual(len(task['execution_history']), 1)
        self.assertEqual(job['stages'][0]['attempts']['primary'], 1)
        self.assertNotEqual(task['request_id'], task['execution_history'][0]['request_id'])
        self.advance(self.node(1), self.node(2))
        self.assertEqual(len(self.stored()['tasks'][0]['execution_history']), 1)
        calls = [a['taskId'] for t, a in self.host.calls if t == 'task_status']
        self.assertIn(host, calls)
        self.assertFalse(any(c.startswith('org-') for c in calls))
        self.assertEqual(len([1 for t, _ in self.host.calls if t == 'delegate_task']), 3)

    def test_incomplete_scan_fans_out_around_one_workspace_failure_and_reconciles_handles(self):
        nodes = [self.node(number) for number in (1, 2, 3, 4)]
        report = self.report(*nodes)
        report['complete'] = False
        report['gaps'].append({'kind': 'fixture-incomplete-page'})
        original_workspace = self.jobs.workspace

        def workspace(row, prepared):
            if row['number'] == 1:
                raise runner.ExecutionError('pr-workspace-unavailable')
            return original_workspace(row, prepared)

        with patch.object(self.jobs, 'workspace', side_effect=workspace):
            first = runner.execute(report, self.api, self.host, self.jobs, self.config)
        self.assertFalse(first['complete'])
        by_url = {outcome['url']: outcome for outcome in first['outcomes']}
        self.assertEqual(by_url[pr()['url']]['status'], 'held')
        launched = [by_url[pr(number=n)['url']] for n in (2, 3, 4)]
        self.assertTrue(all(outcome['status'] == 'dispatched' for outcome in launched), first)
        task_ids = [outcome['task_id'] for outcome in launched]
        self.assertEqual(len(task_ids), len(set(task_ids)))
        self.assertEqual(len([1 for tool, _ in self.host.calls if tool == 'delegate_task']), 3)
        state = runner.continuous.read_state(self.config['continuous_state'])
        for number in (2, 3, 4):
            ledger = state['prs'][pr(number=number)['url']]
            self.assertEqual([dispatch['kind'] for dispatch in ledger['dispatches']], ['fixer'])
            self.assertTrue(ledger['fixer']['in_flight'])
            self.assertIn(ledger['fixer']['host_task_id'], task_ids)

        second_report = self.report(*nodes)
        with patch.object(self.jobs, 'workspace', side_effect=workspace):
            second = runner.execute(second_report, self.api, self.host, self.jobs, self.config)
        second_by_url = {outcome['url']: outcome for outcome in second['outcomes']}
        self.assertTrue(all(second_by_url[pr(number=n)['url']]['status'] == 'active-fixer'
                            for n in (2, 3, 4)), second)
        self.assertEqual(len([1 for tool, _ in self.host.calls if tool == 'delegate_task']), 3)
        reconciled = [arguments['taskId'] for tool, arguments in self.host.calls if tool == 'task_status']
        self.assertCountEqual(reconciled, task_ids)

    def test_incomplete_scan_fans_out_around_one_job_prepare_failure_and_reconciles_handles(self):
        nodes = [self.node(number) for number in (1, 2, 3, 4)]
        report = self.report(*nodes)
        report['complete'] = False
        report['gaps'].append({'kind': 'fixture-incomplete-page'})
        original_prepare = self.jobs.prepare

        def prepare(row):
            if row['number'] == 1:
                raise runner.ExecutionError('job-prepare-unavailable')
            return original_prepare(row)

        with patch.object(self.jobs, 'prepare', side_effect=prepare):
            first = runner.execute(report, self.api, self.host, self.jobs, self.config)
        by_url = {outcome['url']: outcome for outcome in first['outcomes']}
        self.assertEqual(by_url[pr()['url']]['status'], 'held')
        launched = [by_url[pr(number=n)['url']] for n in (2, 3, 4)]
        self.assertTrue(all(outcome['status'] == 'dispatched' for outcome in launched), first)
        task_ids = [outcome['task_id'] for outcome in launched]
        self.assertEqual(len(task_ids), 3)
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 3)
        state = runner.continuous.read_state(self.config['continuous_state'])
        for number in (2, 3, 4):
            ledger = state['prs'][pr(number=number)['url']]
            self.assertTrue(ledger['fixer']['in_flight'])
            self.assertIn(ledger['fixer']['host_task_id'], task_ids)

        with patch.object(self.jobs, 'prepare', side_effect=prepare):
            second = runner.execute(self.report(*nodes), self.api, self.host, self.jobs, self.config)
        second_by_url = {outcome['url']: outcome for outcome in second['outcomes']}
        self.assertTrue(all(second_by_url[pr(number=n)['url']]['status'] == 'active-fixer'
                            for n in (2, 3, 4)), second)
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 3)
        reconciled = [arguments['taskId'] for tool, arguments in self.host.calls if tool == 'task_status']
        self.assertCountEqual(reconciled, task_ids)

    def test_returned_receipt_recovers_when_job_record_failed(self):
        original_record = self.jobs.record
        fail_once = True

        def record(prepared, event):
            nonlocal fail_once
            if event.get('kind') == 'accepted' and fail_once:
                fail_once = False
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=record):
            first = self.advance(self.node())
        self.assertEqual(first['outcomes'][0]['status'], 'held')
        receipt_path = next(self.jobs.directory.glob('*-receipt.json'))
        host_id = next(iter(self.host.statuses))
        self.assertEqual(self.jobs.context(self.report(self.node())['prs'][0])['job']['tasks'][0].get('handles', []), [])

        with patch.object(self.jobs, 'record', side_effect=record):
            recovered = self.advance(self.node())
        self.assertEqual(recovered['outcomes'][0]['status'], 'active-fixer', recovered)
        self.assertTrue(any(tool == 'task_status' and args['taskId'] == host_id for tool, args in self.host.calls))
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertTrue(receipt_path.exists())

    def test_second_cycle_receipt_recovers_against_its_exact_reservation(self):
        initial = self.advance(self.node())
        self.assertEqual(initial['outcomes'][0]['status'], 'dispatched', initial)
        self.finish(status='failed')
        moved_head = 'b' * 40
        self.api.move_head = True
        original_record = self.jobs.record
        fail_once = True

        def record(prepared, event):
            nonlocal fail_once
            if event.get('kind') == 'accepted' and fail_once:
                fail_once = False
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=record):
            first = self.advance(self.node(headRefOid=moved_head))
        self.assertEqual(first['outcomes'][0]['status'], 'held')
        job = self.stored()['tasks'][0]
        brief = json.loads(Path(job['brief']['path']).read_text())
        ledger = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        dispatch = ledger['dispatches'][-1]
        self.assertEqual(job['attempt'], brief['attempt'])
        self.assertEqual(brief['attempt'], 1)
        self.assertEqual(dispatch['attempt'], 1)
        self.assertNotEqual(dispatch['attempt'], brief['attempt'] + 1)
        self.assertNotEqual(dispatch['head'], self.config['job_template']['stages'][0]['validator_contract']['head_sha'])
        self.assertEqual(dispatch['request_id'], job['request_id'])
        host_id = self.host.statuses.keys() - {job['handles'][0]['task_id']}
        self.assertEqual(len(host_id), 1)
        host_id = next(iter(host_id))

        with patch.object(self.jobs, 'record', side_effect=record):
            recovered = self.advance(self.node(headRefOid=moved_head))
        self.assertEqual(recovered['outcomes'][0]['status'], 'active-fixer', recovered)
        self.assertTrue(any(tool == 'task_status' and args['taskId'] == host_id for tool, args in self.host.calls))
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 2)

    def test_unbound_returned_receipt_holds_without_adopting_handle(self):
        original_record = self.jobs.record

        def fail_record(prepared, event):
            if event.get('kind') == 'accepted':
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=fail_record):
            self.assertEqual(self.advance(self.node())['outcomes'][0]['status'], 'held')
        receipt_path = next(self.jobs.directory.glob('*-receipt.json'))
        envelope = json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps(envelope['receipt']))
        with patch.object(self.jobs, 'record', side_effect=fail_record):
            held = self.advance(self.node())
        self.assertEqual(held['outcomes'][0]['status'], 'held')
        self.assertIn('host-receipt-envelope', held['outcomes'][0]['reason'])
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertFalse(any(tool == 'task_status' for tool, _ in self.host.calls))

    def test_foreign_bound_request_receipt_holds_without_adopting_handle(self):
        original_record = self.jobs.record

        def fail_record(prepared, event):
            if event.get('kind') == 'accepted':
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=fail_record):
            self.assertEqual(self.advance(self.node())['outcomes'][0]['status'], 'held')
        receipt_path = next(self.jobs.directory.glob('*-receipt.json'))
        envelope = json.loads(receipt_path.read_text())
        request_id = envelope['request_id']
        envelope['request_id'] = 'another-bound-request'
        receipt_path.write_text(json.dumps(envelope))
        with patch.object(self.jobs, 'record', side_effect=fail_record):
            held = self.advance(self.node())
        self.assertEqual(held['outcomes'][0]['status'], 'held')
        self.assertIn('host-receipt-envelope-binding', held['outcomes'][0]['reason'])
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertFalse(any(tool == 'task_status' for tool, _ in self.host.calls))
        envelope['request_id'] = request_id
        envelope['pr_url'] = 'https://github.com/another/repo/pull/1'
        receipt_path.write_text(json.dumps(envelope))
        with patch.object(self.jobs, 'record', side_effect=fail_record):
            foreign_pr = self.advance(self.node())
        self.assertEqual(foreign_pr['outcomes'][0]['status'], 'held')
        self.assertIn('host-receipt-envelope-binding', foreign_pr['outcomes'][0]['reason'])
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertFalse(any(tool == 'task_status' for tool, _ in self.host.calls))

    def test_returned_receipt_recovers_when_continuous_attach_failed(self):
        original = runner.continuous_command
        fail_once = True

        def command(config, cmd, **values):
            nonlocal fail_once
            if cmd == 'dispatch' and values.get('host_task_id') and fail_once:
                fail_once = False
                raise runner.ExecutionError('fixture-attach-failure')
            return original(config, cmd, **values)

        with patch.object(runner, 'continuous_command', side_effect=command):
            first = self.advance(self.node())
        self.assertEqual(first['outcomes'][0]['status'], 'held')
        host_id = next(iter(self.host.statuses))
        with patch.object(runner, 'continuous_command', side_effect=command):
            recovered = self.advance(self.node())
        self.assertEqual(recovered['outcomes'][0]['status'], 'active-fixer', recovered)
        self.assertTrue(any(tool == 'task_status' and args['taskId'] == host_id for tool, args in self.host.calls))
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)

    def test_tampered_receipt_bindings_hold_before_status_or_relaunch(self):
        original_record = self.jobs.record

        def fail_record(prepared, event):
            if event.get('kind') == 'accepted':
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=fail_record):
            self.assertEqual(self.advance(self.node())['outcomes'][0]['status'], 'held')
        receipt_path = next(self.jobs.directory.glob('*-receipt.json'))
        original = json.loads(receipt_path.read_text())
        for field, reason in (
                ('reservation', 'host-receipt-reservation-mismatch'),
                ('target', 'host-receipt-target-mismatch'),
                ('brief_sha256', 'host-receipt-brief-binding')):
            with self.subTest(field=field):
                envelope = json.loads(json.dumps(original))
                if field == 'reservation':
                    envelope[field]['attempt'] += 1
                elif field == 'target':
                    envelope[field]['model'] = 'another-model'
                else:
                    envelope[field] = '0' * 64
                receipt_path.write_text(json.dumps(envelope))
                held = self.advance(self.node())
                self.assertEqual(held['outcomes'][0]['status'], 'held', held)
                self.assertIn(reason, held['outcomes'][0]['reason'])
                self.assertFalse(any(tool == 'task_status' for tool, _ in self.host.calls))
                self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)

    def test_returned_receipt_recovers_after_the_live_fixer_moves_the_head(self):
        original_record = self.jobs.record

        def fail_record(prepared, event):
            if event.get('kind') == 'accepted':
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=fail_record):
            self.assertEqual(self.advance(self.node())['outcomes'][0]['status'], 'held')
        host_id = next(iter(self.host.statuses))
        recovered = self.advance(self.node(headRefOid='b' * 40))
        self.assertEqual(recovered['outcomes'][0]['status'], 'active-fixer', recovered)
        self.assertTrue(any(tool == 'task_status' and args['taskId'] == host_id
                            for tool, args in self.host.calls))
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)

    def test_mismatched_durable_receipt_holds_without_adopting_foreign_handle(self):
        original_record = self.jobs.record

        def fail_record(prepared, event):
            if event.get('kind') == 'accepted':
                raise runner.ExecutionError('fixture-record-failure')
            return original_record(prepared, event)

        with patch.object(self.jobs, 'record', side_effect=fail_record):
            self.assertEqual(self.advance(self.node())['outcomes'][0]['status'], 'held')
        receipt_path = next(self.jobs.directory.glob('*-receipt.json'))
        envelope = json.loads(receipt_path.read_text())
        envelope['receipt']['taskId'] = ''
        receipt_path.write_text(json.dumps(envelope))
        with patch.object(self.jobs, 'record', side_effect=fail_record):
            malformed = self.advance(self.node())
        self.assertEqual(malformed['outcomes'][0]['status'], 'held')
        self.assertIn('host-receipt-shape', malformed['outcomes'][0]['reason'])
        envelope['receipt']['taskId'] = next(iter(self.host.statuses))
        envelope['receipt']['providerInstanceId'] = 'foreign-provider'
        receipt_path.write_text(json.dumps(envelope))
        with patch.object(self.jobs, 'record', side_effect=fail_record):
            held = self.advance(self.node())
        self.assertEqual(held['outcomes'][0]['status'], 'held')
        self.assertIn('host-receipt-identity-mismatch', held['outcomes'][0]['reason'])
        self.assertEqual(sum(tool == 'delegate_task' for tool, _ in self.host.calls), 1)
        self.assertFalse(any(tool == 'task_status' for tool, _ in self.host.calls))
        ledger = runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]
        self.assertTrue(ledger['fixer']['in_flight'])

    def test_terminal_pending_runs_and_missing_result_keep_writer(self):
        self.advance(self.node())
        host_id = self.finish(pending=True)
        self.assertEqual(self.advance(self.node())['outcomes'][0]['status'], 'active-fixer')
        self.host.statuses[host_id].update(hasPendingChildRuns=False, summary=None)
        held = self.advance(self.node())
        self.assertIn('missing-terminal-result', held['outcomes'][0]['reason'])
        self.assertEqual(len([1 for t, _ in self.host.calls if t == 'delegate_task']), 1)
        self.assertTrue(runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]['fixer']['in_flight'])

    def test_malformed_result_ingests_failure_and_refills_within_budget(self):
        self.advance(self.node())
        self.finish(summary='not JSON')
        second = self.advance(self.node())
        self.assertEqual(second['outcomes'][0]['status'], 'dispatched', second)
        self.assertTrue(self.stored()['tasks'][0]['execution_history'][0]['malformed'])

    def test_settled_receipt_is_not_replayed_but_later_pending_runs_still_exclude_writes(self):
        self.advance(self.node())
        host_id = self.finish()
        pending = self.node(state='IN_PROGRESS')
        self.advance(pending)
        with patch.object(runner, 'continuous_command', wraps=runner.continuous_command) as command:
            self.assertEqual(self.advance(pending)['outcomes'][0]['status'], 'waiting')
        self.assertNotIn('receipt', [call.args[1] for call in command.call_args_list])
        self.host.statuses[host_id]['hasPendingChildRuns'] = True
        self.assertEqual(self.advance(self.node(state='SUCCESS'))['outcomes'][0]['status'], 'active-fixer')
        self.assertIn(('task_status', {'taskId': host_id}), self.host.calls)

    def test_forbidden_followup_reconciles_status_without_a_dispatch_receipt(self):
        handle = {'task_id': 'forbidden-host', 'request_id': 'forbidden-request', 'forbidden_followup': True}
        ctx = {'job': {'tasks': [{'followups': [handle]}]}}
        self.host.statuses['forbidden-host'] = {'taskId': 'forbidden-host', 'status': 'completed',
            'workState': 'result_available', 'hasPendingChildRuns': False, 'summary': 'Untrusted forbidden result.'}
        row = self.report(self.node())['prs'][0]
        with patch.object(self.jobs, 'context', return_value=ctx), patch.object(self.jobs, 'record') as record, \
                patch.object(self.jobs, 'call') as call, patch.object(runner, 'continuous_command') as command:
            result = self.jobs.reconcile(row, self.host)
            self.assertEqual(result, {'active': False, 'ingested': []})
            self.assertEqual(record.call_args.args[1]['kind'], 'reconciled')
            self.host.statuses['forbidden-host']['hasPendingChildRuns'] = True
            self.assertTrue(self.jobs.reconcile(row, self.host)['active'])
        call.assert_not_called()
        command.assert_not_called()

    def test_head_drift_retires_unlaunched_request_without_losing_work_or_budget(self):
        self.api.move_head = True
        rejected = self.advance(self.node())
        self.assertEqual(rejected['outcomes'][0]['reason'], 'head-changed-before-fixer')
        before = self.stored()['tasks'][0]['request_id']
        refreshed = self.advance(self.node(headRefOid='b' * 40))
        self.assertEqual(refreshed['outcomes'][0]['status'], 'dispatched', refreshed)
        job = self.stored()
        self.assertNotEqual(job['tasks'][0]['request_id'], before)
        self.assertEqual(job['stages'][0]['attempts']['primary'], 1)
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 1)

    def test_uncertain_request_cannot_be_retired_as_not_submitted(self):
        self.host.lose_response = True
        self.advance(self.node())
        ctx = self.jobs.context(self.report(self.node())['prs'][0])
        task = ctx['job']['tasks'][0]
        proof = self.root / 'not-submitted.json'
        proof.write_text(json.dumps({'request_id': task['request_id'], 'submitted': False, 'reason': 'untrusted absence'}))
        with self.assertRaisesRegex(runner.ExecutionError, 'job-gate:task-observation'):
            self.jobs.record(ctx, {'kind': 'not-submitted', 'request_id': task['request_id'],
                'reference': {'path': str(proof), 'sha256': hashlib.sha256(proof.read_bytes()).hexdigest(), 'bytes': proof.stat().st_size}})
        self.assertEqual(self.stored()['tasks'][0]['uncertain_calls'], 1)

    def test_external_dependency_and_policy_changes_leave_other_pr_runnable(self):
        self.config['external_blockers'] = {pr()['url']: [{'name': 'runner unavailable',
            'dependency': 'shared-linux-runner', 'detail': 'Fixture runner is offline.',
            'next_check_at': '2026-10-27T00:00:00Z', 'reopen_when': 'Runner accepts the queued canary.'}]}
        held = self.advance(self.node(), self.node(2))
        by_url = {o['url']: o for o in held['outcomes']}
        self.assertIn('runner unavailable', by_url[pr()['url']]['reason'])
        self.assertEqual(by_url[pr(number=2)['url']]['status'], 'dispatched')
        saved = runner.continuous.read_state(self.config['continuous_state'])
        self.assertEqual(saved['prs'][pr()['url']]['blocked']['dependencies'][0]['dependency'], 'shared-linux-runner')
        self.config['external_blockers'] = {}
        reopened = self.advance(self.node(), self.node(2))
        self.assertEqual(next(o for o in reopened['outcomes'] if o['url'] == pr()['url'])['status'], 'dispatched')

    def test_omitted_known_draft_exclusion_can_be_removed(self):
        self.advance(self.node())
        self.finish(status='failed')
        terminal = self.node()
        terminal['isDraft'] = True
        query = self.api.query
        def targeted(text, variables, **kwargs):
            if 'pullRequest(number:$number)' in text:
                return {'repository': {'pullRequest': terminal}}
            return query(text, variables, **kwargs)
        with patch.object(self.api, 'query', side_effect=targeted):
            excluded = self.advance()
        self.assertEqual(excluded['outcomes'][0]['status'], 'excluded-by-saved-scope', excluded)
        path = runner.continuous.state_path(self.config['continuous_state'])
        with runner.continuous.locked_state(path) as state:
            state['scope']['include_drafts'] = True
            runner.continuous.save_json(path, state)
        with patch.object(self.api, 'query', side_effect=targeted):
            reopened = self.advance()
        # Draft auto-merge is forbidden, but the policy change is reconciled and
        # the existing result/history survives instead of being dropped.
        self.assertEqual(runner.continuous.read_state(path)['prs'][pr()['url']]['state'], 'open')
        self.assertEqual(len(self.stored()['tasks'][0]['execution_history']), 1)

    def test_unknown_launch_holds_checkout_and_allows_other_pr(self):
        self.host.lose_response = True
        self.advance(self.node())
        self.host.lose_response = False
        second = self.advance(self.node(), self.node(2))
        by_url = {o['url']: o for o in second['outcomes']}
        self.assertEqual(by_url[pr()['url']]['status'], 'held')
        self.assertEqual(by_url[pr(number=2)['url']]['status'], 'dispatched')
        self.assertEqual(self.jobs.workspace.call_count, 2)

    def test_worker_claim_requires_head_bound_coordinator_disposition_before_resolution(self):
        thread = {'id': 'review-1', 'isResolved': False, 'isOutdated': False}
        node = self.node(threads=[thread])
        self.advance(node)
        finding = {'id': 'thread:review-1', 'severity': 'note', 'scenario': 'Fixed synthetic concern.',
                   'source_evidence': ['synthetic test and diff'], 'disposition': 'fixed', 'reply': 'Verified fix.'}
        self.finish(findings=[finding])
        request = self.advance(node)['outcomes'][0]
        self.assertEqual(request['status'], 'needs-semantic-verification', request)
        retained = self.stored()['tasks'][0]['finding_dispositions'][0]
        self.assertIsNone(retained['disposition'], 'the worker cannot dispose its own finding')
        row = self.report(node)['prs'][0]
        proof = {'pr': row['url'], 'head_sha': HEAD, 'subject_sha256': runner.semantic_subject(row),
            'request_id': self.stored()['tasks'][0]['execution_history'][-1]['request_id'],
            'verification': ['Coordinator inspected the synthetic diff and reproduction at this head.'],
            'findings': [{'finding_id': retained['finding_id'], 'finding_sha256': retained['finding_sha256'], 'disposition': 'fixed'}],
            'threads': [{'id': 'review-1', 'reply': 'Verified fix at ' + HEAD}]}
        path = self.root / 'semantic.json'
        path.write_text(json.dumps(proof))
        self.config['semantic_verifications'] = {row['url']: {'path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}}
        self.assertIsNone(self.jobs.semantic({**row, 'head_sha': 'b' * 40}))
        self.assertIsNone(self.jobs.semantic({**row, 'base_sha': 'c' * 40}))
        proof['findings'][0]['disposition'] = 'deferred'
        path.write_text(json.dumps(proof))
        self.config['semantic_verifications'][row['url']].update(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
        with self.assertRaisesRegex(runner.ExecutionError, 'semantic-disposition-must-fix-or-reject'):
            self.jobs.semantic(row)
        proof['findings'][0]['disposition'] = 'fixed'
        path.write_text(json.dumps(proof))
        self.config['semantic_verifications'][row['url']].update(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
        original = subprocess.run
        def helper(argv, **kwargs):
            if 'merge-pr.sh' in str(argv[1]):
                if '--resolve-thread' in argv:
                    self.assertIn('--verified-head', argv)
                    return subprocess.CompletedProcess(argv, 0, 'RESOLVED fixture/repo#1 thread=review-1 head=' + HEAD + ' replied=1\n', '')
                return subprocess.CompletedProcess(argv, 0, 'MERGED fixture/repo#1 via squash\n', '')
            return original(argv, **kwargs)
        with patch.object(subprocess, 'run', side_effect=helper):
            resolved = self.advance(node)
        self.assertEqual(resolved['outcomes'][0]['status'], 'resolution-executed', resolved)
        self.assertEqual(self.stored()['tasks'][0]['finding_dispositions'][0]['disposition'], 'fixed')
        pending = self.advance(self.node(state='IN_PROGRESS'))
        self.assertEqual(pending['outcomes'][0]['status'], 'waiting', pending)
        with patch.object(subprocess, 'run', side_effect=helper):
            green = self.advance(self.node(state='SUCCESS'))
        self.assertEqual(green['outcomes'][0]['status'], 'merge-executed', green)
        terminal = self.node(state='SUCCESS')
        terminal['state'] = 'MERGED'
        with patch.object(runner.org_scan, 'targeted', return_value=runner.org_scan.classify(terminal, self.api)):
            observed = self.advance()
        self.assertEqual(observed['outcomes'][0]['status'], 'merged-observed', observed)
        self.assertEqual(len(self.stored()['tasks'][0]['execution_history']), 1)

    def test_last_permitted_repair_can_still_request_semantic_verification(self):
        thread = {'id': 'review-1', 'isResolved': False, 'isOutdated': False}
        node = self.node(threads=[thread])
        self.advance(node)
        for attempt in range(2):
            self.finish(status='failed')
            result = self.advance(node)
            self.assertEqual(result['outcomes'][0]['status'], 'dispatched', result)
        self.finish()
        terminal = self.advance(node)
        self.assertEqual(terminal['outcomes'][0]['status'], 'needs-semantic-verification', terminal)
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), 3)

    def test_semantic_repair_required_alone_blocks_landing(self):
        self.check_semantic_repair_hold(False)

    def test_semantic_repair_with_threads_blocks_resolution_and_landing(self):
        self.check_semantic_repair_hold(True)

    def test_author_pushed_fix_requires_current_proof_without_another_worker(self):
        self.check_semantic_repair_hold(False, author_fix=True)

    def check_semantic_repair_hold(self, with_threads, author_fix=False):
        number = 1
        threads = [{'id': 'review-1', 'isResolved': False, 'isOutdated': False}] if with_threads else []
        self.advance(self.node(number))
        self.finish(number)
        node = self.node(number, state='SUCCESS', threads=threads)
        row = self.report(node)['prs'][0]
        proof = {'pr': row['url'], 'head_sha': HEAD, 'subject_sha256': runner.semantic_subject(row),
            'request_id': self.stored(number)['tasks'][0]['request_id'], 'repair_required': True,
            'verification': ['Coordinator reproduced an outstanding semantic defect.'],
            'threads': [{'id': 'review-1', 'reply': 'Verified separate concern.'}] if with_threads else []}
        path = self.root / 'semantic-repair.json'
        def publish(value):
            path.write_text(json.dumps(value))
            self.config['semantic_verifications'] = {row['url']: {'path': str(path),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}}
        publish(proof)
        with patch.object(self.jobs, 'workspace', side_effect=runner.ExecutionError('pr-workspace-unavailable')), \
                patch.object(runner, 'coordinator_action') as action:
            failed = self.advance(node)
        self.assertEqual(failed['outcomes'][0]['status'], 'held', failed)
        action.assert_not_called()
        self.assertIn('semantic_repair_hold', runner.continuous.read_state(self.config['continuous_state'])['prs'][row['url']])
        # Another actor resolves threads. The proof subject is now stale,
        # but the retained repair requirement must still dispatch, not land.
        green = self.node(number, state='SUCCESS', **({'headRefOid': 'b' * 40} if author_fix else {}))
        with patch.object(runner, 'coordinator_action') as action:
            if not author_fix:
                resumed = self.advance(green)
                self.assertEqual(resumed['outcomes'][0]['status'], 'dispatched', resumed)
                action.assert_not_called()
                self.assertEqual(self.advance(green)['outcomes'][0]['status'], 'active-fixer')
                self.finish(number, status='failed')
                self.assertEqual(self.advance(green)['outcomes'][0]['status'], 'dispatched')
                self.finish(number)
            completed = self.advance(green)
            self.assertEqual(completed['outcomes'][0]['status'], 'needs-semantic-verification', completed)
            action.assert_not_called()
            request = completed['outcomes'][0]['semantic_request']
            self.assertEqual(request['semantic_repair']['state'], 'needs-verification')
            self.assertEqual(request['semantic_repair']['verification'], proof['verification'])
            saved = runner.continuous.read_state(self.config['continuous_state'])
            self.assertEqual(runner.continuous.reconcile_pr(saved['prs'][row['url']], saved,
                runner.continuous.parse_time(runner.org_scan.utc_now()), saved['discovery'])[0]['kind'], 'verify-semantic')
            for kind in ['merge', 'resolution', 'auto-merge', 'fixer', 'update-branch']:
                with self.assertRaisesRegex(runner.continuous.ContinuousError, 'semantic verification required'):
                    runner.continuous_command(self.config, 'dispatch', pr=row['url'], request_id='blocked-' + kind,
                        kind=kind, head=request['head_sha'], reserve=True, host_task_id=None,
                        attempt=1, review_triage=False)
            latest = self.stored(number)['tasks'][0]['execution_history'][-1]['request_id']
            if not author_fix:
                self.assertEqual(request['semantic_repair']['repairing_request_id'], latest)
            self.config['semantic_verifications'] = {}
            self.assertEqual(self.advance(green)['outcomes'][0]['status'], 'needs-semantic-verification')
            clean = {**proof, 'head_sha': request['head_sha'], 'base_sha': request['base_sha'],
                'subject_sha256': request['subject_sha256'], 'request_id': latest,
                'repair_required': False, 'threads': [],
                'verification': ['Coordinator verified the retained defect is fixed at the current head.']}
            for key, wrong in [('head_sha', 'c' * 40), ('base_sha', 'c' * 40),
                               ('subject_sha256', 'c' * 64), ('request_id', 'stale-request')]:
                publish({**clean, key: wrong})
                held = self.advance(green)
                self.assertEqual(held['outcomes'][0]['status'], 'needs-semantic-verification', (key, held))
            # A proof without an explicit clean verdict cannot clear the concern.
            publish({k: v for k, v in clean.items() if k != 'repair_required'})
            self.assertEqual(self.advance(green)['outcomes'][0]['status'], 'needs-semantic-verification')
            action.assert_not_called()
        publish(clean)
        launches = sum(t == 'delegate_task' for t, _ in self.host.calls)
        with patch.object(runner, 'coordinator_action', return_value={'status': 'merge-executed'}) as action:
            completed = self.advance(green)
        self.assertEqual(completed['outcomes'][0]['status'], 'merge-executed', completed)
        self.assertEqual(action.call_args.args[1]['kind'], 'merge')
        self.assertNotIn('semantic_repair_hold', runner.continuous.read_state(self.config['continuous_state'])['prs'][row['url']])
        self.assertEqual(sum(t == 'delegate_task' for t, _ in self.host.calls), launches)
        if author_fix:
            self.assertEqual(launches, 1)

    def test_update_refresh_green_gates_merge_and_targeted_omission(self):
        original = subprocess.run
        def helper(argv, **kwargs):
            if 'merge-pr.sh' in str(argv[1]):
                if '--update-only' in argv:
                    return subprocess.CompletedProcess(argv, 0, 'UPDATED fixture/repo#1 previous_head=' + HEAD + ' head=' + 'b' * 40 + ' refresh_gates=required\n', '')
                self.assertIn('--expected-head', argv)
                self.assertIn('b' * 40, argv)
                return subprocess.CompletedProcess(argv, 0, 'MERGED fixture/repo#1 via squash\n', '')
            return original(argv, **kwargs)
        with patch.object(subprocess, 'run', side_effect=helper):
            updated = self.advance(self.node(state='SUCCESS', mergeStateStatus='BEHIND'))
            self.assertEqual(updated['outcomes'][0]['status'], 'update-branch-executed', updated)
            merged = self.advance(self.node(state='SUCCESS', headRefOid='b' * 40))
        self.assertEqual(merged['outcomes'][0]['status'], 'merge-executed', merged)
        self.assertNotEqual(runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]['state'], 'merged')
        terminal = self.node(state='SUCCESS', headRefOid='b' * 40)
        terminal['state'] = 'MERGED'
        query = self.api.query
        def targeted(text, variables, **kwargs):
            if 'pullRequest(number:$number)' in text:
                return {'repository': {'pullRequest': terminal}}
            return query(text, variables, **kwargs)
        with patch.object(self.api, 'query', side_effect=targeted):
            observed = self.advance()
        self.assertEqual(observed['outcomes'][0]['status'], 'merged-observed', observed)
        self.assertEqual(runner.continuous.read_state(self.config['continuous_state'])['prs'][pr()['url']]['resolved_head'], 'b' * 40)

    def test_installed_helper_imports_without_source_and_schedule_uses_one_advance(self):
        run = self.box.run([sys.executable, self.package / 'scripts/org_execute.py', '--probe', '--bridge'], check=False)
        self.assertIn('T3_CALL', run.stdout)
        self.assertNotIn('ModuleNotFoundError', run.stderr)
        state = runner.continuous.read_state(self.config['continuous_state'])
        unbound = runner.continuous.schedule_request(state, self.config['continuous_state'])
        self.assertEqual(unbound['gap'], 'missing-execution-config')
        self.assertNotIn('--advance', unbound['arguments']['prompt'])
        self.assertIn('continuous helper', unbound['arguments']['prompt'])
        state['execution_config'] = {'path': str(self.root / 'run.json'), 'sha256': 'a' * 64}
        prompt = runner.continuous.schedule_request(state, self.config['continuous_state'])['arguments']['prompt']
        self.assertEqual(prompt.count('--advance'), 1)
        self.assertIn('--continuous-state', prompt)
        self.assertIn('--wake-kind schedule --bridge', prompt)
        self.assertIn("--wake-id '<host wake ID>'", prompt)
        self.assertIn('otherwise omit --wake-id', prompt)

    def test_unbound_repo_schedule_keeps_continuous_reconciliation(self):
        path = self.root / 'repo-continuous.json'
        args = runner.continuous.build_parser().parse_args(['start', '--state', str(path),
            '--now', runner.org_scan.utc_now(), '--scope-kind', 'repo', '--scope-value', 'fixture/repo',
            '--thread-id', 'parent', '--scheduler', 'scheduled',
            '--authorization-source', self.config['authorization_source']])
        args.func(args)
        plan = runner.continuous.cmd_schedule_plan(argparse.Namespace(state=str(path)))
        self.assertEqual(plan['gap'], 'missing-execution-config')
        prompt = plan['request']['arguments']['prompt']
        self.assertIn('repo sweep for fixture/repo', prompt)
        self.assertIn('continuous.py', prompt)
        self.assertIn('--state ' + str(path), prompt)
        self.assertNotIn('--advance', prompt)

    def test_periodic_coverage_requested_without_receipt_is_explicitly_incomplete(self):
        path = runner.continuous.state_path(self.config['continuous_state'])
        with runner.continuous.locked_state(path) as state:
            state['scheduler'].update(mode='scheduled', authorization={'state': 'authorized',
                'source': self.config['authorization_source'], 'sha256': self.config['authorization_sha256']})
            runner.continuous.save_json(path, state)
        result = self.advance(self.node())
        self.assertEqual(result['outcomes'][0]['status'], 'dispatched', result)
        self.assertEqual(result['coverage']['coverage'], 'scheduled-unverified')
        self.assertFalse(result['complete'])

    def test_workspace_identity_checks_real_repository_before_launch(self):
        self.guard.stop()
        worktree = self.root / 'wrong-repo'
        worktree.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(worktree), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git('init')
        git('remote', 'add', 'origin', 'https://github.com/other/repo.git')
        row = self.report(self.node())['prs'][0]
        with self.assertRaisesRegex(runner.ExecutionError, 'pr-workspace-repository'):
            self.jobs.guard(row, {}, str(worktree))
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        git('-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'fixture')
        git('remote', 'set-url', 'origin', 'https://github.com/fixture/repo.git')
        row['head_sha'] = git('rev-parse', 'HEAD')
        guard = self.jobs.guard(row, {}, str(worktree))
        self.assertEqual(guard['observed_head'], guard['local_head'])
        git('-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'unpublished worker commit')
        with self.assertRaisesRegex(runner.ExecutionError, 'pr-workspace-head-mismatch'):
            self.jobs.guard(row, {}, str(worktree))
        row['head_sha'] = git('rev-parse', 'HEAD')
        (worktree / 'dirty.txt').write_text('uncommitted')
        with self.assertRaisesRegex(runner.ExecutionError, 'pr-workspace-dirty'):
            self.jobs.guard(row, {}, str(worktree))


if __name__ == '__main__':
    unittest.main()
