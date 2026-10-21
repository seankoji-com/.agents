"""Installed-artifact tests: catalog, ownership, relocation, and offline invocation."""
import json
import hashlib
import os
from pathlib import Path
import shutil
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
        self.agents = Path(self.tmp.name) / 'managed agents'
        self.env = {**os.environ, 'HOME': self.tmp.name,
                    'XDG_CONFIG_HOME': str(Path(self.tmp.name) / 'config'),
                    'XDG_STATE_HOME': str(Path(self.tmp.name) / 'state')}

    def call(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(CLI), '--prefix', str(self.prefix), '--agents-root', str(self.agents), *args],
                                capture_output=True, text=True, timeout=30, env=self.env)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_catalog_install_doctor_and_uninstall_preserve_neighbors(self):
        receipts = [json.loads(line)['data'] for line in self.call('install').stdout.splitlines()]
        self.assertEqual(len(receipts), 8)
        self.assertEqual({r['plugin'] for r in receipts},
                         {'imps', 'ape', 'babysitter', 'elephant-goldfish', 'agent-tuneup', 'ralph', 'focus-group', 'bug-report'})
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

    def test_setup_uses_native_skill_roots_and_preserves_shared_copies(self):
        self.env.pop('CODEX_HOME', None)
        self.env.pop('XDG_CONFIG_HOME', None)
        home = Path(self.tmp.name)
        shared = home / '.agents/skills/t3-ape/SKILL.md'
        shared.parent.mkdir(parents=True)
        shared.write_text('operator-owned shared copy')
        self.call('setup', 'ape')
        roots = (home / '.claude/skills', home / '.codex/skills',
                 home / '.config/opencode/skills', home / '.gemini/config/skills',
                 home / '.gemini/skills', home / '.config/muse/skills')
        for root in roots:
            self.assertTrue((root / 't3-ape/SKILL.md').is_file(), str(root))
        self.assertEqual(shared.read_text(), 'operator-owned shared copy')
        self.assertEqual(list(shared.parent.parent.iterdir()), [shared.parent])

    def test_setup_respects_provider_overrides_and_deduplicates_roots(self):
        home = Path(self.tmp.name)
        # Codex deliberately shares Claude's root; setup should write it once.
        self.env['CODEX_HOME'] = str(home / '.claude')
        self.env['XDG_CONFIG_HOME'] = str(home / 'custom config')
        result = self.call('setup', 'ape')
        receipts = [json.loads(line) for line in result.stdout.splitlines()]
        adapters = [row['path'] for row in receipts if row.get('name') == 't3-ape']
        self.assertEqual(len(adapters), 5)
        self.assertEqual(len(set(adapters)), 5)
        for provider in ('opencode', 'muse'):
            self.assertTrue((home / 'custom config' / provider / 'skills/t3-ape/SKILL.md').is_file())
        self.assertFalse((home / '.codex/skills').exists())
        self.assertFalse((home / 'config/opencode/skills').exists())
        self.assertFalse((home / '.agents/skills').exists())

    def test_setup_explicit_root_replaces_native_defaults(self):
        self.env.pop('CODEX_HOME', None)
        root = Path(self.tmp.name) / 'chosen skills'
        self.call('setup', 'ape', '--root', str(root))
        self.assertTrue((root / 't3-ape/SKILL.md').is_file())
        for name in ('.claude/skills', '.codex/skills', 'config/opencode/skills',
                     '.gemini/config/skills', '.gemini/skills', 'config/muse/skills',
                     '.agents/skills'):
            self.assertFalse((Path(self.tmp.name) / name).exists(), name)

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
        picker = self.call('prompt', 'ape').stdout.strip()
        self.assertEqual(picker, f"Read {self.prefix}/ape/current/entry.md. Ask through the host's native question picker. Recommend the first option and do nothing until the owner answers. Options: forage, study, clean, doctor.")
        self.assertNotIn('run: doctor', picker)

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

    def test_agents_inspection_and_explicit_override_enablement(self):
        self.call('install', 'imps')
        items = [json.loads(line) for line in self.call('agents', 'list', 'imps').stdout.splitlines()]
        self.assertEqual(len(items), 4)
        self.assertTrue(all(item['integrity'] == 'ok' and item['override_status'] == 'disabled' for item in items))
        shown = json.loads(self.call('agents', 'show', 'imps', 'stage-executor').stdout)
        self.assertIn('Complete one assigned engineering stage', shown['definition'])
        override = self.agents / 'overrides/imps/stage-executor.md'
        override.parent.mkdir(parents=True)
        override.write_text('---\nworker_id: imps/stage-executor\n---\n\nKeep evidence compact.\n')
        self.call('agents', 'enable-override', 'imps/stage-executor', '--base-digest', shown['worker']['bundle_digest'])
        shown = json.loads(self.call('agents', 'show', 'imps', 'stage-executor').stdout)
        self.assertIn('Keep evidence compact.', shown['definition'])
        self.call('agents', 'disable-override', 'imps/stage-executor', '--base-digest', shown['worker']['bundle_digest'])
        self.assertNotIn('Keep evidence compact.', json.loads(self.call('agents', 'show', 'imps', 'stage-executor').stdout)['definition'])

    def test_job_path_uses_only_verified_declared_dependency(self):
        self.call('install', 'imps')
        version_dir = self.prefix / 'imps' / os.readlink(self.prefix / 'imps/current')
        manifest = json.loads((version_dir / 'install-manifest.json').read_text())
        job = Path(self.tmp.name) / 'job.json'
        job.write_text(json.dumps({'schema_version': 1, 'dependencies': [{'key': 'workflow', 'plugin': 'imps'}],
                                   'pins': {'workflow': {'package_dir': str(version_dir),
                                   'installation_id': manifest['installation_id'],
                                   'package_digest': manifest['package_digest'], 'bundle_dir': manifest['bundle_dir'],
                                   'bundle_digest': manifest['bundle_digest']}}}))
        self.assertEqual(self.call('--job', str(job), 'path', 'imps').stdout.strip(), str(version_dir / 'entry.md'))
        self.call('--job', str(job), 'path', 'ape', expected=2)
        bad = Path(self.tmp.name) / 'bad-job.json'
        bad.write_text('{"schema_version": 99}')
        self.call('--job', str(bad), 'path', 'imps', expected=2)
        extra = version_dir / 'unlisted-user-file.txt'
        extra.write_text('preserve this unlisted file')
        self.call('--job', str(job), 'path', 'imps', expected=2)
        self.assertEqual(extra.read_text(), 'preserve this unlisted file')
        extra.unlink()
        fifo = Path(self.tmp.name) / 'fifo-job.json'
        os.mkfifo(fifo)
        self.call('--job', str(fifo), 'path', 'imps', expected=2)
        self.assertTrue(fifo.exists())

    def test_explicit_relocation_adoption_requires_verified_copy(self):
        self.call('install', 'ape')
        relocated = Path(self.tmp.name) / 'relocated'
        shutil.copytree(self.prefix, relocated, symlinks=True)
        result = self.call('--prefix', str(relocated), 'adopt', '--from-prefix', str(self.prefix))
        self.assertIn('"verified": true', result.stdout)
        claims = json.loads((self.agents / 'claims.json').read_text())
        identity = json.loads((relocated / 'ape' / os.readlink(relocated / 'ape/current') / 'install-manifest.json').read_text())['installation_id']
        self.assertEqual(claims[identity]['locators'], [str(self.prefix), str(relocated)])
        self.call('--prefix', str(relocated), 'agents', 'list', 'ape')
        self.call('agents', 'list', 'ape', expected=2)
        old_remove = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'ape',
                                     '--prefix', str(self.prefix), '--agents-root', str(self.agents), '--uninstall'],
                                    capture_output=True, text=True, env=self.env)
        self.assertEqual(old_remove.returncode, 2)
        self.assertIn('identity conflict', old_remove.stdout + old_remove.stderr)


if __name__ == '__main__':
    unittest.main()
