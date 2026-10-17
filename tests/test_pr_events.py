"""Compile and execute the shipped legacy event-diff program, without a watcher."""
import json
import os
import tempfile
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('jq'), 'jq required by the helper')
class EventDiffTest(unittest.TestCase):
    def test_new_and_removed_pull_requests_emit_events(self):
        path = Path(__file__).resolve().parents[1] / 'plugins/babysitter/scripts/pr-events.sh'
        program = path.read_text().split("<<'JQ' || true\n", 1)[1].split('\nJQ\n', 1)[0]
        pr = {'repo': 'fixture/repo', 'number': 3, 'url': 'https://github.com/fixture/repo/pull/3'}
        for old, new, expected in (([], [pr], 'NEW fixture/repo#3'), ([pr], [], 'GONE fixture/repo#3')):
            result = subprocess.run(['jq', '-nr', '--argjson', 'old', json.dumps(old),
                                     '--argjson', 'new', json.dumps(new), program],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(expected), result.stdout)


@unittest.skipUnless(shutil.which('jq'), 'jq required by the helper')
class PollBudgetTest(unittest.TestCase):
    """A 100-thread page per PR makes a 100-PR poll exceed GitHub's hourly GraphQL budget at 60 s."""

    def run_watch(self, *args):
        source = Path(__file__).resolve().parents[1] / 'plugins/babysitter/scripts/pr-events.sh'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pr-events.sh').write_text(source.read_text())
            stub = root / 'list-prs.sh'
            stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" >>"${0%/*}/argv.log"\n')
            for script in (stub, root / 'pr-events.sh'):
                script.chmod(0o755)
            result = subprocess.run(['bash', str(root / 'pr-events.sh'), *args, '--exit-when-empty'],
                                    capture_output=True, text=True, timeout=30,
                                    env={**os.environ, 'TMPDIR': tmp})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('END nothing eligible to watch', result.stdout)
            return (root / 'argv.log').read_text().split()

    def test_watch_caps_its_poll_at_50_prs_by_default(self):
        argv = self.run_watch('--repo', 'x/y', '--pr', '1')
        self.assertEqual(argv, ['--repo', 'x/y', '--pr', '1', '--limit', '50'])

    def test_explicit_limit_suppresses_the_default(self):
        argv = self.run_watch('--org', 'x', '--limit', '20')
        self.assertEqual(argv, ['--org', 'x', '--limit', '20'])
