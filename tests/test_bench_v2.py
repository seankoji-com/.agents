"""bench-v2 (issue #28): frozen five-stage fixture, hidden checks, start plan and usage parser.

Everything runs offline against synthetic data. The hidden checker executes fixture
code only inside temporary copies.
"""
import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / 'bench' / 'v2'
FIXTURE = V2 / 'fixtures' / 'five_stage' / 'workspace'
REFERENCE = V2 / 'checks' / 'reference'
PARSER_FIXTURES = V2 / 'tools' / 'fixtures'
sys.path.insert(0, str(V2 / 'tools'))
sys.path.insert(0, str(V2 / 'checks'))

import five_stage  # noqa: E402
import importlib.util  # noqa: E402
_prepare_spec = importlib.util.spec_from_file_location('bench_v2_prepare_workspace', V2/'tools'/'prepare_workspace.py')
prepare_workspace = importlib.util.module_from_spec(_prepare_spec)
_prepare_spec.loader.exec_module(prepare_workspace)
import usage  # noqa: E402
import model_policy  # noqa: E402
import attempt_record  # noqa: E402
import captured_ledger  # noqa: E402

REQUIRED = {f'C{n}' for n in range(1, 14)}


def read_text_for_test(path):
    return path.read_text()


def frozen_files():
    for path in sorted(V2.rglob('*')):
        rel = path.relative_to(V2)
        if path.is_file() and rel.parts[0] != 'runs' and rel.as_posix() != 'frozen.json' \
                and '__pycache__' not in rel.parts:
            yield rel.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()
    support = ROOT / 'tests' / 'test_bench_v2.py'
    yield '../../tests/test_bench_v2.py', hashlib.sha256(support.read_bytes()).hexdigest()


def map_digest(files: dict) -> str:
    """SHA-256 of a frozen file map as compact sorted JSON, as recorded in frozen.json."""
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def protocol_section(heading: str) -> str:
    text = (V2 / 'protocol.md').read_text()
    start = text.index(heading)
    end = text.find('\n### ', start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def workspace(tmp: Path, overlay=True, edits=None) -> Path:
    target = tmp / 'ws'
    shutil.copytree(FIXTURE, target)
    if overlay:
        shutil.copytree(REFERENCE, target, dirs_exist_ok=True)
    for rel, (old, new) in (edits or {}).items():
        path = target / rel
        text = path.read_text()
        assert old in text, (rel, old)
        path.write_text(text.replace(old, new))
    return target


def trusted_check(target: Path, review_context=None) -> list:
    """Grade a repository-owned synthetic fixture copy; the explicit opt-in is test-only."""
    return five_stage.check(target, review_context, trusted_synthetic_fixture=True)


def failed(results) -> set:
    return {r['id'].split('-')[0] for r in results if r['required'] and not r['passed']}


def coordinator_context(scenario: str, outcome: Path) -> dict:
    root=V2/'fixtures/workflows'
    contracts=json.loads((root/'contracts.json').read_text())
    group='negative_scenarios' if scenario.startswith('negative-') else 'scenarios'
    spec=contracts[group][scenario]
    seed=json.loads((root/'coordinator-contexts'/(scenario+'.json')).read_text())
    run_id='offline-'+uuid.uuid4().hex
    nonce=uuid.uuid4().hex+uuid.uuid4().hex
    seed.update(run_id=run_id,prelaunch_nonce=nonce)
    seed['launch']={'scenario':scenario,'run_id':run_id,'prelaunch_nonce':nonce,
                    'input_sha256':spec['input_sha256']}
    seed['artifacts']={name:{'path':name,'sha256':hashlib.sha256((outcome/name).read_bytes()).hexdigest(),
                            'run_id':run_id} for name in spec['required_outputs']}
    return seed


def save_context(context: dict, path: Path, scenario: str, outcome: Path) -> Path:
    for name,entry in context['artifacts'].items():
        entry['sha256']=hashlib.sha256((outcome/name).read_bytes()).hexdigest()
        entry['run_id']=context['run_id']
    path.write_text(json.dumps(context,indent=2)+'\n')
    return path


def save_ledgers(context: dict, directory: Path, scenario: str, outcome: Path):
    contracts=json.loads((V2/'fixtures/workflows/contracts.json').read_text())
    group='negative_scenarios' if scenario.startswith('negative-') else 'scenarios'
    spec=contracts[group][scenario]
    context_path=save_context(context,directory/'context.json',scenario,outcome)
    prelaunch_path=directory/'prelaunch.json'
    captured_ledger.create_prelaunch(scenario,context['run_id'],context['prelaunch_nonce'],spec['input_sha256'],prelaunch_path)
    capture_path=directory/'capture.json'
    captured_ledger.create_capture(prelaunch_path,context_path,capture_path)
    return context_path,prelaunch_path,capture_path


class ModelPolicyTest(unittest.TestCase):
    def setUp(self):
        # Synthetic IDs exercise family validation without pinning a real model version.
        self.catalog = {'providers': [
            {'providerInstanceId': 'codex', 'canRunChildTask': True, 'models': [
                {'id': 'gpt-0-luna', 'options': [
                    {'id': 'reasoningEffort', 'options': [{'id': 'low'}, {'id': 'high'}]},
                    {'id': 'serviceTier', 'options': [{'id': 'default'}, {'id': 'priority'}]}]},
                {'id': 'gpt-0-sol', 'label': 'Luna', 'options': []}]},
            {'providerInstanceId': 'claudeAgent', 'canRunChildTask': True, 'models': [
                {'id': 'claude-haiku-0', 'options': [
                    {'id': 'effort', 'options': [{'id': 'low'}, {'id': 'high'}]},
                    {'id': 'fastMode', 'type': 'boolean'}]},
                {'id': 'claude-opus-0', 'label': 'Haiku', 'options': []}]}]}
        self.luna = {'providerInstanceId': 'codex', 'model': 'gpt-0-luna',
                     'options': {'reasoningEffort': 'low', 'serviceTier': 'default'}}
        self.haiku = {'providerInstanceId': 'claudeAgent', 'model': 'claude-haiku-0',
                      'options': {'effort': 'low', 'fastMode': False}}

    def test_explicit_catalog_targets_are_allowed(self):
        for target in (self.luna, self.haiku):
            self.assertEqual(model_policy.validate_target(self.catalog, target), target)

    def test_legacy_thinking_false_and_complete_frozen_targets_remain_strict(self):
        catalog = json.loads(json.dumps(self.catalog))
        claude = next(p for p in catalog['providers'] if p['providerInstanceId'] == 'claudeAgent')
        model = next(m for m in claude['models'] if m['id'] == self.haiku['model'])
        model['options'] = [{'id':'thinking','type':'boolean'}]
        cheap = dict(self.haiku, options={'thinking':False})
        self.assertEqual(model_policy.validate_target(catalog, cheap), cheap)
        with self.assertRaises(ValueError):
            model_policy.validate_target(catalog, dict(cheap,options={'thinking':True}))
        frozen = {'codex':self.luna, 'claudeAgent':cheap}
        self.assertEqual(model_policy.validate_frozen_map(catalog, frozen), frozen)
        for bad in ({'codex':self.luna}, {**frozen,'claudeAgent':dict(cheap,model='claude-opus-0')}):
            with self.assertRaises(ValueError):
                model_policy.validate_frozen_map(catalog,bad)

    def test_expensive_models_and_deceptive_names_are_rejected(self):
        for provider, model in [('codex', 'gpt-0-sol'), ('codex', 'gpt-0-astra'),
                                ('claudeAgent', 'claude-opus-0'), ('claudeAgent', 'claude-sonnet-0'),
                                ('codex', 'gpt-0-luna-sol'), ('claudeAgent', 'claude-haiku-0-opus')]:
            with self.subTest(model=model), self.assertRaises(ValueError):
                model_policy.validate_target(self.catalog, {'providerInstanceId': provider, 'model': model})

    def test_missing_targets_and_catalog_entries_never_fall_back(self):
        for target in ({}, dict(self.luna, model='gpt-999-luna'),
                       dict(self.luna, providerInstanceId='other')):
            with self.subTest(target=target), self.assertRaises(ValueError):
                model_policy.validate_target(self.catalog, target)
        self.catalog['providers'][0]['canRunChildTask'] = False
        with self.assertRaises(ValueError):
            model_policy.validate_target(self.catalog, self.luna, role='worker')

    def test_parent_and_canary_do_not_require_child_capability(self):
        self.catalog['providers'][0]['canRunChildTask'] = False
        self.assertEqual(model_policy.validate_target(self.catalog, self.luna, role='parent'), self.luna)
        self.assertEqual(model_policy.validate_target(self.catalog, self.luna, role='canary'), self.luna)
        for role in ('worker', 'child', 'native-child', 'reviewer'):
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'provider unavailable'):
                model_policy.validate_target(self.catalog, self.luna, role=role)

    def test_disabled_exact_provider_or_model_is_rejected_for_all_roles(self):
        self.catalog['providers'][0]['enabled'] = False
        with self.assertRaises(ValueError):
            model_policy.validate_target(self.catalog, self.luna, role='parent')
        self.catalog['providers'][0].pop('enabled')
        self.catalog['providers'][0]['models'][0]['enabled'] = False
        with self.assertRaises(ValueError):
            model_policy.validate_target(self.catalog, self.luna, role='parent')

    def test_premium_and_inherited_options_are_rejected(self):
        for target, options in [(self.luna, {}), (self.luna, {'reasoningEffort': 'low', 'serviceTier': 'priority'}),
                                (self.luna, {'reasoningEffort': 'high', 'serviceTier': 'default'}),
                                (self.haiku, {'effort': 'low', 'fastMode': True})]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                model_policy.validate_target(self.catalog, dict(target, options=options))

    def test_missing_option_controls_and_ambiguous_models_block(self):
        model = self.catalog['providers'][0]['models'][0]
        model['options'].pop()
        with self.assertRaises(ValueError):
            model_policy.validate_target(self.catalog, self.luna)
        self.catalog['providers'][1]['models'].append(self.catalog['providers'][1]['models'][0])
        with self.assertRaises(ValueError):
            model_policy.validate_target(self.catalog, self.haiku)

    def test_haiku_without_fast_mode_control_is_supported(self):
        self.catalog['providers'][1]['models'][0]['options'].pop()
        target = dict(self.haiku, options={'effort': 'low'})
        self.assertEqual(model_policy.validate_target(self.catalog, target), target)

    def test_plan_requires_policy_for_every_live_role(self):
        policy = json.loads((V2 / 'plan.json').read_text())['model_policy']
        self.assertEqual(policy['families'], model_policy.FAMILIES)
        self.assertEqual(set(policy['applies_to']),
                         {'parent', 'worker', 'reviewer', 'canary', 'retry', 'repair', 'resume', 'native-child'})
        self.assertEqual(policy['on_unavailable'], 'blocked')
        self.assertFalse(policy['allow_model_escalation'])
        negative = next(x for x in json.loads((V2 / 'plan.json').read_text())['starts']
                        if x['scenario'] == 'negative-missing-delegation')
        self.assertEqual(negative['catalog_mutation'], {
            'field': 'canRunChildTask', 'from': True, 'to': False,
            'parent_target_unchanged': True, 'exact_provider_model_options_unchanged': True})


