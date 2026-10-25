"""Behavioral regressions for the late issue-95 evidence findings."""
from copy import deepcopy
from datetime import datetime, timezone
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import test_tests_omg as base

omg, helper = base.omg, base.helper


def judgment(i, state='gap'):
    return {'id': f'TEST-{i:02}', 'state': state, 'reason': f'Independent inspected observation {i}',
            'evidence': ['inspection'], 'confidence': 'high', 'consequence': 'Material failure',
            'owner': 'fixture owner', 'next_action': 'Repair the named failure'}


def passing_checks(data):
    data.update(expected_checks=['unit:0'], assurance_set_complete=True,
                checks=[{'check': 'unit', 'shard': '0', 'attempt': 1, 'outcome': 'pass',
                         'discovered': 9, 'report_complete': True}])


def admission(data):
    from shared import model_selection
    from upfront_fixtures import chosen
    selected = chosen('tests-omg/audit')
    data['selection_context'] = {'record': selected, 'selection_sha256': selected['selection_sha256'],
        'invocation_id': selected['invocation_id'], 'scope_id': selected['scope_id']}
    return data


def measured_group():
    return {**base.group('simplify'),
        'rationale': 'Measured corpus detection is 80% with 20% of the runtime; no future safety claim.',
        'measurement': {'scope': 'named historical corpus', 'evidence': ['inspection'],
                        'detected': 4, 'total': 5, 'runtime_ratio': .2},
        'protection_lost': ['obsolete-platform'],
        'tradeoff': {'state': 'accepted', 'owner': 'platform owner',
                     'reason': 'Platform retired; retain ledger recovery.', 'evidence': ['inspection']}}


def malformed_recommendations():
    for field in ('measurement', 'tradeoff'):
        for value in ('claimed' if field == 'measurement' else 'accepted', None, False, 0, '', [], [1], {}):
            row = measured_group()
            row[field] = value
            yield field, value, row
        fields = {'evidence': ('inspection', [], [1], [[]], ['missing']),
                  **({'scope': (False, 1, [], {}, ' '), 'detected': (True, '4', [], -1, 6),
                      'total': (False, '5', {}, 0), 'runtime_ratio': (True, '.2', [], -1)}
                     if field == 'measurement' else
                     {'state': (False, [], {}, 'approved'), 'owner': (True, 1, [], {}, ' '),
                      'reason': (True, 1, [], {}, ' ')})}
        for nested, values in fields.items():
            for value in values:
                row = measured_group()
                row[field][nested] = value
                yield field, {nested: value}, row
    for field in ('protection_retained', 'protection_lost'):
        for value in (None, False, 0, '', 'case', {}, [1], [None], [[]], [{}], ['case', False]):
            row = measured_group()
            row[field] = value
            yield field, value, row


