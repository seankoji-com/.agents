"""Source-spec case 14: a direct bug fix reproduces red, fixes the defect, passes
the original reproduction and produces a valid report."""
import json
import subprocess
import sys

from support import CoreTestCase, cli, git

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


class DirectBugFixTest(CoreTestCase):
    def test_direct_bugfix_red_fix_green_report(self):
        repo = self.make_repo()
        self.assertEqual(reproduce(repo).stdout.strip(), '2', 'defect reproduces before edits')
        run = self.init(self.plan(repo))
        apply_fix(repo)
        self.run_check(run)
        binding = run.binding()
        green = reproduce(repo)
        self.assertEqual(green.stdout.strip(), '3')
        log = run.scratch('green.log', green.stdout + green.stderr)
        run.submit('evidence', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                               'explanation': 'original reproduction prints 3', 'artifacts': [str(log)], 'binding': binding})
        self.assertEqual(run.validate()['outcome'], 'completed')
        code, env, _ = cli('report', *run.args())
        self.assertEqual(code, 0, env)
        report = env['data']['report']
        self.assertEqual(report['readiness']['status'], 'ready')
        self.assertEqual(report['readiness']['requirements'][0]['status'], 'passed')
        self.assertIn('REQ-MULTILINE', (run.run_dir/'reports/report.md').read_text())
        self.assertEqual(json.loads((run.run_dir/'reports/report.json').read_text())['run_id'], run.run_id)
        self.assertEqual(git(repo, 'status', '--porcelain').stdout.count('\n'), 2)

    def test_unreproduced_symptom_remains_unverified(self):
        repo = self.make_repo()
        apply_fix(repo)
        git(repo, 'commit', '-qam', 'already fixed')
        self.assertEqual(reproduce(repo).stdout.strip(), '3')
        run = self.init(self.plan(repo))
        run.submit('note', {'text': 'symptom did not reproduce at HEAD; fix is unverified'})
        self.assertFalse(run.validate()['ready'])
        self.assertEqual(run.validate()['requirements'][0]['status'], 'unverified')
