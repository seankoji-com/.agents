"""REQ-CLEANUP: success removes every run-owned worktree, branch and process;
failure preserves them and the report lists one exact cleanup command each.
Evidence survives both."""
import shlex
import subprocess
import sys
from pathlib import Path

from support import CoreTestCase, FakeT3, capabilities, cli, done, git, native, result_block


class CleanupTest(CoreTestCase):
    def delegated_run(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, execution={'mode': 'delegated', 'isolation': 'parallel'},
                                  tasks=[{'id': 'fix', 'purpose': 'fix counting', 'files': ['wordstat.py']}],
                                  policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': [],
                                          'worktree_root': str(self.tmp / 'wt')}))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        server = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(lambda: server.wait(timeout=10))
        self.addCleanup(lambda: server.poll() is None and server.kill())
        run.record('resource', {'kind': 'process', 'pid': server.pid, 'purpose': 'dev server'})
        tree = run.only('create_worktree')
        native(tree['args']['argv'])
        run.record('resource', {'action_id': tree['id'], 'kind': 'worktree', 'name': tree['args']['name'], 'path': tree['args']['path'],
                                'branch': tree['args']['branch'], 'task_id': 'fix'})
        t3 = FakeT3()
        action = run.only('dispatch')
        run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
        return repo, run, t3, action, server

    def finish_child(self, run, t3, action, content):
        worktree = Path(run.state['tasks'][0]['worktree'])
        (worktree / 'wordstat.py').write_text(content)
        git(worktree, 'commit', '-qam', 'child change')
        t3.tasks['task:' + action['host_call']['arguments']['clientRequestId']]['queue'] = [
            done(result_block('fix', changed_files=['wordstat.py']))]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})

    def test_success_removes_run_owned_resources_and_keeps_evidence(self):
        repo, run, t3, action, server = self.delegated_run()
        fixed = (repo / 'wordstat.py').read_text().replace("split(' ')", 'split()')
        self.finish_child(run, t3, action, fixed)
        integrate = run.only('integrate')
        self.assertEqual(native(integrate['args']['argv']).returncode, 0)
        run.record('integration', {'action_id': integrate['id'], 'exit_code': 0})
        run.record('transition', {'to': 'verifying'})
        log = run.scratch('ok.log', 'prints 3')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'prints 3', 'artifacts': [str(log)]})
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'completed'})
        seen = []
        while True:
            cleanup = [a for a in run.next()['actions'] if a['action'] == 'cleanup']
            if not cleanup:
                break
            seen.append(cleanup[0]['args']['kind'])
            native(cleanup[0]['args']['argv'])
            if cleanup[0]['args']['kind'] == 'process':
                server.wait(timeout=10)
            run.record('cleanup', {'resource_id': cleanup[0]['args']['resource_id'], 'exit_code': 0})
        self.assertEqual(seen, ['process', 'worktree', 'branch'])
        self.assertEqual(git(repo, 'worktree', 'list').stdout.count('\n'), 1)
        self.assertEqual(git(repo, 'branch', '--list', 't3p/*').stdout.strip(), '')
        self.assertIsNotNone(server.poll(), 'run-owned process stopped')
        artifacts = run.run_dir / 'artifacts'
        self.assertTrue(any(artifacts.rglob('*.log')) and any(artifacts.rglob('*.json')))
        code, env, _ = cli('report', *run.args())
        self.assertTrue(all(row['status'] in ('removed', 'gone') for row in env['data']['report']['resources']))
        self.assertIn('All run-owned worktrees, branches and processes were removed',
                      (run.run_dir / 'reports' / 'report.md').read_text())

    def test_failed_integration_preserves_and_lists_resources(self):
        repo, run, t3, action, server = self.delegated_run()
        (repo / 'wordstat.py').write_text('parent edit that conflicts\n')
        git(repo, 'commit', '-qam', 'parent moved on')
        self.finish_child(run, t3, action, 'child edit that conflicts\n')
        integrate = run.only('integrate')
        merge = native(integrate['args']['argv'])
        self.assertNotEqual(merge.returncode, 0)
        native(['git', '-C', str(repo), 'merge', '--abort'])
        log = run.scratch('merge.log', merge.stdout + merge.stderr)
        run.record('integration', {'action_id': integrate['id'], 'exit_code': merge.returncode, 'log': str(log)})
        self.assertEqual(run.status()['phase'], 'blocked')
        self.assertFalse([a for a in run.next()['actions'] if a['action'] == 'cleanup'], 'nothing is cleaned on failure')
        code, env, _ = cli('report', *run.args())
        report = env['data']['report']
        live = [row for row in report['resources'] if row['status'] == 'live']
        self.assertEqual(sorted(row['kind'] for row in live), ['branch', 'process', 'worktree'])
        markdown = (run.run_dir / 'reports' / 'report.md').read_text()
        self.assertIn('## Preserved resources', markdown)
        for row in live:
            self.assertIn(f'`{row["cleanup_command"]}`', markdown)
            self.assertEqual(len(shlex.split(row['cleanup_command'])) > 1, True)
        self.assertIn('t3p/', git(repo, 'branch', '--list', 't3p/*').stdout)
        self.assertEqual(git(repo, 'worktree', 'list').stdout.count('\n'), 2)
        self.assertIsNone(server.poll(), 'process preserved for inspection')
        self.assertTrue((run.run_dir / run.state['integrations'][-1]['log']['path']).is_file())
        for row in sorted(live, key=lambda r: {'process': 0, 'worktree': 1, 'branch': 2}[r['kind']]):
            self.assertEqual(native(shlex.split(row['cleanup_command'])).returncode, 0, row)
        server.wait(timeout=10)
        self.assertEqual(git(repo, 'branch', '--list', 't3p/*').stdout.strip(), '')
