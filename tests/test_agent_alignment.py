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
        plan=align.prepare(adapter, str(self.target), str(self.candidate), keys or ['/permissions/allow'])[0]
        self.review_context=self.apply_context(plan)
        return plan

    def apply_reviewed(self,*args):
        with patch.dict(os.environ,self.review_env):
            return align.apply(*args)

    def apply_context(self, plan):
        from tests.test_rebuild_installed import Sandbox
        from tests.adopter_plan_review_fixtures import reviewed_apply_context
        if not hasattr(self,'review_box'):
            self.review_box=Sandbox(self.root/'review-fixture')
            self.review_package,self.review_manifest=self.review_box.install('agent-tuneup')
        context=reviewed_apply_context(self.review_box,self.review_package,self.review_manifest,plan)
        self.review_env = {k:self.review_box.env[k] for k in ('XDG_STATE_HOME','XDG_CONFIG_HOME','HOME')}
        return context

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
        enabled = self.file('global', '{"mcp":{"repo":{"type":"local","command":["fixture"],"enabled":true}}}')
        disabled = self.file('project', '{"mcp":{"repo":{"type":"local","command":["fixture"],"enabled":false}}}')
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
        receipt = self.apply_reviewed(plan, plan['approval_digest'], str(backup), self.review_context)
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
                    self.apply_reviewed(plan, approval, str(self.root / 'backup'), self.review_context)
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
            self.apply_reviewed(plan, plan['approval_digest'], str(backup), self.review_context)
        self.assertEqual(backup.read_text(), 'existing')

    def test_second_preflight_detects_concurrent_edit_and_keeps_backup(self):
        plan = self.proposal()
        real_write = align.write_private
        def mutate_after_backup(path, raw):
            real_write(path, raw)
            self.target.write_text('{}')
        with patch.object(align, 'write_private', mutate_after_backup), self.assertRaises(ValueError):
            self.apply_reviewed(plan, plan['approval_digest'], str(self.root / 'backup'), self.review_context)
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
                self.apply_reviewed(plan, plan['approval_digest'], str(backup), self.review_context)
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

    def test_opencode_permission_order_cannot_hide_behind_mcp_changes(self):
        for prefix in [(), ('agent', 'build')]:
            before = {'permission': {'bash': {'*': 'allow', 'rm *': 'deny'}}}
            after = {'permission': {'bash': {'rm *': 'deny', '*': 'allow'}}}
            if prefix:
                before = {'agent': {'build': before}}
                after = {'agent': {'build': after}}
            before['mcp'] = {}
            after['mcp'] = {'fixture': {'type': 'local', 'command': ['fixture-command']}}
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
                self.proposal('opencode', json.dumps(before), json.dumps(after), ['/mcp/fixture'])
            policy_key = '/agent/build/permission/bash' if prefix else '/permission/bash'
            with self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
                self.proposal('opencode', json.dumps(before), json.dumps(after), ['/mcp/fixture', policy_key])
        # Reordering retained patterns must remain visible alongside a new pattern.
        before = {'permission': {'bash': {'*': 'allow', 'rm *': 'deny'}}}
        after = {'permission': {'bash': {'rm *': 'deny', '*': 'allow', 'git *': 'ask'}}}
        self.assertEqual(align.changed_paths(before, after, adapter='opencode'), [('permission', 'bash')])
        self.assertEqual(align.changed_paths(before, {'permission': {'bash': {'rm *': 'deny', '*': 'allow'}}}, adapter='claude'), [])

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

    def test_claude_disabled_servers_plan_and_apply_match_inventory_support(self):
        plan = self.proposal('claude', '{"disabledMcpServers":[]}',
                             '{"disabledMcpServers":["fixture"]}', ['/disabledMcpServers'])
        backup = self.root / 'disable-backup'
        self.apply_reviewed(plan, plan['approval_digest'], str(backup), self.review_context)
        self.assertEqual(json.loads(self.target.read_text())['disabledMcpServers'], ['fixture'])
        self.assertEqual(align.resources('claude', json.loads(self.target.read_text()))['mcp']['fixture'], 'disabled')

    def test_invalid_opencode_permission_actions_fail_before_planning(self):
        for value in [True, 123, None, [], 'invalid', {'bash': 'invalid'}, {'bash': {'*': 123}}, {'bash': {'*': {'nested': 'allow'}}}]:
            for agent in [False, True]:
                data = {'permission': value}
                if agent:
                    data = {'agent': {'build': data}}
                with self.subTest(value=value, agent=agent), self.assertRaises(ValueError):
                    align.parse('opencode', json.dumps(data).encode())
        align.parse('opencode', b'{"permission":{"bash":{"*":"ask","git *":"allow"}}}')

    def test_native_order_partial_constraints_full_guards_and_override_identity(self):
        allow = {'action': 'shell', 'resource': '*', 'effect': 'allow'}
        deny = {'action': 'shell', 'resource': 'git push *', 'effect': 'deny'}
        ask = {'action': 'shell', 'resource': '*', 'effect': 'ask'}
        policy = {'permissions': [allow, deny]}
        self.assertEqual(align.parse('opencode', json.dumps(policy).encode()), policy)
        self.assertEqual(align.audit.inspect('opencode', policy)[0]['code'], 'constrained_broad_allow')
        self.assertEqual(align.audit.inspect('opencode', {'permissions': [allow, ask]}), [])
        self.assertEqual(align.audit.inspect('opencode', {'permissions': [ask, allow]})[0]['code'], 'broad_tool_allow')
        for after in ([allow], [deny, allow], [ask, deny]):
            if after == [ask, deny]:
                align.protect_policy('opencode', policy, {'permissions': after})
            else:
                with self.assertRaises(ValueError):
                    align.protect_policy('opencode', policy, {'permissions': after})
        for key in ('agents', 'agent'):
            allowed = {'permissions': [ask, allow]} if key == 'agents' else {'permission': {'*': 'ask', 'bash': 'allow'}}
            guarded = {'permissions': [ask]} if key == 'agents' else {'permission': 'ask'}
            old = {key: {'a': allowed, 'b': guarded}}
            new = {key: {'a': guarded, 'b': allowed}}
            self.assertTrue(align.risk_locations('opencode', new) - align.risk_locations('opencode', old))
        self.assertEqual(align.changed_paths(policy, {'permissions': [deny, allow]}, adapter='opencode'), [('permissions',)])

    def test_global_guards_refuse_changed_or_new_agent_allows(self):
        for native in (True, False):
            for effect in ('deny', 'ask'):
                guard = {'action': 'shell', 'resource': 'rm*', 'effect': effect}
                allow = {**guard, 'effect': 'allow'}
                root, key = ('agents', 'permissions') if native else ('agent', 'permission')
                policy = lambda rules: {key: rules if native else {'bash': {
                    r['resource']: r['effect'] for r in rules}}}
                before = {**policy([guard]), root: {'x': policy([])}}
                for name in ('x', 'y'):
                    after = json.loads(json.dumps(before))
                    after[root][name] = policy([allow])
                    with self.subTest(native=native, effect=effect, agent=name):
                        # This narrow rule deliberately evades the broad-risk counter.
                        self.assertFalse(align.risk_locations('opencode', after) -
                                         align.risk_locations('opencode', before))
                        with self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
                            align.protect_policy('opencode', before, after)
                unchanged = {**policy([guard]), root: {'x': policy([allow])}}
                align.protect_policy('opencode', unchanged, unchanged)
                tightened = {**policy([guard]), root: {'x': policy([{**allow, 'effect': 'ask'}])}}
                align.protect_policy('opencode', unchanged, tightened)
                two_allows = [allow, {**allow, 'resource': 'git*'}]
                before = {**policy([guard]), root: {'x': policy(two_allows)}}
                tightened = {**policy([guard]), root: {'x': policy([
                    {**allow, 'effect': 'deny'}, two_allows[1]])}}
                align.protect_policy('opencode', before, tightened)
                changed = {**policy([guard]), root: {'x': policy([
                    {**allow, 'resource': 'mv*'}, two_allows[1]])}}
                with self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
                    align.protect_policy('opencode', before, changed)

    def test_native_plugins_inventory_shapes_and_change_roots(self):
        data = {'plugins': ['fixture-plugin@1.0', {'package': '@fixture/plugin', 'options': {'strict': True}}]}
        parsed = align.parse('opencode', json.dumps(data).encode())
        self.assertEqual(align.resources('opencode', parsed)['plugin'],
                         {'fixture-plugin@1.0': 'configured', '@fixture/plugin': 'configured'})
        self.assertEqual(align.audit.inspect('opencode', parsed), [])
        self.assertEqual(align.changed_paths({}, data, adapter='opencode'), [('plugins',)])
        self.assertTrue(align.allowed_change('opencode', ('plugins',), {}, data))
        for value, reason in [({'plugin': [], **data}, 'unsupported_mixed_plugins'),
                              ({'plugins': {}}, 'unsupported_plugins'),
                              ({'plugins': [['fixture', {}]]}, 'unsupported_plugins'),
                              ({'plugins': [{'package': 'fixture', 'enabled': True}]}, 'unsupported_plugins'),
                              ({'plugins': [{'package': 'fixture', 'options': []}]}, 'unsupported_plugins'),
                              ({'plugins': [False]}, 'unsupported_plugins'),
                              ({'plugins': ['-fixture']}, 'unsupported_plugin_directive'),
                              ({'plugins': ['*']}, 'unsupported_plugin_directive')]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, reason):
                align.parse('opencode', json.dumps(value).encode())
        path = self.file('native-plugin-settings', json.dumps(data))
        compared = align.compare({'providers': [{'providerInstanceId': 'oc'}]}, {'version': 1,
            'providers': [{'provider_instance_id': 'oc', 'adapter': 'opencode',
                           'sources': [{'path': str(path), 'scope': 'global'}]}],
            'capabilities': [{'kind': 'plugin', 'members': {'oc': 'fixture-plugin@1.0'}}]})
        self.assertEqual(compared['capabilities'][0]['states'], ['configured'])

    def test_unverified_native_equivalences_still_fail_closed(self):
        ask = {'action': 'shell', 'resource': 'rm*', 'effect': 'ask'}
        with self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
            align.protect_policy('opencode', {'permissions': [ask]},
                                 {'permissions': [{**ask, 'effect': 'deny'}]})
        with self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
            align.protect_policy('opencode', {'permission': {'bash': {'rm*': 'ask'}}},
                                 {'permissions': [ask]})
        with self.assertRaisesRegex(ValueError, 'unsupported_mcp_server'):
            align.parse('opencode', b'{"mcp":{"servers":{"fixture":{"type":"local","command":[]}}}}')

    def test_typed_legacy_mcp_reserved_names_and_native_timeouts(self):
        server = {'type': 'local', 'command': ['fixture'], 'enabled': False, 'timeout': 30000}
        legacy = {'permission': {'bash': 'ask'}, 'mcp': {'servers': server, 'timeout': server}}
        self.assertEqual(align.resources('opencode', align.parse('opencode', json.dumps(legacy).encode()))['mcp'],
                         {'servers': 'disabled', 'timeout': 'disabled'})
        native = {'permissions': [], 'mcp': {'timeout': {'startup': 5, 'catalog': 10, 'execution': 20},
                  'servers': {'fixture': {'type': 'local', 'command': ['fixture'], 'timeout': {'startup': 50}}}}}
        self.assertEqual(align.resources('opencode', align.parse('opencode', json.dumps(native).encode()))['mcp'],
                         {'fixture': 'configured'})
        for mcp in ({'x': {}}, {'servers': [], 'timeout': {}}, {'timeout': {'startup': True}},
                    {'servers': {'x': {'type': 'new'}}},
                    {'x': {'type': 'local', 'command': ['fixture'], 'disabled': True}}):
            with self.subTest(mcp=mcp), self.assertRaises(ValueError):
                align.parse('opencode', json.dumps({'mcp': mcp}).encode())

    def test_muse_native_coverage_gap_is_in_comparison_findings(self):
        path = self.file('muse', '{"permissions":{"profiles":{}}}')
        result = align.compare({'providers': [{'providerInstanceId': 'm'}]}, {'version': 1, 'providers': [
            {'provider_instance_id': 'm', 'adapter': 'muse', 'sources': [{'path': str(path), 'scope': 'global'}]}]})
        self.assertIn('coverage_gap', {f['code'] for f in result['findings']})
        self.assertIn('unsupported', {f['code'] for f in result['findings']})

    def test_project_scope_conflicts_are_never_overwritten_by_disable_markers(self):
        data = {'projects': {'/fixture/project': {'mcpServers': {'fixture': {'command': 'fixture-command'}}}},
                'disabledMcpServers': ['fixture'], 'enabledMcpjsonServers': ['fixture'],
                'mcpServers': {'fixture': {'disabled': True, 'command': 'fixture-command'}}}
        self.assertEqual(align.resources('claude', data)['mcp']['fixture'], 'scope_conflict')

    def test_approval_only_mcp_is_unknown_until_a_definition_is_supplied(self):
        catalog = {'providers': [{'providerInstanceId': 'claude'}]}
        approvals = self.file('approvals.json', '{"enabledMcpjsonServers":["fixture"]}')
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'claude', 'adapter': 'claude',
                     'sources': [{'path': str(approvals), 'scope': 'global'}]}],
                     'capabilities': [{'kind': 'mcp', 'members': {'claude': 'fixture'}}]}
        self.assertEqual(align.compare(catalog, inventory)['capabilities'][0]['states'], ['unknown'])
        definition = self.file('definition.json', '{"mcpServers":{"fixture":{"command":"fixture-command"}}}')
        inventory['providers'][0]['sources'].append({'path': str(definition), 'scope': 'project'})
        self.assertEqual(align.compare(catalog, inventory)['capabilities'][0]['states'], ['configured'])

    def test_compare_fifo_returns_invalid_instead_of_blocking(self):
        source = self.root / 'fifo-source'
        os.mkfifo(source)
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'claude', 'adapter': 'claude',
                     'sources': [{'path': str(source), 'scope': 'global'}]}]}
        result = align.compare({'providers': [{'providerInstanceId': 'claude'}]}, inventory)
        self.assertEqual(result['providers'][0]['sources'][0]['status'], 'unreadable_or_invalid')

    def test_muse_tightening_plans_and_loosening_is_refused(self):
        safe = ('{"permissions":{"schema_version":1,"profiles":{"work":{"approval":"on_request",'
                '"network":{"mode":"proxy_only"}}}}}')
        risky = ('{"permissions":{"schema_version":1,"profiles":{"work":{"approval":"allow_all",'
                 '"network":{"mode":"enabled"}}}}}')
        keys = ['/permissions/profiles/work/approval', '/permissions/profiles/work/network/mode']
        with self.assertRaisesRegex(ValueError, 'unsupported_policy_coverage'):
            self.proposal('muse', risky, safe, keys)
        with self.assertRaises(ValueError):
            self.proposal('muse', safe, risky, keys)
        # Removing a stated protective dimension is a weakening, not a no-op.
        with self.assertRaises(ValueError):
            self.proposal('muse', safe, '{"permissions":{"schema_version":1}}', ['/permissions/profiles'])

    def test_muse_filesystem_deletion_is_refused_before_writes(self):
        before = {'permissions': {'profiles': {'work': {
            'approval': 'on_request', 'filesystem': {'allow': ['./fixture']}}}}}
        after = {'permissions': {'profiles': {'work': {'approval': 'on_request'}}}}
        with self.assertRaisesRegex(ValueError, 'protective_setting_weakened'):
            self.proposal('muse', json.dumps(before), json.dumps(after),
                          ['/permissions/profiles/work/filesystem'])
        self.assertEqual(json.loads(self.target.read_text()), before)

    def test_muse_mcp_and_plugin_inventory_remain_unknown(self):
        path = self.file('muse-settings.json', '{"permissions":{"profiles":{}}}')
        catalog = {'providers': [{'providerInstanceId': 'muse'}]}
        inventory = {'version': 1, 'providers': [{
            'provider_instance_id': 'muse', 'adapter': 'muse',
            'sources': [{'path': str(path), 'scope': 'global'}]}],
            'capabilities': [{'kind': kind, 'members': {'muse': 'fixture'}}
                             for kind in ('mcp', 'plugin')]}
        result = align.compare(catalog, inventory)
        self.assertEqual(result['providers'][0]['sources'][0]['status'], 'parsed')
        self.assertEqual([c['states'] for c in result['capabilities']], [['unknown'], ['unknown']])

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