class LateEvidenceTests(unittest.TestCase):
    def test_followup_malformed_recommendation_shapes_are_validation_errors(self):
        for field, value, row in malformed_recommendations():
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    omg.recommendations([row], {'inspection': {}}, [])

    def test_followup_optional_claims_are_validated_even_without_value_prose_or_losses(self):
        for field in ('measurement', 'tradeoff'):
            for value in (False, 0, '', [], None, 'claimed', {}):
                with self.subTest(field=field, value=value):
                    row = {**base.group(), field: value}
                    with self.assertRaisesRegex(ValueError, field):
                        omg.recommendations([row], {'inspection': {}}, [])

    def test_followup_valid_measurements_tradeoffs_and_empty_lists_preserve_semantics(self):
        data, snap = base.fixture()
        row = measured_group()
        row['protection_retained'].append('<script>bad()</script>')
        data.update(groups=[row], inspected_groups=['restore'], findings=[judgment(5)])
        result = self.analyze(data, snap)
        rec = result['recommendations'][0]
        self.assertEqual(rec['action'], 'simplify')
        self.assertEqual(rec['measurement'], row['measurement'])
        self.assertEqual(rec['tradeoff'], row['tradeoff'])
        self.assertEqual(result['findings'][4]['state'], 'gap')
        row['tradeoff']['state'] = 'unaccepted'
        self.assertIsNone(self.analyze(data, snap)['recommendations'][0]['action'])
        row = {**base.group('delete'), 'basis': 'dead-feature',
               'protection_retained': [], 'protection_lost': []}
        self.assertEqual(omg.recommendations([row], {'inspection': {}}, [])[0]['action'], 'delete')
        row = {'id': 'uninspected', 'protection_retained': [], 'protection_lost': []}
        self.assertIsNone(omg.recommendations([row], {}, [])[0]['action'])

    def analyze(self, data, snap):
        return omg.analyze(data, snap, '2026-10-25T00:00:00+00:00')

    def test_late_all_twelve_observed_gaps_survive_success_and_uncertainty(self):
        for tools in (True, False):
            with self.subTest(tools=tools):
                data, snap = base.fixture()
                data['findings'] = [judgment(i) for i in range(1, 13)]
                data['runs'] = [base.run([base.node('unit', 300)])]
                passing_checks(data)
                data['coverage'] = {'counts': {}, 'revision': data['identity']['tested_sha']}
                if not tools:
                    del data['identity']['tool_versions']
                result = self.analyze(data, snap)
                for i, f in enumerate(result['findings'], 1):
                    with self.subTest(dimension=i):
                        self.assertEqual((f['state'], f['reason'], f['evidence']),
                                         ('gap', judgment(i)['reason'], ['inspection']), f['id'])
                self.assertEqual(result['validation_verdict'], 'incomplete')

    def test_supplement_authored_unknown_is_not_a_default_to_upgrade(self):
        data, snap = base.fixture()
        data['findings'] = [judgment(11, 'unknown')]
        result = self.analyze(data, snap)
        self.assertEqual(result['findings'][10]['state'], 'unknown')
        self.assertEqual(result['findings'][10]['reason'], judgment(11)['reason'])
        self.assertEqual(result['findings'][10]['evidence'], ['inspection'])

    def test_supplement_expired_logs_preserve_slow_runs_and_failed_attempts(self):
        for availability in ({'expires_at': '2000-01-01T00:00:00+00:00'}, {'available': False}):
            with self.subTest(availability=availability):
                data, snap = base.fixture()
                data['references'].append({'id': 'oldlog', 'source': 'original slow failed run',
                    'observed_at': '2000-01-01T00:00:00+00:00', **availability})
                slow = {**base.run([base.node('slow', 650)], observed=650), 'id': 'slow', 'evidence': ['oldlog']}
                fast = {**base.run([base.node('fast', 300)], observed=300), 'id': 'fast', 'evidence': ['inspection']}
                data['runs'] = [slow, fast]; passing_checks(data)
                data['checks'] = [{**data['checks'][0], 'outcome': 'fail', 'evidence': ['oldlog']},
                                  {**data['checks'][0], 'attempt': 2, 'evidence': ['inspection']}]
                result = self.analyze(data, snap)
                self.assertEqual([r['run_id'] for r in result['timing']['runs']], ['slow', 'fast'])
                self.assertEqual(result['findings'][1]['state'], 'gap')
                self.assertEqual(len(result['timing']['breaches']), 1)
                self.assertEqual(len(result['timing']['observed_breaches']), 1)
                self.assertFalse(result['timing']['runs'][0]['support_current'])
                self.assertEqual(result['counts']['failures'], 1)
                self.assertEqual(result['findings'][2]['state'], 'gap')
                self.assertFalse(result['evidence_current'])

    def test_late_computed_gaps_survive_later_uncertainty(self):
        data, snap = base.fixture()
        data['groups'] = [{**base.group('replace'), 'protection_lost': ['ledger-loss']}]
        data['inspected_groups'] = ['restore']
        data['comparisons'] = [{'group': 'restore', 'same_corpus': True, 'same_environment': True,
            'cases': [{'id': 'ledger-loss', 'risk': 'data-loss', 'existing': 'detected', 'candidate': 'missed'}]}]
        result = self.analyze(data, snap)
        self.assertEqual([result['findings'][i-1]['state'] for i in (5, 10)], ['gap', 'gap'])
        self.assertIsNone(result['recommendations'][0]['action'])

    def test_late_every_unsuccessful_attempt_then_pass_is_visible_and_not_clean(self):
        for outcome in ('fail', 'timed-out', 'runner-lost', 'setup-failed', 'cancelled', 'report-failed', 'unknown', 'skipped'):
            with self.subTest(outcome=outcome):
                data, snap = base.fixture()
                passing_checks(data)
                first = {**data['checks'][0], 'outcome': outcome, 'report_complete': False,
                         'tests': [{'id': 'date', 'outcome': outcome}]}
                last = {**data['checks'][0], 'attempt': 2, 'cause': 'infrastructure',
                        'tests': [{'id': 'date', 'outcome': 'pass'}]}
                data['checks'] = [first, last]
                result = self.analyze(data, snap)
                self.assertEqual(result['findings'][2]['state'], 'gap')
                self.assertEqual(result['intermittent'][0]['attempts'], [first, last])
                self.assertEqual(result['counts']['failures'], int(outcome != 'skipped'))
                self.assertEqual(result['counts']['retry_passes'], 1)
                self.assertEqual(len(result['per_test_attempts']), 2)
                self.assertEqual((result['findings'][11]['state'], result['validation_verdict']), ('gap', 'incomplete'))
                self.assertEqual(result['completed_checks'], ['unit:0'])
                # Actual repair evidence can resolve retry integrity, without
                # erasing either attempt or proving historical nondeterminism absent.
                last.update(disposition='fixed', repair_evidence=['inspection'])
                repaired = self.analyze(data, snap)
                self.assertEqual(repaired['validation_verdict'], 'complete')
                self.assertNotEqual(repaired['findings'][2]['state'], 'meets')

    def test_late_per_test_failure_cannot_hide_behind_a_passing_check_retry(self):
        data, snap = base.fixture(); passing_checks(data)
        first = {**data['checks'][0], 'tests': [{'id': 'contract', 'outcome': 'timed-out'}]}
        last = {**data['checks'][0], 'attempt': 2, 'tests': [{'id': 'contract', 'outcome': 'pass'}]}
        data['checks'] = [first, last]
        result = self.analyze(data, snap)
        self.assertEqual(result['findings'][2]['state'], 'gap')
        self.assertEqual(result['validation_verdict'], 'incomplete')

    def test_late_partial_inventory_preserves_bound_gaps_and_only_scoped_clean_claims(self):
        data, snap = base.fixture()
        snap.update(limitations=['Source bytes unavailable: asset.bin'], files={'readme': {'sha256': 'c'*64}})
        data['findings'] = [judgment(1), judgment(8, 'meets'),
                            {**judgment(7, 'meets'), 'source_paths': ['readme']}]
        passing_checks(data); data['checks'][0]['outcome'] = 'fail'
        data['runs'] = [base.run([base.node('unit', 650)])]
        data.update(groups=[base.group()], inspected_groups=['restore'])
        result = self.analyze(data, snap)
        self.assertEqual([result['findings'][i-1]['state'] for i in (1, 2, 3, 12)], ['gap']*4)
        self.assertEqual(result['findings'][0]['evidence'], ['inspection'])
        self.assertEqual(result['findings'][7]['state'], 'unknown')
        self.assertEqual(result['findings'][6]['state'], 'meets')
        self.assertFalse(result['evidence_current'])
        self.assertEqual(result['recommendations'][0]['assessment_state'], 'needs_evidence')
        self.assertIsNone(result['recommendations'][0]['action'])
        self.assertEqual(len(result['timing']['breaches']), 1)

    def test_late_workload_rationales_and_measured_percentages_are_allowed(self):
        for rationale in ('Protects background job retry idempotency.',
                'Keep: covers the nightly reconciliation job totals.',
                'Guards optional checks in the payment form.',
                'The pre-merge tests run the nightly reconciliation job on a disposable ledger.',
                'Keep: the only test that catches nightly settlement rounding errors in the ledger batch.',
                'Keep this check; it is the sole oracle for background job retry idempotency.',
                'Keep this check because it tests nightly ledger totals.',
                'Run before merge because it exercises the optional checks job contract.',
                'Measured corpus detection is 80% with 20% of the runtime; no future safety claim.'):
            with self.subTest(rationale=rationale):
                row = base.group(); row['rationale'] = rationale
                if rationale.startswith('Measured'):
                    row['measurement'] = {'evidence': ['inspection'], 'scope': 'named historical corpus',
                                          'detected': 4, 'total': 5, 'runtime_ratio': .2}
                self.assertEqual(omg.recommendations([row], {'inspection': {}}, [])[0]['action'], 'keep')
                if row.get('measurement'):
                    row['measurement']['detected'] = 2
                    with self.assertRaisesRegex(ValueError, '80/20'):
                        omg.recommendations([row], {'inspection': {}}, [])

    def test_late_deferral_and_unmeasured_value_bypasses_are_refused(self):
        for rationale in ('Run this suite after merge on main only.',
                'Move the e2e suite to a weekly cron workflow.',
                '80 per cent of the value for a fifth of the time.',
                'Most of the protection at 20% of the cost.',
                'Eighty percent of safety for twenty percent of time.'):
            with self.subTest(rationale=rationale):
                row = base.group(); row['rationale'] = rationale
                with self.assertRaisesRegex(ValueError, 'deferral|80/20'):
                    omg.recommendations([row], {'inspection': {}}, [])
        row = {**base.group(), 'execution_policy': 'after_merge'}
        with self.assertRaisesRegex(ValueError, 'pre-merge'):
            omg.recommendations([row], {'inspection': {}}, [])

    def test_late_simplification_tradeoffs_need_explicit_evidence_bound_acceptance(self):
        data, snap = base.fixture()
        row = {**base.group('simplify'), 'protection_lost': ['windows-path-quoting']}
        data.update(groups=[row], inspected_groups=['restore'], findings=[judgment(i, 'meets') for i in (5, 10)])
        result = self.analyze(data, snap)
        rec = result['recommendations'][0]
        self.assertIsNone(rec['action'])
        self.assertEqual(rec['assessment_state'], 'needs_evidence')
        for i in (5, 10):
            self.assertEqual(result['findings'][i-1]['state'], 'gap')
            self.assertNotIn('replacement', result['findings'][i-1]['reason'])
        row['tradeoff'] = {'state': 'accepted', 'owner': 'platform owner',
            'reason': 'Windows is no longer a supported target; retain Linux restore protection.', 'evidence': ['inspection']}
        result = self.analyze(data, snap)
        self.assertEqual(result['recommendations'][0]['action'], 'simplify')
        self.assertEqual([result['findings'][i-1]['state'] for i in (5, 10)], ['meets', 'meets'])
        data['findings'][0] = judgment(5)
        self.assertEqual(self.analyze(data, snap)['findings'][4]['state'], 'gap')

    def test_supplement_dead_feature_deletion_does_not_invent_replacement_gaps(self):
        data, snap = base.fixture()
        row = {**base.group('delete'), 'basis': 'dead-feature', 'protection_retained': [],
               'protection_lost': ['legacy export rendering']}
        data.update(groups=[row], inspected_groups=['restore'])
        result = self.analyze(data, snap)
        self.assertEqual(result['recommendations'][0]['action'], 'delete')
        for i in (5, 10):
            self.assertNotEqual(result['findings'][i-1]['state'], 'gap')

    def test_supplement_passing_sample_reason_is_clear_and_protection_lists_are_readable(self):
        data, snap = base.fixture(); passing_checks(data)
        result = self.analyze(data, snap)
        self.assertIn('does not establish', result['findings'][2]['reason'])
        row = base.group(); row['protection_retained'] = ['restore-ledger', '<script>bad()</script>']
        data.update(groups=[row], inspected_groups=['restore'])
        result = self.analyze(data, snap)
        audit = {'repository': 'fixture', 'snapshot': snap, 'run_id': 'fixture', 'generated_at': 'fixture',
                 'completion': 'complete', 'scope': {}, 'input': data, 'analysis': result,
                 'generator_version': helper.GENERATOR, 'benchmark_version': omg.VERSION, 'input_sha256': 'fixture'}
        html = base.html_report.render(audit)
        self.assertNotIn('Retained: [', html)
        self.assertIn('Retained: restore-ledger, &lt;script&gt;', html)
        self.assertNotIn('<script>', html)

    def test_late_expired_exceptions_limit_only_dependent_current_claims(self):
        data, snap = base.fixture()
        exception = {'owner': 'fixture owner', 'reason': 'Temporary compensating control',
                     'evidence': ['inspection'], 'expires_at': '2000-01-01T00:00:00+00:00'}
        data['findings'] = [{**judgment(3, 'meets'), 'exceptions': [exception]}, judgment(8, 'meets')]
        result = self.analyze(data, snap)
        self.assertEqual(result['findings'][2]['state'], 'unknown')
        self.assertEqual(result['findings'][2]['exceptions'], [exception])
        self.assertEqual(result['findings'][7]['state'], 'meets')
        self.assertTrue(any('exception' in s.lower() and 'expir' in s.lower() for s in result['limitations']))
        passing_checks(data)
        data['findings'][0] = {**judgment(12, 'meets'), 'exceptions': [exception]}
        self.assertNotEqual(self.analyze(data, snap)['validation_verdict'], 'complete')
        for expires in ('not-a-date', '2026-01-01T00:00:00'):
            exception['expires_at'] = expires
            with self.assertRaisesRegex(ValueError, 'timezone|expiry'):
                self.analyze(data, snap)
        exception.update(expires_at='2099-01-01T00:00:00+00:00', evidence=['compensation'])
        data['references'].append({'id': 'compensation', 'source': 'temporary control',
                                  'observed_at': '2026-10-25T00:00:00+00:00', 'available': False})
        result = self.analyze(data, snap)
        self.assertFalse(result['evidence_current'])
        self.assertNotEqual(result['validation_verdict'], 'complete')
        self.assertEqual(result['findings'][7]['state'], 'meets')


