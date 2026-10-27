"""scripts/conformance.py end to end: fixture setup, run lookup, evidence collection,
and the generated compatibility page. No model or provider runs; the installed core
is a stub that prints a fixed report."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('conformance_flows', ROOT / 'scripts' / 'conformance.py')
conformance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conformance)

REPORT = {'outcome': 'completed', 'blocker': None, 'reviews': [{'verdict': 'passed'}],
          'review': {'status': 'passed'}, 'requirements': [{'status': 'passed'}]}


def run_state(run_id, worktree, created_at='2026-10-09T13:00:00Z'):
    return {'run_id': run_id, 'phase': 'done', 'created_at': created_at,
            'repo': {'worktree': str(worktree), 'base_sha': 'abc123'},
            'plugin': {'version': '9.9.9'}, 'budget': {'spent_seconds': 42},
            'tasks': [{'id': 'fix', 'kind': 'code', 'status': 'integrated', 'result': {'artifact': 'results/fix.json'},
                       'rounds': [{'task_id': 'host-1'}]}],
            'events': []}


def call(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        conformance.main(list(argv))
    return json.loads(out.getvalue())


class ConformanceFlowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.state_root = self.tmp / 'state'
        # A global hooksPath or commit.gpgsign must not break the fixture commits.
        env = patch.dict(os.environ, {'AGENTS_STATE_ROOT': str(self.state_root), 'GIT_CONFIG_NOSYSTEM': '1',
                                      'GIT_CONFIG_GLOBAL': os.devnull})
        env.start()
        self.addCleanup(env.stop)

    def add_run(self, run_id, worktree, **kwargs):
        run_dir = self.state_root / 'runs' / run_id
        (run_dir / 'reports').mkdir(parents=True)
        (run_dir / 'run.json').write_text(json.dumps(run_state(run_id, worktree, **kwargs)))
        return run_dir

    def test_compile_reproduces_the_committed_compatibility_page(self):
        sandbox = self.tmp / 'conformance'
        sandbox.mkdir()
        shutil.copy(ROOT / 'conformance' / 'compatibility.json', sandbox)
        with patch.object(conformance, 'CONFORMANCE', sandbox):
            call('compile')
        self.assertEqual((sandbox / 'compatibility.md').read_text(),
                         (ROOT / 'conformance' / 'compatibility.md').read_text(),
                         'compatibility.md is stale: run python3 scripts/conformance.py compile')

    def test_setup_builds_one_branch_per_case_and_refuses_an_existing_directory(self):
        dest = self.tmp / 'fixture'
        receipt = call('setup', '--dest', str(dest))
        cases = conformance.CASES['cases']
        self.assertEqual(sorted(receipt['branches']), sorted(c['branch'] for c in cases.values()))
        for case in cases.values():
            policy = subprocess.run(['git', '-C', str(dest), 'show', f'{case["branch"]}:.agents/imps.json'],
                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(json.loads(policy)['policy']['model_preferences'], conformance.CASES['model_preferences'])
        branch = subprocess.run(['git', '-C', str(dest), 'branch', '--show-current'],
                                capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(branch, 'main')
        with self.assertRaises(SystemExit) as caught:
            call('setup', '--dest', str(dest))
        self.assertIn('exists', str(caught.exception))

    def test_find_run_matches_the_worktree_and_since(self):
        mine, other = self.tmp / 'mine', self.tmp / 'other'
        mine.mkdir()
        other.mkdir()
        self.add_run('run-old', mine, created_at='2026-10-01T00:00:00Z')
        self.add_run('run-new', mine, created_at='2026-10-09T00:00:00Z')
        self.add_run('run-elsewhere', other)
        found = call('find-run', '--worktree', str(mine))
        self.assertEqual([r['run_id'] for r in found], ['run-new', 'run-old'])
        self.assertEqual(found[0]['tasks'], [{'id': 'fix', 'status': 'integrated', 'host_task_ids': ['host-1']}])
        found = call('find-run', '--worktree', str(mine), '--since', '2026-10-05')
        self.assertEqual([r['run_id'] for r in found], ['run-new'])

    def test_collect_writes_sanitised_graded_evidence_once(self):
        run_dir = self.add_run('run-0001', self.tmp / 'repo')
        (run_dir / 'reports' / 'report.md').write_text(f'Artifacts: `{self.state_root}/runs/run-0001/artifacts`\n')
        (run_dir / 'artifacts' / 'results').mkdir(parents=True)
        (run_dir / 'artifacts' / 'results' / 'fix.json').write_text('{"summary": "fixed"}')
        prefix = self.tmp / 'prefix'
        stub = prefix / 'imps' / 'current' / 'core' / 'cli.py'
        stub.parent.mkdir(parents=True)
        report = {**REPORT, 'evidence_dir': f'{self.state_root}/runs/run-0001/artifacts'}
        stub.write_text(f'print({json.dumps(json.dumps({"ok": True, "data": {"report": report}}))})\n')
        transcript = self.tmp / 'transcript.md'
        transcript.write_text(f'state root {self.state_root}\n')
        repo = self.tmp / 'checkout'
        argv = ['collect', '--run-id', 'run-0001', '--provider', 'provider-a', '--model', 'model-a', '--case', 'bugfix',
                '--repeat', '1', '--t3-version', '1.2.3', '--thread-id', 'thread-1', '--transcript', str(transcript),
                '--elapsed', '12.5', '--note', 'clean run']
        with patch.dict(os.environ, {'AGENTS_PREFIX': str(prefix)}), \
                patch.object(conformance, 'TEMP', str(self.tmp)), \
                patch.object(conformance, 'ROOT', repo), \
                patch.object(conformance, 'CONFORMANCE', repo / 'conformance'):
            record = call(*argv)
            target = repo / 'conformance' / 'results' / '1.2.3' / 'provider-a' / 'bugfix' / '1'
            self.assertEqual(record['artifacts'], 'conformance/results/1.2.3/provider-a/bugfix/1')
            self.assertTrue(record['grade']['passed'], record['grade'])
            self.assertEqual((record['plugin_version'], record['starting_revision']), ('9.9.9', 'abc123'))
            for name in ('report.json', 'report.md', 'result.json', 'transcript.md'):
                text = (target / name).read_text()
                self.assertNotIn(str(self.tmp), text, name)
            self.assertIn('$TMPDIR/state/runs/run-0001/artifacts', (target / 'report.md').read_text())
            self.assertEqual(json.loads((target / 'result.json').read_text()), {'fix.json': {'summary': 'fixed'}})
            self.assertIsNone(json.loads((target / 'usage.json').read_text())['tokens'])
            with self.assertRaises(SystemExit) as caught:
                call(*argv)
            self.assertIn('never overwritten', str(caught.exception))

    def test_collect_reports_a_missing_install_and_a_failing_report(self):
        self.add_run('run-0002', self.tmp / 'repo')
        argv = ['collect', '--run-id', 'run-0002', '--provider', 'p', '--model', 'm', '--case', 'bugfix',
                '--repeat', '1', '--t3-version', '1', '--thread-id', 't']
        prefix = self.tmp / 'prefix'
        with patch.dict(os.environ, {'AGENTS_PREFIX': str(prefix)}):
            with self.assertRaises(SystemExit) as caught:
                call(*argv)
            self.assertIn('no installed imps core', str(caught.exception))
            stub = prefix / 'imps' / 'current' / 'core' / 'cli.py'
            stub.parent.mkdir(parents=True)
            stub.write_text('import json, sys\nprint(json.dumps({"ok": False, "error": {"code": "no_run"}}))\nsys.exit(2)\n')
            with self.assertRaises(SystemExit) as caught:
                call(*argv)
            self.assertIn('report failed (2)', str(caught.exception))
            stub.write_text('import sys\nsys.stderr.write("Traceback: boom")\nsys.exit(5)\n')
            with self.assertRaises(SystemExit) as caught:
                call(*argv)
            self.assertIn('boom', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
