"""Central coverage, duplicate retirement diagnostics and all-destination safety."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/agent-tuneup/scripts/align.py'
spec = importlib.util.spec_from_file_location('wiring_alignment', SCRIPT)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
wiring = align.wiring


class WiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.catalog = {'providers': [{'providerInstanceId': name} for name in ('a', 'disabled', 'future')]}

    def file(self, name, raw='synthetic evidence'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        path.chmod(0o600)
        return path

    def evidence(self, path):
        return [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]

    def test_default_compare_includes_all_surfaces_for_all_catalog_providers(self):
        result = align.compare(self.catalog, {'version': 1, 'providers': []})
        central = result['wiring']
        self.assertEqual(len(central['providers']), 3)
        for row in central['providers']:
            self.assertEqual([c['surface'] for c in row['surfaces']], list(wiring.SURFACES))
            self.assertTrue(all(c['declared'] == 'unknown' for c in row['surfaces']))
        self.assertIn('permissions', wiring.SURFACES)
        self.assertEqual(central['writes'], 0)
        self.assertEqual(central['loading'], 'unverified')

    def test_bound_evidence_is_freshness_only_and_unknown_versions_remain_explicit(self):
        path = self.file('private-evidence', 'fixture-secret')
        cells = {surface: {'state': 'configured', 'evidence': self.evidence(path)}
                 for surface in wiring.SURFACES}
        inventory = {'version': 1, 'authorities': {s: self.evidence(path) for s in wiring.SURFACES},
                     'providers': [{'provider_instance_id': 'a', 'surfaces': cells}]}
        result = wiring.inspect(self.catalog, inventory)
        self.assertTrue(all(c['evidence'] == 'bound' for c in result['providers'][0]['surfaces']))
        self.assertEqual(result['providers'][0]['version'], 'unknown')
        self.assertIn('runtime_version_unknown', {f['code'] for f in result['findings']})
        for secret in ('fixture-secret', 'private-evidence', str(path), 'disabled', 'future'):
            self.assertNotIn(secret, json.dumps(result))
        path.write_text('changed')
        result = wiring.inspect(self.catalog, inventory)
        self.assertEqual(result['authorities'][0]['evidence'], 'stale')
        self.assertEqual(result['providers'][0]['surfaces'][0]['evidence'], 'stale')

    def test_unsupported_needs_reason_and_evidence_not_silent_omission(self):
        path = self.file('reason')
        cell = {'state': 'unsupported', 'reason': 'documented native limit', 'evidence': self.evidence(path)}
        inventory = {'providers': [{'provider_instance_id': 'a', 'runtime_version': 'synthetic',
                                    'surfaces': {'mcp': cell}}]}
        result = wiring.inspect(self.catalog, inventory)
        self.assertFalse(any(f['location'] == 'wiring.providers[0].mcp' for f in result['findings']))
        cell.pop('reason')
        result = wiring.inspect(self.catalog, inventory)
        self.assertTrue(any(f['location'] == 'wiring.providers[0].mcp' for f in result['findings']))

    def test_shared_readers_report_redundant_aliases_and_retired_skills_preserving_vendor(self):
        shared = self.root / 'shared'
        native = self.root / 'native'
        skill = self.file('shared/ordinary/SKILL.md')
        self.file('shared/hatch-pet/SKILL.md')
        self.file('shared/sync-harness-permissions/SKILL.md')
        self.file('native/vendor/SKILL.md', 'vendor contents')
        (native / 'ordinary').symlink_to(skill.parent, target_is_directory=True)
        before = sorted(str(p) for p in self.root.rglob('*'))
        result = wiring.inspect(self.catalog, {'shared_skills': str(shared), 'providers': [{
            'provider_instance_id': 'a', 'reads_shared_skills': True, 'skill_roots': [str(native)]}]})
        codes = {f['code'] for f in result['findings']}
        self.assertTrue({'retired_skill_present', 'redundant_skill_alias', 'duplicate_skill_discovery'} <= codes)
        self.assertEqual(result['skill_roots'][0]['retired_skills'], 2)
        self.assertEqual(result['skill_roots'][1]['local_or_vendor'], 2)
        self.assertEqual((native / 'vendor/SKILL.md').read_text(), 'vendor contents')
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))

    def test_missing_shared_root_and_broken_retired_alias_are_findings(self):
        native = self.root / 'native'
        native.mkdir()
        (native / 'hatch-pet').symlink_to(self.root / 'gone', target_is_directory=True)
        result = wiring.inspect(self.catalog, {'shared_skills': str(self.root / 'absent'), 'providers': [{
            'provider_instance_id': 'a', 'skill_roots': [str(native)]}]})
        self.assertTrue({'skill_root_unreadable', 'retired_skill_present'} <= {f['code'] for f in result['findings']})

    def test_required_aliases_are_unique_in_each_nonshared_provider(self):
        skill = self.file('shared/ordinary/SKILL.md')
        for name in ('a', 'disabled'):
            (self.root / name).mkdir()
            (self.root / name / 'ordinary').symlink_to(skill.parent, target_is_directory=True)
        providers = [{'provider_instance_id': name, 'reads_shared_skills': False,
                      'skill_roots': [str(self.root / name)]} for name in ('a', 'disabled')]
        inventory = {'shared_skills': str(self.root / 'shared'), 'providers': providers}
        result = wiring.inspect(self.catalog, inventory)
        self.assertFalse(any(f['code'] in {'duplicate_skill_discovery', 'redundant_skill_alias'}
                             for f in result['findings']))
        providers[0]['reads_shared_skills'] = True
        result = wiring.inspect(self.catalog, inventory)
        duplicates = [f['location'] for f in result['findings'] if f['code'] == 'duplicate_skill_discovery']
        self.assertEqual(duplicates, ['wiring.skill_roots[1]'])

    def test_two_effective_roots_in_one_provider_still_report_duplicate(self):
        skill = self.file('shared/ordinary/SKILL.md')
        for name in ('native-one', 'native-two'):
            (self.root / name).mkdir()
            (self.root / name / 'ordinary').symlink_to(skill.parent, target_is_directory=True)
        result = wiring.inspect(self.catalog, {'shared_skills': str(self.root / 'shared'), 'providers': [{
            'provider_instance_id': 'a', 'reads_shared_skills': False,
            'skill_roots': [str(self.root / 'native-one'), str(self.root / 'native-two')]}]})
        self.assertGreaterEqual(len(result['skill_roots']), 3)
        duplicates = [f for f in result['findings'] if f['code'] == 'duplicate_skill_discovery']
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]['location'], 'wiring.skill_roots[2]')
        root_number = int(duplicates[0]['location'].split('[')[1].split(']')[0])
        self.assertEqual(result['skill_roots'][root_number]['provider'], 0)

    def test_unresolvable_skill_entry_does_not_discard_other_root_observations(self):
        root = self.root / 'skills'
        root.mkdir()
        (root / 'loop').mkdir()
        (root / 'loop' / 'SKILL.md').write_text('fixture')
        original = Path.resolve

        def resolve(path, *args, **kwargs):
            if path.name == 'loop':
                raise OSError('simulated junction loop')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'resolve', resolve):
            result = wiring.inspect(self.catalog, {'providers': [{
                'provider_instance_id': 'a', 'skill_roots': [str(root)]}]})
        self.assertEqual(result['skill_roots'][0]['status'], 'observed')
        self.assertEqual(result['skill_roots'][0]['skills'], 1)
        self.assertIn('skill_entry_unresolvable', {f['code'] for f in result['findings']})
        self.assertNotIn('skill_root_unreadable', {f['code'] for f in result['findings']})

    def test_python311_windows_junction_attributes_are_counted_as_aliases(self):
        path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400))
        self.assertTrue(wiring.is_alias(path))
        self.assertFalse(wiring.is_alias(self.root))

    def test_receipt_counts_require_every_owned_file_to_match(self):
        skill = self.file('shared/t3-example/SKILL.md')
        extra = self.file('shared/t3-example/agents/openai.yaml', 'metadata')
        self.file('shared/t3-example/.t3-plugins-skill.json', json.dumps({
            'schema_version': 1, 'name': 't3-example',
            'sha256': hashlib.sha256(skill.read_bytes()).hexdigest(),
            'files': {'agents/openai.yaml': hashlib.sha256(extra.read_bytes()).hexdigest()}}))
        inventory = {'shared_skills': str(self.root / 'shared')}
        self.assertEqual(wiring.inspect(self.catalog, inventory)['skill_roots'][0]['receipt_owned'], 1)
        extra.write_text('operator edit')
        result = wiring.inspect(self.catalog, inventory)
        row = result['skill_roots'][0]
        self.assertEqual(row['receipt_owned'], 0)
        self.assertEqual(row['local_or_vendor'], 0)
        self.assertEqual(row['entries'][0]['receipts'], [{'owner': 't3-plugins', 'status': 'modified'}])
        self.assertIn('skill_receipt_modified', {f['code'] for f in result['findings']})
        self.assertEqual(extra.read_text(), 'operator edit')
        marker = skill.parent / '.t3-plugins-skill.json'
        receipt = json.loads(marker.read_text())
        receipt['files']['operator.txt'] = '0' * 64
        marker.write_text(json.dumps(receipt))
        self.assertEqual(wiring.skill_receipts(skill.parent), [{'owner': 't3-plugins', 'status': 'invalid'}])

    def test_common_dotfiles_receipt_checks_all_files_through_read_alias(self):
        skill = self.file('shared/ordinary/SKILL.md')
        extra = self.file('shared/ordinary/references/detail.txt', 'detail')
        marker = self.file('shared/ordinary/.dotfiles-skill.json', json.dumps({
            'schema_version': 1, 'name': 'ordinary', 'files': {
                'SKILL.md': hashlib.sha256(skill.read_bytes()).hexdigest(),
                'references/detail.txt': hashlib.sha256(extra.read_bytes()).hexdigest()}}))
        alias = self.root / 'native'
        alias.symlink_to(skill.parent.parent, target_is_directory=True)
        inventory = {'providers': [{'provider_instance_id': 'a', 'skill_roots': [str(alias)]}]}
        before = {p: p.read_bytes() for p in (skill, extra, marker)}
        result = wiring.inspect(self.catalog, inventory)
        row = result['skill_roots'][0]
        self.assertEqual(row['receipt_owned'], 1)
        self.assertEqual(row['aliases'], 1)
        self.assertEqual(row['entries'][0]['receipts'], [{'owner': 'dotfiles', 'status': 'verified'}])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        extra.write_text('edited')
        self.assertEqual(wiring.inspect(self.catalog, inventory)['skill_roots'][0]['entries'][0]['receipts'][0]['status'],
                         'modified')
        extra.unlink()
        self.assertEqual(wiring.inspect(self.catalog, inventory)['skill_roots'][0]['entries'][0]['receipts'][0]['status'],
                         'modified')

    def test_recognized_bad_receipts_never_become_vendor_content(self):
        skill = self.file('shared/ordinary/SKILL.md')
        inventory = {'shared_skills': str(skill.parent.parent)}
        for owner, marker in (('dotfiles', '.dotfiles-skill.json'), ('t3-plugins', '.t3-plugins-skill.json')):
            for raw, status in (('{', 'invalid'), ('[]', 'invalid'),
                                (json.dumps({'schema_version': 2}), 'unsupported')):
                with self.subTest(owner=owner, raw=raw):
                    receipt = self.file('shared/ordinary/' + marker, raw)
                    result = wiring.inspect(self.catalog, inventory)
                    row = result['skill_roots'][0]
                    self.assertEqual(row['local_or_vendor'], 0)
                    self.assertEqual(row['entries'][0]['receipts'], [{'owner': owner, 'status': status}])
                    self.assertIn('skill_receipt_' + status, {f['code'] for f in result['findings']})
                    self.assertEqual(receipt.read_text(), raw)
                    receipt.unlink()
        self.assertEqual(wiring.inspect(self.catalog, inventory)['skill_roots'][0]['entries'][0]['receipts'],
                         [{'owner': 'unmanaged', 'status': 'unmanaged'}])

    def test_untrusted_receipt_paths_rejected_before_asset_reads(self):
        skill = self.file('shared/ordinary/SKILL.md')
        digest = hashlib.sha256(skill.read_bytes()).hexdigest()
        for name in ('../outside', '/outside', 'C:\\outside', 'a/../../outside', './SKILL.md', 'a//b'):
            with self.subTest(path=name):
                marker = self.file('shared/ordinary/.dotfiles-skill.json', json.dumps({
                    'schema_version': 1, 'name': 'ordinary', 'files': {'SKILL.md': digest, name: digest}}))
                with patch.object(wiring, 'read_file', wraps=wiring.read_file) as read:
                    receipts = wiring.skill_receipts(skill.parent)
                self.assertEqual(receipts, [{'owner': 'dotfiles', 'status': 'invalid'}])
                self.assertEqual([call.args[0] for call in read.call_args_list], [marker])

    def test_receipt_asset_alias_cannot_escape_skill_directory(self):
        skill = self.file('shared/ordinary/SKILL.md')
        outside = self.file('outside', 'preserve')
        alias = skill.parent / 'extra'
        alias.symlink_to(outside)
        self.file('shared/ordinary/.dotfiles-skill.json', json.dumps({
            'schema_version': 1, 'name': 'ordinary', 'files': {
                'SKILL.md': hashlib.sha256(skill.read_bytes()).hexdigest(),
                'extra': hashlib.sha256(outside.read_bytes()).hexdigest()}}))
        self.assertEqual(wiring.skill_receipts(skill.parent), [{'owner': 'dotfiles', 'status': 'invalid'}])
        self.assertTrue(alias.is_symlink())
        self.assertEqual(outside.read_text(), 'preserve')

    @unittest.skipUnless(os.name == 'posix', 'FIFO fixture requires POSIX')
    def test_receipted_special_file_is_invalid_and_preserved(self):
        if not hasattr(os, 'mkfifo'):
            self.skipTest('FIFO fixtures require os.mkfifo')
        skill = self.file('shared/ordinary/SKILL.md')
        fifo = skill.parent / 'fifo'
        os.mkfifo(fifo)
        self.file('shared/ordinary/.dotfiles-skill.json', json.dumps({
            'schema_version': 1, 'name': 'ordinary', 'files': {
                'SKILL.md': hashlib.sha256(skill.read_bytes()).hexdigest(), 'fifo': '0' * 64}}))
        self.assertEqual(wiring.skill_receipts(skill.parent), [{'owner': 'dotfiles', 'status': 'invalid'}])
        self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))

    def test_invalid_wiring_is_rejected_without_echoing_values(self):
        inventory = self.file('inventory.json', json.dumps({'version': 1, 'providers': [], 'wiring': {
            'providers': [{'provider_instance_id': 'fixture-secret'}]}}))
        catalog = self.file('catalog.json', json.dumps(self.catalog))
        result = subprocess.run([sys.executable, str(SCRIPT), 'compare', '--catalog', str(catalog),
                                 '--inventory', str(inventory)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('fixture-secret', result.stdout + result.stderr)

    def test_general_audit_reports_missing_coverage_as_findings(self):
        inventory = self.file('inventory.json', '{"version":1,"providers":[]}')
        catalog = self.file('catalog.json', json.dumps(self.catalog))
        result = subprocess.run([sys.executable, str(SCRIPT), 'audit', '--catalog', str(catalog),
                                 '--inventory', str(inventory)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['writes'], 0)
        self.assertTrue(json.loads(result.stdout)['wiring']['findings'])

    def test_general_audit_unreadable_native_layer_is_a_blocker(self):
        inventory = self.file('inventory.json', json.dumps({'version': 1, 'providers': [{
            'provider_instance_id': 'a', 'adapter': 'claude',
            'sources': [{'scope': 'global', 'path': str(self.root / 'missing')}]}]}))
        catalog = self.file('catalog.json', json.dumps(self.catalog))
        result = subprocess.run([sys.executable, str(SCRIPT), 'audit', '--catalog', str(catalog),
                                 '--inventory', str(inventory)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['audit_exit_code'], 2)
        self.assertEqual(receipt['writes'], 0)

    def test_audit_capability_gaps_need_specific_fresh_exception_evidence(self):
        evidence = self.file('evidence')
        cells = {s: {'state': 'configured', 'evidence': self.evidence(evidence)} for s in wiring.SURFACES}
        settings = self.file('settings', '{}')
        shared = self.root / 'empty-shared'
        shared.mkdir()
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'a', 'adapter': 'claude',
                     'sources': [{'path': str(settings), 'scope': 'global'}]}],
                     'wiring': {'shared_skills': str(shared),
                                'authorities': {s: self.evidence(evidence) for s in wiring.SURFACES},
                                'providers': [{'provider_instance_id': 'a', 'runtime_version': 'fixture',
                                               'surfaces': cells}]},
                     'capabilities': [{'kind': 'mcp', 'members': {'a': 'fixture'}}]}
        catalog = self.file('catalog.json', json.dumps({'providers': [{'providerInstanceId': 'a'}]}))
        source = self.root / 'inventory.json'

        def run(operation='audit'):
            source.write_text(json.dumps(inventory))
            result = subprocess.run([sys.executable, str(SCRIPT), operation, '--catalog', str(catalog),
                                     '--inventory', str(source)], capture_output=True, text=True, timeout=60)
            return result.returncode, json.loads(result.stdout)

        scenarios = [(['{}'], 'not_in_supplied_sources'),
                     (['{"mcpServers":{"fixture":{}}}', '{"disabledMcpServers":["fixture"]}'], 'scope_conflict'),
                     (['{"enabledMcpjsonServers":["fixture"]}'], 'unknown'),
                     (['{"disabledMcpServers":["fixture"]}'], 'disabled')]
        for layers, state in scenarios:
            with self.subTest(state=state):
                inventory['providers'][0]['sources'] = [
                    {'path': str(self.file(f'layer-{i}', raw)), 'scope': 'global'} for i, raw in enumerate(layers)]
                code, receipt = run()
                self.assertEqual(code, 1)
                self.assertFalse(receipt['wiring']['findings'])
                self.assertEqual(receipt['capabilities'][0]['states'], [state])
                self.assertEqual(receipt['findings'][0]['code'], 'capability_' + state)
                self.assertEqual(run('compare')[0], 0)
        capability = inventory['capabilities'][0]
        capability['intentional_differences'] = {'a': {'reason': 'documented task scope',
                                                       'evidence': self.evidence(evidence)}}
        self.assertEqual(run()[0], 0)
        capability['intentional_differences']['a'].pop('reason')
        self.assertEqual(run()[0], 1)
        capability['intentional_differences']['a']['reason'] = 'documented task scope'
        evidence.write_text('changed')
        code, receipt = run()
        self.assertEqual(code, 1)
        self.assertTrue(receipt['findings'])
        inventory['providers'][0]['sources'] = [
            {'path': str(self.file('configured-settings', '{"mcpServers":{"fixture":{}}}')),
             'scope': 'global'}]
        capability['intentional_differences'] = {'a': {
            'reason': 'documented task scope', 'evidence': [{'path': 'notes.md'}]}}
        compared = align.compare(self.catalog, inventory)
        self.assertEqual(compared['providers'][0]['sources'][0]['status'], 'parsed')
        self.assertEqual(compared['capabilities'][0]['states'][0], 'configured')

    def test_malformed_capability_exception_evidence_is_invalid_input(self):
        evidence = self.file('evidence')
        settings = self.file('settings', '{}')
        inventory = {'version': 1, 'providers': [{'provider_instance_id': 'a', 'adapter': 'claude',
                     'sources': [{'path': str(settings), 'scope': 'global'}]}],
                     'capabilities': [{'kind': 'mcp', 'members': {'a': 'fixture'},
                                       'intentional_differences': {'a': {
                                           'reason': 'documented task scope',
                                           'evidence': self.evidence(evidence)}}}]}
        for malformed in ('not-an-array', [{'path': str(evidence), 'sha256': 'g' * 64}],
                          [{'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]):
            with self.subTest(evidence=malformed), self.assertRaises(ValueError):
                inventory['capabilities'][0]['intentional_differences']['a']['evidence'] = malformed
                align.compare(self.catalog, inventory)

    def test_malformed_evidence_is_rejected_after_stale_or_unreadable_entries(self):
        path = self.file('evidence')
        stale = self.evidence(path)[0]
        path.write_text('changed')
        unreadable = {'path': str(self.root / 'missing'), 'sha256': '0' * 64}
        malformed = [None, {'path': str(path), 'sha256': 'g' * 64},
                     {'path': str(path)}, {'path': 'relative', 'sha256': '0' * 64}]
        for first in (stale, unreadable):
            for invalid in malformed:
                for items in ([first, invalid], [invalid, first]):
                    with self.subTest(items=items), self.assertRaises(ValueError):
                        wiring.evidence_state(items)

    def plan(self, number):
        target = self.file(f'target-{number}', '{"permissions":{"allow":["Read(*)"]}}')
        candidate = self.file(f'candidate-{number}', '{"permissions":{"allow":[]}}')
        plan = align.prepare('claude', str(target), str(candidate), ['/permissions/allow'])[0]
        plan_path = self.file(f'plan-{number}', json.dumps(plan))
        return {'plan': str(plan_path), 'backup': str(self.root / f'backup-{number}')}, target

    def test_all_destination_preflight_is_read_only_and_not_approval(self):
        first, a = self.plan(1)
        second, b = self.plan(2)
        before = [a.read_bytes(), b.read_bytes()]
        result = align.preflight_batch([first, second])
        self.assertEqual(result['plans'], 2)
        self.assertEqual(result['authorization'], 'not_granted')
        self.assertEqual(result['settings_writes'], 0)
        self.assertEqual(before, [a.read_bytes(), b.read_bytes()])
        self.assertFalse(Path(first['backup']).exists())

    def test_batch_items_with_missing_or_non_string_paths_are_invalid_batch(self):
        for batch in ([{}], [{'plan': 4, 'backup': 'backup.json'}],
                      [{'plan': 'plan.json'}], [{'plan': 'plan.json', 'backup': None}]):
            with self.subTest(batch=batch), self.assertRaisesRegex(ValueError, 'invalid_batch'):
                align.preflight_batch(batch)

    def test_late_backup_conflict_stops_entire_preflight_without_writes(self):
        first, a = self.plan(1)
        second, b = self.plan(2)
        self.file('backup-2', 'preserve')
        with self.assertRaisesRegex(ValueError, 'invalid_backup'):
            align.preflight_batch([first, second])
        self.assertFalse(Path(first['backup']).exists())
        self.assertIn('Read(*)', a.read_text())
        self.assertIn('Read(*)', b.read_text())

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() != 0, 'requires an ordinary POSIX user')
    def test_readable_unwritable_second_parent_blocks_entire_batch(self):
        for destination in ('backup', 'target'):
            with self.subTest(destination=destination):
                first, a = self.plan('first-' + destination)
                second, b = self.plan('second-' + destination)
                blocked = self.root / ('blocked-' + destination)
                blocked.mkdir()
                if destination == 'backup':
                    second['backup'] = str(blocked / 'backup')
                else:
                    moved = blocked / b.name
                    b.rename(moved)
                    b = moved
                    document = json.loads(Path(second['plan']).read_text())
                    document = align.prepare('claude', str(b), document['candidate'], ['/permissions/allow'])[0]
                    Path(second['plan']).write_text(json.dumps(document))
                before = (a.read_bytes(), b.read_bytes())
                blocked.chmod(0o555)
                try:
                    with self.assertRaisesRegex(ValueError, 'destination_not_writable'):
                        align.preflight_batch([first, second])
                    self.assertEqual(before, (a.read_bytes(), b.read_bytes()))
                    self.assertFalse(Path(first['backup']).exists())
                    self.assertFalse(Path(second['backup']).exists())
                    self.assertFalse(any(p.name.startswith('.t3-tuneup-') for p in blocked.iterdir()))
                finally:
                    blocked.chmod(0o700)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() != 0, 'requires an ordinary POSIX user')
    def test_backup_parent_requires_search_access(self):
        first, _ = self.plan(1)
        blocked = self.root / 'no-search'
        blocked.mkdir()
        first['backup'] = str(blocked / 'backup')
        blocked.chmod(0o600)
        try:
            with self.assertRaises((PermissionError, ValueError)):
                align.preflight_batch([first])
        finally:
            blocked.chmod(0o700)
        self.assertEqual(list(blocked.iterdir()), [])

    def test_preflight_reports_unknown_when_effective_access_cannot_be_checked(self):
        first, _ = self.plan(1)
        with patch.object(os, 'supports_effective_ids', set()):
            with self.assertRaisesRegex(ValueError, 'destination_readiness_unknown'):
                align.preflight_batch([first])
        self.assertFalse(Path(first['backup']).exists())

    def test_stale_plan_linked_parent_and_cross_plan_overlap_refuse(self):
        first, a = self.plan(1)
        second, _ = self.plan(2)
        original = a.read_bytes()
        a.write_text('{}')
        with self.assertRaises(ValueError):
            align.preflight_batch([first, second])
        a.write_bytes(original)
        second['backup'] = first['plan']
        with self.assertRaises(ValueError):
            align.preflight_batch([first, second])
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        first['backup'] = str(alias / 'new-backup')
        with self.assertRaisesRegex(ValueError, 'symlink_refused'):
            align.preflight_batch([first])

    def test_trusted_system_aliases_cannot_hide_duplicate_targets(self):
        first, target = self.plan(1)
        second, _ = self.plan(2)
        alias = self.root / 'system-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        trusted = align.trusted_link
        with patch.object(align, 'trusted_link', lambda path: path == alias or trusted(path)):
            document = align.prepare('claude', str(alias / target.name), str(self.root / 'candidate-2'),
                                     ['/permissions/allow'])[0]
            Path(second['plan']).write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'overlapping_batch'):
                align.preflight_batch([first, second])

    def test_installed_compare_loads_adjacent_wiring_helper_from_other_cwd(self):
        from tests.test_rebuild_installed import Sandbox
        box = Sandbox(self.root / 'installed')
        package, _ = box.install('agent-tuneup')
        catalog = self.file('catalog.json', json.dumps(self.catalog))
        inventory = self.file('inventory.json', '{"version":1,"providers":[]}')
        result = subprocess.run([sys.executable, '-I', str(package / 'scripts/align.py'), 'compare',
                                 '--catalog', str(catalog), '--inventory', str(inventory)],
                                cwd=self.root, capture_output=True, text=True, env=box.env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['wiring']['providers']), 3)


if __name__ == '__main__':
    unittest.main()