class LateCommandTests(unittest.TestCase):
    setUp = base.CommandTests.setUp
    git = base.CommandTests.git
    call = base.CommandTests.call
    input = base.CommandTests.input
    bound = base.CommandTests.bound

    def test_followup_size_stat_race_is_already_a_partial_inventory(self):
        target = self.repo / 'test_contract.py'
        resolved_target = target.resolve()
        original_stat = Path.stat
        original_resolve = Path.resolve
        original_symlink, original_exists, original_file = Path.is_symlink, Path.exists, Path.is_file
        for error in (FileNotFoundError, PermissionError, ValueError):
            with self.subTest(error=error):
                calls = []

                def stat_race(path, *args, **kwargs):
                    if path == target:
                        calls.append(path)
                        raise error('fixture unavailable at size stat')
                    return original_stat(path, *args, **kwargs)

                # Select the regular file deterministically, independent of
                # which Python versions implement predicates or non-strict
                # resolution via Path.stat. Inject only at the size check.
                with mock.patch.object(Path, 'is_symlink', lambda p: False if p == target else original_symlink(p)), \
                     mock.patch.object(Path, 'exists', lambda p: True if p == target else original_exists(p)), \
                     mock.patch.object(Path, 'is_file', lambda p: True if p == target else original_file(p)), \
                     mock.patch.object(Path, 'resolve', lambda p, *a, **kw: resolved_target if p == target else original_resolve(p, *a, **kw)), \
                     mock.patch.object(Path, 'stat', stat_race):
                    snap = helper.snapshot(self.repo)
                self.assertEqual(calls, [target])
                self.assertEqual(snap['limitations'], ['Source bytes unavailable: test_contract.py'])
                self.assertNotIn('test_contract.py', snap['files'])

    def test_followup_symlink_selection_race_keeps_other_inventory(self):
        target = self.repo / 'vanishing-link'
        target.symlink_to('test_contract.py')
        original = Path.is_symlink

        def vanished_after_selection(path):
            result = original(path)
            if path == target and result:
                path.unlink()
            return result

        with mock.patch.object(Path, 'is_symlink', vanished_after_selection):
            snap = helper.snapshot(self.repo)
        self.assertEqual(snap['limitations'], ['Source bytes unavailable: vanishing-link'])
        self.assertIn('test_contract.py', snap['files'])
        self.assertNotIn('vanishing-link', snap['files'])
        data = self.bound()
        data['findings'] = [judgment(1)]
        result = omg.analyze(data, {**snap, 'sha256': data['identity']['snapshot_sha256']}, 'fixture')
        self.assertEqual(result['findings'][0]['state'], 'gap')
        self.assertFalse(result['evidence_current'])

    def check_shape_cli(self, script):
        data = admission(self.bound())
        data['inspected_groups'] = ['restore']
        # Cover the reported crashes, falsey bypasses and nested fields through
        # real source and relocated installed CLI subprocesses.
        cases = [('measurement', 'claimed'), ('measurement', False),
                 ('measurement', {'scope': []}), ('measurement', {'evidence': [[]]}),
                 ('tradeoff', 'accepted'), ('tradeoff', []), ('tradeoff', {'owner': 1}),
                 ('tradeoff', {'evidence': 'inspection'}),
                 ('protection_retained', [1]), ('protection_lost', [1]),
                 ('protection_retained', ''), ('protection_lost', {})]
        for field, value in cases:
            with self.subTest(script=script, field=field, value=value):
                row = measured_group()
                if isinstance(value, dict) and field in ('measurement', 'tradeoff'):
                    row[field].update(value)
                else:
                    row[field] = value
                data['groups'] = [row]
                before = set(self.state.glob('runs/*/manifest.json'))
                proc = subprocess.run([sys.executable, '-E', '-s', str(script), '--state-root', str(self.state),
                    'audit', str(self.repo), '--input', str(self.input(data))],
                    cwd=self.base, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertNotIn('Traceback', proc.stdout + proc.stderr)
                blocked = json.loads(proc.stdout)
                self.assertEqual(blocked['completion'], 'blocked')
                self.assertIn(field, blocked['error'])
                self.assertEqual(before, set(self.state.glob('runs/*/manifest.json')))
                self.assertNotIn('report', blocked)
        data['groups'] = [measured_group()]
        report = self.call('audit', self.repo, '--input', self.input(data), script=script)
        rec = helper.load(Path(report['audit']))['analysis']['recommendations'][0]
        self.assertEqual(rec['action'], 'simplify')
        self.assertEqual(rec['measurement'], measured_group()['measurement'])
        self.assertEqual(rec['tradeoff'], measured_group()['tradeoff'])
        self.call('status', report['run_id'], script=script)
        self.call('report', report['run_id'], script=script)

    def test_followup_cli_rejects_malformed_evidence_without_saving_report(self):
        self.check_shape_cli(base.SCRIPTS / 'audit.py')

    def test_followup_relocated_installed_cli_validates_evidence_shapes(self):
        import shutil
        proc = subprocess.run([sys.executable, str(base.ROOT / 'scripts/install.py'),
            '--plugin', 'tests-omg', '--prefix', str(self.base / 'prefix'),
            '--agents-root', str(self.base / 'agents')], cwd=self.base,
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        package = self.base / 'relocated'
        shutil.move(json.loads(proc.stdout)['data']['version_dir'], package)
        self.assertTrue(self.call('doctor', script=package / 'scripts/audit.py')['installed_receipt'])
        self.check_shape_cli(package / 'scripts/audit.py')

    def test_supplement_requested_history_failure_is_partial_but_unmeasured_is_complete(self):
        data = self.bound()
        data['history'] = {'runs_complete': False, 'bugs_accessible': False,
                           'errors': ['GET /actions/runs page 3: HTTP 403 rate limited']}
        result = self.call('audit', self.repo, '--input', self.input(data), code=1)
        self.assertEqual(result['completion'], 'partial')
        self.call('status', result['run_id'], code=1)
        self.call('audit', self.repo)
        data['history'] = {'requested': ['runs', 'incidents'], 'runs_complete': False, 'bugs_accessible': False}
        self.call('audit', self.repo, '--input', self.input(data), code=1)

    def test_supplement_org_assertions_are_explicit_in_json_html_and_status(self):
        data, snap = base.fixture()
        snap.update(head_sha='f'*40, sha256='e'*64)
        data['identity'].update(head_sha=snap['head_sha'], snapshot_sha256=snap['sha256'])
        data.update(groups=[base.group()], inspected_groups=['restore'],
                    history={'runs_complete': True, 'bugs_accessible': True})
        admission(data)
        pack = {'org': {'owner': 'example', 'expected_repos': ['example/a'], 'expected_source': 'owner scope',
                'pages': [{'page': 1, 'repos': [{'name': 'example/a', 'classification': 'web-services'}], 'next_page': None}]},
                'repositories': {'example/a': {'snapshot': snap, 'evidence': data}}}
        result = self.call('audit', '--org', 'example', '--input', self.input(pack))
        record = helper.load(Path(result['audit']))
        self.assertTrue(record['scope']['fleet_wide'])
        analysis = record['scope']['results'][0]['analysis']
        self.assertFalse(analysis['evidence_current'])
        self.assertTrue(analysis['asserted_binding_consistent'])
        self.assertEqual(analysis['source_verification'], 'coordinator-asserted; not independently verified')
        self.assertIn('coordinator-asserted', Path(result['report']).read_text())
        status = self.call('status', result['run_id'])
        self.assertEqual(status['freshness'], 'unknown')
        self.assertFalse(status['current_evidence'])
        self.assertIn('organization', status['freshness_reason'].lower())
        self.assertIn('assert', status['freshness_reason'].lower())

    def test_late_same_names_different_sources_never_join_and_same_source_continues(self):
        first = self.call('audit', self.repo)
        other = self.base / 'another' / self.repo.name
        other.parent.mkdir(); other.mkdir()
        subprocess.run(['git', 'init', '-q', str(other)], check=True, capture_output=True)
        (other / 'readme').write_text('unrelated repository')
        subprocess.run(['git', '-C', str(other), 'add', 'readme'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(other), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'other'], check=True, capture_output=True)
        second = self.call('audit', other, '--input', self.input({'repository': self.repo.name}))
        self.assertIsNone(json.loads(Path(second['audit']).read_text())['predecessor'])
        self.assertIsNone(self.call('status', first['run_id'])['superseded_by'])
        third = self.call('audit', self.repo, '--input', self.input({'repository': 'new display label'}))
        self.assertEqual(json.loads(Path(third['audit']).read_text())['predecessor'], first['run_id'])
        self.assertIsNone(self.call('status', first['run_id'])['superseded_by'])
        (self.repo / 'test_contract.py').write_text('new working snapshot')
        fourth = self.call('audit', self.repo)
        self.assertEqual(self.call('status', third['run_id'], code=1)['superseded_by'], fourth['run_id'])

    def test_late_ambiguous_legacy_display_name_is_not_a_predecessor(self):
        first = self.call('audit', self.repo)
        index = helper.load(self.state / 'index.json')
        index['runs'][0].pop('source_identity', None)
        helper.write(self.state / 'index.json', helper.canonical(index))
        second = self.call('audit', self.repo)
        self.assertIsNone(helper.load(Path(second['audit']))['predecessor'])
        self.assertIsNone(self.call('status', first['run_id'])['superseded_by'])

    def test_late_large_source_and_saved_snapshot_limits_are_honest(self):
        (self.repo / 'asset.bin').write_bytes(b'x' * (9 * 1024 * 1024))
        snap = self.call('audit', self.repo, '--snapshot', code=1)
        with mock.patch.object(helper, 'snapshot', wraps=helper.snapshot) as collect:
            same_scope = helper.snapshot_saved(self.repo, snap)
        self.assertEqual(collect.call_args.kwargs['selected_paths'], list(snap['files']))
        self.assertEqual(same_scope['sha256'], snap['sha256'])
        self.assertTrue(same_scope['limitations'])
        byte_limited = helper.snapshot(self.repo, max_bytes=32)
        self.assertTrue(byte_limited['limitations'])
        self.assertEqual(byte_limited['inspected_count'], 0)
        data = admission({'identity': {'head_sha': snap['head_sha'], 'snapshot_sha256': snap['sha256']},
                          'references': base.fixture()[0]['references'], 'findings': [judgment(1)]})
        passing_checks(data); data['checks'][0]['outcome'] = 'fail'
        report = self.call('audit', self.repo, '--input', self.input(data), code=1)
        record = helper.load(Path(report['audit']))
        self.assertEqual([record['analysis']['findings'][i-1]['state'] for i in (1, 3, 12)], ['gap']*3)
        for op in ('status', 'report'):
            self.assertFalse(self.call(op, report['run_id'], code=1)['current_evidence'])
        overrides = ('--snapshot-file-bytes', 10*1024*1024, '--snapshot-bytes', 40*1024*1024)
        complete = self.call('audit', self.repo, '--snapshot', *overrides)
        self.assertEqual(complete['inspected_count'], 2)
        fresh = self.call('audit', self.repo, *overrides)
        for op in ('status', 'report'):
            self.assertEqual(self.call(op, fresh['run_id'])['freshness'], 'current')
        self.call('audit', self.repo, '--resume', fresh['run_id'], code=2)
        self.call('audit', self.repo, '--snapshot-files', 100001, code=2)

    def test_late_file_count_and_time_caps_preserve_independent_gaps(self):
        for n in range(4001):
            (self.repo / f'file-{n:04}').touch()
        snap = helper.snapshot(self.repo)
        self.assertTrue(snap['limitations'])
        data = admission({'identity': {'head_sha': snap['head_sha'], 'snapshot_sha256': snap['sha256']},
                          'references': base.fixture()[0]['references'], 'findings': [judgment(1)]})
        result = omg.analyze(data, snap, 'fixture')
        self.assertEqual(result['findings'][0]['state'], 'gap')
        full = self.call('audit', self.repo, '--snapshot', '--snapshot-files', 5000)
        self.assertEqual(full['inspected_count'], 4002)
        summary = self.call('audit', self.repo, '--snapshot', '--snapshot-files', 5000, '--snapshot-summary')
        self.assertEqual(summary['sha256'], full['sha256'])
        self.assertNotIn('files', summary)
        with mock.patch.object(helper.time, 'monotonic', side_effect=[0, 31]):
            timed = helper.snapshot(self.repo)
        data['identity']['snapshot_sha256'] = timed['sha256']
        self.assertEqual(omg.analyze(data, timed, 'fixture')['findings'][0]['state'], 'gap')

    def test_late_expiry_after_save_blocks_status_report_and_exact_validator(self):
        data = admission(self.bound())
        exception = {'owner': 'fixture', 'reason': 'Temporary control', 'evidence': ['inspection'],
                     'expires_at': '2099-01-01T00:00:00+00:00'}
        data['findings'] = [{**judgment(8, 'meets'), 'exceptions': [exception]}, judgment(1)]
        result = self.call('audit', self.repo, '--input', self.input(data))
        record = helper.load(Path(result['audit'])); manifest = helper.load(Path(result['manifest']))
        descriptor = {'state_root': str(self.state), 'run_id': result['run_id'],
            'audit_sha256': manifest['hashes']['audit.json'], 'input_sha256': manifest['hashes']['input.json'],
            'head_sha': record['snapshot']['head_sha'], 'snapshot_sha256': record['snapshot']['sha256']}
        import validate_audit
        with mock.patch.object(validate_audit, 'audit', helper):
            self.assertEqual(validate_audit.inspect_report(descriptor)['run_id'], result['run_id'])
            with mock.patch.object(omg, 'datetime', wraps=datetime) as clock:
                clock.now.return_value = datetime(2100, 1, 1, tzinfo=timezone.utc)
                for op in ('status', 'report'):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        code = helper.main(['--state-root', str(self.state), op, result['run_id']])
                    self.assertEqual(code, 1)
                    status = json.loads(out.getvalue())
                    self.assertFalse(status['current_evidence'])
                    self.assertEqual(status['expired_exceptions'][0]['finding'], 'TEST-08')
                    self.assertEqual(status['current_findings'][7]['state'], 'unknown')
                    self.assertEqual(status['current_findings'][0]['state'], 'gap')
                with self.assertRaisesRegex(ValueError, 'exception'):
                    validate_audit.inspect_report(descriptor)
        self.assertEqual(helper.load(Path(result['audit'])), record)

    def test_late_relocated_installed_repairs_and_saved_limits_reach_acceptance(self):
        import shutil
        from shared.tests_omg_review import report_binding
        prefix, agents = self.base / 'prefix', self.base / 'agents'
        installed = subprocess.run([sys.executable, str(base.ROOT / 'scripts/install.py'),
            '--plugin', 'tests-omg', '--prefix', str(prefix), '--agents-root', str(agents)],
            cwd=self.base, capture_output=True, text=True, timeout=60)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        original = Path(json.loads(installed.stdout)['data']['version_dir'])
        package = self.base / 'relocated'; shutil.move(str(original), package)
        script = package / 'scripts' / 'audit.py'

        def installed_call(*args, code=0):
            proc = subprocess.run([sys.executable, '-E', '-s', str(script), '--state-root', str(self.state),
                *map(str, args)], cwd=self.base, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)

        self.assertTrue(installed_call('doctor')['installed_receipt'])
        (self.repo / 'asset.bin').write_bytes(b'x' * (9 * 1024 * 1024))
        overrides = ('--snapshot-file-bytes', 10*1024*1024, '--snapshot-bytes', 40*1024*1024)
        snap = installed_call('audit', self.repo, '--snapshot', *overrides)
        data = admission({'identity': {'head_sha': snap['head_sha'], 'snapshot_sha256': snap['sha256'],
            'tested_sha': snap['head_sha'], 'run_id': 'fixture', 'attempt': 1, 'environment': 'fixture',
            'tool_versions': {'python': 'fixture'}, 'config_version': 'fixture'},
            'references': base.fixture()[0]['references'],
            'findings': [judgment(2), judgment(11, 'unknown'), {**judgment(8, 'meets'), 'exceptions': [{
                'owner': 'fixture', 'reason': 'temporary control', 'evidence': ['inspection'],
                'expires_at': '2099-01-01T00:00:00+00:00'}]}],
            'runs': [base.run([base.node('unit', 300)])]})
        passing_checks(data)
        data['checks'] = [{**data['checks'][0], 'outcome': 'timed-out'}, {**data['checks'][0], 'attempt': 2}]
        report = installed_call('audit', self.repo, '--input', self.input(data), *overrides)
        record = helper.load(Path(report['audit'])); manifest = helper.load(Path(report['manifest']))
        self.assertEqual(record['analysis']['findings'][1]['state'], 'gap')
        self.assertEqual(record['analysis']['findings'][10]['state'], 'unknown')
        self.assertEqual(record['analysis']['findings'][2]['state'], 'gap')
        self.assertEqual(record['analysis']['validation_verdict'], 'incomplete')
        for op in ('status', 'report'):
            self.assertTrue(installed_call(op, report['run_id'])['current_evidence'])
        descriptor = {'state_root': str(self.state), 'run_id': report['run_id'],
            'audit_sha256': manifest['hashes']['audit.json'], 'input_sha256': manifest['hashes']['input.json'],
            'head_sha': snap['head_sha'], 'snapshot_sha256': snap['sha256']}
        contract = self.base / 'descriptor.json'; contract.write_text(json.dumps(descriptor))
        proc = subprocess.run([sys.executable, '-E', '-s', str(package / 'scripts/validate_audit.py'),
            '--input', str(contract)], cwd=self.base, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)['accepted'])
        stage = {'id': 'review', 'depends_on': []}
        job = {'stages': [stage], 'tasks': [{'stage_id': 'review', 'role': 'review', 'independent_of_author': True,
            'reviewed_documents': [{'path': report['audit'], 'sha256': descriptor['audit_sha256']}]}]}
        self.assertIn('source-binding', report_binding(job, stage, descriptor, package))
        # Clock advance inside the relocated installed validator, without editing
        # the report or taking authority from the source checkout/PYTHONPATH.
        code = ('import sys; from datetime import datetime, timezone; from unittest import mock; '
            'sys.path.insert(0, sys.argv[1]); import validate_audit, analysis; '
            'clock = mock.patch.object(analysis, "datetime", wraps=datetime); frozen = clock.start(); '
            'frozen.now.return_value = datetime(2100, 1, 1, tzinfo=timezone.utc); '
            'sys.exit(validate_audit.main(["--input", sys.argv[2]]))')
        expired = subprocess.run([sys.executable, '-E', '-s', '-c', code, str(package / 'scripts'), str(contract)],
            cwd=self.base, capture_output=True, text=True, timeout=30)
        self.assertEqual(expired.returncode, 1, expired.stdout + expired.stderr)
        self.assertFalse(json.loads(expired.stdout)['accepted'])
        self.assertEqual(helper.load(Path(report['audit'])), record)


if __name__ == '__main__':
    unittest.main()
