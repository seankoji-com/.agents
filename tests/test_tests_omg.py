"""Observable tests-omg evidence/results. No network, models or GitHub mutations."""
from copy import deepcopy
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/tests-omg/scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))
import analysis as omg
import render as html_report
spec = importlib.util.spec_from_file_location('tests_omg_audit', SCRIPTS / 'audit.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def fixture():
    snapshot = {'head_sha': 'a' * 40, 'sha256': 'b' * 64, 'limitations': []}
    data = {'schema_version': 1, 'identity': {
        'head_sha': snapshot['head_sha'], 'snapshot_sha256': snapshot['sha256'],
        'tested_sha': 'a' * 40, 'comparison_base': 'c' * 40, 'run_id': 'run-1',
        'attempt': 1, 'environment': 'fixture-linux', 'tool_versions': {'python': '3.10'},
        'config_version': 'fixture-v1'},
        'history': {'runs_complete': True, 'bugs_accessible': False},
        'references': [{'id': 'inspection', 'source': 'test fixture source lines 1-20',
                        'observed_at': '2026-10-23T00:00:00+00:00'}]}
    return data, snapshot


def node(name, seconds, needs=(), phase='test'):
    return {'id': name, 'duration': seconds, 'needs': list(needs), 'pool': 'linux', 'phase': phase}


def run(nodes, workers=2, observed=900):
    return {'id': 'run-1', 'attempt': 1, 'outcome': 'pass', 'observed_seconds': observed,
            'graph_complete': True, 'ready_metadata': True, 'capacity': {'linux': workers},
            'capacity_waits': {'documented': True, 'seconds': 480}, 'nodes': nodes}


def group(action='keep'):
    return {'id': 'restore', 'tags': ['critical'], 'assessment_state': 'supported',
            'action': action, 'failure': 'Backup restores corrupt financial data.',
            'consequence': 'Permanent ledger loss.', 'boundary': 'independent restored database',
            'oracle': 'known externally computed ledger balances', 'distinct_protection': 'real restore and rollback',
            'evidence': ['inspection'], 'rationale': 'Rare high-impact failure needs protection.',
            'maintenance': 'Fixture refresh after schema migrations.', 'owner': 'data owner',
            'protection_retained': ['restore-ledger'], 'protection_lost': []}


class EvidenceTests(unittest.TestCase):
    def analyze(self, data, snap):
        return omg.analyze(data, snap, '2026-10-23T00:00:00+00:00')

    def finding(self, result, number):
        return result['findings'][number - 1]

    def test_parallel_graph_is_420_estimate_with_900_observed_and_numeric_capacity(self):
        data, snap = fixture()
        data['runs'] = [run([node('setup', 60, phase='setup'), node('unit', 300, ['setup']),
                             node('contract', 300, ['setup']), node('report', 60, ['unit', 'contract'], 'report')])]
        r = self.analyze(data, snap)
        self.assertEqual(self.finding(r, 2)['state'], 'meets')
        timing = r['timing']['runs'][0]
        self.assertEqual((timing['available_seconds'], timing['observed_seconds'], timing['runner_minutes']), (420, 900, 12))
        self.assertTrue(timing['estimate'])
        self.assertEqual(timing['required_pool'], {'linux': 2})
        self.assertEqual(len(r['timing']['observed_breaches']), 1)
        self.assertTrue(r['timing']['available_p95']['small_sample_warning'])

    def test_capacity_batching_and_reporting_serialization_are_counted(self):
        two = omg.timing(run([node('a', 300), node('b', 300), node('c', 300), node('report', 30, ['a', 'b', 'c'], 'report')]))
        one = omg.timing(run([node('a', 300), node('b', 300), node('c', 300), node('report', 30, ['a', 'b', 'c'], 'report')], workers=1))
        self.assertEqual((two['available_seconds'], one['available_seconds']), (630, 930))
        self.assertEqual(two['runner_minutes'], one['runner_minutes'])

    def test_large_graph_is_unknown_and_unused_capacity_does_not_change_timing(self):
        data, snap = fixture()
        data['runs'] = [run([node(str(i), 1) for i in range(2001)])]
        result = self.analyze(data, snap)
        self.assertEqual(self.finding(result, 2)['state'], 'unknown')
        self.assertIsNone(result['timing']['runs'][0]['available_seconds'])
        self.assertIn('2000-node', result['timing']['runs'][0]['limitations'][0])
        one = run([node('unit', 30)], workers=1024)
        one['capacity'].update({str(i): 1024 for i in range(10000)})
        self.assertEqual(omg.timing(one)['available_seconds'], 30)

    def test_unknown_queue_or_external_dependency_prevents_complete_time_claim(self):
        r = run([node('test', 50)])
        r['ready_metadata'] = False
        self.assertIsNone(omg.timing(r)['available_seconds'])
        r['ready_metadata'] = True
        r['nodes'][0]['needs'] = ['external-workflow']
        self.assertIsNone(omg.timing(r)['available_seconds'])
        r['nodes'] = [node('test', None)]
        self.assertIsNone(omg.timing(r)['available_seconds'])
        with self.assertRaisesRegex(ValueError, 'cyclic'):
            omg.timing(run([node('a', 1, ['b']), node('b', 1, ['a'])]))

    def test_valuable_650_second_check_kept_but_budget_gap_and_all_outliers_remain(self):
        data, snap = fixture()
        data['runs'] = [run([node('restore', 650)], observed=680)]
        data['groups'] = [group()]; data['inspected_groups'] = ['restore']
        r = self.analyze(data, snap)
        self.assertEqual(self.finding(r, 2)['state'], 'gap')
        self.assertEqual(r['recommendations'][0]['action'], 'keep')
        self.assertEqual(r['timing']['breaches'][0]['available_seconds'], 650)
        self.assertEqual(omg.percentile([1] * 20 + [900], .95)['seconds'], 1)
        self.assertEqual(len(r['timing']['breaches']), 1)

    def test_fail_retry_pass_infrastructure_label_is_unfixed_and_attempts_preserved(self):
        data, snap = fixture()
        check = {'check': 'unit', 'shard': '1', 'attempt': 1, 'outcome': 'fail', 'discovered': 1,
                 'report_complete': True, 'tests': [{'id': 'date', 'outcome': 'fail'}]}
        data['checks'] = [check, {**check, 'attempt': 2, 'outcome': 'pass', 'cause': 'infrastructure',
                                 'tests': [{'id': 'date', 'outcome': 'pass'}]}]
        data['expected_checks'] = ['unit:1']; data['assurance_set_complete'] = True
        r = self.analyze(data, snap)
        self.assertEqual(self.finding(r, 3)['state'], 'gap')
        self.assertEqual(r['counts']['retry_passes'], 1)
        self.assertEqual(r['counts']['first_attempt_passes'], 0)
        self.assertEqual(r['counts']['failures'], 1)
        self.assertEqual(len(r['intermittent'][0]['attempts']), 2)
        self.assertEqual(len(r['per_test_attempts']), 2)

    def test_zero_discovery_missing_skipped_quarantined_and_failed_report_are_incomplete(self):
        for outcome, count, report, quarantine in [('pass', 0, True, False), ('skipped', 3, True, False),
                                                  ('pass', 3, True, True), ('pass', 3, False, False),
                                                  ('cancelled', 3, False, False), ('timed-out', 3, False, False)]:
            data, snap = fixture()
            data['checks'] = [{'check': 'unit', 'shard': '1', 'attempt': 1, 'outcome': outcome,
                               'discovered': count, 'report_complete': report, 'quarantined': quarantine}]
            data['expected_checks'] = ['unit:1', 'unit:2']
            data['assurance_set_complete'] = True
            r = self.analyze(data, snap)
            self.assertEqual((self.finding(r, 12)['state'], r['validation_verdict']), ('gap', 'incomplete'))
            self.assertIn('unit:2', r['missing_checks'])
        data, snap = fixture(); data['expected_checks'] = []
        self.assertEqual(self.finding(self.analyze(data, snap), 12)['state'], 'gap')

    def test_colliding_shard_ids_and_spoofed_per_test_identity_are_rejected(self):
        data, snap = fixture()
        check = {'check': 'unit', 'shard': '1', 'attempt': 1, 'outcome': 'pass',
                 'discovered': 1, 'report_complete': True}
        data['checks'] = [{**check, 'check': 'a:b', 'shard': 'c'}, {**check, 'check': 'a', 'shard': 'b:c'}]
        data['expected_checks'] = ['a:b:c']; data['assurance_set_complete'] = True
        with self.assertRaisesRegex(ValueError, 'without colons'):
            self.analyze(data, snap)
        for key, value in [('check', 'other'), ('shard', '2'), ('attempt', 99), ('test', 'other-case')]:
            data['checks'] = [{**check, 'tests': [{'id': 'case', 'outcome': 'pass', key: value}]}]
            with self.assertRaisesRegex(ValueError, 'per-test identity'):
                self.analyze(data, snap)

    def test_mixed_or_stale_identity_and_expired_evidence_reject_current_claims(self):
        data, snap = fixture()
        data['runs'] = [run([node('unit', 30)])]
        data['artifacts'] = [{**data['identity'], 'attempt': 2}]
        r = self.analyze(data, snap)
        self.assertFalse(r['evidence_current'])
        self.assertEqual(self.finding(r, 11)['state'], 'gap')
        self.assertEqual(r['timing']['runs'], [])
        data['artifacts'] = []; data['identity']['head_sha'] = 'd' * 40
        self.assertFalse(self.analyze(data, snap)['evidence_current'])
        data, snap = fixture(); data['references'][0]['expires_at'] = '2000-01-01T00:00:00+00:00'
        self.assertIn('expired', ' '.join(self.analyze(data, snap)['limitations']))

    def test_coverage_incompatible_base_and_history_unavailable_stay_unknown(self):
        data, snap = fixture()
        data['coverage'] = {'counts': {'lines': 200}, 'baseline': {'compatible': False}}
        r = self.analyze(data, snap)
        self.assertEqual(self.finding(r, 4)['state'], 'unknown')
        self.assertIn('incompatible', self.finding(r, 4)['reason'])
        self.assertEqual(self.finding(r, 6)['state'], 'unknown')

    def test_coverage_metadata_preserves_an_inspected_critical_gap(self):
        data, snap = fixture()
        gap = {'id': 'TEST-04', 'state': 'gap', 'reason': 'Checkout never tests a declined payment.',
               'evidence': ['inspection'], 'confidence': 'high', 'consequence': 'Wrong charge.',
               'owner': 'payments', 'next_action': 'Test rejection at the processor boundary.'}
        data['findings'] = [gap]
        data['coverage'] = {key: [] for key in ('source_inventory', 'exclusions', 'uninstrumented', 'generated_vendored')}
        data['coverage'].update(tool='coverage', version='1', unit='line', identity_policy='file:line',
                                counts={'lines': 20}, revision=data['identity']['tested_sha'], instrumentation='fixture',
                                baseline={'base_sha': data['identity']['comparison_base'], 'policy': 'merge-base',
                                          'instrumentation': 'fixture', 'compatible': True})
        for compatible in (True, False):
            data['coverage']['baseline']['compatible'] = compatible
            finding = self.finding(self.analyze(data, snap), 4)
            self.assertEqual((finding['state'], finding['reason'], finding['evidence']),
                             ('gap', gap['reason'], ['inspection']))
            self.assertEqual(finding['coverage_comparison']['state'], 'compatible' if compatible else 'unknown')

        data['references'].append({'id': 'old-coverage', 'source': 'expired coverage attachment',
                                   'observed_at': '2000-01-01T00:00:00+00:00',
                                   'expires_at': '2000-01-02T00:00:00+00:00'})
        data['coverage']['evidence'] = ['old-coverage']
        result = self.analyze(data, snap)
        finding = self.finding(result, 4)
        self.assertEqual((finding['state'], finding['reason'], finding['evidence']),
                         ('gap', gap['reason'], ['inspection']))
        self.assertEqual(finding['coverage_comparison']['state'], 'unknown')
        self.assertEqual(result['coverage'], {})

    def test_expired_unused_reference_preserves_independent_findings_timing_and_actions(self):
        data, snap = fixture()
        data['references'].append({'id': 'old', 'source': 'unused diagnostic',
                                   'observed_at': '2000-01-01T00:00:00+00:00',
                                   'expires_at': '2000-01-02T00:00:00+00:00'})
        data['findings'] = [{'id': 'TEST-01', 'state': 'gap', 'reason': 'Restore rejects no corrupt backup.',
                             'evidence': ['inspection'], 'confidence': 'high', 'consequence': 'Data loss.',
                             'owner': 'storage', 'next_action': 'Test rejection.'},
                            {'id': 'TEST-08', 'state': 'meets', 'reason': 'Old evidence.', 'evidence': ['old'],
                             'confidence': 'high', 'consequence': 'Recovery.', 'owner': 'storage', 'next_action': 'Review.'}]
        data.update(groups=[group()], inspected_groups=['restore'], runs=[run([node('unit', 30)])])
        result = self.analyze(data, snap)
        self.assertEqual(self.finding(result, 1)['state'], 'gap')
        self.assertEqual(self.finding(result, 8)['state'], 'unknown')
        self.assertEqual(result['recommendations'][0]['action'], 'keep')
        self.assertEqual(result['timing']['runs'][0]['available_seconds'], 30)
        data['groups'][0]['evidence'] = ['old']
        data['runs'][0]['evidence'] = ['old']
        result = self.analyze(data, snap)
        self.assertIsNone(result['recommendations'][0]['action'])
        self.assertEqual(result['timing']['runs'], [])

    def test_all_uninspected_supported_actions_become_unresolved(self):
        for action in ('keep', 'simplify', 'delete', 'replace'):
            data, snap = fixture()
            data['groups'] = [{**group(action), 'basis': 'dead-feature'}]
            data['comparisons'] = [{'group': 'restore', 'same_corpus': True, 'same_environment': True,
                                    'existing_seconds': 650, 'candidate_seconds': 100,
                                    'existing_runner_minutes': 11, 'candidate_runner_minutes': 2,
                                    'cases': [{'id': 'restore-ledger', 'risk': 'data-loss',
                                               'existing': 'detected', 'candidate': 'detected'}]}]
            result = self.analyze(data, snap)
            self.assertEqual(result['sample']['omitted'], ['restore'])
            self.assertEqual(result['recommendations'][0]['assessment_state'], 'needs_evidence')
            self.assertIsNone(result['recommendations'][0]['action'])
            self.assertTrue(result['recommendations'][0]['next_experiment'])

    def test_deferral_phrasings_rejected_but_wallclock_percentages_allowed(self):
        data, snap = fixture(); data.update(groups=[group()], inspected_groups=['restore'])
        for rationale in ('shift the expensive suite to a nightly job', 'Post-merge slow suite',
                          'Nightly tests', 'offload checks to the background', 'keep optional slow checks'):
            data['groups'][0]['rationale'] = rationale
            with self.assertRaisesRegex(ValueError, 'deferral'):
                self.analyze(data, snap)
        for rationale in ('setup is 80% of wallclock before the assertion runs',
                          '20% of runtime is reporting', 'Protect background transaction processing before merge.'):
            data['groups'][0]['rationale'] = rationale
            self.assertEqual(self.analyze(data, snap)['recommendations'][0]['action'], 'keep')
        for rationale in ('80% value for 20% cost', 'protection is 80 percent of all future safety', '80/20 safety'):
            data['groups'][0]['rationale'] = rationale
            with self.assertRaisesRegex(ValueError, '80/20'):
                self.analyze(data, snap)

    def test_known_over_budget_node_is_a_gap_without_ready_metadata(self):
        data, snap = fixture()
        measured = run([node('restore', 650)], workers=1, observed=650)
        measured['ready_metadata'] = False
        data['runs'] = [measured]
        result = self.analyze(data, snap)
        self.assertEqual(self.finding(result, 2)['state'], 'gap')
        self.assertIsNone(result['timing']['runs'][0]['available_seconds'])
        self.assertEqual(result['timing']['breaches'][0]['lower_bound_seconds'], 650)
        self.assertEqual(len(result['timing']['observed_breaches']), 1)

    def test_modelled_chain_and_capacity_breaches_survive_missing_ready_metadata(self):
        graphs = ([node('setup', 250, phase='setup'), node('unit', 250, ['setup']),
                   node('report', 250, ['unit'], 'report')],
                  [node('a', 250), node('b', 250), node('c', 250)])
        for nodes in graphs:
            with self.subTest(nodes=nodes):
                data, snap = fixture()
                data['runs'] = [run(nodes, workers=1, observed=100)]
                data['runs'][0]['ready_metadata'] = False
                result = self.analyze(data, snap)
                self.assertEqual(self.finding(result, 2)['state'], 'gap')
                measured = result['timing']['breaches'][0]
                self.assertEqual(measured['modelled_seconds'], 750)
                self.assertEqual(measured['lower_bound_seconds'], 250)
                self.assertIsNone(measured['available_seconds'])
                self.assertTrue(any('Ready/start' in note for note in measured['limitations']))
                self.assertIsNone(result['timing']['available_p95'])
                self.assertEqual(result['timing']['observed_breaches'], [])

    def test_uncertain_or_incomplete_timing_cannot_establish_a_budget_pass(self):
        for missing in ('ready_metadata', 'graph_complete', 'duration', 'dependency', 'capacity'):
            with self.subTest(missing=missing):
                data, snap = fixture()
                measured = run([node('setup', 250), node('report', 250, ['setup'])], workers=1)
                if missing in ('ready_metadata', 'graph_complete'):
                    measured[missing] = False
                elif missing == 'duration':
                    measured['nodes'][0]['duration'] = None
                elif missing == 'dependency':
                    measured['nodes'][0]['needs'] = ['external']
                else:
                    measured['capacity'] = {}
                data['runs'] = [measured]
                result = self.analyze(data, snap)
                self.assertEqual(self.finding(result, 2)['state'], 'unknown')
                self.assertIsNone(result['timing']['runs'][0]['available_seconds'])
                self.assertEqual(result['timing']['breaches'], [])
                if missing != 'ready_metadata':
                    self.assertNotIn('modelled_seconds', result['timing']['runs'][0])

    def test_complete_local_report_identity_can_meet_test_11(self):
        data, snap = fixture()
        result = self.analyze(data, snap)
        self.assertEqual(self.finding(result, 11)['state'], 'meets')
        self.assertIn('delivery remain unverified', ' '.join(result['limitations']))

    def test_critical_lost_case_cancels_replacement_and_names_protection(self):
        data, snap = fixture(); data['groups'] = [group('replace')]; data['inspected_groups'] = ['restore']
        data['comparisons'] = [{'group': 'restore', 'same_corpus': True, 'same_environment': True,
                               'cases': [{'id': 'lost-critical-ledger', 'risk': 'catastrophic-data', 'existing': 'detected', 'candidate': 'missed'},
                                         {'id': 'equivalent', 'risk': 'data', 'existing': 'equivalent', 'candidate': 'equivalent'},
                                         {'id': 'kept', 'risk': 'data', 'existing': 'detected', 'candidate': 'detected'}]}]
        r = self.analyze(data, snap)
        rec = r['recommendations'][0]
        self.assertIsNone(rec['action'])
        self.assertEqual(rec['assessment_state'], 'needs_evidence')
        self.assertEqual(rec['protection_lost'], ['lost-critical-ledger'])
        self.assertEqual(rec['protection_retained'], ['kept'])
        self.assertEqual([self.finding(r, i)['state'] for i in (5, 10)], ['gap', 'gap'])
        self.assertIn('lost-critical-ledger', json.dumps(self.finding(r, 5)))

    def test_unsupported_claims_duplicates_and_forbidden_savings_are_rejected(self):
        data, snap = fixture(); data['groups'] = [group()]; data['inspected_groups'] = ['restore']
        for rationale in ('80% value for 20% cost', 'Move slow suite to nightly', 'Run in background', 'defer slow suite until later'):
            data['groups'][0]['rationale'] = rationale
            with self.assertRaises(ValueError): self.analyze(data, snap)
        data['groups'] = [{**group('delete'), 'basis': 'confirmed-duplication'}]; data['inspected_groups'] = ['restore']
        with self.assertRaisesRegex(ValueError, 'same lines'): self.analyze(data, snap)
        data['groups'][0]['independent_boundary_analysis'] = 'Same process and oracle; no real second boundary.'
        self.assertEqual(self.analyze(data, snap)['recommendations'][0]['action'], 'delete')
        data['groups'] = [{'id': 'unknown'}]; data['inspected_groups'] = []
        self.assertIsNone(self.analyze(data, snap)['recommendations'][0]['action'])
        data['groups'] = [group()]; data['inspected_groups'] = ['restore']
        data['groups'][0]['rationale'] = 'Protect background transaction processing and nightly ledger imports before merge.'
        self.assertEqual(self.analyze(data, snap)['recommendations'][0]['action'], 'keep')

    def test_sampling_is_reproducible_and_retains_critical_rare_cases(self):
        groups = [group()] + [{'id': str(i)} for i in range(20)]
        a = omg.sample(groups, 'seed', 3); b = omg.sample(groups, 'seed', 3)
        self.assertEqual(a, b)
        self.assertIn('restore', a['selected'])
        self.assertEqual(len(a['random']), 3)
        self.assertEqual(len(a['selected']), 4)

    def test_incomplete_inventory_invalidates_supported_recommendations(self):
        data, snap = fixture(); data['groups'] = [group()]; data['inspected_groups'] = ['restore']
        snap['limitations'] = ['Source inventory file/time/32MiB budget exhausted.']
        result = self.analyze(data, snap)
        self.assertFalse(result['evidence_current'])
        self.assertEqual(result['recommendations'], [])
        self.assertFalse(any(f['state'] == 'meets' for f in result['findings']))

    def test_missing_timing_and_assurance_set_override_authored_clean_claims(self):
        data, snap = fixture()
        data['findings'] = [{'id': 'TEST-%02d' % i, 'state': 'meets', 'reason': 'Claim',
                             'evidence': ['inspection'], 'confidence': 'high', 'consequence': 'Contract',
                             'owner': 'owner', 'next_action': 'Verify'} for i in (2, 12)]
        result = self.analyze(data, snap)
        self.assertEqual([self.finding(result, i)['state'] for i in (2, 12)], ['unknown', 'unknown'])
        self.assertEqual(result['validation_verdict'], 'unknown')
        data['findings'][0]['revision'] = 'd' * 40
        with self.assertRaisesRegex(ValueError, 'finding revision'):
            self.analyze(data, snap)
        data['findings'][0].pop('revision')
        data['findings'].append(deepcopy(data['findings'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate finding'):
            self.analyze(data, snap)

    def test_quarantine_and_skips_do_not_count_as_completed_shards(self):
        for extra in ({'quarantined': True}, {'skipped_tests': 1}, {'attempt': 2},
                      {'tests': [{'id': 'hidden-failure', 'outcome': 'fail'}]}):
            data, snap = fixture()
            data['checks'] = [{'check': 'unit', 'shard': '1', 'attempt': 1, 'outcome': 'pass',
                               'discovered': 2, 'report_complete': True, **extra}]
            data['expected_checks'] = ['unit:1']
            result = self.analyze(data, snap)
            self.assertEqual(result['completed_checks'], [])
            self.assertEqual(result['missing_checks'], ['unit:1'])
            self.assertEqual(result['validation_verdict'], 'incomplete')

    def test_replacement_needs_named_detection_and_compute_comparison(self):
        data, snap = fixture(); data['groups'] = [group('replace')]; data['inspected_groups'] = ['restore']
        comparison = {'group': 'restore', 'same_corpus': True, 'same_environment': True,
                      'cases': [{'id': 'restore-ledger', 'risk': 'data-loss',
                                 'existing': 'detected', 'candidate': 'detected'}]}
        data['comparisons'] = [comparison]
        self.assertIsNone(self.analyze(data, snap)['recommendations'][0]['action'])
        comparison.update(existing_seconds=650, candidate_seconds=100,
                          existing_runner_minutes=11, candidate_runner_minutes=2)
        self.assertEqual(self.analyze(data, snap)['recommendations'][0]['action'], 'replace')
        comparison['cases'][0]['existing'] = 'missed'
        comparison['cases'][0]['candidate'] = 'missed'
        self.assertIsNone(self.analyze(data, snap)['recommendations'][0]['action'])
        comparison['cases'][0]['candidate'] = 'arbitrary'
        with self.assertRaisesRegex(ValueError, 'explicit outcomes'):
            self.analyze(data, snap)

    def test_hostile_names_executable_links_and_credentials_are_inert(self):
        data, snap = fixture()
        hostile = '<img src=x onerror="alert(1)"><script>bad()</script>'
        data['references'][0].update(source=hostile, url='javascript:alert(1)')
        data['checks'] = [{'check': 'setup', 'shard': '1', 'attempt': 1, 'outcome': 'setup-failed',
                           'discovered': 0, 'diagnostic': 'setup attempt 1 failed before discovery'}]
        result = self.analyze(data, snap)
        audit = {'repository': hostile, 'snapshot': snap, 'run_id': 'fixture', 'generated_at': 'today',
                 'completion': 'complete', 'scope': {}, 'input': data, 'analysis': result,
                 'input_sha256': 'digest', 'generator_version': '0.1.0', 'benchmark_version': '1.0',
                 'risks': ['Named residual exposure: ' + hostile]}
        html = html_report.render(audit)
        self.assertNotIn('<script>', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn("default-src 'none'", html)
        self.assertIn('Actual tested SHA: ' + data['identity']['tested_sha'], html)
        self.assertIn('setup attempt 1 failed before discovery', html)
        self.assertIn('fixture-linux', html)
        self.assertIn('Named residual exposure: &lt;img', html)
        self.assertIsNone(html_report.safe_url('https://user:password@example.invalid/log'))
        self.assertEqual(html_report.safe_url('https://example.invalid/log#attempt-2'), 'https://example.invalid/log#attempt-2')
        cleaned = helper.sanitize({'token': 'fixture-secret', 'log': 'Bearer fixture-secret', 'url': 'https://example.invalid/?token=fixture-secret'})
        self.assertNotIn('fixture-secret', json.dumps(cleaned))


class CommandTests(unittest.TestCase):
    def test_doctor_manifest_cannot_read_outside_package(self):
        package = self.base / 'package'
        shutil.copytree(SCRIPTS.parent, package)
        outside = self.base / 'outside'; outside.mkdir()
        sentinel = outside / 'fixture.txt'; sentinel.write_text('public fixture marker')
        (package / 'linked').symlink_to(outside, target_is_directory=True)
        original_read = helper.read
        def bounded_read(path, *args, **kwargs):
            self.assertNotEqual(Path(path).resolve(), sentinel)
            return original_read(path, *args, **kwargs)
        for path in ('../outside/fixture.txt', str(sentinel), 'linked/fixture.txt'):
            (package / 'install-manifest.json').write_text(json.dumps({'files': [{'path': path, 'sha256': 'unused'}]}))
            with mock.patch.object(helper, 'PACKAGE', package), mock.patch.object(helper, 'read', side_effect=bounded_read):
                with self.assertRaisesRegex(ValueError, 'manifest path'):
                    helper.doctor()

    def test_doctor_checks_git_and_posix_locking_without_launching_commands(self):
        with mock.patch.object(helper.shutil, 'which', return_value=None), \
                mock.patch.object(helper.importlib.util, 'find_spec', return_value=None), \
                mock.patch.object(helper.subprocess, 'run', side_effect=AssertionError('doctor launched a command')):
            result = helper.doctor()
        self.assertEqual(result['completion'], 'blocked')
        self.assertIn('Git executable unavailable', result['errors'])
        self.assertTrue(any('POSIX' in e for e in result['errors']))

    def test_explicit_skill_operations_route_without_an_extra_picker(self):
        with mock.patch.object(sys, 'path', [str(ROOT / 'scripts'), *sys.path]):
            import skills
        meta = json.loads((SCRIPTS.parent / 'plugin.json').read_text())
        for request, operation in [('doctor', 'doctor'), ('audit', 'audit'),
                                   ('audit /repo --run-checks', 'audit'), ('audit --org example', 'audit'),
                                   ('status omg-123', 'status'), ('report omg-123', 'report')]:
            self.assertEqual(skills.route(meta, request), operation)
        for request in ('', 'audit-typo', 'doctor --run-checks', 'status', 'publish omg-123'):
            self.assertIsNone(skills.route(meta, request))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS temporary paths can traverse /var -> /private/var. Use the
        # canonical fixture root so private-state symlink guards stay enabled.
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / 'repo'; self.repo.mkdir()
        self.state = self.base / 'state'
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        self.git('init', '-q')
        (self.repo / 'test_contract.py').write_text('from pathlib import Path\nPath("must-not-run").touch()\n')
        self.git('add', 'test_contract.py')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')

    def git(self, *args):
        return subprocess.run(['git', '-c', 'commit.gpgsign=false', '-C', str(self.repo), *args], check=True, capture_output=True, timeout=10)

    def call(self, *args, code=0, script=None):
        p = subprocess.run([sys.executable, str(script or SCRIPTS / 'audit.py'), '--state-root', str(self.state), *map(str, args)],
                           cwd=self.base, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def input(self, data):
        p = self.base / 'evidence.json'; p.write_text(json.dumps(data)); return p

    def bound(self):
        snap = self.call('audit', self.repo, '--snapshot')
        data, _ = fixture(); data['identity'].update(head_sha=snap['head_sha'], snapshot_sha256=snap['sha256'], tested_sha=snap['head_sha'])
        return data

    def test_default_read_only_report_private_state_and_hash_drift(self):
        before = self.git('status', '--porcelain').stdout
        report = self.call('audit', self.repo)
        self.assertEqual(report['completion'], 'complete')
        self.assertFalse((self.repo / 'must-not-run').exists())
        self.assertEqual(self.git('status', '--porcelain').stdout, before)
        path = Path(report['audit'])
        record = json.loads(path.read_text())
        self.assertEqual(len(record['analysis']['findings']), 12)
        self.assertTrue(all(f['state'] == 'unknown' for f in record['analysis']['findings']))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        raw = Path(report['report']).read_bytes()
        self.call('report', report['run_id'])
        self.assertEqual(raw, Path(report['report']).read_bytes())
        Path(report['report']).write_bytes(raw + b'changed')
        self.assertIn('digest mismatch', self.call('report', report['run_id'], code=2)['error'])

    def test_installed_review_bundle_and_exact_advisory_acceptance(self):
        from shared.job_coordinator import create_pinned_job, publish_observation, prepare_task, verify_pinned_dependency
        from core.jobs import record_dispatch, record_result
        from core.jobs.store import Store, canonical
        from shared.job_acceptance import _adapter, AcceptanceError, accept_stage, validate_stage
        prefix, agents = self.base / 'prefix', self.base / 'agents'
        installed = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'),
            '--plugin', 'tests-omg', '--prefix', str(prefix), '--agents-root', str(agents)],
            cwd=self.base, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        package = Path(json.loads(installed.stdout)['data']['version_dir'])
        receipt = json.loads((package / 'install-manifest.json').read_text())
        self.assertTrue(receipt.get('bundle_dir'))
        snapshot = self.call('audit', self.repo, '--snapshot', script=package / 'scripts/audit.py')
        evidence_input = self.input({'identity': {'head_sha': snapshot['head_sha'],
            'snapshot_sha256': snapshot['sha256']}, 'expected_checks': ['unit:1']})
        report = self.call('audit', self.repo, '--input', evidence_input, script=package / 'scripts/audit.py')
        saved = json.loads(Path(report['audit']).read_text())
        manifest = json.loads(Path(report['manifest']).read_text())
        descriptor = {'state_root': str(self.state), 'run_id': report['run_id'],
            'audit_sha256': manifest['hashes']['audit.json'], 'input_sha256': manifest['hashes']['input.json'],
            'head_sha': saved['snapshot']['head_sha'], 'snapshot_sha256': saved['snapshot']['sha256']}
        validator = package / 'scripts/validate_audit.py'
        def validate(data, code):
            path = self.base / 'descriptor.json'; path.write_text(json.dumps(data))
            proc = subprocess.run([sys.executable, str(validator), '--input', str(path)],
                cwd=self.base, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)
        result = validate(descriptor, 0)
        self.assertTrue(result['accepted'])
        # Unknown test outcomes remain unknown; valid advisory is not a test pass.
        evidence = result['requirement_outcomes']['audit-report-integrity']['evidence']
        self.assertEqual(evidence['validation_verdict'], 'incomplete')
        self.assertFalse((self.repo / 'must-not-run').exists())
        for key in ('run_id', 'audit_sha256', 'input_sha256', 'head_sha', 'snapshot_sha256'):
            self.assertFalse(validate({**descriptor, key: 'wrong'}, 1)['accepted'])
        job = {'schema_version': 1, 'job_id': 'audit-review', 'installation_id': receipt['installation_id'],
            'workflow': 'tests-omg/audit', 'owner': 'fixture', 'objective': 'review exact advisory',
            'requirements': {'R1': 'complete advisory'}, 'authorization': {'actions': ['read']},
            'constraints': ['read only'], 'dependencies': [{'key': 'audit', 'plugin': 'tests-omg'}],
            'pins': {}, 'policy': {'max_repair_cycles': 1, 'max_artifact_bytes': 16777216},
            'stages': [{'id': 'review', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                'validator_dependency': 'audit', 'validator_contract': descriptor}],
            'tasks': [{'task_id': 'review', 'stage_id': 'review', 'logical_slot_id': 'review',
                'request_id': 'review-request', 'worker_id': 'tests-omg/reviewer', 'dependency_key': 'audit',
                'role': 'review', 'independent_of_author': True,
                'target': {'providerInstanceId': 'fixture-reviewer', 'model': 'gemini-fixture', 'lineage': 'google'},
                'document_authors': [{'lineage': 'openai'}],
                'reviewed_documents': [{'path': report['audit'], 'sha256': descriptor['audit_sha256']}]}],
            'decisions': [], 'history': [], 'metrics': {}, 'result_contract': {'schema_version': 1}}
        jobs = self.base / 'jobs'
        create_pinned_job(job, jobs, prefix, agents, self.base / 'workers.json')
        caller = {'actor': 'coordinator', 'installation_id': receipt['installation_id'],
                  'workflow': job['workflow'], 'package_digest': receipt['package_digest']}
        store = Store(jobs, job['job_id'])
        path = self.input(descriptor)
        publish_observation(store, caller, 'review', str(path))
        pinned = store.load(); stage = pinned['stages'][0]
        argv = [str(validator), '--input', stage['observation_ref']['path']]
        binding = _adapter(pinned, stage, argv, stage['observation_ref']['path'])[2]
        self.assertEqual(binding['expected_outcome_ids'],
                         ['audit-report-integrity', 'audit-scope-complete', 'audit-source-current'])
        no_review = deepcopy(pinned); no_review['tasks'] = []
        with self.assertRaisesRegex(ValueError, 'independent review'):
            _adapter(no_review, stage, argv, stage['observation_ref']['path'])
        changed = deepcopy(pinned); changed['stages'][0]['validator_contract']['audit_sha256'] = '0' * 64
        with self.assertRaisesRegex(AcceptanceError, 'exact declared report'):
            _adapter(changed, changed['stages'][0], argv, stage['observation_ref']['path'])
        with self.assertRaisesRegex(AcceptanceError, 'observed execution identity'):
            accept_stage(store, caller, 'review', argv, stage['observation_ref']['path'])
        brief_ref = prepare_task(store, caller, 'review', verify_pinned_dependency,
                                lambda sid: validate_stage(store, sid).get('accepted') is True)
        brief = json.loads(Path(brief_ref['path']).read_text())
        record_dispatch(store, caller, 'review', {'kind': 'accepted', 'request_id': 'review-request',
            'host_task_id': 'fixture-task', 'child_thread_id': 'fixture-thread'})
        record_dispatch(store, caller, 'review', {'kind': 'completion', 'request_id': 'review-request',
            'host_task_id': 'fixture-task', 'completion_id': 'fixture-completion', 'status': 'completed',
            'work_state': 'result_available', 'has_pending_child_runs': False,
            'status_identity': {'providerInstanceId': 'fixture-reviewer', 'model': 'gemini-fixture'}})
        result = {k: brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id',
                                        'worker_id', 'effective_brief_sha256', 'revision')}
        result.update(schema_version=1, status='ready-for-acceptance', conclusion='Fixture review approves the advisory only.',
            binding=brief['snapshot'], requirements=[{'id': 'R1', 'status': 'passed', 'evidence': 'fixture inspection'}],
            review_verdict='approve', findings=[], gaps=[], uncertainties=[], changes=[], commands=[], artifacts=[],
            extra_work_requests=[], metrics={})
        record_result(store, caller, 'review', {'result': canonical(result), 'request_id': 'review-request',
                                              'completion_id': 'fixture-completion'})
        accepted = accept_stage(store, caller, 'review', argv, stage['observation_ref']['path'])
        self.assertTrue(accepted['accepted'], accepted)
        self.assertTrue(validate_stage(store, 'review')['accepted'])
        # Source and report mutations invalidate the current advisory, not just its filename.
        (self.repo / 'test_contract.py').write_text('changed fixture\n')
        self.assertFalse(validate(descriptor, 1)['accepted'])
        with self.assertRaisesRegex(ValueError, 'stale'):
            _adapter(pinned, stage, argv, stage['observation_ref']['path'])
        self.assertFalse(validate_stage(store, 'review')['accepted'])
        Path(report['report']).write_text('corrupt report')
        self.assertFalse(validate(descriptor, 1)['accepted'])

    def test_valid_input_with_larger_saved_counterpart_stays_openable(self):
        data = self.bound()
        data['groups'] = [{'id': 'large-existing-evidence', 'unresolved_claim': 'x' * 4_300_000}]
        result = self.call('audit', self.repo, '--input', self.input(data))
        self.assertGreater(Path(result['audit']).stat().st_size, 8 * 1024 * 1024)
        self.assertTrue(self.call('status', result['run_id'])['current_evidence'])
        self.call('report', result['run_id'])

    def test_source_drift_rejected_resume_and_old_report_stale(self):
        data = self.bound()
        first = self.call('audit', self.repo, '--input', self.input(data))
        self.assertTrue(self.call('status', first['run_id'])['current_evidence'])
        (self.repo / 'test_contract.py').write_text('changed')
        self.assertEqual(self.call('status', first['run_id'], code=1)['freshness'], 'stale')
        self.assertIn('rebinding', self.call('audit', self.repo, '--resume', first['run_id'], code=2)['error'])
        second = self.call('audit', self.repo)
        index = json.loads((self.state / 'index.json').read_text())
        self.assertEqual(index['runs'][-1]['predecessor'], first['run_id'])
        self.assertEqual(second['completion'], 'complete')

    def test_resume_keeps_limits_counters_and_rejects_expanded_authority(self):
        first = self.call('audit', self.repo, '--seconds', 15)
        second = self.call('audit', self.repo, '--seconds', 15, '--resume', first['run_id'])
        a = json.loads(Path(first['audit']).read_text()); b = json.loads(Path(second['audit']).read_text())
        self.assertEqual(a['scope']['counters'], b['scope']['counters'])
        self.assertGreater(b['scope']['elapsed_seconds'], a['scope']['elapsed_seconds'])
        self.call('audit', self.repo, '--run-checks', '--seconds', 15, '--resume', second['run_id'], code=2)

    def test_coordinator_effort_exhaustion_stays_partial_across_resume(self):
        data = self.bound(); data['audit_effort'] = {'incremental_seconds': 20}
        first = self.call('audit', self.repo, '--seconds', 15, '--input', self.input(data), code=1)
        resumed = self.call('audit', self.repo, '--seconds', 15, '--input', self.input(data),
                            '--resume', first['run_id'], code=1)
        a = json.loads(Path(first['audit']).read_text()); b = json.loads(Path(resumed['audit']).read_text())
        self.assertEqual((a['completion'], b['completion']), ('partial', 'partial'))
        self.assertGreater(b['scope']['elapsed_seconds'], a['scope']['elapsed_seconds'])
        self.assertEqual(a['scope']['counters'], b['scope']['counters'])

    def test_interruption_keeps_private_checkpoint_and_resumes_without_a_new_scope(self):
        output = io.StringIO()
        with mock.patch.object(helper, 'snapshot', side_effect=KeyboardInterrupt), contextlib.redirect_stdout(output):
            code = helper.main(['--state-root', str(self.state), 'audit', str(self.repo)])
        self.assertEqual(code, 1)
        interrupted = json.loads(output.getvalue())
        self.assertTrue(interrupted['run_id'])
        saved = self.call('status', interrupted['run_id'], code=1)
        self.assertEqual(saved['phase'], 'interrupted')
        self.assertIsNone(saved['report'])
        result = self.call('audit', self.repo, '--resume', interrupted['run_id'])
        record = json.loads(Path(result['audit']).read_text())
        self.assertEqual(record['scope']['resumed_from'], interrupted['run_id'])
        self.assertGreaterEqual(record['scope']['elapsed_seconds'], saved['elapsed_seconds'])
        status = self.call('status', interrupted['run_id'])
        self.assertEqual(status['requested_run_id'], interrupted['run_id'])
        self.assertEqual(status['run_id'], result['run_id'])
        self.assertFalse(helper.pending_path(self.state, interrupted['run_id']).exists())
        self.assertIn('already resumed', self.call('audit', self.repo, '--resume', interrupted['run_id'], code=1)['error'])

    def test_interrupted_report_write_resumes_without_discarding_partial_files(self):
        def interrupted_save(root, audit, locator):
            helper.private_dir(root / 'runs')
            folder = helper.run_dir(root, audit['run_id']); folder.mkdir(mode=0o700)
            (folder / 'input.json').write_text('{}')
            raise KeyboardInterrupt
        output = io.StringIO()
        with mock.patch.object(helper, 'save', side_effect=interrupted_save), contextlib.redirect_stdout(output):
            code = helper.main(['--state-root', str(self.state), 'audit', str(self.repo)])
        self.assertEqual(code, 1)
        interrupted = json.loads(output.getvalue())
        old = self.state / 'runs' / interrupted['run_id']
        self.assertEqual(self.call('status', interrupted['run_id'], code=1)['phase'], 'interrupted')
        result = self.call('audit', self.repo, '--resume', interrupted['run_id'])
        self.assertEqual(result['completion'], 'complete')
        record = json.loads(Path(result['audit']).read_text())
        self.assertEqual(record['scope']['resumed_from'], interrupted['run_id'])
        self.assertEqual((old / 'input.json').read_text(), '{}')
        self.assertEqual(self.call('report', interrupted['run_id'])['run_id'], result['run_id'])

    def test_expired_unavailable_and_missing_source_status_report_exit_one(self):
        for field in ('expires_at', 'available'):
            data = self.bound()
            data['references'][0][field] = '2000-01-01T00:00:00+00:00' if field == 'expires_at' else False
            result = self.call('audit', self.repo, '--input', self.input(data))
            for op in ('status', 'report'):
                saved = self.call(op, result['run_id'], code=1)
                self.assertFalse(saved['current_evidence'])
                self.assertEqual(saved['freshness'], 'current')
                self.assertEqual(saved['expired_evidence'] if field == 'expires_at' else saved['unavailable_evidence'], ['inspection'])
        result = self.call('audit', self.repo)
        shutil.rmtree(self.repo / '.git')
        for op in ('status', 'report'):
            saved = self.call(op, result['run_id'], code=1)
            self.assertEqual(saved['freshness'], 'unavailable')
            self.assertFalse(saved['current_evidence'])

    def test_rejected_bindings_make_status_and_report_non_success(self):
        for mismatch in ('head_sha', 'snapshot_sha256', 'missing_identity', 'run_id', 'attempt', 'check_environment'):
            with self.subTest(mismatch=mismatch):
                data = self.bound()
                if mismatch in ('head_sha', 'snapshot_sha256'):
                    data['identity'][mismatch] = 'd' * len(data['identity'][mismatch])
                    expected = 'source_binding_mismatch'
                elif mismatch == 'missing_identity':
                    del data['identity']
                    data['runs'] = [run([node('unit', 30)])]
                    expected = 'source_binding_mismatch'
                elif mismatch == 'check_environment':
                    data['checks'] = [{'environment': 'other'}]
                    expected = 'artifact_identity_mismatch'
                else:
                    data['artifacts'] = [{**data['identity'], mismatch: 2 if mismatch == 'attempt' else 'other'}]
                    expected = 'artifact_identity_mismatch'
                result = self.call('audit', self.repo, '--input', self.input(data))
                record = json.loads(Path(result['audit']).read_text())
                self.assertEqual(record['completion'], 'complete')
                for op in ('status', 'report'):
                    saved = self.call(op, result['run_id'], code=1)
                    self.assertEqual(saved['completion'], 'complete')
                    self.assertEqual(saved['freshness'], 'current')
                    self.assertFalse(saved['current_evidence'])
                    self.assertIn(expected, saved['evidence_rejections'])
                self.assertIn(expected, record['analysis']['evidence_rejections'])

    def test_unmeasured_advisory_and_repository_gap_are_successful_completed_audits(self):
        for data in (None, self.bound()):
            with self.subTest(measured=data is not None):
                if data is not None:
                    data['runs'] = [run([node('restore', 650)])]
                args = ('--input', self.input(data)) if data is not None else ()
                result = self.call('audit', self.repo, *args)
                record = json.loads(Path(result['audit']).read_text())
                self.assertEqual(record['analysis']['findings'][1]['state'], 'gap' if data else 'unknown')
                for op in ('status', 'report'):
                    saved = self.call(op, result['run_id'])
                    self.assertEqual(saved['evidence_rejections'], [])
                    self.assertEqual(saved['current_evidence'], data is not None)

    def test_saved_records_without_rejection_metadata_use_saved_bindings(self):
        data = self.bound()
        data['artifacts'] = [{**data['identity'], 'attempt': 2}]
        result = self.call('audit', self.repo, '--input', self.input(data))
        record = json.loads(Path(result['audit']).read_text())
        del record['analysis']['evidence_rejections']
        self.state = self.base / 'legacy-state'
        self.state.mkdir(mode=0o700)
        helper.save(self.state, record, self.repo)
        for op in ('status', 'report'):
            saved = self.call(op, result['run_id'], code=1)
            self.assertEqual(saved['evidence_rejections'], ['artifact_identity_mismatch'])
        _, _, unchanged = helper.verify(self.state, result['run_id'])
        self.assertNotIn('evidence_rejections', unchanged['analysis'])

    def test_busy_state_is_scope_blocked_not_invalid_input(self):
        import fcntl
        self.state.mkdir(mode=0o700)
        with (self.state / '.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.call('audit', self.repo, code=1)
        self.assertEqual(result['completion'], 'blocked')
        self.assertIn('temporarily unavailable', result['error'])

    def test_partly_inspected_sample_is_not_presented_as_complete(self):
        data = self.bound()
        data.update(groups=[{'id': 'unit'}, {'id': 'restore', 'tags': ['critical']}], inspected_groups=['unit'])
        result = self.call('audit', self.repo, '--input', self.input(data))
        record = json.loads(Path(result['audit']).read_text())
        self.assertEqual(record['scope']['test_value_assessment'], 'incomplete')
        self.assertEqual(record['analysis']['sample']['omitted'], ['restore'])

    def test_execution_publication_and_model_admission_boundaries(self):
        data = self.bound(); data['execution'] = [{'argv': ['python3', 'test_contract.py'], 'cwd': '.',
            'timeout_seconds': 5, 'prerequisites': ['disposable fixture'], 'authorization': 'fixture scope',
            'exit_code': 1, 'duration_seconds': 1, 'cleanup': 'nothing created'}]
        self.call('audit', self.repo, '--input', self.input(data), code=2)
        report = self.call('audit', self.repo, '--input', self.input(data), '--run-checks')
        self.assertFalse((self.repo / 'must-not-run').exists())
        self.assertEqual(json.loads(Path(report['audit']).read_text())['input']['execution'][0]['exit_code'], 1)
        data['execution'][0]['production'] = True
        self.call('audit', self.repo, '--input', self.input(data), '--run-checks', code=2)
        data.pop('execution'); data['groups'] = [group()]; data['inspected_groups'] = ['restore']
        self.assertIn('model-selection', self.call('audit', self.repo, '--input', self.input(data), code=2)['error'])
        from tests.upfront_fixtures import chosen
        selection = chosen('tests-omg/audit', 'Private advisory report')
        data['selection_context'] = {'record': selection, 'selection_sha256': selection['selection_sha256'],
                                     'invocation_id': selection['invocation_id'], 'scope_id': selection['scope_id']}
        self.call('audit', self.repo, '--input', self.input(data))
        p = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'), 'publish'], capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 2)
        self.assertIn('invalid choice', p.stderr)
        data.pop('groups'); data.pop('selection_context')
        data['strategy'] = {'snapshot_sha256': 'a' * 64}
        self.assertIn('planning receipt', self.call('audit', self.repo, '--input', self.input(data), code=2)['error'])

    def test_authored_audit_requires_its_scoped_agreement_and_retains_it_on_resume(self):
        from shared import model_selection
        from tests.model_selection_fixtures import selection_input
        from tests.upfront_fixtures import agree, chosen
        data = self.bound()
        data.update(groups=[group()], inspected_groups=['restore'])

        def bind(selection):
            data['selection_context'] = {'record': selection, 'selection_sha256': selection['selection_sha256'],
                'invocation_id': selection['invocation_id'], 'scope_id': selection['scope_id']}

        # A format-valid internal selection or another public operation cannot
        # supply authority for this audit, even if it has work/review choices.
        for selection in (model_selection.freeze(selection_input()), chosen('ape/study'),
                          chosen('tests-omg/doctor')):
            bind(selection)
            self.call('audit', self.repo, '--input', self.input(data), code=2)

        raw = selection_input(); raw['operation'] = 'ape/study'
        agree(raw, operations=['ape/study', 'tests-omg/audit'])
        selected = model_selection.freeze(raw)
        bind(selected)
        first = self.call('audit', self.repo, '--input', self.input(data))
        saved = json.loads(Path(first['audit']).read_text())
        self.assertEqual(saved['input']['selection_context'], data['selection_context'])
        resumed = self.call('audit', self.repo, '--input', self.input(data), '--resume', first['run_id'])
        saved = json.loads(Path(resumed['audit']).read_text())
        self.assertEqual(saved['input']['selection_context'], data['selection_context'])
        self.assertEqual(saved['analysis']['recommendations'][0]['action'], 'keep')
        self.call('status', resumed['run_id'])
        self.call('report', resumed['run_id'])

    def test_org_visibility_pagination_errors_and_archived_unclassified_repos(self):
        data = {'org': {'owner': 'example', 'pages': [
            {'page': 1, 'repos': [{'name': 'example/archived', 'archived': True}], 'next_page': 2},
            {'page': 2, 'error': '403 history/list access denied'}]}}
        r = self.call('audit', '--org', 'example', '--input', self.input(data), code=1)
        scope = json.loads(Path(r['audit']).read_text())['scope']
        self.assertEqual(scope['denominator_state'], 'unknown')
        self.assertFalse(scope['fleet_wide'])
        self.assertTrue(scope['inventory'][0]['archived'])
        self.assertEqual(scope['inventory'][0]['classification'], 'unknown')
        self.assertEqual(scope['results'][0]['test_value_assessment'], 'incomplete')
        record = json.loads(Path(r['audit']).read_text())
        self.assertEqual(record['analysis']['findings'], [])
        self.assertIn('Test-value assessment incomplete', Path(r['report']).read_text())
        data['org'].update(expected_repos=['example/archived', 'example/private'], expected_source='owner supplied scope')
        r = self.call('audit', '--org', 'example', '--input', self.input(data), code=1)
        scope = json.loads(Path(r['audit']).read_text())['scope']
        self.assertEqual(scope['denominator_state'], 'gap')
        self.assertEqual(scope['missing_repositories'], ['example/private'])

    def test_org_html_findings_belong_to_repositories_not_an_aggregate(self):
        data = self.bound(); snap = self.call('audit', self.repo, '--snapshot')
        data.update(groups=[{'id': 'unit'}], inspected_groups=['unit'], history={'runs_complete': True, 'bugs_accessible': True})
        evidence = {'org': {'owner': 'example', 'expected_repos': ['example/a'], 'expected_source': 'owner scope',
                           'pages': [{'page': 1, 'repos': [{'name': 'example/a', 'classification': 'cli'}], 'next_page': None}]},
                    'repositories': {'example/a': {'snapshot': snap, 'evidence': data}}}
        result = self.call('audit', '--org', 'example', '--input', self.input(evidence))
        audit = json.loads(Path(result['audit']).read_text())
        self.assertEqual(audit['analysis']['findings'], [])
        self.assertEqual(len(audit['scope']['results'][0]['analysis']['findings']), 12)
        html = Path(result['report']).read_text()
        self.assertIn('<h3>example/a</h3>', html)
        self.assertNotIn('<h2>Twelve findings</h2>', html)
        self.assertNotIn('<h2>Ten-minute validation path</h2>', html)
        self.assertIn('Inventory denominator: meets', html)
        self.assertEqual(html.count('<th scope="row">TEST-'), 12)
        for op in ('status', 'report'):
            saved = self.call(op, result['run_id'])
            self.assertEqual(saved['evidence_rejections'], [])
            self.assertEqual(saved['freshness'], 'unknown')
        evidence['repositories']['example/a']['snapshot']['sha256'] = 'd' * 64
        evidence['repositories']['example/a']['evidence']['identity']['snapshot_sha256'] = 'd' * 64
        resumed = self.call('audit', '--org', 'example', '--input', self.input(evidence), '--resume', result['run_id'], code=2)
        self.assertIn('source/scope changed', resumed['error'])

    def test_org_budget_exhaustion_and_missing_page_are_partial(self):
        data = {'org': {'owner': 'example', 'pages': [{'page': 1, 'repos': [
            {'name': 'example/a'}, {'name': 'example/b'}], 'next_page': None}]}}
        r = self.call('audit', '--org', 'example', '--repo-budget', 1, '--input', self.input(data), code=1)
        scope = json.loads(Path(r['audit']).read_text())['scope']
        self.assertEqual(len(scope['inventory']), 2)
        self.assertIn('repository audit budget exhausted', scope['errors'])
        data['org']['pages'][0]['page'] = 2
        self.call('audit', '--org', 'example', '--input', self.input(data), code=1)
        self.call('audit', '--org', 'example', '--input', self.input(data), '--run-checks', code=2)

    def test_org_run_history_failure_prevents_complete_fleet_claim(self):
        data, snap = fixture()
        data.update(groups=[{'id': 'unit'}], inspected_groups=['unit'],
                    history={'runs_complete': False, 'errors': ['403 on attempts page 2']})
        result = helper.inventory('example', {
            'org': {'owner': 'example', 'expected_repos': ['example/a'], 'expected_source': 'owner scope',
                    'pages': [{'page': 1, 'repos': [{'name': 'example/a', 'classification': 'cli'}], 'next_page': None}]},
            'repositories': {'example/a': {'snapshot': snap, 'evidence': data}}}, 10, 120)
        self.assertEqual(result['completion'], 'partial')
        self.assertEqual(result['denominator_state'], 'unknown')
        self.assertFalse(result['fleet_wide'])
        self.assertIn('run/job/attempt history incomplete: example/a', result['errors'])

    def test_org_incident_access_and_selected_sample_limit_fleet_completeness(self):
        data, snap = fixture()
        data.update(groups=[{'id': 'unit'}], inspected_groups=['unit'])
        evidence = {'org': {'owner': 'example', 'expected_repos': ['example/a'], 'expected_source': 'owner scope',
                            'pages': [{'page': 1, 'repos': [{'name': 'example/a', 'classification': 'cli'}], 'next_page': None}]},
                    'repositories': {'example/a': {'snapshot': snap, 'evidence': data}}}
        for bugs_accessible in (False, None, True):
            data['history']['bugs_accessible'] = bugs_accessible
            result = helper.inventory('example', evidence, 10, 120)
            self.assertEqual(result['completion'], 'complete' if bugs_accessible else 'partial')
            self.assertEqual(result['denominator_state'], 'meets' if bugs_accessible else 'unknown')
            self.assertEqual(result['fleet_wide'], bool(bugs_accessible))
            if not bugs_accessible:
                self.assertIn('incident/fix history inaccessible: example/a', result['errors'])
        data['groups'].append({'id': 'restore', 'tags': ['critical']})
        result = helper.inventory('example', evidence, 10, 120)
        self.assertEqual(result['completion'], 'partial')
        self.assertFalse(result['fleet_wide'])

    def test_state_inside_repo_symlinks_and_invalid_json_are_refused(self):
        self.state = self.repo / 'forbidden-state'
        self.call('audit', self.repo, code=2)
        self.assertFalse(self.state.exists())
        real = self.base / 'real-state'; real.mkdir(mode=0o700)
        self.state = self.base / 'linked'; self.state.symlink_to(real, target_is_directory=True)
        self.call('audit', self.repo, code=2)
        self.state = self.base / 'state'
        path = self.input({}); path.write_text('{"schema_version":1,"schema_version":1}')
        self.call('audit', self.repo, '--input', path, code=2)

    def test_installed_relocated_operation_outside_source_and_skill_adapter(self):
        prefix, agents, skills = (self.base / p for p in ('prefix', 'agents', 'skills'))
        cli = [sys.executable, str(ROOT / 'bin/t3-plugins'), '--prefix', str(prefix), '--agents-root', str(agents)]
        p = subprocess.run([*cli, 'setup', 'tests-omg', '--root', str(skills)], cwd=self.base,
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        adapter = (skills / 't3-tests-omg/SKILL.md').read_text()
        self.assertIn('audit', adapter)
        self.assertIn('tests-omg', adapter)
        current = (prefix / 'tests-omg/current').resolve()
        moved = self.base / 'moved-package'; shutil.copytree(current, moved)
        self.assertTrue(self.call('doctor', script=moved / 'scripts/audit.py')['installed_receipt'])
        result = self.call('audit', self.repo, script=moved / 'scripts/audit.py')
        self.assertTrue(Path(result['report']).is_file())
        self.call('report', result['run_id'], script=moved / 'scripts/audit.py')
        from tests.upfront_fixtures import chosen
        selected = chosen('tests-omg/audit', 'Private advisory report')
        data = self.bound()
        data.update(groups=[group()], inspected_groups=['restore'], selection_context={
            'record': selected, 'selection_sha256': selected['selection_sha256'],
            'invocation_id': selected['invocation_id'], 'scope_id': selected['scope_id']})
        authored = self.call('audit', self.repo, '--input', self.input(data), script=moved / 'scripts/audit.py')
        saved = json.loads(Path(authored['audit']).read_text())
        self.assertEqual(saved['input']['selection_context']['record']['agreement'], selected['agreement'])
        self.assertEqual(saved['analysis']['recommendations'][0]['action'], 'keep')
        self.call('report', authored['run_id'], script=moved / 'scripts/audit.py')
        (moved / 'scripts/analysis.py').write_text('# damaged')
        p = subprocess.run([sys.executable, str(moved / 'scripts/audit.py'), 'doctor'], cwd=self.base,
                           capture_output=True, text=True, env=self.env, timeout=15)
        self.assertNotEqual(p.returncode, 0)


if __name__ == '__main__':
    unittest.main()
