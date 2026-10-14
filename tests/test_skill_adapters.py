import hashlib
import json
from pathlib import Path
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
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/catalog.py'),
                                 '--prefix', str(self.prefix), '--agents-root', str(self.agents), *args],
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
        self.assertIn('For imps, a task without an operation means `run <task>`.', adapter.read_text())
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
        self.assertEqual(len(result.stdout.splitlines()), 6)
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
        imps = (self.skills / 't3-imps/SKILL.md').read_text().split('---\n', 2)[1]
        for hint in ('run <task>', 'resume <run-id>', 'checklist <path>',
                     'issues <number> [<number> ...]', 'discussion <number or URL>',
                     'add --personas before or after any request'):
            self.assertIn(hint, imps)

    def test_modified_snapshot_is_not_registered(self):
        self.call('install', 'imps')
        (self.prefix / 'imps/current/entry.md').write_text('changed')
        self.call('skills', 'install', 'imps', '--root', str(self.skills), code=2)
        self.assertFalse(self.skills.exists())

    def test_prompt_forwards_panel_flags(self):
        self.call('install', 'imps')
        prompt = self.call('prompt', 'imps', '--personas', '42', '43').stdout
        self.assertIn('run: --personas 42 43', prompt)

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

    def swap_agents_after_validation(self):
        """Patch `managed` so agents/ becomes a link to an external directory right
        after the ownership check passes: the window a racing process would use."""
        external = self.base / 'external-agents'
        external.mkdir()
        (external / 'openai.yaml').write_text('external')
        original = skills.managed

        def racing(directory, *args, **kwargs):
            receipt = original(directory, *args, **kwargs)
            agents = directory / 'agents'
            for item in agents.iterdir():
                item.unlink()
            agents.rmdir()
            agents.symlink_to(external, target_is_directory=True)
            return receipt
        return external, mock.patch.object(skills, 'managed', racing)

    def test_agents_swapped_for_a_symlink_after_validation_is_never_followed(self):
        meta = json.loads((ROOT / 'plugins/imps/plugin.json').read_text())
        for action in ('install', 'uninstall'):
            with self.subTest(action=action):
                self.install()
                external, patch = self.swap_agents_after_validation()
                with patch, self.assertRaises(ValueError):
                    if action == 'install':
                        skills.install(self.skills, self.prefix, meta)
                    else:
                        skills.uninstall(self.skills, meta)
                self.assertEqual([p.name for p in external.iterdir()], ['openai.yaml'])
                self.assertEqual((external / 'openai.yaml').read_text(), 'external')
                (self.skills / 't3-imps/agents').unlink()
                for item in external.iterdir():
                    item.unlink()
                external.rmdir()
                shutil_rmtree(self.skills / 't3-imps')

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

    def test_swap_after_the_directories_are_opened_cannot_redirect_writes_or_deletes(self):
        self.install()
        folder = self.skills / 't3-imps'
        external = self.base / 'external-agents'
        external.mkdir()
        (external / 'openai.yaml').write_text('external')
        original = skills.open_dirs

        def racing(directory, sub, create=False):
            fds = original(directory, sub, create)
            agents = directory / sub
            agents.rename(directory / 'agents-detached')  # the pinned fd follows the directory
            agents.symlink_to(external, target_is_directory=True)
            return fds
        for action in ('write', 'remove'):
            with self.subTest(action=action), mock.patch.object(skills, 'open_dirs', racing):
                if action == 'write':
                    skills.write_extra(folder, 'agents/openai.yaml', b'ours')
                    self.assertEqual((folder / 'agents-detached/openai.yaml').read_bytes(), b'ours')
                else:
                    skills.remove_extra(folder, 'agents/openai.yaml')
                    self.assertFalse((folder / 'agents-detached/openai.yaml').exists())
            self.assertEqual((external / 'openai.yaml').read_text(), 'external')
            (folder / 'agents').unlink()
            (folder / 'agents-detached').rename(folder / 'agents')

if __name__ == '__main__':
    unittest.main()
