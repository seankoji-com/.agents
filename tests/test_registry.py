"""Managed worker bundle, policy, and Stage 3 pin snapshot contract tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import registry


class RegistryPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'agents'
        self.config = Path(self.tmp.name) / 'config/workers.json'

    def test_limits_reject_booleans_fractions_and_null_repairs(self):
        self.config.parent.mkdir(parents=True)
        for live, repair in ((True, 3), (2.5, 3), (None, False), (None, 1.5)):
            self.config.write_text(json.dumps({'schema_version': 1, 'max_live_workers': live,
                                               'max_repair_cycles': repair, 'overrides': []}))
            with self.assertRaises(registry.RegistryError):
                registry.load_workers_config(self.config)

    def test_override_is_explicit_and_digest_bound(self):
        worker_id = 'imps/stage-executor'
        digest = 'a' * 64
        self.assertIsNone(registry.validate_override(self.root, worker_id, digest,
                    {'schema_version': 1, 'max_live_workers': None, 'max_repair_cycles': 3, 'overrides': []}))
        path = registry.override_path(self.root, worker_id)
        path.parent.mkdir(parents=True)
        path.write_text('---\nworker_id: imps/stage-executor\n---\ncustom\n')
        cfg = {'schema_version': 1, 'max_live_workers': None, 'max_repair_cycles': 3,
               'overrides': [{'worker_id': worker_id, 'base_bundle_digest': digest,
                              'path': 'imps/stage-executor.md', 'enabled': True}]}
        self.assertEqual(registry.validate_override(self.root, worker_id, digest, cfg)['status'], 'enabled')
        self.assertEqual(registry.validate_override(self.root, worker_id, 'b' * 64, cfg)['status'], 'stale')
        path.unlink()
        with self.assertRaises(registry.RegistryError):
            registry.validate_override(self.root, worker_id, digest, cfg)

    def test_dangling_workers_config_symlink_is_not_a_default(self):
        self.config.parent.mkdir(parents=True)
        self.config.symlink_to(self.config.parent / 'missing.json')
        with self.assertRaises(registry.RegistryError):
            registry.load_workers_config(self.config)

    def test_override_writes_from_threads_preserve_distinct_workers(self):
        workers = ['imps/stage-executor', 'imps/investigator']
        for worker in workers:
            target = registry.override_path(self.root, worker)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f'---\nworker_id: {worker}\n---\ncustom\n')
        errors = []
        def update(worker):
            try: registry.set_override(self.root, worker, 'a' * 64, True, self.config)
            except Exception as exc: errors.append(exc)
        threads = [threading.Thread(target=update, args=(worker,)) for worker in workers]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual({r['worker_id'] for r in registry.load_workers_config(self.config)['overrides']}, set(workers))

    def test_concurrent_distinct_prefix_claims_are_not_lost(self):
        identities = [str(registry.uuid.uuid4()), str(registry.uuid.uuid4())]
        prefixes = [self.root.parent / 'prefix-a', self.root.parent / 'prefix-b']
        errors = []
        def claim(identity, prefix):
            try: registry.claim_installation(self.root, identity, prefix)
            except Exception as exc: errors.append(exc)
        threads = [threading.Thread(target=claim, args=pair) for pair in zip(identities, prefixes)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        claims = json.loads((self.root / 'claims.json').read_text())
        self.assertEqual(errors, [])
        self.assertEqual(set(claims), set(identities))


class PinSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.prefix = self.base / 'prefix'
        self.agents = self.base / 'agents'
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.base / 'config'),
                    'XDG_STATE_HOME': str(self.base / 'state')}

    def test_snapshot_api_pins_exact_assets_limits_and_task_contract(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'imps',
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        version_dir = Path(json.loads(result.stdout)['data']['version_dir'])
        other_prefix, other_agents = self.base / 'other-prefix', self.base / 'other-agents'
        ape_install = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'ape',
                                      '--prefix', str(other_prefix), '--agents-root', str(other_agents)],
                                     capture_output=True, text=True, env=self.env)
        self.assertEqual(ape_install.returncode, 0, ape_install.stdout + ape_install.stderr)
        ape_version_dir = Path(json.loads(ape_install.stdout)['data']['version_dir'])
        ape_manifest = json.loads((ape_version_dir / 'install-manifest.json').read_text())
        manifest = json.loads((version_dir / 'install-manifest.json').read_text())
        job = self.base / 'job.json'
        job.write_text(json.dumps({'schema_version': 1, 'dependencies': [
            {'key': 'workflow', 'plugin': 'imps'}, {'key': 'research', 'plugin': 'ape',
             'package_dir': str(ape_version_dir), 'bundle_dir': ape_manifest['bundle_dir'],
             'bundle_digest': ape_manifest['bundle_digest']}]}))
        contract = b'Only inspect the assigned stage.\n'
        snap = registry.snapshot_pins(job, {'workflow': 'imps', 'research': 'ape'}, self.prefix, self.agents,
                                      self.base / 'config/workers.json', contract)
        pin = snap['pins']['workflow']
        self.assertEqual(pin['installation_id'], manifest['installation_id'])
        self.assertEqual(pin['package_digest'], manifest['package_digest'])
        self.assertEqual(pin['bundle_digest'], manifest['bundle_digest'])
        self.assertEqual(pin['compatible_pinned_invocation'], f't3-plugins --job {job.absolute()} path imps')
        self.assertEqual(snap['compatible_pinned_invocations']['workflow'], pin['compatible_pinned_invocation'])
        self.assertEqual(pin['limits'], {'max_live_workers': None, 'max_repair_cycles': 3})
        effective = pin['effective_workers']['imps/stage-executor']
        self.assertIn('Shared boundary contracts', effective['bytes'])
        self.assertIn('Specialized worker definition', effective['bytes'])
        self.assertIn('Pinned task contract\nThe task brief and repository instructions set the authority ceiling.', effective['bytes'])
        self.assertIn('Only inspect the assigned stage.', effective['bytes'])
        self.assertEqual(effective['sha256'], hashlib.sha256(effective['bytes'].encode()).hexdigest())
        self.assertEqual(pin['task_contract']['sha256'], hashlib.sha256(contract).hexdigest())
        self.assertEqual(snap['pins']['research']['installation_id'], ape_manifest['installation_id'])
        self.assertNotEqual(snap['pins']['research']['installation_id'], manifest['installation_id'])

    def test_snapshot_rejects_unknown_job_state_and_unresolved_dependency(self):
        job = self.base / 'job.json'
        job.write_text('{"schema_version":77,"dependencies":[]}')
        with self.assertRaises(registry.RegistryError):
            registry.snapshot_pins(job, {}, self.prefix, self.agents)
        job.write_text('{"schema_version":1,"dependencies":[]}')
        with self.assertRaises(registry.RegistryError):
            registry.snapshot_pins(job, {'missing':'imps'}, self.prefix, self.agents)

    def test_installed_package_exports_snapshot_api_without_source_tree(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'imps',
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        package = json.loads(result.stdout)['data']['version_dir']
        job = self.base / 'installed-job.json'
        job.write_text(json.dumps({'schema_version': 1, 'dependencies': [{'key': 'workflow', 'plugin': 'imps'}]}))
        probe = (
            "import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
            "from shared.worker_registry import snapshot_pins; "
            "result=snapshot_pins(Path(sys.argv[2]),{'workflow':'imps'},Path(sys.argv[3]),"
            "Path(sys.argv[4]),Path(sys.argv[5]),b'Isolated installed task.'); "
            "print(json.dumps(result['pins']['workflow']))"
        )
        isolated_env = dict(self.env); isolated_env.pop('PYTHONPATH', None)
        imported = subprocess.run([sys.executable, '-I', '-c', probe, package, str(job), str(self.prefix),
                                   str(self.agents), str(self.base / 'config/workers.json')], cwd=self.base,
                                  env=isolated_env, capture_output=True, text=True)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        pin = json.loads(imported.stdout)
        self.assertEqual(pin['package_dir'], package)
        self.assertIn('imps/stage-executor', pin['effective_workers'])
        self.assertEqual(pin['task_contract']['bytes'], 'Isolated installed task.')
        receipt = json.loads((Path(package) / 'install-manifest.json').read_text())
        os.mkfifo(Path(package) / 'unlisted.pipe')
        with self.assertRaises(registry.RegistryError):
            registry.verify_package_files(Path(package), receipt)

    def test_all_workers_use_existing_routing_categories(self):
        allowed = {'workhorse', 'reviewer', 'judgement'}
        roles = []
        for plugin in ('imps', 'ape', 'elephant-goldfish', 'babysitter', 'agent-tuneup'):
            manifest = json.loads((ROOT / 'plugins' / plugin / 'plugin.json').read_text())
            for worker in manifest['workers']:
                self.assertIn(worker['role'], allowed)
                self.assertTrue(worker['responsibility'].strip())
                roles.append(worker['role'])
        self.assertEqual(len(roles), 12)
        import shutil
        scratch = self.base / 'malformed-plugin' / 'imps'
        scratch.parent.mkdir()
        shutil.copytree(ROOT / 'plugins/imps', scratch)
        manifest_path = scratch / 'plugin.json'
        bad = json.loads(manifest_path.read_text())
        bad['workers'][0]['role'] = 'Complete one assigned engineering stage.'
        manifest_path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(registry.RegistryError, 'invalid worker operation mapping or role'):
            registry.load_manifest(scratch)


class BundleIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.prefix = self.base / 'prefix'
        self.agents = self.base / 'agents'
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_STATE_HOME': str(self.base / 'state')}
        result = self.install()
        self.version_dir = Path(json.loads(result.stdout)['data']['version_dir'])
        self.receipt_path = self.version_dir / 'install-manifest.json'
        self.receipt = json.loads(self.receipt_path.read_text())
        self.bundle = Path(self.receipt['bundle_dir'])

    def install(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'imps',
                               '--prefix', str(self.prefix), '--agents-root', str(self.agents), *args],
                              capture_output=True, text=True, env=self.env)

    def test_bundle_rejects_extra_symlink_traversal_and_corrupt_manifest(self):
        extra = self.bundle / 'extra.md'
        extra.write_text('extra')
        with self.assertRaises(registry.RegistryError):
            registry.verify_bundle(self.bundle, self.receipt['installation_id'], 'imps', self.receipt['version'], self.receipt['package_digest'])
        extra.unlink()
        link = self.bundle / 'workers/linked.md'
        link.symlink_to(self.bundle / 'workers/stage-executor.md')
        with self.assertRaises(registry.RegistryError):
            registry.verify_bundle(self.bundle, self.receipt['installation_id'], 'imps', self.receipt['version'], self.receipt['package_digest'])
        link.unlink()
        manifest_path = self.bundle / 'manifest.json'
        original = manifest_path.read_bytes()
        manifest = json.loads(original); manifest['assets'][0]['path'] = '../outside'
        manifest_path.chmod(0o644); manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(registry.RegistryError):
            registry.verify_bundle(self.bundle, self.receipt['installation_id'], 'imps', self.receipt['version'], self.receipt['package_digest'])
        manifest_path.write_bytes(b'{bad json');
        with self.assertRaises(registry.RegistryError):
            registry.verify_bundle(self.bundle, self.receipt['installation_id'], 'imps', self.receipt['version'], self.receipt['package_digest'])
        manifest_path.write_bytes(original)

    def test_bundle_rejects_fifo_without_opening_it(self):
        import os
        fifo = self.bundle / 'workers/unlisted.pipe'
        os.mkfifo(fifo)
        with self.assertRaises(registry.RegistryError):
            registry.verify_bundle(self.bundle, self.receipt['installation_id'], 'imps', self.receipt['version'], self.receipt['package_digest'])
        fifo.unlink()

    def test_show_composes_boundaries_base_and_enabled_customization(self):
        worker = 'imps/stage-executor'
        custom = registry.override_path(self.agents, worker)
        custom.parent.mkdir(parents=True, exist_ok=True)
        custom.write_text(f'---\nworker_id: {worker}\n---\nCustom note.\n')
        config = self.base / 'config/workers.json'
        registry.set_override(self.agents, worker, self.receipt['bundle_digest'], True, config)
        shown = registry.show_agent(self.agents, 'imps', 'stage-executor', self.prefix, config)
        self.assertIn('Shared boundary contracts', shown['definition'])
        self.assertIn('Specialized worker definition', shown['definition'])
        self.assertIn('Complete one assigned engineering stage', shown['definition'])
        self.assertIn('Custom note.', shown['definition'])
        self.assertEqual(shown['provenance']['override_status'], 'enabled')

    def test_interrupted_bundle_install_repairs_and_activation_fails_closed(self):
        # A package receipt written before its external bundle is a recoverable interrupted install.
        import shutil
        shutil.rmtree(self.bundle)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.bundle.is_dir())
        current = self.prefix / 'imps/current'
        previous = os.readlink(current)
        worker = self.bundle / 'workers/stage-executor.md'
        worker.chmod(0o644); worker.write_text('tampered')
        result = self.install('--activate', previous)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(os.readlink(current), previous)

    def test_two_plugins_share_prefix_identity_and_second_prefix_does_not(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'ape',
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ape = Path(json.loads(result.stdout)['data']['version_dir'])
        ape_id = json.loads((ape / 'install-manifest.json').read_text())['installation_id']
        self.assertEqual(ape_id, self.receipt['installation_id'])
        other_prefix, other_agents = self.base / 'other-prefix', self.base / 'other-agents'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'imps',
                                 '--prefix', str(other_prefix), '--agents-root', str(other_agents)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        other = Path(json.loads(result.stdout)['data']['version_dir'])
        self.assertNotEqual(json.loads((other / 'install-manifest.json').read_text())['installation_id'], ape_id)

    def test_uninstall_preserves_file_added_after_bundle_verification(self):
        import argparse
        import install as install_module
        user_file = self.bundle / 'workers/added-after-check.md'
        original_verify = registry.verify_bundle
        def verify_then_add(*args, **kwargs):
            checked = original_verify(*args, **kwargs)
            user_file.write_text('user-owned')
            return checked
        args = argparse.Namespace(plugin='imps', prefix=str(self.prefix), agents_root=str(self.agents),
                                  version=None, force=False, dry_run=False)
        with mock.patch.object(registry, 'verify_bundle', side_effect=verify_then_add):
            result = install_module.uninstall(args)
        self.assertTrue(user_file.exists())
        self.assertIn(str(user_file), result['kept_modified'])

    def test_concurrent_same_prefix_plugin_installs_remain_consistent(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.install())) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual([r.returncode for r in results], [0, 0])
        current = self.prefix / 'imps/current'
        version_dir = current.resolve()
        receipt = json.loads((version_dir / 'install-manifest.json').read_text())
        checked = registry.verify_bundle(Path(receipt['bundle_dir']), receipt['installation_id'], 'imps',
                                         receipt['version'], receipt['package_digest'])
        self.assertEqual(checked['bundle_digest'], receipt['bundle_digest'])


if __name__ == '__main__':
    unittest.main()
