"""Reference-repo sync and t3.json shape, using a local bare repository and no network."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT, git

SYNC = ROOT / 'scripts' / 'sync_reference_repos.py'
T3_SCRIPT_KEYS = {'name', 'command', 'icon', 'runOnWorktreeCreate', 'async', 'runOnSettle', 'previewUrl',
                  'autoOpenPreview'}
T3_ICONS = {'play', 'test', 'lint', 'configure', 'build', 'debug'}


class SyncReferenceReposTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        work = self.tmp / 'work'
        work.mkdir()
        git(work, 'init', '-q', '-b', 'main')
        self.first = self.commit(work, 'one')
        self.second = self.commit(work, 'two')
        self.upstream = self.tmp / 'upstream.git'
        git(self.tmp, 'clone', '-q', '--bare', str(work), str(self.upstream))
        self.root = self.tmp / '.repos'

    def commit(self, work, text):
        (work / 'file.txt').write_text(text)
        git(work, 'add', '-A')
        git(work, 'commit', '-q', '-m', text)
        return git(work, 'rev-parse', 'HEAD').stdout.strip()

    def config(self, ref, name='ref'):
        path = self.tmp / 'repos.json'
        path.write_text(json.dumps({'repos': [{'name': name, 'url': self.upstream.as_uri(), 'ref': ref}]}))
        return path

    def sync(self, config, *extra, expected=0):
        result = subprocess.run([sys.executable, str(SYNC), '--config', str(config), '--root', str(self.root),
                                 *extra], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def head(self):
        return git(self.root / 'ref', 'rev-parse', 'HEAD').stdout.strip()

    def test_clones_at_the_recorded_ref_then_refreshes_to_a_new_one(self):
        self.sync(self.config(self.first))
        self.assertEqual(self.head(), self.first)
        self.assertEqual((self.root / 'ref' / 'file.txt').read_text(), 'one')
        self.assertEqual(git(self.root / 'ref', 'rev-list', '--count', 'HEAD').stdout.strip(), '1')  # shallow
        self.sync(self.config(self.second))
        self.assertEqual(self.head(), self.second)
        self.assertEqual((self.root / 'ref' / 'file.txt').read_text(), 'two')

    def test_resyncing_the_same_ref_is_a_no_op(self):
        config = self.config(self.first)
        self.sync(config)
        self.assertIn('refreshed ref', self.sync(config).stdout)
        self.assertEqual(self.head(), self.first)

    def test_a_branch_ref_resolves_to_its_tip(self):
        self.sync(self.config('main'))
        self.assertEqual(self.head(), self.second)

    def test_local_changes_are_kept_and_reported(self):
        config = self.config(self.first)
        self.sync(config)
        (self.root / 'ref' / 'file.txt').write_text('edited')
        result = self.sync(self.config(self.second), expected=1)
        self.assertIn('local changes', result.stderr)
        self.assertEqual((self.root / 'ref' / 'file.txt').read_text(), 'edited')

    def test_a_missing_ref_fails_without_touching_the_checkout(self):
        self.sync(self.config(self.first))
        result = self.sync(self.config('f' * 40), expected=1)
        self.assertIn('git fetch failed', result.stderr)
        self.assertEqual(self.head(), self.first)

    def test_unsafe_names_and_unknown_selection_are_rejected(self):
        for name in ('../escape', 'a/b', '.', '-x', ''):
            result = self.sync(self.config(self.first, name=name), expected=2)
            self.assertIn('error:', result.stderr)
        self.assertFalse(self.root.exists())
        self.assertIn('not in', self.sync(self.config(self.first), 'nope', expected=2).stderr)

    def test_a_non_checkout_directory_is_never_overwritten(self):
        (self.root / 'ref').mkdir(parents=True)
        (self.root / 'ref' / 'keep.txt').write_text('mine')
        result = self.sync(self.config(self.first), expected=1)
        self.assertIn('not a git checkout', result.stderr)
        self.assertEqual((self.root / 'ref' / 'keep.txt').read_text(), 'mine')


class RepositoryConfigTest(unittest.TestCase):
    def test_shipped_reference_pins_a_full_sha_and_is_gitignored(self):
        repos = json.loads((ROOT / 'scripts' / 'reference_repos.json').read_text())['repos']
        self.assertEqual([r['name'] for r in repos], ['t3code'])
        self.assertEqual(repos[0]['url'], 'https://github.com/pingdotgg/t3code.git')
        self.assertRegex(repos[0]['ref'], r'^[0-9a-f]{40}$')
        self.assertIn('.repos/', (ROOT / '.gitignore').read_text().splitlines())

    def test_t3_json_uses_only_known_script_fields(self):
        data = json.loads((ROOT / 't3.json').read_text())
        self.assertEqual(data['$schema'], 'https://t3.codes/schema/t3.json')
        scripts = {s['name']: s for s in data['scripts']}
        self.assertEqual(list(scripts), ['Tests', 'Docs check', 'Docs preview'])
        for script in scripts.values():
            self.assertLessEqual(set(script), T3_SCRIPT_KEYS)
            self.assertIn(script['icon'], T3_ICONS)
            self.assertNotIn('runOnWorktreeCreate', script)  # stdlib runtime: nothing to install
        self.assertEqual(scripts['Tests']['command'], 'python3 scripts/run_tests.py')
        self.assertEqual(scripts['Docs check']['command'], 'python3 scripts/check_docs.py')
        preview = scripts['Docs preview']
        self.assertIn('mkdocs serve -a 127.0.0.1:8000', preview['command'])
        self.assertIn('requirements-docs.txt', preview['command'])
        self.assertEqual(preview['previewUrl'], 'http://127.0.0.1:8000/t3-plugins/')
        self.assertIs(preview['autoOpenPreview'], True)


if __name__ == '__main__':
    unittest.main()
