"""Sandbox grants never touch the owner's configuration; all paths are isolated."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
from learning_grants import grant


class GrantsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.env = dict(HOME=str(self.base / 'home'), XDG_CONFIG_HOME=str(self.base / 'config'),
                        XDG_STATE_HOME=str(self.base / 'state'))
        self.subtree = str(self.base / 'state/t3-plugins/learnings')

    def config(self, driver, raw):
        receipt = grant(driver, self.project, env=self.env)
        path = Path(receipt['config'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        return path

    def test_dry_setup_prints_grants_without_writing_anything(self):
        for driver in ('claudeAgent', 'codex', 'opencode'):
            result = grant(driver, self.project, env=self.env)
            self.assertEqual(result['status'], 'proposed')
            self.assertIn(self.subtree, json.dumps(result['grant']))
        self.assertEqual(list(self.base.iterdir()), [self.project])
        self.assertEqual(grant('unsupported', self.project, True, self.env)['status'], 'unavailable')

    def test_json_grants_preserve_sandbox_and_permission_settings_and_backup(self):
        fixtures = {
            'claudeAgent': {'sandbox': {'enabled': True, 'filesystem': {'denyRead': ['secret'], 'allowWrite': ['existing']}},
                            'permissions': {'defaultMode': 'default'}, 'env': {'KEEP': 'yes'}},
            'opencode': {'permission': {'edit': 'ask', 'bash': 'ask', 'external_directory': {'*': 'ask'}},
                         'theme': 'system'},
        }
        for driver, config in fixtures.items():
            raw = json.dumps(config)
            path = self.config(driver, raw)
            result = grant(driver, self.project, True, self.env)
            self.assertEqual(result['status'], 'applied', result)
            self.assertEqual(Path(result['backup']).read_text(), raw)
            updated = json.loads(path.read_text())
            if driver == 'claudeAgent':
                self.assertEqual(updated['sandbox']['filesystem']['allowWrite'], ['existing', self.subtree])
                updated['sandbox']['filesystem']['allowWrite'].remove(self.subtree)
            else:
                self.assertEqual(updated['permission']['external_directory'][self.subtree + '/**'], 'allow')
                del updated['permission']['external_directory'][self.subtree + '/**']
            self.assertEqual(updated, config)
            before = path.read_bytes()
            self.assertEqual(grant(driver, self.project, True, self.env)['status'], 'unchanged')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(path.parent.glob('*.pre-learnings-*'))), 1)

    @unittest.skipIf(sys.version_info < (3, 11), 'Codex config editing explicitly requires Python 3.11+')
    def test_codex_toml_preserves_unrelated_keys_and_only_adds_root(self):
        import tomllib
        raw = ('# retained comment\napproval_policy = "on-request"\nsandbox_mode = "workspace-write"\n'
               '[sandbox_workspace_write]\nnetwork_access = false\nwritable_roots = [\n "existing"\n]\n'
               '[other]\nvalue = "unchanged"\n')
        path = self.config('codex', raw)
        result = grant('codex', self.project, True, self.env)
        self.assertEqual(result['status'], 'applied', result)
        expected = tomllib.loads(raw)
        expected['sandbox_workspace_write']['writable_roots'].append(self.subtree)
        self.assertEqual(tomllib.loads(path.read_text()), expected)
        self.assertTrue(path.read_text().startswith('# retained comment'))
        self.assertEqual(Path(result['backup']).read_text(), raw)
        self.assertEqual(grant('codex', self.project, True, self.env)['status'], 'unchanged')

    def test_config_symlink_and_backup_failure_are_soft_and_preserve_active_config(self):
        path = self.config('claudeAgent', '{"sandbox":{"enabled":true}}')
        before = path.read_bytes()
        with mock.patch('learning_grants.atomic_file', side_effect=OSError('backup denied')):
            self.assertEqual(grant('claudeAgent', self.project, True, self.env)['status'], 'unavailable')
        self.assertEqual(path.read_bytes(), before)
        target = self.base / 'untouched'
        target.write_text('{}')
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(grant('claudeAgent', self.project, True, self.env)['status'], 'unavailable')
        self.assertEqual(target.read_text(), '{}')

    def test_unsupported_layout_and_pattern_path_are_not_widened(self):
        path = self.config('opencode', '{"permission":"ask"}')
        before = path.read_bytes()
        self.assertEqual(grant('opencode', self.project, True, self.env)['status'], 'unavailable')
        self.assertEqual(path.read_bytes(), before)
        env = dict(self.env, XDG_STATE_HOME=str(self.base / 'state*'))
        self.assertEqual(grant('claudeAgent', self.project, True, env)['status'], 'unavailable')
        env = dict(self.env, XDG_STATE_HOME=str(self.project / 'state'))
        self.assertEqual(grant('claudeAgent', self.project, True, env)['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
