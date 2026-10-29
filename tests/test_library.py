"""Synthetic library/helper contracts. No provider or network access."""
import importlib.util
from importlib.machinery import SourceFileLoader
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    loader = SourceFileLoader(Path(relative).stem, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load('scripts/check_library.py')
timings = load('skills/test-writer/scripts/summarize_timings.py')
scanner = load('skills/agent-tuneup/scripts/scan_config.py')
waiter = load('skills/babysitter/scripts/pr-wait')


class Helpers(unittest.TestCase):
    def test_timing_includes_failures_and_nearest_rank(self):
        rows = [{'seconds': n, 'outcome': 'failed' if n == 20 else 'passed'}
                for n in range(1, 21)]
        result = timings.summarize(rows)
        self.assertEqual(result['p50_seconds'], 10)
        self.assertEqual(result['p95_seconds'], 19)
        self.assertEqual(result['runner_seconds'], 210)
        self.assertEqual(result['outcomes'], {'failed': 1, 'passed': 19})

    def test_invalid_observations_rejected(self):
        for rows in ([], {}, [None], [{'seconds': True, 'outcome': 'passed'}],
                     [{'seconds': -1, 'outcome': 'passed'}],
                     [{'seconds': float('nan'), 'outcome': 'passed'}],
                     [{'seconds': float('inf'), 'outcome': 'passed'}],
                     [{'seconds': 2}], [{'seconds': 2, 'outcome': []}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                timings.summarize(rows)

    def test_config_flags_without_values_and_escapes_pointers(self):
        result = scanner.scan({'permissions': {'allow': ['tool:*', 'tool:read'],
                                               'a/b~c': '*'},
                               'token': 'synthetic-private-value', 'other': '*'})
        self.assertEqual(result['leaves'], 5)
        self.assertEqual(result['broad_permission_pointers'],
                         ['/permissions/allow/0', '/permissions/a~1b~0c'])
        self.assertNotIn('synthetic-private-value', json.dumps(result))

    def test_copied_skill_helpers_run_from_foreign_cwd(self):
        # Copy entire independent skill folders, without repository/runtime support.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foreign = root / 'foreign'
            foreign.mkdir()
            for name, helper, data, expected in (
                ('test-writer', 'summarize_timings.py',
                 [{'seconds': 3, 'outcome': 'failed'}], 'runner_seconds'),
                ('agent-tuneup', 'scan_config.py', {'allow': ['*']},
                 'broad_permission_pointers')):
                copied = root / name
                shutil.copytree(ROOT / 'skills' / name, copied,
                                ignore=shutil.ignore_patterns('__pycache__'))
                source = foreign / 'input.json'
                source.write_text(json.dumps(data))
                result = subprocess.run([sys.executable, str(copied / 'scripts' / helper),
                                         str(source)], cwd=foreign, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, json.loads(result.stdout))
                source.write_text('invalid secret-like text')
                failed = subprocess.run([sys.executable, str(copied / 'scripts' / helper),
                                         str(source)], cwd=foreign, capture_output=True, text=True)
                self.assertEqual(failed.returncode, 2)
                self.assertNotIn('secret-like', failed.stderr)


class Watcher(unittest.TestCase):
    @contextmanager
    def fixture(self, checks=None, merge_state='CLEAN', unresolved=False, review=False):
        pr = {'state': 'OPEN', 'headRefOid': 'a' * 40, 'baseRefName': 'main',
              'baseRef': {'target': {'oid': 'b' * 40}},
              'author': {'login': 'author'}, 'viewer': 'owner',
              'comments': {'nodes': []}, 'reviews': {'nodes': []},
              'reviewThreads': {'nodes': []}, 'mergeStateStatus': merge_state}
        if unresolved:
            pr['reviewThreads']['nodes'].append({
                'isResolved': False, 'path': 'app.py', 'line': 1,
                'comments': {'nodes': [{'id': 'finding', 'url': 'https://example.invalid/review',
                                       'body': 'A real finding', 'author': {'login': 'reviewer'}}]}})
        if review:
            pr['reviews']['nodes'].append({
                'id': 'review', 'url': 'https://example.invalid/review',
                'state': 'APPROVED', 'body': 'Review completed',
                'commit': {'oid': 'c' * 40},
                'author': {'login': 'greptile[bot]', '__typename': 'Bot'}})
        if checks is None:
            checks = {'gate': {'bucket': 'pass', 'link': 'https://example.invalid/check'}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(waiter, 'STATE_DIR', Path(tmp)), \
                mock.patch.object(waiter, 'required_checks', return_value={'gate'}), \
                mock.patch.object(waiter, 'gh', side_effect=AssertionError('network forbidden')), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            watcher = waiter.Watcher('example/repo', 1, 'ready', 20)
            watcher.fetch_pr = mock.Mock(return_value=pr)
            watcher.fetch_checks = mock.Mock(return_value=checks)
            watcher.behind = mock.Mock(return_value='')
            yield watcher, pr

    def test_ready_without_optional_review_bots(self):
        with self.fixture() as (watcher, _):
            watcher.poll()
            watcher.baseline = False
            with self.assertRaises(SystemExit) as done:
                watcher.poll()
            self.assertEqual(done.exception.code, 0)

    def test_missing_required_check_and_blocked_merge_stay_pending(self):
        for kwargs in ({'checks': {}}, {'merge_state': 'BLOCKED'}, {'merge_state': 'UNKNOWN'}):
            with self.subTest(kwargs=kwargs), self.fixture(**kwargs) as (watcher, _):
                watcher.poll()
                watcher.baseline = False
                watcher.poll()

    def test_failed_required_check_needs_action(self):
        checks = {'gate': {'bucket': 'fail', 'link': 'https://example.invalid/check'}}
        with self.fixture(checks=checks) as (watcher, _):
            with self.assertRaises(SystemExit) as stopped:
                watcher.poll()
            self.assertEqual(stopped.exception.code, 1)

    def test_unresolved_thread_blocks_readiness(self):
        with self.fixture(unresolved=True) as (watcher, _):
            watcher.poll()
            watcher.baseline = False
            with self.assertRaises(SystemExit) as stopped:
                watcher.poll()
            self.assertEqual(stopped.exception.code, 1)

    def test_observed_review_bot_must_review_current_head(self):
        with self.fixture(review=True) as (watcher, pr):
            watcher.poll()
            watcher.baseline = False
            watcher.poll()
            pr['reviews']['nodes'][0]['commit']['oid'] = pr['headRefOid']
            with self.assertRaises(SystemExit) as done:
                watcher.poll()
            self.assertEqual(done.exception.code, 0)

    def test_copied_watcher_runs_from_foreign_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copied = root / 'babysitter'
            shutil.copytree(ROOT / 'skills/babysitter', copied,
                            ignore=shutil.ignore_patterns('__pycache__'))
            result = subprocess.run([sys.executable, str(copied / 'scripts/pr-wait'), '--help'],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--until', result.stdout)

    def test_fetch_checks_uses_cli_fields_and_worst_duplicate(self):
        rows = [{'name': 'gate', 'bucket': 'pass', 'link': 'pass-link', 'description': 'ok'},
                {'name': 'gate', 'bucket': 'fail', 'link': 'fail-link', 'description': 'failed'}]
        with self.fixture() as (watcher, _), mock.patch.object(
                waiter, 'gh', return_value=subprocess.CompletedProcess([], 1, json.dumps(rows), '')) as gh:
            result = waiter.Watcher.fetch_checks(watcher)
            self.assertEqual(result['gate']['bucket'], 'fail')
            self.assertEqual(result['gate']['link'], 'fail-link')
            args = gh.call_args.args[0]
            self.assertEqual(set(args[args.index('--json') + 1].split(',')),
                             {'name', 'bucket', 'link', 'description'})

    def test_invalid_check_payload_needs_action(self):
        for payload in ('not JSON', '{}', '[{}]', '[{"name":"gate","bucket":"unknown"}]'):
            with self.subTest(payload=payload), self.fixture() as (watcher, _), mock.patch.object(
                    waiter, 'gh', return_value=subprocess.CompletedProcess([], 0, payload, '')):
                with self.assertRaises(waiter.GhError):
                    waiter.Watcher.fetch_checks(watcher)

    def test_fetch_pr_handles_lost_access_invalid_json_and_truncated_history(self):
        with self.fixture() as (watcher, pr):
            payload = {'data': {'repository': {'pullRequest': pr}, 'viewer': {'login': 'owner'}}}
            with mock.patch.object(waiter, 'gh', return_value=subprocess.CompletedProcess(
                    [], 0, json.dumps(payload), '')):
                self.assertEqual(waiter.Watcher.fetch_pr(watcher)['headRefOid'], 'a' * 40)
            pr['reviewThreads']['pageInfo'] = {'hasPreviousPage': True}
            cases = ('not JSON', 'null', '{"data":{"repository":null}}',
                     '{"errors":[{"message":"access denied"}]}', json.dumps(payload))
            for body in cases:
                with self.subTest(body=body), mock.patch.object(waiter, 'gh', return_value=(
                        subprocess.CompletedProcess([], 0, body, ''))):
                    with self.assertRaises(waiter.GhError):
                        waiter.Watcher.fetch_pr(watcher)

    def test_required_check_branch_is_url_encoded(self):
        with mock.patch.object(waiter, 'gh_lines', side_effect=[['gate'], []]) as gh:
            self.assertEqual(waiter.required_checks('example/repo', 'release/a#b?c%'), {'gate'})
            paths = [call.args[0][1] for call in gh.call_args_list]
            self.assertTrue(all('release%2Fa%23b%3Fc%25' in path for path in paths))

    def test_embedded_sha_in_stale_summary_does_not_mark_review_complete(self):
        with self.fixture(review=True) as (watcher, pr):
            summary = {'id': 'summary', 'url': 'https://example.invalid/review',
                       'body': '0' + pr['headRefOid'][:7] + '0',
                       'author': {'login': 'greptile[bot]', '__typename': 'Bot'}}
            pr['comments']['nodes'].append(summary)
            watcher.poll()
            watcher.baseline = False
            watcher.poll()
            summary['body'] = 'Reviewed commit ' + pr['headRefOid']
            with self.assertRaises(SystemExit) as done:
                watcher.poll()
            self.assertEqual(done.exception.code, 0)


class Library(unittest.TestCase):
    def fixture(self, root):
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        for name in checker.SKILLS:
            shutil.copytree(ROOT / 'skills' / name, root / 'skills' / name,
                            ignore=shutil.ignore_patterns('__pycache__'))
        subprocess.run(['git', '-C', str(root), 'add', 'skills'], check=True)

    def test_library_and_independent_folders(self):
        self.assertEqual(checker.check(ROOT), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            self.assertEqual(checker.check(root), [])

    def test_missing_skill_bad_metadata_retired_dependency_and_broken_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'skills/plan/SKILL.md').unlink()
            p = root / 'skills/imps/SKILL.md'
            p.write_text(p.read_text().replace('name: imps', 'name: wrong') +
                         '\n[missing](missing.md)\nPKG/shared/contract.md\n')
            errors = '\n'.join(checker.check(root))
            for expected in ('missing skill: plan', 'mismatched name',
                             'retired dependency', 'broken/escaping link'):
                self.assertIn(expected, errors)

    def test_external_import_rejected_and_vendor_state_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            vendor = root / 'skills/synced'
            vendor.mkdir()
            (vendor / 'SKILL.md').write_text('PKG/shared/private.md')
            self.assertEqual(checker.check(root), [])
            folder = root / 'skills/imps/scripts'
            folder.mkdir()
            for name in ('bad.py', 'bad-script'):
                with self.subTest(name=name):
                    p = folder / name
                    p.write_text('#!/usr/bin/env python3\nimport external_provider_sdk\n')
                    self.assertIn('non-stdlib import', '\n'.join(checker.check(root)))
                    p.unlink()

    def test_metadata_without_instructions_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            p = root / 'skills/bro/SKILL.md'
            p.write_text('---\nname: bro\ndescription: Restate text.\n---\n')
            self.assertIn('bro: missing instructions', checker.check(root))

    def test_retired_tracked_container_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            retired = root / 'core'
            retired.mkdir()
            (retired / 'engine.py').write_text('pass\n')
            subprocess.run(['git', '-C', str(root), 'add', 'core/engine.py'], check=True)
            self.assertIn('retired source container', '\n'.join(checker.check(root)))


if __name__ == '__main__':
    unittest.main()
