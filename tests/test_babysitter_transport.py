"""GitHub inventory transport keeps credentials out of process arguments."""
import json
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

    def test_queued_check_exposes_its_creation_clock(self):
        # An unchanged queued job emits no native event; only createdAt proves age.
        node = {
            'number': 3380, 'title': 'Fixture', 'url': 'https://github.com/fixture/repo/pull/3380',
            'state': 'OPEN', 'isDraft': False, 'isCrossRepository': False, 'mergeable': 'MERGEABLE',
            'mergeStateStatus': 'BLOCKED', 'author': {'login': 'fixture'},
            'headRefName': 'topic', 'baseRefName': 'main',
            'baseRef': {'target': {'oid': '1' * 40}},
            'repository': {'nameWithOwner': 'fixture/repo'},
            'commits': {'nodes': [{'commit': {'oid': '2' * 40, 'statusCheckRollup': {
                'state': 'PENDING', 'contexts': {'nodes': [
                    {'__typename': 'CheckRun', 'name': 'Validate compose files', 'status': 'QUEUED',
                     'conclusion': None, 'startedAt': None, 'createdAt': '2026-10-22T14:12:00Z'},
                    {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED',
                     'conclusion': 'SUCCESS', 'startedAt': '2026-10-22T14:00:00Z',
                     'createdAt': '2026-10-22T13:59:00Z'},
                ]}}}}]},
            'comments': {'nodes': []}, 'reviews': {'nodes': []}, 'reviewDecision': 'APPROVED',
            'latestReviews': {'nodes': []},
            'reviewThreads': {'totalCount': 0, 'pageInfo': {'hasNextPage': False}, 'nodes': []},
        }
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'search': {'issueCount': 1, 'nodes': [node]}}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            body = {
                'gh': '#!/bin/sh\nprintf fixture-token',
                'sleep': '#!/bin/sh\nexit 0',
                'curl': '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
assert not any('fixture-token' in arg for arg in args)
assert '@-' in args
assert sys.stdin.read().strip() == 'Authorization: bearer fixture-token'
Path(args[args.index('-o') + 1]).write_text(os.environ['FIXTURE_PAYLOAD'])
print('200', end='')
''',
            }
            for name, script in body.items():
                path = directory / name
                path.write_text(script)
                path.chmod(0o755)
            result = subprocess.run(
                ['bash', str(ROOT / 'plugins/babysitter/scripts/list-prs.sh'), '--repo', 'fixture/repo'],
                env={**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
                     'FIXTURE_PAYLOAD': json.dumps(payload)},
                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row['failing'], [])
        self.assertEqual([c['name'] for c in row['pending_checks']], ['Validate compose files'])
        self.assertEqual(row['pending_checks'][0]['created_at'], '2026-10-22T14:12:00Z')
        self.assertIsNone(row['pending_checks'][0]['started_at'])
        self.assertEqual(row['oldest_pending_check']['name'], 'Validate compose files')
