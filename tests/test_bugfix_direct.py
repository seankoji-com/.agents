"""Source-spec case 14: a direct bug fix reproduces red, fixes the defect, passes
the original reproduction and produces a valid report."""
import json
import subprocess
import sys

from support import CoreTestCase, FakeT3, PARENT, capabilities, cli, done, result_block, git

REGRESSION_TEST = '''

    def test_multiline(self):
        self.assertEqual(run('one two\\nthree\\n').stdout.strip(), '3')
'''


def reproduce(repo):
    return subprocess.run([sys.executable, 'wordstat.py', 'count', 'notes.txt'], cwd=repo, capture_output=True, text=True)


def apply_fix(repo):
    source = (repo / 'wordstat.py').read_text()
    (repo / 'wordstat.py').write_text(source.replace("text.split(' ')", 'text.split()'))
    tests = (repo / 'tests' / 'test_wordstat.py').read_text()
    marker = "    def test_usage(self):"
    (repo / 'tests' / 'test_wordstat.py').write_text(tests.replace(marker, REGRESSION_TEST.strip('\n') + '\n\n' + marker))


def approve_review(run, t3, test):
    action = run.only('dispatch')
    test.assertEqual(action['host_call']['arguments']['role'], 'review')
    request = action['host_call']['arguments']['clientRequestId']
    task_id = action['task_id']
    t3.script(request, done(result_block(task_id, verdict='approve', findings=[
        {'severity': 'note', 'summary': 'split() also handles tabs'}])))
    run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
    query = run.only('query_task')
    run.record('observation', {'response': t3.call(query['host_call'])})
    return action


class DirectBugFixTest(CoreTestCase):
    def test_direct_bugfix_red_fix_green_report(self):
        repo = self.make_repo()
        red = reproduce(repo)
        self.assertEqual(red.stdout.strip(), '2', 'fixture defect must reproduce before the fix')
        red_log = self.write('red.log', f'argv: python3 wordstat.py count notes.txt\nexpected: 3\nactual: {red.stdout}')

        run = self.init(self.plan(repo, policy={'review': {'required': True, 'role': 'reviewer'},
                                               'checks': [{'name': 'unit', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                                           'cwd': str(repo)}],
                                               'worktree_root': str(self.tmp / 'wt')}))
        run.claim()
        t3 = FakeT3()
        discover = run.only('discover')
        self.assertEqual(discover['host_call']['tool'], 'orchestrator_capabilities')
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': run.only('transition')['args']['to']})
        implement = run.only('implement')
        self.assertEqual(implement['task_id'], 'main')
        apply_fix(repo)
        run.record('result', {'task_id': 'main', 'text': result_block(
            'main', changed_files=['tests/test_wordstat.py', 'wordstat.py'],
            requirements=[{'id': 'REQ-MULTILINE', 'status': 'passed', 'explanation': 'split() on any whitespace'}])})
        run.record('transition', {'to': 'verifying'})
        self.run_check(run, run.only('run_check'))
        accept = run.only('accept')
        self.assertEqual(accept['args']['requirement_id'], 'REQ-MULTILINE')
        green = reproduce(repo)
        self.assertEqual(green.stdout.strip(), '3')
        green_log = run.scratch('green.log', f'argv: python3 wordstat.py count notes.txt\nexpected: 3\nactual: {green.stdout}')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'original reproduction now prints 3', 'artifacts': [str(green_log)]})
        review = approve_review(run, t3, self)
        self.assertEqual(review['args']['target']['providerInstanceId'], 'codex',
                         'default chain picks the first catalog provider that is not the implementer')
        run.record('note', {'key': 'cause', 'text': "count_words split on ' ' only, so newlines joined words"})
        run.record('note', {'key': 'before', 'text': f'red evidence {red_log.name}: printed 2'})
        run.record('transition', {'to': run.only('transition')['args']['to']})
        self.assertEqual(run.only('transition')['args']['to'], 'completed')
        run.record('transition', {'to': 'completed'})
        run.release()

        code, env, _ = cli('report', *run.args())
        self.assertEqual(code, 0, env)
        report = env['data']['report']
        self.assertEqual(report['outcome'], 'completed')
        self.assertEqual(report['readiness']['status'], 'ready')
        self.assertEqual([r['status'] for r in report['requirements']], ['passed'])
        self.assertEqual(report['review']['status'], 'passed')
        self.assertEqual(report['reviews'][0]['selection']['providerInstanceId'], 'codex')
        markdown = (run.run_dir / 'reports' / 'report.md').read_text()
        self.assertIn('REQ-MULTILINE', markdown)
        self.assertIn('approve by codex', markdown)
        self.assertEqual(json.loads((run.run_dir / 'reports' / 'report.json').read_text())['run_id'], run.run_id)
        self.assertEqual(git(repo, 'status', '--porcelain').stdout.count('\n'), 2)

    def test_unreproduced_symptom_blocks_with_resume(self):
        repo = self.make_repo()
        apply_fix(repo)
        git(repo, 'commit', '-qam', 'already fixed')
        self.assertEqual(reproduce(repo).stdout.strip(), '3')
        run = self.init(self.plan(repo))
        run.claim()
        out = run.record('block', {'code': 'operator', 'reason': 'symptom did not reproduce at HEAD; fix is unverified'})
        blocker = out['result']['blocker']
        self.assertEqual(run.status()['phase'], 'blocked')
        self.assertTrue(blocker['resume']['argv'][0] == 'python3' and 'unblock' in blocker['resume']['argv'])
