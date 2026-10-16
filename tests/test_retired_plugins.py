"""Retirement of offload-sidecar and prompt-builder: setup removes their adapters only
when the adapter's own marker proves ownership, and uninstall still accepts them."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RETIRED = ('offload-sidecar', 'prompt-builder')
MARKER = '.t3-plugins-skill.json'
DEFAULT_ROOTS = ('.claude/skills', '.codex/skills', '.config/opencode/skills',
                 '.gemini/config/skills', '.gemini/skills', '.config/muse/skills')


def owned_adapter(root, plugin, text=None):
    """An adapter exactly as an earlier setup wrote it."""
    name = 't3-' + plugin
    folder = Path(root) / name
    folder.mkdir(parents=True)
    data = (text or f'---\nname: {name}\ndescription: "retired"\n---\n\n# {plugin} in T3 Code\n').encode()
    (folder / 'SKILL.md').write_bytes(data)
    receipt = {'schema_version': 1, 'name': name, 'entry': '/old/entry.md', 'sha256': hashlib.sha256(data).hexdigest()}
    (folder / MARKER).write_text(json.dumps(receipt, indent=2) + '\n')
    return folder


def tree(path):
    """Every file and symlink under path with its bytes or link target."""
    path = Path(path)
    found = {}
    for item in sorted(path.rglob('*')):
        rel = item.relative_to(path).as_posix()
        if item.is_symlink():
            found[rel] = ('link', os.readlink(item))
        elif item.is_file():
            found[rel] = ('file', item.read_bytes())
        else:
            found[rel] = ('dir', None)
    return found


class RetiredAdapters(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.prefix = self.base / 'prefix'
        self.agents = self.base / 'managed-agents'
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
                    'XDG_STATE_HOME': str(self.base / 'state')}
        self.env.pop('CODEX_HOME', None)

    def call(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'), '--prefix', str(self.prefix),
                                 '--agents-root', str(self.agents), *args],
                                env=self.env, cwd=self.base, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]

    def preserved_cases(self, root):
        """Adapters setup must leave byte for byte, keyed by what makes them so."""
        root = Path(root)
        cases = {}
        # Owned by marker, then edited by the user.
        edited = owned_adapter(root, 'offload-sidecar')
        (edited / 'SKILL.md').write_text('my edits')
        cases['modified'] = edited
        # Owned and unmodified, plus a user file: only the owned files go.
        extra = owned_adapter(root, 'prompt-builder')
        (extra / 'notes.md').write_text('keep me')
        cases['extra'] = extra
        return cases

    def assert_cleanup(self, roots, receipts):
        for root in roots:
            root = Path(root)
            self.assertEqual((root / 't3-offload-sidecar/SKILL.md').read_text(), 'my edits')
            self.assertTrue((root / 't3-offload-sidecar' / MARKER).is_file())
            self.assertEqual(sorted(p.name for p in (root / 't3-prompt-builder').iterdir()), ['notes.md'])
            self.assertEqual((root / 't3-prompt-builder/notes.md').read_text(), 'keep me')
            self.assertEqual((root / 'my-skill/SKILL.md').read_text(), 'unrelated')
            self.assertTrue((root / 't3-imps/SKILL.md').is_file())
        by_root = {}
        for receipt in receipts:
            if receipt.get('name') in ('t3-offload-sidecar', 't3-prompt-builder') and 'removed' in receipt:
                by_root.setdefault(receipt['root'], {})[receipt['name']] = receipt
        for root in roots:
            seen = by_root[str(Path(root))]
            self.assertFalse(seen['t3-offload-sidecar']['removed'])
            self.assertIn('modified', seen['t3-offload-sidecar']['preserved'])
            self.assertTrue(seen['t3-prompt-builder']['removed'])
            self.assertEqual(seen['t3-prompt-builder']['kept'], ['notes.md'])

    def seed(self, roots):
        for root in roots:
            self.preserved_cases(root)
            unrelated = Path(root) / 'my-skill'
            unrelated.mkdir(parents=True)
            (unrelated / 'SKILL.md').write_text('unrelated')

    def test_default_roots(self):
        roots = [self.home / r for r in DEFAULT_ROOTS]
        self.seed(roots)
        receipts = self.call('setup')
        self.assert_cleanup(roots, receipts)
        # A second setup changes nothing that survived the first.
        before = {str(r): tree(r) for r in roots}
        self.call('setup')
        self.assertEqual(before, {str(r): tree(r) for r in roots})

    def test_custom_roots(self):
        roots = [self.base / 'custom one', self.base / 'custom two']
        self.seed(roots)
        receipts = self.call('setup', '--root', str(roots[0]), '--root', str(roots[1]))
        self.assert_cleanup(roots, receipts)
        self.assertFalse((self.home / '.agents').exists())

    def test_per_plugin_setup_and_skills_uninstall(self):
        root = self.base / 'per plugin'
        self.seed([root])
        receipts = self.call('setup', 'imps', '--root', str(root))
        self.assert_cleanup([root], receipts)
        self.assertFalse((root / 't3-ape').exists())
        # The retired name is accepted for adapter removal, still by marker only.
        owned_adapter(self.base / 'other root', 'offload-sidecar')
        self.call('skills', 'uninstall', 'offload-sidecar', '--root', str(self.base / 'other root'))
        self.assertFalse((self.base / 'other root/t3-offload-sidecar').exists())
        self.call('skills', 'uninstall', 'offload-sidecar', '--root', str(root), code=2)
        self.assertEqual((root / 't3-offload-sidecar/SKILL.md').read_text(), 'my edits')
        self.call('skills', 'install', 'offload-sidecar', '--root', str(root), code=2)

    def test_owned_unmodified_adapter_is_removed_from_every_root(self):
        roots = [self.home / r for r in DEFAULT_ROOTS]
        for root in roots:
            for plugin in RETIRED:
                owned_adapter(root, plugin)
        receipts = self.call('setup')
        for root in roots:
            for plugin in RETIRED:
                self.assertFalse((root / ('t3-' + plugin)).exists())
        removed = [r for r in receipts if r.get('removed') is True]
        self.assertEqual(len(removed), len(roots) * len(RETIRED))

    def test_symlinks_corrupt_markers_and_unowned_directories_are_preserved(self):
        root = self.base / 'skills'
        outside = self.base / 'outside'
        outside.mkdir()
        target = owned_adapter(outside, 'offload-sidecar')  # owned, but reached through a symlink
        root.mkdir()
        (root / 't3-offload-sidecar').symlink_to(target, target_is_directory=True)
        corrupt = root / 't3-prompt-builder'
        corrupt.mkdir()
        (corrupt / 'SKILL.md').write_text('anything')
        (corrupt / MARKER).write_text('{not json')
        before_root, before_outside = tree(root), tree(outside)
        receipts = self.call('setup', 'imps', '--root', str(root))
        adapter = {'t3-imps', 't3-imps/SKILL.md', 't3-imps/' + MARKER, 't3-imps/agents', 't3-imps/agents/openai.yaml'}
        self.assertLessEqual({k for k in tree(root) if k.split('/')[0] == 't3-imps'}, adapter)
        after = {k: v for k, v in tree(root).items() if k not in adapter}
        self.assertEqual(after, before_root)
        self.assertEqual(tree(outside), before_outside)
        preserved = {r['name']: r['preserved'] for r in receipts if 'preserved' in r}
        self.assertIn('symlink', preserved['t3-offload-sidecar'])
        self.assertIn('t3-prompt-builder', preserved)

    def test_inner_symlinks_wrong_name_and_missing_marker_are_preserved(self):
        root = self.base / 'skills'
        secret = self.base / 'secret.md'
        secret.write_text('private')
        linked = owned_adapter(root, 'offload-sidecar')
        (linked / 'SKILL.md').unlink()
        (linked / 'SKILL.md').symlink_to(secret)
        renamed = owned_adapter(root, 'prompt-builder')
        receipt = json.loads((renamed / MARKER).read_text())
        receipt['name'] = 't3-something-else'
        (renamed / MARKER).write_text(json.dumps(receipt))
        before = tree(root)
        self.call('setup', 'imps', '--root', str(root))
        after = {k: v for k, v in tree(root).items() if not k.startswith('t3-imps')}
        self.assertEqual(after, before)
        self.assertEqual(secret.read_text(), 'private')
        shutil.rmtree(renamed)
        unmarked = root / 't3-prompt-builder'
        unmarked.mkdir()
        (unmarked / 'SKILL.md').write_text('hand written')
        self.call('setup', 'imps', '--root', str(root))
        self.assertEqual((unmarked / 'SKILL.md').read_text(), 'hand written')

    def test_symlinked_root_is_untouched(self):
        real = self.base / 'real'
        owned_adapter(real, 'offload-sidecar')
        link = self.base / 'linked'
        link.symlink_to(real, target_is_directory=True)
        before = tree(real)
        self.call('setup', 'imps', '--root', str(link), code=2)
        self.assertEqual(tree(real), before)


class RetiredUninstall(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.prefix = self.base / 'prefix'
        self.agents = self.base / 'managed-agents'

    def call(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'), '--prefix', str(self.prefix),
                                 '--agents-root', str(self.agents), *args],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def old_snapshot(self, plugin, recorded=None):
        """A snapshot installed by an earlier release, built with the real installer."""
        source = self.base / 'old source'
        (source / 'plugins' / plugin).mkdir(parents=True, exist_ok=True)
        (source / 'plugins' / plugin / 'plugin.json').write_text(
            json.dumps({'name': plugin, 'version': '0.1.3', 'entry': 'entry.md'}))
        (source / 'plugins' / plugin / 'entry.md').write_text('# old entry\n')
        for name in ('core', 'shared'):
            (source / name).mkdir(exist_ok=True)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', plugin,
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents), '--source', str(source)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        version_dir = Path(json.loads(result.stdout)['data']['version_dir'])
        if recorded:
            manifest = json.loads((version_dir / 'install-manifest.json').read_text())
            manifest['plugin'] = recorded
            (version_dir / 'install-manifest.json').write_text(json.dumps(manifest))
        return version_dir

    def test_uninstall_accepts_a_retired_plugin_its_manifest_records(self):
        for plugin in RETIRED:
            version_dir = self.old_snapshot(plugin)
            extra = version_dir / 'my-notes.txt'
            extra.write_text('keep')
            receipt = json.loads(self.call('uninstall', plugin).stdout)['data']
            self.assertEqual(receipt['action'], 'uninstall')
            self.assertFalse((version_dir / 'entry.md').exists())
            self.assertEqual(extra.read_text(), 'keep')

    def test_uninstall_refuses_without_a_matching_manifest(self):
        self.call('uninstall', 'offload-sidecar', code=2)
        version_dir = self.old_snapshot('prompt-builder', recorded='imps')
        result = self.call('uninstall', 'prompt-builder', code=2)
        self.assertIn('unknown plugin', result.stderr)
        self.assertTrue((version_dir / 'entry.md').exists())
        self.call('uninstall', 'never-existed', code=2)

    def test_corrupt_retired_manifest_reaches_the_installer(self):
        version_dir = self.old_snapshot('offload-sidecar')
        (version_dir / 'install-manifest.json').write_text('not json')
        result = self.call('uninstall', 'offload-sidecar', code=2)
        self.assertIn('manifest_corrupt', result.stdout + result.stderr)
        self.assertTrue((version_dir / 'entry.md').exists())
        missing = self.call('uninstall', 'prompt-builder', code=2)
        self.assertIn('nothing of it is installed', missing.stderr)
        self.assertNotIn('t3-plugins uninstall prompt-builder', missing.stderr)

    def test_other_commands_reject_retired_names(self):
        self.old_snapshot('offload-sidecar')
        for command in (['install', 'offload-sidecar'], ['doctor', 'offload-sidecar'], ['path', 'offload-sidecar']):
            result = self.call(*command, code=2)
            self.assertIn('retired', result.stderr)


if __name__ == '__main__':
    unittest.main()
