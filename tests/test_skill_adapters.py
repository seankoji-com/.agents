import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillAdapters(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.prefix = self.base / 'package with spaces'
        self.skills = self.base / 'provider skills'

    def call(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'),
                                 '--prefix', str(self.prefix), *args],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def install(self):
        self.call('install', 'imps')
        return self.call('skills', 'install', 'imps', '--root', str(self.skills))

    def test_adapter_uses_installed_entry_and_is_idempotent(self):
        first = self.install()
        entry = self.prefix / 'imps/current/entry.md'
        adapter = self.skills / 't3-imps/SKILL.md'
        self.assertIn(json.dumps(str(entry)), adapter.read_text())
        self.assertIn('name: t3-imps', adapter.read_text())
        self.assertNotIn(str(ROOT), adapter.read_text())
        second = self.call('skills', 'install', 'imps', '--root', str(self.skills))
        self.assertEqual(first.stdout, second.stdout)
        receipt = json.loads((adapter.parent / '.t3-plugins-skill.json').read_text())
        self.assertEqual(receipt['sha256'], hashlib.sha256(adapter.read_bytes()).hexdigest())
        # Exercise the actual helper bundled behind the adapter, from another cwd.
        request = self.base / 'request.json'
        request.write_text(json.dumps({'text': '--personas 42 43'}))
        output = subprocess.run([sys.executable, str(entry.parent / 'scripts/input.py'),
                                 '--input', str(request)], cwd=self.base,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(json.loads(output.stdout)['data']['issues'], [42, 43])

    def test_missing_package_and_external_activation_fail_without_adapter_writes(self):
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())
        self.call('install', 'imps')
        current = self.prefix / 'imps/current'
        current.unlink()
        current.symlink_to(ROOT / 'plugins/imps')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())

    def test_unowned_and_modified_adapters_are_preserved(self):
        self.call('install', 'imps')
        folder = self.skills / 't3-imps'
        folder.mkdir(parents=True)
        skill = folder / 'SKILL.md'
        skill.write_text('my existing skill')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(skill.read_text(), 'my existing skill')
        skill.unlink()
        folder.rmdir()
        self.install()
        skill.write_text('my edited skill')
        for action in ('install', 'uninstall'):
            self.call('skills', action, 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(skill.read_text(), 'my edited skill')
        self.assertTrue((folder / '.t3-plugins-skill.json').exists())

    def test_symlink_roots_and_leafs_are_rejected(self):
        self.call('install', 'imps')
        external = self.base / 'external'
        external.mkdir()
        self.skills.symlink_to(external)
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(list(external.iterdir()), [])
        self.skills.unlink()
        self.install()
        target = external / 'private.md'
        target.write_text('preserve')
        skill = self.skills / 't3-imps/SKILL.md'
        skill.unlink()
        skill.symlink_to(target)
        for action in ('install', 'uninstall'):
            self.call('skills', action, 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(target.read_text(), 'preserve')

    def test_uninstall_preserves_extra_files_and_is_idempotent(self):
        self.install()
        extra = self.skills / 't3-imps/operator.txt'
        extra.write_text('notes')
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills))
        self.assertEqual(extra.read_text(), 'notes')
        self.assertTrue((self.prefix / 'imps/current/entry.md').exists())
        # Remaining unowned directories are intentionally not removed on retry.
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills), code=2)
        extra.unlink()
        extra.parent.rmdir()
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills))

    def test_all_catalog_adapters_and_invalid_receipt(self):
        self.call('install')
        result = self.call('skills', 'install', '--root', str(self.skills))
        self.assertEqual(len(result.stdout.splitlines()), 5)
        marker = self.skills / 't3-imps/.t3-plugins-skill.json'
        marker.write_text('[]')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)

    def test_modified_snapshot_is_not_registered(self):
        self.call('install', 'imps')
        (self.prefix / 'imps/current/entry.md').write_text('changed')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())

    def test_prompt_forwards_panel_flags(self):
        self.call('install', 'imps')
        prompt = self.call('prompt', 'imps', '--personas', '42', '43').stdout
        self.assertIn('run: --personas 42 43', prompt)


if __name__ == '__main__':
    unittest.main()
