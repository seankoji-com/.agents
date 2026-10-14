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
        # macOS temporary paths traverse /var -> /private/var. Provider state
        # deliberately refuses symlink ancestors; use the real isolated root.
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        # Match the formula's installed tree, with no Git checkout or bin directory.
        self.package = self.base / 'libexec'
        for name in ('scripts', 'core', 'plugins', 'shared'):
            shutil.copytree(ROOT / name, self.package / name,
                            ignore=shutil.ignore_patterns('__pycache__'))
        self.prefix = self.home / 'snapshots'
        self.agents = self.base / 'managed-agents'
        self.project = self.base / 'project'
        self.project.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home),
                    'XDG_CONFIG_HOME': str(self.home / 'config'),
                    'XDG_STATE_HOME': str(self.base / 'state')}
        for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'OPENCODE_CONFIG', 'OPENCODE_CONFIG_CONTENT'):
            self.env.pop(key, None)

    def call(self, *args, code=0):
        result = subprocess.run([sys.executable, str(self.package / 'scripts/catalog.py'),
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents), *args], cwd=self.project,
                                env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def test_default_setup_installs_catalog_and_four_roots_idempotently(self):
        first = self.call('setup')
        receipts = [json.loads(line) for line in first.stdout.splitlines()]
        install_receipts = [r for r in receipts if 'learnings_grant' not in r]
        self.assertEqual(len(install_receipts), 30)
        grants = [r['learnings_grant'] for r in receipts if 'learnings_grant' in r]
        self.assertEqual(len(grants), 6)
        self.assertEqual({r['status'] for r in grants}, {'proposed', 'unavailable'})
        self.assertFalse((self.home / '.claude/settings.json').exists())
        self.assertFalse((self.home / '.codex/config.toml').exists())
        for root in ('.agents/skills', '.claude/skills', '.gemini/config/skills', '.config/muse/skills'):
            skill = self.home / root / 't3-imps/SKILL.md'
            self.assertIn(str(self.prefix / 'imps/current/entry.md'), skill.read_text())
        self.call('setup')
        self.call('doctor')

    def test_setup_grants_require_explicit_flag_in_an_isolated_home(self):
        self.call('setup', 'imps')
        self.assertFalse((self.home / '.claude/settings.json').exists())
        result = self.call('setup', 'imps', '--grant-learnings')
        grants = [json.loads(line)['learnings_grant'] for line in result.stdout.splitlines()
                  if 'learnings_grant' in json.loads(line)]
        self.assertEqual(next(g for g in grants if g['provider'] == 'claudeAgent')['status'], 'applied')
        config = json.loads((self.home / '.claude/settings.json').read_text())
        self.assertEqual(config, {'sandbox': {'filesystem': {'allowWrite': [
            str(self.base / 'state/t3-plugins/learnings')]}}})
        repeated = self.call('setup', 'imps', '--grant-learnings')
        grants = [json.loads(line)['learnings_grant'] for line in repeated.stdout.splitlines()
                  if 'learnings_grant' in json.loads(line)]
        self.assertEqual(next(g for g in grants if g['provider'] == 'claudeAgent')['status'], 'unchanged')

    def test_setup_from_home_prints_and_applies_default_grants(self):
        self.project = self.home
        self.env.pop('XDG_STATE_HOME')
        self.env.pop('XDG_CONFIG_HOME')
        first = self.call('setup', 'imps')
        grants = [json.loads(line)['learnings_grant'] for line in first.stdout.splitlines()
                  if 'learnings_grant' in json.loads(line)]
        claude = next(g for g in grants if g['provider'] == 'claudeAgent')
        self.assertEqual(claude['status'], 'proposed')
        self.assertEqual(claude['grant'], {'sandbox': {'filesystem': {'allowWrite': [
            str(self.home / '.local/state/t3-plugins/learnings')]}}})
        applied = self.call('setup', 'imps', '--grant-learnings')
        grants = [json.loads(line)['learnings_grant'] for line in applied.stdout.splitlines()
                  if 'learnings_grant' in json.loads(line)]
        self.assertEqual(next(g for g in grants if g['provider'] == 'claudeAgent')['status'], 'applied')

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
