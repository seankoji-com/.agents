"""Installed-artifact tests: catalog, ownership, relocation, and offline invocation."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'bin/t3-plugins'


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prefix = Path(self.tmp.name) / 'path with spaces'

    def call(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(CLI), '--prefix', str(self.prefix), *args],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_catalog_install_doctor_and_uninstall_preserve_neighbors(self):
        receipts = [json.loads(line)['data'] for line in self.call('install').stdout.splitlines()]
        self.assertEqual(len(receipts), 5)
        self.assertEqual({r['plugin'] for r in receipts},
                         {'imps', 'ape', 'babysitter', 'elephant-goldfish', 'agent-tuneup'})
        for receipt in receipts:
            entry = Path(receipt['entry'])
            self.assertTrue(entry.is_file())
            self.assertTrue((entry.parent / 'shared/t3-runtime.md').is_file())
        self.call('doctor')
        self.assertIn('already_installed', self.call('install').stdout)
        entry = self.prefix / 'ape/current/entry.md'
        entry.write_text('operator edit')
        self.call('doctor', 'ape', expected=1)
        self.call('install', 'ape', expected=4)
        extra = entry.parent / 'personal.txt'
        extra.write_text('keep')
        self.call('uninstall', 'ape')
        self.assertEqual(entry.read_text(), 'operator edit')
        self.assertEqual(extra.read_text(), 'keep')
        self.call('doctor', 'imps')

    def test_dry_run_does_not_create_prefix(self):
        self.call('install', '--dry-run')
        self.assertFalse(self.prefix.exists())

    def test_healthy_old_snapshot_is_reported_and_cli_warns_without_rewriting(self):
        self.call('install', 'imps')
        command = [sys.executable, str(ROOT / 'scripts/run_imps.py'), '--help']
        env = {**os.environ, 'T3_PLUGINS_PREFIX': str(self.prefix)}
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('snapshot differs', result.stderr)
        current = self.prefix / 'imps/current'
        contract = current / 'shared/t3-runtime.md'
        contract.write_text('previous release contract')
        manifest_path = current / 'install-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for item in manifest['files']:
            if item['path'] == 'shared/t3-runtime.md':
                item['sha256'] = hashlib.sha256(contract.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        receipt = json.loads(self.call('doctor', 'imps', expected=1).stdout)
        self.assertEqual(receipt['errors'], ['snapshot_outdated: run t3-plugins install imps'])
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('snapshot differs', result.stderr)
        self.assertEqual(contract.read_text(), 'previous release contract')

    def test_unknown_and_traversal_names_fail_without_writes(self):
        for name in ('../elsewhere', '/tmp', 'unknown-plugin'):
            self.call('install', name, expected=2)
        self.assertFalse(self.prefix.exists())

    def test_prompt_requires_install_and_uses_expanded_path(self):
        self.call('prompt', 'ape', expected=2)
        self.call('install', 'ape')
        self.assertEqual(self.call('prompt', 'ape', 'study', 'https://github.com/example/project').stdout.strip(),
                         f'Read {self.prefix}/ape/current/entry.md and run: study https://github.com/example/project')

    def test_doctor_detects_missing_files_and_external_activation(self):
        self.call('install', 'ape')
        (self.prefix / 'ape/current/entry.md').unlink()
        self.call('doctor', 'ape', expected=1)
        current = self.prefix / 'ape/current'
        current.unlink()
        current.symlink_to(ROOT / 'plugins/ape')
        receipt = json.loads(self.call('doctor', 'ape', expected=1).stdout)
        self.assertEqual(receipt['errors'], ['installation_invalid: missing or external current symlink'])

    def test_doctor_names_a_missing_installation(self):
        receipt = json.loads(self.call('doctor', 'ape', expected=1).stdout)
        self.assertEqual(receipt['errors'], ['not_installed: run t3-plugins install ape'])

    def test_uninstall_forwards_force_and_version(self):
        first = json.loads(self.call('install', 'ape').stdout)['data']
        entry = self.prefix / 'ape/current/entry.md'
        entry.write_text('operator edit')
        receipt = json.loads(self.call('uninstall', 'ape', '--version', 'no-such', expected=2).stdout)
        self.assertEqual(receipt['error']['code'], 'unknown_version')
        self.assertEqual(entry.read_text(), 'operator edit')
        receipt = json.loads(self.call('uninstall', 'ape', '--version', first['version'], '--force').stdout)['data']
        self.assertEqual(receipt['versions'], [first['version']])
        self.assertEqual(receipt['kept_modified'], [])
        self.assertFalse(Path(first['version_dir']).exists())

    def test_every_subcommand_has_help(self):
        text = self.call('--help').stdout
        for name in ('path', 'prompt', 'doctor'):
            self.assertRegex(text, rf'(?m)^\s+{name}\s{{2,}}\S', f'{name} needs help text')

    def test_installed_helper_works_outside_checkout(self):
        self.call('install', 'agent-tuneup')
        project = Path(self.tmp.name) / 'project'
        project.mkdir()
        (project / 'settings.json').write_text(json.dumps({'permissions': {'allow': ['Bash(*)']}}))
        script = self.prefix / 'agent-tuneup/current/scripts/audit.py'
        result = subprocess.run([sys.executable, '-I', str(script), '--provider', 'claude', '--settings', 'settings.json'],
                                cwd=project, capture_output=True, text=True, timeout=10)
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt['ok'])
        self.assertNotIn('Bash(*)', result.stdout)

    def test_installed_alignment_helper_plans_and_applies_outside_checkout(self):
        self.call('install', 'agent-tuneup')
        project = Path(self.tmp.name).resolve() / 'alignment-project'
        project.mkdir()
        target = project / 'settings.json'
        candidate = project / 'candidate.json'
        target.write_text('{"permissions":{"allow":["Read(*)"]}}')
        candidate.write_text('{"permissions":{"allow":[]}}')
        target.chmod(0o600)
        candidate.chmod(0o600)
        script = self.prefix / 'agent-tuneup/current/scripts/align.py'
        plan = project / 'plan.json'
        result = subprocess.run([sys.executable, '-I', str(script), 'plan', '--adapter', 'claude',
                                 '--target', str(target), '--candidate', str(candidate),
                                 '--allow-key', '/permissions/allow', '--out', str(plan)],
                                cwd=project, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        digest = json.loads(result.stdout)['approval_digest']
        result = subprocess.run([sys.executable, '-I', str(script), 'apply', '--plan', str(plan),
                                 '--approval', digest, '--backup', str(project / 'backup')],
                                cwd=project, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), candidate.read_bytes())
        self.assertEqual((project / 'backup').read_text(), '{"permissions":{"allow":["Read(*)"]}}')

    def test_retired_plugins_are_not_in_the_catalog(self):
        listed = self.call('list').stdout
        for name in ('offload-sidecar', 'prompt-builder'):
            self.assertNotIn(name, listed)
            self.assertFalse((ROOT / 'plugins' / name).exists())
            self.assertIn('unknown plugin', self.call('install', name, expected=2).stderr)
        self.assertFalse(self.prefix.exists())

    def test_entries_are_small_and_load_existing_files(self):
        import re
        for directory in (ROOT / 'plugins').iterdir():
            meta = json.loads((directory / 'plugin.json').read_text())
            entry = directory / meta['entry']
            self.assertLess(len(entry.read_text().split()), 1500, directory.name)
            for path in directory.rglob('*.md'):
                for rel in re.findall(r'PKG/([a-zA-Z0-9_./-]+)', path.read_text()):
                    rel = rel.rstrip('.')
                    if rel.endswith('/') or rel.endswith('.'):
                        continue
                    # Placeholder-derived template names are checked by rendering tests.
                    if rel in ('templates/probes',):
                        continue
                    self.assertTrue((directory / rel).exists() or (ROOT / rel).exists(), f'{path}: {rel}')

    def test_templates_do_not_reintroduce_claude_dispatch(self):
        for path in (ROOT / 'plugins/elephant-goldfish/templates').glob('*.md'):
            text = path.read_text()
            for forbidden in ('/imps:imps', 'haiku', 'CLAUDE_PLUGIN_ROOT'):
                self.assertNotIn(forbidden, text, path)


if __name__ == '__main__':
    unittest.main()
