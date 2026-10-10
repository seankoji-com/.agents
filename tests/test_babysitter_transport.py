"""GitHub inventory transport keeps credentials out of process arguments."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('jq'), 'jq required by the shipped helper')
class InventoryTransportTest(unittest.TestCase):
    def test_inventory_reads_authorization_from_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name, body in {
                'gh': '#!/bin/sh\nprintf fixture-token',
                'sleep': '#!/bin/sh\nexit 0',
                'curl': '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
assert not any('fixture-token' in arg for arg in args)
assert '@-' in args
assert sys.stdin.read().strip() == 'Authorization: bearer fixture-token'
payload = {'data': {'viewer': {'login': 'fixture'}, 'search': {'nodes': [], 'issueCount': 0}}}
Path(args[args.index('-o') + 1]).write_text(json.dumps(payload))
print('200', end='')
''',
            }.items():
                path = directory / name
                path.write_text(body)
                path.chmod(0o755)
            result = subprocess.run(
                ['bash', str(ROOT / 'plugins/babysitter/scripts/list-prs.sh'), '--repo', 'fixture/repo'],
                env={**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH']},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