class FrozenTest(unittest.TestCase):
    def test_frozen_files_match_their_recorded_digests(self):
        recorded = json.loads((V2 / 'frozen.json').read_text())['files']
        self.assertEqual(dict(frozen_files()), recorded,
                         'a frozen bench-v2 file changed: amend bench/v2/protocol.md before the next start')

    def test_amendment_receipt_binds_current_and_superseded_maps(self):
        """R9-BE-05: the receipt names the latest history entry and both pass 9 maps."""
        frozen = json.loads((V2 / 'frozen.json').read_text())
        history, receipt = frozen['history'], frozen['amendment_receipt']
        entry = history[receipt['history_index']]
        self.assertEqual(receipt['history_index'], len(history) - 1)
        self.assertEqual(receipt['current_map_sha256'], map_digest(frozen['files']))
        self.assertEqual(receipt['superseded_map_sha256'], map_digest(entry['files']))
        self.assertEqual((entry['superseded_map_sha256'], entry['replacement_map_sha256']),
                         (receipt['superseded_map_sha256'], receipt['current_map_sha256']))
        self.assertNotEqual(receipt['current_map_sha256'], receipt['superseded_map_sha256'])
        # Pass 25 superseded the pass 23 map (pass 24 was review-only and recorded none); pass 23
        # superseded the pass 22 map; pass 22 superseded the pass 21 map; pass 21 superseded the
        # pass 20 map; pass 20 superseded the pass 19 map; pass 19 superseded the pass 16 map (passes 17
        # and 18 recorded none). The pass 23, 22, 21, 20, 19, 16, 15, 14, 13, 12, 11 and 10 pairs are retained
        # unchanged.
        pass23 = receipt['pass23']
        pass22, pass21, pass20, pass19 = receipt['pass22'], receipt['pass21'], receipt['pass20'], receipt['pass19']
        pass16, pass15, pass14, pass13 = receipt['pass16'], receipt['pass15'], receipt['pass14'], receipt['pass13']
        pass12, pass11, pass10 = receipt['pass12'], receipt['pass11'], receipt['pass10']
        self.assertEqual((receipt['history_index'], pass23['history_index'], pass22['history_index'], pass21['history_index'],
                          pass20['history_index'], pass19['history_index'], pass16['history_index'],
                          pass15['history_index'], pass14['history_index'], pass13['history_index'],
                          pass12['history_index'], pass11['history_index'], pass10['history_index']),
                         (31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19))
        # History entries 0-30 are immutable: passes 19, 20, 21, 22, 23 and 25 each appended exactly one entry.
        self.assertEqual(len(history), 32)
        self.assertEqual(map_digest(history[:26]),
                         '880f73d45da58d1200916316382b2b44fcfa937697b114e8c4b6cfc41264cfe3')
        self.assertEqual(map_digest(history[:27]),
                         'c3e58a08b61f53416e582e9800c4fe4232b73baebd138f40780e5f21a5a0b77f')
        self.assertEqual(map_digest(history[:28]),
                         '1f3518586eab585e2c8d383cbc7da59f0ee81fe64e63f6e8d830c250cf0383a9')
        self.assertEqual(map_digest(history[:29]),
                         '0aec009649e2948a877224215358edb7136d421c3d0008cae0ebf1f49b5f4d2b')
        self.assertEqual(map_digest(history[:30]),
                         '4609adc3a8929b9f216c09cce1b663c8f57340a3b1950e47f9feeba978afec2e')
        self.assertEqual(map_digest(history[:31]),
                         '3532ee72def9ac3afdfad8bac1721211135be4c006b611a147a708124daf25c0')
        self.assertEqual(history[26]['map_role'], 'pass16 map superseded by pass19')
        self.assertEqual(history[27]['map_role'], 'pass19 map superseded by pass20')
        self.assertEqual(history[28]['map_role'], 'pass20 map superseded by pass21')
        self.assertEqual(history[29]['map_role'], 'pass21 map superseded by pass22')
        self.assertEqual(history[30]['map_role'], 'pass22 map superseded by pass23')
        self.assertEqual(history[31]['map_role'], 'pass23 map superseded by pass25')
        self.assertEqual(pass23['current_map_sha256'], receipt['superseded_map_sha256'])
        self.assertEqual(pass23['current_map_sha256'], '1279d4741bc967ae3855d01a2772ef60aba6df79d1b47a88951e4b037c831120')
        self.assertEqual(pass23['superseded_map_sha256'], map_digest(history[pass23['history_index']]['files']))
        self.assertEqual((history[30]['superseded_map_sha256'], history[30]['replacement_map_sha256']),
                         (pass23['superseded_map_sha256'], pass23['current_map_sha256']))
        self.assertEqual(pass22['current_map_sha256'], pass23['superseded_map_sha256'])
        self.assertEqual(pass22['current_map_sha256'], '3f5293b175df63280fbf3c04597099da9107ef7881b7c7a7b1b53217335b4a24')
        self.assertEqual(pass22['superseded_map_sha256'], map_digest(history[pass22['history_index']]['files']))
        self.assertEqual((history[29]['superseded_map_sha256'], history[29]['replacement_map_sha256']),
                         (pass22['superseded_map_sha256'], pass22['current_map_sha256']))
        self.assertEqual(pass21['current_map_sha256'], pass22['superseded_map_sha256'])
        self.assertEqual(pass21['current_map_sha256'], '20c0c60b49a02787bc9eec195a11cdca82e8bc4c43aa790d9a7f8ca826154f4c')
        self.assertEqual(pass21['superseded_map_sha256'], map_digest(history[pass21['history_index']]['files']))
        self.assertEqual((history[28]['superseded_map_sha256'], history[28]['replacement_map_sha256']),
                         (pass21['superseded_map_sha256'], pass21['current_map_sha256']))
        self.assertEqual(pass20['current_map_sha256'], pass21['superseded_map_sha256'])
        self.assertEqual(pass20['current_map_sha256'], '8c429d47572c14daed096e8337adbdb681c41670090da204582d6052d01677bd')
        self.assertEqual(pass20['superseded_map_sha256'], map_digest(history[pass20['history_index']]['files']))
        self.assertEqual((history[27]['superseded_map_sha256'], history[27]['replacement_map_sha256']),
                         (pass20['superseded_map_sha256'], pass20['current_map_sha256']))
        self.assertEqual(pass19['current_map_sha256'], pass20['superseded_map_sha256'])
        self.assertEqual(pass19['current_map_sha256'], '003958833f88b812f78f76396e4135249ec63d9c76c5191bd68c12237175c1d2')
        self.assertEqual(pass19['superseded_map_sha256'], map_digest(history[pass19['history_index']]['files']))
        self.assertEqual((history[26]['superseded_map_sha256'], history[26]['replacement_map_sha256']),
                         (pass19['superseded_map_sha256'], pass19['current_map_sha256']))
        self.assertEqual(pass16['current_map_sha256'], pass19['superseded_map_sha256'])
        self.assertEqual(pass16['superseded_map_sha256'], map_digest(history[pass16['history_index']]['files']))
        self.assertEqual((history[25]['superseded_map_sha256'], history[25]['replacement_map_sha256']),
                         (pass16['superseded_map_sha256'], pass16['current_map_sha256']))
        self.assertEqual(pass15['current_map_sha256'], pass16['superseded_map_sha256'])
        self.assertEqual(pass15['superseded_map_sha256'], map_digest(history[pass15['history_index']]['files']))
        self.assertEqual((history[24]['superseded_map_sha256'], history[24]['replacement_map_sha256']),
                         (pass15['superseded_map_sha256'], pass15['current_map_sha256']))
        self.assertEqual(pass14['current_map_sha256'], pass15['superseded_map_sha256'])
        self.assertEqual(pass14['superseded_map_sha256'], map_digest(history[pass14['history_index']]['files']))
        self.assertEqual((history[23]['superseded_map_sha256'], history[23]['replacement_map_sha256']),
                         (pass14['superseded_map_sha256'], pass14['current_map_sha256']))
        self.assertEqual(pass13['current_map_sha256'], pass14['superseded_map_sha256'])
        self.assertEqual(pass13['superseded_map_sha256'], map_digest(history[pass13['history_index']]['files']))
        self.assertEqual((history[22]['superseded_map_sha256'], history[22]['replacement_map_sha256']),
                         (pass13['superseded_map_sha256'], pass13['current_map_sha256']))
        self.assertEqual(pass12['current_map_sha256'], pass13['superseded_map_sha256'])
        self.assertEqual(pass12['superseded_map_sha256'], map_digest(history[pass12['history_index']]['files']))
        self.assertEqual((history[21]['superseded_map_sha256'], history[21]['replacement_map_sha256']),
                         (pass12['superseded_map_sha256'], pass12['current_map_sha256']))
        self.assertEqual(pass11['current_map_sha256'], pass12['superseded_map_sha256'])
        self.assertEqual(pass11['superseded_map_sha256'], map_digest(history[pass11['history_index']]['files']))
        self.assertEqual((history[20]['superseded_map_sha256'], history[20]['replacement_map_sha256']),
                         (pass11['superseded_map_sha256'], pass11['current_map_sha256']))
        self.assertEqual(pass10['current_map_sha256'], pass11['superseded_map_sha256'])
        self.assertEqual(pass10['superseded_map_sha256'], map_digest(history[pass10['history_index']]['files']))
        self.assertEqual((history[19]['superseded_map_sha256'], history[19]['replacement_map_sha256']),
                         (pass10['superseded_map_sha256'], pass10['current_map_sha256']))
        pass9 = receipt['pass9']
        self.assertEqual(pass9['current_map_sha256'], map_digest(history[pass9['history_index']]['files']))
        self.assertEqual(pass9['current_map_sha256'], pass10['superseded_map_sha256'])
        self.assertEqual(pass9['superseded_map_sha256'], history[pass9['history_index'] - 1]['replacement_map_sha256'])
        section = protocol_section('### Owner-authorized pass 10 amendment')
        for digest in (pass9['current_map_sha256'], pass9['superseded_map_sha256']):
            self.assertIn(digest, section)
        section = protocol_section('### Owner-authorized pass 11 amendment')
        for digest in (pass10['current_map_sha256'], pass10['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 12 amendment')
        for digest in (pass11['current_map_sha256'], pass11['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 13 amendment')
        for digest in (pass12['current_map_sha256'], pass12['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 14 amendment')
        for digest in (pass13['current_map_sha256'], pass13['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 15 amendment')
        for digest in (pass14['current_map_sha256'], pass14['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 16 amendment')
        for digest in (pass15['current_map_sha256'], pass15['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 19 amendment')
        for digest in (pass16['current_map_sha256'], pass16['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 20 amendment')
        for digest in (pass19['current_map_sha256'], pass19['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 21 amendment')
        for digest in (pass20['current_map_sha256'], pass20['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        section = protocol_section('### Owner-authorized pass 22 amendment')
        for digest in (pass21['current_map_sha256'], pass21['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        self.assertIn('No quality start has run', section)
        section = protocol_section('### Owner-authorized pass 23 amendment')
        for digest in (pass22['current_map_sha256'], pass22['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        self.assertIn('No quality start has run', section)
        section = protocol_section('### Owner-authorized pass 25 amendment')
        for digest in (pass23['current_map_sha256'], pass23['superseded_map_sha256']):
            self.assertIn(digest, section)
        self.assertNotIn('\n>', section)
        self.assertIn('No quality start has run', section)

    def test_pass10_amendment_records_superseded_in_place_text(self):
        """R9-BE-06: protocol text rewritten in place is quoted and bound to its digest."""
        original_digest = json.loads((V2 / 'frozen.json').read_text())['history'][0]['files']['protocol.md']
        section = protocol_section('### Owner-authorized pass 10 amendment')
        self.assertIn(original_digest, section)
        quotes, current = [], []
        for line in section.splitlines() + ['']:
            if line.startswith('>'):
                current.append(line[1:])
            elif current:
                quotes.append(' '.join(' '.join(current).split())); current = []
        self.assertEqual(len(quotes), 4)
        kept, inside = [], False
        for line in (V2 / 'protocol.md').read_text().splitlines():
            inside = True if line.startswith('### ') else False if line.startswith('## ') else inside
            if not inside:
                kept.append(line)
        body = ' '.join(' '.join(kept).split())  # main sections without dated amendments
        self.assertIn('**Missing delegation**: change only the selected provider capability field', body)
        for quote in quotes:
            self.assertNotIn(quote, body)
        committed = subprocess.run(['git', '-C', str(ROOT), 'show', 'cedebed:bench/v2/protocol.md'],
                                   capture_output=True)
        if committed.returncode != 0:
            self.skipTest('original protocol commit unavailable')
        self.assertEqual(hashlib.sha256(committed.stdout).hexdigest(), original_digest)
        original = ' '.join(committed.stdout.decode().split())
        for quote in quotes:
            self.assertIn(quote, original)

    def test_historical_protocol_is_untouched_by_v2(self):
        tracked = subprocess.run(['git', '-C', str(ROOT), 'diff', '--name-only', 'HEAD', '--', 'bench/protocol.md',
                                  'bench/rubric.md', 'bench/runs'], capture_output=True, text=True)
        if tracked.returncode != 0:
            self.skipTest('not a git checkout')
        self.assertEqual(tracked.stdout.strip(), '')


class FixtureTest(unittest.TestCase):
    def test_prepared_workspaces_are_identical_and_never_contain_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = prepare_workspace.prepare(Path(tmp) / 'a')
            second = prepare_workspace.prepare(Path(tmp) / 'b')
            self.assertEqual(first['head'], second['head'])
            names = {p.name for p in (Path(tmp) / 'a').rglob('*')}
            self.assertFalse(names & {'five_stage.py', 'reference', 'investigation.md', 'test_stages.py'})
            suite = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=Path(tmp) / 'a',
                                   capture_output=True, text=True)
            self.assertEqual(suite.returncode, 0, suite.stderr)

    def test_prepare_refuses_a_non_empty_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'keep.txt').write_text('owner data')
            with self.assertRaises(SystemExit):
                prepare_workspace.prepare(Path(tmp))
            self.assertEqual((Path(tmp) / 'keep.txt').read_text(), 'owner data')


SYNTHETIC_LUNA={'providerInstanceId':'codex','model':'gpt-0-luna','options':{'reasoningEffort':'low','serviceTier':'default'}}
SYNTHETIC_HAIKU={'providerInstanceId':'claudeAgent','model':'claude-haiku-0','options':{'effort':'low','fastMode':False}}


def synthetic_review_context(target, destination, reviewer=SYNTHETIC_LUNA, parent=SYNTHETIC_HAIKU):
    """Synthetic local transport for grader tests, never live acceptance proof.

    The parent implemented the change on one cheap lineage; the reviewer uses the other.
    parent=None omits the implementing target.
    """
    selected=reviewer
    catalog={'providers':[{'providerInstanceId':'codex','canRunChildTask':True,'models':[{'id':'gpt-0-luna','options':[{'id':'reasoningEffort','options':[{'id':'low'}]},{'id':'serviceTier','options':[{'id':'default'}]}]}]},
                          {'providerInstanceId':'claudeAgent','canRunChildTask':True,'models':[{'id':'claude-haiku-0','options':[{'id':'effort','options':[{'id':'low'}]},{'id':'fastMode','type':'boolean'}]}]}]}
    review=(target/'notes/review.md').read_text() if (target/'notes/review.md').exists() else ''
    context={'parent_thread_id':'synthetic-parent','task_id':'synthetic-review','target':selected,'catalog':catalog,'tool_records':[
        {'threadId':'synthetic-parent','toolName':'t3-code.delegate_task','input':{'role':'review','target':selected,'task':'ISSUE28_REVIEW_SOURCE_SHA256='+five_stage.reviewed_source_hash(target)},'output':{'taskId':'synthetic-review'}},
        {'threadId':'synthetic-parent','toolName':'t3-code.task_status','input':{'taskId':'synthetic-review'},'output':{'taskId':'synthetic-review','providerInstanceId':selected['providerInstanceId'],'model':selected['model'],'status':'completed','workState':'result_available','hasPendingChildRuns':False,'summary':review}}]}
    if parent is not None:
        context['parent_target']=parent
    destination.write_text(json.dumps(context)); return destination


class HiddenCheckTest(unittest.TestCase):
    def run_checks(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp), **kwargs)
            before = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
            review_context=synthetic_review_context(target,Path(tmp)/"coordinator-review.json")
            results = trusted_check(target, review_context)
            after = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(before, after, 'the checker must not write the evaluated tree')
            return results

    def test_reference_solution_passes_every_required_check(self):
        self.assertEqual(failed(self.run_checks()), set())

    def test_untouched_fixture_fails_every_stage_requirement(self):
        self.assertEqual(failed(self.run_checks(overlay=False)), REQUIRED - {'C9'})

    def test_export_header_and_frozen_suite_cannot_be_weakened(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp))
            io_file = target / 'ledger/io.py'
            source = io_file.read_text()
            self.assertIn("writer.writerow(FIELDS)", source)
            io_file.write_text(source.replace("writer.writerow(FIELDS)",
                                              "writer.writerow(['wrong', 'account', 'description', 'amount'])"))
            self.assertIn('C6', failed(trusted_check(target)))
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp))
            shutil.rmtree(target / 'tests'); (target / 'tests').mkdir()
            model = target / 'ledger/model.py'; source = model.read_text()
            model.write_text(source.replace("match = AMOUNT.fullmatch(text or '')", "return round(float(text) * 100)\n    match = AMOUNT.fullmatch(text or '')"))
            self.assertIn('C8', failed(trusted_check(target)))

    def test_float_rounding_fix_still_accepts_exponents(self):
        results = self.run_checks(edits={'ledger/model.py': (
            "    match = AMOUNT.fullmatch(text or '')",
            "    return round(float(text) * 100)\n    match = AMOUNT.fullmatch(text or '')")})
        self.assertEqual(failed(results), {'C3', 'C8', 'C13'})  # review evidence cannot approve a failing current suite

    def test_escaping_negative_amounts_is_rejected(self):
        results = self.run_checks(edits={'ledger/io.py': ('format_cents(entry.cents)])',
                                                          'neutralise(format_cents(entry.cents))])')})
        self.assertEqual(failed(results), {'C6', 'C8', 'C13'})

    def test_boilerplate_or_negated_approval_notes_fail(self):
        results = self.run_checks(edits={'notes/audit.md': ('Reproducer: export a CSV description `=HYPERLINK(\"https://invalid\",\"x\")`; a spreadsheet evaluates the cell.', 'Reproducer: issue'), 'notes/review.md': ('Verdict: approve', 'Verdict: adverse')})
        self.assertEqual(failed(results), {'C12', 'C13'})

    def test_c11_requires_seeded_fix_entries_not_keyword_mentions(self):
        weak='''## Unreleased\n\n- Amounts, months, formula, overwrite.\n'''
        old='# Changelog\n\n## Unreleased\n\n- Fixed: amounts are parsed exactly; totals are no longer a cent low. Invalid amounts are rejected.\n- Added: `report FILE --by month`.\n- Security: `export` neutralises spreadsheet formula cells and refuses to overwrite its input file.\n\n## 0.1.0\n\n- `total` and `export` commands.\n'
        results=self.run_checks(edits={'CHANGELOG.md':(old,weak)})
        self.assertIn('C11',failed(results))

    def test_c12_requires_severity_and_fix_inside_each_concrete_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=workspace(Path(tmp)); audit=target/'notes/audit.md'
            original=audit.read_text()
            audit.write_text(original.replace('Severity: high\n',''))
            self.assertIn('C12',failed(trusted_check(target)))
        with tempfile.TemporaryDirectory() as tmp:
            target=workspace(Path(tmp)); audit=target/'notes/audit.md'
            original=audit.read_text()
            audit.write_text(original.replace('Fix: `cli.main` checks `os.path.samefile` and refuses the output before opening it.\n',''))
            self.assertIn('C12',failed(trusted_check(target)))

    def test_grader_cli_refuses_to_execute_candidates_outside_the_isolated_container(self):
        """B-8-04: main() must not run untrusted workspace code on a host."""
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'dockerenv'
            self.assertFalse(five_stage.isolated_grader_environment({'T3_BENCH_ISOLATED_GRADER': '1'}, marker))
            marker.touch()
            self.assertFalse(five_stage.isolated_grader_environment({}, marker))
            self.assertFalse(five_stage.isolated_grader_environment({'T3_BENCH_ISOLATED_GRADER': 'true'}, marker))
            self.assertTrue(five_stage.isolated_grader_environment({'T3_BENCH_ISOLATED_GRADER': '1'}, marker))
            target = workspace(Path(tmp) / 'ws')
            with patch.object(five_stage, 'isolated_grader_environment', return_value=False), \
                    patch.object(five_stage, 'check', side_effect=AssertionError('candidate executed')), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(five_stage.main([str(target), '--json']), 2)

    def test_check_and_sandbox_refuse_host_execution_without_explicit_trust(self):
        """R9-BE-03: the guard sits on the code-execution path, not only main()."""
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp))
            refuse = patch.object(five_stage.subprocess, 'run', side_effect=AssertionError('candidate executed'))
            with patch.object(five_stage, 'isolated_grader_environment', return_value=False), refuse as runner:
                for trust in (False, None, 1, 'yes'):
                    with self.subTest(trust=trust), self.assertRaises(five_stage.HostExecutionRefused):
                        five_stage.check(target, trusted_synthetic_fixture=trust)
                with self.assertRaises(five_stage.HostExecutionRefused):
                    five_stage.check(target)
                with self.assertRaises(five_stage.HostExecutionRefused):
                    five_stage.Sandbox(target, Path(tmp) / 'host-sandbox')
                trusted = five_stage.Sandbox(target, Path(tmp) / 'trusted-sandbox', trusted_synthetic_fixture=True)
                trusted.trusted_synthetic_fixture = False
                with self.assertRaises(five_stage.HostExecutionRefused):
                    trusted.run('-c', 'pass')
                runner.assert_not_called()
            with patch.object(five_stage, 'isolated_grader_environment', return_value=True):
                inside = five_stage.Sandbox(target, Path(tmp) / 'container-sandbox')
                self.assertEqual(inside.run('-c', 'pass').returncode, 0)

    def test_c12_fix_must_name_the_mechanism_for_its_own_finding(self):
        """B-8-01: a shared keyword or swapped fixes cannot satisfy both findings."""
        formula_fix = 'Fix: `neutralise` prefixes dangerous text cells with an apostrophe.'
        overwrite_fix = 'Fix: `cli.main` checks `os.path.samefile` and refuses the output before opening it.'
        cases = {'generic prefix': ('Fix: prefix', 'Fix: prefix'),
                 'swapped': (overwrite_fix, formula_fix),
                 'identity without refusal': (formula_fix, 'Fix: compare with `os.path.samefile`.'),
                 'reference': (formula_fix, overwrite_fix)}
        for name, (first, second) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                target=workspace(Path(tmp)); audit=target/'notes/audit.md'
                text=audit.read_text().replace(formula_fix, '\0A').replace(overwrite_fix, '\0B')
                audit.write_text(text.replace('\0A', first).replace('\0B', second))
                if name == 'reference':
                    self.assertNotIn('C12', failed(trusted_check(target)))
                else:
                    self.assertIn('C12', failed(trusted_check(target)))

    def test_c12_requires_distinct_formula_and_same_file_finding_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=workspace(Path(tmp))
            audit=target/'notes/audit.md'
            original=audit.read_text()
            formula=original.split('\n\n')[0]
            audit.write_text(formula+'\n\n'+formula+'\n\nUnrelated note: overwrite\n')
            self.assertIn('C12',failed(trusted_check(target)))

    def test_c12_combined_or_filler_blocks_cannot_fill_the_count(self):
        """R9-BE-01: every block is concrete; one block cannot count for both seeded defects."""
        formula = ('Finding: Formula injection in exported text.\nSeverity: high\n'
                   'Evidence: `ledger/io.py:24` writes text cells unchanged.\n'
                   'Reproducer: export a description `=HYPERLINK("x")`.\n'
                   'Fix: prefix dangerous cells with an apostrophe.')
        overwrite = ('Finding: Export overwrites its own input.\nSeverity: medium\n'
                     'Evidence: `ledger/cli.py:31` opens the output unchecked.\n'
                     'Reproducer: run `python3 -m ledger export data.csv data.csv`.\n'
                     'Fix: compare paths with `os.path.samefile` and refuse the output.')
        combined = ('Finding: Export is unsafe.\nSeverity: high\n'
                    'Evidence: `ledger/io.py:24` and `ledger/cli.py:31`.\n'
                    'Reproducer: `=HYPERLINK("x")` then `export data.csv data.csv`.\n'
                    'Fix: apostrophe prefix, and refuse when input and output are the same file path.')
        filler = 'Finding: unrelated.\nSeverity: low\nReproducer: none\nFix: none'
        cases = {'combined plus filler': ([combined, filler], False),
                 'combined plus overwrite': ([combined, overwrite], False),
                 'combined plus formula': ([formula, combined], False),
                 'proper pair plus filler': ([formula, overwrite, filler], False),
                 'duplicated formula': ([formula, formula], False),
                 'proper pair': ([formula, overwrite], True),
                 'proper pair reversed': ([overwrite, formula], True)}
        for name, (blocks, passes) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                target = workspace(Path(tmp))
                (target / 'notes/audit.md').write_text('# Export audit\n\n' + '\n\n'.join(blocks) + '\n')
                result = next(r for r in trusted_check(target) if r['id'].startswith('C12'))
                self.assertIs(result['passed'], passes, result['detail'])
        with tempfile.TemporaryDirectory() as tmp:
            reference = next(r for r in trusted_check(workspace(Path(tmp))) if r['id'].startswith('C12'))
            self.assertTrue(reference['passed'], reference['detail'])

    def test_c12_fix_must_be_a_supported_affirmative_corrective_assertion(self):
        """R24-benchmark-range-shard-2-01: opposite, negated or extra clauses fail closed."""
        formula_fix = 'Fix: `neutralise` prefixes dangerous text cells with an apostrophe.'
        overwrite_fix = 'Fix: `cli.main` checks `os.path.samefile` and refuses the output before opening it.'
        formula_cases = {
            'reference': (formula_fix, True),
            'short form': ('Fix: prefix dangerous cells with an apostrophe.', True),
            'explicit opposite': ('Fix: Never add an apostrophe; leave dangerous cells untouched.', False),
            'negated': ('Fix: do not prefix dangerous cells with an apostrophe.', False),
            'contradictory': ('Fix: prefix dangerous cells with an apostrophe; never prefix dangerous cells.', False),
            'qualified away': ('Fix: `neutralise` prefixes dangerous text cells with an apostrophe, except in export.', False),
            'mechanism only': ('Fix: apostrophe.', False),
            'missing': ('Fix: none.', False)}
        overwrite_cases = {
            'reference': (overwrite_fix, True),
            'short form': ('Fix: compare paths with `os.path.samefile` and refuse the output.', True),
            'explicit opposite': ('Fix: Never reject samefile paths; always overwrite the input.', False),
            'negated refusal': ('Fix: `cli.main` checks `os.path.samefile` and does not refuse the output.', False),
            'contradictory': ('Fix: compare paths with `os.path.samefile` and refuse the output; otherwise overwrite the input.', False),
            'unsupported mechanism': ('Fix: resolve paths and exit with an error.', False),
            'missing': ('Fix: none.', False)}
        for kind, original, cases in (('formula', formula_fix, formula_cases), ('overwrite', overwrite_fix, overwrite_cases)):
            for name, (replacement, passes) in cases.items():
                with self.subTest(kind=kind, case=name), tempfile.TemporaryDirectory() as tmp:
                    target = workspace(Path(tmp)); audit = target / 'notes/audit.md'
                    audit.write_text(audit.read_text().replace(original, replacement))
                    result = next(r for r in trusted_check(target) if r['id'].startswith('C12'))
                    self.assertIs(result['passed'], passes, result['detail'])
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp)); audit = target / 'notes/audit.md'
            audit.write_text(audit.read_text().replace(formula_fix, formula_cases['explicit opposite'][0])
                             .replace(overwrite_fix, overwrite_cases['explicit opposite'][0]))
            self.assertIn('C12', failed(trusted_check(target)))

    def test_c1_and_c13_require_numeric_and_current_review_evidence(self):
        boilerplate={'notes/investigation.md':('Input: `0.29`','Input: decimal'),
                     'notes/review.md':('Changed: ledger/model.py:22','Changed: model.py:1')}
        self.assertTrue({'C1','C13'} <= failed(self.run_checks(edits=boilerplate)))

    def test_negated_approval_review_is_rejected(self):
        results = self.run_checks(edits={'notes/review.md': ('Finding: The seeded decimal truncation defect is repaired in the current implementation.', 'Finding: The reviewer did not approve this change.')})
        self.assertIn('C13', failed(results))

    def test_same_file_check_by_spelling_only_is_rejected(self):
        results = self.run_checks(edits={'ledger/cli.py': (
            'os.path.exists(args.out) and os.path.samefile(args.file, args.out)', 'args.file == args.out')})
        self.assertEqual(failed(results), {'C7'})

    def test_missing_notes_fail_only_their_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp))
            (target / 'notes' / 'review.md').unlink()
            (target / 'notes' / 'investigation.md').write_text('Cause: float truncation at ledger/model.py:3\n')
            self.assertEqual(failed(trusted_check(target)), {'C1', 'C13'})

    def test_report_must_reject_invalid_amounts_like_every_command(self):
        """R10-BE-03: a report-only lax parser cannot pass C3 or the frozen reference suite."""
        lax = ("    try:\n        entries = io.read_csv(args.file)",
               "    try:\n        if args.command == 'report':\n            from decimal import Decimal\n"
               "            io.parse_amount = lambda text: int(Decimal(text) * 100)\n"
               "        entries = io.read_csv(args.file)")
        results = self.run_checks(edits={'ledger/cli.py': lax})
        c3 = next(r for r in results if r['id'].startswith('C3'))
        self.assertIn("report '1e3'", c3['detail'])
        self.assertEqual(failed(results), {'C3', 'C8', 'C13'})

    def test_review_needs_a_known_different_lineage_from_the_implementer(self):
        """R10-BE-04: same target, same lineage, unknown or missing implementer lineage fail."""
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp)); review = (target / 'notes/review.md').read_text()
            def matches(reviewer, parent, **extra):
                path = synthetic_review_context(target, Path(tmp) / 'context.json', reviewer, parent)
                if extra:
                    context = json.loads(path.read_text()); context.update(extra); path.write_text(json.dumps(context))
                return five_stage.independent_review_matches(target, path, review)
            self.assertTrue(matches(SYNTHETIC_HAIKU, SYNTHETIC_LUNA))
            self.assertTrue(matches(SYNTHETIC_LUNA, SYNTHETIC_HAIKU))
            self.assertFalse(matches(SYNTHETIC_LUNA, SYNTHETIC_LUNA))
            self.assertFalse(matches(SYNTHETIC_HAIKU, SYNTHETIC_HAIKU))
            self.assertFalse(matches(SYNTHETIC_HAIKU, None))
            for unknown in ({'providerInstanceId': 'codex', 'model': 'gpt-0-sol'}, {'model': 'gpt-0-luna'},
                            dict(SYNTHETIC_LUNA, lineage='haiku'), 'gpt-0-luna'):
                with self.subTest(parent=unknown):
                    self.assertFalse(matches(SYNTHETIC_HAIKU, unknown))
            self.assertFalse(matches(SYNTHETIC_HAIKU, SYNTHETIC_LUNA, parent_target=None))

    def test_review_hash_binds_documentation_and_audit_but_not_the_review(self):
        """R10-BE-05: README/CHANGELOG/audit edits after review invalidate the review receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp)); review = (target / 'notes/review.md').read_text()
            context = synthetic_review_context(target, Path(tmp) / 'context.json')
            self.assertTrue(five_stage.independent_review_matches(target, context, review))
            before = five_stage.reviewed_source_hash(target)
            (target / 'notes/review.md').write_text(review + '\n')
            self.assertEqual(five_stage.reviewed_source_hash(target), before)
            (target / 'notes/review.md').write_text(review)
            for rel in ('README.md', 'CHANGELOG.md', 'notes/audit.md'):
                with self.subTest(rel=rel):
                    path = target / rel; original = path.read_text()
                    path.write_text(original + '\nRun `rm -rf ~` before `--by month`.\n')
                    self.assertFalse(five_stage.independent_review_matches(target, context, review))
                    path.unlink()
                    self.assertFalse(five_stage.independent_review_matches(target, context, review))
                    path.write_text(original)
                    self.assertTrue(five_stage.independent_review_matches(target, context, review))
            readme = target / 'README.md'
            readme.write_text(readme.read_text() + '\nSpreadsheet formula note changed after review.\n')
            self.assertEqual({'C10', 'C13'} & failed(trusted_check(target, context)), {'C13'})


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((V2 / 'plan.json').read_text())

    def test_twenty_four_starts_in_the_issue_composition(self):
        starts = self.plan['starts']
        self.assertEqual(len(starts), 24)
        self.assertEqual(len({s['id'] for s in starts}), 24)
        by = lambda prefix: [s for s in starts if s['scenario'].startswith(prefix)]
        self.assertEqual((len(by('engineering')), len(by('workflow')), len(by('negative'))), (12, 8, 4))
        for provider in self.plan['providers']:
            self.assertEqual(sum(s['provider'] == provider for s in starts), 12)

    def test_pairs_share_everything_but_the_arm_and_repetition_three_interrupts_both(self):
        pairs = {}
        for start in self.plan['starts']:
            if start['pair']:
                pairs.setdefault(start['pair'], []).append(start)
        self.assertEqual(len(pairs), 6)
        for members in pairs.values():
            self.assertEqual(sorted(m['arm'] for m in members), ['baseline', 'rebuilt'])
            for key in ('provider', 'fixture', 'repetition', 'interrupt_after', 'grading'):
                self.assertEqual(len({json.dumps(m[key]) for m in members}), 1, key)
            self.assertEqual(members[0]['interrupt_after'], 's3' if members[0]['repetition'] == 3 else None)

    def test_every_worker_is_dispatched_per_provider(self):
        workers = set(self.plan['workers'])
        self.assertEqual(len(workers), 12)
        for provider in self.plan['providers']:
            seen = {w for s in self.plan['starts'] if s['provider'] == provider for w in s['workers_expected']}
            self.assertEqual(seen, workers, provider)

    def test_no_model_ids_and_every_canary_is_blocked(self):
        text = (V2 / 'plan.json').read_text()
        self.assertNotRegex(text, r'(?i)\b(claude|gpt|gemini|opus|sonnet|haiku)-[0-9a-z.-]+')
        self.assertTrue(self.plan['canaries'])
        self.assertTrue(all(c['status'].startswith('blocked') for c in self.plan['canaries']))
        self.assertEqual(self.plan['infrastructure_retry_limit'], 1)

    def test_workflow_and_negative_grading_are_named_and_not_pending(self):
        for start in self.plan['starts']:
            self.assertNotIn('pending', json.dumps(start).lower())
            if start['scenario'].startswith('workflow-'):
                self.assertEqual(start['grading']['checker'],'checks/workflow_contract.py')
                self.assertTrue(start['grading']['check_ids'])
            if start['scenario'].startswith('negative-'):
                self.assertEqual(start['grading']['checker'],'checks/negative_start.py')
                self.assertTrue(start['grading']['check_ids'])

    def test_engineering_grading_names_checks_review_context_and_isolation(self):
        recorded = re.findall(r"record\('([CI]\d+-[a-z0-9-]+)'", (V2 / 'checks/five_stage.py').read_text())
        for start in self.plan['starts']:
            if start['scenario'] != 'engineering-five-stage':
                continue
            grading = start['grading']
            self.assertEqual(grading['checker'], 'checks/five_stage.py')
            self.assertEqual(sorted(grading['check_ids'] + grading['informational_check_ids']), sorted(recorded))
            self.assertEqual({c.split('-')[0] for c in grading['check_ids']}, REQUIRED)
            self.assertIn('--review-context', grading['review_context'])
            self.assertIn('T3_BENCH_ISOLATED_GRADER=1', grading['execution'])

    def test_offline_workflow_grader_accepts_fixture_and_rejects_mutation(self):
        sys.path.insert(0,str(V2/'checks'))
        import workflow_contract
        contracts=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['scenarios']
        for scenario,spec in contracts.items():
            with tempfile.TemporaryDirectory() as tmp:
                # R9-BE-04: grade and mutate a temporary copy, never the frozen fixture.
                fixture=Path(tmp)/'outcome';shutil.copytree(V2/'fixtures/workflows'/spec['fixture_dir'],fixture)
                context,prelaunch,capture=save_ledgers(coordinator_context(scenario,fixture),Path(tmp),scenario,fixture)
                self.assertTrue(workflow_contract.grade(scenario,fixture,context,prelaunch,capture)['required_passed'])
                self.assertFalse(workflow_contract.grade(scenario,fixture)['required_passed'])
                self.assertFalse(workflow_contract.grade(scenario,spec,context,prelaunch,capture)['required_passed'])
                forged=json.loads(context.read_text()); forged['artifacts'][spec['required_outputs'][0]]['sha256']='0'*64
                fake=Path(tmp)/'forged-context.json';fake.write_text(json.dumps(forged))
                self.assertFalse(workflow_contract.grade(scenario,fixture,fake,prelaunch,capture)['required_passed'])
                target=fixture/'observation.json' if scenario in ('workflow-ape','workflow-elephant-goldfish') else fixture/('sidecar-observation.json' if scenario=='workflow-babysitter' else 'host-observation.json')
                target.write_bytes(target.read_bytes()+b' ')
                self.assertFalse(workflow_contract.grade(scenario,fixture,context,prelaunch,capture)['required_passed'])

    def test_negative_start_graders_require_correlated_job_artifacts(self):
        sys.path.insert(0,str(V2/'checks'))
        import negative_start
        contracts=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['negative_scenarios']
        for scenario,spec in contracts.items():
            with tempfile.TemporaryDirectory() as tmp:
                # R9-BE-04: grade and mutate a temporary copy, never the frozen fixture.
                fixture=Path(tmp)/'outcome';shutil.copytree(V2/'fixtures/workflows'/spec['fixture_dir'],fixture)
                context,prelaunch,capture=save_ledgers(coordinator_context(scenario,fixture),Path(tmp),scenario,fixture)
                self.assertTrue(negative_start.grade(scenario,fixture,context,prelaunch,capture)['required_passed'])
                self.assertFalse(negative_start.grade(scenario,fixture)['required_passed'])
                self.assertFalse(negative_start.grade(scenario,{'required_passed':True},context,prelaunch,capture)['required_passed'])
                forged=json.loads(context.read_text());forged['observed_ids'].pop(spec['required_observed_ids'][0])
                fake=Path(tmp)/'forged-context.json';fake.write_text(json.dumps(forged))
                self.assertFalse(negative_start.grade(scenario,fixture,fake,prelaunch,capture)['required_passed'])
                dispatched=json.loads(context.read_text());dispatched['host_observations']['dispatch_calls']=[{'operation':'unexpected_dispatch'}]
                fake=Path(tmp)/'dispatched-context.json';fake.write_text(json.dumps(dispatched))
                self.assertFalse(negative_start.grade(scenario,fixture,fake,prelaunch,capture)['required_passed'])
                self.assertTrue(negative_start.grade(scenario,fixture,context,prelaunch,capture)['required_passed'])
                target=fixture/('direct-stage-receipts.json' if scenario=='negative-missing-delegation' else 'job.json')
                target.write_bytes(target.read_bytes()+b' ')
                self.assertFalse(negative_start.grade(scenario,fixture,context,prelaunch,capture)['required_passed'])

    def test_workflow_regressions_never_write_frozen_fixtures(self):
        """R9-BE-04: a killed mutation test cannot leave a frozen fixture altered."""
        frozen_root=(V2/'fixtures').resolve(); before=dict(frozen_files())
        def guard(real):
            def write(path,*args,**kwargs):
                if Path(path).resolve().is_relative_to(frozen_root):
                    raise AssertionError(f'frozen fixture written in place: {path}')
                return real(path,*args,**kwargs)
            return write
        with patch.object(Path,'write_bytes',guard(Path.write_bytes)), patch.object(Path,'write_text',guard(Path.write_text)):
            self.test_offline_workflow_grader_accepts_fixture_and_rejects_mutation()
            self.test_negative_start_graders_require_correlated_job_artifacts()
        self.assertEqual(dict(frozen_files()),before)

    def test_workflow_grader_requires_independent_context_and_accepts_fresh_ids(self):
        import workflow_contract
        scenario='workflow-ape'; spec=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['scenarios'][scenario]
        fixture=V2/'fixtures/workflows'/spec['fixture_dir']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'worker-output';shutil.copytree(fixture,root)
            context=coordinator_context(scenario,root)
            follow=json.loads((root/'followup.json').read_text());follow.update(task_id='task-fresh-9',conversation_id='conversation-fresh-9')
            (root/'followup.json').write_text(json.dumps(follow,indent=2)+'\n')
            observation=json.loads((root/'observation.json').read_text());observation.update(followup_id='task-fresh-9',conversation_id='conversation-fresh-9')
            (root/'observation.json').write_text(json.dumps(observation,indent=2)+'\n')
            context['run_id']='fresh-run-9';context['prelaunch_nonce']='fresh-prelaunch-nonce-20261012'
            context['launch'].update(run_id='fresh-run-9',prelaunch_nonce=context['prelaunch_nonce'])
            context['observed_ids'].update(followup_task_id='task-fresh-9',conversation_id='conversation-fresh-9')
            context['host_observations']['dispatch_calls'][0].update(task_id='task-fresh-9',conversation_id='conversation-fresh-9')
            context_path,prelaunch,capture=save_ledgers(context,Path(tmp),scenario,root)
            self.assertFalse(workflow_contract.grade(scenario,root)['required_passed'])
            self.assertTrue(workflow_contract.grade(scenario,root,context_path,prelaunch,capture)['required_passed'])
            context['observed_ids'].pop('followup_task_id')
            context_path.write_text(json.dumps(context))
            self.assertFalse(workflow_contract.grade(scenario,root,context_path,prelaunch,capture)['required_passed'])

    def test_ape_followup_must_be_a_new_host_observed_task(self):
        """R10-BE-01: reusing the original task ID as the follow-up fails even when all records agree."""
        import workflow_contract
        scenario='workflow-ape'; spec=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['scenarios'][scenario]
        def grade(task_id, host_prior='task-original', extra_dispatch=None):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'worker-output';shutil.copytree(V2/'fixtures/workflows'/spec['fixture_dir'],root)
                context=coordinator_context(scenario,root)
                follow=json.loads((root/'followup.json').read_text());follow.update(task_id=task_id)
                (root/'followup.json').write_text(json.dumps(follow)+'\n')
                observation=json.loads((root/'observation.json').read_text());observation.update(followup_id=task_id)
                (root/'observation.json').write_text(json.dumps(observation)+'\n')
                context['observed_ids'].update(followup_task_id=task_id)
                event=context['host_observations']['dispatch_calls'][0];event.update(task_id=task_id)
                if host_prior is None:
                    event.pop('prior_task_id')
                else:
                    event['prior_task_id']=host_prior
                context['host_observations']['dispatch_calls'].extend(extra_dispatch or [])
                paths=save_ledgers(context,Path(tmp),scenario,root)
                result=workflow_contract.grade(scenario,root,*paths)
                return next(c['passed'] for c in result['checks'] if c['id']=='APE-FOLLOWUP-CORRELATED'), result['required_passed']
        self.assertEqual(grade('task-followup-2'),(True,True))
        self.assertEqual(grade('task-original'),(False,False))
        self.assertEqual(grade('task-followup-2',host_prior=None),(False,False))
        self.assertEqual(grade('task-followup-2',host_prior='task-followup-2'),(False,False))
        self.assertEqual(grade('task-followup-2',extra_dispatch=[{'operation':'research','task_id':'task-followup-2'}]),(False,False))

    def test_cold_brief_facts_and_worker_owned_ledgers_are_refused(self):
        import workflow_contract
        scenario = 'workflow-elephant-goldfish'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); root = directory / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
            context = coordinator_context(scenario, root)
            paths = save_ledgers(context, directory, scenario, root)
            self.assertTrue(workflow_contract.grade(scenario, root, *paths)['required_passed'])
            brief = root / 'cold-brief.md'; original = brief.read_text()
            for leaked in ('0.25', '0.20', '2026-10-12', '2026-10-11'):
                brief.write_text(original + leaked)
                paths = save_ledgers(context, directory, scenario, root)
                self.assertFalse(workflow_contract.grade(scenario, root, *paths)['required_passed'])
            brief.write_text(original)
            paths = save_ledgers(context, directory, scenario, root)
            local_capture = root / 'capture.json'; shutil.copyfile(paths[2], local_capture)
            self.assertFalse(workflow_contract.grade(scenario, root, paths[0], paths[1], local_capture)['required_passed'])
            bad = json.loads(paths[0].read_text()); bad['observed_ids'] = ['malformed']
            paths[0].write_text(json.dumps(bad))
            self.assertFalse(workflow_contract.grade(scenario, root, *paths)['required_passed'])

    def test_cold_brief_must_be_the_frozen_procedural_template(self):
        """R11-BE-02: a paraphrased predecessor finding fails even without literal answers."""
        import workflow_contract
        scenario = 'workflow-elephant-goldfish'
        paraphrase = ('The prior factual reviewer found two errors: use one quarter for the rate and the twelfth '
                      'of October twenty twenty six for the date. Check those corrections.\n')
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); root = directory / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
            brief = root / 'cold-brief.md'; original = brief.read_text()
            def grade(text, **edits):
                brief.write_text(text)
                for name, value in edits.items():
                    (root / name).write_text(value)
                result = workflow_contract.grade(scenario, root, *save_ledgers(coordinator_context(scenario, root), directory, scenario, root))
                return next(c['passed'] for c in result['checks'] if c['id'] == 'EG-COLD-BRIEF-OMISSIONS'), result['required_passed']
            self.assertEqual(grade(original), (True, True))
            self.assertEqual(grade(original + paraphrase), (False, False))
            self.assertEqual(grade(original.replace('Report each', 'The prior reviewer flagged the rate. Report each')), (False, False))
            self.assertEqual(grade(original.replace('incorrect.md', 'source.md', 1)), (False, False))
            self.assertEqual(grade(original.replace(hashlib.sha256((root / 'source.md').read_bytes()).hexdigest(), '0' * 64)), (False, False))
            template = (root / 'cold-brief-template.md').read_text()
            # Editing the frozen template to admit the paraphrase breaks its input binding.
            self.assertFalse(grade(original + paraphrase, **{'cold-brief-template.md': template + paraphrase})[1])

    def test_cold_reader_dispatch_must_carry_exactly_the_rendered_brief(self):
        """R12-BE-02: the host-recorded cold_read input, not the saved brief file, is graded."""
        import workflow_contract
        scenario = 'workflow-elephant-goldfish'
        paraphrase = ('The prior factual reviewer found two errors: use one quarter for the rate and the twelfth '
                      'of October twenty twenty six for the date. Check those corrections.\n')
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); root = directory / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
            brief = (root / 'cold-brief.md').read_text()
            def grade(edit=None, reader_id=None):
                context = coordinator_context(scenario, root)
                calls = context['host_observations']['dispatch_calls']
                if edit:
                    edit(calls)
                if reader_id is not None:
                    observation = json.loads((root / 'observation.json').read_text())
                    observation['cold_reader_task_id'] = reader_id
                    (root / 'observation.json').write_text(json.dumps(observation))
                    context = dict(context, observed_ids=dict(context['observed_ids'], cold_reader_task_id=reader_id))
                    context['artifacts']['observation.json']['sha256'] = hashlib.sha256((root / 'observation.json').read_bytes()).hexdigest()
                result = workflow_contract.grade(scenario, root, *save_ledgers(context, directory, scenario, root))
                return next(c['passed'] for c in result['checks'] if c['id'] == 'EG-COLD-BRIEF-OMISSIONS'), result['required_passed']
            reader = lambda calls: next(c for c in calls if c['operation'] == 'cold_read')
            self.assertEqual(grade(), (True, True))
            self.assertEqual(reader(json.loads((V2 / 'fixtures/workflows/coordinator-contexts' / f'{scenario}.json')
                                               .read_text())['host_observations']['dispatch_calls'])['input'], {'task': brief})
            # Host-recorded contamination fails although every saved artifact is unchanged.
            self.assertEqual(grade(lambda calls: reader(calls)['input'].update(task=brief + paraphrase)), (False, False))
            self.assertEqual(grade(lambda calls: reader(calls)['input'].update(prior_findings=paraphrase)), (False, False))
            self.assertEqual(grade(lambda calls: reader(calls).pop('input')), (False, False))
            # Zero, repeated, or reused-task reader dispatches fail.
            self.assertEqual(grade(lambda calls: calls.clear()), (False, False))
            self.assertEqual(grade(lambda calls: calls.remove(reader(calls))), (False, False))
            self.assertEqual(grade(lambda calls: calls.append(dict(reader(calls), task_id='task-cold-reader-2'))), (False, False))
            self.assertEqual(grade(lambda calls: calls[0].update(task_id=reader(calls)['task_id'])), (False, False))
            self.assertEqual(grade(lambda calls: reader(calls).pop('task_id')), (False, False))
            # The worker-reported reader must be the host-observed one.
            self.assertFalse(grade(reader_id='task-other-reader')[1])

    def test_corrections_need_one_unambiguous_cited_row_per_seeded_fact(self):
        """R20-benchmark-shard-3-01: a contradictory extra correction fails in either row order."""
        import workflow_contract
        scenario = 'workflow-elephant-goldfish'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); root = directory / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
            document = json.loads((root / 'corrections.json').read_text())
            rate, date = document['corrections']
            def grade(rows):
                # Truthful fresh context/prelaunch/capture records bind the modified output bytes.
                (root / 'corrections.json').write_text(json.dumps(dict(document, corrections=rows)))
                result = workflow_contract.grade(scenario, root, *save_ledgers(coordinator_context(scenario, root), directory, scenario, root))
                failed = sorted(c['id'] for c in result['checks'] if c['required'] and not c['passed'])
                return result['required_passed'], failed
            self.assertEqual(grade([rate, date]), (True, []))
            self.assertEqual(grade([date, rate]), (True, []))
            wrong_rate, wrong_date = dict(rate, value='0.20'), dict(date, value='2026-10-11')
            rejected = (['EG-CORRECTIONS-CITED'], 'corrections')
            for rows in ([rate, date, wrong_rate], [wrong_rate, rate, date], [rate, wrong_rate, date],
                         [rate, date, wrong_date], [wrong_date, rate, date], [wrong_rate, date],
                         [rate, date, dict(rate)], [rate, rate, date], [rate], [date], [],
                         [rate, date, dict(rate, fact='fact-other', value='1')],
                         [dict(rate, source_sha256='0' * 64), date], [dict(rate, source='incorrect.md'), date],
                         [dict(rate, value=0.25), date], [{k: v for k, v in rate.items() if k != 'source_sha256'}, date],
                         [rate, date, 'fact-rate: 0.20'], [rate, date, None]):
                with self.subTest(rows=rows):
                    self.assertEqual(grade(rows), (False, rejected[0]))
            for corrections in ({'fact-rate': rate, 'fact-date': date}, 'fact-rate: 0.25', None):
                with self.subTest(corrections=corrections):
                    passed, failed = grade(corrections)
                    self.assertFalse(passed)
                    self.assertIn('EG-CORRECTIONS-CITED', failed)

    def test_every_workflow_requires_host_dispatch_of_both_specialised_workers(self):
        """Saved output cannot show a worker ran: each required worker needs its own host dispatch."""
        import workflow_contract
        contracts = json.loads((V2 / 'fixtures/workflows/contracts.json').read_text())['scenarios']
        plan = json.loads((V2 / 'plan.json').read_text())
        for start in plan['starts']:
            if start['scenario'] in contracts:
                self.assertEqual(contracts[start['scenario']]['required_worker_dispatches'], start['workers_expected'])
        for scenario, spec in contracts.items():
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); root = directory / 'outcome'
                shutil.copytree(V2 / 'fixtures/workflows' / spec['fixture_dir'], root)
                def grade(edit=None):
                    context = coordinator_context(scenario, root)
                    if edit:
                        edit(context['host_observations'])
                    result = workflow_contract.grade(scenario, root, *save_ledgers(context, directory, scenario, root))
                    return result['required_passed']
                first, second = spec['required_worker_dispatches']
                def drop(worker):
                    return lambda host: host.update(dispatch_calls=[c for c in host['dispatch_calls'] if c.get('worker') != worker])
                def share(host):
                    owned = [c for c in host['dispatch_calls'] if c.get('worker') in (first, second)]
                    owned[1]['task_id'] = owned[0]['task_id']
                self.assertTrue(grade(), scenario)
                self.assertFalse(grade(drop(first)), scenario)
                self.assertFalse(grade(drop(second)), scenario)
                self.assertFalse(grade(share), scenario)
                self.assertFalse(grade(lambda host: host['trace_coverage'].remove('dispatch_calls')), scenario)
                self.assertFalse(grade(lambda host: host.pop('dispatch_calls')), scenario)

    def test_babysitter_no_action_checks_require_host_trace_coverage(self):
        """R11-BE-03: empty post/merge logs prove nothing unless the host traced those routes."""
        import workflow_contract
        scenario = 'workflow-babysitter'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); root = directory / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
            def grade(coverage):
                context = coordinator_context(scenario, root)
                if coverage is None:
                    context['host_observations'].pop('trace_coverage')
                else:
                    context['host_observations']['trace_coverage'] = coverage
                result = workflow_contract.grade(scenario, root, *save_ledgers(context, directory, scenario, root))
                checks = {c['id']: c['passed'] for c in result['checks']}
                return checks['BABY-NO-UNAUTHORIZED-POST'], checks['BABY-NO-UNAUTHORIZED-MERGE'], result['required_passed']
            self.assertEqual(grade(['sidecar_post_calls', 'sidecar_merge_calls', 'head_readback', 'check_readback',
                                    'comment_readback', 'dispatch_calls']), (True, True, True))
            self.assertEqual(grade(None), (False, False, False))
            self.assertEqual(grade(['head_readback', 'check_readback', 'comment_readback']), (False, False, False))
            self.assertEqual(grade(['sidecar_post_calls']), (True, False, False))
            self.assertEqual(grade(['sidecar_merge_calls']), (False, True, False))
            self.assertEqual(grade('sidecar_post_calls sidecar_merge_calls'), (False, False, False))

    def test_ape_read_only_sources_require_source_access_trace_coverage(self):
        """R13-BE-04: no write event proves read-only access only where the host traced source access."""
        import workflow_contract
        scenario = 'workflow-ape'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); root = directory / 'outcome'
            shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
            def grade(edit):
                context = coordinator_context(scenario, root)
                edit(context['host_observations'])
                result = workflow_contract.grade(scenario, root, *save_ledgers(context, directory, scenario, root))
                return {c['id']: c['passed'] for c in result['checks']}, result['required_passed']
            checks, passed = grade(lambda host: None)
            self.assertTrue(passed); self.assertTrue(checks['APE-RO-SOURCES'])
            # The observed reads and hashes are retained; only the coverage claim is removed.
            for edit in (lambda host: host['trace_coverage'].remove('source_access_events'),
                         lambda host: host.update(trace_coverage=dict.fromkeys(host['trace_coverage'], True)),
                         lambda host: host.update(source_access_events={'events': host['source_access_events']})):
                checks, passed = grade(edit)
                self.assertFalse(checks['APE-RO-SOURCES']); self.assertFalse(passed)
            # A unique follow-up dispatch is a claim about every dispatch: it needs dispatch coverage too.
            checks, passed = grade(lambda host: host['trace_coverage'].remove('dispatch_calls'))
            self.assertFalse(checks['APE-FOLLOWUP-CORRELATED'])
            self.assertFalse(checks['coordinator-context-id-match:followup_task_id']); self.assertFalse(passed)

    def test_every_absence_check_requires_list_coverage_of_its_own_route(self):
        """Sweep after R13-BE-04: a coverage map, or a covered route with no recorded log, proves nothing."""
        import workflow_contract, negative_start
        for scenario in ('workflow-ape', 'workflow-elephant-goldfish'):
            check = 'APE-NO-IMPLEMENTATION' if scenario == 'workflow-ape' else 'EG-NO-IMPLEMENTATION'
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); root = directory / 'outcome'
                shutil.copytree(V2 / 'fixtures/workflows' / scenario, root)
                for edit in (lambda host: host.update(trace_coverage={'dispatch_calls': False, 'stage_transitions': False}),
                             lambda host: host.pop('stage_transitions'),
                             lambda host: host.update(stage_transitions={'operation': 'implementation'})):
                    context = coordinator_context(scenario, root); edit(context['host_observations'])
                    result = workflow_contract.grade(scenario, root, *save_ledgers(context, directory, scenario, root))
                    self.assertFalse(next(c['passed'] for c in result['checks'] if c['id'] == check), scenario)
                    self.assertFalse(result['required_passed'], scenario)
        contracts = json.loads((V2 / 'fixtures/workflows/contracts.json').read_text())['negative_scenarios']
        for scenario, spec in contracts.items():
            check = 'N4-ZERO-WORKER-DISPATCH' if scenario == 'negative-missing-delegation' else 'N8-ZERO-REVIEWER-DISPATCH'
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); root = directory / 'outcome'
                shutil.copytree(V2 / 'fixtures/workflows' / spec['fixture_dir'], root)
                for coverage in ({'dispatch_calls': False, 'task_handles': False}, ['dispatch_calls'], ['task_handles']):
                    context = coordinator_context(scenario, root); context['host_observations']['trace_coverage'] = coverage
                    result = negative_start.grade(scenario, root, *save_ledgers(context, directory, scenario, root))
                    self.assertFalse(next(c['passed'] for c in result['checks'] if c['id'] == check), (scenario, coverage))
                    self.assertFalse(result['required_passed'], scenario)

    def test_captured_ledger_cli_records_and_detects_tampering(self):
        scenario='workflow-ape';spec=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['scenarios'][scenario]
        fixture=V2/'fixtures/workflows'/spec['fixture_dir']
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); context,prelaunch,capture=save_ledgers(coordinator_context(scenario,fixture),directory,scenario,fixture)
            ok=captured_ledger.verify(prelaunch,context,capture,scenario,spec['input_sha256'],spec['required_outputs'],spec['required_observed_ids'])
            self.assertTrue(all(ok.values()),ok)
            record=json.loads(capture.read_text());record['run_id']='other-run';capture.write_text(json.dumps(record))
            bad=captured_ledger.verify(prelaunch,context,capture,scenario,spec['input_sha256'],spec['required_outputs'],spec['required_observed_ids'])
            self.assertFalse(bad['capture-ledger-integrity'])

    def test_fixed_copied_context_fails_ledger_identity_and_fresh_run_passes(self):
        import workflow_contract
        scenario='workflow-ape';spec=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['scenarios'][scenario]
        fixture=V2/'fixtures/workflows'/spec['fixture_dir']
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            stale=json.loads((V2/'fixtures/workflows/coordinator-contexts'/f'{scenario}.json').read_text())
            stale_path=directory/'stale.json';stale_path.write_text(json.dumps(stale))
            prelaunch=directory/'prelaunch.json'
            captured_ledger.create_prelaunch(scenario,'different-run','different-nonce-value',spec['input_sha256'],prelaunch)
            capture=directory/'capture.json'
            capture.write_text('{}')
            self.assertFalse(workflow_contract.grade(scenario,fixture,stale_path,prelaunch,capture)['required_passed'])
            context=coordinator_context(scenario,fixture)
            context_path,prelaunch,capture=save_ledgers(context,directory,scenario,fixture)
            self.assertTrue(workflow_contract.grade(scenario,fixture,context_path,prelaunch,capture)['required_passed'])
            context['run_id']='replaced-run'
            context_path.write_text(json.dumps(context))
            self.assertFalse(workflow_contract.grade(scenario,fixture,context_path,prelaunch,capture)['required_passed'])

    def test_workflow_host_observations_reject_forbidden_actions(self):
        import workflow_contract
        scenario='workflow-ape';spec=json.loads((V2/'fixtures/workflows/contracts.json').read_text())['scenarios'][scenario]
        fixture=V2/'fixtures/workflows'/spec['fixture_dir']
        with tempfile.TemporaryDirectory() as tmp:
            context=coordinator_context(scenario,fixture)
            context['host_observations']['dispatch_calls'].append({'operation':'implementation','task_id':'unexpected'})
            path,prelaunch,capture=save_ledgers(context,Path(tmp),scenario,fixture)
            self.assertFalse(workflow_contract.grade(scenario,fixture,path,prelaunch,capture)['required_passed'])

    def test_attempt_record_requires_exact_readback_pins_metrics_and_null_reasons(self):
        record={'schema_version':1,'start_id':'s','attempt':1,'arm':'rebuilt',
                'provider_instance_id':'codex','model_as_read_back':{'provider_instance_id':'codex','model_id':'gpt-0-luna'},
                'model_options':{'provider_instance_id':'codex','model_id':'gpt-0-luna','reasoningEffort':'low','serviceTier':'default'},'runtime_mode':'local','os':'synthetic',
                't3_build':'build-hash','package_digests':{'imps':'a'*64},'bundle_digests':{'bench':'b'*64},
                'job_id':'j','thread_id':'t','task_ids':[],'check_results':[],'parser_summary':{'schema_version':1,'protocol':'bench-v2','sources':[],'parent':{},'workers':[],'sidechain':{},'unattributed_sources':[],'aggregate':{},'gaps':[]},
                'interventions':[],'failures':[],'private_raw_sha256':[],'unknown_reasons':{},
                'metrics_unknown_reasons':{},'metrics':{'wall_seconds':1,'repair_count':0,'task_count':0,
                'compaction_count':0,'fallback_count':0,'repeated_setup':0,'parent_peak_context':None,
                'worker_usage':{},'attribution_gaps':[],'retained_plan_correct':True}}
        self.assertIn('metrics.parent_peak_context null requires',attempt_record.validate(record)[0])
        record['metrics_unknown_reasons']['parent_peak_context']='parser unavailable'
        self.assertEqual(attempt_record.validate(record),[])

    def test_attempt_schema_rejects_adversarial_types_unknown_fields_hashes_and_nonfinite_cli(self):
        valid={'schema_version':1,'start_id':'s','attempt':1,'arm':'rebuilt','provider_instance_id':'codex',
               'model_as_read_back':{'provider_instance_id':'codex','model_id':'gpt-0-luna'},
               'model_options':{'provider_instance_id':'codex','model_id':'gpt-0-luna','reasoningEffort':'low','serviceTier':'default'},'runtime_mode':'local',
               'os':'synthetic','t3_build':'build','package_digests':{'imps':'a'*64},'bundle_digests':{'bench':'b'*64},
               'job_id':'j','thread_id':'t','task_ids':['task-1'],'check_results':[{'id':'C1','required':True,'passed':True}],
               'parser_summary':{'schema_version':1,'protocol':'bench-v2','sources':[],'parent':{},'workers':[],'sidechain':{},'unattributed_sources':[],'aggregate':{},'gaps':[]},'interventions':[],'failures':[],'private_raw_sha256':[],
               'metrics':{'wall_seconds':1.5,'repair_count':0,'task_count':1,'compaction_count':0,'fallback_count':0,
                          'repeated_setup':0,'parent_peak_context':10,'worker_usage':{'task-1':{'inferences':1,'input':10,'cache_read':0,'cache_write':0,'output':2,'context':10,'unknown':{}}},'attribution_gaps':[],
                          'retained_plan_correct':True},'unknown_reasons':{},'metrics_unknown_reasons':{}}
        self.assertEqual(attempt_record.validate(valid),[])
        mutations=[('start_id',7),('arm','invalid-arm'),('task_ids',False),('check_results',3),
                   ('interventions','bad'),('failures',{}),('metrics',dict(valid['metrics'],wall_seconds=float('nan'))),
                   ('metrics',dict(valid['metrics'],repair_count=-1)),('package_digests',{'imps':'bad'}),
                   ('bundle_digests',{}),('extra','unknown'),
                   ('model_options',{'nested':{'unexpected':True}}),
                   ('model_as_read_back',{'provider_instance_id':'other','model_id':'synthetic-model'})]
        for key,value in mutations:
            candidate=dict(valid);candidate[key]=value
            self.assertTrue(attempt_record.validate(candidate),key)
        self.assertTrue(attempt_record.validate(dict(valid,model_options=dict(valid['model_options'],reasoningEffort='high'))))
        self.assertTrue(attempt_record.validate(dict(valid,model_options=dict(valid['model_options'],serviceTier='priority'))))
        unknown_pair=dict(valid);unknown_pair['unknown_reasons']={'provider_instance_id':'missing'}
        self.assertTrue(attempt_record.validate(unknown_pair))
        # R9-BE-02: requested options obey the low/standard policy even without a readback.
        unknown_model=dict(valid,provider_instance_id=None,model_as_read_back=None,
                           unknown_reasons={'provider_instance_id':'not read back','model_as_read_back':'not read back'})
        for options in ({'reasoningEffort':'low','serviceTier':'default'},{'effort':'low','fastMode':False},{'thinking':False},
                        {'provider_instance_id':'codex','model_id':'gpt-0-luna','reasoningEffort':'low','serviceTier':'default'}):
            with self.subTest(options=options):
                self.assertEqual(attempt_record.validate(dict(unknown_model,model_options=options)),[])
        for options in ({'serviceTier':'priority','reasoningEffort':'high','thinking':0},{'thinking':0},{},
                        {'reasoningEffort':'low','serviceTier':'priority'},{'effort':'low','fastMode':True},
                        {'reasoningEffort':'low','serviceTier':'default','effort':'low'},
                        {'model_id':'claude-opus-0','effort':'low'},{'model_id':'gpt-0-luna','effort':'low'},
                        {'provider_instance_id':'other','reasoningEffort':'low','serviceTier':'default'}):
            with self.subTest(options=options):
                self.assertTrue(attempt_record.validate(dict(unknown_model,model_options=options)))
        nested_unknown=dict(valid);nested_unknown['metrics']=dict(valid['metrics'],retained_plan_correct=None)
        nested_unknown['metrics_unknown_reasons']={'retained_plan_correct':'not observed'}
        self.assertEqual(attempt_record.validate(nested_unknown),[])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'record.json'
            shutil.copy2(V2/'tools'/'attempt_record.py',root/'attempt_record.py')
            shutil.copy2(V2/'tools'/'attempt.schema.json',root/'attempt.schema.json')
            path.write_text(json.dumps(valid))
            relocated=subprocess.run([sys.executable,str(root/'attempt_record.py'),str(path)],capture_output=True,text=True)
            self.assertEqual(relocated.returncode,0,relocated.stdout+relocated.stderr)
            for raw in ('{"schema_version":1,"schema_version":1}', '{"metric":NaN}', '{"metric":Infinity}'):
                path.write_text(raw)
                proc=subprocess.run([sys.executable,str(root/'attempt_record.py'),str(path)],capture_output=True,text=True)
                self.assertNotEqual(proc.returncode,0)
                self.assertEqual(len(proc.stdout.splitlines()),1)
                self.assertFalse(json.loads(proc.stdout)['valid'])

    def test_malformed_model_readback_types_are_structured_errors(self):
        """R20-benchmark-shard-4-01 and R20-benchmark-shard-3-02: malformed typed readbacks fail closed without raising."""
        base={'schema_version':1,'start_id':'s','attempt':1,'arm':'rebuilt','provider_instance_id':'codex',
              'model_as_read_back':{'provider_instance_id':'codex','model_id':'gpt-0-luna'},
              'model_options':{'reasoningEffort':'low','serviceTier':'default'},'runtime_mode':'local',
              'os':'synthetic','t3_build':'build','package_digests':{'imps':'a'*64},'bundle_digests':{'bench':'b'*64},
              'job_id':'j','thread_id':'t','task_ids':[],'check_results':[],
              'parser_summary':{'schema_version':1,'protocol':'bench-v2','sources':[],'parent':{},'workers':[],'sidechain':{},'unattributed_sources':[],'aggregate':{},'gaps':[]},
              'interventions':[],'failures':[],'private_raw_sha256':[],
              'metrics':{'wall_seconds':1,'repair_count':0,'task_count':0,'compaction_count':0,'fallback_count':0,
                         'repeated_setup':0,'parent_peak_context':10,'worker_usage':{},'attribution_gaps':[],'retained_plan_correct':True},
              'unknown_reasons':{},'metrics_unknown_reasons':{}}
        haiku=dict(base,provider_instance_id='claudeAgent',model_as_read_back={'provider_instance_id':'claudeAgent','model_id':'claude-haiku-0'},
                   model_options={'effort':'low'})
        unknown=dict(base,provider_instance_id=None,model_as_read_back=None,model_options={'reasoningEffort':'low','serviceTier':'default'},
                     unknown_reasons={'provider_instance_id':'not read back','model_as_read_back':'not read back'})
        # Exact cheap-model controls stay valid.
        for record in (base,haiku,unknown,dict(haiku,model_options={'thinking':False}),dict(haiku,model_options={'effort':'low','fastMode':False})):
            self.assertEqual(attempt_record.validate(record),[])
        malformed=(17,1.5,True,None,{'id':'gpt-0-luna'},['gpt-0-luna'],'')
        records=[]
        for value in malformed:
            for record in (base,haiku):
                provider=record['provider_instance_id']
                records.append(dict(record,model_as_read_back={'provider_instance_id':provider,'model_id':value}))
                records.append(dict(record,model_as_read_back={'provider_instance_id':value,'model_id':record['model_as_read_back']['model_id']}))
                records.append(dict(record,model_options=dict(record['model_options'],model_id=value)))
            records.append(dict(unknown,model_options=dict(unknown['model_options'],provider_instance_id=value)))
            records.append(dict(unknown,model_options=dict(unknown['model_options'],model_id=value)))
        records.append(dict(base,model_as_read_back={'provider_instance_id':'codex'}))
        for record in records:
            with self.subTest(readback=record['model_as_read_back'],options=record['model_options']):
                errors=attempt_record.validate(record)
                self.assertTrue(errors)
                self.assertTrue(all(isinstance(error,str) for error in errors))
        self.assertIn('$.model_as_read_back.model_id must be string',attempt_record.validate(dict(base,model_as_read_back={'provider_instance_id':'codex','model_id':17})))
        # Existing false/zero, premium and unknown-readback policy refusals are unchanged.
        for record in (dict(haiku,model_options={'thinking':0}),dict(haiku,model_options={'effort':'low','fastMode':0}),
                       dict(base,model_as_read_back={'provider_instance_id':'codex','model_id':'gpt-0-sol'}),
                       dict(base,model_options={'reasoningEffort':'high','serviceTier':'default'}),
                       dict(unknown,model_options={'thinking':0}),dict(unknown,model_options={'serviceTier':'priority','reasoningEffort':'low'})):
            self.assertTrue(attempt_record.validate(record))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'record.json'
            shutil.copy2(V2/'tools'/'attempt_record.py',root/'attempt_record.py')
            shutil.copy2(V2/'tools'/'attempt.schema.json',root/'attempt.schema.json')
            for record,code in ((base,0),(dict(base,model_as_read_back={'provider_instance_id':'codex','model_id':17}),1),
                                (dict(haiku,model_as_read_back={'provider_instance_id':'claudeAgent','model_id':None}),1),
                                (dict(unknown,model_options={'provider_instance_id':{'id':'codex'},'reasoningEffort':'low','serviceTier':'default'}),1)):
                path.write_text(json.dumps(record))
                proc=subprocess.run([sys.executable,str(root/'attempt_record.py'),str(path)],capture_output=True,text=True)
                self.assertEqual((proc.returncode,proc.stderr),(code,''))
                self.assertEqual(len(proc.stdout.splitlines()),1)
                self.assertEqual(json.loads(proc.stdout)['valid'],code==0)

    def test_large_finite_json_integers_are_validated_without_float_conversion(self):
        """R21-benchmark-shard-3-01: a 1001-digit JSON integer is a structured result, never OverflowError."""
        base={'schema_version':1,'start_id':'s','attempt':1,'arm':'rebuilt','provider_instance_id':'codex',
              'model_as_read_back':{'provider_instance_id':'codex','model_id':'gpt-0-luna'},
              'model_options':{'reasoningEffort':'low','serviceTier':'default'},'runtime_mode':'local',
              'os':'synthetic','t3_build':'build','package_digests':{'imps':'a'*64},'bundle_digests':{'bench':'b'*64},
              'job_id':'j','thread_id':'t','task_ids':[],'check_results':[],
              'parser_summary':{'schema_version':1,'protocol':'bench-v2','sources':[],'parent':{},'workers':[],'sidechain':{},'unattributed_sources':[],'aggregate':{},'gaps':[]},
              'interventions':[],'failures':[],'private_raw_sha256':[],
              'metrics':{'wall_seconds':1,'repair_count':0,'task_count':0,'compaction_count':0,'fallback_count':0,
                         'repeated_setup':0,'parent_peak_context':10,'worker_usage':{},'attribution_gaps':[],'retained_plan_correct':True},
              'unknown_reasons':{},'metrics_unknown_reasons':{}}
        haiku=dict(base,provider_instance_id='claudeAgent',model_as_read_back={'provider_instance_id':'claudeAgent','model_id':'claude-haiku-0'},
                   model_options={'effort':'low'})
        huge=10**1000
        self.assertEqual(len(json.dumps(huge)),1001)
        def metric(record,value,name='wall_seconds'):
            # Serialize and parse, as a recorded file would be read.
            return json.loads(json.dumps(dict(record,metrics=dict(record['metrics'],**{name:value}))))
        # Finite integers of any size are finite numbers; ordinary finite values stay valid.
        for record in (base,haiku):
            for value in (huge,0,1,1.5,10**20):
                self.assertEqual(attempt_record.validate(metric(record,value)),[],value)
        self.assertEqual(attempt_record.validate(metric(base,huge,'parent_peak_context')),[])
        self.assertEqual(attempt_record.validate(metric(base,-huge)),['$.metrics.wall_seconds is below minimum 0'])
        # Non-finite floats and booleans are still not numbers.
        for value in (float('inf'),float('-inf'),float('nan'),True,False):
            self.assertEqual(attempt_record.validate(dict(base,metrics=dict(base['metrics'],wall_seconds=value))),
                             ['$.metrics.wall_seconds must be number or null'],value)
        # A large metric is not a cost-policy bypass: premium and high-effort records still fail.
        for record in (dict(base,model_as_read_back={'provider_instance_id':'codex','model_id':'gpt-0-sol'}),
                       dict(base,model_options={'reasoningEffort':'high','serviceTier':'default'}),
                       dict(haiku,model_options={'thinking':0})):
            self.assertTrue(attempt_record.validate(metric(record,huge)))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'record.json'
            shutil.copy2(V2/'tools'/'attempt_record.py',root/'attempt_record.py')
            shutil.copy2(V2/'tools'/'attempt.schema.json',root/'attempt.schema.json')
            def cli(text):
                path.write_text(text)
                proc=subprocess.run([sys.executable,str(root/'attempt_record.py'),str(path)],capture_output=True,text=True)
                self.assertEqual(proc.stderr,'')
                self.assertEqual(len(proc.stdout.splitlines()),1)
                return proc.returncode,json.loads(proc.stdout)
            self.assertEqual(cli(json.dumps(metric(base,huge))),(0,{'valid':True,'errors':[]}))
            self.assertEqual(cli(json.dumps(metric(base,-huge))),(1,{'valid':False,'errors':['$.metrics.wall_seconds is below minimum 0']}))
            self.assertEqual(cli(json.dumps(metric(base,True))),(1,{'valid':False,'errors':['$.metrics.wall_seconds must be number or null']}))
            overflow=json.dumps(base).replace('"wall_seconds": 1,','"wall_seconds": 1e999,')
            self.assertEqual(cli(overflow),(1,{'valid':False,'errors':['$.metrics.wall_seconds must be number or null']}))
            code,result=cli(json.dumps(base).replace('"wall_seconds": 1,','"wall_seconds": Infinity,'))
            self.assertEqual((code,result['valid']),(2,False))


def nulls_without_reason(node, path='$'):
    """Every null total must sit beside a reason in the adjacent `unknown` map."""
    problems = []
    if isinstance(node, dict):
        reasons = node.get('unknown') if isinstance(node.get('unknown'), dict) else None
        totals = node.get('totals') if isinstance(node.get('totals'), dict) else None
        if totals is not None and reasons is not None:
            for field, value in totals.items():
                if value is None and field not in reasons:
                    problems.append(f'{path}.totals.{field}')
        for key, value in node.items():
            problems += nulls_without_reason(value, f'{path}.{key}')
    elif isinstance(node, list):
        for index, value in enumerate(node):
            problems += nulls_without_reason(value, f'{path}[{index}]')
    return problems


class UsageParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = usage.summarise(PARSER_FIXTURES / 'manifest.json')
        cls.sources = {s['file']: s for s in cls.summary['sources']}
        cls.workers = {w['task_id']: w for w in cls.summary['workers']}

    def test_duplicate_lines_collapse_to_one_inference_with_final_usage(self):
        parent = self.summary['parent']
        first = next(r for r in parent['inferences'] if r['id'] == 'msg_p1')
        self.assertEqual((first['output'], first['context']), (80, 3012))
        self.assertEqual(self.sources['parent.jsonl']['duplicates_collapsed'], 2)
        self.assertEqual(len(parent['inferences']), 7)

    def test_resumed_transcript_does_not_count_a_message_twice(self):
        self.assertEqual(self.sources['parent_resumed.jsonl']['totals']['inferences'], 1)
        self.assertIn({'source': 'parent_resumed.jsonl', 'first_source': 'parent.jsonl',
                       'kind': 'duplicate_across_sources', 'detail': 'msg_p2'},
                      self.summary['gaps'])

    def test_missing_cache_value_is_unknown_not_zero(self):
        parent = self.summary['parent']
        self.assertIsNone(parent['totals']['cache_read'])
        self.assertIsNone(parent['totals']['context'])
        self.assertIsNone(parent['peak_context'])
        self.assertEqual(parent['known_max_context'], 3723)
        self.assertIn('lower bound', parent['peak_reason'])
        self.assertEqual(parent['totals']['known_lower_bound']['cache_read'], 17200)
        # parent.jsonl holds a malformed line, so every parent total is a floor (R12-BE-03).
        self.assertEqual((parent['totals']['input'], parent['totals']['output']), (None, None))
        self.assertEqual((parent['totals']['known_lower_bound']['input'],
                          parent['totals']['known_lower_bound']['output']), (30, 189))
        self.assertIn('unparseable or truncated', parent['unknown']['input'])

    def test_stage_boundaries_use_the_last_parent_inference_before_them(self):
        # The frozen parent transcript has a malformed line that may have held a later
        # inference, so no boundary context is known (R12-BE-03).
        for row in self.summary['parent']['stage_boundary_context']:
            self.assertEqual((row['inference'], row['context']), (None, None))
            self.assertIn('unparseable or truncated parent line', row['reason'])
        # Selection itself is checked on a temporary copy without the damaged line.
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'fixtures'; shutil.copytree(PARSER_FIXTURES, copy)
            parent = copy / 'parent.jsonl'
            parent.write_text(''.join(line for line in parent.read_text().splitlines(True) if line.strip() != '{not json'))
            summary = usage.summarise(copy / 'manifest.json')
        bounds = {b['stage']: b for b in summary['parent']['stage_boundary_context']}
        self.assertEqual(bounds['s1']['context'], 3503)
        self.assertEqual(bounds['s1']['inference'], 'req_p3')
        self.assertIsNone(bounds['s2']['context'])
        self.assertEqual(bounds['s2']['reason'], 'needs cache_read')
        self.assertEqual(bounds['s3']['context'], 3612)
        self.assertEqual(bounds['s0']['reason'], 'no parent inference before boundary')

    def test_codex_per_call_and_cumulative_counters(self):
        # Pass 15: the per-call capture ends with a token_count whose info is null after usage
        # was reported, so its session is unknown; its two proven rows are only a floor.
        per_call = self.workers['task-s1-investigator']['totals']
        self.assertEqual((per_call['input'], per_call['cache_read'], per_call['output'], per_call['context']),
                         (None, None, None, None))
        self.assertEqual(tuple(per_call['known_lower_bound'][f] for f in ('input', 'cache_read', 'output', 'context')),
                         (2500, 900, 150, 2500))
        self.assertIn('fail validation', self.workers['task-s1-investigator']['unknown']['input'])
        self.assertIsNone(per_call['cache_write'])
        self.assertEqual(self.sources['worker_codex_per_call.jsonl']['duplicates_collapsed'], 1)
        # A capture without last_token_usage proves no row, so its floor is zero (pass 14: 2800).
        cumulative = self.workers['task-s2-executor']
        self.assertEqual(cumulative['totals']['inferences'], 4)
        self.assertIsNone(cumulative['totals']['input'])
        self.assertEqual(cumulative['totals']['known_lower_bound']['input'], 0)
        kinds = [g['kind'] for g in self.summary['gaps'] if g['source'] == 'worker_codex_cumulative.jsonl']
        self.assertIn('counter_decreased', kinds)
        self.assertIn('token_count_without_usage', kinds)
        self.assertEqual(self.sources['worker_codex_cumulative.jsonl']['duplicates_collapsed'], 1)

    def test_attribution_gaps_keep_aggregates_honest(self):
        self.assertFalse(self.summary['aggregate']['attribution_complete'])
        self.assertEqual(self.summary['unattributed_sources'], ['orphan.jsonl'])
        self.assertEqual(self.summary['sidechain']['inferences'], 1)
        self.assertEqual(self.workers['task-s4-auditor']['totals']['inferences'], 0)
        self.assertIsNone(self.workers['task-s4-auditor']['totals']['output'])
        review = self.workers['task-s5-reviewer']['totals']
        self.assertEqual((review['input'], review['cache_write'], review['context']), (26, 2300, 4326))
        attributed = self.summary['aggregate']['attributed']['totals']
        self.assertIsNone(attributed['input'])
        # Pass 15: the cumulative-only Codex worker proves no row, so it adds 0 instead of 2800.
        self.assertEqual(attributed['known_lower_bound']['input'], 2556)

    def test_every_unknown_total_has_a_reason(self):
        self.assertEqual(nulls_without_reason(self.summary), [])

    def test_manifest_cannot_reach_outside_its_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'sub' / 'manifest.json'
            manifest.parent.mkdir()
            (Path(tmp) / 'outside.jsonl').write_text('')
            manifest.write_text(json.dumps({'schema_version': 1, 'sources': [
                {'file': '../outside.jsonl', 'format': 'claude-jsonl', 'role': 'parent'}]}))
            result = subprocess.run([sys.executable, str(V2 / 'tools' / 'usage.py'), str(manifest)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('escapes', result.stderr)

    def test_same_basename_and_renamed_copy_are_content_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'a').mkdir(); (root/'b').mkdir()
            def row(ts, ident):
                return json.dumps({'type':'assistant','timestamp':ts,'message':{'id':ident,'model':'synthetic','usage':{'input_tokens':5,'output_tokens':2,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}})+'\n'
            (root/'a'/'rollout.jsonl').write_text(row('2026-01-01T00:00:00Z','m1'))
            (root/'b'/'rollout.jsonl').write_text(row('2026-01-01T00:00:01Z','m2'))
            (root/'renamed.jsonl').write_text(row('2026-01-01T00:00:00Z','m1'))
            specs=[{'file':f,'format':'claude-jsonl','role':'worker','task_id':t,'slot':'x','stage':'s1','attempt':0} for f,t in [('a/rollout.jsonl','one'),('b/rollout.jsonl','two'),('renamed.jsonl','one')]]
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':specs}))
            summary=usage.summarise(manifest)
            self.assertEqual({w['task_id']:w['totals']['inferences'] for w in summary['workers']},{'one':1,'two':1})

    def test_manifest_metadata_conflict_and_malformed_type_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'x.jsonl').write_text('');m=root/'manifest.json'
            base={'file':'x.jsonl','format':'claude-jsonl','role':'worker','task_id':'t','stage':'s1','attempt':0}
            m.write_text(json.dumps({'schema_version':1,'sources':[dict(base,slot='a'),dict(base,slot='b')]}))
            with self.assertRaisesRegex(ValueError,'conflicting'):
                usage.summarise(m)
            m.write_text(json.dumps({'schema_version':1,'sources':[dict(base,file=5)]}))
            with self.assertRaisesRegex(ValueError,'string file'):
                usage.summarise(m)
            m.write_text('{"schema_version":true,"schema_version":1,"sources":[]}')
            with self.assertRaisesRegex(ValueError,'duplicate manifest key'):
                usage.summarise(m)
            m.write_text(json.dumps({'schema_version':True,'sources':[]}))
            with self.assertRaisesRegex(ValueError,'schema_version'):
                usage.summarise(m)

    def test_lower_bound_is_complete_and_naive_boundary_has_reason(self):
        self.assertEqual(set(self.summary['parent']['totals']['known_lower_bound']),set(usage.FIELDS)|{'context'})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'p.jsonl').write_text('');m=root/'manifest.json'
            m.write_text(json.dumps({'schema_version':1,'sources':[],'boundaries':[{'stage':'s1','at':'2026-01-01T00:00:00'}]}))
            row=usage.summarise(m)['parent']['stage_boundary_context'][0]
            self.assertIn('timezone-naive',row['reason'])

    def test_naive_parent_timestamp_is_recorded_as_unattributable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); row={'type':'assistant','timestamp':'2026-01-01T00:00:00','message':{'id':'naive','model':'synthetic','usage':{'input_tokens':1,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
            (root/'p.jsonl').write_text(json.dumps(row)+'\n'); m=root/'manifest.json'
            m.write_text(json.dumps({'schema_version':1,'sources':[{'file':'p.jsonl','format':'claude-jsonl','role':'parent'}], 'boundaries':[{'stage':'s1','at':'2026-01-02T00:00:00Z'}]}))
            summary=usage.summarise(m)
            self.assertTrue(any(g['kind']=='timestamp_unorderable' and g['detail']=='naive' for g in summary['gaps']))
            self.assertIn('cannot attribute',summary['parent']['stage_boundary_context'][0]['reason'])

    def test_codex_same_basename_and_renamed_resume_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'left').mkdir(); (root/'right').mkdir()
            one={'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':10,'cached_input_tokens':2,'output_tokens':3}}}}
            two={'type':'event_msg','timestamp':'2026-01-01T00:00:01Z','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':20,'cached_input_tokens':4,'output_tokens':6}}}}
            def write(path, rows): path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            write(root/'left'/'rollout.jsonl',[one]);write(root/'right'/'rollout.jsonl',[two]);write(root/'copy.jsonl',[one])
            specs=[{'file':'left/rollout.jsonl','format':'codex-rollout','role':'worker','task_id':'a','stage':'s1','attempt':0},
                   {'file':'right/rollout.jsonl','format':'codex-rollout','role':'worker','task_id':'b','stage':'s1','attempt':0},
                   {'file':'copy.jsonl','format':'codex-rollout','role':'worker','task_id':'a','stage':'s1','attempt':0}]
            m=root/'manifest.json';m.write_text(json.dumps({'schema_version':1,'sources':specs}))
            summary=usage.summarise(m)
            self.assertEqual({w['task_id']:w['totals']['inferences'] for w in summary['workers']},{'a':2,'b':1})
            self.assertTrue(any(g['kind']=='no_identity' and g['source']=='left/rollout.jsonl' for g in summary['gaps']))

    def test_claude_distinct_message_ids_same_timestamp_and_usage_are_not_collapsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def row(ident):
                return {'type':'assistant','timestamp':'2026-01-01T00:00:00Z','message':{'id':ident,'model':'synthetic','usage':{'input_tokens':7,'output_tokens':2,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
            (root/'one.jsonl').write_text(json.dumps(row('actual-1'))+'\n')
            (root/'two.jsonl').write_text(json.dumps(row('actual-2'))+'\n')
            sources=[{'file':'one.jsonl','format':'claude-jsonl','role':'worker','task_id':'task-one'},
                     {'file':'two.jsonl','format':'claude-jsonl','role':'worker','task_id':'task-two'}]
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':sources}))
            result=usage.summarise(manifest)
            self.assertEqual({w['task_id']:w['totals']['inferences'] for w in result['workers']},{'task-one':1,'task-two':1})
            self.assertEqual({w['task_id']:w['totals']['input'] for w in result['workers']},{'task-one':7,'task-two':7})

    def test_codex_distinct_session_ids_same_event_time_and_usage_are_not_collapsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            meta=lambda sid:{'type':'session_meta','payload':{'id':sid,'model':'synthetic'}}
            event={'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':{'last_token_usage':{'input_tokens':9,'cached_input_tokens':1,'output_tokens':2},'total_token_usage':{'input_tokens':9,'cached_input_tokens':1,'output_tokens':2}}}}
            specs=[]
            for i,sid in enumerate(('session-one','session-two'),1):
                name=f's{i}.jsonl';(root/name).write_text(json.dumps(meta(sid))+'\n'+json.dumps(event)+'\n')
                specs.append({'file':name,'format':'codex-rollout','role':'worker','task_id':f't{i}'})
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':specs}))
            result=usage.summarise(manifest)
            self.assertEqual({w['task_id']:w['totals']['inferences'] for w in result['workers']},{'t1':1,'t2':1})
            self.assertEqual({w['task_id']:w['totals']['input'] for w in result['workers']},{'t1':9,'t2':9})

    def test_codex_same_session_renamed_resume_copy_deduplicates_by_session_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);event={'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':{'last_token_usage':{'input_tokens':9,'cached_input_tokens':1,'output_tokens':2},'total_token_usage':{'input_tokens':9,'cached_input_tokens':1,'output_tokens':2}}}}
            content='\n'.join(json.dumps(x) for x in [{'type':'session_meta','payload':{'id':'one-session','model':'synthetic'}},event])+'\n'
            for name in ('original.jsonl','renamed-copy.jsonl'):(root/name).write_text(content)
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':[{'file':name,'format':'codex-rollout','role':'worker','task_id':'task-a'} for name in ('original.jsonl','renamed-copy.jsonl')]}))
            result=usage.summarise(manifest)
            self.assertEqual(result['workers'][0]['totals']['inferences'],1)
            self.assertTrue(any(g['kind']=='duplicate_across_sources' and g['source']=='renamed-copy.jsonl' and g['first_source']=='original.jsonl' for g in result['gaps']))

    def test_codex_session_change_resets_cumulative_baseline_inside_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            counters={'input_tokens':9,'cached_input_tokens':1,'output_tokens':2}
            for info,expected in (({'total_token_usage':counters,'last_token_usage':counters},18),
                                  ({'total_token_usage':counters},None)):  # pass 15: no last_token_usage proves nothing
                root=Path(tmp);event={'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':info}}
                rows=[]
                for sid in ('session-one','session-two'):
                    rows.extend([{'type':'session_meta','payload':{'id':sid,'model':'synthetic'}},event])
                (root/'combined.jsonl').write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
                manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':[{'file':'combined.jsonl','format':'codex-rollout','role':'parent'}]}))
                result=usage.summarise(manifest)
                self.assertEqual(result['parent']['totals']['inferences'],2)
                self.assertEqual(result['parent']['totals']['input'],expected)

    def test_codex_identityless_equal_snapshots_are_retained_with_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=[]
            for second in ('00','01'):
                rows.append({'type':'event_msg','timestamp':f'2026-01-01T00:00:{second}Z','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':9,'cached_input_tokens':1,'output_tokens':2},'last_token_usage':{'input_tokens':9,'cached_input_tokens':1,'output_tokens':2}}}})
            (root/'rollout.jsonl').write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':[{'file':'rollout.jsonl','format':'codex-rollout','role':'parent'}]}))
            result=usage.summarise(manifest)
            self.assertEqual(result['parent']['totals']['inferences'],2)
            # Pass 15: the repeat may be a copied line or another session's first request, so the
            # capture's usage is unknown above the first row (pass 14 published 18).
            self.assertIsNone(result['parent']['totals']['input'])
            self.assertEqual(result['parent']['totals']['known_lower_bound']['input'],9)
            self.assertFalse(result['aggregate']['attribution_complete'])
            self.assertTrue(any(g['kind']=='ambiguous_repeated_snapshot' for g in result['gaps']))

    def test_identityless_reuse_is_counted_as_unknown_with_manifest_relative_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a').mkdir();(root/'b').mkdir()
            row={'type':'assistant','timestamp':'2026-01-01T00:00:00Z','message':{'model':'synthetic','usage':{'input_tokens':3,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
            raw=json.dumps(row)+'\n';(root/'a'/'same.jsonl').write_text(raw);(root/'b'/'same.jsonl').write_text(raw)
            specs=[{'file':f'{name}/same.jsonl','format':'claude-jsonl','role':'worker','task_id':name} for name in ('a','b')]
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':specs}))
            result=usage.summarise(manifest)
            self.assertEqual({w['task_id']:w['totals']['inferences'] for w in result['workers']},{'a':1,'b':1})
            self.assertEqual({w['task_id']:w['totals']['input'] for w in result['workers']},{'a':3,'b':3})
            self.assertTrue(all(g['source'] in ('a/same.jsonl','b/same.jsonl') for g in result['gaps'] if g['kind']=='no_identity'))
            self.assertEqual({row['source'] for w in result['workers'] for row in w['inferences']},{'a/same.jsonl','b/same.jsonl'})
            self.assertNotIn(str(root.resolve()),json.dumps(result))

    def test_same_inference_identity_with_conflicting_task_ownership_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);row={'type':'assistant','timestamp':'2026-01-01T00:00:00Z','message':{'id':'one-id','model':'synthetic','usage':{'input_tokens':3,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
            for name in ('a.jsonl','b.jsonl'):(root/name).write_text(json.dumps(row)+'\n')
            sources=[{'file':name,'format':'claude-jsonl','role':'worker','task_id':task} for name,task in [('a.jsonl','task-a'),('b.jsonl','task-b')]]
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':sources}))
            with self.assertRaisesRegex(ValueError,'conflicting role/task ownership'):
                usage.summarise(manifest)

    def test_partial_and_final_copies_merge_independent_of_source_order(self):
        """R10-BE-02: an interrupted partial and its resumed final copy give one final total."""
        def row(output, cache=0, model='synthetic', at='2026-01-01T00:00:00Z'):
            usage_row={'input_tokens':3,'output_tokens':output,'cache_creation_input_tokens':0}
            if cache is not None: usage_row['cache_read_input_tokens']=cache
            return json.dumps({'type':'assistant','timestamp':at,'message':{'id':'one-message','model':model,'usage':usage_row}})+'\n'
        def summary(first, second):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'partial.jsonl').write_text(first);(root/'final.jsonl').write_text(second)
                results=[]
                for order in (('partial.jsonl','final.jsonl'),('final.jsonl','partial.jsonl')):
                    manifest=root/'manifest.json'
                    manifest.write_text(json.dumps({'schema_version':1,'sources':[{'file':f,'format':'claude-jsonl','role':'parent'} for f in order]}))
                    results.append(usage.summarise(manifest))
                return results
        for result in summary(row(1), row(80)):
            self.assertEqual(result['parent']['totals']['output'], 80)
            self.assertEqual(result['parent']['totals']['inferences'], 1)
            self.assertEqual(result['aggregate']['attributed']['totals']['output'], 80)
            self.assertTrue(result['aggregate']['attribution_complete'])
            self.assertEqual(sum(s['totals']['output'] or 0 for s in result['sources']), 80)
        # A missing field in one copy is filled from the other; context is then known.
        for result in summary(row(1, cache=None, at='2026-01-01T00:00:05Z'), row(80, cache=7)):
            inference=result['parent']['inferences'][0]
            self.assertEqual((inference['cache_read'], inference['context'], inference['unknown']), (7, 10, {}))
            self.assertEqual(inference['at'], '2026-01-01T00:00:00Z')
            self.assertEqual(nulls_without_reason(result), [])
        # A copy naming another model cannot be merged by maximum: attribution is incomplete.
        for result in summary(row(1), row(80, model='other-synthetic')):
            self.assertFalse(result['aggregate']['attribution_complete'])
            self.assertEqual(result['aggregate']['usage_conflicts'][0]['fields'], ['model'])
            self.assertIn('usage_conflict', {g['kind'] for g in result['gaps']})

    def test_codex_cumulative_tail_uses_merged_snapshots_not_max_of_deltas(self):
        """R11-BE-01: a resumed cumulative tail neither inflates totals nor context in either order."""
        meta={'type':'session_meta','payload':{'id':'same-session','model':'synthetic'}}
        def event(number, input_tokens, output_tokens, last=(100,10)):
            info={'id':f'e{number}','total_token_usage':{'input_tokens':input_tokens,'cached_input_tokens':0,'output_tokens':output_tokens}}
            if last: info['last_token_usage']={'input_tokens':last[0],'cached_input_tokens':0,'output_tokens':last[1]}
            return {'type':'event_msg','timestamp':f'2026-01-01T00:00:0{number}Z','payload':{'type':'token_count','info':info}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name, rows): (root/name).write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            # Pass 15: every snapshot carries last_token_usage; the late tail claims a second zero start.
            write('full.jsonl',[meta,event(1,100,10),event(2,200,20)])
            write('tail.jsonl',[meta,event(2,200,20)])
            write('late-tail.jsonl',[meta,event(3,300,30,last=(300,30))])
            write('cumulative-full.jsonl',[meta,event(1,100,10,last=None),event(2,200,20,last=None)])
            write('cumulative-tail.jsonl',[meta,event(2,200,20,last=None)])
            def summary(*files, resumed=()):
                manifest=root/'manifest.json'
                manifest.write_text(json.dumps({'schema_version':1,'sources':[
                    dict({'file':f,'format':'codex-rollout','role':'parent'},**({'resumed':True} if f in resumed else {}))
                    for f in files]}))
                return usage.summarise(manifest)
            for files in (('full.jsonl',),('full.jsonl','tail.jsonl'),('tail.jsonl','full.jsonl')):
                for resumed in ((),('tail.jsonl',)):
                    result=summary(*files,resumed=resumed);parent=result['parent']
                    self.assertEqual((parent['totals']['input'],parent['totals']['output'],parent['totals']['inferences']),(200,20,2),files)
                    self.assertEqual(parent['peak_context'],100,files)
                    self.assertEqual(parent['totals']['known_lower_bound']['input'],200,files)
                    self.assertTrue(result['aggregate']['attribution_complete'],files)
                    self.assertEqual(nulls_without_reason(result),[])
            # A tail whose first snapshot has no earlier snapshot in any source has no known baseline.
            alone=summary('tail.jsonl',resumed=('tail.jsonl',));parent=alone['parent']
            self.assertEqual(parent['totals']['inferences'],1)
            self.assertIsNone(parent['totals']['input']);self.assertIsNone(parent['totals']['output'])
            self.assertIsNone(parent['peak_context']);self.assertEqual(parent['totals']['known_lower_bound']['input'],0)
            self.assertIn('no earlier snapshot',parent['inferences'][0]['unknown']['input'])
            self.assertFalse(alone['aggregate']['attribution_complete'])
            self.assertIn('cumulative_baseline_unknown',{g['kind'] for g in alone['gaps']})
            self.assertEqual(nulls_without_reason(alone),[])
            # Pass 15: without the resumed flag the tail still does not prove a zero start.
            unflagged=summary('tail.jsonl')
            self.assertIsNone(unflagged['parent']['totals']['input'])
            self.assertIn('not a zero start',unflagged['parent']['inferences'][0]['unknown']['input'])
            self.assertFalse(unflagged['aggregate']['attribution_complete'])
            # Pass 15: cumulative-only captures (pass 14 counted them from zero) are unknown in every order.
            for files in (('cumulative-full.jsonl',),('cumulative-full.jsonl','cumulative-tail.jsonl'),
                          ('cumulative-tail.jsonl','cumulative-full.jsonl')):
                result=summary(*files);parent=result['parent']
                self.assertIsNone(parent['totals']['input'],files);self.assertIsNone(parent['peak_context'],files)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],0,files)
                self.assertFalse(result['aggregate']['attribution_complete'],files)
                self.assertEqual(nulls_without_reason(result),[],files)
            # One session cannot start twice: the larger unlinked first snapshot is a tail.
            for files in (('full.jsonl','late-tail.jsonl'),('late-tail.jsonl','full.jsonl')):
                result=summary(*files);parent=result['parent']
                self.assertIsNone(parent['totals']['input'],files)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],200,files)
                self.assertFalse(result['aggregate']['attribution_complete'],files)
            # The same event with different cumulative snapshots is a conflict, not a maximum.
            write('collision.jsonl',[meta,event(2,250,25,last=(150,15))])
            result=summary('full.jsonl','collision.jsonl')
            self.assertIsNone(result['parent']['totals']['input'])
            self.assertEqual(result['aggregate']['usage_conflicts'][0]['fields'],['cumulative_snapshot'])
            self.assertFalse(result['aggregate']['attribution_complete'])
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'schema_version':1,'sources':[
                {'file':'tail.jsonl','format':'codex-rollout','role':'parent','resumed':'yes'}]}))
            with self.assertRaisesRegex(ValueError,'unknown format or role'):
                usage.summarise(manifest)

    def test_codex_session_captures_align_by_cumulative_snapshot_not_local_ordinal(self):
        """R12-BE-01: A,A,B and A,B of one session without event IDs count two inferences in either order."""
        meta={'type':'session_meta','payload':{'id':'same-session','model':'synthetic'}}
        def snap(input_tokens, output_tokens, second, last=False, ident=None, delta=(100,10)):
            usage_row={'input_tokens':input_tokens,'cached_input_tokens':0,'output_tokens':output_tokens}
            info={'last_token_usage':usage_row} if last else {'total_token_usage':usage_row}
            if delta and not last:  # pass 15: a usable snapshot also reports its per-call usage
                info['last_token_usage']={'input_tokens':delta[0],'cached_input_tokens':0,'output_tokens':delta[1]}
            if ident: info['id']=ident
            return {'type':'event_msg','timestamp':f'2026-01-01T00:00:0{second}Z','payload':{'type':'token_count','info':info}}
        a,b=snap(100,10,1),snap(200,20,2)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name, rows): (root/name).write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            def summary(*files):
                manifest=root/'manifest.json'
                manifest.write_text(json.dumps({'schema_version':1,'sources':[
                    {'file':f,'format':'codex-rollout','role':'parent'} for f in files]}))
                return usage.summarise(manifest)
            write('full.jsonl',[meta,a,a,b]);write('copy.jsonl',[meta,a,b])
            # Pass 15: the same captures without last_token_usage are unknown in every order.
            plain_a,plain_b=snap(100,10,1,delta=None),snap(200,20,2,delta=None)
            write('cumulative-full.jsonl',[meta,plain_a,plain_a,plain_b]);write('cumulative-copy.jsonl',[meta,plain_a,plain_b])
            for files in (('cumulative-full.jsonl',),('cumulative-full.jsonl','cumulative-copy.jsonl'),
                          ('cumulative-copy.jsonl','cumulative-full.jsonl')):
                result=summary(*files)
                self.assertIsNone(result['parent']['totals']['input'],files)
                self.assertFalse(result['aggregate']['attribution_complete'],files)
            for files in (('full.jsonl',),('copy.jsonl',),('full.jsonl','copy.jsonl'),('copy.jsonl','full.jsonl')):
                result=summary(*files);parent=result['parent']
                self.assertEqual((parent['totals']['input'],parent['totals']['output'],parent['totals']['inferences']),(200,20,2),files)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],200,files)
                self.assertEqual(parent['peak_context'],100,files)
                self.assertEqual(result['aggregate']['usage_conflicts'],[],files)
                self.assertTrue(result['aggregate']['attribution_complete'],files)
            # Captures that cannot be aligned leave the session's usage unknown, never summed.
            write('recurs.jsonl',[meta,a,b,a])
            write('per-call-1.jsonl',[meta,snap(100,10,1,last=True),snap(100,10,2,last=True)])
            write('per-call-2.jsonl',[meta,snap(100,10,2,last=True)])
            write('with-ids.jsonl',[meta,snap(100,10,1,ident='e1'),snap(200,20,2,ident='e2')])
            write('gapped.jsonl',[meta,a,snap(300,30,3)])
            write('three.jsonl',[meta,a,b,snap(300,30,3)])
            for files in (('recurs.jsonl',),('per-call-1.jsonl','per-call-2.jsonl'),('with-ids.jsonl','copy.jsonl'),
                          ('copy.jsonl','with-ids.jsonl'),('three.jsonl','gapped.jsonl')):
                result=summary(*files);parent=result['parent']
                self.assertIsNone(parent['totals']['input'],files);self.assertIsNone(parent['peak_context'],files)
                self.assertFalse(result['aggregate']['attribution_complete'],files)
                self.assertEqual(nulls_without_reason(result),[],files)
            kinds={g['kind'] for g in summary('with-ids.jsonl','copy.jsonl')['gaps']}
            self.assertIn('session_alignment_ambiguous',kinds)

    def test_damaged_usage_line_makes_totals_and_peak_unknown(self):
        """R12-BE-03: a truncated m2 line after a valid m1 leaves only lower bounds."""
        m1=json.dumps({'type':'assistant','timestamp':'2026-01-01T00:00:00Z','message':{'id':'m1','model':'synthetic','usage':{
            'input_tokens':100,'output_tokens':10,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}})+'\n'
        truncated='{"type": "assistant", "timestamp": "2026-01-01T00:00:01Z", "message": {"id": "m2", "usage": {"input_tokens": 9999'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def summary(raw, role='parent'):
                (root/'source.jsonl').write_bytes(raw)
                spec={'file':'source.jsonl','format':'claude-jsonl','role':role}
                if role=='worker': spec['task_id']='task-a'
                manifest=root/'manifest.json'
                manifest.write_text(json.dumps({'schema_version':1,'sources':[spec],
                                                'boundaries':[{'stage':'s1','at':'2026-01-01T00:00:05Z'}]}))
                return usage.summarise(manifest)
            clean=summary(m1.encode())
            self.assertEqual((clean['parent']['totals']['input'],clean['parent']['peak_context']),(100,100))
            self.assertTrue(clean['aggregate']['attribution_complete'])
            for raw in ((m1+truncated).encode(),(m1+'[1, 2]\n').encode(),m1.encode()+b'{"type": "\xff"}\n'):
                result=summary(raw);parent=result['parent'];totals=parent['totals']
                self.assertEqual((totals['input'],totals['output'],totals['context']),(None,None,None),raw)
                self.assertEqual((totals['known_lower_bound']['input'],totals['known_lower_bound']['output']),(100,10),raw)
                self.assertIsNone(parent['peak_context']);self.assertEqual(parent['known_max_context'],100)
                self.assertIsNone(parent['stage_boundary_context'][0]['context'])
                self.assertFalse(result['aggregate']['attribution_complete'],raw)
                self.assertIsNone(result['aggregate']['attributed']['totals']['input'])
                self.assertEqual(result['aggregate']['attributed']['totals']['known_lower_bound']['input'],100)
                self.assertEqual(result['sources'][0]['damaged_lines'],1)
                self.assertIsNone(result['sources'][0]['totals']['input'])
                self.assertEqual(nulls_without_reason(result),[])
            worker=summary((m1+truncated).encode(),role='worker')['workers'][0]['totals']
            self.assertIsNone(worker['input']);self.assertEqual(worker['known_lower_bound']['input'],100)

    @staticmethod
    def codex_summary(root, files, order=None, boundaries=None, form='codex-rollout'):
        """Write each capture (rows or raw lines) and summarise them as parent sources in order."""
        for name, rows in files.items():
            (root/name).write_text(''.join(row if isinstance(row, str) else json.dumps(row)+'\n' for row in rows))
        manifest=root/'manifest.json'
        manifest.write_text(json.dumps({'schema_version':1,'sources':[{'file':f,'format':form,'role':'parent'} for f in (order or files)],
                                        **({'boundaries':boundaries} if boundaries else {})}))
        return usage.summarise(manifest)

    @staticmethod
    def snap(input_tokens, output_tokens, second, extra=None, last=None):
        info={'total_token_usage':{'input_tokens':input_tokens,'cached_input_tokens':0,'output_tokens':output_tokens,**(extra or {})}}
        if last: info['last_token_usage']={'input_tokens':last[0],'cached_input_tokens':0,'output_tokens':last[1]}
        return {'type':'event_msg','timestamp':f'2026-01-01T00:00:0{second}Z','payload':{'type':'token_count','info':info}}

    META={'type':'session_meta','payload':{'id':'same-session','model':'synthetic'}}

    def test_optional_codex_counters_are_compared_never_part_of_snapshot_identity(self):
        """R13-BE-01: copies of one session that differ only in optional counters count each request once."""
        snap=self.snap
        def optional(i, o): return {'total_tokens':i+o,'reasoning_output_tokens':0}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files={'rich.jsonl':[self.META,snap(100,10,1,optional(100,10),last=(100,10)),snap(200,20,2,optional(200,20),last=(100,10))],
                   'plain.jsonl':[self.META,snap(100,10,1,last=(100,10)),snap(200,20,2,last=(100,10))]}
            for order in (('rich.jsonl',),('plain.jsonl',)):
                result=self.codex_summary(root,files,order);parent=result['parent']
                self.assertEqual((parent['totals']['input'],parent['totals']['output'],parent['totals']['inferences']),(200,20,2),order)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],200,order)
                self.assertEqual(parent['peak_context'],100,order)
                self.assertEqual(result['aggregate']['usage_conflicts'],[],order)
                self.assertTrue(result['aggregate']['attribution_complete'],order)
            # Pass 15: a snapshot recorded twice must be identical in every counter, optional ones
            # included, so rich and plain copies are a conflict (pass 14 aligned them). The floor
            # comes from one capture and never sums the copies.
            for order in (('rich.jsonl','plain.jsonl'),('plain.jsonl','rich.jsonl')):
                result=self.codex_summary(root,files,order);parent=result['parent']
                self.assertIsNone(parent['totals']['input'],order);self.assertIsNone(parent['peak_context'],order)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],200,order)
                self.assertEqual(result['aggregate']['usage_conflicts'][0]['fields'],['cumulative_snapshot'],order)
                self.assertFalse(result['aggregate']['attribution_complete'],order)
                self.assertEqual(nulls_without_reason(result),[],order)
            # An optional counter both copies report must agree; otherwise it is a conflict, never a sum.
            files['clash.jsonl']=[self.META,snap(100,10,1,{'total_tokens':999},last=(100,10)),snap(200,20,2,last=(100,10))]
            for order in (('rich.jsonl','clash.jsonl'),('clash.jsonl','rich.jsonl')):
                result=self.codex_summary(root,files,order)
                self.assertNotEqual(result['parent']['totals']['input'],400,order)
                self.assertLessEqual(result['parent']['totals']['known_lower_bound']['input'],200,order)
                self.assertEqual(result['aggregate']['usage_conflicts'][0]['fields'],['cumulative_snapshot'],order)
                self.assertFalse(result['aggregate']['attribution_complete'],order)
            # A snapshot missing a required counter cannot align captures at all.
            short={'type':'event_msg','timestamp':'2026-01-01T00:00:01Z','payload':{'type':'token_count','info':{
                'total_token_usage':{'input_tokens':100,'output_tokens':10}}}}
            files['short.jsonl']=[self.META,short,snap(200,20,2,last=(100,10))]
            result=self.codex_summary(root,files,('plain.jsonl','short.jsonl'))
            self.assertIsNone(result['parent']['totals']['input'])
            self.assertIn('token_count_without_usage',{g['kind'] for g in result['gaps']})
            self.assertFalse(result['aggregate']['attribution_complete'])
            self.assertEqual(nulls_without_reason(result),[])

    def test_cumulative_delta_across_a_damaged_or_usage_less_line_is_unknown(self):
        """R13-BE-02: A, damaged B, C must not publish C's two-request delta as one context."""
        snap=self.snap
        damaged='{"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 2\n'
        usage_less={'type':'event_msg','timestamp':'2026-01-01T00:00:02Z','payload':{'type':'token_count','info':{
            'last_token_usage':{'output_tokens':10}}}}
        a,b,c=snap(100,10,1,last=(100,10)),snap(200,20,2,last=(100,10)),snap(300,30,3,last=(100,10))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,rows in (('session.jsonl',[self.META,a,damaged,c]),('identityless.jsonl',[a,damaged,c]),
                              ('usage-less.jsonl',[self.META,a,usage_less,c])):
                result=self.codex_summary(root,{name:rows});parent=result['parent']
                self.assertNotIn(200,[row['context'] for row in parent['inferences']],name)
                self.assertEqual(parent['known_max_context'],100,name)
                self.assertIsNone(parent['peak_context'],name)
                last=next(row for row in parent['inferences'] if row['at']=='2026-01-01T00:00:03Z')
                self.assertEqual((last['input'],last['output'],last['context']),(None,None,None),name)
                self.assertIn('lies between this snapshot and the preceding one',last['unknown']['input'],name)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],100,name)
                self.assertFalse(result['aggregate']['attribution_complete'],name)
                self.assertEqual(nulls_without_reason(result),[],name)
            # A damaged line before the first snapshot: the snapshot is not usage from zero.
            result=self.codex_summary(root,{'head.jsonl':[damaged,a]})
            self.assertIsNone(result['parent']['inferences'][0]['context'])
            self.assertNotIn('assumption',{g['kind'] for g in result['gaps']})
            # Pass 15: damage in any capture of a session makes the whole session unknown, even
            # when an undamaged copy records every snapshot (pass 14 published its contexts). The
            # floor is the clean capture's proven rows, never both copies.
            files={'damaged.jsonl':[self.META,a,damaged,c],'clean.jsonl':[self.META,a,b,c]}
            for order in (('damaged.jsonl','clean.jsonl'),('clean.jsonl','damaged.jsonl')):
                result=self.codex_summary(root,files,order);parent=result['parent']
                self.assertIn(None,[row['context'] for row in parent['inferences']],order)
                self.assertNotIn(200,[row['context'] for row in parent['inferences']],order)
                self.assertIsNone(parent['totals']['input'],order);self.assertIsNone(parent['peak_context'],order)
                self.assertEqual(parent['known_max_context'],100,order)
                self.assertEqual(result['aggregate']['usage_conflicts'],[],order)
                self.assertEqual(parent['totals']['known_lower_bound']['input'],300,order)
                self.assertIn('session_damaged',{g['kind'] for g in result['gaps']},order)
                self.assertFalse(result['aggregate']['attribution_complete'],order)
            # Damage before a session's first snapshot leaves its baseline unknown.
            result=self.codex_summary(root,{'damaged.jsonl':[self.META,damaged,c]})
            self.assertIsNone(result['parent']['inferences'][0]['context'])
            self.assertIn('cumulative_baseline_unknown',{g['kind'] for g in result['gaps']})

    def test_per_call_usage_that_disagrees_with_cumulative_counters_is_not_a_complete_total(self):
        """Sweep: counters that grow by more than the per-call usage show requests the capture lacks."""
        snap=self.snap
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            consistent=self.codex_summary(root,{'ok.jsonl':[self.META,snap(100,10,1,last=(100,10)),snap(200,20,2,last=(100,10))]})
            self.assertEqual(consistent['parent']['totals']['input'],200)
            self.assertTrue(consistent['aggregate']['attribution_complete'])
            result=self.codex_summary(root,{'gap.jsonl':[self.META,snap(100,10,1,last=(100,10)),snap(300,30,3,last=(100,10))]})
            parent=result['parent']
            # Pass 15: only rows proven by the cumulative counters form the floor (pass 14: 200).
            self.assertIsNone(parent['totals']['input']);self.assertEqual(parent['totals']['known_lower_bound']['input'],100)
            self.assertIsNone(parent['peak_context']);self.assertEqual(parent['known_max_context'],100)
            self.assertIn('disagree with the cumulative counters',parent['unknown']['input'])
            self.assertEqual(result['sources'][0]['usage_mismatches'],2)
            self.assertFalse(result['aggregate']['attribution_complete'])
            self.assertEqual(nulls_without_reason(result),[])

    def test_codex_session_usage_is_known_only_for_a_self_consistent_capture(self):
        """Pass 15 (R14-BE-01..03): a Codex session's usage is published only when every row proves it."""
        snap=self.snap
        bounds=[{'stage':'s1','at':'2026-01-01T00:00:05Z'}]
        def token_count(second, **payload):
            return {'type':'event_msg','timestamp':f'2026-01-01T00:00:0{second}Z','payload':{'type':'token_count',**payload}}
        def assert_unknown(result, label, floor, peak_floor):
            parent=result['parent']
            self.assertEqual((parent['totals']['input'],parent['totals']['output'],parent['totals']['context']),(None,None,None),label)
            self.assertEqual(parent['totals']['known_lower_bound']['input'],floor,label)
            self.assertIsNone(parent['peak_context'],label);self.assertEqual(parent['known_max_context'],peak_floor,label)
            self.assertNotIn(200,[row['context'] for row in parent['inferences']],label)
            self.assertEqual([(b['inference'],b['context']) for b in parent['stage_boundary_context']],[(None,None)],label)
            self.assertFalse(result['aggregate']['attribution_complete'],label)
            self.assertEqual(nulls_without_reason(result),[],label)
        a,b=snap(100,10,1,last=(100,10)),snap(200,20,3,last=(100,10))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # R14-BE-01: the review's cumulative-only capture with info=null between A and C.
            result=self.codex_summary(root,{'p.jsonl':[self.META,snap(100,10,1),token_count(2,info=None),snap(300,30,3)]},boundaries=bounds)
            assert_unknown(result,'review',0,None)
            # A usage-less token_count after usage was reported makes a consistent capture unknown.
            for label,usage_less in (('null',token_count(2,info=None)),('missing',token_count(2)),
                                     ('not an object',token_count(2,info='garbage')),('empty',token_count(2,info={}))):
                result=self.codex_summary(root,{'p.jsonl':[self.META,a,usage_less,b]},boundaries=bounds)
                assert_unknown(result,label,100,100)
                self.assertIn('token_count_without_usage',{g['kind'] for g in result['gaps']},label)
            # A null info before the first usage report claims nothing: the zero start still proves the session.
            result=self.codex_summary(root,{'p.jsonl':[self.META,token_count(0,info=None),a,b]},boundaries=bounds)
            self.assertEqual((result['parent']['totals']['input'],result['parent']['peak_context']),(200,100))
            self.assertTrue(result['aggregate']['attribution_complete'])
            # R14-BE-02: a repeat differing in an optional counter is a conflict, in either order and capture.
            plain=snap(100,10,1,last=(100,10))
            rich=snap(100,10,1,{'total_tokens':999},last=(100,10))
            other=snap(100,10,1,{'total_tokens':110},last=(100,10))
            for files,order in (({'p.jsonl':[self.META,plain,rich,b],'q.jsonl':[self.META,other,b]},('p.jsonl','q.jsonl')),
                                ({'p.jsonl':[self.META,plain,rich,b],'q.jsonl':[self.META,other,b]},('q.jsonl','p.jsonl')),
                                ({'p.jsonl':[self.META,rich,plain,b]},('p.jsonl',)),
                                ({'p.jsonl':[self.META,plain,rich,b]},('p.jsonl',))):
                result=self.codex_summary(root,files,order,boundaries=bounds)
                self.assertIsNone(result['parent']['totals']['input'],order)
                self.assertEqual(result['aggregate']['usage_conflicts'][0]['fields'],['cumulative_snapshot'],order)
                self.assertFalse(result['aggregate']['attribution_complete'],order)
                self.assertLessEqual(result['parent']['totals']['known_lower_bound']['input'],200,order)
                self.assertEqual(nulls_without_reason(result),[],order)
            # R14-BE-03: a first row whose per-call usage is below its total is not a zero start.
            result=self.codex_summary(root,{'p.jsonl':[self.META,snap(300,30,3,last=(100,10))]},boundaries=bounds)
            assert_unknown(result,'first row',0,None)
            self.assertIn('cumulative_baseline_unknown',{g['kind'] for g in result['gaps']})
            self.assertIn('not a zero start',result['parent']['inferences'][0]['unknown']['input'])
            # A later row is proven alone by its predecessor, so it is a floor, never the total.
            result=self.codex_summary(root,{'p.jsonl':[self.META,snap(300,30,1,last=(100,10)),snap(400,40,3,last=(100,10))]},
                                      boundaries=bounds)
            self.assertIsNone(result['parent']['totals']['input'])
            self.assertEqual(result['parent']['totals']['known_lower_bound']['input'],100)
            self.assertFalse(result['aggregate']['attribution_complete'])

    def test_unorderable_parent_inference_makes_every_boundary_unknown(self):
        """R13-BE-03: a naive m2 may precede the boundary, so m1 is not the known last inference."""
        def row(ident, at, tokens):
            return {'type':'assistant','timestamp':at,'message':{'id':ident,'model':'synthetic','usage':{
                'input_tokens':tokens,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
        bounds=[{'stage':'s1','at':'2026-01-01T00:00:05Z'},{'stage':'s2','at':'2026-01-01T00:01:00Z'}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            clean=self.codex_summary(root,{'p.jsonl':[row('m1','2026-01-01T00:00:01Z',100)]},boundaries=bounds,form='claude-jsonl')
            self.assertEqual(clean['parent']['stage_boundary_context'][0]['context'],100)
            self.assertTrue(clean['aggregate']['attribution_complete'])
            for stamp in ('2026-01-01T00:00:02', None, 'not a time'):
                result=self.codex_summary(root,{'p.jsonl':[row('m1','2026-01-01T00:00:01Z',100),row('m2',stamp,9999)]},
                                          boundaries=bounds,form='claude-jsonl')
                for boundary in result['parent']['stage_boundary_context']:
                    self.assertEqual((boundary['inference'],boundary['context']),(None,None),stamp)
                    self.assertIn('cannot attribute',boundary['reason'],stamp)
                self.assertFalse(result['aggregate']['attribution_complete'],stamp)
                # Usage totals stay known; only the stage attribution is unknown.
                self.assertEqual(result['parent']['totals']['input'],10099,stamp)
                self.assertEqual(result['parent']['peak_context'],9999,stamp)
                self.assertEqual((result['sources'][0]['first_at'],result['sources'][0]['last_at']),(None,None),stamp)
                self.assertIn('timezone-naive',result['sources'][0]['unknown']['first_at'],stamp)
            # Two captures stamping different inferences with one instant have no known order.
            tied=self.codex_summary(root,{'a.jsonl':[row('m1','2026-01-01T00:00:01Z',100)],
                                          'b.jsonl':[row('m2','2026-01-01T00:00:01Z',9999)]},boundaries=bounds,form='claude-jsonl')
            self.assertEqual(tied['parent']['stage_boundary_context'][0]['context'],None)
            self.assertFalse(tied['aggregate']['attribution_complete'])
            # An unusable boundary leaves its stage unattributed.
            invalid=self.codex_summary(root,{'p.jsonl':[row('m1','2026-01-01T00:00:01Z',100)]},
                                       boundaries=[{'stage':'s1','at':'2026-01-01T00:00:05'}],form='claude-jsonl')
            self.assertFalse(invalid['aggregate']['attribution_complete'])
            # Source spans order by instant, not by string: 10:00+10:00 precedes 01:00Z.
            spans=self.codex_summary(root,{'p.jsonl':[row('m1','2026-01-01T01:00:00Z',1),row('m2','2026-01-01T10:00:00+10:00',1)]},
                                     form='claude-jsonl')
            self.assertEqual((spans['sources'][0]['first_at'],spans['sources'][0]['last_at']),
                             ('2026-01-01T10:00:00+10:00','2026-01-01T01:00:00Z'))

    def test_identityless_rows_leave_attribution_incomplete(self):
        """A row without a stable identity cannot be recognised in a copy: totals may double count."""
        claude=json.dumps({'type':'assistant','timestamp':'2026-01-01T00:00:00Z','message':{'model':'synthetic','usage':{
            'input_tokens':3,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}})+'\n'
        counters={'input_tokens':3,'cached_input_tokens':0,'output_tokens':1}
        def codex(info): return json.dumps({'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':info}})+'\n'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # Pass 15: a Codex row needs total_token_usage too; per-call usage alone is unknown.
            for raw,form,expected in ((claude,'claude-jsonl',3),
                                      (codex({'last_token_usage':counters,'total_token_usage':counters}),'codex-rollout',3),
                                      (codex({'last_token_usage':counters}),'codex-rollout',None)):
                (root/'one.jsonl').write_text(raw)
                manifest=root/'manifest.json'
                manifest.write_text(json.dumps({'schema_version':1,'sources':[{'file':'one.jsonl','format':form,'role':'parent'}]}))
                result=usage.summarise(manifest)
                self.assertEqual(result['parent']['totals']['input'],expected,form)
                self.assertFalse(result['aggregate']['attribution_complete'],form)

    def test_repeated_identityless_manifest_entry_keeps_ambiguous_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);row={'type':'assistant','timestamp':'2026-01-01T00:00:00Z','message':{'model':'synthetic','usage':{'input_tokens':4,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
            (root/'unknown.jsonl').write_text(json.dumps(row)+'\n')
            source={'file':'unknown.jsonl','format':'claude-jsonl','role':'parent'}
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'sources':[source,source]}))
            result=usage.summarise(manifest)
            self.assertEqual(result['parent']['totals']['inferences'],2)
            self.assertEqual(result['parent']['totals']['input'],8)
            self.assertEqual(sum(g['kind']=='no_identity' for g in result['gaps']),2)

    def test_missing_previous_cache_delta_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); f=root/'rollout.jsonl'
            rows=[{'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':10,'output_tokens':2}}}},
                  {'type':'event_msg','timestamp':'2026-01-01T00:00:01Z','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':20,'cached_input_tokens':50,'output_tokens':4}}}}]
            f.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            m=root/'manifest.json';m.write_text(json.dumps({'schema_version':1,'sources':[{'file':f.name,'format':'codex-rollout','role':'parent'}]}))
            summary=usage.summarise(m); row=summary['parent']['inferences'][1]
            self.assertIsNone(row['cache_read']); self.assertIn('lacks complete total_token_usage',row['unknown']['cache_read'])

    def test_copied_sidechain_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); line={'type':'assistant','isSidechain':True,'timestamp':'2026-01-01T00:00:00Z','message':{'id':'side-1','model':'synthetic','usage':{'input_tokens':10,'output_tokens':2,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
            for name in ('a.jsonl','b.jsonl'): (root/name).write_text(json.dumps(line)+'\n')
            m=root/'manifest.json';m.write_text(json.dumps({'schema_version':1,'sources':[{'file':n,'format':'claude-jsonl','role':'parent'} for n in ('a.jsonl','b.jsonl')]}))
            summary=usage.summarise(m)
            self.assertEqual(summary['sidechain']['inferences'],1)
            self.assertTrue(any(g['kind']=='duplicate_sidechain_across_sources' for g in summary['gaps']))

    def test_r15_be_01_replayed_subsequence_never_reproves_a_copied_row(self):
        """R15-BE-01: A,B,A,B keeps only the unique rows as a floor, never the copied suffix."""
        snap=self.snap
        # A zero start and its one-step extension, each replayed byte-identically at the end.
        a=snap(100,10,1,last=(100,10));b=snap(200,20,2,last=(100,10))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=self.codex_summary(root,{'s.jsonl':[self.META,a,b,a,b]})
            parent=result['parent']
            # The copied A is rejected, so the copied B can no longer be proven from it.
            self.assertIsNone(parent['totals']['input']);self.assertIsNone(parent['totals']['output'])
            self.assertIsNone(parent['totals']['context']);self.assertIsNone(parent['peak_context'])
            self.assertEqual(parent['totals']['known_lower_bound']['input'],200)
            self.assertEqual(parent['totals']['known_lower_bound']['output'],20)
            self.assertEqual(parent['known_max_context'],100)
            self.assertIn('counter_decreased',{g['kind'] for g in result['gaps']})
            self.assertFalse(result['aggregate']['attribution_complete'])
            self.assertEqual(nulls_without_reason(result),[])
            # A recurrence after a usage-less interval cannot re-prove a later row either.
            c=snap(300,30,4,last=(200,20))
            empty={'type':'event_msg','timestamp':'2026-01-01T00:00:03Z','payload':{'type':'token_count','info':None}}
            result=self.codex_summary(root,{'s.jsonl':[self.META,a,b,a,empty,c]})
            parent=result['parent']
            self.assertIsNone(parent['totals']['input'])
            self.assertLessEqual(parent['totals']['known_lower_bound']['input'],200)
            self.assertFalse(result['aggregate']['attribution_complete'])
            self.assertEqual(nulls_without_reason(result),[])

    def test_r15_be_01_replay_sweep_keeps_the_floor_at_or_below_the_unique_rows(self):
        """R15-BE-01 sweep: no replay shape republishes a copied row above the true usage."""
        snap=self.snap
        a=snap(100,10,1,last=(100,10));b=snap(200,20,2,last=(100,10))
        def optional(i,o): return {'total_tokens':i+o,'reasoning_output_tokens':0}
        def event(second,ident,inp,out,last):
            info={'id':ident,'total_token_usage':{'input_tokens':inp,'cached_input_tokens':0,'output_tokens':out},
                  'last_token_usage':{'input_tokens':last[0],'cached_input_tokens':0,'output_tokens':last[1]}}
            return {'type':'event_msg','timestamp':f'2026-01-01T00:00:0{second}Z','payload':{'type':'token_count','info':info}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            variants={'optional counter on the copies':[self.META,snap(100,10,1,optional(100,10),last=(100,10)),
                                                        snap(200,20,2,optional(200,20),last=(100,10)),
                                                        snap(100,10,1,optional(100,10),last=(100,10)),
                                                        snap(200,20,2,optional(200,20),last=(100,10))],
                      'event IDs on the copied suffix':[self.META,event(1,'e1',100,10,(100,10)),event(2,'e2',200,20,(100,10)),
                                                        event(1,'e1',100,10,(100,10)),event(2,'e2',200,20,(100,10))],
                      'three-deep replay':[self.META,a,b,a,b,a,b]}
            for label,rows in variants.items():
                result=self.codex_summary(root,{'s.jsonl':rows})
                parent=result['parent']
                self.assertIsNone(parent['totals']['input'],label)
                self.assertLessEqual(parent['totals']['known_lower_bound']['input'],200,label)
                self.assertLessEqual(parent['totals']['known_lower_bound']['output'],20,label)
                self.assertLessEqual(parent['known_max_context'] or 0,100,label)
                self.assertFalse(result['aggregate']['attribution_complete'],label)
                self.assertEqual(nulls_without_reason(result),[],label)

    def test_r15_be_02_resumed_empty_tail_after_usage_is_unknown(self):
        """R15-BE-02: a resumed-only usage-less token_count after usage hides the earlier totals."""
        snap=self.snap
        meta=self.META
        bounds=[{'stage':'s0','at':'2026-01-01T00:00:05Z'}]
        a,b=snap(100,10,1,last=(100,10)),snap(200,20,2,last=(100,10))
        empty={'type':'event_msg','timestamp':'2026-01-01T00:00:03Z','payload':{'type':'token_count','info':None}}
        def summarise(root,head,resumed):
            (root/'full.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in [meta,a,b]))
            (root/'head.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in [meta]+([head] if head else [])))
            sources=[{'file':'full.jsonl','format':'codex-rollout','role':'parent'},
                     {'file':'head.jsonl','format':'codex-rollout','role':'parent',**({'resumed':True} if resumed else {})}]
            (root/'manifest.json').write_text(json.dumps({'schema_version':1,'sources':sources,'boundaries':bounds}))
            return usage.summarise(root/'manifest.json')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # A later or unorderable empty interval leaves the session totals, peak and boundary unknown.
            for head in (empty, {'type':'event_msg','payload':{'type':'token_count','info':None}},
                         {'type':'event_msg','timestamp':'2026-01-01T00:00:03','payload':{'type':'token_count','info':None}}):
                result=summarise(root,head,True);parent=result['parent']
                self.assertIsNone(parent['totals']['input'],head)
                self.assertIsNone(parent['totals']['output'],head)
                self.assertIsNone(parent['peak_context'],head)
                self.assertEqual([(x['inference'],x['context']) for x in parent['stage_boundary_context']],[(None,None)],head)
                self.assertIn('token_count_without_usage',{g['kind'] for g in result['gaps']},head)
                self.assertFalse(result['aggregate']['attribution_complete'],head)
                self.assertLessEqual(parent['totals']['known_lower_bound']['input'],200,head)
                self.assertEqual(nulls_without_reason(result),[],head)
            # An empty report that provably precedes every usage report claims nothing, resumed or not.
            before={'type':'event_msg','timestamp':'2026-01-01T00:00:00Z','payload':{'type':'token_count','info':None}}
            for resumed in (True,False):
                for order in (('full.jsonl','head.jsonl'),('head.jsonl','full.jsonl')):
                    root=Path(tmp)
                    (root/'full.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in [meta,a,b]))
                    (root/'head.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in [meta,before]))
                    sources=[{'file':f,'format':'codex-rollout','role':'parent'} for f in order]
                    for spec in sources:
                        if spec['file']=='head.jsonl' and resumed: spec['resumed']=True
                    (root/'manifest.json').write_text(json.dumps({'schema_version':1,'sources':sources,'boundaries':bounds}))
                    result=usage.summarise(root/'manifest.json');parent=result['parent']
                    self.assertEqual((parent['totals']['input'],parent['totals']['output']),(200,20),(resumed,order))
                    self.assertEqual(parent['peak_context'],100,(resumed,order))
                    self.assertTrue(result['aggregate']['attribution_complete'],(resumed,order))
                    self.assertEqual(nulls_without_reason(result),[],(resumed,order))

    def test_r16_be_01_same_capture_model_conflict_matches_split_capture(self):
        """R16-BE-01: one identity naming two models is a conflict whether its copies share a capture or not."""
        def line(model, output=10, side=False, ident='same-message'):
            message = {'id': ident, 'usage': {'input_tokens': 100, 'output_tokens': output,
                                              'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}
            if model is not None:
                message['model'] = model
            item = {'type': 'assistant', 'timestamp': '2026-01-01T00:00:00Z', 'message': message}
            if side:
                item['isSidechain'] = True
            return json.dumps(item) + '\n'
        def run(files):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, lines in files:
                    (root / name).write_text(''.join(lines))
                (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'sources': [
                    {'file': name, 'format': 'claude-jsonl', 'role': 'parent'} for name, _ in files]}))
                return usage.summarise(root / 'manifest.json')
        def layouts(lines):
            yield 'same', run([('one.jsonl', lines)])
            yield 'split', run([(f'part{i}.jsonl', [x]) for i, x in enumerate(lines)])
            yield 'reversed', run([(f'part{i}.jsonl', [x]) for i, x in reversed(list(enumerate(lines)))])
        conflicting = {('model-a', 'model-b'): 1, ('model-a', None): 1, (None, 'model-a'): 1,
                       ('model-a', 'model-a', 'model-b'): 1, ('model-a', 'model-b', 'model-a'): 1,
                       ('model-a', 'model-b', 'model-b'): 2, ('model-a', None, 'model-b'): 2}
        for models, count in conflicting.items():
            for layout, result in layouts([line(m) for m in models]):
                label = (models, layout)
                aggregate = result['aggregate']
                self.assertFalse(aggregate['attribution_complete'], label)
                self.assertEqual(result['parent']['totals']['inferences'], 1, label)
                self.assertEqual(result['parent']['totals']['output'], 10, label)
                self.assertTrue(aggregate['usage_conflicts'], label)
                self.assertTrue(all(c['fields'] == ['model'] and c['inference'] == 'same-message'
                                    for c in aggregate['usage_conflicts']), label)
                self.assertIn('usage_conflict', {g['kind'] for g in result['gaps']}, label)
                self.assertEqual(nulls_without_reason(result), [], label)
                if layout != 'reversed':  # copies are compared with the first-counted one
                    self.assertEqual(len(aggregate['usage_conflicts']), count, label)
                if layout == 'same':
                    self.assertEqual(aggregate['usage_conflicts'][0]['source'], 'one.jsonl', label)
                    self.assertEqual(aggregate['usage_conflicts'][0]['first_source'], 'one.jsonl', label)
                    self.assertEqual(result['parent']['inferences'][0]['model'], models[0] or 'unknown', label)
        # Agreeing copies, partial usage and synthetic lines stay complete in every layout.
        agreeing = ([line('model-a'), line('model-a')], [line(None), line(None)],
                    [line('model-a', output=1), line('model-a', output=10)],
                    [line('model-a'), line('<synthetic>')])
        for lines in agreeing:
            for layout, result in layouts(lines):
                label = (lines, layout)
                self.assertTrue(result['aggregate']['attribution_complete'], label)
                self.assertEqual(result['aggregate']['usage_conflicts'], [], label)
                self.assertNotIn('usage_conflict', {g['kind'] for g in result['gaps']}, label)
                self.assertEqual((result['parent']['totals']['inferences'], result['parent']['totals']['output']),
                                 (1, 10), label)
        # Sidechain copies use the same comparison; agreeing sidechain copies report no conflict.
        for models, conflicts in ((('model-a', 'model-b'), 1), (('model-a', 'model-a'), 0)):
            for layout, result in layouts([line(m, side=True) for m in models]):
                label = (models, layout)
                self.assertFalse(result['aggregate']['attribution_complete'], label)
                self.assertEqual(result['sidechain']['inferences'], 1, label)
                self.assertEqual(len(result['aggregate']['usage_conflicts']), conflicts, label)
        # A distinct identity is never merged by heuristics, even with equal usage and timestamp.
        result = run([('one.jsonl', [line('model-a'), line('model-b', ident='other-message')])])
        self.assertTrue(result['aggregate']['attribution_complete'])
        self.assertEqual(result['parent']['totals']['inferences'], 2)
        self.assertEqual(result['aggregate']['usage_conflicts'], [])

    def test_r19_be_01_codex_same_capture_model_conflict_matches_split_capture(self):
        """R19-BE-01: a repeated Codex snapshot naming two models is a conflict however it is packaged."""
        usage_counts = {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 10}
        def meta(model):
            return {'type': 'session_meta', 'payload': {'id': 'S', **({'model': model} if model else {})}}
        def turn(model):
            return {'type': 'turn_context', 'payload': {**({'model': model} if model else {})}}
        def count(total=usage_counts, event=None):
            info = {'total_token_usage': dict(total), 'last_token_usage': dict(usage_counts)}
            return {'type': 'event_msg', 'timestamp': '2026-01-01T00:00:01Z',
                    **({'id': event} if event else {}), 'payload': {'type': 'token_count', 'info': info}}
        def run(files):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, records in files:
                    (root / name).write_text(''.join(json.dumps(r) + '\n' for r in records))
                (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'sources': [
                    {'file': name, 'format': 'codex-rollout', 'role': 'parent'} for name, _ in files]}))
                return usage.summarise(root / 'manifest.json')
        def layouts(models, event=None):
            same = [meta(models[0]), count(event=event)]
            for model in models[1:]:
                same += [turn(model), count(event=event)]
            parts = [(f'part{i}.jsonl', [meta(m), count(event=event)]) for i, m in enumerate(models)]
            yield 'same', run([('one.jsonl', same)])
            yield 'split', run(parts)
            yield 'reversed', run(list(reversed(parts)))
        def check_usage(result, label):
            totals = result['parent']['totals']
            self.assertEqual((totals['inferences'], totals['input'], totals['output']), (1, 100, 10), label)
            self.assertEqual(result['parent']['peak_context'], 100, label)
            self.assertEqual(nulls_without_reason(result), [], label)
        conflicting = {('model-a', 'model-b'): 1, ('model-b', 'model-a'): 1, (None, 'model-a'): 1,
                       ('model-a', 'model-a', 'model-b'): 1, ('model-a', 'model-b', 'model-a'): 1,
                       ('model-a', 'model-b', 'model-b'): 2, (None, 'model-a', 'model-b'): 2}
        for event in (None, 'call-1'):
            for models, number in conflicting.items():
                for layout, result in layouts(models, event):
                    label = (models, event, layout)
                    aggregate = result['aggregate']
                    self.assertFalse(aggregate['attribution_complete'], label)
                    self.assertTrue(aggregate['usage_conflicts'], label)
                    self.assertTrue(all(c['fields'] == ['model'] for c in aggregate['usage_conflicts']), label)
                    self.assertIn('usage_conflict', {g['kind'] for g in result['gaps']}, label)
                    check_usage(result, label)
                    if layout != 'reversed':  # copies are compared with the first-counted one
                        self.assertEqual(len(aggregate['usage_conflicts']), number, label)
                        self.assertEqual(result['parent']['inferences'][0]['model'], models[0] or 'unknown', label)
                    if layout == 'same':
                        self.assertEqual(result['sources'][0]['duplicates_collapsed'], len(models) - 1, label)
                        self.assertEqual({(c['source'], c['first_source']) for c in aggregate['usage_conflicts']},
                                         {('one.jsonl', 'one.jsonl')}, label)
            # Agreeing copies (missing models included) stay one complete inference in every layout.
            for models in (('model-a', 'model-a'), (None, None), ('model-a', 'model-a', 'model-a')):
                for layout, result in layouts(models, event):
                    label = (models, event, layout)
                    self.assertTrue(result['aggregate']['attribution_complete'], label)
                    self.assertEqual(result['aggregate']['usage_conflicts'], [], label)
                    self.assertNotIn('usage_conflict', {g['kind'] for g in result['gaps']}, label)
                    check_usage(result, label)
        # A turn_context without a model keeps the session's model: no conflict is invented.
        result = run([('one.jsonl', [meta('model-a'), count(), turn(None), count()])])
        self.assertTrue(result['aggregate']['attribution_complete'])
        self.assertEqual(result['aggregate']['usage_conflicts'], [])
        check_usage(result, 'model-less turn_context')
        # A new snapshot after a model switch is a new call by the new model, not a conflict.
        second = count({'input_tokens': 200, 'cached_input_tokens': 0, 'output_tokens': 20})
        result = run([('one.jsonl', [meta('model-a'), count(), turn('model-b'), second])])
        self.assertTrue(result['aggregate']['attribution_complete'])
        self.assertEqual(result['aggregate']['usage_conflicts'], [])
        self.assertEqual([row['model'] for row in result['parent']['inferences']], ['model-a', 'model-b'])
        self.assertEqual((result['parent']['totals']['input'], result['parent']['totals']['output']), (200, 20))

    def test_r21_benchmark_shard_2_01_codex_model_never_crosses_a_session_boundary(self):
        """R21-benchmark-shard-2-01: a new session without model evidence does not inherit another session's model."""
        usage_counts = {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 10}
        stamps = {'S1': '2026-01-01T00:00:01+00:00', 'S2': '2026-01-01T00:00:02+00:00', 'S3': '2026-01-01T00:00:03+00:00'}
        def meta(session, model=None):
            return {'type': 'session_meta', 'payload': {'id': session, **({'model': model} if model else {})}}
        def turn(model=None):
            return {'type': 'turn_context', 'payload': {**({'model': model} if model else {})}}
        def count(session, total=usage_counts):
            info = {'total_token_usage': dict(total), 'last_token_usage': dict(usage_counts)}
            return {'type': 'event_msg', 'timestamp': stamps[session], 'payload': {'type': 'token_count', 'info': info}}
        def run(files):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, records in files:
                    (root / name).write_text(''.join(json.dumps(r) + '\n' for r in records))
                (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'sources': [
                    {'file': name, 'format': 'codex-rollout', 'role': 'parent'} for name, _ in files]}))
                return usage.summarise(root / 'manifest.json')
        def layouts(parts):
            yield 'same', run([('one.jsonl', [record for part in parts for record in part])])
            named = [(f'part{i}.jsonl', part) for i, part in enumerate(parts)]
            yield 'split', run(named)
            yield 'reversed', run(list(reversed(named)))
        def models(result):
            return {row['id'].split(':')[0]: row['model'] for row in result['parent']['inferences']}
        def check_usage(result, label, inferences):
            totals = result['parent']['totals']
            self.assertEqual((totals['inferences'], totals['input'], totals['output']), (inferences, 100 * inferences, 10 * inferences), label)
            self.assertEqual(nulls_without_reason(result), [], label)
        # The reported case: S2 first has no model, then a known copy. Every packaging reports the same conflict.
        for layout, result in layouts([[meta('S1', 'model-a'), count('S1')], [meta('S2'), count('S2')],
                                       [meta('S2', 'model-a'), count('S2')]]):
            aggregate = result['aggregate']
            self.assertFalse(aggregate['attribution_complete'], layout)
            self.assertEqual(len(aggregate['usage_conflicts']), 1, layout)
            self.assertTrue(all(c['fields'] == ['model'] for c in aggregate['usage_conflicts']), layout)
            check_usage(result, layout, 2)
            if layout != 'reversed':  # copies are compared with the first-counted one
                self.assertEqual(models(result), {'S1': 'model-a', 'S2': 'unknown'}, layout)
        # A model-less new session after a different session stays unknown in every packaging, including
        # after repeated transitions, and a later session's model never flows back to an earlier one.
        sequences = (
            [[meta('S1', 'model-a'), count('S1')], [meta('S2'), count('S2')]],
            [[meta('S1', 'model-a'), count('S1')], [meta('S2', 'model-b'), count('S2')], [meta('S3'), count('S3')]],
            [[meta('S1'), turn('model-a'), count('S1')], [meta('S2'), turn(), count('S2')]],
        )
        for parts in sequences:
            for layout, result in layouts(parts):
                label = (len(parts), layout)
                self.assertTrue(result['aggregate']['attribution_complete'], label)
                self.assertEqual(result['aggregate']['usage_conflicts'], [], label)
                self.assertEqual(models(result)[f'S{len(parts)}'], 'unknown', label)
                self.assertEqual(models(result)['S1'], 'model-a', label)
                check_usage(result, label, len(parts))
        # Explicit agreeing and differing per-session models are complete and conflict-free.
        for second in ('model-a', 'model-b'):
            for layout, result in layouts([[meta('S1', 'model-a'), count('S1')], [meta('S2', second), count('S2')],
                                           [meta('S2', second), count('S2')]]):
                self.assertTrue(result['aggregate']['attribution_complete'], (second, layout))
                self.assertEqual(result['aggregate']['usage_conflicts'], [], (second, layout))
                self.assertEqual(models(result), {'S1': 'model-a', 'S2': second}, (second, layout))
                check_usage(result, (second, layout), 2)
        # Absent initial metadata: model evidence before the first session does not name that session.
        result = run([('one.jsonl', [turn('model-a'), meta('S1'), count('S1')])])
        self.assertEqual(models(result), {'S1': 'unknown'})
        # Same-session evidence stays sticky: a model-less turn_context or repeated session_meta keeps
        # the session's model, and returning to a session uses only that session's own evidence.
        later = {'input_tokens': 200, 'cached_input_tokens': 0, 'output_tokens': 20}
        same = [meta('S1', 'model-a'), count('S1'), turn(), meta('S1'), count('S1', later)]
        result = run([('one.jsonl', same)])
        self.assertEqual([row['model'] for row in result['parent']['inferences']], ['model-a', 'model-a'])
        self.assertTrue(result['aggregate']['attribution_complete'])
        back = [meta('S1', 'model-a'), count('S1'), meta('S2', 'model-b'), count('S2'), meta('S1'), count('S1', later)]
        result = run([('one.jsonl', back)])
        self.assertEqual({row['id']: row['model'] for row in result['parent']['inferences']},
                         {'S1:cumulative-100-0-10': 'model-a', 'S2:cumulative-100-0-10': 'model-b',
                          'S1:cumulative-200-0-20': 'model-a'})
        self.assertEqual(result['aggregate']['usage_conflicts'], [])

    def test_r22_benchmark_shard_2_01_source_hash_names_the_bytes_parsed(self):
        """R22-benchmark-shard-2-01: a capture changed after parsing is never hashed as the parsed source."""
        def claude(ident, second, tokens):
            return {'type': 'assistant', 'timestamp': f'2026-01-01T00:00:0{second}Z', 'message': {
                'id': ident, 'model': 'model-a', 'usage': {'input_tokens': tokens, 'output_tokens': 10,
                                                            'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}}
        def codex(second, total, last):
            names = ('input_tokens', 'cached_input_tokens', 'output_tokens')
            return {'type': 'event_msg', 'timestamp': f'2026-01-01T00:00:0{second}Z', 'payload': {'type': 'token_count', 'info': {
                'total_token_usage': dict(zip(names, total)), 'last_token_usage': dict(zip(names, last))}}}
        def lines(*records):
            return b''.join(json.dumps(r).encode() + b'\n' for r in records)
        meta = {'type': 'session_meta', 'payload': {'id': 'S', 'model': 'model-a'}}
        # V0 holds one inference (input 100); V1 appends a second (input 9999), as an ongoing capture would.
        formats = {'claude-jsonl': (lines(claude('m1', 1, 100)), lines(claude('m2', 2, 9999))),
                   'codex-rollout': (lines(meta, codex(1, (100, 0, 10), (100, 0, 10))),
                                     lines(codex(2, (10099, 0, 20), (9999, 0, 10))))}
        damaged = b'{not json\n\xff\xfe\n'

        def write(root, files, form):
            for name, data in files.items():
                (root / name).write_bytes(data)
            (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'sources': [
                {'file': name, 'format': form, 'role': 'parent'} for name in files],
                'boundaries': [{'stage': 's1', 'at': '2026-01-01T00:00:05Z'}]}))

        def stable(files, form):
            with tempfile.TemporaryDirectory() as tmp:
                write(Path(tmp), files, form)
                return usage.summarise(Path(tmp) / 'manifest.json')

        def changed_after_parse(files, form, target, change):
            """Summarise while ``change`` rewrites ``target`` right after its parse returns."""
            def hook(original):
                def parse(path, *args, **kwargs):
                    result = original(path, *args, **kwargs)
                    if Path(path).name == target:
                        change(Path(path))
                    return result
                return parse
            with tempfile.TemporaryDirectory() as tmp:
                write(Path(tmp), files, form)
                with patch.object(usage, 'parse_claude', hook(usage.parse_claude)), \
                        patch.object(usage, 'parse_codex', hook(usage.parse_codex)):
                    result = usage.summarise(Path(tmp) / 'manifest.json')
                return result, (Path(tmp) / target).read_bytes()

        def append(extra):
            def change(path):
                with open(path, 'ab') as handle:
                    handle.write(extra)
            return change

        def replace(data):
            def change(path):
                fresh = path.with_name(path.name + '.new')
                fresh.write_bytes(data)
                fresh.replace(path)
            return change

        def facts(result):
            parent = result['parent']
            return (parent['totals']['inferences'], parent['totals']['input'], parent['peak_context'],
                    parent['stage_boundary_context'][0]['context'], result['aggregate']['attribution_complete'])

        sha = lambda data: hashlib.sha256(data).hexdigest()
        for form, (v0, tail) in formats.items():
            v1 = v0 + tail
            # Stable controls: each byte string, read once, is described by its own totals and hash.
            one, two = stable({'parent.jsonl': v0}, form), stable({'parent.jsonl': v1}, form)
            self.assertEqual(facts(one), (1, 100, 100, 100, True), form)
            self.assertEqual(facts(two), (2, 10099, 9999, 9999, True), form)
            self.assertEqual((one['sources'][0]['sha256'], two['sources'][0]['sha256']), (sha(v0), sha(v1)), form)
            self.assertEqual(nulls_without_reason(two), [], form)
            cases = {'append': ({'parent.jsonl': v0}, 'parent.jsonl', append(tail), v1),
                     'replace': ({'parent.jsonl': v0}, 'parent.jsonl', replace(v1), v1),
                     # Raw-byte damage accounting: undecodable and unparseable lines stay in the parsed hash.
                     'damaged-append': ({'parent.jsonl': v0 + damaged}, 'parent.jsonl', append(tail), v0 + damaged + tail),
                     # A copied capture extended after its parse: dedupe still sees only the parsed copy.
                     'copy-append': ({'parent.jsonl': v0, 'resumed.jsonl': v0}, 'resumed.jsonl', append(tail), v1),
                     'first-replace': ({'parent.jsonl': v0, 'resumed.jsonl': v0}, 'parent.jsonl', replace(v1), v1)}
            for label, (files, target, change, after) in cases.items():
                with self.subTest(form=form, case=label):
                    result, current = changed_after_parse(files, form, target, change)
                    self.assertEqual(current, after)  # the change really landed before the summary was built
                    by_file = {s['file']: s['sha256'] for s in result['sources']}
                    self.assertEqual(by_file[target], sha(files[target]))
                    self.assertNotEqual(by_file[target], sha(current))
                    # Every published field is exactly what a stable read of the parsed bytes gives.
                    self.assertEqual(result, stable(files, form))
            # Damaged-line control: an unparseable line and an undecodable one (also unparseable) give three
            # damage gaps and leave totals, peak and boundary unknown, never zero.
            damaged_result = stable({'parent.jsonl': v0 + damaged}, form)
            self.assertEqual(damaged_result['sources'][0]['damaged_lines'], 3, form)
            self.assertEqual(facts(damaged_result)[1:], (None, None, None, False), form)
            self.assertEqual(nulls_without_reason(damaged_result), [], form)
        # Public parsers keep their two-argument form; the optional digest sees exactly the bytes read.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'parent.jsonl'
            path.write_bytes(formats['claude-jsonl'][0] + damaged)
            plain_gaps, read, read_gaps = [], hashlib.sha256(), []
            plain = usage.parse_claude(path, plain_gaps)
            self.assertEqual((usage.parse_claude(path, read_gaps, read), read_gaps), (plain, plain_gaps))
            self.assertEqual(read.hexdigest(), sha(path.read_bytes()))


if __name__ == '__main__':
    unittest.main()
