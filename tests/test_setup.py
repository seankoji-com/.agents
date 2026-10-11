import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'home with spaces'
        self.home.mkdir()
        # Match the formula's installed tree, with no Git checkout or bin directory.
        self.package = Path(self.temp.name) / 'libexec'
        for name in ('scripts', 'core', 'plugins', 'shared'):
            shutil.copytree(ROOT / name, self.package / name,
                            ignore=shutil.ignore_patterns('__pycache__'))
        self.prefix = self.home / 'snapshots'

    def call(self, *args, code=0):
        result = subprocess.run([sys.executable, str(self.package / 'scripts/catalog.py'),
                                 '--prefix', str(self.prefix), *args], cwd=self.home,
                                env={**os.environ, 'HOME': str(self.home)},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def test_default_setup_installs_catalog_and_three_roots_idempotently(self):
        first = self.call('setup')
        receipts = [json.loads(line) for line in first.stdout.splitlines()]
        self.assertEqual(len(receipts), 28)
        for root in ('.agents/skills', '.claude/skills', '.gemini/config/skills'):
            skill = self.home / root / 't3-imps/SKILL.md'
            self.assertIn(str(self.prefix / 'imps/current/entry.md'), skill.read_text())
        self.call('setup')
        self.call('doctor')

    def test_custom_roots_replace_defaults_and_preserve_unowned_skill(self):
        custom = self.home / 'custom skills'
        second = self.home / 'second skills'
        self.call('setup', 'imps', '--root', str(custom), '--root', str(second))
        self.assertTrue((second / 't3-imps/SKILL.md').is_file())
        self.assertFalse((self.home / '.agents').exists())
        (custom / 't3-imps/SKILL.md').write_text('operator edit')
        self.call('setup', 'imps', '--root', str(custom), code=2)
        self.assertEqual((custom / 't3-imps/SKILL.md').read_text(), 'operator edit')
        self.assertTrue((custom / 't3-imps/.t3-plugins-skill.json').exists())

    def test_setup_rejects_symlink_root_without_touching_target(self):
        target = self.home / 'target'
        target.mkdir()
        root = self.home / 'linked skills'
        root.symlink_to(target)
        self.call('setup', 'imps', '--root', str(root), code=2)
        self.assertEqual(list(target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
