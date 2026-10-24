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
        # An unchanged queued job emits no native event. GraphQL CheckRun has no
        # createdAt, so the clock comes from the Actions job API named in detailsUrl.
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
                     'conclusion': None, 'startedAt': None,
                     'detailsUrl': 'https://github.com/fixture/repo/actions/runs/39793710469/job/119875753605'},
                    {'__typename': 'CheckRun', 'name': 'lint', 'status': 'COMPLETED',
                     'conclusion': 'SUCCESS', 'startedAt': '2026-10-22T14:00:00Z',
                     'detailsUrl': 'https://github.com/fixture/repo/actions/runs/39793710469/job/1'},
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
url = next(arg for arg in args if arg.startswith('https://'))
if '/actions/jobs/' in url:
    assert url.endswith('/actions/jobs/119875753605'), url
    body = os.environ['FIXTURE_JOB_PAYLOAD']
else:
    body = os.environ['FIXTURE_PAYLOAD']
Path(args[args.index('-o') + 1]).write_text(body)
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
                     'FIXTURE_PAYLOAD': json.dumps(payload),
                     'FIXTURE_JOB_PAYLOAD': json.dumps({
                         'id': 119875753605, 'created_at': '2026-10-22T14:12:00Z',
                         'started_at': None, 'status': 'queued', 'name': 'Validate compose files'})},
                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row['failing'], [])
        self.assertEqual([c['name'] for c in row['pending_checks']], ['Validate compose files'])
        self.assertEqual(row['pending_checks'][0]['created_at'], '2026-10-22T14:12:00Z')
        self.assertEqual(row['pending_checks'][0]['queue_clock'], 'actions-job-api')
        self.assertIsNone(row['pending_checks'][0]['started_at'])
        self.assertEqual(row['queue_clock_gaps'], [])
        self.assertTrue(row['checks_complete'])
        self.assertFalse(row['required_contexts_known'])
        self.assertEqual(row['oldest_pending_check']['name'], 'Validate compose files')

    def test_unavailable_job_clock_is_an_explicit_gap(self):
        # A third-party check has no Actions job URL. The row must say the clock is
        # unknown rather than date the queue from the observation time.
        node = {
            'number': 7, 'title': 'Fixture', 'url': 'https://github.com/fixture/repo/pull/7',
            'state': 'OPEN', 'isDraft': False, 'isCrossRepository': False, 'mergeable': 'MERGEABLE',
            'mergeStateStatus': 'BLOCKED', 'author': {'login': 'fixture'},
            'headRefName': 'topic', 'baseRefName': 'main',
            'baseRef': {'target': {'oid': '1' * 40}},
            'repository': {'nameWithOwner': 'fixture/repo'},
            'commits': {'nodes': [{'commit': {'oid': '2' * 40, 'statusCheckRollup': {
                'state': 'PENDING', 'contexts': {'pageInfo': {'hasNextPage': False}, 'nodes': [
                    {'__typename': 'CheckRun', 'name': 'third-party', 'status': 'QUEUED',
                     'conclusion': None, 'startedAt': None,
                     'detailsUrl': 'https://ci.example.invalid/build/7'}]}}}}]},
            'comments': {'nodes': []}, 'reviews': {'nodes': []}, 'reviewDecision': 'APPROVED',
            'latestReviews': {'nodes': []},
            'reviewThreads': {'totalCount': 0, 'pageInfo': {'hasNextPage': False}, 'nodes': []},
        }
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'search': {'issueCount': 1, 'nodes': [node]}}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name, script in {
                'gh': '#!/bin/sh\nprintf fixture-token',
                'sleep': '#!/bin/sh\nexit 0',
                'curl': '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
assert '@-' in args
sys.stdin.read()
Path(args[args.index('-o') + 1]).write_text(os.environ['FIXTURE_PAYLOAD'])
print('200', end='')
''',
            }.items():
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
        self.assertIsNone(row['pending_checks'][0]['created_at'])
        self.assertEqual(row['queue_clock_gaps'][0]['name'], 'third-party')
        self.assertIn('detailsUrl', row['queue_clock_gaps'][0]['reason'])

    def test_single_pr_read_binds_required_status_contexts_without_claiming_completeness(self):
        # StatusContext.isRequired is a separate field from CheckRun.isRequired. A
        # failing required status context must not be reported as an empty required
        # set, and the observed subset must not be labelled the complete configured set.
        node = {
            'number': 12, 'title': 'Fixture', 'url': 'https://github.com/fixture/repo/pull/12',
            'state': 'OPEN', 'isDraft': False, 'isCrossRepository': False, 'mergeable': 'MERGEABLE',
            'mergeStateStatus': 'BLOCKED', 'author': {'login': 'fixture'},
            'headRefName': 'topic', 'baseRefName': 'main',
            'baseRef': {'target': {'oid': '1' * 40}},
            'repository': {'nameWithOwner': 'fixture/repo'},
            'commits': {'nodes': [{'commit': {'oid': '2' * 40, 'statusCheckRollup': {
                'state': 'FAILURE', 'contexts': {'pageInfo': {'hasNextPage': False}, 'nodes': [
                    {'__typename': 'StatusContext', 'context': 'required-ci', 'state': 'FAILURE',
                     'createdAt': '2026-10-22T14:00:00Z', 'isRequired': True},
                    {'__typename': 'CheckRun', 'name': 'optional-lint', 'status': 'COMPLETED',
                     'conclusion': 'FAILURE', 'startedAt': '2026-10-22T14:00:00Z',
                     'detailsUrl': None, 'isRequired': False},
                ]}}}}]},
            'comments': {'nodes': []}, 'reviews': {'nodes': []}, 'reviewDecision': 'APPROVED',
            'latestReviews': {'nodes': []},
            'reviewThreads': {'totalCount': 0, 'pageInfo': {'hasNextPage': False}, 'nodes': []},
        }
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'repository': {'pullRequest': node}}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name, script in {
                'gh': '#!/bin/sh\nprintf fixture-token',
                'sleep': '#!/bin/sh\nexit 0',
                'curl': '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
sys.stdin.read()
Path(args[args.index('-o') + 1]).write_text(os.environ['FIXTURE_PAYLOAD'])
print('200', end='')
''',
            }.items():
                path = directory / name
                path.write_text(script)
                path.chmod(0o755)
            result = subprocess.run(
                ['bash', str(ROOT / 'plugins/babysitter/scripts/list-prs.sh'),
                 '--repo', 'fixture/repo', '--pr', '12'],
                env={**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
                     'FIXTURE_PAYLOAD': json.dumps(payload)},
                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row['failing'], ['optional-lint', 'required-ci'])
        self.assertEqual(row['required_contexts'], ['required-ci'])
        self.assertEqual(row['required_contexts_observed'], ['required-ci'])
        self.assertFalse(row['required_contexts_known'])

    def test_fragment_requests_only_real_checkrun_fields(self):
        text = (ROOT / 'plugins/babysitter/scripts/list-prs.sh').read_text()
        check_run = text.split('... on CheckRun {', 1)[1].split('}', 1)[0]
        self.assertNotIn('createdAt', check_run)
        self.assertIn('detailsUrl', check_run)
        self.assertIn('startedAt', check_run)
        self.assertIn('contexts(first: 100)', text)
        self.assertIn('pageInfo { hasNextPage }', text)

    def test_incomplete_context_page_is_an_explicit_gap(self):
        node = {
            'number': 3, 'title': 'Fixture', 'url': 'https://github.com/fixture/repo/pull/3',
            'state': 'OPEN', 'isDraft': False, 'isCrossRepository': False, 'mergeable': 'MERGEABLE',
            'mergeStateStatus': 'CLEAN', 'author': {'login': 'fixture'},
            'headRefName': 'topic', 'baseRefName': 'main',
            'baseRef': {'target': {'oid': '1' * 40}},
            'repository': {'nameWithOwner': 'fixture/repo'},
            'commits': {'nodes': [{'commit': {'oid': '2' * 40, 'statusCheckRollup': {
                'state': 'SUCCESS', 'contexts': {
                    'totalCount': 200, 'pageInfo': {'hasNextPage': True}, 'nodes': [
                        {'__typename': 'CheckRun', 'name': 'ci', 'status': 'COMPLETED',
                         'conclusion': 'SUCCESS', 'startedAt': '2026-10-22T14:00:00Z',
                         'detailsUrl': None}]}}}}]},
            'comments': {'nodes': []}, 'reviews': {'nodes': []}, 'reviewDecision': 'APPROVED',
            'latestReviews': {'nodes': []},
            'reviewThreads': {'totalCount': 0, 'pageInfo': {'hasNextPage': False}, 'nodes': []},
        }
        payload = {'data': {'viewer': {'login': 'fixture'},
                            'search': {'issueCount': 1, 'nodes': [node]}}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name, script in {
                'gh': '#!/bin/sh\nprintf fixture-token',
                'sleep': '#!/bin/sh\nexit 0',
                'curl': '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
sys.stdin.read()
Path(args[args.index('-o') + 1]).write_text(os.environ['FIXTURE_PAYLOAD'])
print('200', end='')
''',
            }.items():
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
        self.assertFalse(row['checks_complete'])
        self.assertEqual(row['checks_total'], 200)
