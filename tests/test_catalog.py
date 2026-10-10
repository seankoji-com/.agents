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
        self.assertEqual(len(receipts), 7)
        self.assertEqual({r['plugin'] for r in receipts},
                         {'imps', 'ape', 'babysitter', 'elephant-goldfish', 'prompt-builder', 'agent-tuneup', 'offload-sidecar'})
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
        self.call('doctor', 'ape', expected=1)

    def test_installed_sidecar_transform_works_outside_checkout(self):
        self.call('install', 'offload-sidecar')
        project = Path(self.tmp.name) / 'project'
        project.mkdir()
        (project / 'input.txt').write_text('zebra\napple\n')
        request = {'operation': 'sort_lines', 'input_path': 'input.txt', 'output_path': 'sorted.txt'}
        (project / 'request.json').write_text(json.dumps(request))
        script = self.prefix / 'offload-sidecar/current/scripts/process.py'
        result = subprocess.run([sys.executable, str(script), 'request.json'], cwd=project,
                                env={**os.environ, 'SIDECAR_ROOT': str(project)}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((project / 'sorted.txt').read_text(), 'apple\nzebra\n')
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['status'], 'success')
        self.assertIn('output_sha256', receipt)

    def test_cloud_default_and_explicit_tiers_require_consent(self):
        script = ROOT / 'plugins/offload-sidecar/scripts/process.py'
        for request in ({'operation': 'describe_image'}, {'operation': 'summarize', 'tier': 'pro'}):
            path = Path(self.tmp.name) / 'request.json'
            path.write_text(json.dumps(request))
            result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn('allow_cloud=true', result.stdout)

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

    def test_one_shot_rejects_malformed_request_types_without_tracebacks(self):
        script = ROOT / 'plugins/offload-sidecar/scripts/process.py'
        for changes in ({'params': ['bad']}, {'overwrite': 'false'}, {'operation': []},
                        {'instruction': {}}, {'input_paths': 'file'}, {'allow_cloud': 'true'}):
            path = Path(self.tmp.name) / 'request.json'
            path.write_text(json.dumps({'operation': 'sort_lines', **changes}))
            result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['status'], 'error')
            self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
