"""Issue 96 A1/A2: synthetic, read-only discovery and installed public audit.

No provider process, real config root, GitHub or transcript is used. Receipt
fixtures describe declared provenance, never cryptographic proof of owner intent.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
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
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/agent-tuneup'
SCRIPT = PLUGIN / 'scripts/align.py'
spec = importlib.util.spec_from_file_location('inventory_alignment', SCRIPT)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
agents = align.wiring.agent_inventory


class AgentInventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.inventory = json.loads((PLUGIN / 'fixtures/agent-inventory-v2.json').read_text().replace('@ROOT@', str(self.root)))
        self.catalog = {'providers': [
            {'providerInstanceId': 'fixture-native', 'canRunChildTask': True},
            {'providerInstanceId': 'fixture-disabled', 'enabled': False},
            {'providerInstanceId': 'fixture-future', 'canRunChildTask': False}]}
        self.native = self.root / 'native'; self.native.mkdir()
        (self.root / 'roles').mkdir()
        self.file('config.jsonc', '{}')
        self.provider = self.inventory['wiring']['providers'][0]

    def file(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text); path.chmod(0o600)
        return path

    def agent(self, name='reviewer', front='mode: subagent', body='Review synthetic changes.'):
        return self.file('native/' + name + '.md', '---\ndescription: Synthetic definition\n' + front + '\n---\n' + body)

    def bound(self, path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def inspect(self):
        private = {}
        report = align.compare(self.catalog, self.inventory, private=private)
        return report['wiring']['agent_inventory'], private['agent_plan']

    def items(self):
        return self.inspect()[1]['providers'][0]['items']

    def receipt(self, path, kind='native', owner='synthetic-owner'):
        original = agents.descriptor(path)
        source = self.file('owning-source-' + path.stem, 'Synthetic owning source revision.')
        claim = {k: original[k] for k in ('path', 'sha256', 'mode', 'link_target')}
        claim['content_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        claim.update(source=self.bound(source), kind=kind)
        receipt = self.file('receipt-' + path.stem + '.json', json.dumps({
            'schema_version': 1, 'owner': owner, 'items': [claim]}))
        self.provider.setdefault('ownership_receipts', []).append(self.bound(receipt))
        return receipt, source

    def request(self, path, disposition='retire-managed-alias', names=()):
        proof = self.file('caller-proof', 'Synthetic caller inventory and reviewed intent.')
        self.provider['caller_references'] = {'state': 'complete', 'names': list(names),
                                               'evidence': [self.bound(proof)]}
        self.provider['assessments'] = [{'path': str(path), 'disposition': disposition,
            'reason': 'Synthetic reviewed proposal', 'evidence': [self.bound(proof)]}]

    def run_public(self, script=SCRIPT, extra=(), env=None, tag='input'):
        inventory = self.file(tag + '-inventory.json', json.dumps(self.inventory))
        catalog = self.file(tag + '-catalog.json', json.dumps(self.catalog))
        result = subprocess.run([sys.executable, '-I', str(script), 'audit', '--catalog', str(catalog),
                                 '--inventory', str(inventory), *extra], cwd=self.root,
                                capture_output=True, text=True, env=env, timeout=120)
        return result, json.loads(result.stdout)

    def test_catalog_coverage_disabled_unknown_and_no_implicit_scan(self):
        self.agent()
        report, plan = self.inspect()
        self.assertEqual(len(report['providers']), 3)
        self.assertTrue(report['providers'][1]['catalog_disabled'])
        self.assertEqual(report['providers'][2]['discovery'], 'unknown')
        self.assertEqual(plan['providers'][2]['items'], [])
        self.assertTrue(any(f['code'] == 'agent_roots_unknown' for f in report['findings']))
        self.assertEqual(report['loading'], 'unverified')
        self.assertEqual(report['exercise'], 'not-run')

    def test_v2_provider_identity_is_required_and_unique(self):
        malformed = copy.deepcopy(self.inventory['wiring'])
        malformed['providers'][0].pop('provider_instance_id')
        with self.assertRaisesRegex(ValueError, 'invalid_provider_instance_id'):
            agents.inspect(self.catalog, malformed)
        malformed = copy.deepcopy(self.inventory['wiring'])
        duplicate = copy.deepcopy(malformed['providers'][0])
        malformed['providers'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'duplicate_provider_instance_id'):
            agents.inspect(self.catalog, malformed)

    def test_empty_yaml_block_scalar_is_scoped_as_an_empty_value(self):
        data, body = agents.markdown(b'---\nsystem: |\n  \n---\nBody')
        self.assertEqual(data['system'], '')
        self.assertEqual(body, 'Body')

    def test_private_plan_writer_bounds_and_cleans_up_failed_atomic_write(self):
        destination = self.root / 'private-plan.json'
        with self.assertRaisesRegex(ValueError, 'private_plan_too_large'):
            align.write_private(destination, b'x' * (agents.MAX_BYTES + 1))
        self.assertFalse(destination.exists())
        with patch.object(align._core_store.os, 'fsync', side_effect=OSError('fixture write failure')):
            with self.assertRaisesRegex(OSError, 'fixture write failure'):
                align.write_private(destination, b'{}')
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.private-plan.json.*')), [])

    def test_live_and_broken_aliases_preserve_link_metadata(self):
        target = self.agent('target')
        live = self.native / 'live.md'; live.symlink_to('target.md')
        broken = self.native / 'broken.md'; broken.symlink_to('absent.md')
        before = [os.readlink(p) for p in (live, broken)]
        rows = {r['name']: r for r in self.items()}
        self.assertEqual(rows['live']['status'], 'parsed')
        self.assertEqual(rows['broken']['status'], 'broken-alias')
        self.assertEqual(rows['live']['original']['link_target'], 'target.md')
        self.assertEqual(rows['broken']['original']['mode'], stat.S_IMODE(broken.lstat().st_mode))
        self.assertEqual(before, [os.readlink(p) for p in (live, broken)])
        self.assertEqual(target.read_text().splitlines()[-1], 'Review synthetic changes.')

    def test_external_alias_requires_explicit_read_path(self):
        outside = self.file('outside.md', '---\nmode: subagent\n---\nSynthetic content')
        alias = self.native / 'alias.md'; alias.symlink_to(outside)
        self.assertEqual(self.items()[0]['status'], 'alias-target-out-of-scope')
        self.provider['read_paths'] = [str(outside)]
        self.assertEqual(self.items()[0]['status'], 'parsed')
        self.assertEqual(self.items()[0]['ownership']['status'], 'unmanaged')

    def test_directory_alias_is_not_recursively_followed(self):
        outside = self.file('outside/hidden.md', 'do not parse')
        (self.native / 'vendor-alias').symlink_to(outside.parent, target_is_directory=True)
        rows = self.items()
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]['status'], 'parsed')
        self.assertNotIn('hidden', {r['name'] for r in rows})

    def test_python310_reparse_directory_is_not_recursively_followed(self):
        target = self.file('native/junction/hidden.md', 'Synthetic vendor content')
        original = Path.lstat
        def reparse(path):
            if path == target.parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400)
            return original(path)
        with patch.object(Path, 'lstat', reparse):
            rows = self.items()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'unsupported_alias')
        self.assertNotIn('junction/hidden', {r['name'] for r in rows})

    def test_concurrent_source_change_is_an_explicit_refusal(self):
        path = self.agent()
        original = agents.read
        reads = 0
        def changing(candidate, **kwargs):
            nonlocal reads
            if candidate == path:
                reads += 1
                if reads == 2:
                    path.write_text('---\nmode: subagent\n---\nChanged during read')
            return original(candidate, **kwargs)
        with patch.object(agents, 'read', side_effect=changing):
            row = self.items()[0]
        self.assertEqual(row['status'], 'invalid')
        self.assertEqual(row['error'], 'concurrent_drift')
        self.assertFalse(row['automatic_eligibility'])

    def test_explicit_root_alias_is_read_but_not_write_eligibility(self):
        self.agent()
        alias = self.root / 'root-alias'; alias.symlink_to(self.native, target_is_directory=True)
        self.provider['agent_roots'][0]['path'] = str(alias)
        row = self.items()[0]
        self.assertEqual(row['status'], 'parsed')
        self.assertTrue(row['linked_parents'])
        self.assertFalse(row['automatic_eligibility'])

    def test_config_entries_and_project_global_precedence(self):
        self.agent()
        self.file('config.jsonc', '{// synthetic\n"agents":{"reviewer":{"mode":"subagent","model":"private-model"}},}')
        report, plan = self.inspect()
        rows = plan['providers'][0]['items']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['collision'] for r in rows))
        self.assertEqual({r['effective_layer'] for r in rows}, {'merge-required'})
        self.assertTrue(all(not r['automatic_eligibility'] for r in rows))
        self.assertNotIn('private-model', json.dumps(report))

    def test_claude_project_definition_shadows_global_and_same_scope_is_ambiguous(self):
        self.provider.update(adapter='claude', runtime_version='2.1.198', agent_configs=[])
        self.agent(front='name: reviewer\nmode: subagent')
        self.file('project/reviewer.md', '---\nname: reviewer\ndescription: Project\n---\nSynthetic')
        self.provider['agent_roots'].append({'path': str(self.root/'project'), 'scope': 'project', 'format': 'markdown'})
        rows = self.items()
        self.assertEqual([r['effective_layer'] for r in rows], ['shadowed', 'candidate'])
        self.provider['agent_roots'][1]['scope'] = 'global'
        self.assertEqual({r['effective_layer'] for r in self.items()}, {'ambiguous'})

    def test_claude_config_capture_only_on_documented_managed_session_surfaces(self):
        self.provider.update(adapter='claude', runtime_version='2.1.198')
        self.file('config.jsonc', '{"session-agent":{"description":"Synthetic"}}')
        self.assertTrue(self.inspect()[0]['fatal'])
        self.provider['agent_configs'][0]['scope'] = 'session'
        self.assertFalse(self.inspect()[0]['fatal'])
        self.assertEqual(self.items()[0]['scope'], 'session')

    def test_builtins_and_hidden_maintenance_never_retire(self):
        path = self.agent('compaction')
        self.receipt(path)
        self.request(path)
        report, plan = self.inspect()
        row = plan['providers'][0]['items'][0]
        self.assertTrue(row['builtin_collision'])
        self.assertFalse(row['automatic_eligibility'])
        self.assertEqual(row['assessment_status'], 'refused')
        builtins = plan['providers'][0]['builtins']
        self.assertEqual({r['name'] for r in builtins if r['hidden_maintenance']}, {'compaction', 'title', 'summary'})
        self.assertTrue(all(r['disposition'] == 'keep' and not r['automatic_eligibility'] for r in builtins))
        self.assertTrue(report['providers'][0]['builtins'])

    def test_default_reference_missing_disabled_hidden_and_retained_primary(self):
        path = self.agent('primary', 'mode: primary')
        for value in ('missing', 'primary'):
            self.file('config.jsonc', json.dumps({'default_agent': value}))
            _, plan = self.inspect()
            reference = plan['providers'][0]['default_references'][0]
            self.assertEqual(reference['status'], 'missing-default-agent' if value == 'missing' else 'resolved-in-supplied-layers')
        self.assertEqual(self.items()[0]['disposition'], 'keep-as-native-exception')
        path.write_text('---\nmode: primary\nhidden: true\n---\nSynthetic')
        self.assertEqual(self.inspect()[1]['providers'][0]['default_references'][0]['status'], 'missing-default-agent')

    def test_public_default_selection_uses_documented_builtin_modes_and_custom_overrides(self):
        from tests.test_rebuild_installed import Sandbox, tree_digest
        box = Sandbox(self.root/'default-installed')
        package, _ = box.install('agent-tuneup')
        # Expectations come from OpenCode v2 Selection, Builtins and Modes, not
        # from the inventory's format table. Exercise both public entrypoints.
        cases = [
            ('build', {}, True), ('plan', {}, True),
            ('general', {}, False), ('explore', {}, False),
            ('compaction', {}, False), ('title', {}, False), ('summary', {}, False),
            ('missing', {}, False),
            ('build', {'mode': 'subagent'}, False),
            ('plan', {'disabled': True}, False), ('build', {'hidden': True}, False),
            ('general', {'system': 'Synthetic custom instructions.'}, False),
            ('explore', {'permissions': []}, False),
            ('general', {'mode': 'primary'}, True), ('explore', {'mode': 'all'}, True),
            ('general', {'mode': 'primary', 'disabled': True}, False),
            ('explore', {'mode': 'all', 'hidden': True}, False),
            ('writer', {'description': 'Synthetic custom primary.'}, True),
            ('writer', {'mode': 'all'}, True), ('writer', {'mode': 'subagent'}, False),
            ('writer', {'mode': 'primary', 'disabled': True}, False),
            ('writer', {'mode': 'primary', 'hidden': True}, False),
        ]
        for script, env in [(SCRIPT, None), (package/'scripts/align.py', box.env)]:
            for number, (name, override, available) in enumerate(cases):
                with self.subTest(installed=env is not None, name=name, override=override):
                    config = self.file('config.jsonc', json.dumps({'default_agent': name,
                        'agents': {name: override} if override else {}}))
                    before = tree_digest(self.native, self.root/'roles'), config.read_bytes()
                    out = self.root/f'default-{env is not None}-{number}.json'
                    result, report = self.run_public(script, env=env, extra=['--private-out', str(out)])
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    provider = json.loads(out.read_text())['providers'][0]
                    reference = provider['default_references'][0]
                    self.assertEqual(reference['name'], name)
                    self.assertEqual(reference['status'], 'resolved-in-supplied-layers'
                                     if available else 'missing-default-agent')
                    missing = [f for f in report['wiring']['agent_inventory']['findings']
                               if f['code'] == 'missing_default_agent']
                    self.assertEqual(len(missing), 0 if available else 1)
                    builtins = provider['builtins']
                    self.assertEqual({b['name'] for b in builtins},
                        {'build', 'plan', 'general', 'explore', 'compaction', 'title', 'summary'})
                    self.assertTrue(all(b['disposition'] == 'keep' and not b['automatic_eligibility']
                                        for b in builtins))
                    self.assertTrue(all(not i['automatic_eligibility'] for i in provider['items']))
                    self.assertEqual(before, (tree_digest(self.native, self.root/'roles'), config.read_bytes()))

    def test_public_default_builtin_file_overrides_and_conflicting_layers_stay_conservative(self):
        for name, front, available in [
                ('general', '', False), ('explore', 'mode: primary', True),
                ('build', 'mode: subagent', False), ('plan', 'disabled: true', False),
                ('build', 'hidden: true', False)]:
            with self.subTest(name=name, front=front):
                path = self.agent(name, front)
                self.file('config.jsonc', json.dumps({'default_agent': name}))
                out = self.root/f'file-default-{name}-{len(front)}.json'
                _, report = self.run_public(extra=['--private-out', str(out)])
                provider = json.loads(out.read_text())['providers'][0]
                self.assertEqual(provider['default_references'][0]['status'],
                    'resolved-in-supplied-layers' if available else 'missing-default-agent')
                self.assertEqual(provider['items'][0]['effective_layer'], 'merge-required')
                self.assertFalse(provider['items'][0]['automatic_eligibility'])
                self.assertEqual(any(f['code'] == 'missing_default_agent'
                    for f in report['wiring']['agent_inventory']['findings']), not available)
                path.unlink()
        self.agent('writer', 'mode: primary')
        for override in ({'disabled': True}, {'hidden': True}, {'mode': 'subagent'}):
            with self.subTest(override=override):
                self.file('config.jsonc', json.dumps({'default_agent': 'writer', 'agents': {'writer': override}}))
                _, report = self.run_public()
                self.assertTrue(any(f['code'] == 'missing_default_agent'
                    for f in report['wiring']['agent_inventory']['findings']))
                self.assertEqual({r['effective_layer'] for r in self.items()}, {'merge-required'})

    def test_unknown_future_and_unsupported_provider_versions_do_not_read_roots(self):
        for adapter, version, status in [('opencode', None, 'unknown'), ('opencode', '2.1.3', 'unsupported'),
                                         ('codex', '1.0.0', 'unsupported'), ('muse', '1.4.7', 'unsupported')]:
            with self.subTest(adapter=adapter, version=version):
                self.provider.update(adapter=adapter, runtime_version=version)
                with patch.object(agents, 'discover', wraps=agents.discover) as discovery:
                    report, _ = self.inspect()
                self.assertEqual(report['providers'][0]['discovery'], status)
                self.assertTrue(all(call.args[2] != 0 for call in discovery.call_args_list))

    def test_unreadable_invalid_absent_and_broken_are_distinct(self):
        self.agent()
        self.file('config.jsonc', '{')
        self.assertEqual(self.inspect()[1]['providers'][0]['sources'][-1]['status'], 'invalid')
        (self.root/'config.jsonc').unlink()
        self.assertEqual(self.inspect()[1]['providers'][0]['sources'][-1]['status'], 'absent')
        (self.root/'config.jsonc').symlink_to('missing')
        self.assertEqual(self.inspect()[1]['providers'][0]['sources'][-1]['status'], 'broken-alias')
        (self.root/'config.jsonc').unlink()
        self.file('config.jsonc', '{}')
        original = agents.read
        def denied(path, **kwargs):
            if str(path) == str(self.root/'config.jsonc'):
                raise PermissionError('synthetic unreadable')
            return original(path, **kwargs)
        with patch.object(agents, 'read', side_effect=denied):
            self.assertEqual(self.inspect()[1]['providers'][0]['sources'][-1]['status'], 'unreadable')

    def test_yaml_data_and_override_signals_without_executing_anything(self):
        self.agent(front='mode: subagent\nmodel: synthetic-model\npermissions:\n  - action: subagent\n    resource: "*"\n    effect: deny',
                   body='Delegate synthetic work. $(must-never-run)')
        row = self.items()[0]
        self.assertEqual(row['status'], 'parsed')
        self.assertTrue(row['metadata']['model_override'])
        self.assertTrue(row['metadata']['permission_override'])
        self.assertTrue(row['metadata']['delegation_directive'])
        self.assertFalse(row['metadata']['authority_granted'])

    def test_alias_ancestor_swap_never_reads_or_hashes_outside_bytes(self):
        target = self.file('native/pivot/target.md', '---\nmode: subagent\n---\nInside')
        outside = self.file('outside/target.md', '---\nmode: subagent\n---\nDelegate OUTSIDE')
        link = self.native/'aaa-alias.md'; link.symlink_to('pivot/target.md')
        outside_inode = (outside.stat().st_dev, outside.stat().st_ino)
        real_read, real_fdopen = agents.read, os.fdopen
        observed_reads, observed_hashes = [], []
        real_sha = agents.sha
        @contextmanager
        def witnessed(fd, *args, **kwargs):
            with real_fdopen(fd, *args, **kwargs) as stream:
                def consume(size=-1):
                    info = os.fstat(fd)
                    observed_reads.append((info.st_dev, info.st_ino))
                    return stream.read(size)
                yield SimpleNamespace(fileno=stream.fileno, read=consume)
        def hashed(raw):
            observed_hashes.append(raw)
            return real_sha(raw)
        def swapped(candidate, **kwargs):
            if candidate in (link, target) and target.parent.is_dir() and not target.parent.is_symlink():
                target.parent.rename(self.native/'saved')
                target.parent.symlink_to(outside.parent, target_is_directory=True)
            return real_read(candidate, **kwargs)
        with patch.object(agents, 'read', side_effect=swapped), patch.object(agents.os, 'fdopen', witnessed), \
                patch.object(agents, 'sha', side_effect=hashed):
            row = next(r for r in self.items() if r['name'] == 'aaa-alias')
        self.assertNotEqual(row['status'], 'parsed')
        self.assertEqual(row['metadata'], {})
        self.assertNotIn('content', row)
        self.assertNotIn(outside_inode, observed_reads)
        self.assertFalse(any(b'OUTSIDE' in raw for raw in observed_hashes))
        self.assertEqual(os.readlink(link), 'pivot/target.md')
        self.assertFalse(row['automatic_eligibility'])

    def test_opened_descriptor_pins_bytes_and_refuses_ancestor_drift(self):
        target = self.file('native/pivot/target.md', '---\nmode: subagent\n---\nInside')
        outside = self.file('outside/target.md', '---\nmode: subagent\n---\nDelegate OUTSIDE')
        expected = agents.file_identity(target)
        real_fdopen = os.fdopen
        reads = []
        @contextmanager
        def swapped_after_open(fd, *args, **kwargs):
            target.parent.rename(self.native/'saved')
            target.parent.symlink_to(outside.parent, target_is_directory=True)
            with real_fdopen(fd, *args, **kwargs) as stream:
                def consume(size=-1):
                    raw = stream.read(size); reads.append(raw); return raw
                yield SimpleNamespace(fileno=stream.fileno, read=consume)
        with patch.object(agents.os, 'fdopen', swapped_after_open), self.assertRaisesRegex(ValueError, 'concurrent_drift'):
            agents.read(target, expected=expected)
        self.assertTrue(reads)
        self.assertTrue(all(b'Inside' in raw and b'OUTSIDE' not in raw for raw in reads))

    def test_changed_leaf_identity_and_alias_are_refused(self):
        target = self.file('source/target.md', '---\nmode: subagent\n---\nInside')
        outside = self.file('outside.md', '---\nmode: subagent\n---\nDelegate OUTSIDE')
        expected = agents.file_identity(target)
        target.unlink(); target.symlink_to(outside)
        with self.assertRaises(ValueError):
            agents.read(target, expected=expected)
        target.unlink(); target.write_text('---\nmode: subagent\n---\nInside')
        link = self.native/'alias.md'; link.symlink_to(target)
        self.provider['read_paths'] = [str(target)]
        real_read = agents.read
        def replaced(candidate, **kwargs):
            if candidate == target:
                link.unlink(); link.symlink_to(outside)
            return real_read(candidate, **kwargs)
        with patch.object(agents, 'read', side_effect=replaced):
            row = self.items()[0]
        self.assertEqual(row['status'], 'invalid')
        self.assertEqual(row['error'], 'concurrent_drift')
        self.assertEqual(row['metadata'], {})

    def test_config_and_role_ancestor_swaps_do_not_parse_outside(self):
        for kind in ('config', 'role'):
            with self.subTest(kind=kind):
                target = self.file(kind+'/data'+('.json' if kind == 'config' else '.md'),
                                   '{}' if kind == 'config' else 'Inside')
                outside = self.file(kind+'-outside/'+target.name,
                                    '{"agents":{"outside":{"system":"delegate"}}}' if kind == 'config' else 'delegate OUTSIDE')
                if kind == 'config':
                    self.provider['agent_configs'][0]['path'] = str(target)
                else:
                    self.provider['agent_configs'][0]['path'] = str(self.root/'config.jsonc')
                    self.inventory['wiring']['role_roots'][0]['path'] = str(target.parent)
                real_read = agents.read
                calls = 0
                def swapped(candidate, **kwargs):
                    nonlocal calls
                    if candidate == target:
                        calls += 1
                        if calls == 2:
                            target.parent.rename(self.root/(kind+'-saved'))
                            target.parent.symlink_to(outside.parent, target_is_directory=True)
                    return real_read(candidate, **kwargs)
                with patch.object(agents, 'read', side_effect=swapped):
                    report, plan = self.inspect()
                self.assertTrue(report['fatal'])
                rows = plan['providers'][0]['sources'] if kind == 'config' else plan['roles']
                self.assertNotEqual(rows[-1]['status'], 'parsed')
                self.assertNotIn('outside', {r['name'] for r in plan['providers'][0]['items']})

    def test_secure_read_has_no_unsupported_platform_fallback(self):
        target = self.agent()
        with patch.object(agents.os, 'supports_dir_fd', set()):
            with self.assertRaisesRegex(ValueError, 'secure_read_unavailable'):
                agents.read(target)
            self.assertNotEqual(agents.descriptor(target)['status'], 'file')

    def test_explicit_root_alias_retarget_during_read_refuses_fidelity(self):
        target = self.agent()
        outside = self.file('outside/reviewer.md', 'delegate OUTSIDE')
        root_link = self.root/'root-alias'; root_link.symlink_to(self.native, target_is_directory=True)
        self.provider['agent_roots'][0]['path'] = str(root_link)
        real_read = agents.read
        calls = 0
        def changed(candidate, **kwargs):
            nonlocal calls
            if candidate == target:
                calls += 1
                if calls == 2:
                    root_link.unlink(); root_link.symlink_to(outside.parent, target_is_directory=True)
            return real_read(candidate, **kwargs)
        with patch.object(agents, 'read', side_effect=changed):
            row = self.items()[0]
        self.assertEqual(row['status'], 'invalid')
        self.assertEqual(row['error'], 'concurrent_drift')
        self.assertEqual(row['metadata'], {})
        self.assertFalse(row['automatic_eligibility'])

    def test_config_alias_swap_before_resolution_cannot_expand_authorized_target(self):
        config = self.root/'config.jsonc'; config.unlink()
        target = self.file('source/config.json', '{}')
        outside = self.file('outside/config.json', '{"agents":{"outside":{"system":"delegate"}}}')
        config.symlink_to(target)
        real_descriptor, real_read = agents.descriptor, agents.read
        reads = []
        def changed(candidate, *args):
            captured = real_descriptor(candidate, *args)
            if candidate == config:
                config.unlink(); config.symlink_to(outside)
            return captured
        def witnessed(candidate, **kwargs):
            reads.append(candidate)
            return real_read(candidate, **kwargs)
        with patch.object(agents, 'descriptor', side_effect=changed), patch.object(agents, 'read', side_effect=witnessed):
            report, plan = self.inspect()
        self.assertTrue(report['fatal'])
        self.assertEqual(plan['providers'][0]['sources'][-1]['status'], 'invalid')
        self.assertNotIn(outside, reads)
        self.assertEqual(plan['providers'][0]['items'], [])

    def test_yaml_block_content_folding_chomping_comments_and_nonstring_system(self):
        cases = [
            ('|', ['# delegate'], '# delegate\n'),
            ('|-', ['# delegate', '', '  nested'], '# delegate\n\n  nested'),
            ('|+', ['# delegate', '', ''], '# delegate\n\n\n'),
            ('>', ['# delegate', 'work'], '# delegate work\n'),
            ('>-', ['# delegate', 'work', '', 'next'], '# delegate work\nnext'),
            ('>+', ['# delegate', 'work', '', ''], '# delegate work\n\n\n'),
            ('>', ['intro', '  # delegate', 'outro'], 'intro\n  # delegate\noutro\n'),
            ('>', ['intro', '  # delegate', '', 'outro'], 'intro\n  # delegate\n\noutro\n'),
            ('>-', ['intro', '', '  # delegate', '', '', 'outro'], 'intro\n\n  # delegate\n\n\noutro'),
            ('|-', ['', '# delegate'], '\n# delegate'),
        ]
        for header, content, expected in cases:
            with self.subTest(header=header, content=content):
                raw = ('---\n# surrounding comment\nsystem: '+header+' # header comment\n'
                       +'\n'.join('  '+c for c in content)+'\n# outside block\nmode: subagent\n---\nBody').encode()
                data, body = agents.markdown(raw)
                self.assertEqual(data['system'], expected)
                meta = agents.metadata(data, body, 'opencode')
                self.assertEqual(meta['prompt_bytes'], len(('Body\n'+expected).encode()))
                self.assertTrue(meta['delegation_directive'])
                self.assertFalse(meta['authority_granted'])
        for value in ({'delegate': True}, ['delegate'], True, None, 17, 1.5):
            with self.subTest(system=value), self.assertRaisesRegex(ValueError, 'invalid_agent_definition'):
                agents.metadata({'system': value}, '', 'opencode')
        for value in ('|2', '>2-', '&anchor', '*anchor', '!!str delegate'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                agents.markdown(('---\nsystem: '+value+'\n---\n').encode())

    def test_public_installed_block_metadata_and_alias_scope(self):
        from tests.test_rebuild_installed import Sandbox, tree_digest
        box = Sandbox(self.root/'block-installed')
        package, _ = box.install('agent-tuneup')
        path = self.agent('block')
        external = self.file('external/target.md', '---\nmode: subagent\n---\nInside explicit target')
        link = self.native/'alias.md'; link.symlink_to(external)
        for script, env in ((SCRIPT, None), (package/'scripts/align.py', box.env)):
            for number, (header, expected) in enumerate((('|', '# delegate\n'), ('|-', '# delegate'),
                    ('|+', '# delegate\n\n'), ('>', '# delegate work\n'), ('>-', '# delegate work'),
                    ('>+', '# delegate work\n\n'), ('>', 'intro\n  # delegate\n\noutro\n'))):
                with self.subTest(installed=env is not None, header=header):
                    content = '  # delegate\n'+('  work\n' if header.startswith('>') else '')
                    if number == 6:
                        content = '  intro\n    # delegate\n\n  outro\n'
                    if header.endswith('+'):
                        content += '\n'
                    path.write_text('---\n# outside\nmode: subagent\nsystem: '+header+'\n'+content+'# outside\n---\nBody')
                    self.provider['read_paths'] = [str(external)] if number % 2 else []
                    before = tree_digest(self.native, self.root/'roles', external.parent)
                    out = self.root/f'block-{env is not None}-{number}.json'
                    result, report = self.run_public(script, env=env, extra=['--private-out', str(out)])
                    self.assertEqual(result.returncode, 1, result.stderr)
                    plan = json.loads(out.read_text())
                    rows = {r['name']: r for r in plan['providers'][0]['items']}
                    self.assertEqual(rows['block']['status'], 'parsed')
                    self.assertEqual(rows['block']['metadata']['prompt_bytes'], len(('Body\n'+expected).encode()))
                    self.assertTrue(rows['block']['metadata']['delegation_directive'])
                    self.assertFalse(rows['block']['metadata']['authority_granted'])
                    self.assertEqual(rows['alias']['status'], 'parsed' if number % 2 else 'alias-target-out-of-scope')
                    if number % 2:
                        self.assertEqual(rows['alias']['content']['sha256'], self.bound(external)['sha256'])
                    else:
                        self.assertNotIn('content', rows['alias'])
                    self.assertTrue(all(not r['automatic_eligibility'] for r in rows.values()))
                    self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
                    self.assertEqual(before, tree_digest(self.native, self.root/'roles', external.parent))
                    self.assertNotIn('# delegate', result.stdout+out.read_text())
            for number, value in enumerate(({'delegate': True}, ['delegate'], True, None, 12, 1.5)):
                with self.subTest(installed=env is not None, nonstring=value):
                    path.write_text('---\nmode: subagent\nsystem: '+json.dumps(value)+'\n---\nBody')
                    self.file('config.jsonc', json.dumps({'agents': {'config-agent': {'system': value}}}))
                    out = self.root/f'nonstring-{env is not None}-{number}.json'
                    result, _ = self.run_public(script, env=env, extra=['--private-out', str(out)])
                    self.assertEqual(result.returncode, 2, result.stderr)
                    provider = json.loads(out.read_text())['providers'][0]
                    row = next(r for r in provider['items'] if r['name'] == 'block')
                    self.assertEqual(row['status'], 'invalid')
                    self.assertEqual(row['metadata'], {})
                    self.assertEqual(provider['sources'][-1]['status'], 'invalid')
            self.file('config.jsonc', '{}')

    def test_bounded_data_invalid_syntax_duplicate_keys_and_mixed_formats(self):
        path = self.agent()
        for raw in ('---\nmode: subagent\nmode: primary\n---\ntext',
                    '---\nhooks: !!python/object:unsafe\n---\ntext',
                    '---\npermission:\n  edit: allow\n---\ntext'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                self.assertEqual(self.items()[0]['status'], 'invalid')
        for raw in ('{"agents":{},"agents":{}}', '{"agent":{}}',
                    '{"agents":{"x":{"permissions":"allow"}}}',
                    '{"agents":{"x":{"mode":true}}}', '[' * 40 + '0' + ']' * 40):
            with self.subTest(raw=raw):
                self.file('config.jsonc', raw)
                self.assertTrue(self.inspect()[0]['fatal'])
        path.write_bytes(b'x' * (agents.MAX_BYTES + 1))
        self.assertNotEqual(self.items()[0]['status'], 'parsed')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires FIFO')
    def test_special_files_are_never_blocking_reads(self):
        fifo = self.native / 'fifo.md'; os.mkfifo(fifo)
        row = self.items()[0]
        self.assertEqual(row['status'], 'unsafe_file')
        self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))

    def test_managed_alias_proposal_has_recovery_source_and_revalidation_metadata(self):
        target = self.file('source/role.md', '---\nmode: subagent\n---\nSynthetic')
        alias = self.native/'managed.md'; alias.symlink_to(target)
        self.provider['read_paths'] = [str(target)]
        receipt, source = self.receipt(alias)
        self.request(alias)
        report, plan = self.inspect()
        row = plan['providers'][0]['items'][0]
        self.assertEqual(row['disposition'], 'retire-managed-alias')
        self.assertTrue(row['automatic_eligibility'])
        self.assertEqual(row['preservation']['original']['link_target'], str(target))
        self.assertEqual(row['preservation']['source'], self.bound(source))
        self.assertTrue(row['revalidation'])
        self.assertIn('one owned alias', row['followup_operation'])
        self.assertFalse(plan['apply_supported'])
        self.assertEqual(plan['authorization'], 'not-granted')
        self.assertEqual(report['writes'], 0)
        self.assertTrue(alias.is_symlink()); self.assertTrue(receipt.exists())

    def test_unmanaged_and_modified_files_never_become_eligible(self):
        path = self.agent()
        self.request(path)
        self.assertFalse(self.items()[0]['automatic_eligibility'])
        _, source = self.receipt(path)
        self.assertFalse(self.items()[0]['automatic_eligibility'])  # A file is not an alias.
        self.request(path, 'extract-role')
        self.assertEqual(self.items()[0]['disposition'], 'extract-role')
        source.write_text('changed source')
        self.assertEqual(self.items()[0]['ownership']['status'], 'modified')
        self.assertEqual(self.items()[0]['assessment_status'], 'refused')

    def test_public_verified_native_retention_reason_and_matched_assessment(self):
        from tests.test_rebuild_installed import Sandbox, tree_digest
        path = self.agent()
        self.receipt(path)
        box = Sandbox(self.root/'retention-installed')
        package, _ = box.install('agent-tuneup')
        before = tree_digest(self.native, self.root/'roles')
        for script, env in [(SCRIPT, None), (package/'scripts/align.py', box.env)]:
            for requested in (False, True):
                with self.subTest(installed=env is not None, requested=requested):
                    self.provider.pop('assessments', None)
                    if requested:
                        self.request(path, 'extract-role')
                    out = self.root/f'retention-{env is not None}-{requested}.json'
                    result, report = self.run_public(script, env=env, extra=['--private-out', str(out)])
                    self.assertEqual(result.returncode, 1, result.stderr)
                    provider = json.loads(out.read_text())['providers'][0]
                    row = provider['items'][0]
                    self.assertEqual(row['ownership']['status'], 'verified')
                    self.assertEqual(row['disposition'], 'extract-role' if requested else 'preserve-unmanaged')
                    self.assertFalse(row['automatic_eligibility'])
                    self.assertEqual(provider['assessment_refusals'], [])
                    if requested:
                        self.assertEqual(row['assessment_status'], 'bound-declaration')
                    else:
                        self.assertEqual(row['reason'],
                            'Verified ownership; preserve the object pending a bound assessment.')
                        self.assertIsNone(row['followup_operation'])
                    self.assertEqual(report['wiring']['agent_inventory']['providers'][0]['items'][0]['ownership'],
                                     'verified')
        self.assertEqual(before, tree_digest(self.native, self.root/'roles'))

    def test_public_unmatched_provider_and_role_assessments_are_indexed_and_redacted(self):
        from tests.test_rebuild_installed import Sandbox, tree_digest
        target = self.file('source/role.md', '---\nmode: subagent\n---\nSynthetic')
        link = self.native/'managed.md'; link.symlink_to(target)
        self.provider['read_paths'] = [str(target)]
        self.receipt(link)
        self.request(link)
        role = self.file('roles/scout.md', 'Synthetic expertise only.')
        self.receipt(role, 'role')
        proof = copy.deepcopy(self.provider['assessments'][0]['evidence'])
        role_spec = {'ownership_receipts': [self.provider['ownership_receipts'].pop()],
                     'caller_references': copy.deepcopy(self.provider['caller_references']),
                     'assessments': [{'path': str(role), 'disposition': 'keep',
                                      'reason': 'Synthetic intent', 'evidence': proof}]}
        self.inventory['wiring']['role_evidence'] = role_spec
        _, baseline = self.inspect()
        # Include absent and existing-but-out-of-scope paths. Neither is an item.
        outside = self.file('excluded/secret-role.md', 'Never discover this object.')
        for supplied in (self.provider, role_spec):
            matched = supplied['assessments'][0]
            supplied['assessments'] = [
                dict(matched, path=str(self.root/'private-typo.md'), reason='secret-operator-reason'),
                matched, dict(matched, path=str(outside), reason='secret-operator-reason')]
        box = Sandbox(self.root/'assessment-installed')
        package, _ = box.install('agent-tuneup')
        before = tree_digest(self.native, self.root/'roles', outside.parent)
        for script, env in [(SCRIPT, None), (package/'scripts/align.py', box.env)]:
            with self.subTest(installed=env is not None):
                out = self.root/f'assessments-{env is not None}.json'
                result, report = self.run_public(script, env=env, extra=['--private-out', str(out)])
                self.assertEqual(result.returncode, 1, result.stderr)
                plan = json.loads(out.read_text())
                self.assertEqual(plan['providers'][0]['items'], baseline['providers'][0]['items'])
                self.assertEqual(plan['roles'], baseline['roles'])
                expected = {f'{location}.assessments[{index}]'
                    for location in ('wiring.providers[0].orchestration', 'wiring.role_evidence')
                    for index in (0, 2)}
                refused = [f for f in report['wiring']['agent_inventory']['findings']
                           if f['code'] == 'agent_assessment_refused']
                self.assertEqual(len(refused), 4)
                self.assertEqual({f['location'] for f in refused}, expected)
                for rows in (plan['providers'][0]['assessment_refusals'], plan['role_assessment_refusals']):
                    self.assertEqual([r['assessment'] for r in rows], [0, 2])
                    self.assertEqual([r['path'] for r in rows], [str(self.root/'private-typo.md'), str(outside)])
                    self.assertTrue(all(r['status'] == 'refused' and not r['automatic_eligibility'] for r in rows))
                    self.assertTrue(all(r['reason'] == 'No discovered item matches the supplied path.' for r in rows))
                for secret in (str(self.root), 'private-typo', 'secret-role', 'secret-operator-reason'):
                    self.assertNotIn(secret, result.stdout)
                self.assertNotIn('secret-operator-reason', out.read_text())
                self.assertEqual(plan['writes'], 0)
                self.assertFalse(plan['apply_supported'])
        self.assertEqual(before, tree_digest(self.native, self.root/'roles', outside.parent))

    def test_public_unmatched_assessments_refused_when_discovery_has_no_items(self):
        self.request(self.root/'private-unknown.md')
        self.provider['assessments'][0]['reason'] = 'secret-operator-reason'
        self.inventory['wiring']['role_evidence'] = {
            'assessments': copy.deepcopy(self.provider['assessments'])}
        for case, version, roots, config, expected_exit in [
                ('unknown', None, True, '{}', 1),
                ('unsupported', '99.0.0', True, '{}', 1),
                ('unsupplied', '2.1.2', False, '{}', 1),
                ('invalid', '2.1.2', True, '{', 2)]:
            with self.subTest(case=case):
                self.provider['runtime_version'] = version
                self.provider['agent_roots'] = ([{'path': str(self.root/'absent-native'),
                    'scope': 'global', 'format': 'markdown'}] if roots else [])
                self.inventory['wiring']['role_roots'] = ([{'path': str(self.root/'absent-roles'),
                    'scope': 'shared'}] if roots else [])
                self.file('config.jsonc', config)
                out = self.root/f'no-items-{case}.json'
                result, report = self.run_public(extra=['--private-out', str(out)])
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                plan = json.loads(out.read_text())
                self.assertEqual(plan['providers'][0]['items'], [])
                self.assertEqual(plan['roles'], [])
                refused = [f for f in report['wiring']['agent_inventory']['findings']
                           if f['code'] == 'agent_assessment_refused']
                self.assertEqual({f['location'] for f in refused}, {
                    'wiring.providers[0].orchestration.assessments[0]', 'wiring.role_evidence.assessments[0]'})
                self.assertEqual(len(refused), 2)
                for rows in (plan['providers'][0]['assessment_refusals'], plan['role_assessment_refusals']):
                    self.assertEqual(len(rows), 1)
                    self.assertFalse(rows[0]['automatic_eligibility'])
                self.assertNotIn(str(self.root), result.stdout)
                self.assertNotIn('secret-operator-reason', result.stdout + out.read_text())

    def test_receipt_target_caller_and_intent_drift_refuse_eligibility(self):
        target = self.file('source.md', '---\nmode: subagent\n---\nSynthetic')
        alias = self.native/'managed.md'; alias.symlink_to(target)
        self.provider['read_paths'] = [str(target)]
        receipt, _ = self.receipt(alias); self.request(alias)
        self.assertTrue(self.items()[0]['automatic_eligibility'])
        target.write_text('---\nmode: subagent\n---\nChanged target')
        self.assertFalse(self.items()[0]['automatic_eligibility'])
        target.write_text('---\nmode: subagent\n---\nSynthetic')
        proof = self.root/'caller-proof'; proof.write_text('changed')
        self.assertFalse(self.items()[0]['automatic_eligibility'])
        self.request(alias)
        alias.unlink(); alias.symlink_to('missing.md')
        self.assertFalse(self.items()[0]['automatic_eligibility'])
        alias.unlink(); alias.symlink_to(target)
        receipt.write_text('{')
        self.assertFalse(self.items()[0]['automatic_eligibility'])

    def test_portable_role_ownership_and_ambiguous_claims_preserve(self):
        role = self.file('roles/scout.md', 'Synthetic expertise only.')
        receipt, _ = self.receipt(role, 'role')
        self.inventory['wiring']['role_evidence'] = {
            'ownership_receipts': self.provider.pop('ownership_receipts')}
        self.assertEqual(self.inspect()[1]['roles'][0]['ownership']['status'], 'verified')
        self.inventory['wiring']['role_evidence']['ownership_receipts'].append(self.bound(receipt))
        self.assertEqual(self.inspect()[1]['roles'][0]['disposition'], 'unresolved')

    def test_primary_adapter_needs_provenance_and_preserves_entrypoint(self):
        path = self.agent('entry', 'mode: primary')
        self.receipt(path, 'primary-adapter')
        self.request(path)
        row = self.items()[0]
        self.assertEqual(row['classification'], 'primary-adapter')
        self.assertEqual(row['disposition'], 'keep-as-native-exception')
        self.assertFalse(row['automatic_eligibility'])

    def test_public_clean_v2_audit_exit_zero_and_scope_narrowing(self):
        self.catalog['providers'] = self.catalog['providers'][:1]
        self.inventory['wiring']['providers'] = [self.provider]
        proof = self.file('surface-proof', 'Synthetic observation')
        self.inventory['wiring']['authorities'] = {s: [self.bound(proof)] for s in align.wiring.SURFACES}
        self.provider['surfaces'] = {s: {'state': 'configured', 'evidence': [self.bound(proof)]}
                                     for s in align.wiring.SURFACES}
        skills = self.root/'skills'; skills.mkdir()
        self.inventory['wiring']['shared_skills'] = str(skills)
        ignored = self.file('not-in-read-scope/invalid.md', 'Invalid native data, must not be read')
        before = ignored.read_bytes()
        result, report = self.run_public()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report['wiring']['version'], 2)
        self.assertEqual(before, ignored.read_bytes())

    def test_directory_and_data_limits_fail_closed(self):
        self.agent()
        with patch.object(agents, 'MAX_ENTRIES', 4):
            for number in range(5):
                self.agent('extra' + str(number))
            self.assertTrue(self.inspect()[0]['fatal'])
        for raw in ('[' * 1000 + '0' + ']' * 1000, b'x' * (agents.MAX_BYTES + 1)):
            with self.subTest(kind=type(raw).__name__):
                (self.root/'config.jsonc').write_bytes(raw.encode() if isinstance(raw, str) else raw)
                self.assertTrue(self.inspect()[0]['fatal'])

    def test_receipt_name_or_familiar_target_never_proves_ownership(self):
        self.agent('t3-managed-reviewer')
        self.assertEqual(self.items()[0]['ownership']['status'], 'unmanaged')
        path = self.agent('ordinary')
        receipt, _ = self.receipt(path)
        data = json.loads(receipt.read_text()); data['items'][0]['mode'] ^= 0o100
        receipt.write_text(json.dumps(data))
        self.provider['ownership_receipts'] = [self.bound(receipt)]
        rows = {r['name']: r for r in self.items()}
        self.assertEqual(rows['ordinary']['ownership']['status'], 'modified')

    def test_unknown_callers_references_stale_intent_and_ambiguous_alias_refuse(self):
        source = self.agent('original')
        alias = self.native/'managed.md'; alias.symlink_to(source)
        self.receipt(alias); self.request(alias)
        self.provider['caller_references']['state'] = 'unknown'
        self.assertFalse(next(r for r in self.items() if r['name'] == 'managed')['automatic_eligibility'])
        self.request(alias, names=['managed'])
        self.assertFalse(next(r for r in self.items() if r['name'] == 'managed')['automatic_eligibility'])
        self.request(alias)
        (self.native/'other.md').symlink_to(source)
        row = next(r for r in self.items() if r['name'] == 'managed')
        self.assertTrue(row['ambiguous_alias']); self.assertFalse(row['automatic_eligibility'])

    def test_vendor_repo_worker_role_and_custom_remain_separate(self):
        paths = [self.agent(n) for n in ('vendor', 'worker', 'custom')]
        self.receipt(paths[0], 'vendor'); self.receipt(paths[1], 'repo-worker')
        self.file('roles/sre.md', 'Synthetic expertise. No actions granted.')
        _, plan = self.inspect()
        rows = {r['name']: r for r in plan['providers'][0]['items']}
        self.assertEqual(rows['vendor']['classification'], 'vendor-content')
        self.assertEqual(rows['vendor']['disposition'], 'preserve-unmanaged')
        self.assertEqual(rows['worker']['classification'], 'repo-managed-worker')
        self.assertEqual(rows['worker']['disposition'], 'keep')
        self.assertEqual(rows['custom']['classification'], 'custom-definition')
        self.assertEqual(plan['roles'][0]['classification'], 'portable-role')
        self.assertFalse(plan['roles'][0]['metadata']['authority_granted'])

    def test_invalid_v2_fields_rejected_even_for_unsupported_versions(self):
        self.provider['runtime_version'] = '99.0.0'
        for field, value in [('agent_roots', 'not-a-list'), ('read_paths', 'relative'),
                             ('ownership_receipts', [{'path':'relative','sha256':'f'*64}]),
                             ('assessments', [{'path':'relative'}]), ('typo', True)]:
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                altered = copy.deepcopy(self.inventory)
                altered['wiring']['providers'][0][field] = value
                align.compare(self.catalog, altered)

    def test_legacy_unknown_and_mixed_versions_through_public_audit(self):
        legacy = json.loads((PLUGIN/'fixtures/agent-inventory-v1.json').read_text())
        self.inventory = legacy
        result, report = self.run_public()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['wiring']['agent_inventory']['coverage'], 'unavailable')
        for version in (True, 0, 3, '2'):
            self.inventory['wiring']['version'] = version
            self.assertEqual(self.run_public()[0].returncode, 2)
        self.inventory['wiring']['version'] = 1
        self.inventory['wiring']['role_roots'] = []
        self.assertEqual(self.run_public()[0].returncode, 2)

    def test_private_plan_exclusive_redacted_and_revalidation_refuses_drift(self):
        self.agent(body='fixture-secret https://private.invalid credential=sentinel')
        out = self.root/'private-plan.json'
        result, report = self.run_public(extra=['--private-out', str(out)])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        for secret in ('fixture-secret', 'private.invalid', 'sentinel', str(self.root), 'fixture-native'):
            self.assertNotIn(secret, result.stdout)
            self.assertNotIn(secret, out.read_text()) if secret in {'fixture-secret','private.invalid','sentinel'} else None
        self.assertEqual(self.run_public(extra=['--private-out', str(out)])[0].returncode, 2)
        self.assertEqual(self.run_public(extra=['--revalidate-plan', str(out)])[0].returncode, 1)
        self.agent(body='Edited synthetic prompt')
        self.assertEqual(self.run_public(extra=['--revalidate-plan', str(out)])[0].returncode, 2)
        self.assertEqual(report['normalization_plan'], 'private-proposal-only')

    def test_plan_cannot_be_used_by_settings_apply(self):
        _, plan = self.inspect()
        with self.assertRaisesRegex(ValueError, 'agent_plan_has_no_apply'), patch.object(align, 'prepare') as prepare:
            align.apply(plan, 'synthetic', str(self.root/'backup'))
        prepare.assert_not_called()

    def test_audit_never_mutates_native_or_settings_trees(self):
        from tests.test_rebuild_installed import tree_digest
        self.agent(); (self.native/'broken.md').symlink_to('missing')
        self.file('roles/custom.md', 'Synthetic expertise')
        before = tree_digest(self.native, self.root/'roles')
        config = (self.root/'config.jsonc').read_bytes()
        with patch.object(align, 'apply', side_effect=AssertionError('audit may not apply')):
            self.inspect()
        self.run_public()
        self.assertEqual(before, tree_digest(self.native, self.root/'roles'))
        self.assertEqual(config, (self.root/'config.jsonc').read_bytes())

    def test_installed_public_audit_and_version_dispatch_from_foreign_cwd(self):
        from tests.test_rebuild_installed import Sandbox, tree_digest
        box = Sandbox(self.root/'installed')
        package, _ = box.install('agent-tuneup')
        self.agent()
        before = tree_digest(self.native, self.root/'roles')
        result, report = self.run_public(package/'scripts/align.py', env=box.env, tag='installed')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(report['wiring']['version'], 2)
        self.assertEqual(len(report['wiring']['agent_inventory']['providers']), 3)
        self.assertEqual(before, tree_digest(self.native, self.root/'roles'))
        self.file('config.jsonc', '{"agent":{}}')
        self.assertEqual(self.run_public(package/'scripts/align.py', env=box.env)[0].returncode, 2)
        self.inventory['wiring'] = {'version': 1}
        result, report = self.run_public(package/'scripts/align.py', env=box.env)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['wiring']['agent_inventory']['coverage'], 'unavailable')
        self.inventory['wiring']['version'] = 99
        self.assertEqual(self.run_public(package/'scripts/align.py', env=box.env)[0].returncode, 2)

    def test_public_read_inputs_relative_parent_and_alias_match_absolute(self):
        from tests.test_rebuild_installed import Sandbox, tree_digest
        box = Sandbox(self.root/'relative-installed')
        package, _ = box.install('agent-tuneup')
        self.agent(body='fixture-secret https://private.invalid credential=sentinel')
        foreign = self.root/'client'
        inputs = foreign/'inputs'
        nested = foreign/'nested'; nested.mkdir(parents=True)
        catalog = self.file('client/inputs/catalog.json', json.dumps(self.catalog))
        inventory = self.file('client/inputs/inventory.json', json.dumps(self.inventory))
        plan = inputs/'plan.json'
        for path in (catalog, inventory, plan):
            (inputs/('alias-' + path.name)).symlink_to(path.name)
        linked = foreign/'linked'; linked.symlink_to(inputs, target_is_directory=True)
        before = tree_digest(self.native, self.root/'roles'), (self.root/'config.jsonc').read_bytes()
        layouts = [(inputs, ''), (foreign, 'inputs/'), (nested, '../inputs/'), (inputs, 'alias-')]
        for script, env in ((SCRIPT, None), (package/'scripts/align.py', box.env)):
            def run(operation, cwd, cat, inv, extra=()):
                result = subprocess.run([sys.executable, '-I', str(script), operation, '--catalog', str(cat),
                    '--inventory', str(inv), *extra], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
                return result.returncode, json.loads(result.stdout)
            for operation in ('compare', 'audit'):
                with self.subTest(installed=env is not None, operation=operation):
                    baseline = run(operation, foreign, catalog, inventory, ['--private-out', str(plan)])
                    self.assertEqual(baseline[0], 0 if operation == 'compare' else 1)
                    self.assertEqual(stat.S_IMODE(plan.stat().st_mode), 0o600)
                    preserved = tree_digest(inputs)
                    for cwd, prefix in layouts:
                        with self.subTest(cwd=cwd.name, prefix=prefix):
                            self.assertEqual(run(operation, cwd, prefix+'catalog.json', prefix+'inventory.json',
                                ['--revalidate-plan', prefix+'plan.json']), baseline)
                    self.assertEqual(preserved, tree_digest(inputs))
                    for secret in ('fixture-secret', 'private.invalid', 'sentinel'):
                        self.assertNotIn(secret, json.dumps(baseline) + plan.read_text())
                    self.assertNotIn(str(self.root), json.dumps(baseline))
                    self.assertEqual(baseline[1]['writes'], 0)
                    plan.unlink()
            # V1 keeps its coverage gap, and an unknown version reaches version
            # dispatch rather than being mistaken for an unsafe relative path.
            for version in (1, 99):
                legacy = json.loads((PLUGIN/'fixtures/agent-inventory-v1.json').read_text())
                legacy['wiring']['version'] = version
                inventory.write_text(json.dumps(legacy))
                for operation in ('compare', 'audit'):
                    absolute = run(operation, foreign, catalog, inventory)
                    self.assertEqual(run(operation, nested, '../inputs/catalog.json', '../inputs/inventory.json'), absolute)
                    self.assertEqual(absolute[0], 2 if version == 99 else (1 if operation == 'audit' else 0))
                    if version == 1:
                        self.assertEqual(absolute[1]['wiring']['agent_inventory']['coverage'], 'unavailable')
                    else:
                        self.assertEqual(absolute[1]['error'], 'invalid_unsafe_stale_or_unapproved_input')
                        with self.assertRaisesRegex(ValueError, 'invalid_wiring_inventory'):
                            align.compare(self.catalog, legacy)
            inventory.write_text(json.dumps(self.inventory))
            # The normalization applies to read inputs only, including error paths.
            for bad in ('missing.json', 'invalid.json'):
                if bad == 'invalid.json':
                    (inputs/bad).write_text('{')
                self.assertEqual(run('audit', inputs, catalog, bad), run('audit', foreign, catalog, inputs/bad))
                self.assertEqual(run('audit', inputs, catalog, bad)[0], 2)
            self.assertEqual(run('compare', inputs, catalog, inventory, ['--private-out', 'refused.json'])[0], 2)
            self.assertEqual(run('compare', foreign, catalog, inventory, ['--private-out', str(linked/'refused.json')])[0], 2)
            self.assertFalse((inputs/'refused.json').exists())
        self.assertEqual(before, (tree_digest(self.native, self.root/'roles'), (self.root/'config.jsonc').read_bytes()))

    def test_low_level_read_still_refuses_relative_and_parent_paths(self):
        self.file('read.json', '{}')
        for path in (Path('read.json'), self.root/'native/../read.json'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'invalid_agent_path'):
                agents.read(path)


if __name__ == '__main__':
    unittest.main()
