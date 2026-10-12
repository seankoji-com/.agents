"""bench-v2 (issue #28): frozen five-stage fixture, hidden checks, start plan and usage parser.

Everything runs offline against synthetic data. The hidden checker executes fixture
code only inside temporary copies.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / 'bench' / 'v2'
FIXTURE = V2 / 'fixtures' / 'five_stage' / 'workspace'
REFERENCE = V2 / 'checks' / 'reference'
PARSER_FIXTURES = V2 / 'tools' / 'fixtures'
sys.path.insert(0, str(V2 / 'tools'))
sys.path.insert(0, str(V2 / 'checks'))

import five_stage  # noqa: E402
import prepare_workspace  # noqa: E402
import usage  # noqa: E402
import model_policy  # noqa: E402

REQUIRED = {f'C{n}' for n in range(1, 14)}


def frozen_files():
    for path in sorted(V2.rglob('*')):
        rel = path.relative_to(V2)
        if path.is_file() and rel.parts[0] != 'runs' and rel.as_posix() != 'frozen.json' \
                and '__pycache__' not in rel.parts:
            yield rel.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


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


def failed(results) -> set:
    return {r['id'].split('-')[0] for r in results if r['required'] and not r['passed']}


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
            model_policy.validate_target(self.catalog, self.luna)

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


class FrozenTest(unittest.TestCase):
    def test_frozen_files_match_their_recorded_digests(self):
        recorded = json.loads((V2 / 'frozen.json').read_text())['files']
        self.assertEqual(dict(frozen_files()), recorded,
                         'a frozen bench-v2 file changed: amend bench/v2/protocol.md before the next start')

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


class HiddenCheckTest(unittest.TestCase):
    def run_checks(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp), **kwargs)
            before = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
            results = five_stage.check(target)
            after = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(before, after, 'the checker must not write the evaluated tree')
            return results

    def test_reference_solution_passes_every_required_check(self):
        self.assertEqual(failed(self.run_checks()), set())

    def test_untouched_fixture_fails_every_stage_requirement(self):
        self.assertEqual(failed(self.run_checks(overlay=False)), REQUIRED - {'C8', 'C9'})

    def test_float_rounding_fix_still_accepts_exponents(self):
        results = self.run_checks(edits={'ledger/model.py': (
            "    match = AMOUNT.fullmatch(text or '')",
            "    return round(float(text) * 100)\n    match = AMOUNT.fullmatch(text or '')")})
        self.assertEqual(failed(results), {'C3', 'C8'})  # the reference's own tests also catch it

    def test_escaping_negative_amounts_is_rejected(self):
        results = self.run_checks(edits={'ledger/io.py': ('format_cents(entry.cents)])',
                                                          'neutralise(format_cents(entry.cents))])')})
        self.assertEqual(failed(results), {'C6', 'C8'})

    def test_same_file_check_by_spelling_only_is_rejected(self):
        results = self.run_checks(edits={'ledger/cli.py': (
            'os.path.exists(args.out) and os.path.samefile(args.file, args.out)', 'args.file == args.out')})
        self.assertEqual(failed(results), {'C7'})

    def test_missing_notes_fail_only_their_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = workspace(Path(tmp))
            (target / 'notes' / 'review.md').unlink()
            (target / 'notes' / 'investigation.md').write_text('Cause: float truncation at ledger/model.py:3\n')
            self.assertEqual(failed(five_stage.check(target)), {'C1', 'C13'})


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
        self.assertIn({'source': 'parent_resumed.jsonl', 'kind': 'duplicate_across_sources', 'detail': 'msg_p2'},
                      self.summary['gaps'])

    def test_missing_cache_value_is_unknown_not_zero(self):
        parent = self.summary['parent']
        self.assertIsNone(parent['totals']['cache_read'])
        self.assertIsNone(parent['totals']['context'])
        self.assertIsNone(parent['peak_context'])
        self.assertEqual(parent['known_max_context'], 3723)
        self.assertIn('lower bound', parent['peak_reason'])
        self.assertEqual(parent['totals']['known_lower_bound']['cache_read'], 17200)
        self.assertEqual((parent['totals']['input'], parent['totals']['output']), (30, 189))

    def test_stage_boundaries_use_the_last_parent_inference_before_them(self):
        bounds = {b['stage']: b for b in self.summary['parent']['stage_boundary_context']}
        self.assertEqual(bounds['s1']['context'], 3503)
        self.assertEqual(bounds['s1']['inference'], 'req_p3')
        self.assertIsNone(bounds['s2']['context'])
        self.assertEqual(bounds['s2']['reason'], 'needs cache_read')
        self.assertEqual(bounds['s3']['context'], 3612)
        self.assertEqual(bounds['s0']['reason'], 'no parent inference before boundary')

    def test_codex_per_call_and_cumulative_counters(self):
        per_call = self.workers['task-s1-investigator']['totals']
        self.assertEqual((per_call['input'], per_call['cache_read'], per_call['output'], per_call['context']),
                         (2500, 900, 150, 2500))
        self.assertIsNone(per_call['cache_write'])
        cumulative = self.workers['task-s2-executor']
        self.assertEqual(cumulative['totals']['inferences'], 4)
        self.assertIsNone(cumulative['totals']['input'])
        self.assertEqual(cumulative['totals']['known_lower_bound']['input'], 2800)
        kinds = [g['kind'] for g in self.summary['gaps'] if g['source'] == 'worker_codex_cumulative.jsonl']
        self.assertIn('counter_decreased', kinds)
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
        self.assertEqual(attributed['known_lower_bound']['input'], 5356)

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

    def test_fixtures_are_synthetic(self):
        for path in PARSER_FIXTURES.iterdir():
            text = path.read_text()
            self.assertNotRegex(text, r'/(home|Users|tmp|var|private)/', path.name)
            self.assertNotRegex(text, r'(?i)(api[_-]?key|token["\']?\s*[:=]\s*["\'][A-Za-z0-9]{16,}|\.internal\b)',
                                path.name)
            self.assertNotRegex(text, r'(?i)\b(claude|gpt|opus|sonnet)-[0-9]', path.name)


if __name__ == '__main__':
    unittest.main()
