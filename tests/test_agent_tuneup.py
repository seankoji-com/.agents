"""Fail-closed parsing and secret-safe, read-only settings audit receipts."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/agent-tuneup/scripts/audit.py'
spec = importlib.util.spec_from_file_location('settings_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTest(unittest.TestCase):
    def test_claude_exact_duplicates_and_broad_rules(self):
        findings = audit.inspect('claude', {'permissions': {'allow': ['Bash(python3 *)', 'Read(file)', 'Read(file)', 'Bash(git status)']}})
        self.assertEqual([f['code'] for f in findings], ['broad_execution_allow', 'duplicate_rule'])

    def test_quote_variants_are_not_deduplicated(self):
        self.assertEqual(audit.inspect('claude', {'permissions': {'allow': ['Bash(cat "x")', "Bash(cat 'x')"]}}), [])

    def test_opencode_jsonc_preserves_strings_and_reports_global_allow(self):
        raw = '{/* comment */"url":"https://example.com/a,}","permission":{"*":"allow",},// comment\n}'
        data = json.loads(audit.jsonc(raw))
        self.assertEqual(data['url'], 'https://example.com/a,}')
        self.assertEqual(audit.inspect('opencode', data)[0]['code'], 'all_tools_allowed')

    def test_codex_profiles_are_audited_without_exposing_names(self):
        findings = audit.inspect('codex', {'profiles': {'private-project': {'sandbox_mode': 'danger-full-access'}}})
        self.assertEqual(findings, [{'code': 'sandbox_disabled', 'location': 'profiles[0].sandbox_mode'}])

    def test_cli_never_writes_or_echoes_secrets_even_on_parse_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            for content, code in [('{"apiKey":"secret-fixture","permissions":{"allow":["Bash(*)"]}}', 1),
                                  ('{"secret-fixture": invalid}', 2), ('[]', 2)]:
                path.write_text(content)
                result = subprocess.run([sys.executable, str(SCRIPT), '--provider', 'claude', '--settings', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, code)
                self.assertNotIn('secret-fixture', result.stdout + result.stderr)
                self.assertEqual(path.read_text(), content)

    def test_malformed_types_fail(self):
        for data in ({'permissions': []}, {'permissions': {'allow': '*'}}):
            with self.assertRaises(ValueError):
                audit.inspect('claude', data)

    def test_muse_profiles_are_audited_without_exposing_names(self):
        # Shapes and values verified against the Muse 1.4.7 binary: flat
        # settings.json, permissions.profiles with approval/filesystem/
        # network/reviewer dimensions.
        findings = audit.inspect('muse', {'permissions': {'schema_version': 1, 'profiles': {
            'private-profile': {'approval': 'allow_all', 'filesystem': 'unrestricted',
                                'network': {'mode': 'enabled'}, 'reviewer': 'none'}}}})
        self.assertEqual(findings, [
            {'code': 'approvals_disabled', 'location': 'permissions.profiles[0].approval'},
            {'code': 'sandbox_disabled', 'location': 'permissions.profiles[0].filesystem'},
            {'code': 'network_unrestricted', 'location': 'permissions.profiles[0].network.mode'},
        ])

    def test_muse_restrictive_profile_and_absent_permissions_are_clean(self):
        self.assertEqual(audit.inspect('muse', {'model': 'synthetic'}), [])
        self.assertEqual(audit.inspect('muse', {'permissions': {'schema_version': 1, 'profiles': {
            'safe': {'approval': 'on_request', 'filesystem': {'allow': []},
                     'network': {'mode': 'proxy_only'}, 'reviewer': 'human'}}}}), [])

    def test_muse_malformed_types_fail(self):
        for data in ({'permissions': []}, {'permissions': {'profiles': []}},
                     {'permissions': {'profiles': {'p': []}}},
                     {'permissions': {'profiles': {'p': {'approval': 1}}}},
                     {'permissions': {'profiles': {'p': {'network': {'mode': 1}}}}},
                     {'permissions': {'profiles': {'p': {'filesystem': 1}}}}):
            with self.assertRaises(ValueError):
                audit.inspect('muse', data)

    def test_muse_cli_exit_codes_and_adapter_listing(self):
        listed = subprocess.run([sys.executable, str(SCRIPT), '--list-adapters'], capture_output=True, text=True)
        self.assertEqual(json.loads(listed.stdout)['muse'], 'JSON')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({'permissions': {'schema_version': 1, 'profiles': {
                'p': {'approval': 'allow_all'}}}}))
            result = subprocess.run([sys.executable, str(SCRIPT), '--provider', 'muse', '--settings', str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['findings'][0]['code'], 'approvals_disabled')


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True,
                   env={**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                        # No detached auto-maintenance: it writes under .git while tests compare trees.
                        'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'gc.auto', 'GIT_CONFIG_VALUE_0': '0',
                        'GIT_CONFIG_KEY_1': 'maintenance.auto', 'GIT_CONFIG_VALUE_1': 'false'})


class WorktreeBootstrapTest(unittest.TestCase):
    """`audit --t3-projects`: worktree-mode projects whose new worktrees start without deps."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def repo(self, name, tracked=(), untracked=(), t3_json=None):
        root = self.base / name
        root.mkdir()
        git(root, 'init', '-q')
        for path in tracked:
            (root / path).write_text('lock\n')
        if t3_json is not None:
            (root / 't3.json').write_text(json.dumps(t3_json))
            tracked = (*tracked, 't3.json')
        if tracked:
            git(root, 'add', *tracked)
            git(root, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'fixture')
        for path in untracked:
            (root / path).write_text('lock\n')
        return root

    def project(self, root, scripts=(), mode=None, **extra):
        return {'id': 'project-' + root.name, 'title': root.name, 'workspaceRoot': str(root),
                'defaultThreadEnvMode': mode, 'scripts': None if scripts is None else list(scripts),
                'deletedAt': None, **extra}

    def snapshot(self, *projects, mode='worktree'):
        return {'environment': {'preferences': {'defaultThreadEnvMode': mode}}, 'projects': list(projects)}

    def codes(self, snapshot):
        findings, _ = audit.inspect_projects(snapshot)
        return [f['project_id'] for f in findings]

    def test_worktree_project_with_tracked_lockfile_and_no_setup_is_flagged_with_a_draft(self):
        npm = self.repo('npm', tracked=['package-lock.json'])
        findings, unchecked = audit.inspect_projects(self.snapshot(self.project(npm)))
        self.assertEqual(unchecked, [])
        [finding] = findings
        self.assertEqual(finding['code'], 'worktree-bootstrap-missing')
        self.assertEqual(finding['location'], 'projects[0]')
        self.assertEqual(finding['mode_source'], 'environment')
        self.assertEqual(finding['lockfiles'], ['package-lock.json'])
        self.assertEqual(finding['t3_json'], 'absent')
        self.assertEqual(finding['draft_t3_json'], {'scripts': [{
            'name': 'Setup Worktree', 'command': 'node "$HOME/.local/bin/t3-setup-worktree.mjs"',
            'icon': 'configure', 'runOnWorktreeCreate': True, 'async': False}]})
        self.assertEqual(finding['draft_saved_script']['id'], 'setup-worktree')
        self.assertIn('t3_project_update', finding['import'])
        self.assertIn('Actions', finding['import'])

    def test_every_lockfile_kind_and_async_choice(self):
        for name, is_async in (('pnpm-lock.yaml', False), ('package-lock.json', False), ('bun.lock', False),
                               ('uv.lock', False), ('go.mod', True)):
            with self.subTest(lockfile=name):
                root = self.repo(name.replace('.', '-'), tracked=[name])
                [finding], _ = audit.inspect_projects(self.snapshot(self.project(root)))
                self.assertEqual(finding['lockfiles'], [name])
                self.assertIs(finding['draft_t3_json']['scripts'][0]['async'], is_async)
        mixed = self.repo('mixed', tracked=['go.mod', 'package-lock.json'])
        [finding], _ = audit.inspect_projects(self.snapshot(self.project(mixed)))
        self.assertIs(finding['draft_t3_json']['scripts'][0]['async'], False)

    def test_untracked_lockfiles_and_nested_lockfiles_do_not_count(self):
        ignored = self.repo('ignored-uv', untracked=['uv.lock', 'package-lock.json'])
        nested = self.repo('nested', tracked=['README'])
        (nested / 'app').mkdir()
        (nested / 'app/package-lock.json').write_text('lock\n')
        git(nested, 'add', 'app/package-lock.json')
        self.assertEqual(self.codes(self.snapshot(self.project(ignored), self.project(nested))), [])

    def test_saved_setup_script_clears_and_t3_json_only_script_needs_importing(self):
        setup = {'name': 'Setup', 'command': 'make deps', 'icon': 'configure', 'runOnWorktreeCreate': True}
        in_file = self.repo('in-file', tracked=['pnpm-lock.yaml'], t3_json={'scripts': [setup]})
        saved = self.repo('saved', tracked=['pnpm-lock.yaml'])
        other = self.repo('other', tracked=['pnpm-lock.yaml'],
                          t3_json={'scripts': [dict(setup, runOnWorktreeCreate=False)]})
        findings, _ = audit.inspect_projects(self.snapshot(
            self.project(in_file), self.project(saved, scripts=[dict(setup, id='s')]), self.project(other)))
        self.assertEqual([(f['project_id'], f['code']) for f in findings],
                         [('project-in-file', 'worktree-bootstrap-not-imported'),
                          ('project-other', 'worktree-bootstrap-missing')])
        self.assertNotIn('draft_t3_json', findings[0])
        self.assertIn('t3_project_update', findings[0]['import'])
        self.assertEqual(findings[1]['t3_json'], 'tracked')
        # A t3.json setup script that the saved scripts also hold is fully imported.
        both = self.project(in_file, scripts=[dict(setup, id='s')])
        self.assertEqual(self.codes(self.snapshot(both)), [])

    def test_draft_saved_script_id_avoids_existing_ids_and_null_scripts_are_empty(self):
        root = self.repo('ids', tracked=['package-lock.json'])
        taken = [{'id': 'setup-worktree', 'name': 'Old', 'command': 'true', 'icon': 'configure',
                  'runOnWorktreeCreate': False},
                 {'id': 'setup-worktree-2', 'name': 'Older', 'command': 'true', 'icon': 'play',
                  'runOnWorktreeCreate': False}]
        [finding], _ = audit.inspect_projects(self.snapshot(self.project(root, scripts=taken)))
        self.assertEqual(finding['draft_saved_script']['id'], 'setup-worktree-3')
        [finding], _ = audit.inspect_projects(self.snapshot(self.project(root, scripts=None)))
        self.assertEqual(finding['draft_saved_script']['id'], 'setup-worktree')

    def test_project_rooted_in_a_repository_subdirectory_checks_its_own_root(self):
        repo = self.repo('mono', tracked=['README'])
        app = repo / 'apps/web'
        app.mkdir(parents=True)
        (app / 'pnpm-lock.yaml').write_text('lock\n')
        git(repo, 'add', 'apps/web/pnpm-lock.yaml')
        [finding], _ = audit.inspect_projects(self.snapshot(self.project(app)))
        self.assertEqual(finding['lockfiles'], ['pnpm-lock.yaml'])
        self.assertEqual(self.codes(self.snapshot(self.project(repo))), [])

    def test_thread_mode_resolution_project_then_environment_then_t3_json(self):
        root = self.repo('modes', tracked=['package-lock.json'])
        self.assertEqual(self.codes(self.snapshot(self.project(root, mode='local'))), [])
        self.assertEqual(self.codes(self.snapshot(self.project(root, mode='worktree'), mode='local')),
                         ['project-modes'])
        self.assertEqual(self.codes(self.snapshot(self.project(root), mode='local')), [])
        self.assertEqual(self.codes(self.snapshot(self.project(root), mode=None)), [])
        from_file = self.repo('from-file', tracked=['package-lock.json'],
                              t3_json={'defaultThreadEnvMode': 'worktree', 'scripts': []})
        [finding], _ = audit.inspect_projects(self.snapshot(self.project(from_file), mode=None))
        self.assertEqual(finding['mode_source'], 't3.json')

    def test_unavailable_deleted_and_invalid_projects(self):
        good = self.repo('good', tracked=['package-lock.json'])
        broken = self.repo('broken', tracked=['package-lock.json'])
        (broken / 't3.json').write_text('{not json')
        plain = self.base / 'not-a-repo'
        plain.mkdir()
        findings, unchecked = audit.inspect_projects(self.snapshot(
            self.project(good, deletedAt='2026-10-01T00:00:00Z'), self.project(broken),
            {'id': 'gone', 'workspaceRoot': str(self.base / 'missing'), 'scripts': []},
            {'id': 'relative', 'workspaceRoot': 'repos/x', 'scripts': []}, self.project(plain)))
        self.assertEqual(findings, [])
        self.assertEqual(unchecked, [
            {'location': 'projects[1]', 'reason': 'workspace_unreadable'},
            {'location': 'projects[2]', 'reason': 'workspace_unavailable'},
            {'location': 'projects[3]', 'reason': 'workspace_unavailable'},
            {'location': 'projects[4]', 'reason': 'workspace_unreadable'}])
        for bad in ([], {'projects': {}}, {'projects': [1]}, {'environment': [], 'projects': []},
                    {'projects': [{'scripts': {}}]}):
            with self.subTest(snapshot=bad), self.assertRaises(ValueError):
                audit.inspect_projects(bad)

    def test_cli_is_read_only_and_never_prints_paths_or_titles(self):
        root = self.repo('private-title', tracked=['package-lock.json'])
        snapshot = self.base / 'snapshot.json'
        snapshot.write_text(json.dumps(self.snapshot(self.project(root))))

        def state():
            return {p.relative_to(self.base): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}

        before = state()
        result = subprocess.run([sys.executable, str(SCRIPT), '--t3-projects', str(snapshot)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['writes'], 0)
        self.assertEqual(receipt['findings'][0]['code'], 'worktree-bootstrap-missing')
        self.assertNotIn(str(self.base), result.stdout)
        self.assertNotIn('private-title', result.stdout.replace('project-private-title', ''))
        self.assertEqual(state(), before)
        self.assertFalse((root / 't3.json').exists())
        snapshot.write_text('{"projects": "secret-fixture"}')
        bad = subprocess.run([sys.executable, str(SCRIPT), '--t3-projects', str(snapshot)],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertNotIn('secret-fixture', bad.stdout + bad.stderr)
        clean = self.repo('clean', tracked=['README'])
        snapshot.write_text(json.dumps(self.snapshot(self.project(clean))))
        ok = subprocess.run([sys.executable, str(SCRIPT), '--t3-projects', str(snapshot)],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        mixed = subprocess.run([sys.executable, str(SCRIPT), '--t3-projects', str(snapshot),
                                '--provider', 'claude'], capture_output=True, text=True)
        self.assertEqual(mixed.returncode, 2)

if __name__ == '__main__':
    unittest.main()
