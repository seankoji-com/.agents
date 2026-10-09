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
