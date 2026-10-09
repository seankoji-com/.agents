"""Source-spec case 15 and REQ-ISOLATION: a delegated bug fix exercises dispatch,
result validation, integration, verification and review repair, in both the
parallel-worktree mode and the serialised single-worktree mode."""
import subprocess
import sys
from pathlib import Path

from support import CoreTestCase, FakeT3, capabilities, cli, done, git, native, result_block
from test_bugfix_direct import apply_fix, reproduce


def run_argv(argv):
    result = native(argv)
    assert result.returncode == 0, (argv, result.stderr)
    return result


def commit_all(worktree, message):
    git(worktree, 'add', '-A')
    git(worktree, 'commit', '-qm', message)
    return git(worktree, 'rev-parse', 'HEAD').stdout.strip()


class DelegatedFlow:
    """Plays the parent agent: follows next, performs native steps and T3 calls."""

    def __init__(self, test, run, t3):
        self.test, self.run, self.t3 = test, run, t3

    def create_worktree(self, action):
        run_argv(action['args']['argv'])
        self.run.record('resource', {'kind': 'worktree', 'name': action['args']['name'], 'path': action['args']['path'],
                                     'branch': action['args']['branch'], 'task_id': action['task_id']})

    def dispatch(self, action, script):
        request = action['host_call']['arguments']['clientRequestId']
        self.t3.script(request, *script)
        response = self.t3.call(action['host_call'])
        return self.run.record('dispatch', {'action_id': action['id'], 'response': response})

    def observe(self, action):
        return self.run.record('observation', {'response': self.t3.call(action['host_call'])})


