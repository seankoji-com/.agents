"""REQ-BLOCKED: every code path that produces `blocked` names a reason, the task
IDs involved and one complete resume argv with no unresolved placeholder."""
import json
import re
import subprocess
import sys
from pathlib import Path

from support import CLI, ROOT, TIMEOUT, CoreTestCase, FakeT3, capabilities, cli, done, git, native, result_block

sys.path.insert(0, str(ROOT))
from core.blockers import CODES  # noqa: E402

PLACEHOLDER = re.compile(r'<[^>]*>|\{[^}]*\}|^None$|^$|TODO|TBD')


class BlockedPathsTest(CoreTestCase):
    def base(self, **overrides):
        repo = self.make_repo()
        policy = {'review': {'required': False, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}
        policy.update(overrides.pop('policy', {}))
        run = self.init(self.plan(repo, policy=policy, **overrides))
        run.claim()
        return repo, run

    def executing_direct(self, **overrides):
        repo, run = self.base(**overrides)
        run.record('transition', {'to': 'executing'})
        return repo, run

    def delegated(self, tasks, caps=None, **overrides):
        repo, run = self.base(execution={'mode': 'delegated', 'isolation': 'parallel'}, tasks=tasks, **overrides)
        run.record('capabilities', {'response': caps or capabilities()})
        if run.state['capabilities']['available']:
            run.record('transition', {'to': 'executing'})
        return repo, run

    def verifying(self, **overrides):
        repo, run = self.executing_direct(**overrides)
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        git(repo, 'commit', '-qam', 'fix')
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        return repo, run

    # -- one scenario per blocker code -----------------------------------------------------------
    def capability_unavailable(self):
        caps = capabilities()
        caps['features']['appOwnedSubagents'] = False
        repo, run = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}], caps=caps)
        return run, run.next()['blocked']

    def provider_unavailable(self):
        repo, run = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read',
                                     'target': {'providerInstanceId': 'codex', 'model': 'gpt-6-sol'}}])
        action = run.only('dispatch')
        run.record('dispatch', {'action_id': action['id'], 'error': {'code': 'capability_denied', 'message': 'provider unavailable'}})
        return run, run.next()['blocked']

    def malformed_result(self):
        repo, run = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        t3 = FakeT3()
        for _ in range(2):
            action = run.only('dispatch')
            t3.script(action['host_call']['arguments']['clientRequestId'], done('```json\n{broken\n```'))
            run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
            out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        return run, out['result']['blocker']

    def result_rejected(self):
        repo, run = self.executing_direct()
        out = run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['ghost.py'])})
        return run, out['result']['blocker']

    def task_failed(self):
        repo, run = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        t3 = FakeT3()
        action = run.only('dispatch')
        t3.script(action['host_call']['arguments']['clientRequestId'],
                  {'status': 'failed', 'workState': 'result_available', 'summary': 'provider crashed'})
        run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        return run, out['result']['blocker']

    def cross_parent_resume(self):
        repo, run = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        action = run.only('dispatch')
        run.record('dispatch', {'action_id': action['id'], 'response': FakeT3().call(action['host_call'])})
        return run, run.next(parent='thread-elsewhere')['blocked']

    def cancel_unconfirmed(self):
        repo, run = self.delegated([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        t3 = FakeT3()
        action = run.only('dispatch')
        run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
        run.record('transition', {'to': 'cancelling'})
        run.record('cancel', {'response': t3.call(run.only('cancel_task')['host_call'])})
        run.record('observation', {'response': t3.call(run.only('confirm_stop')['host_call'])})
        return run, run.next()['blocked']

    def repair_limit(self):
        repo, run = self.verifying(policy={'repair_limit': 0, 'checks': [
            {'name': 'fails', 'argv': [sys.executable, '-c', 'raise SystemExit(1)'], 'cwd': '.'}]})
        action = run.only('run_check')
        result = native(action['args']['argv'])
        Path(action['args']['log_path']).write_text(result.stderr)
        run.record('check', {'name': 'fails', 'argv': action['args']['argv'], 'exit_code': result.returncode,
                             'log': action['args']['log_path']})
        return run, run.next()['blocked']

    def budget_exhausted(self):
        repo, run = self.executing_direct()
        run.release()
        state_file = run.run_dir / 'run.json'
        state = json.loads(state_file.read_text())
        state['budget']['spent_seconds'] = state['budget']['seconds']
        state_file.write_text(json.dumps(state))
        return run, run.next()['blocked']

    def integration_failed(self):
        repo, run = self.delegated([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}])
        tree = run.only('create_worktree')
        native(tree['args']['argv'])
        run.record('resource', {'action_id': tree['id'], 'kind': 'worktree', 'name': tree['args']['name'], 'path': tree['args']['path'],
                                'branch': tree['args']['branch'], 'task_id': 'fix'})
        t3 = FakeT3()
        action = run.only('dispatch')
        run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
        worktree = Path(run.state['tasks'][0]['worktree'])
        (worktree / 'wordstat.py').write_text('conflicting change\n')
        git(worktree, 'commit', '-qam', 'child change')
        t3.tasks['task:' + action['host_call']['arguments']['clientRequestId']]['queue'] = [
            done(result_block('fix', changed_files=['wordstat.py']))]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        integrate = run.only('integrate')
        out = run.record('integration', {'action_id': integrate['id'], 'exit_code': 1})
        return run, out['result']['blocker']

    def endstate_unsupported(self):
        repo, run = self.verifying(authorization={'endstate': 'release', 'evidence': 'x'})
        log = run.scratch('ok.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        run.record('transition', {'to': 'ready'})
        return run, run.next()['blocked']

    def remote_unconfirmed(self):
        repo, run = self.verifying(authorization={'endstate': 'pr', 'evidence': 'x'})
        log = run.scratch('ok.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'publishing'})
        run.record('remote-receipt', {'kind': 'pr', 'url': 'https://example.invalid/pr/1'})
        run.record('remote-observation', {'kind': 'pr', 'url': 'https://example.invalid/pr/1', 'state': 'closed',
                                          'head_sha': git(repo, 'rev-parse', 'HEAD').stdout.strip()})
        return run, run.next()['blocked']

    def evidence_unavailable(self):
        repo, run = self.verifying()
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'unavailable', 'kind': 'command',
                                  'explanation': 'interpreter missing on this host'})
        return run, run.next()['blocked']

    def operator(self):
        repo, run = self.executing_direct()
        out = run.record('block', {'reason': 'symptom not reproduced; need the production log line'})
        return run, out['result']['blocker']

    def test_every_blocker_code_is_actionable(self):
        produced = {}
        for code in CODES:
            with self.subTest(code=code):
                run, blocker = getattr(self, code)()
                self.assertIsNotNone(blocker, f'{code} scenario produced no block')
                self.assertEqual(blocker['code'], code)
                produced[code] = blocker
                self.assertTrue(blocker['reason'].strip())
                self.assertIsInstance(blocker['task_ids'], list)
                argv = blocker['resume']['argv']
                self.assertEqual(argv[:2], ['python3', str(CLI)])
                for item in argv:
                    self.assertIsInstance(item, str)
                    self.assertIsNone(PLACEHOLDER.search(item), f'{code}: unresolved {item!r} in {argv}')
                self.assertIn(run.run_id, argv)
                self.assertIn('then', blocker['resume'])
                self.assertIn(f'resume {run.run_id}', blocker['resume']['then'])
        self.assertEqual(set(produced), set(CODES))
        task_scoped = {'provider_unavailable', 'malformed_result', 'result_rejected', 'task_failed', 'cross_parent_resume',
                       'cancel_unconfirmed', 'integration_failed'}
        for code in task_scoped:
            self.assertTrue(produced[code]['task_ids'], f'{code} must name its tasks')
        for code in set(CODES) - task_scoped - {'budget_exhausted'}:
            self.assertEqual(produced[code]['task_ids'], [], f'{code} involves no task')

    def test_resume_command_runs_as_printed(self):
        run, blocker = self.repair_limit()
        run.record('block', {'blocker': blocker})
        run.release()
        result = subprocess.run([sys.executable, *blocker['resume']['argv'][1:]], capture_output=True, text=True,
                                timeout=TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(run.status()['phase'], 'verifying')
        self.assertEqual(run.state['policy']['repair_limit'], 1)
        run.claim()
        self.assertEqual(run.only('repair')['args']['stage'], 'checks')
        markdown_code, env, _ = cli('report', *run.args())
        self.assertEqual(markdown_code, 0)

    def test_every_resume_command_unblocks(self):
        """The printed resume command runs as printed and the run does not fall
        straight back into the same block."""
        for code in CODES:
            with self.subTest(code=code):
                run, blocker = getattr(self, code)()
                if run.status()['owner']:
                    run.release()
                result = subprocess.run([sys.executable, *blocker['resume']['argv'][1:]], capture_output=True, text=True,
                                timeout=TIMEOUT)
                self.assertEqual(result.returncode, 0, f'{code}: {result.stdout} {result.stderr}')
                self.assertTrue(json.loads(result.stdout)['ok'])
                run.claim()
                after = run.next()
                self.assertNotEqual((after.get('blocked') or {}).get('code'), code,
                                    f'{code} re-blocked immediately: {after.get("blocked")}')
                run.release()
