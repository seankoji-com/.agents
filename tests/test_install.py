"""REQ-INSTALL and source-spec case 13 (install half): idempotent, standalone and
reversible installation that never touches run state or unrelated files."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from support import ROOT, CoreTestCase


def tree_digest(root: Path) -> dict:
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'dir'
            for p in sorted(root.rglob('*'))}


class InstallTest(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.source = self.tmp / 'src'
        for part in ('core', 'plugins', 'scripts'):
            shutil.copytree(ROOT / part, self.source / part, ignore=shutil.ignore_patterns('__pycache__'))
        self.env = dict(os.environ, HOME=str(self.home))
        self.env.pop('T3_PLUGINS_PREFIX', None)
        self.env.pop('T3_PLUGINS_STATE_ROOT', None)
        self.env.pop('XDG_STATE_HOME', None)
        self.prefix = self.home / '.local' / 'share' / 't3-plugins'
        self.state = self.home / '.local' / 'state' / 't3-plugins'

    def installer(self, *args, expect=0, source=None):
        script = (source or self.source) / 'scripts' / 'install.py'
        result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def installed_cli(self, *args):
        cli = self.prefix / 'imps' / 'current' / 'core' / 'cli.py'
        result = subprocess.run([sys.executable, str(cli), *map(str, args)], capture_output=True, text=True, env=self.env,
                                cwd=self.tmp)
        return result.returncode, json.loads(result.stdout)

    def test_install_lifecycle(self):
        # 1. dry run writes nothing
        before = tree_digest(self.home)
        out = self.installer('--dry-run')
        self.assertTrue(out['data']['dry_run'])
        self.assertEqual(tree_digest(self.home), before)

        # 2. two installs of the same version leave an identical manifest
        first = self.installer()['data']
        version_dir = Path(first['version_dir'])
        manifest = (version_dir / 'install-manifest.json').read_bytes()
        second = self.installer()['data']
        self.assertEqual(second['action'], 'already_installed')
        self.assertEqual((version_dir / 'install-manifest.json').read_bytes(), manifest)

        # 3 and 4. current points at the version dir and entry.md resolves through it
        current = self.prefix / 'imps' / 'current'
        self.assertTrue(current.is_symlink())
        self.assertEqual(current.resolve(), version_dir.resolve())
        entry = Path(first['entry'])
        self.assertEqual(entry, current / 'entry.md')
        self.assertTrue(entry.resolve().is_file())
        self.assertIn(str(entry), first['paste'])

        # 5. with the source checkout renamed away, the installed core still runs
        repo = self.make_repo()
        plan = self.plan(repo)
        moved = self.tmp / 'src-moved'
        self.source.rename(moved)
        code, env = self.installed_cli('init', '--json', json.dumps(plan))
        self.assertEqual(code, 0, env)
        run_id = env['run_id']
        self.assertTrue(env['data']['state_root'].startswith(str(self.state)), 'default state root under ~/.local/state')
        code, env = self.installed_cli('status', '--run-id', run_id)
        self.assertEqual(code, 0, env)
        self.assertEqual(env['data']['plugin']['entry'], str(current / 'entry.md'))
        self.assertEqual(env['data']['plugin']['version'], first['version'], 'runs record the installed version label')
        moved.rename(self.source)

        # 6. a locally modified owned file makes install refuse without --force
        (version_dir / 'entry.md').write_text('edited by hand\n')
        out = self.installer(expect=4)
        self.assertEqual(out['error']['code'], 'locally_modified')
        self.assertEqual((version_dir / 'entry.md').read_text(), 'edited by hand\n')
        self.installer('--force')
        self.assertNotEqual((version_dir / 'entry.md').read_text(), 'edited by hand\n')

        # 7 and 8. uninstall removes only owned files; state and unrelated files survive
        unrelated = self.prefix / 'imps' / 'my-notes.txt'
        unrelated.write_text('mine')
        other_plugin = self.prefix / 'someone-else' / 'keep.md'
        other_plugin.parent.mkdir(parents=True)
        other_plugin.write_text('keep')
        state_before = tree_digest(self.state)
        self.assertTrue(state_before, 'the init above created run state')
        self.installer('--uninstall')
        self.assertFalse(version_dir.exists())
        self.assertFalse(current.is_symlink())
        self.assertEqual(unrelated.read_text(), 'mine')
        self.assertEqual(other_plugin.read_text(), 'keep')
        self.assertEqual(tree_digest(self.state), state_before)

    def test_new_version_and_rollback(self):
        first = self.installer()['data']
        (self.source / 'plugins' / 'imps' / 'references' / 'extra-note.md').write_text('a change\n')
        second = self.installer()['data']
        self.assertNotEqual(first['version'], second['version'])
        current = self.prefix / 'imps' / 'current'
        self.assertEqual(os.readlink(current), second['version'])
        self.installer('--activate', first['version'])
        self.assertEqual(os.readlink(current), first['version'])
        self.assertTrue((Path(first['version_dir']) / 'entry.md').is_file())
        self.installer('--activate', 'no-such-version', expect=2)

    def test_reinstall_after_rollback_reports_reactivated(self):
        first = self.installer()['data']
        (self.source / 'plugins' / 'imps' / 'references' / 'extra-note.md').write_text('a change\n')
        second = self.installer()['data']
        self.installer('--activate', first['version'])
        current = self.prefix / 'imps' / 'current'
        self.assertEqual(os.readlink(current), first['version'])
        third = self.installer()['data']
        self.assertEqual(third['action'], 'reactivated', 'the receipt says current moved')
        self.assertEqual(third['version'], second['version'])
        self.assertEqual(os.readlink(current), second['version'])
        self.assertEqual(self.installer()['data']['action'], 'already_installed', 'nothing changed this time')

    def test_half_uninstalled_snapshot_is_not_installed_or_activatable(self):
        first = self.installer()['data']
        (Path(first['version_dir']) / 'entry.md').write_text('edited by hand\n')
        (self.source / 'plugins' / 'imps' / 'references' / 'extra-note.md').write_text('a change\n')
        second = self.installer()['data']
        kept = self.installer('--uninstall', '--version', first['version'])['data']
        self.assertEqual(kept['kept_modified'], [str(Path(first['version_dir']) / 'entry.md')])
        manifest = json.loads((Path(first['version_dir']) / 'install-manifest.json').read_text())
        self.assertTrue(manifest['preserved_modified'])
        out = self.installer('--activate', first['version'], expect=2)
        self.assertEqual(out['error']['code'], 'unknown_version')
        self.assertEqual(out['error']['details']['installed'], [second['version']])
        self.assertEqual(out['error']['details']['preserved_modified'], [first['version']])
        self.assertEqual(os.readlink(self.prefix / 'imps' / 'current'), second['version'])
        # --force still finishes the half-done uninstall
        self.installer('--uninstall', '--version', first['version'], '--force')
        self.assertFalse(Path(first['version_dir']).exists())

    def test_missing_git_binary_falls_back_to_content_version(self):
        nothing = self.tmp / 'empty-bin'
        nothing.mkdir()
        self.env['PATH'] = str(nothing)
        out = self.installer()['data']
        self.assertIn('+content.', out['version'])
        self.assertIsNone(out['source_commit'])
        self.assertTrue((Path(out['version_dir']) / 'entry.md').is_file())

    def test_git_vanishing_between_log_and_status_still_falls_back(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location('install_under_test', ROOT / 'scripts' / 'install.py')
        install = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(install)
        log = subprocess.CompletedProcess([], 0, stdout='abc123\n', stderr='')
        with mock.patch.object(install.subprocess, 'run', side_effect=[log, FileNotFoundError('git')]):
            self.assertEqual(install.git_commit(self.source, ['core']), (None, True))

    def test_uninstall_keeps_user_created_empty_directories(self):
        first = self.installer()['data']
        version_dir = Path(first['version_dir'])
        mine = version_dir / 'my-scratch'
        mine.mkdir()
        self.assertTrue((version_dir / 'references').is_dir(), 'an owned directory to compare against')
        self.installer('--uninstall')
        self.assertTrue(mine.is_dir(), 'an empty directory the installer never owned survives')
        self.assertFalse((version_dir / 'references').exists(), 'owned directories emptied by the uninstall go')
        self.assertFalse((version_dir / 'install-manifest.json').exists())

    def test_relative_prefix_yields_absolute_receipt_paths(self):
        script = self.source / 'scripts' / 'install.py'
        result = subprocess.run([sys.executable, str(script), '--prefix', 'rel/prefix', '--dry-run'],
                                capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)['data']
        self.assertEqual(Path(data['version_dir']).parts[:len(self.tmp.parts)], self.tmp.parts)
        self.assertTrue(Path(data['entry']).is_absolute())

    def test_version_without_uninstall_is_a_usage_error(self):
        script = self.source / 'scripts' / 'install.py'
        result = subprocess.run([sys.executable, str(script), '--version', '1.0.0+g0', '--dry-run'],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--version requires --uninstall', result.stderr)
        self.assertFalse(self.prefix.exists())

    def test_activate_receipt_uses_declared_entry(self):
        demo = self.source / 'plugins' / 'demo'
        demo.mkdir()
        (demo / 'plugin.json').write_text(json.dumps({'name': 'demo', 'version': '0.1.0', 'entry': 'start.md',
                                                      'description': 'fixture'}))
        (demo / 'start.md').write_text('# demo\n')
        first = self.installer('--plugin', 'demo')['data']
        self.assertTrue(first['entry'].endswith('/demo/current/start.md'))
        out = self.installer('--plugin', 'demo', '--activate', first['version'])['data']
        self.assertEqual(out['entry'], str(self.prefix / 'demo' / 'current' / 'start.md'))

    def test_finder_and_explorer_litter_is_not_installed(self):
        baseline = self.installer('--dry-run')['data']
        (self.source / 'plugins' / 'imps' / '.DS_Store').write_bytes(b'\x00')
        (self.source / 'core' / 'Thumbs.db').write_bytes(b'\x00')
        out = self.installer()['data']
        self.assertEqual(out['version'], baseline['version'], 'the snapshot identity does not change')
        self.assertEqual(out['files'], baseline['files'])
        self.assertFalse((Path(out['version_dir']) / '.DS_Store').exists())
        self.assertFalse((Path(out['version_dir']) / 'core' / 'Thumbs.db').exists())
