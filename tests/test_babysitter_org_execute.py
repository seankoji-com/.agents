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

    def query(self, query, variables, **kwargs):
        self.calls.append((query, variables, kwargs))
        if query.startswith('mutation'):
            return {'enablePullRequestAutoMerge': {'pullRequest': {
                'state': 'MERGED' if self.merge_on_arm else 'OPEN', 'autoMergeRequest': {'enabledAt': 'observed'}}}}
        return {'node': {'id': variables['id'], 'state': 'OPEN', 'isDraft': self.draft,
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
        node = pr(contexts=[check('FAILURE')], autoMergeRequest=None, **changes)
        return runner.org_scan.scan(FixtureAPI([{'id': 'r', 'nameWithOwner': 'fixture/repo'}], {'r': [node]}), 'fixture')

    def execute(self, report=None):
        return runner.execute(report or self.report(), self.api, self.host, self.jobs, self.config)

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
        self.host.threads = [{'threadId': 'sibling', 'parentThreadId': None,
                             'pullRequests': [{'url': pr()['url']}]}]
        result = self.execute()
        self.assertEqual(result['outcomes'][0]['status'], 'owned-elsewhere')
        self.assertEqual(self.api.calls, [])
        self.assertFalse(any(t == 'delegate_task' for t, _ in self.host.calls))

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
                setattr(self.api, flag, True)
                result = self.execute()
                self.assertEqual(result['outcomes'][0]['status'], 'held')
                self.assertFalse(any(q.startswith('mutation') for q, _, _ in self.api.calls))
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
        with patch.dict(os.environ, {}, clear=True), patch.object(subprocess, 'run') as run:
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