class DelegatedBugFixTest(CoreTestCase):
    def delegated_plan(self, repo, tasks, review=True):
        return self.plan(repo, execution={'mode': 'delegated', 'concurrency': 4}, tasks=tasks,
                         policy={'review': {'required': review, 'role': 'reviewer'},
                                 'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                             'cwd': str(repo)}],
                                 'worktree_root': str(self.tmp / 'wt')})

    def test_parallel_delegated_fix_with_review_repair(self):
        repo = self.make_repo()
        self.assertEqual(reproduce(repo).stdout.strip(), '2')
        run = self.init(self.delegated_plan(repo, [
            {'id': 'fix', 'purpose': 'fix multi-line counting', 'files': ['wordstat.py', 'tests/*'],
             'requirement_ids': ['REQ-MULTILINE']},
            {'id': 'survey', 'purpose': 'list other callers of count_words', 'kind': 'read'}]))
        run.claim()
        t3 = FakeT3()
        flow = DelegatedFlow(self, run, t3)
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})

        # Isolation probe: the child writes the nonce into a sibling worktree.
        probe_tree = run.only('create_worktree')
        self.assertEqual(probe_tree['args']['name'], 'probe-claudeAgent')
        flow.create_worktree(probe_tree)
        probe = run.only('dispatch')
        marker = Path(run.state['tasks'][-1]['probe']['marker'])
        nonce = run.state['tasks'][-1]['probe']['nonce']
        flow.dispatch(probe, [])
        marker.write_text(nonce)
        t3.tasks['task:' + probe['host_call']['arguments']['clientRequestId']]['queue'] = [done(result_block(probe['task_id']))]
        flow.observe(run.only('query_task'))
        self.assertTrue(run.state['probes']['claudeAgent']['sibling_write'])

        # Parallel mode: the writer gets its own worktree; the read task dispatches alongside.
        actions = run.next()['actions']
        self.assertEqual(sorted(a['action'] for a in actions), ['create_worktree', 'dispatch'])
        survey = next(a for a in actions if a['action'] == 'dispatch')
        self.assertEqual(survey['task_id'], 'survey')
        flow.create_worktree(next(a for a in actions if a['action'] == 'create_worktree'))
        flow.dispatch(survey, [done(result_block('survey', findings=[{'severity': 'note', 'summary': 'only main() calls it'}]))])
        fix = next(a for a in run.next()['actions'] if a['action'] == 'dispatch')
        self.assertEqual(fix['task_id'], 'fix')
        self.assertIn(run.state['tasks'][0]['worktree'], fix['host_call']['arguments']['task'])
        self.assertEqual(run.state['execution']['isolation'] or 'parallel', 'parallel')
        flow.dispatch(fix, [])
        worktree = Path(run.state['tasks'][0]['worktree'])
        apply_fix(worktree)
        sha = commit_all(worktree, 'fix: split on any whitespace')
        t3.tasks['task:' + fix['host_call']['arguments']['clientRequestId']]['queue'] = [done(result_block(
            'fix', changed_files=['wordstat.py', 'tests/test_wordstat.py'], commit=sha,
            requirements=[{'id': 'REQ-MULTILINE', 'status': 'passed', 'explanation': 'regression test added'}]))]
        for query in [a for a in run.next()['actions'] if a['action'] == 'query_task']:
            flow.observe(query)
        statuses = {t['id']: t['status'] for t in run.state['tasks']}
        self.assertEqual((statuses['fix'], statuses['survey']), ('accepted', 'accepted'))
        result_file = run.run_dir / run.state['tasks'][0]['result']['artifact']['path']
        self.assertTrue(result_file.is_file(), 'child result is stored as a run artifact')

        integrate = run.only('integrate')
        merge = native(integrate['args']['argv'])
        run.record('integration', {'action_id': integrate['id'], 'exit_code': merge.returncode})
        self.assertEqual(reproduce(repo).stdout.strip(), '3')
        run.record('transition', {'to': 'verifying'})
        self.run_check(run, run.only('run_check'))
        log = run.scratch('green.log', reproduce(repo).stdout)
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'original reproduction prints 3', 'artifacts': [str(log)]})

        # Review round 1 is adverse: retained, triggers repair (not a fallback reviewer).
        review = run.only('dispatch')
        self.assertEqual(review['args']['target']['providerInstanceId'], 'codex')
        flow.dispatch(review, [done(result_block(review['task_id'], verdict='adverse', findings=[
            {'severity': 'major', 'summary': 'count_words lacks a docstring describing whitespace handling',
             'file': 'wordstat.py'}]))])
        flow.observe(run.only('query_task'))
        repair = run.only('repair')
        self.assertEqual(repair['args']['stage'], 'review')
        run.record('repair', {'stage': 'review', 'reason': 'review adverse', 'findings': repair['args']['findings']})
        self.assertEqual(run.status()['phase'], 'executing')
        tree = run.only('create_worktree')
        self.assertEqual(tree['args']['name'], 'repair-1')
        flow.create_worktree(tree)
        redo = run.only('dispatch')
        self.assertIn('Findings to repair', redo['host_call']['arguments']['task'])
        self.assertNotEqual(redo['host_call']['arguments']['clientRequestId'], fix['host_call']['arguments']['clientRequestId'])
        flow.dispatch(redo, [])
        repair_tree = Path(run.state['tasks'][-1]['worktree'])
        source = (repair_tree / 'wordstat.py').read_text()
        (repair_tree / 'wordstat.py').write_text(source.replace(
            'def count_words(text):\n', 'def count_words(text):\n    """Count words separated by any whitespace."""\n'))
        sha = commit_all(repair_tree, 'docs: describe whitespace handling')
        t3.tasks['task:' + redo['host_call']['arguments']['clientRequestId']]['queue'] = [done(result_block(
            'repair-1', changed_files=['wordstat.py'], commit=sha))]
        flow.observe(run.only('query_task'))
        integrate = run.only('integrate')
        merge = native(integrate['args']['argv'])
        run.record('integration', {'action_id': integrate['id'], 'exit_code': merge.returncode})
        run.record('transition', {'to': 'verifying'})
        # The repair invalidated the earlier check, acceptance and review.
        self.run_check(run, run.only('run_check'))
        log = run.scratch('green2.log', reproduce(repo).stdout)
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'original reproduction prints 3 after repair', 'artifacts': [str(log)]})
        review2 = run.only('dispatch')
        self.assertNotEqual(review2['host_call']['arguments']['clientRequestId'], review['host_call']['arguments']['clientRequestId'])
        flow.dispatch(review2, [done(result_block(review2['task_id'], verdict='approve'))])
        flow.observe(run.only('query_task'))
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'completed'})
        while True:
            actions = run.next()['actions']
            cleanup = [a for a in actions if a['action'] == 'cleanup']
            if not cleanup:
                break
            native(cleanup[0]['args']['argv'])
            run.record('cleanup', {'resource_id': cleanup[0]['args']['resource_id'], 'exit_code': 0})
        run.release()
        code, env, _ = cli('report', *run.args())
        report = env['data']['report']
        self.assertEqual(report['outcome'], 'completed')
        self.assertEqual([r['verdict'] for r in report['reviews']], ['adverse', 'approve'])
        self.assertTrue(report['reviews'][0]['invalidated'])
        self.assertEqual(run.state['counters']['repairs'], {'review': 1})
        worktrees = git(repo, 'worktree', 'list').stdout
        self.assertEqual(worktrees.count('\n'), 1, worktrees)
        self.assertEqual(git(repo, 'branch', '--list', 't3p/*').stdout.strip(), '')
        self.assertTrue(all(r['status'] in ('removed', 'gone') for r in report['resources']))
        self.assertTrue(result_file.is_file(), 'evidence survives cleanup')

    def test_serial_mode_when_probe_fails(self):
        repo = self.make_repo()
        run = self.init(self.delegated_plan(repo, [
            {'id': 'fix', 'purpose': 'fix counting', 'files': ['wordstat.py'], 'requirement_ids': ['REQ-MULTILINE']},
            {'id': 'tests', 'purpose': 'add regression test', 'files': ['tests/*'], 'requirement_ids': ['REQ-MULTILINE']}],
            review=False))
        run.claim()
        t3 = FakeT3()
        flow = DelegatedFlow(self, run, t3)
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        flow.create_worktree(run.only('create_worktree'))
        probe = run.only('dispatch')
        # The child cannot write outside the parent checkout: no marker appears.
        flow.dispatch(probe, [done(result_block(probe['task_id'], status='blocked', blockers=[{'reason': 'EPERM'}]))])
        flow.observe(run.only('query_task'))
        self.assertFalse(run.state['probes']['claudeAgent']['sibling_write'])
        tree = run.only('create_worktree')
        self.assertEqual(tree['args']['name'], 'shared')
        flow.create_worktree(tree)
        actions = run.next()['actions']
        dispatches = [a for a in actions if a['action'] == 'dispatch']
        self.assertEqual([a['task_id'] for a in dispatches], ['fix'], 'serial mode dispatches one writer')
        flow.dispatch(dispatches[0], [])
        self.assertEqual(run.state['execution']['isolation'], 'serial')
        self.assertFalse([a for a in run.next()['actions'] if a['action'] in ('dispatch', 'assign_worktree')
                          and a['task_id'] == 'tests'], 'second writer waits while the first is active')
        shared = Path(run.state['tasks'][0]['worktree'])
        source = (shared / 'wordstat.py').read_text()
        (shared / 'wordstat.py').write_text(source.replace("text.split(' ')", 'text.split()'))
        sha = commit_all(shared, 'fix')
        t3.tasks['task:' + dispatches[0]['host_call']['arguments']['clientRequestId']]['queue'] = [done(result_block(
            'fix', changed_files=['wordstat.py'], commit=sha))]
        flow.observe(run.only('query_task'))
        assign = run.only('assign_worktree')
        run.record('assign', {'task_id': assign['args']['task_id'], 'name': assign['args']['name']})
        second = run.only('dispatch')
        self.assertEqual(second['task_id'], 'tests')
        self.assertEqual(run.state['tasks'][1]['worktree'], str(shared))
        flow.dispatch(second, [])
        apply_fix(shared)
        sha = commit_all(shared, 'test: multiline regression')
        t3.tasks['task:' + second['host_call']['arguments']['clientRequestId']]['queue'] = [done(result_block(
            'tests', changed_files=['tests/test_wordstat.py'], commit=sha))]
        flow.observe(run.only('query_task'))
        integrate = run.only('integrate')
        self.assertEqual(integrate['args']['task_ids'], ['fix', 'tests'])
        self.assertTrue(integrate['args']['branch'].endswith('/shared'))
