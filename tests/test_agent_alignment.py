"""Provider coverage, private comparison receipts, and approved native writes."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/agent-tuneup/scripts/align.py'
spec = importlib.util.spec_from_file_location('agent_alignment', SCRIPT)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
HAS_TOML = importlib.util.find_spec('tomllib') is not None


class AlignmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def file(self, name, raw):
        path = self.root / name
        path.write_bytes(raw.encode())
        path.chmod(0o600)
        return path

    def proposal(self, adapter='claude', before=None, after=None, keys=None):
        before = before if before is not None else '{"permissions":{"allow":["Read(*)"]},"env":{"TOKEN":"fixture-secret"}}'
        after = after if after is not None else '{"permissions":{"allow":[]},"env":{"TOKEN":"fixture-secret"}}'
        self.target = self.file('target', before)
        self.candidate = self.file('candidate', after)
        return align.prepare(adapter, str(self.target), str(self.candidate), keys or ['/permissions/allow'])[0]

    def test_all_catalog_instances_remain_visible_including_disabled_and_future(self):
        path = self.file('settings', '{"mcpServers":{"private-name":{"url":"https://example.invalid/fixture-secret"}}}')
        catalog = {'providers': [{'providerInstanceId': p, 'canRunChildTask': p != 'future'}
                                 for p in ['claude', 'ag', 'future']]}
        inventory = {'version': 1, 'providers': [
            {'provider_instance_id': 'claude', 'adapter': 'claude', 'sources': [{'path': str(path), 'scope': 'global'}]},
            {'provider_instance_id': 'ag', 'adapter': 'antigravity', 'sources': [{'path': str(path), 'scope': 'global'}]},
        ], 'capabilities': [{'kind': 'mcp', 'members': {'claude': 'private-name', 'ag': 'private-name'}}]}
        result = align.compare(catalog, inventory)
        self.assertEqual(len(result['providers']), 3)
        self.assertFalse(result['providers'][2]['catalog_runnable'])
        self.assertEqual(result['capabilities'][0]['states'], ['configured', 'configured', 'unmapped'])
        self.assertEqual(result['providers'][1]['sources'][0]['permissions'], 'manual')
        rendered = json.dumps(result)
        for secret in ['fixture-secret', 'private-name', str(path), 'example.invalid']:
            self.assertNotIn(secret, rendered)

    def test_conflicting_scopes_and_failed_layers_do_not_claim_alignment(self):
        enabled = self.file('global', '{"mcp":{"repo":{"enabled":true}}}')
        disabled = self.file('project', '{"mcp":{"repo":{"enabled":false}}}')
        catalog = {'providers': [{'providerInstanceId': 'oc'}]}
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'oc', 'adapter': 'opencode',
                     'sources': [{'path': str(enabled), 'scope': 'global'}, {'path': str(disabled), 'scope': 'project'}]}],
                     'capabilities': [{'kind': 'mcp', 'members': {'oc': 'repo'}}]}
        self.assertEqual(align.compare(catalog, inventory)['capabilities'][0]['states'], ['scope_conflict'])
        disabled.write_text('{"fixture-secret": broken}')
        self.assertEqual(align.compare(catalog, inventory)['capabilities'][0]['states'], ['unknown'])

    def test_plugin_identity_policies_are_not_installation_evidence(self):
        if not HAS_TOML:
            self.skipTest('Codex TOML requires Python 3.11+')
        data = align.parse('codex', b'[plugins.repo]\nenabled = true\n[mcp_servers.repo]\nenabled = false\n')
        self.assertEqual(align.resources('codex', data), {'mcp': {'repo': 'disabled'}, 'plugin': {}})
        self.assertEqual(align.resources('claude', {'enabledPlugins': {'repo@store': False}})['plugin'], {'repo@store': 'disabled'})
        self.assertEqual(align.resources('opencode', {'plugin': ['repo@1.0']})['plugin'], {'repo@1.0': 'configured'})

    def test_invalid_types_and_unknown_instances_fail_closed(self):
        for adapter, raw in [('claude', b'{"mcpServers":[]}'), ('opencode', b'{"plugin":{}}'),
                             ('antigravity', b'{"mcpServers":{"x":{"disabled":"false"}}}'),
                             ('claude', b'{"enabledPlugins":{"x":1}}')]:
            with self.subTest(adapter=adapter, raw=raw), self.assertRaises(ValueError):
                align.parse(adapter, raw)
        with self.assertRaises(ValueError):
            align.compare({'providers': []}, {'version': 1, 'providers': [{'provider_instance_id': 'unknown'}]})

    def test_missing_tomllib_is_explicit_in_comparison_and_plan_parsing(self):
        path = self.file('config.toml', 'approval_policy = "on-request"')
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'codex', 'adapter': 'codex',
                     'sources': [{'path': str(path), 'scope': 'global'}]}]}
        with patch.dict(sys.modules, {'tomllib': None}):
            with self.assertRaisesRegex(ValueError, 'python_3_11_required'):
                align.parse('codex', path.read_bytes())
            result = align.compare({'providers': [{'providerInstanceId': 'codex'}]}, inventory)
        self.assertEqual(result['providers'][0]['sources'][0]['error'], 'python_3_11_required')

    def test_approved_apply_preserves_exact_candidate_backup_and_mode(self):
        plan = self.proposal()
        original = self.target.read_bytes()
        candidate = self.candidate.read_bytes()
        backup = self.root / 'backup'
        receipt = align.apply(plan, plan['approval_digest'], str(backup))
        self.assertEqual(self.target.read_bytes(), candidate)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertEqual(receipt['live_acceptance'], 'not_run')
        self.assertNotIn('fixture-secret', json.dumps(receipt))
        self.assertEqual(list(self.root.glob('.t3-tuneup-*')), [])

    def test_stale_target_candidate_identity_and_approval_refuse_writes(self):
        for mutation in ['target', 'candidate', 'identity', 'approval', 'plan']:
            with self.subTest(mutation=mutation):
                plan = self.proposal()
                approval = plan['approval_digest']
                if mutation in {'target', 'candidate'}:
                    path = getattr(self, mutation)
                    path.write_bytes(path.read_bytes() + b'\n')
                elif mutation == 'identity':
                    raw = self.target.read_bytes()
                    replacement = self.file('replacement', raw.decode())
                    os.replace(replacement, self.target)
                elif mutation == 'approval':
                    approval = 'wrong'
                else:
                    plan['changed_keys'] = ['/env']
                current = self.target.read_bytes()
                with self.assertRaises(ValueError):
                    align.apply(plan, approval, str(self.root / 'backup'))
                self.assertEqual(self.target.read_bytes(), current)
                self.assertFalse((self.root / 'backup').exists())

    def test_unrelated_changes_unknown_roots_and_partial_approval_are_rejected(self):
        for after, keys in [
            ('{"permissions":{"allow":[]},"env":{"TOKEN":"other"}}', ['/permissions/allow']),
            ('{"permissions":{"allow":[]},"env":{"TOKEN":"other"}}', ['/permissions/allow', '/env/TOKEN']),
            ('{"permissions":{"allow":[]},"env":{"TOKEN":"fixture-secret"}}', ['/permissions']),
        ]:
            with self.subTest(after=after, keys=keys), self.assertRaises(ValueError):
                self.proposal(after=after, keys=keys)

    def test_nested_boolean_numeric_changes_cannot_hide_unrelated_edits(self):
        with self.assertRaises(ValueError):
            self.proposal(before='{"permissions":{"allow":["Read(*)"]},"other":[{"x":true}]}',
                          after='{"permissions":{"allow":[]},"other":[{"x":1}]}')
        changes = align.changed_paths({'mcpServers': {'repo': {'args': [True]}}},
                                      {'mcpServers': {'repo': {'args': [1]}}})
        self.assertEqual(changes, [('mcpServers', 'repo', 'args')])

    def test_symlinks_hardlinks_fifo_and_existing_backup_refused(self):
        plan = self.proposal()
        link = self.root / 'link'
        link.symlink_to(self.target)
        with self.assertRaises(ValueError):
            align.prepare('claude', str(link), str(self.candidate), ['/permissions/allow'])
        folder_link = self.root / 'folder'
        folder_link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            align.prepare('claude', str(folder_link / 'target'), str(self.candidate), ['/permissions/allow'])
        link.unlink()
        os.link(self.target, link)
        with self.assertRaises(ValueError):
            align.prepare('claude', str(self.target), str(self.candidate), ['/permissions/allow'])
        link.unlink()
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            align.prepare('claude', str(fifo), str(self.candidate), ['/permissions/allow'])
        backup = self.file('backup', 'existing')
        with self.assertRaises(FileExistsError):
            align.apply(plan, plan['approval_digest'], str(backup))
        self.assertEqual(backup.read_text(), 'existing')

    def test_second_preflight_detects_concurrent_edit_and_keeps_backup(self):
        plan = self.proposal()
        real_write = align.write_private
        def mutate_after_backup(path, raw):
            real_write(path, raw)
            self.target.write_text('{}')
        with patch.object(align, 'write_private', mutate_after_backup), self.assertRaises(ValueError):
            align.apply(plan, plan['approval_digest'], str(self.root / 'backup'))
        self.assertEqual(self.target.read_text(), '{}')
        self.assertTrue((self.root / 'backup').exists())
        self.assertEqual(list(self.root.glob('.t3-tuneup-*')), [])

    def test_jsonc_and_toml_native_candidates_preserve_comments_and_unrelated_keys(self):
        cases = [
            ('opencode', '{/* kept */"permission":"ask","model":"fixture/model"}',
             '{/* kept */"permission":"deny","model":"fixture/model"}', ['/permission']),
            ('codex', '# kept\napproval_policy = "never"\nmodel = "fixture"\n',
             '# kept\napproval_policy = "on-request"\nmodel = "fixture"\n', ['/approval_policy']),
            ('antigravity', '{/* kept */"mcpServers":{}}', '{/* kept */"mcpServers":{"repo":{"command":"fixture","disabled":true}},}', ['/mcpServers/repo']),
        ]
        for adapter, before, after, keys in cases:
            with self.subTest(adapter=adapter):
                if adapter == 'codex' and not HAS_TOML:
                    continue
                plan = self.proposal(adapter, before, after, keys)
                backup = self.root / (adapter + '-backup')
                align.apply(plan, plan['approval_digest'], str(backup))
                self.assertEqual(self.target.read_text(), after)

    def test_new_risky_permissions_are_rejected_in_top_level_and_overrides(self):
        cases = [
            ('claude', '{"permissions":{"allow":[]}}',
             '{"permissions":{"allow":["Bash"],"defaultMode":"bypassPermissions"}}',
             ['/permissions/allow', '/permissions/defaultMode']),
            ('claude', '{"sandbox":{"enabled":true}}', '{"sandbox":{"enabled":false}}', ['/sandbox/enabled']),
            ('opencode', '{"agent":{"build":{"permission":{"bash":"ask"}}}}',
             '{"agent":{"build":{"permission":{"bash":"allow"}}}}', ['/agent/build/permission/bash']),
        ]
        if HAS_TOML:
            cases.append(('codex', '[profiles.work]\napproval_policy = "on-request"\n',
                          '[profiles.work]\napproval_policy = "never"\n', ['/profiles/work/approval_policy']))
        for adapter, before, after, keys in cases:
            with self.subTest(adapter=adapter), self.assertRaisesRegex(ValueError, 'new_risky_permission_patterns'):
                self.proposal(adapter, before, after, keys)

    def test_protection_deletions_and_broad_rule_substitution_are_refused(self):
        cases = [
            ('claude', '{"sandbox":{"enabled":true}}', '{}', ['/sandbox']),
            ('claude', '{"permissions":{"deny":["Bash(rm:*)"]}}', '{"permissions":{"deny":[]}}', ['/permissions/deny']),
            ('claude', '{"permissions":{"allow":["Bash(*)","Bash(*)"]}}', '{"permissions":{"allow":["Bash(*)","*"]}}', ['/permissions/allow']),
            ('claude', '{"sandbox":{}}', '{"sandbox":{"allowUnsandboxedCommands":true}}', ['/sandbox/allowUnsandboxedCommands']),
            ('claude', '{}', '{"enableAllProjectMcpServers":true}', ['/enableAllProjectMcpServers']),
            ('opencode', '{"permission":{"bash":"ask","*":"ask"}}', '{"permission":{}}', ['/permission/*','/permission/bash']),
            ('opencode', '{"agent":{"build":{"permission":"ask"}}}', '{"agent":{}}', ['/agent/build']),
        ]
        if HAS_TOML:
            cases.extend([
                ('codex', 'sandbox_mode = "workspace-write"', '', ['/sandbox_mode']),
                ('codex', '[sandbox_workspace_write]\nnetwork_access = false\n',
                 '[sandbox_workspace_write]\nnetwork_access = true\n', ['/sandbox_workspace_write/network_access']),
            ])
        for adapter, before, after, keys in cases:
            with self.subTest(adapter=adapter, before=before), self.assertRaises(ValueError):
                self.proposal(adapter, before, after, keys)

    def test_equal_aggregate_counts_cannot_move_broad_grants_to_other_scopes(self):
        with self.assertRaisesRegex(ValueError, 'new_risky_permission_patterns'):
            self.proposal('opencode',
                          '{"permission":{"bash":"allow"},"agent":{"a":{"permission":{"bash":"allow"}}}}',
                          '{"permission":{"bash":"allow"},"agent":{"a":{"permission":{"external_directory":"allow"}}}}',
                          ['/agent/a/permission/bash', '/agent/a/permission/external_directory'])
        if HAS_TOML:
            with self.assertRaisesRegex(ValueError, 'new_risky_permission_patterns'):
                self.proposal('codex',
                              'approval_policy = "never"\n[profiles.a]\napproval_policy = "on-request"\n',
                              '[profiles.a]\napproval_policy = "never"\n',
                              ['/approval_policy', '/profiles/a/approval_policy'])
            old = {'profiles': {'a': {'approval_policy': 'never'}, 'b': {'approval_policy': 'on-request'}}}
            new = {'profiles': {'b': {'approval_policy': 'on-request'}, 'a': {'approval_policy': 'never'}}}
            self.assertEqual(align.risk_locations('codex', old), align.risk_locations('codex', new))

    def test_claude_tightening_and_reordering_preserve_broad_rule_identity(self):
        for before, after in [
            (["Read(x)", "Bash"], ["Bash"]),
            (["Bash", "Read(x)"], ["Read(x)", "Bash"]),
        ]:
            plan = self.proposal('claude', json.dumps({'permissions': {'allow': before}}),
                                 json.dumps({'permissions': {'allow': after}}), ['/permissions/allow'])
            self.assertEqual(plan['risk_patterns_before'], plan['risk_patterns_after'])
        self.assertEqual(align.risk_locations('opencode', {'permission': 'allow'}),
                         align.risk_locations('opencode', {'permission': {'*': 'allow'}}))

    def test_hook_commands_are_outside_automatic_apply(self):
        candidate = json.dumps({'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [
            {'type': 'command', 'command': 'fixture-command'}]}]}})
        with self.assertRaisesRegex(ValueError, 'unsupported_or_empty_change'):
            self.proposal('claude', '{}', candidate, ['/hooks'])

    def test_nested_policy_changes_work_without_changing_model_identity(self):
        cases = [('opencode', '{"agent":{"build":{"permission":{"bash":"allow"},"model":"fixture"}}}',
                  '{"agent":{"build":{"permission":{"bash":"ask"},"model":"fixture"}}}', ['/agent/build/permission/bash'])]
        if HAS_TOML:
            cases.append(('codex', '[profiles.work]\napproval_policy = "never"\nmodel = "fixture"\n',
                          '[profiles.work]\napproval_policy = "on-request"\nmodel = "fixture"\n', ['/profiles/work/approval_policy']))
        for adapter, before, after, keys in cases:
            plan = self.proposal(adapter, before, after, keys)
            self.assertTrue(plan['risk_patterns_before'])
            self.assertFalse(plan['risk_patterns_after'])
        with self.assertRaisesRegex(ValueError, 'unsupported_or_empty_change'):
            self.proposal('opencode', '{"agent":{}}', '{"agent":{"build":{"permission":"ask","model":"other"}}}', ['/agent/build'])

    def test_claude_disable_lists_and_nested_project_definitions_remain_visible(self):
        catalog = {'providers': [{'providerInstanceId': 'claude'}]}
        server = self.file('mcp.json', '{"mcpServers":{"repo":{"command":"fixture"}}}')
        disabled = self.file('settings.json', '{"disabledMcpjsonServers":["repo"]}')
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'claude', 'adapter': 'claude',
                     'sources': [{'path': str(server), 'scope': 'project'}, {'path': str(disabled), 'scope': 'global'}]}],
                     'capabilities': [{'kind': 'mcp', 'members': {'claude': 'repo'}}]}
        self.assertEqual(align.compare(catalog, inventory)['capabilities'][0]['states'], ['scope_conflict'])
        server.write_text('{"projects":{"/fixture/project":{"mcpServers":{"repo":{"command":"fixture"}}}}}')
        self.assertEqual(align.compare(catalog, inventory)['capabilities'][0]['states'], ['unknown'])

    def test_compare_fifo_returns_invalid_instead_of_blocking(self):
        source = self.root / 'fifo-source'
        os.mkfifo(source)
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'claude', 'adapter': 'claude',
                     'sources': [{'path': str(source), 'scope': 'global'}]}]}
        result = align.compare({'providers': [{'providerInstanceId': 'claude'}]}, inventory)
        self.assertEqual(result['providers'][0]['sources'][0]['status'], 'unreadable_or_invalid')

    def test_cli_plan_is_private_and_failures_never_echo_parser_values(self):
        plan = self.proposal()
        out = self.root / 'plan.json'
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'plan', '--adapter', 'claude',
                                 '--target', str(self.target), '--candidate', str(self.candidate),
                                 '--allow-key', '/permissions/allow', '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        self.assertNotIn('fixture-secret', result.stdout + result.stderr + out.read_text())
        self.candidate.write_text('{"fixture-secret":bad}')
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'apply', '--plan', str(out),
                                 '--approval', plan['approval_digest'], '--backup', str(self.root / 'backup')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('fixture-secret', result.stdout + result.stderr)
        self.assertNotIn(str(self.target), result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
