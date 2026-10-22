import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import skills  # noqa: E402
from shutil import rmtree as shutil_rmtree  # noqa: E402


class SkillAdapters(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.prefix = self.base / 'package with spaces'
        self.skills = self.base / 'provider skills'
        self.agents = self.base / 'managed agents'

    def call(self, *args, code=0):
        # A full install fsyncs every file it writes (about 470), so it takes several
        # seconds and stretches further when the disk is busy. The timeout only guards
        # against a hang, so leave headroom for parallel suite runs on a loaded host.
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'),
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents), *args],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def install(self):
        self.call('install', 'imps')
        return self.call('skills', 'install', 'imps', '--root', str(self.skills))

    def test_adapter_uses_installed_entry_and_is_idempotent(self):
        first = self.install()
        entry = (self.prefix / 'imps/current').resolve() / 'entry.md'
        adapter = self.skills / 't3-imps/SKILL.md'
        self.assertIn(json.dumps(str(entry)), adapter.read_text())
        self.assertIn('name: t3-imps', adapter.read_text())
        self.assertIn("With no request, ask through the host's native question picker.", adapter.read_text())
        self.assertIn('Recommend the first option.', adapter.read_text())
        self.assertIn('Do nothing until the owner answers.', adapter.read_text())
        self.assertIn('Use the operation from the first matching route. If no route matches, ask',
                      adapter.read_text())
        self.assertNotIn('With no arguments, run `doctor`.', adapter.read_text())
        self.assertIn('do not switch to another imps installation', adapter.read_text())
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
        self.assertEqual(len(result.stdout.splitlines()), 8)
        marker = self.skills / 't3-imps/.t3-plugins-skill.json'
        marker.write_text('[]')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)

    def test_installed_descriptions_show_argument_hints_for_every_operation(self):
        self.call('install')
        self.call('skills', 'install', '--root', str(self.skills))
        for manifest in sorted((ROOT / 'plugins').glob('*/plugin.json')):
            meta = json.loads(manifest.read_text())
            with self.subTest(plugin=meta['name']):
                adapter = self.skills / ('t3-' + meta['name']) / 'SKILL.md'
                front = adapter.read_text().split('---\n', 2)[1]
                line = next(line for line in front.splitlines() if line.startswith('description: '))
                description = json.loads(line.removeprefix('description: '))
                self.assertTrue(description.startswith(meta['description'] + ' Args: '))
                self.assertIn(meta['argument_hint'], description)
                self.assertLessEqual(len(description), 1024)
                operations = {hint.strip().split()[0] for hint in meta['argument_hint'].split('|')}
                self.assertEqual(operations, set(meta['operations']))
                self.assertEqual(len(meta['picker']), len(set(meta['picker'])))
                self.assertGreaterEqual(len(meta['picker']), 2)
                self.assertLessEqual(len(meta['picker']), 4)
                for route in meta['routes']:
                    self.assertTrue(route['pattern'].startswith('^') and route['pattern'].endswith('$'))
                    self.assertIn(route['pattern'], (self.skills / ('t3-' + meta['name']) / 'SKILL.md').read_text())
                    self.assertIn(route['operation'], meta['operations'])
        imps = (self.skills / 't3-imps/SKILL.md').read_text().split('---\n', 2)[1]
        imps_adapter = (self.skills / 't3-imps/SKILL.md').read_text()
        self.assertIn('Remove declared standalone flags (`--personas`) before choosing the operation.',
                      imps_adapter)
        for hint in ('run <task>', 'resume <run-id>', 'checklist <path>',
                     'issues <number> [<number> ...]', 'discussion <number or URL>',
                     'add --personas before or after any request'):
            self.assertIn(hint, imps)

    def test_modified_snapshot_is_not_registered(self):
        self.call('install', 'imps')
        (self.prefix / 'imps/current/entry.md').write_text('changed')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())

    def test_receipt_digest_tamper_is_not_registered(self):
        self.call('install', 'imps')
        marker = self.prefix / 'imps/current/install-manifest.json'
        receipt = json.loads(marker.read_text())
        receipt['package_digest'] = '0' * 64
        marker.write_text(json.dumps(receipt))
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())

    def test_missing_receipt_entry_is_not_registered_even_with_updated_digest(self):
        self.call('install', 'imps')
        marker = self.prefix / 'imps/current/install-manifest.json'
        receipt = json.loads(marker.read_text())
        removed = next(item for item in receipt['files'] if item['path'] not in {'entry.md', 'plugin.json'})
        receipt['files'].remove(removed)
        receipt['package_digest'] = skills.installer.registry.package_digest(receipt)
        marker.write_text(json.dumps(receipt))
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())
        self.assertTrue((marker.parent / removed['path']).is_file())

    def test_unlisted_package_file_is_not_registered(self):
        self.call('install', 'imps')
        extra = self.prefix / 'imps/current/unlisted.txt'
        extra.write_text('preserve')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())
        self.assertEqual(extra.read_text(), 'preserve')

    def test_worker_bundle_required_from_current_metadata(self):
        self.call('install', 'imps')
        marker = self.prefix / 'imps/current/install-manifest.json'
        receipt = json.loads(marker.read_text())
        receipt.pop('bundle_dir')
        receipt.pop('bundle_digest')
        marker.write_text(json.dumps(receipt))
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())

    @unittest.skipUnless(os.name == 'posix', 'read-only installed assets require POSIX mode bits')
    def test_stale_worker_bundle_preserves_existing_adapter(self):
        self.install()
        marker = self.prefix / 'imps/current/install-manifest.json'
        receipt = json.loads(marker.read_text())
        bundle = Path(receipt['bundle_dir'])
        asset = next(p for p in bundle.rglob('*') if p.is_file() and p.name != 'manifest.json')
        asset.chmod(0o644)
        asset.write_text('modified bundle')
        asset.chmod(0o444)
        folder = self.skills / 't3-imps'
        before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(asset.read_text(), 'modified bundle')

    @unittest.skipUnless(os.name == 'posix', 'read-only installed assets require POSIX mode bits')
    def test_worker_bundle_pairing_and_receipt_digest_are_verified(self):
        self.call('install', 'imps')
        marker = self.prefix / 'imps/current/install-manifest.json'
        receipt = json.loads(marker.read_text())
        bundle_marker = Path(receipt['bundle_dir']) / 'manifest.json'
        original = bundle_marker.read_bytes()
        bundle = json.loads(original)
        bundle['package_digest'] = '0' * 64
        bundle_marker.chmod(0o644)
        bundle_marker.write_text(json.dumps(bundle))
        bundle_marker.chmod(0o444)
        # Even a receipt matching the changed bundle cannot excuse wrong pairing.
        receipt['bundle_digest'] = skills.installer.registry.digest(skills.installer.registry.canonical(bundle))
        marker.write_text(json.dumps(receipt))
        result = self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())
        self.assertIn('package pairing mismatch', result.stderr)
        bundle_marker.chmod(0o644)
        bundle_marker.write_bytes(original)
        bundle_marker.chmod(0o444)
        receipt['bundle_digest'] = '0' * 64
        marker.write_text(json.dumps(receipt))
        result = self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())
        self.assertIn('bundle digest mismatch', result.stderr)

    def test_adapter_metadata_comes_from_current_receipted_package_not_cli_catalog(self):
        self.call('install', 'imps')
        installed = json.loads((self.prefix / 'imps/current/plugin.json').read_text())
        bundled = dict(installed, version='999.0.0', description='wrong CLI metadata',
                       operations=['wrong'], picker=['wrong', 'other'])
        skills.install(self.skills, self.prefix, bundled)
        text = (self.skills / 't3-imps/SKILL.md').read_text()
        self.assertIn(installed['description'], text)
        self.assertNotIn('wrong CLI metadata', text)
        self.assertNotIn('999.0.0', text)

    def test_metadata_changed_after_snapshot_verification_is_not_rendered(self):
        self.call('install', 'imps')
        meta = json.loads((self.prefix / 'imps/current/plugin.json').read_text())
        changed = dict(meta, description='unverified metadata')
        original = skills.installer.registry.read_regular

        def read(path, label):
            return json.dumps(changed).encode() if label == 'installed plugin metadata' else original(path, label)

        with mock.patch.object(skills.installer.registry, 'read_regular', side_effect=read):
            with self.assertRaisesRegex(ValueError, 'metadata changed'):
                skills.install(self.skills, self.prefix, meta)
        self.assertFalse(self.skills.exists())

    def test_changed_activation_is_refused_before_adapter_writes(self):
        self.call('install', 'imps')
        current = self.prefix / 'imps/current'
        meta = json.loads((current / 'plugin.json').read_text())
        original = skills.render

        def activate_other(*args):
            current.unlink()
            current.symlink_to(self.base / 'other')
            return original(*args)

        with mock.patch.object(skills, 'render', activate_other), self.assertRaisesRegex(ValueError, 'activation changed'):
            skills.install(self.skills, self.prefix, meta)
        self.assertFalse(self.skills.exists())

    def test_prompt_forwards_panel_flags(self):
        self.call('install', 'imps')
        prompt = self.call('prompt', 'imps', '--personas', '42', '43').stdout
        self.assertIn('run: --personas 42 43', prompt)

    def test_prompt_without_request_offers_manifest_picker(self):
        self.call('install', 'imps')
        prompt = self.call('prompt', 'imps').stdout
        self.assertIn("Ask through the host's native question picker.", prompt)
        self.assertIn('Recommend the first option and do nothing until the owner answers.', prompt)
        self.assertIn('Options: run, audit, issues, doctor.', prompt)
        self.assertNotIn('doctor\n', prompt)

    def test_workflow_manifests_have_valid_picker_routes(self):
        expected = {
            'imps': ['run', 'audit', 'issues', 'doctor'],
            'ralph': ['run', 'resume', 'status', 'doctor'],
            'elephant-goldfish': ['thinking', 'elephant', 'check', 'doctor'],
            'babysitter': ['pr', 'repo', 'org', 'doctor'],
            'ape': ['forage', 'study', 'clean', 'doctor'],
            'agent-tuneup': ['audit', 'align', 'scan', 'doctor'],
            'focus-group': ['plan', 'run', 'status', 'doctor'],
            'bug-report': ['run', 'resume', 'status', 'cancel'],
        }
        for manifest in sorted((ROOT / 'plugins').glob('*/plugin.json')):
            meta = json.loads(manifest.read_text())
            with self.subTest(plugin=meta['name']):
                skills.validate_picker(meta)
                self.assertEqual(meta['picker'], expected[meta['name']])
        invalid = {'name': 'bad', 'operations': ['doctor'], 'picker': ['doctor', 'doctor'],
                   'routes': [{'pattern': 'doctor', 'operation': 'doctor'}]}
        with self.assertRaises(ValueError):
            skills.validate_picker(invalid)
        for bad_picker in (['doctor', 'doctor'], ['doctor', 'unknown'],
                           ['run', 'resume', 'status', 'doctor', 'cancel']):
            invalid_picker = {'name': 'bad', 'operations': ['doctor', 'run', 'resume', 'status', 'cancel'],
                              'picker': bad_picker, 'routes': []}
            with self.subTest(picker=bad_picker), self.assertRaises(ValueError):
                skills.validate_picker(invalid_picker)
        with self.assertRaises(ValueError):
            skills.validate_picker({'name': 'bad', 'operations': ['run', 'doctor'],
                                    'picker': ['run', 'doctor'],
                                    'routes': [{'pattern': '^a|b$', 'operation': 'run'}]})
        with self.assertRaises(ValueError):
            skills.validate_picker({'name': 'bad', 'operations': ['run', 'doctor'],
                                    'picker': ['run', 'doctor'],
                                    'routes': [{'pattern': '^abc\\$', 'operation': 'run'}]})
        skills.validate_picker({'name': 'good', 'operations': ['run', 'doctor'],
                                 'picker': ['run', 'doctor'],
                                 'routes': [{'pattern': '^[]|]x$', 'operation': 'run'}]})
        for flags in (['-p'], ['--bad flag'], ['--personas', '--personas'], [1]):
            with self.subTest(standalone_flags=flags), self.assertRaises(ValueError):
                skills.validate_picker({'name': 'bad', 'operations': ['run', 'doctor'],
                                        'picker': ['run', 'doctor'], 'routes': [],
                                        'standalone_flags': flags})

    def test_imps_manifest_routes_match_input_classifier_and_render_in_order(self):
        manifest = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        input_spec = importlib.util.spec_from_file_location(
            'imps_input_for_routes', ROOT / 'plugins/imps/scripts/input.py')
        input_module = importlib.util.module_from_spec(input_spec)
        input_spec.loader.exec_module(input_module)
        with tempfile.TemporaryDirectory() as temp:
            checklist = Path(temp) / 'audit with spaces.md'
            checklist.write_text('- [ ] check\n  Verify: python3 check.py\n  Done when: passed\n')
            # Bare /imps:imps-shaped requests and --personas alone belong to the
            # picker surface, which the route table never sees. route() returns
            # None for empty text; input.py classifies the whole request.
            cases = {
                '42 #43': 'issues', '#12': 'issues',
                'discussion 5': 'discussion',
                'https://github.com/example/project/discussions/5': 'discussion',
                'HTTPS://github.com/example/project/discussions/5': 'discussion',
                'Https://github.com/example/project/discussions/5': 'discussion',
                'run HTTPS://github.com/example/project/discussions/5': 'discussion',
                'run 42 #43': 'issues', 'run discussion 5': 'discussion',
                '/imps:imps 42 43': 'issues', 'imps #12': 'issues',
                'imps {"issues": [1]}': 'issues', 'imps discussion 5': 'discussion',
                'imps https://github.com/a/b/discussions/7': 'discussion',
                'imps ' + str(checklist): 'checklist',
                '/imps:imps ' + str(checklist): 'checklist',
                '--personas audit': 'audit', '--personas doctor': 'doctor',
                '--personas 42': 'issues', '42 --personas': 'issues',
                'run ' + str(checklist): 'checklist',
                'status run-123': 'status', 'resume run-123': 'resume',
                'cancel run-123': 'cancel', 'blast-radius HEAD~1': 'blast-radius',
                'prs repo example/project': 'prs',
                'audit --focus routing': 'audit', 'issue-mode 42': 'issues',
                'imp-agency security': 'audit', 'verification-init': 'verification-init',
                'doctor --global': 'doctor', 'doctor 42': 'doctor',
                'doctor verbose': 'doctor',
                'issue tracker is slow': 'run', 'issues are piling up': 'issues',
                'status-page shows stale data': 'run', 'audit-log is broken': 'run',
                'doctor-mode flaky': 'run', 'ISSUES 5': 'run', 'Issues 5': 'run',
                'Resume x': 'run', '/imps:audit': 'audit', '/imps:doctor': 'doctor',
                '/imps:issues 5': 'issues', '  doctor  ': 'doctor',
                '  issue tracker is slow  ': 'run',
                'fix the bug\nwith details': 'run',
                '/imps:resume x': 'resume', '/imps:status x': 'status',
                '/imps:cancel x': 'cancel', '/imps:verification-init x': 'verification-init',
                '/imps:blast-radius x': 'blast-radius', '/imps:prs x': 'prs',
                '/imps:checklist ' + str(checklist): 'checklist',
                '/imps:discussion 7': 'discussion',
                '/imps:run fix it': 'run', '/imps:run 5': 'issues',
                '/imps:imp-agency x': 'audit', '/imps:issue-mode 5': 'issues',
                str(checklist): 'checklist', 'a plain task': 'run',
            }
            rendered = skills.render(manifest, Path('entry.md'))
            rendered_routes = [line for line in rendered.splitlines() if line.startswith('- `')]
            expected_routes = ['- `' + item['pattern'] + '` -> `' + item['operation'] + '`'
                               for item in manifest['routes']]
            self.assertEqual(rendered_routes, expected_routes)
            classifier_refusals = {'issues are piling up'}
            for text, operation in cases.items():
                with self.subTest(text=text):
                    self.assertEqual(skills.route(manifest, text), operation)
                    if text in classifier_refusals:
                        with self.assertRaisesRegex(ValueError, 'issues requires issue numbers'):
                            input_module.route(text)
                    else:
                        self.assertEqual(input_module.route(text)['operation'], operation)
            # Routes cannot test file existence. input.py deliberately leaves a
            # nonexistent markdown path as task text while the manifest selects checklist.
            missing = str(Path(temp) / 'missing.md')
            self.assertEqual(skills.route(manifest, missing), 'checklist')
            self.assertEqual(input_module.route(missing)['operation'], 'run')
            self.assertIsNone(skills.route(manifest, '   '))
            self.assertIsNone(skills.route(manifest, '--personas'))
            self.assertIsNone(input_module.route('--personas')['operation'])

    def test_manifest_routes_dispatch_first_match_and_leave_ambiguous_text_to_picker(self):
        manifests = {meta['name']: meta for manifest in (ROOT / 'plugins').glob('*/plugin.json')
                     for meta in [json.loads(manifest.read_text())]}
        babysitter = manifests['babysitter']
        ape = manifests['ape']
        tuneup = manifests['agent-tuneup']
        self.assertEqual(skills.route(babysitter, 'https://github.com/acme/widgets/pull/42'), 'pr')
        self.assertEqual(skills.route(babysitter, 'pr https://github.com/acme/widgets/pull/42'), 'pr')
        self.assertEqual(skills.route(babysitter, 'acme/widgets'), 'repo')
        self.assertEqual(skills.route(babysitter, 'repo acme/widgets'), 'repo')
        self.assertEqual(skills.route(babysitter, 'org acme'), 'org')
        for text in ('pr', 'repo', 'org'):
            self.assertIsNone(skills.route(babysitter, text))
        self.assertIsNone(skills.route(babysitter, 'doctr'))
        for text in (
            'Org chart is wrong', 'Organization of files is messy',
            'pull request 1', 'PR-1 is stuck',
            'repository a/b', 'repo-cleanup',
        ):
            with self.subTest(plugin='babysitter', text=text):
                self.assertIsNone(skills.route(babysitter, text))
        self.assertEqual(skills.route(ape, 'https://github.com/acme/widgets'), 'study')
        for text in (
            'Clean up the README', 'search for auth libs', 'find repos', 'research caching',
        ):
            with self.subTest(plugin='ape', text=text):
                self.assertIsNone(skills.route(ape, text))
        self.assertEqual(tuneup['routes'], [])
        self.assertIsNone(skills.route(tuneup, 'align the provider permissions'))
        rendered_tuneup = skills.render(tuneup, Path('entry.md'))
        self.assertIn("With no request, ask through the host's native question picker.", rendered_tuneup)
        self.assertIn('With no route table, ask which operation to run.', rendered_tuneup)
        self.assertNotIn('Use the text after the skill mention as the operation and arguments.',
                         rendered_tuneup)
        imps = manifests['imps']
        ralph = manifests['ralph']
        elephant = manifests['elephant-goldfish']
        self.assertEqual(skills.route(imps, 'add dark mode'), 'run')
        self.assertEqual(skills.route(imps, 'review login flow'), 'run')
        self.assertEqual(skills.route(ralph, 'ship a settings page'), 'run')
        for text, operation in {
            'run --max-attempts 3 goal': 'run', 'resume state.json': 'resume',
            'status state.json': 'status', 'cancel state.json': 'cancel',
            'doctor': 'doctor', 'doctor --verbose': 'doctor',
        }.items():
            with self.subTest(ralph=text):
                self.assertEqual(skills.route(ralph, text), operation)
        self.assertEqual(skills.route(elephant, 'improve the design brief'), 'thinking')
        for text, operation in {
            'doctor': 'doctor', 'thinking topic': 'thinking',
            'elephant failure report': 'elephant', 'check': 'check',
            'status page shows stale data': 'thinking',
            'verify the rollout plan': 'thinking',
            'failure modes of the queue': 'thinking',
        }.items():
            with self.subTest(elephant=text):
                self.assertEqual(skills.route(elephant, text), operation)
        multiline = 'ship this\nwith details'
        self.assertEqual(skills.route(imps, multiline), 'run')
        self.assertEqual(skills.route(ralph, multiline), 'run')
        self.assertEqual(skills.route(elephant, multiline), 'thinking')
        for meta in manifests.values():
            with self.subTest(plugin=meta['name']):
                skills.validate_picker(meta)
                for item in meta['routes']:
                    self.assertTrue(item['pattern'].startswith('^') and item['pattern'].endswith('$'))
                    re.compile(item['pattern'])
                    self.assertIn(item['operation'], meta['operations'])
                    rendered = skills.render(meta, Path('entry.md'))
                    self.assertIn('- `' + item['pattern'] + '` -> `' + item['operation'] + '`', rendered)

    def test_adapter_frontmatter_carries_provenance_metadata(self):
        meta = json.loads((ROOT / 'plugins/babysitter/plugin.json').read_text())
        self.call('install', 'babysitter')
        self.call('skills', 'install', 'babysitter', '--root', str(self.skills))
        front = (self.skills / 't3-babysitter/SKILL.md').read_text().split('---\n', 2)[1]
        self.assertIn('metadata:', front)
        self.assertIn('  t3-plugins-version: ' + json.dumps(meta['version']), front)
        self.assertIn('  t3-plugins-kind: ' + json.dumps(meta['kind']), front)
        self.assertIn('  t3-plugins-compatibility: ' + json.dumps(meta['compatibility']), front)
        origin = meta['origin']
        self.assertIn('  t3-plugins-origin-repository: ' + json.dumps(origin['repository']), front)
        self.assertIn('  t3-plugins-origin-plugin: ' + json.dumps(origin['plugin']), front)
        self.assertIn('  t3-plugins-origin-version: ' + json.dumps(origin['version']), front)

    def test_adapter_without_origin_omits_origin_keys(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        self.assertNotIn('origin', meta)
        self.install()
        front = (self.skills / 't3-imps/SKILL.md').read_text().split('---\n', 2)[1]
        self.assertIn('  t3-plugins-version: ' + json.dumps(meta['version']), front)
        self.assertNotIn('t3-plugins-origin', front)

    def test_frontmatter_top_level_stays_within_the_spec(self):
        spec_fields = {'name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'}
        self.install()
        front = (self.skills / 't3-imps/SKILL.md').read_text().split('---\n', 2)[1]
        keys = {line.split(':', 1)[0] for line in front.splitlines() if line and not line[0].isspace()}
        self.assertLessEqual(keys, spec_fields)
        self.assertNotIn('disable-model-invocation', front)
        self.assertNotIn('user-invocable', front)
        self.assertNotIn('argument-hint', front)

    def test_model_invocation_policy_lives_in_metadata(self):
        imps = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        self.assertNotIn('model_invocable', imps)
        self.install()
        front = (self.skills / 't3-imps/SKILL.md').read_text().split('---\n', 2)[1]
        self.assertIn('  opencode/slash: "true"', front)
        self.assertIn('  opencode/autoinvoke: "false"', front)

    def test_babysitter_stays_model_invocable(self):
        meta = json.loads((ROOT / 'plugins/babysitter/plugin.json').read_text())
        self.assertTrue(meta['model_invocable'])
        self.call('install', 'babysitter')
        self.call('skills', 'install', 'babysitter', '--root', str(self.skills))
        front = (self.skills / 't3-babysitter/SKILL.md').read_text().split('---\n', 2)[1]
        self.assertIn('  opencode/slash: "true"', front)
        self.assertNotIn('opencode/autoinvoke', front)


    def openai_yaml(self, plugin='imps'):
        return self.skills / ('t3-' + plugin) / 'agents/openai.yaml'

    def receipt(self, plugin='imps'):
        return json.loads((self.skills / ('t3-' + plugin) / '.t3-plugins-skill.json').read_text())

    def test_codex_metadata_is_written_owned_and_removed_with_the_adapter(self):
        self.install()
        yaml = self.openai_yaml()
        lines = yaml.read_text().splitlines()
        self.assertEqual(lines[0], 'interface:')
        fields = {line.split(':', 1)[0].strip(): json.loads(line.split(':', 1)[1]) for line in lines[1:]}
        self.assertEqual(set(fields), {'display_name', 'short_description', 'default_prompt'})
        self.assertEqual(fields['display_name'], 'T3 Imps')
        self.assertIn('$t3-imps', fields['default_prompt'])
        self.assertNotIn(str(self.prefix), yaml.read_text())
        self.assertEqual(self.receipt()['files'],
                         {'agents/openai.yaml': hashlib.sha256(yaml.read_bytes()).hexdigest()})
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills))
        self.assertFalse((self.skills / 't3-imps').exists())

    def test_every_catalog_adapter_has_a_short_picker_description(self):
        self.call('install')
        self.call('skills', 'install', '--root', str(self.skills))
        for manifest in sorted((ROOT / 'plugins').glob('*/plugin.json')):
            meta = json.loads(manifest.read_text())
            with self.subTest(plugin=meta['name']):
                text = self.openai_yaml(meta['name']).read_text()
                line = next(l for l in text.splitlines() if l.startswith('  short_description: '))
                short = json.loads(line.split(': ', 1)[1])
                # Codex picker blurbs are 25-64 characters.
                self.assertTrue(25 <= len(short) <= 64, short)
                self.assertEqual(short, meta.get('short_description', meta['description']))

    def test_upgrade_from_a_receipt_without_files_adopts_the_metadata(self):
        self.install()
        folder = self.skills / 't3-imps'
        receipt = self.receipt()
        receipt.pop('files')
        (folder / '.t3-plugins-skill.json').write_text(json.dumps(receipt))
        self.openai_yaml().unlink()
        (folder / 'agents').rmdir()
        self.call('skills', 'install', 'imps', '--root', str(self.skills))
        self.assertIn('agents/openai.yaml', self.receipt()['files'])
        # Bytes identical to ours (an interrupted earlier install) are adopted too.
        receipt.pop('files', None)
        (folder / '.t3-plugins-skill.json').write_text(json.dumps(receipt))
        self.call('skills', 'install', 'imps', '--root', str(self.skills))
        self.assertIn('agents/openai.yaml', self.receipt()['files'])

    def test_operator_metadata_under_an_old_receipt_is_preserved(self):
        self.install()
        folder = self.skills / 't3-imps'
        receipt = self.receipt()
        receipt.pop('files')
        (folder / '.t3-plugins-skill.json').write_text(json.dumps(receipt))
        self.openai_yaml().write_text('interface:\n  display_name: "Mine"\n')
        result = json.loads(self.call('skills', 'install', 'imps', '--root', str(self.skills)).stdout)
        self.assertEqual(result['preserved_files'], ['agents/openai.yaml'])
        self.assertNotIn('files', self.receipt())
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills))
        self.assertEqual(self.openai_yaml().read_text(), 'interface:\n  display_name: "Mine"\n')
        self.assertFalse((folder / 'SKILL.md').exists())

    def test_modified_or_symlinked_metadata_is_refused(self):
        self.install()
        yaml = self.openai_yaml()
        yaml.write_text('interface:\n  display_name: "Edited"\n')
        for action in ('install', 'uninstall'):
            self.call('skills', action, 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(yaml.read_text(), 'interface:\n  display_name: "Edited"\n')
        yaml.unlink()
        agents = yaml.parent
        agents.rmdir()
        external = self.base / 'external'
        external.mkdir()
        agents.symlink_to(external, target_is_directory=True)
        for action in ('install', 'uninstall'):
            self.call('skills', action, 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(list(external.iterdir()), [])

    def test_receipt_cannot_name_files_outside_the_owned_set(self):
        self.install()
        folder = self.skills / 't3-imps'
        bystander = folder / 'operator.txt'
        bystander.write_text('notes')
        receipt = self.receipt()
        receipt['files']['operator.txt'] = hashlib.sha256(b'notes').hexdigest()
        (folder / '.t3-plugins-skill.json').write_text(json.dumps(receipt))
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(bystander.read_text(), 'notes')

    def test_retired_adapter_removal_takes_its_owned_metadata(self):
        self.install()
        folder = self.skills / 't3-imps'
        removed = skills.remove_retired(self.skills, 'imps')
        self.assertTrue(removed['removed'])
        self.assertEqual(removed['kept'], [])
        self.assertFalse(folder.exists())

    def test_interrupted_upgrade_with_new_bytes_already_written_recovers(self):
        self.install()
        folder = self.skills / 't3-imps'
        marker = folder / '.t3-plugins-skill.json'
        # Simulate an earlier version: different owned bytes, receipt for them.
        old = b'interface:\n  display_name: "Old"\n'
        receipt = self.receipt()
        receipt['files']['agents/openai.yaml'] = hashlib.sha256(old).hexdigest()
        new_yaml = self.openai_yaml().read_bytes()
        marker.write_text(json.dumps(receipt))
        # The upgrade wrote the new metadata, then stopped before the marker.
        self.assertEqual(self.openai_yaml().read_bytes(), new_yaml)
        self.call('skills', 'uninstall', 'imps', '--root', str(self.skills), code=2)
        self.call('skills', 'install', 'imps', '--root', str(self.skills))
        self.assertEqual(self.receipt()['files']['agents/openai.yaml'], hashlib.sha256(new_yaml).hexdigest())

    def test_operator_files_in_agents_survive_uninstall_and_retired_removal(self):
        for remove in ('uninstall', 'retired'):
            with self.subTest(remove=remove):
                self.install()
                own = self.skills / 't3-imps/agents/claude.yaml'
                own.write_text('mine')
                if remove == 'uninstall':
                    self.call('skills', 'uninstall', 'imps', '--root', str(self.skills))
                else:
                    self.assertEqual(skills.remove_retired(self.skills, 'imps')['kept'], ['agents'])
                self.assertEqual(own.read_text(), 'mine')
                self.assertFalse(self.openai_yaml().exists())
                self.assertFalse((self.skills / 't3-imps/SKILL.md').exists())
                own.unlink()
                own.parent.rmdir()
                (self.skills / 't3-imps').rmdir()

    def external(self, name='external'):
        external = self.base / name
        external.mkdir()
        for leaf in ('openai.yaml', 'SKILL.md', '.t3-plugins-skill.json'):
            (external / leaf).write_text('external')
        return external

    def assert_external_untouched(self, external):
        self.assertEqual(sorted(p.name for p in external.iterdir()),
                         ['.t3-plugins-skill.json', 'SKILL.md', 'openai.yaml'])
        for item in external.iterdir():
            self.assertEqual(item.read_text(), 'external')

    def racing_managed(self, swap):
        """Patch `managed` so `swap(adapter_path)` runs right after the ownership
        check passes: the window a racing process would use."""
        original = skills.managed

        def racing(adapter, *args, **kwargs):
            receipt = original(adapter, *args, **kwargs)
            swap(adapter.path)
            return receipt
        return mock.patch.object(skills, 'managed', racing)

    def test_agents_swapped_for_a_symlink_after_validation_is_never_followed(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        external = self.external()

        def swap(folder):
            shutil_rmtree(folder / 'agents')
            (folder / 'agents').symlink_to(external, target_is_directory=True)
        for action in ('install', 'uninstall'):
            with self.subTest(action=action):
                self.install()
                # The pinned agents/ was deleted by the swap: the run may fail or
                # finish, but it never reaches through the link.
                with self.racing_managed(swap), contextlib.suppress(ValueError, OSError):
                    if action == 'install':
                        skills.install(self.skills, self.prefix, meta)
                    else:
                        skills.uninstall(self.skills, meta)
                self.assert_external_untouched(external)
                (self.skills / 't3-imps/agents').unlink()
                shutil_rmtree(self.skills / 't3-imps')

    def test_adapter_swapped_for_a_symlink_after_validation_stays_pinned(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        external = self.external()
        folder = self.skills / 't3-imps'
        detached = self.skills / 'detached'

        def swap(path):
            path.rename(detached)
            path.symlink_to(external, target_is_directory=True)
        for action in ('install', 'uninstall', 'retired'):
            with self.subTest(action=action):
                self.install()
                with self.racing_managed(swap):
                    if action == 'install':
                        skills.install(self.skills, self.prefix, meta)
                        self.assertIn('agents/openai.yaml',
                                      json.loads((detached / '.t3-plugins-skill.json').read_text())['files'])
                    elif action == 'uninstall':
                        skills.uninstall(self.skills, meta)
                    else:
                        skills.remove_retired(self.skills, 'imps')
                    if action != 'install':
                        # Owned files went from the pinned directory; removing the
                        # directory by name now meets the link and is skipped.
                        self.assertEqual(list(detached.iterdir()), [])
                self.assert_external_untouched(external)
                folder.unlink()
                if detached.exists():
                    shutil_rmtree(detached)

    def test_agents_vanishing_after_creation_fails_closed(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        self.install()
        (self.skills / 't3-imps/agents/openai.yaml').unlink()
        (self.skills / 't3-imps/agents').rmdir()
        original = skills.mkdir_at

        def vanishing(dir_fd, name):
            created = original(dir_fd, name)
            if name == 'agents':
                os.rmdir(name, dir_fd=dir_fd)
            return created
        cwd = Path.cwd()
        os.chdir(self.base)
        try:
            with mock.patch.object(skills, 'mkdir_at', vanishing), self.assertRaises(ValueError):
                skills.install(self.skills, self.prefix, meta)
        finally:
            os.chdir(cwd)
        self.assertFalse((self.base / 'openai.yaml').exists())

    def test_fifos_are_refused_without_blocking(self):
        self.install()
        folder = self.skills / 't3-imps'
        self.openai_yaml().unlink()
        os.mkfifo(self.openai_yaml())
        for action in ('install', 'uninstall'):
            self.call('skills', action, 'imps', '--root', str(self.skills), code=2)
        self.openai_yaml().unlink()
        (folder / '.t3-plugins-skill.json').unlink()
        os.mkfifo(folder / 'pipe')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertTrue(stat.S_ISFIFO((folder / 'pipe').lstat().st_mode))

    def test_interrupted_first_install_is_adopted_on_retry(self):
        folder = self.skills / 't3-imps'
        for lost in (['.t3-plugins-skill.json'], ['.t3-plugins-skill.json', 'SKILL.md']):
            with self.subTest(lost=lost):
                self.install()
                for name in lost:
                    (folder / name).unlink()
                self.call('skills', 'install', 'imps', '--root', str(self.skills))
                self.assertIn('agents/openai.yaml', self.receipt()['files'])
                self.call('skills', 'uninstall', 'imps', '--root', str(self.skills))
                self.assertFalse(folder.exists())
        # A marker-less directory with any byte that is not ours stays refused.
        self.install()
        (folder / '.t3-plugins-skill.json').unlink()
        self.openai_yaml().write_text('interface:\n  display_name: "Mine"\n')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertEqual(self.openai_yaml().read_text(), 'interface:\n  display_name: "Mine"\n')

    def test_swap_after_agents_is_opened_cannot_redirect_writes_or_deletes(self):
        self.install()
        folder = self.skills / 't3-imps'
        external = self.external()
        original = skills.Adapter.sub

        def racing(adapter, name, create=False):
            fd = original(adapter, name, create)
            (folder / name).rename(folder / 'agents-detached')  # the pinned fd follows it
            (folder / name).symlink_to(external, target_is_directory=True)
            return fd
        for action in ('write', 'unlink'):
            with self.subTest(action=action), skills.Adapter(folder) as adapter, \
                    mock.patch.object(skills.Adapter, 'sub', racing):
                if action == 'write':
                    adapter.write('agents/openai.yaml', b'ours')
                    self.assertEqual((folder / 'agents-detached/openai.yaml').read_bytes(), b'ours')
                else:
                    adapter.unlink('agents/openai.yaml')
                    self.assertFalse((folder / 'agents-detached/openai.yaml').exists())
            self.assert_external_untouched(external)
            (folder / 'agents').unlink()
            (folder / 'agents-detached').rename(folder / 'agents')

    def test_root_swapped_for_a_symlink_before_open_is_refused(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        self.install()
        external = self.external()
        original = skills.Adapter.__init__

        def swapping(adapter, directory, create=False, root_is_link=False):
            directory.parent.rename(self.base / 'real-root')
            directory.parent.symlink_to(external, target_is_directory=True)
            original(adapter, directory, create, root_is_link)
        with mock.patch.object(skills.Adapter, '__init__', swapping), self.assertRaises(ValueError):
            skills.install(self.skills, self.prefix, meta)
        self.assert_external_untouched(external)

    def test_directory_swapped_in_after_mkdir_gets_the_ownership_check(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        self.call('install', 'imps')
        self.skills.mkdir()
        operator = self.base / 'operator-skill'
        operator.mkdir()
        (operator / 'SKILL.md').write_text('mine')
        original = skills.mkdir_at

        def swapping(dir_fd, name):
            made = original(dir_fd, name)
            if name == 't3-imps':
                os.rmdir(name, dir_fd=dir_fd)
                operator.rename(self.skills / name)
            return made
        with mock.patch.object(skills, 'mkdir_at', swapping), self.assertRaises(ValueError):
            skills.install(self.skills, self.prefix, meta)
        self.assertEqual((self.skills / 't3-imps/SKILL.md').read_text(), 'mine')
        self.assertEqual(sorted(p.name for p in (self.skills / 't3-imps').iterdir()), ['SKILL.md'])

    def test_agents_replaced_by_a_plain_directory_after_validation_keeps_operator_files(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())

        def swap(folder):
            (folder / 'agents').rename(self.base / 'old-agents')
            (folder / 'agents').mkdir()
            (folder / 'agents/openai.yaml').write_text('operator')
        for action in ('install', 'uninstall', 'retired'):
            with self.subTest(action=action):
                self.install()
                with self.racing_managed(swap), contextlib.suppress(ValueError, OSError):
                    if action == 'install':
                        skills.install(self.skills, self.prefix, meta)
                    elif action == 'uninstall':
                        skills.uninstall(self.skills, meta)
                    else:
                        skills.remove_retired(self.skills, 'imps')
                self.assertEqual((self.skills / 't3-imps/agents/openai.yaml').read_text(), 'operator')
                shutil_rmtree(self.skills / 't3-imps')
                shutil_rmtree(self.base / 'old-agents')

    def test_adoption_tolerates_agents_vanishing_mid_check(self):
        self.install()
        folder = self.skills / 't3-imps'
        (folder / '.t3-plugins-skill.json').unlink()
        with skills.Adapter(folder) as adapter, mock.patch.object(
                skills.Adapter, '_open_sub', lambda adapter, name: None):
            self.assertFalse(skills.interrupted_first_install(adapter, {}))

    def test_untrusted_root_link_is_never_followed_even_if_sampled_as_a_link(self):
        external = self.external()
        link = self.base / 'link-root'
        link.symlink_to(external, target_is_directory=True)
        self.assertFalse(skills.trusted_root_link(link))
        folder = link / 't3-imps'
        with self.assertRaises(ValueError):
            skills.Adapter(folder, create=True, root_is_link=skills.trusted_root_link(link))
        self.assert_external_untouched(external)

    def test_failed_subdirectory_check_closes_its_descriptor(self):
        self.install()
        folder = self.skills / 't3-imps'
        shutil_rmtree(folder / 'agents')
        before = len(os.listdir('/dev/fd'))
        real_listdir = os.listdir

        def failing(target):
            if isinstance(target, int):
                raise OSError(5, 'injected')
            return real_listdir(target)
        with skills.Adapter(folder) as adapter, mock.patch.object(skills.os, 'listdir', failing), \
                self.assertRaises(OSError):
            adapter.sub('agents', create=True)
        self.assertEqual(len(os.listdir('/dev/fd')), before)

if __name__ == '__main__':
    unittest.main()
