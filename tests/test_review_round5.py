"""Regression tests for the PR #1 review threads on the core (round 5). Each test
reproduces the reported failure scenario and asserts the fixed behaviour."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from support import ROOT, CoreTestCase, FakeT3, capabilities, cli, done, git, native, result_block
from test_bugfix_delegated import commit_all

sys.path.insert(0, str(ROOT))
from core import engine, planning, results, snapshot, t3  # noqa: E402


def edit(repo, text='\n# changed\n'):
    (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text() + text)


class Round5CoreTest(CoreTestCase):
    def start(self, tasks=None, mode='direct', isolation=None, review=False, plan=None, **policy):
        repo = self.make_repo()
        execution = {'mode': mode}
        if isolation:
            execution['isolation'] = isolation
        settings = {'review': {'required': review, 'role': 'reviewer'}, 'checks': [], 'worktree_root': str(self.tmp / 'wt')}
        settings.update(policy)
        overrides = dict({'execution': execution, 'policy': settings}, **(plan or {}))
        if tasks:
            overrides['tasks'] = tasks
        run = self.init(self.plan(repo, **overrides))
        run.claim()
        if mode == 'delegated' or review:
            run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run, FakeT3()

    def accept(self, run):
        log = run.scratch(f'ok-{run.generation}.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})

    def to_verifying(self, repo, run):
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})

    # -- seankoji P1: self tasks get their own baseline -------------------------------

    def test_disjoint_self_writers_keep_their_own_baselines_and_preexisting_dirt(self):
        repo = self.make_repo()
        (repo / 'notes.txt').write_text('unrelated work in progress\n')
        run = self.init(self.plan(repo, tasks=[
            {'id': 'a', 'purpose': 'fix', 'files': ['wordstat.py']},
            {'id': 'b', 'purpose': 'test', 'files': ['tests/test_wordstat.py'], 'depends_on': ['a']}],
            policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': []}))
        run.claim()
        run.record('transition', {'to': 'executing'})
        edit(repo)
        out = run.record('result', {'task_id': 'a', 'text': result_block('a', changed_files=['wordstat.py'])})
        self.assertEqual(out['result']['outcome'], 'accepted', out)
        commit_all(repo, 'a')
        test_file = repo / 'tests' / 'test_wordstat.py'
        test_file.write_text(test_file.read_text() + '\n# more tests\n')
        out = run.record('result', {'task_id': 'b', 'text': result_block('b', changed_files=['tests/test_wordstat.py'])})
        self.assertEqual(out['result']['outcome'], 'accepted', out)
        self.assertEqual(run.state['tasks'][1]['result']['changed_files'], ['tests/test_wordstat.py'])

    # -- seankoji P1: nested runs keep a serial writer live --------------------------

    def test_pending_nested_runs_hold_the_serial_writer_slot(self):
        repo, run, t3 = self.start([{'id': 'a', 'purpose': 'first', 'files': ['wordstat.py']},
                                    {'id': 'b', 'purpose': 'second', 'files': ['tests/test_wordstat.py']}],
                                   mode='delegated', isolation='serial')
        first = run.only('dispatch')
        self.assertEqual(first['task_id'], 'a')
        response = t3.call(first['host_call'])
        run.record('dispatch', {'action_id': first['id'], 'response': response})
        edit(repo)
        commit_all(repo, 'a')
        t3.tasks[response['taskId']]['queue'] = [dict(done(result_block('a', changed_files=['wordstat.py'])),
                                                      hasPendingChildRuns=True)]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.state['tasks'][0]['status'], 'active', 'a result is not read while nested runs are pending')
        actions = run.next()['actions']
        self.assertEqual([(a['action'], a['task_id']) for a in actions], [('query_task', 'a')],
                         'b waits while a nested run of a may still write')
        t3.tasks[response['taskId']]['queue'] = [done(result_block('a', changed_files=['wordstat.py']))]
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.only('dispatch')['task_id'], 'b')

    # -- seankoji P1: failure stops owned children first ------------------------------

    def test_fail_with_a_live_child_stops_it_before_failing(self):
        repo, run, t3 = self.start([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}],
                                   mode='delegated', isolation='serial')
        dispatch = run.only('dispatch')
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        out = run.record('fail', {'reason': 'operator gave up'})
        self.assertEqual((out['result']['phase'], out['result']['then']), ('cancelling', 'failed'))
        cancel = run.only('cancel_task')
        t3.tasks[cancel['args']['host_task_id']]['cancel_reply'] = 'cancelled'
        run.record('cancel', {'response': t3.call(cancel['host_call'])})
        self.assertEqual(run.only('transition')['args']['to'], 'failed')
        run.record('transition', {'to': 'failed'})
        self.assertEqual(run.status()['phase'], 'failed')

    def test_transition_to_failed_also_routes_through_cancellation(self):
        repo, run, t3 = self.start([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}],
                                   mode='delegated', isolation='serial')
        dispatch = run.only('dispatch')
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        run.record('transition', {'to': 'failed', 'reason': 'x'})
        self.assertEqual(run.status()['phase'], 'cancelling')

    # -- seankoji P1: review brief and binding use one current contract --------------

    def test_review_brief_reads_the_current_requirements_source(self):
        goal = self.write('goal.md', '## Definition of done\n- [ ] [REQ-MULTILINE] count splits on any whitespace '
                                     '[verify:command]\n\n## Global constraints\n- Keep the CLI.\n')
        repo, run, t3 = self.start(review=True, plan={'brief': {'text': 'fix', 'requirements_source': str(goal)}})
        self.to_verifying(repo, run)
        goal.write_text(goal.read_text().replace('any whitespace', 'tabs and spaces').replace('Keep the CLI.', 'Keep it fast.'))
        self.accept(run)
        review = run.only('dispatch')
        brief = review['host_call']['arguments']['task']
        self.assertIn('tabs and spaces', brief)
        self.assertIn('Keep it fast.', brief)
        self.assertNotIn('any whitespace', brief)
        code, env, _ = cli('validate', *run.args())
        self.assertEqual(review['args']['binding']['contract_hash'], env['data']['binding']['contract_hash'])

    # -- seankoji P1: worktree provenance -------------------------------------------

    def test_a_preexisting_worktree_is_never_adopted(self):
        repo, run, t3 = self.start([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}],
                                   mode='delegated', isolation='parallel')
        user_tree = self.tmp / 'user-tree'
        git(repo, 'worktree', 'add', '-q', '--detach', str(user_tree), 'HEAD')
        (user_tree / 'precious.txt').write_text('user data\n')
        code, env, _ = run.record_raw('resource', {'kind': 'worktree', 'name': 'probe-codex', 'path': str(user_tree)})
        self.assertEqual((code, env['error']['code']), (2, 'action_id'))
        tree = run.only('create_worktree')
        code, env, _ = run.record_raw('resource', {'action_id': tree['id'], 'kind': 'worktree', 'name': tree['args']['name'],
                                                   'path': str(user_tree), 'branch': tree['args']['branch']})
        self.assertEqual((code, env['error']['code']), (2, 'resource_mismatch'))
        native(tree['args']['argv'])
        (Path(tree['args']['path']) / 'stray.txt').write_text('not from git worktree add\n')
        code, env, _ = run.record_raw('resource', {'action_id': tree['id'], 'kind': 'worktree', 'name': tree['args']['name'],
                                                   'path': tree['args']['path'], 'branch': tree['args']['branch']})
        self.assertEqual((code, env['error']['code']), (4, 'worktree_not_fresh'))
        (Path(tree['args']['path']) / 'stray.txt').unlink()
        run.record('resource', {'action_id': tree['id'], 'kind': 'worktree', 'name': tree['args']['name'],
                                'path': tree['args']['path'], 'branch': tree['args']['branch']})
        self.assertTrue((user_tree / 'precious.txt').exists())

    # -- Copilot: replaced worktrees and branches are not cleaned up ------------------

    def test_cleanup_skips_a_recreated_worktree_and_branch(self):
        repo, run, t3 = self.start([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}],
                                   mode='delegated', isolation='parallel')
        tree = run.only('create_worktree')
        native(tree['args']['argv'])
        run.record('resource', {'action_id': tree['id'], 'kind': 'worktree', 'name': tree['args']['name'],
                                'path': tree['args']['path'], 'branch': tree['args']['branch']})
        path, branch = tree['args']['path'], tree['args']['branch']
        git(repo, 'worktree', 'remove', '--force', path)
        git(repo, 'branch', '-D', branch)
        git(repo, 'commit', '-q', '--allow-empty', '-m', 'move on')
        git(repo, 'worktree', 'add', '-q', '-b', branch, path, 'HEAD')
        (Path(path) / 'someone-elses.txt').write_text('not run-owned\n')
        for item in run.state['resources']:
            action = engine.cleanup_action(item)
            self.assertEqual(action['args']['identity'], 'replaced', item['kind'])
            self.assertIsNone(action['args']['argv'])

    # -- Copilot: remote completion is bound to the receipt ---------------------------

    def test_observation_of_another_pr_cannot_complete(self):
        repo, run, t3 = self.start(plan={'authorization': {'endstate': 'pr', 'remote': ['push', 'pr'], 'evidence': 'x'}})
        edit(repo)
        commit_all(repo, 'fix')
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'publishing'})
        head = git(repo, 'rev-parse', 'HEAD').stdout.strip()
        run.record('remote-receipt', {'kind': 'pr', 'url': 'https://github.com/o/r/pull/1', 'number': 1, 'head_sha': head})
        code, env, _ = run.record_raw('remote-observation', {'kind': 'pr', 'url': 'https://github.com/o/r/pull/2',
                                                             'number': 2, 'state': 'OPEN', 'head_sha': head})
        self.assertEqual((code, env['error']['code']), (2, 'remote_mismatch'))
        code, env, _ = run.record_raw('transition', {'to': 'completed'})
        self.assertEqual(code, 4)

    # -- Copilot / grumpy: check logs come only from permitted roots ------------------

    def test_check_log_root_cannot_widen_the_evidence_roots(self):
        repo, run, t3 = self.start(checks=[{'name': 'unit', 'argv': [sys.executable, '-c', 'pass']}])
        self.to_verifying(repo, run)
        action = run.only('run_check')
        outside = self.tmp / 'outside.log'
        outside.write_text('secret\n')
        code, env, _ = run.record_raw('check', {'name': 'unit', 'argv': action['args']['argv'], 'exit_code': 0,
                                                'log': str(outside), 'log_root': '/', 'snapshot': action['args']['snapshot']})
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))

    # -- Copilot: policy records cannot weaken obligations ----------------------------

    def test_policy_records_cannot_weaken_obligations(self):
        repo, run, t3 = self.start(review=True, checks=[{'name': 'unit', 'argv': [sys.executable, '-c', 'pass']}])
        for change, code in (({'review': {'required': False}}, 'policy_weakening'),
                             ({'checks': []}, 'policy_weakening'),
                             ({'checks': [{'name': 'unit', 'argv': ['true'], 'required': True}]}, 'policy_weakening'),
                             ({'checks': [{'name': 'unit', 'argv': [sys.executable, '-c', 'pass'], 'required': False}]},
                              'policy_weakening'),
                             ({'repository_policy': None}, 'policy_fixed'),
                             ({'evidence_roots': ['/']}, 'policy_fixed')):
            got, env, _ = run.record_raw('policy', {'policy': change})
            self.assertEqual((got, env['error']['code']), (4, code), change)
        run.record('policy', {'policy': {'checks': [{'name': 'unit', 'argv': [sys.executable, '-c', 'pass']},
                                                    {'name': 'lint', 'argv': [sys.executable, '-c', 'pass']}]}})
        self.assertEqual([c['name'] for c in run.state['policy']['checks']], ['unit', 'lint'])
        self.assertTrue(run.state['policy']['review']['required'])

    # -- Copilot: absolute evidence must be contained ---------------------------------

    def test_absolute_evidence_outside_the_roots_is_rejected(self):
        repo, run, t3 = self.start()
        edit(repo)
        outside = self.tmp / 'elsewhere.txt'
        outside.write_text('unrelated\n')
        out = run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'], requirements=[
            {'id': 'REQ-MULTILINE', 'status': 'passed', 'explanation': 'x', 'evidence': [{'path': str(outside)}]}])})
        self.assertEqual(out['result']['outcome'], 'blocked')
        self.assertEqual(run.state['tasks'][0]['rejections'][-1]['code'], 'result_evidence_outside')

    # -- grumpy P1: a cancel record needs a host task ID ------------------------------

    def test_cancel_without_a_task_id_matches_nothing(self):
        repo, run, t3 = self.start([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}],
                                   mode='delegated', isolation='serial')
        dispatch = run.only('dispatch')
        run.record('dispatch', {'action_id': dispatch['id'], 'error': {'code': 'invalid_request', 'message': 'bad'}})
        run.record('transition', {'to': 'cancelling'})
        code, env, _ = run.record_raw('cancel', {'response': {'status': 'cancelled'}})
        self.assertEqual((code, env['error']['code']), (2, 'host_task_id'))
        self.assertEqual(run.state['cancellation']['outcomes'], [])

    # -- grumpy P2: repairs without a writer use the work role ------------------------

    def test_repair_without_a_writer_uses_the_work_role(self):
        repo, run, t3 = self.start([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}], work_role='researcher',
                                   checks=[{'name': 'unit', 'argv': [sys.executable, '-c', 'raise SystemExit(1)']}])
        run.record('result', {'task_id': 'survey', 'text': result_block('survey')})
        run.record('transition', {'to': 'verifying'})
        self.run_check(run, run.only('run_check'))
        repair = run.only('repair')
        run.record('repair', {'action_id': repair['id'], **repair['args']})
        task = run.state['tasks'][-1]
        self.assertEqual((task['id'], task['role']), ('repair-1', 'researcher'))

    # -- seankoji P2: stale optional evidence does not block readiness ----------------

    def test_stale_optional_check_does_not_block_ready(self):
        repo, run, t3 = self.start(checks=[{'name': 'style', 'argv': [sys.executable, '-c', 'pass'], 'required': False}])
        self.to_verifying(repo, run)
        log = run.scratch('style.log', 'ok')
        run.record('check', {'name': 'style', 'argv': [sys.executable, '-c', 'pass'], 'exit_code': 0, 'log': str(log)})
        edit(repo, '\n# after the optional check\n')
        self.accept(run)
        self.assertEqual(run.only('transition')['args']['to'], 'ready')
        run.record('transition', {'to': 'ready'})
        code, env, _ = cli('validate', *run.args())
        style = next(row for row in env['data']['checks'] if row['name'] == 'style')
        self.assertIn('stale_reason', style, 'stale optional evidence stays visible')

    # -- seankoji P1: repairs own the files their findings name -----------------------

    def test_repair_of_an_earlier_writers_file_after_a_later_writer(self):
        repo, run, t3 = self.start([{'id': 'a', 'purpose': 'first', 'files': ['wordstat.py']},
                                    {'id': 'b', 'purpose': 'second', 'files': ['tests/test_wordstat.py'], 'depends_on': ['a']}],
                                   mode='delegated', isolation='serial')
        for task_id, path in (('a', repo / 'wordstat.py'), ('b', repo / 'tests' / 'test_wordstat.py')):
            dispatch = run.only('dispatch')
            self.assertEqual(dispatch['task_id'], task_id)
            response = t3.call(dispatch['host_call'])
            run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
            path.write_text(path.read_text() + f'\n# {task_id}\n')
            commit_all(repo, task_id)
            rel = str(path.relative_to(repo))
            t3.tasks[response['taskId']]['queue'] = [done(result_block(task_id, changed_files=[rel]))]
            run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        run.record('transition', {'to': 'verifying'})
        run.record('repair', {'stage': 'review', 'findings': [{'severity': 'major', 'summary': 'tabs', 'file': 'wordstat.py'}]})
        repair = run.state['tasks'][-1]
        self.assertIn('wordstat.py', repair['files'])
        dispatch = run.only('dispatch')
        self.assertEqual(dispatch['task_id'], 'repair-1')
        response = t3.call(dispatch['host_call'])
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        edit(repo, '\n# repaired\n')
        commit_all(repo, 'repair')
        t3.tasks[response['taskId']]['queue'] = [done(result_block('repair-1', changed_files=['wordstat.py']))]
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'accepted', out)

    # -- seankoji / Architect nits -----------------------------------------------------

    def test_tracked_file_swapped_for_a_link_into_an_exclusion_moves_the_snapshot(self):
        repo = self.make_repo()
        goal = repo / 'goal.md'
        goal.write_text('goal\n')
        before = snapshot.take(repo, [goal])
        (repo / 'wordstat.py').unlink()
        (repo / 'wordstat.py').symlink_to(goal)
        self.assertNotEqual(snapshot.token(snapshot.take(repo, [goal])), snapshot.token(before))
        (repo / 'loop').symlink_to(repo / 'loop')
        snapshot.take(repo, [goal])  # a symlink loop is hashed, not an internal error

    def test_ownership_globs_stay_within_a_segment(self):
        self.assertTrue(results.owns(['src/*.py'], 'src/a.py'))
        self.assertFalse(results.owns(['src/*.py'], 'src/util/deep.py'))
        self.assertTrue(results.owns(['src/**/*.py'], 'src/util/deep.py'))
        self.assertTrue(results.owns(['src/**'], 'src/a/b/c'))
        self.assertTrue(results.owns([], 'anything'))

    def test_malformed_echoed_dispatch_is_refused_cleanly(self):
        repo, run, t3 = self.start([{'id': 'fix', 'purpose': 'fix', 'files': ['wordstat.py']}],
                                   mode='delegated', isolation='serial')
        bogus = {'action': 'dispatch', 'host_call': 'x', 'task_id': 'fix', 'args': {}}
        bogus['id'] = engine.action('dispatch', 'dispatch', task_id='fix', args={}, host_call='x')['id']
        code, env, _ = run.record_raw('dispatch', {'action': bogus, 'response': {}})
        self.assertEqual((code, env['error']['code']), (4, 'action_tampered'))

    def test_check_exit_code_must_be_an_integer(self):
        repo, run, t3 = self.start(checks=[{'name': 'unit', 'argv': [sys.executable, '-c', 'pass']}])
        self.to_verifying(repo, run)
        action = run.only('run_check')
        Path(action['args']['log_path']).write_text('ok\n')
        for bad in (False, '0'):
            code, env, _ = run.record_raw('check', {'name': 'unit', 'argv': action['args']['argv'], 'exit_code': bad,
                                                    'log': action['args']['log_path'], 'snapshot': action['args']['snapshot']})
            self.assertEqual((code, env['error']['code']), (2, 'exit_code'), bad)

    def test_terminal_status_without_work_state_is_terminal(self):
        self.assertEqual(t3.outcome(t3.observation({'taskId': 't', 'status': 'failed'})), 'failed')
        self.assertEqual(t3.outcome(t3.observation({'taskId': 't', 'status': 'completed', 'workState': 'result_available',
                                                    'hasPendingChildRuns': True})), 'working')
        self.assertEqual(t3.outcome(t3.observation({'taskId': 't', 'status': 'running'})), 'working')

    def test_whitespace_brief_still_reports(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, brief={'text': ' ', 'requirements': [
            {'id': 'REQ-MULTILINE', 'text': 'count splits on any whitespace', 'kind': 'command'}], 'constraints': []}))
        code, env, _ = cli('report', *run.args())
        self.assertEqual(code, 0, env)

    def test_task_defaults_are_not_shared(self):
        tasks = planning._tasks([{'id': 'a', 'purpose': 'a'}, {'id': 'b', 'purpose': 'b'}], 'direct', set(), None)
        tasks[0]['files'].append('x')
        self.assertEqual(tasks[1]['files'], [])
        self.assertEqual(planning.TASK_DEFAULTS['files'], [])


class LauncherTest(CoreTestCase):
    """seankoji: one launcher, whatever the package layout."""

    def test_launcher_runs_the_core_installed_and_from_source(self):
        home = self.tmp / 'home'
        source = self.tmp / 'src'
        for part in ('core', 'plugins', 'scripts'):
            shutil.copytree(ROOT / part, source / part, ignore=shutil.ignore_patterns('__pycache__'))
        env = {key: value for key, value in os.environ.items()
               if key not in ('T3_PLUGINS_PREFIX', 'T3_PLUGINS_STATE_ROOT', 'XDG_STATE_HOME')}
        env['HOME'] = str(home)
        installed = subprocess.run([sys.executable, str(source / 'scripts' / 'install.py')], capture_output=True,
                                   text=True, env=env)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        prefix = home / '.local' / 'share' / 't3-plugins'
        for launcher in (prefix / 'imps' / 'current' / 'cli.py', ROOT / 'plugins' / 'imps' / 'cli.py'):
            result = subprocess.run([sys.executable, str(launcher), 'status', '--state-root', str(self.tmp / 's'),
                                     '--run-id', 'bad'], capture_output=True, text=True, env=env)
            envelope = json.loads(result.stdout)
            self.assertEqual((result.returncode, envelope['op'], envelope['error']['code']), (2, 'status', 'run_id'), launcher)


if __name__ == '__main__':
    import unittest
    unittest.main()
