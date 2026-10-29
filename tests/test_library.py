"""Synthetic library/helper contracts. No provider or network access."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load('scripts/check_library.py')
timings = load('skills/test-writer/scripts/summarize_timings.py')
scanner = load('skills/agent-tuneup/scripts/scan_config.py')


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
            p = root / 'skills/imps/scripts/bad.py'
            p.parent.mkdir()
            p.write_text('import external_provider_sdk\n')
            self.assertIn('non-stdlib import', '\n'.join(checker.check(root)))

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
