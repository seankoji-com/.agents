"""Public defaults and deprecation through the real catalog and installed adapters."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_retired_plugins import owned_adapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import skills


class CommandDefaults(unittest.TestCase):
    def test_ape_infers_search_or_study_without_command_words(self):
        meta = skills.manifest_data.load(ROOT / 'plugins/ape/plugin.json')
        for text in ('', 'find retry approaches', 'study permission patterns', 'clean up error handling', 'clean architecture'):
            self.assertEqual(skills.route(meta, text), 'forage')
        for text in ('https://github.com/example/parser parser tests',
                     'compare our parser with https://github.com/example/parser',
                     'https://gitlab.com/example/parser'):
            self.assertEqual(skills.route(meta, text), 'study')
        # Unsupported hosts reach study's explicit capability check, never broad search.
        self.assertEqual(skills.route(meta, '--clean workspace --all'), 'clean')
        self.assertEqual(skills.route(meta, '--doctor'), 'doctor')
        self.assertEqual(skills.route(meta, 'clean https://github.com/example/parser'), 'study')

    def test_one_workflow_tuneup_has_no_public_mode_or_reserved_word_collisions(self):
        meta = skills.manifest_data.load(ROOT / 'plugins/agent-tuneup/plugin.json')
        for text in ('', 'scan our configuration', 'apply consistent wiring', 'only inspect this file'):
            self.assertEqual(skills.route(meta, text), 'tuneup')
        self.assertEqual(meta['operations'], ['tuneup'])
        adapter = skills.render(meta, Path('entry.md'))
        self.assertNotIn('Options:', adapter)
        self.assertNotIn('with one operation:', skills.openai_yaml(meta).decode())

    def test_deprecation_omits_old_plugin_and_preserves_modified_adapter_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            prefix, agents, root = base / 'prefix', base / 'agents', base / 'skills'
            state = base / 'state/elephant-goldfish'
            state.mkdir(parents=True)
            historical = state / 'existing.json'
            historical.write_text('{"receipt":"historical"}\n')
            old = owned_adapter(root, 'elephant-goldfish')
            (old / 'SKILL.md').write_text('Keep my local changes')
            env = {**os.environ, 'HOME': str(base), 'XDG_STATE_HOME': str(base / 'state')}
            def cli(*args):
                result = subprocess.run([sys.executable, ROOT / 'scripts/catalog.py', '--prefix', prefix,
                    '--agents-root', agents, *args], env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            listing = cli('list').stdout.splitlines()
            self.assertTrue(any(line.startswith('plan ') for line in listing))
            self.assertFalse(any(line.startswith('elephant-goldfish ') for line in listing))
            setup = cli('setup', 'plan', '--root', str(root))
            receipt = json.loads(setup.stdout.splitlines()[0])['data']
            self.assertIn('default workflow', receipt['paste'])
            self.assertNotIn('run: doctor', receipt['paste'])
            self.assertTrue((root / 'plan/SKILL.md').is_file())
            self.assertEqual((old / 'SKILL.md').read_text(), 'Keep my local changes')
            self.assertEqual(historical.read_text(), '{"receipt":"historical"}\n')
            # A pristine, owned adapter can be removed, without touching any old state.
            (old / 'SKILL.md').unlink()
            (old / '.t3-plugins-skill.json').unlink()
            old.rmdir()
            owned_adapter(root, 'elephant-goldfish')
            cli('setup', 'plan', '--root', str(root))
            self.assertFalse(old.exists())
            self.assertTrue(historical.exists())
            result = cli('install', 'elephant-goldfish')
            self.assertIn('deprecated; use plan', result.stderr)


if __name__ == '__main__':
    unittest.main()
