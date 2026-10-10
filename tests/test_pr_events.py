"""Compile and execute the shipped legacy event-diff program, without a watcher."""
import json
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
