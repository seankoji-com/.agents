"""Optional reviews: offline pricing, lifetime, gate isolation and installed CLI.

Synthetic host observations and offline published-wording fixtures only.
No provider or GitHub calls. Published examples are not a supported model roster.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import supplemental_reviews as reviews
from tests.test_rebuild_installed import Sandbox

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture(now=NOW):
    models = ['opencode/sample-a-free', 'opencode/sample-b-free', 'opencode/sample-c-free',
              'opencode/sample-d-free', 'opencode/paid', 'opencode-go/included']
    stamp = now.isoformat()
    return {
        'exclude_models': ['fixture/primary-reviewer', 'fixture/implementer'],
        'permissions': {'delegate': True, 'share_with_opencode': True, 'material': 'public'},
        'catalog_observed_at': stamp,
        'delegate_task_schema': {
            'observed_at': stamp,
            'input_schema': {'properties': {'isolation': {'anyOf': [
                {'description': 'Defaults to shared. Worktree isolation starts from the parent local commit.',
                 'enum': ['shared', 'worktree'], 'type': 'string'}, {'type': 'null'}]}}},
            'evidence': 'Synthetic schema: isolated worktree from parent local commit; runs setup; no dirty edits copied'},
        'workspace': {'observed_at': stamp, 'head_revision': 'a' * 40, 'clean': True, 'scope_committed': True},
        'capabilities': {
            'runtimeMode': 'full-access', 'inheritedProviderInstanceId': 'parent', 'parentThreadId': 'parent-thread',
            'features': {'appOwnedSubagents': True, 'asyncPolling': True, 'cancellation': True},
            'providers': [{'providerInstanceId': 'gateway', 'driverKind': 'opencode',
                           'canRunChildTask': True, 'canRunCrossProviderChildTask': True,
                           'constraints': [], 'runtimeModes': ['auto', 'full-access'],
                           'models': [{'id': m} for m in models]}]},
        'pricing': [{'model': m, 'source': reviews.SOURCES[m.split('/')[0]], 'observed_at': stamp,
                     'all_charges_covered': True, 'eligible': True,
                     'costs': {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'request': 0},
                     'data_use': {'source': reviews.SOURCES['opencode'], 'observed_at': stamp,
                                  'no_training': True, 'prompt_logging': False,
                                  'confidential_allowed': None, 'retention': 'zero',
                                  'evidence': 'Synthetic terms: no training or retained prompt logs; zero retention; confidentiality unspecified'},
                     'evidence': 'Synthetic official row mapped to exact ID; all charges covered'} for m in models[:4]],
        'context': {'round_id': 'job-fixture/review-1', 'revision': 'a' * 40,
                    'tree_hash': 'd' * 64,
                    'base_revision': 'b' * 40, 'base_ref': 'origin/trunk',
                    'scope': 'Synthetic repository combined diff; inspect source and callers',
                    'constraints': 'Read only. No live calls. Preserve unrelated work.',
                    'permissions': 'Authorised read-only review; fixture sharing allowed.',
                    'prior_feedback': 'None'},
    }


def observation(state, status='completed', summary=None, task='task-fixture'):
    request = state['requests'][0]
    if summary is None:
        summary = json.dumps({'revision': 'a' * 40, 'base_revision': 'b' * 40,
                              'coverage': 'Inspected synthetic source and callers',
                              'findings': [{'severity': 'major', 'path': 'module.py', 'line': 3,
                                            'evidence': 'Fixture reproduces missing validation',
                                            'suggestion': 'Validate the input'}]})
    return {'request_id': request['request_id'], 'kind': 'status',
            'current_tree_hash': 'd' * 64,
            'current_revision': 'a' * 40, 'current_base_revision': 'b' * 40,
            'observation': {'taskId': task, 'childThreadId': 'child-fixture', 'childRunId': 'run-fixture',
                            **request['dispatch']['target'], 'status': status, 'workState': 'result_available',
                            'hasPendingChildRuns': False, 'summary': summary}}


class SelectionTest(unittest.TestCase):
    def test_nullable_live_isolation_schema_and_known_alternatives(self):
        # The default fixture retains the nullable anyOf shape reported by T3.
        self.assertEqual(len(reviews.select(fixture(), NOW)[0]), 3)
        for isolation in (
                {'type': 'string', 'enum': ['shared', 'worktree']},
                {'enum': ['shared', 'worktree']},
                {'oneOf': [{'type': 'string', 'enum': ['shared', 'worktree']}, {'type': 'null'}]}):
            data = fixture()
            data['delegate_task_schema']['input_schema']['properties']['isolation'] = isolation
            self.assertEqual(len(reviews.select(data, NOW)[0]), 3)
        for isolation in (
                {'anyOf': [{'type': 'string', 'enum': ['shared']}, {'type': 'null'}]},
                {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                {'anyOf': [{'enum': ['worktree']}, {'$ref': '#/unknown'}]},
                {'anyOf': [{'enum': ['worktree']}], 'not': {'enum': ['worktree']}},
                {'enum': ['shared', 'worktree'], 'allOf': [{'enum': ['shared']}]},
                {'oneOf': [{'enum': ['worktree']}, {'enum': ['worktree']}]},
                {'$ref': '#/worktree'}, {'anyOf': []}, {'anyOf': None}, None):
            data = fixture()
            data['delegate_task_schema']['input_schema']['properties']['isolation'] = isolation
            self.assertEqual(reviews.select(data, NOW), ([], [{'reason': 'worktree-isolation-unavailable'}]))

    def test_worktree_support_requires_fresh_live_schema_not_catalog_flags(self):
        for change in (
                lambda d: d.pop('delegate_task_schema'),
                lambda d: d['delegate_task_schema'].update(evidence=''),
                lambda d: d['delegate_task_schema'].update(observed_at=(NOW - timedelta(minutes=6)).isoformat()),
                lambda d: d['delegate_task_schema'].update(observed_at=(NOW + timedelta(seconds=1)).isoformat()),
                lambda d: d['delegate_task_schema']['input_schema']['properties'].pop('isolation'),
                lambda d: d['delegate_task_schema']['input_schema']['properties']['isolation'].update(enum=['shared'])):
            data = fixture()
            change(data)
            data['capabilities']['features']['worktreeIsolation'] = True  # Not a real capability proof.
            selected, skipped = reviews.select(data, NOW)
            self.assertEqual(selected, [])
            self.assertEqual(skipped, [{'reason': 'worktree-isolation-unavailable'}])

    def test_dirty_uncommitted_stale_or_different_parent_scope_skips(self):
        for change in (
                lambda d: d.pop('workspace'),
                lambda d: d['workspace'].update(clean=False),
                lambda d: d['workspace'].update(scope_committed=False),
                lambda d: d['workspace'].update(head_revision='c' * 40),
                lambda d: d['workspace'].update(observed_at=(NOW - timedelta(minutes=6)).isoformat()),
                lambda d: d['workspace'].pop('head_revision')):
            data = fixture()
            change(data)
            state = reviews.prepare(data, NOW)
            self.assertEqual(state['requests'], [])
            self.assertEqual(state['skipped'], [{'reason': 'uncommitted-or-unavailable-scope'}])

    def test_data_use_must_be_observed_and_allowed_or_explicitly_authorized_for_round(self):
        for change, reason in (
                (lambda p: p.pop('data_use'), 'data-use-unverified'),
                (lambda p: p['data_use'].update(no_training=None), 'data-use-unverified'),
                (lambda p: p['data_use'].update(observed_at='old'), 'data-use-unverified'),
                (lambda p: p['data_use'].update(no_training=False), 'data-use-disallowed'),
                (lambda p: p['data_use'].update(prompt_logging=True), 'data-use-disallowed'),
                (lambda p: p['data_use'].pop('confidential_allowed'), 'data-use-unverified'),
                (lambda p: p['data_use'].update(retention='30 days'), 'data-use-disallowed')):
            data = fixture()
            data['pricing'] = data['pricing'][:1]
            change(data['pricing'][0])
            selected, skipped = reviews.select(data, NOW)
            self.assertEqual(selected, [])
            self.assertIn(reason, [s['reason'] for s in skipped])
        data['permissions']['data_use_exceptions'] = [{
            'model': data['pricing'][0]['model'], 'round_id': data['context']['round_id'],
            'terms_sha256': reviews.digest(data['pricing'][0]['data_use']),
            'authorization': 'Synthetic owner explicitly permits these observed retention terms for this round'}]
        self.assertEqual(len(reviews.select(data, NOW)[0]), 1)
        for key in ('round_id', 'model', 'terms_sha256', 'authorization'):
            changed = deepcopy(data)
            changed['permissions']['data_use_exceptions'][0][key] = ''
            self.assertEqual(reviews.select(changed, NOW)[0], [])

    def test_public_and_confidential_material_require_different_permissions(self):
        data = fixture()
        data['pricing'] = data['pricing'][:1]
        self.assertEqual(len(reviews.select(data, NOW)[0]), 1)
        for material in (None, 'unknown', False):
            changed = deepcopy(data)
            changed['permissions']['material'] = material
            self.assertIn('data-use-unverified', [r['reason'] for r in reviews.select(changed, NOW)[1]])
        data['permissions']['material'] = 'confidential'
        terms = data['pricing'][0]['data_use']
        for allowed in (None, False):
            terms['confidential_allowed'] = allowed
            data['permissions']['data_use_exceptions'] = [{
                'model': data['pricing'][0]['model'], 'round_id': data['context']['round_id'],
                'terms_sha256': reviews.digest(terms), 'authorization': 'Owner accepts observed data-use terms'}]
            self.assertIn('data-use-disallowed', [r['reason'] for r in reviews.select(data, NOW)[1]])
        terms.update(confidential_allowed=True, evidence='Synthetic affirmative provider permission for confidential use')
        self.assertEqual(len(reviews.select(data, NOW)[0]), 1)
        # A restriction on confidential material does not itself prohibit public use.
        data['permissions']['material'] = 'public'
        terms['confidential_allowed'] = False
        self.assertEqual(len(reviews.select(data, NOW)[0]), 1)

    def test_published_public_free_rows_and_model_specific_privacy_exceptions(self):
        # Offline excerpts from the Console models page, observed 16 October 2026.
        # Runtime selection contains no model names or privacy inference scraper.
        data = fixture()
        models = ['opencode/deepseek-v4.1-flash-free', 'opencode/cat-jam-free',
                  'opencode/nemotron-3.5-super-vl-free']
        data['capabilities']['providers'][0]['models'] = [{'id': m} for m in models]
        data['pricing'] = data['pricing'][:3]
        for proof, model in zip(data['pricing'], models):
            proof.update(model=model,
                         price_cells={'input': 'Free', 'output': 'Free', 'cache_read': 'Free', 'cache_write': '-'},
                         costs={'input': 0, 'output': 0, 'cache_read': 0},
                         evidence='Free | Free | Free | -; page says "You are charged per request"; '
                                  'listed token prices apply per request, no separate request fee listed')
        data['pricing'][0]['data_use']['evidence'] = (
            '"zero-retention policy and does not use your data for model training"; '
            'the same model has no privacy exception; no confidentiality permission stated')
        data['pricing'][1]['data_use'].update(
            retention='30 days', prompt_logging=True,
            evidence='Cat Jam: inputs excluded from training; retained for 30 days for safety')
        data['pricing'][2]['data_use'].update(
            no_training=False, prompt_logging=True, confidential_allowed=False, retention='logged; duration unspecified',
            evidence='Nemotron trial: "do not submit personal or confidential data"; '
                     'sessions logged for security and product improvement')
        selected, skipped = reviews.select(data, NOW)
        self.assertEqual([r['target']['model'] for r in selected], models[:1])
        self.assertEqual([(r.get('model'), r['reason']) for r in skipped],
                         [(m, 'data-use-disallowed') for m in models[1:]])
        data['permissions']['material'] = 'confidential'
        self.assertEqual(reviews.select(data, NOW)[0], [])
        data['permissions']['material'] = 'public'
        data['pricing'][0]['price_cells']['output'] = '$0.01'
        self.assertEqual(reviews.select(data, NOW)[0], [])

    def test_official_table_shaped_cells_map_free_and_inapplicable_cache_only(self):
        data = fixture()
        data['pricing'] = data['pricing'][:1]
        proof = data['pricing'][0]
        proof.update(price_cells={'input': 'Free', 'output': 'Free', 'cache_read': 'Free', 'cache_write': '-'},
                     costs={'input': 0, 'output': 0, 'cache_read': 0},
                     evidence='Synthetic table row: Free | Free | Free | -; listed prices apply per request; no request fee listed')
        self.assertEqual(len(reviews.select(data, NOW)[0]), 1)
        proof['price_cells']['cache_read'] = '-'
        proof['costs'].pop('cache_read')
        self.assertEqual(len(reviews.select(data, NOW)[0]), 1)
        for key in ('input', 'output', 'cache_read', 'cache_write'):
            changed = deepcopy(data)
            changed['pricing'][0]['price_cells'][key] = '$0.01'
            self.assertEqual(reviews.select(changed, NOW)[0], [])
        proof['price_cells']['input'] = '-'
        self.assertEqual(reviews.select(data, NOW)[0], [])

    def test_primary_models_excluded_and_duplicate_and_cap_skips_recorded(self):
        data = fixture()
        data['exclude_models'] = ['opencode-go/SAMPLE-A', 'sample-b-free']
        selected, skipped = reviews.select(data, NOW)
        self.assertEqual(len(selected), 2)
        self.assertEqual(sum(s['reason'] == 'primary-lineage' for s in skipped), 2)
        data.pop('exclude_models')
        self.assertEqual(reviews.select(data, NOW)[0], [])
        data = fixture()
        duplicate = deepcopy(data['capabilities']['providers'][0])
        duplicate['providerInstanceId'] = 'another'
        data['capabilities']['providers'].append(duplicate)
        _, skipped = reviews.select(data, NOW)
        self.assertEqual(sum(s['reason'] == 'duplicate-model' for s in skipped), 4)
        self.assertEqual(sum(s['reason'] == 'round-cap' for s in skipped), 1)

    def test_dynamic_selection_three_total_and_no_fixed_roster(self):
        data = fixture()
        selected, skipped = reviews.select(data, NOW)
        self.assertEqual([r['target']['model'] for r in selected],
                         ['opencode/sample-a-free', 'opencode/sample-b-free', 'opencode/sample-c-free'])
        self.assertTrue(any(r.get('model') == 'opencode-go/included' for r in skipped))
        # Another instance and the Go alias must not increase the cap or repeat a model.
        other = deepcopy(data['capabilities']['providers'][0])
        other['providerInstanceId'] = 'another-gateway'
        data['capabilities']['providers'].insert(0, other)
        alias = deepcopy(data['pricing'][0])
        alias.update(model='opencode-go/sample-a', source=reviews.SOURCES['opencode-go'])
        data['pricing'].append(alias)
        other['models'].append({'id': alias['model']})
        selected, _ = reviews.select(data, NOW)
        self.assertEqual(len(selected), 3)
        self.assertEqual(len({r['target']['model'].split('/')[1].removesuffix('-free') for r in selected}), 3)
        data['capabilities']['providers'].reverse()
        self.assertEqual(reviews.select(data, NOW)[0], selected)

    def test_permissions_runnable_modes_features_and_freshness_fail_closed(self):
        changes = [lambda d: d.update(enabled=False),
                   lambda d: d['permissions'].update(delegate=False),
                   lambda d: d['permissions'].update(share_with_opencode=False),
                   lambda d: d['capabilities'].update(runtimeMode='auto'),
                   lambda d: d['capabilities'].update(inheritedProviderInstanceId=None),
                   lambda d: d['capabilities'].update(parentThreadId=None),
                   lambda d: d['capabilities']['features'].update(cancellation=False),
                   lambda d: d['capabilities']['providers'][0].update(canRunChildTask=False),
                   lambda d: d['capabilities']['providers'][0].update(canRunCrossProviderChildTask=False),
                   lambda d: d['capabilities']['providers'][0].update(runtimeModes=None),
                   lambda d: d['capabilities']['providers'][0].update(runtimeModes='full-access'),
                   lambda d: d['capabilities']['providers'][0].update(constraints=['disabled']),
                   lambda d: d.update(catalog_observed_at=(NOW - timedelta(minutes=6)).isoformat()),
                   lambda d: d.update(catalog_observed_at=(NOW + timedelta(seconds=1)).isoformat())]
        for change in changes:
            data = fixture()
            change(data)
            with self.subTest(change=change):
                self.assertEqual(reviews.select(data, NOW)[0], [])
        data = fixture()
        data['capabilities']['inheritedProviderInstanceId'] = 'gateway'
        data['capabilities']['providers'][0]['canRunCrossProviderChildTask'] = False
        self.assertEqual(len(reviews.select(data, NOW)[0]), 3)

    def test_pricing_requires_explicit_fresh_all_zero_evidence_for_exact_namespace(self):
        changes = [lambda p: p.update(costs={'input': .1, 'output': 0}),
                   lambda p: p['costs'].update(cache_write=.1),
                   lambda p: p['costs'].update(request=.1),
                   lambda p: p['costs'].update(input=False),
                   lambda p: p.update(costs={'output': 0}),
                   lambda p: p.update(all_charges_covered=False),
                   lambda p: p.update(eligible=False),
                   lambda p: p.update(source='https://invalid.example/pricing'),
                   lambda p: p.update(source=reviews.SOURCES['opencode-go']),
                   lambda p: p.update(observed_at=(NOW - timedelta(minutes=6)).isoformat()),
                   lambda p: p.update(evidence='')]
        for change in changes:
            data = fixture()
            data['pricing'] = data['pricing'][:1]
            change(data['pricing'][0])
            self.assertEqual(reviews.select(data, NOW)[0], [])
        data = fixture()
        data['pricing'] = []
        self.assertEqual(reviews.select(data, NOW)[0], [], 'a -free suffix alone is insufficient')
        proof = deepcopy(fixture()['pricing'][0])
        proof.update(model='opencode-go/included', source=reviews.SOURCES['opencode-go'])
        data['pricing'] = [proof]
        self.assertEqual(reviews.select(data, NOW)[0][0]['target']['model'], 'opencode-go/included')
        data['pricing'].append(deepcopy(proof))
        self.assertEqual(reviews.select(data, NOW)[0], [], 'conflicting or duplicate pricing is uncertain')
        for advertised in ({'input': 1, 'output': 0}, {'free': True}, None):
            data = fixture()
            data['pricing'] = data['pricing'][:1]
            data['capabilities']['providers'][0]['models'][0]['cost'] = advertised
            self.assertEqual(reviews.select(data, NOW)[0], [], 'conflicting/unknown catalog prices skip')


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.state = reviews.prepare(fixture(), NOW)

    def test_receipt_after_result_preserves_evidence_including_after_close(self):
        event = observation(self.state)
        reviews.record(self.state, event)
        before = deepcopy(self.state['requests'][0]['findings'])
        event['kind'] = 'receipt'
        reviews.record(self.state, event)
        self.assertEqual(self.state['requests'][0]['outcome'], 'untrusted-evidence')
        self.assertEqual(self.state['requests'][0]['findings'], before)
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        reviews.record(self.state, event)
        self.assertEqual(self.state['requests'][0]['findings'], before)
        event['observation']['model'] = 'wrong-model'
        reviews.record(self.state, event)
        self.assertEqual(self.state['requests'][0]['findings'], before)
        self.assertTrue(self.state['requests'][0]['identity_mismatch'])

    def test_later_status_preserves_result_and_disposition_while_updating_liveness(self):
        reviews.record(self.state, observation(self.state))
        request = self.state['requests'][0]
        triage = {'request_id': request['request_id'], 'finding_index': 0,
                  'finding_sha256': reviews.digest(request['findings'][0]), 'revision': 'a' * 40,
                  'disposition': 'confirmed', 'evidence': 'Verified fixture source',
                  'repair_route': 'Ralph stop/report/rerun under remaining budget'}
        reviews.disposition(self.state, triage)
        before = deepcopy(request)
        later = observation(self.state)
        later['observation'].update(hasPendingChildRuns=True, summary='Later child still active')
        reviews.record(self.state, later)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['task-fixture'])
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        for kind in ('status', 'receipt'):
            later = observation(self.state)
            later['kind'] = kind
            later['observation'].update(model='different-model', childRunId='later-run', summary='Unrelated later output')
            reviews.record(self.state, later)
            for key in ('findings', 'result', 'coverage', 'outcome'):
                self.assertEqual(request[key], before[key])
            self.assertEqual(self.state['dispositions'], [triage])
        self.assertTrue(request['identity_mismatch'])
        self.assertTrue(request['run_mismatch'])
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        self.assertEqual(len(request['handles'][0]['observations']), 4)

    def test_one_prose_wrapped_or_fenced_object_and_no_ambiguous_salvage(self):
        raw = observation(self.state)['observation']['summary']
        for wrapped in ('Review complete.\n' + raw + '\nDone.', '```json\n' + raw + '\n```'):
            self.assertEqual(reviews.result(wrapped, self.state['context'])['findings'][0]['line'], 3)
        for raw in (raw + '\n' + raw, '```json\n' + raw + '\n```\n{}',
                    '{ broken ' + raw, raw + '}', '{"revision":1,"revision":2}'):
            with self.assertRaises(ValueError):
                reviews.result(raw, self.state['context'])

    def test_workspace_drift_closes_intake_skips_uningested_and_retains_cleanup(self):
        event = observation(self.state, status='running')
        event.update(current_tree_hash='e' * 64)
        reviews.record(self.state, event)
        self.assertTrue(self.state['closed'])
        self.assertEqual(self.state['workspace_drift']['observed_tree_hash'], 'e' * 64)
        self.assertIn('task-fixture', reviews.overview(self.state)['cancel_task_ids'])
        self.assertTrue(all(r['outcome'] == 'skipped-workspace-drift' for r in self.state['requests']))
        self.assertNotIn('attempt', self.state)
        with self.assertRaises(ValueError):
            data = fixture()
            data['context'].pop('tree_hash')
            reviews.prepare(data, NOW)

    def _ingest_bound_finding(self):
        reviews.record(self.state, observation(self.state))
        request = self.state['requests'][0]
        reviews.disposition(self.state, {
            'request_id': request['request_id'], 'finding_index': 0,
            'finding_sha256': reviews.digest(request['findings'][0]), 'revision': 'a' * 40,
            'disposition': 'confirmed', 'evidence': 'Verified fixture reproduction',
            'repair_route': 'Ralph stop/report/rerun under remaining budget'})
        return deepcopy(request), deepcopy(self.state['dispositions'])

    def _assert_bound_evidence_preserved(self, saved_request, saved_dispositions):
        request = self.state['requests'][0]
        for key in ('result', 'findings', 'coverage', 'outcome'):
            self.assertEqual(request[key], saved_request[key])
        self.assertEqual(self.state['dispositions'], saved_dispositions)
        self.assertEqual(reviews.digest(request['findings'][0]),
                         saved_dispositions[0]['finding_sha256'])
        self.assertTrue(self.state['closed'])
        self.assertTrue(all(r['outcome'].startswith('skipped-') and not r['findings']
                            for r in self.state['requests'][1:]))

    def test_drifted_status_of_another_request_preserves_bound_evidence(self):
        saved = self._ingest_bound_finding()
        event = observation(self.state, status='running', task='other-owned-task')
        other = self.state['requests'][1]
        event.update(request_id=other['request_id'], current_tree_hash='e' * 64)
        event['observation'].update(other['dispatch']['target'])
        reviews.record(self.state, event)
        self._assert_bound_evidence_preserved(*saved)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['other-owned-task'])
        # A completion after drift remains ineligible for intake, but proves stop.
        event['observation']['status'] = 'completed'
        reviews.record(self.state, event)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        self._assert_bound_evidence_preserved(*saved)

    def test_drifted_close_preserves_bound_evidence(self):
        saved = self._ingest_bound_finding()
        reviews.close(self.state, {'current_tree_hash': 'e' * 64})
        self._assert_bound_evidence_preserved(*saved)
        self.assertEqual(self.state['workspace_drift']['observed_tree_hash'], 'e' * 64)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])

    def test_clean_close_is_idempotent_after_tree_changes_or_missing_hash(self):
        saved = self._ingest_bound_finding()
        rejected = self.state['requests'][2]
        reviews.record(self.state, {'request_id': rejected['request_id'], 'kind': 'launch-rejected'})
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        closed = deepcopy(self.state)
        self.assertEqual([r['outcome'] for r in self.state['requests']],
                         ['untrusted-evidence', 'skipped-round-ended', 'skipped-launch-rejected'])
        for event in ({'current_tree_hash': 'f' * 64}, {}, {'current_tree_hash': None}):
            reviews.close(self.state, event)
            self.assertEqual(self.state, closed)
            self.assertIsNone(reviews.overview(self.state)['workspace_drift'])
        self._assert_bound_evidence_preserved(*saved)

    def test_drift_preserves_terminal_skip_reasons_and_first_observation(self):
        for kind in ('launch-rejected', 'not-dispatched', 'launch-error', 'identity-mismatch', 'malformed'):
            with self.subTest(kind=kind):
                state = reviews.prepare(fixture(), NOW)
                request = state['requests'][0]
                event = observation(state)
                if kind in ('identity-mismatch', 'malformed'):
                    event['observation'].update(model='wrong-model' if kind == 'identity-mismatch'
                                                else request['dispatch']['target']['model'], summary='invalid')
                    reviews.record(state, event)
                else:
                    reviews.record(state, {'request_id': request['request_id'], 'kind': kind})
                terminal = request['outcome']
                reviews.close(state, {'current_tree_hash': 'e' * 64})
                self.assertEqual(request['outcome'], terminal)
                self.assertEqual([r['outcome'] for r in state['requests'][1:]],
                                 ['skipped-workspace-drift'] * 2)
                closed = deepcopy(state)
                for event in ({'current_tree_hash': 'f' * 64}, {}, {'current_tree_hash': 'd' * 64}):
                    reviews.close(state, event)
                    self.assertEqual(state, closed)
                    # Direct callers also cannot replace the first drift observation.
                    self.assertFalse(reviews.check_tree(state, event))
                    self.assertEqual(state, closed)
                for late_kind in ('receipt', 'status'):
                    late = observation(state, status='running', task='late-owned-task')
                    late.update(kind=late_kind, current_tree_hash='f' * 64)
                    reviews.record(state, late)
                    self.assertEqual(request['outcome'], terminal)
                    self.assertEqual(reviews.overview(state)['cancel_task_ids'], ['late-owned-task'])
                late['observation']['status'] = 'cancelled'
                reviews.record(state, late)
                self.assertEqual(request['outcome'], terminal)
                self.assertEqual(reviews.overview(state)['cancel_task_ids'], [])
                self.assertEqual(state['workspace_drift'], closed['workspace_drift'])

    def test_late_observations_keep_closed_outcomes_and_owned_handles(self):
        saved = self._ingest_bound_finding()
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        request = self.state['requests'][1]
        for kind in ('receipt', 'status'):
            late = observation(self.state, status='running', task='late-owned-task')
            late.update(request_id=request['request_id'], kind=kind, current_tree_hash='f' * 64)
            late['observation'].update(request['dispatch']['target'])
            reviews.record(self.state, late)
            self.assertEqual(request['outcome'], 'skipped-round-ended')
            self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['late-owned-task'])
            self.assertIsNone(reviews.overview(self.state)['workspace_drift'])
            self._assert_bound_evidence_preserved(*saved)
        for kind in ('launch-error', 'launch-rejected', 'not-dispatched'):
            reviews.record(self.state, {'request_id': request['request_id'], 'kind': kind})
            self.assertEqual(request['outcome'], 'skipped-round-ended')
        reviews.record(self.state, {'request_id': request['request_id'],
                                    'kind': 'cancel-requested', 'task_id': 'late-owned-task'})
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['late-owned-task'])
        late['observation']['status'] = 'cancelled'
        reviews.record(self.state, late)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        self.assertEqual(request['outcome'], 'skipped-round-ended')
        self.assertEqual(len(request['handles'][0]['observations']), 3)
        self._assert_bound_evidence_preserved(*saved)

    def test_drifted_status_and_repeated_close_preserve_evidence_and_liveness(self):
        saved = self._ingest_bound_finding()
        event = observation(self.state)
        event.update(current_tree_hash='e' * 64)
        event['observation'].update(hasPendingChildRuns=True, summary='Later child active')
        reviews.record(self.state, event)
        self._assert_bound_evidence_preserved(*saved)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['task-fixture'])
        with self.assertRaises(ValueError):
            reviews.record(self.state, {'request_id': event['request_id'],
                                        'kind': 'cancel-requested', 'task_id': 'unowned-task'})
        reviews.record(self.state, {'request_id': event['request_id'],
                                    'kind': 'cancel-requested', 'task_id': 'task-fixture'})
        for tree_hash in ('e' * 64, 'd' * 64, None):
            reviews.close(self.state, {'current_tree_hash': tree_hash})
            reviews.record(self.state, event)
            self._assert_bound_evidence_preserved(*saved)
            self.assertEqual(self.state['workspace_drift']['observed_tree_hash'], 'e' * 64)
            self.assertEqual([r['outcome'] for r in self.state['requests'][1:]],
                             ['skipped-workspace-drift'] * 2)
            self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['task-fixture'])
        event['observation']['hasPendingChildRuns'] = False
        reviews.record(self.state, event)
        self._assert_bound_evidence_preserved(*saved)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])

    def test_bound_coordinator_dispositions_have_explicit_workflow_repair_routes(self):
        reviews.record(self.state, observation(self.state))
        for route in ('Ralph: stop old run; report; rerun with confirmed finding in brief',
                      'Jobs: cancel old job; report; rerun plan with confirmed finding in criteria'):
            event = {'request_id': self.state['requests'][0]['request_id'], 'finding_index': 0,
                     'finding_sha256': reviews.digest(self.state['requests'][0]['findings'][0]),
                     'revision': 'a' * 40, 'disposition': 'confirmed', 'evidence': 'Verified fixture reproduction',
                     'repair_route': route}
            reviews.disposition(self.state, event)
            self.assertEqual(self.state['dispositions'][-1], event)
            event['revision'] = 'b' * 40
            with self.assertRaises(ValueError):
                reviews.disposition(self.state, event)
        self.assertNotIn('evaluation', self.state)

    def test_brief_pins_authority_scope_base_feedback_and_request(self):
        dispatch = self.state['requests'][0]['dispatch']
        self.assertEqual(dispatch['mode'], 'async')
        self.assertEqual(dispatch['runtimeMode'], 'full-access')
        self.assertEqual(dispatch['isolation'], 'worktree')
        self.assertEqual(self.state['delegate_task_schema'], fixture()['delegate_task_schema'])
        self.assertEqual(self.state['workspace'], fixture()['workspace'])
        for phrase in ('read-only', 'Do not edit', 'never the required evaluator', 'No live calls.',
                       'Run no tests, builds, installs', 'do not run project code', 'temporary files',
                       'YOUR isolated checkout', 'never the parent checkout', 'parent LOCAL COMMIT',
                       'is clean after host project setup', 'Do not fetch, install or repair setup',
                       'origin/trunk', 'job-fixture/review-1', 'prior_feedback', 'a' * 40, 'b' * 40):
            self.assertIn(phrase, dispatch['task'])
        self.assertEqual(dispatch, reviews.prepare(fixture(), NOW)['requests'][0]['dispatch'])
        new = fixture()
        new['context']['round_id'] += '/next'
        self.assertNotEqual(dispatch['clientRequestId'], reviews.prepare(new, NOW)['requests'][0]['request_id'])

    def test_valid_findings_only_become_untrusted_evidence(self):
        reviews.record(self.state, observation(self.state))
        request = self.state['requests'][0]
        self.assertEqual(request['outcome'], 'untrusted-evidence')
        self.assertEqual(request['findings'][0]['severity'], 'major')
        self.assertNotIn('accepted', self.state)
        self.assertNotIn('attempt', self.state)
        self.assertEqual(reviews.overview(self.state)['mandatory_acceptance'], 'unchanged')
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        self.assertEqual(request['result']['findings'][0]['path'], 'module.py')

    def test_failures_malformed_stale_late_and_pending_are_skips(self):
        changes = [lambda e: e['observation'].update(status='failed'),
                   lambda e: e['observation'].update(summary='overloaded'),
                   lambda e: e['observation'].update(summary='```json\n{}\n```'),
                   lambda e: e['observation'].update(summary='{"revision":1,"revision":2}'),
                   lambda e: e['observation'].update(summary='x' * 32769),
                   lambda e: e['observation'].update(summary=None),
                   lambda e: e.update(current_revision='c' * 40),
                   lambda e: e.update(current_base_revision='c' * 40),
                   lambda e: e['observation'].update(providerInstanceId='other'),
                   lambda e: e['observation'].update(model=None),
                   lambda e: e['observation'].update(childRunId=None),
                   lambda e: e['observation'].update(hasPendingChildRuns=True),
                   lambda e: e['observation'].update(workState='waiting_for_children')]
        for change in changes:
            state = deepcopy(self.state)
            event = observation(state)
            change(event)
            reviews.record(state, event)
            self.assertTrue(state['requests'][0]['outcome'].startswith('skipped-'))
            self.assertEqual(state['requests'][0]['findings'], [])
        state = deepcopy(self.state)
        reviews.close(state, {'current_tree_hash': 'd' * 64})
        reviews.record(state, observation(state))
        self.assertEqual(state['requests'][0]['outcome'], 'skipped-round-ended')

    def test_wrong_revision_in_result_and_invalid_finding_rejected(self):
        valid = json.loads(observation(self.state)['observation']['summary'])
        changes = [lambda v: v.update(revision='c' * 40),
                   lambda v: v.update(base_revision='c' * 40),
                   lambda v: v['findings'][0].update(path='../escape.py'),
                   lambda v: v['findings'][0].update(line=True),
                   lambda v: v['findings'][0].update(evidence='')]
        for change in changes:
            value = deepcopy(valid)
            change(value)
            with self.assertRaises(ValueError):
                reviews.result(json.dumps(value), self.state['context'])

    def test_every_handle_kept_mismatch_sticky_and_cancel_does_not_prove_stop(self):
        event = observation(self.state)
        event['kind'] = 'receipt'
        event['observation']['model'] = 'wrong-model'
        reviews.record(self.state, event)
        request = self.state['requests'][0]
        reviews.record(self.state, observation(self.state))
        self.assertEqual(request['outcome'], 'skipped-identity-or-handle-mismatch')
        later = observation(self.state, task='conflicting-task')
        later['observation']['hasPendingChildRuns'] = True
        reviews.record(self.state, later)
        self.assertEqual(len(request['handles']), 2)
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        reviews.record(self.state, {'request_id': request['request_id'], 'kind': 'cancel-requested',
                                    'task_id': 'conflicting-task'})
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], ['conflicting-task'])
        later['observation']['hasPendingChildRuns'] = False
        later['observation']['status'] = 'cancelled'
        reviews.record(self.state, later)
        self.assertEqual(reviews.overview(self.state)['cancel_task_ids'], [])
        self.assertEqual(request['findings'], [])

    def test_original_run_binding_and_owned_cancellation(self):
        event = observation(self.state)
        event['kind'] = 'receipt'
        reviews.record(self.state, event)
        event['kind'] = 'status'
        event['observation']['childRunId'] = 'later-run'
        reviews.record(self.state, event)
        self.assertEqual(self.state['requests'][0]['outcome'], 'skipped-identity-or-handle-mismatch')
        reviews.record(self.state, observation(self.state))
        self.assertEqual(self.state['requests'][0]['outcome'], 'skipped-identity-or-handle-mismatch')
        with self.assertRaises(ValueError):
            reviews.record(self.state, {'request_id': event['request_id'], 'kind': 'cancel-requested',
                                        'task_id': 'unrelated-task'})

    def test_uncertain_launch_retained_definite_rejection_resolved(self):
        request = self.state['requests'][0]
        event = {'request_id': request['request_id'], 'kind': 'launch-error', 'error': 'do-not-store-secret'}
        reviews.record(self.state, event)
        reviews.close(self.state, {'current_tree_hash': 'd' * 64})
        self.assertIn(request['request_id'], reviews.overview(self.state)['unresolved_request_ids'])
        self.assertNotIn('do-not-store-secret', json.dumps(self.state))
        # Late recovered receipt stays owned and needs cleanup, never result intake.
        late = observation(self.state)
        late['kind'] = 'receipt'
        reviews.record(self.state, late)
        self.assertIn('task-fixture', reviews.overview(self.state)['cancel_task_ids'])
        second = self.state['requests'][1]
        reviews.record(self.state, {'request_id': second['request_id'], 'kind': 'launch-rejected'})
        self.assertNotIn(second['request_id'], reviews.overview(self.state)['unresolved_request_ids'])


class RepairPathTest(unittest.TestCase):
    def test_ralph_success_can_be_stopped_and_restarted_with_confirmed_finding(self):
        from tests.test_ralph import RalphTest
        case = RalphTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.implementation()
        case.review()
        self.assertEqual(case.state['phase'], 'evaluated')
        old_verdict = deepcopy(case.state['tasks'][-1]['evaluation'])
        case.state_path.parent.mkdir()
        case.state_path.write_text(json.dumps(case.state))

        def run(command, state_path, data=None):
            argv = [sys.executable, ROOT / 'plugins/ralph/cli.py', command, '--state', state_path]
            if data is not None:
                source = case.base / 'input.json'
                source.write_text(json.dumps(data))
                argv += ['--input', source]
            proc = subprocess.run(argv, cwd=case.repo, text=True, capture_output=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)

        stopped = run('stop', case.state_path)
        self.assertEqual(stopped['state']['phase'], 'cancelled')
        self.assertFalse(stopped['state']['readyForPublication'])
        self.assertEqual(stopped['state']['tasks'][-1]['evaluation'], old_verdict)
        original = case.state_path.read_bytes()
        replacement = deepcopy(case.init)
        confirmed = 'Confirmed supplemental finding: fixture module.py:3 missing validation; reproduced at pinned revision'
        replacement['brief'] += '\n' + confirmed + '\nPredecessor: ' + str(case.state_path)
        replacement['maxAttempts'] = case.state['maxAttempts'] - case.state['attempt']
        new_path = case.base / 'replacement.json'
        run('init', new_path, replacement)
        issued = run('next', new_path)
        self.assertIn(confirmed, issued['dispatch']['task'])
        self.assertEqual(issued['state']['maxAttempts'], 4)
        self.assertFalse(issued['state']['readyForPublication'])
        self.assertEqual(case.state_path.read_bytes(), original)

    def test_installed_job_cancel_and_replacement_plan_preserve_confirmed_evidence(self):
        from tests.test_rebuild_integration import ApeJob
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            job = ApeJob(self, box, 'original')
            job.create()
            confirmed = 'Confirmed supplemental finding module.py:3; pinned revision; reproduced missing validation'
            box.job(job.pkg, 'cancel', job.job_id, {'caller': job.caller, 'reason': confirmed})
            self.assertEqual(box.state_of(job.job_id)['status'], 'cancelled')
            original = (box.jobs / job.job_id / 'job.json').read_bytes()
            plan = job.plan()
            plan['job_id'] = 'replacement'
            plan['constraints'] += [confirmed, 'Predecessor original; remaining total executions capped at original limits']
            plan['policy']['max_repair_cycles'] = 2
            box.create(job.pkg, plan)
            prepared = box.job(job.pkg, 'prepare', 'replacement',
                               {'caller': job.caller, 'task_id': 's1-research', 'target_reason': 'fixture review repair'})
            self.assertIn(confirmed, Path(prepared['path']).read_text())
            self.assertEqual(box.state_of('replacement')['policy']['max_repair_cycles'], 2)
            self.assertEqual((box.jobs / job.job_id / 'job.json').read_bytes(), original)


class InstalledTest(unittest.TestCase):
    def test_installed_isolation_and_committed_scope_fail_closed_without_shared_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            package, _ = box.install('ralph')
            helper = package / 'shared' / 'supplemental_reviews.py'
            source = box.private / 'input.json'
            for index, change in enumerate((
                    lambda d: d.pop('delegate_task_schema'),
                    lambda d: d['delegate_task_schema']['input_schema']['properties']['isolation'].update(enum=['shared']),
                    lambda d: d['workspace'].update(clean=False),
                    lambda d: d['workspace'].update(scope_committed=False))):
                data = fixture(datetime.now(timezone.utc))
                change(data)
                source.write_text(json.dumps(data))
                ledger = box.private / ('skipped-' + str(index) + '.json')
                proc = box.run([sys.executable, helper, 'prepare', '--state', ledger, '--input', source])
                self.assertEqual(proc.returncode, 0, proc.stderr)
                output = json.loads(proc.stdout)
                self.assertEqual(output['dispatches'], [])
                self.assertEqual(output['requests'], [])
                self.assertEqual(output['mandatory_acceptance'], 'unchanged')
                self.assertTrue(output['skipped'])
                self.assertEqual(json.loads(ledger.read_text())['requests'], [])

    def test_symlinked_ancestor_allowed_but_ledger_and_lock_leaves_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / 'real'
            real.mkdir()
            link = root / 'link'
            link.symlink_to(real, target_is_directory=True)
            ledger = link / 'new-directory' / 'ledger.json'
            source = root / 'input.json'
            source.write_text(json.dumps(fixture(datetime.now(timezone.utc))))

            def run(command):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = reviews.main([command, '--state', str(ledger), '--input', str(source)])
                self.assertEqual(code, 0)
                return json.loads(out.getvalue())

            self.assertEqual(len(run('prepare')['dispatches']), 3)
            self.assertEqual(run('status')['requests'][0]['outcome'], 'reserved')
            original = ledger.read_bytes()
            ledger.unlink()
            target = root / 'target.json'
            target.write_bytes(original)
            ledger.symlink_to(target)
            self.assertIn('optional_error', run('status'))
            self.assertEqual(target.read_bytes(), original)
            ledger.unlink()
            ledger.write_bytes(original)
            lock = ledger.with_suffix('.lock')
            lock.unlink()
            lock.symlink_to(target)
            self.assertIn('optional_error', run('prepare'))
            self.assertEqual(target.read_bytes(), original)

    def test_relocated_installed_round_resume_failure_cleanup_and_mandatory_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            source = box.source_copy('ralph')
            package, manifest = box.install('ralph', source=source)
            shutil.rmtree(source)
            relocated = box.base / 'relocated-package'
            shutil.copytree(package, relocated)
            helper = relocated / 'shared' / 'supplemental_reviews.py'
            self.assertTrue(helper.is_file())
            self.assertTrue((relocated / 'shared' / 'supplemental-reviews.md').is_file())
            self.assertIn('shared/supplemental_reviews.py', [f['path'] for f in manifest['files']])
            # Byte-level proof that the optional CLI does not touch mandatory state/counters.
            mandatory = box.private / 'mandatory.json'
            mandatory.write_text('{"accepted":false,"attempt":1,"requiredReviewer":"primary"}')
            pinned = mandatory.read_bytes()
            ledger = box.private / 'supplemental.json'
            input_file = box.private / 'input.json'

            def run(command, data=None):
                argv = [sys.executable, helper, command, '--state', ledger]
                if data is not None:
                    input_file.write_text(json.dumps(data))
                    argv += ['--input', input_file]
                proc = box.run(argv)
                self.assertEqual(proc.returncode, 0)
                self.assertEqual(mandatory.read_bytes(), pinned)
                return json.loads(proc.stdout)

            data = fixture(datetime.now(timezone.utc))
            first = run('prepare', data)
            self.assertEqual(len(first['dispatches']), 3)
            self.assertTrue(all(d['isolation'] == 'worktree' for d in first['dispatches']))
            self.assertTrue(all('YOUR isolated checkout' in d['task'] for d in first['dispatches']))
            saved = json.loads(ledger.read_text())
            self.assertEqual(run('prepare', data)['dispatches'], [])
            self.assertEqual(json.loads(ledger.read_text())['requests'], saved['requests'])
            self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)
            bad = deepcopy(data)
            bad['context']['revision'] = 'c' * 40
            self.assertIn('optional_error', run('prepare', bad))
            event = observation(saved)
            event['observation']['summary'] = 'Review complete.\n```json\n' + event['observation']['summary'] + '\n```'
            self.assertEqual(run('record', event)['requests'][0]['outcome'], 'untrusted-evidence')
            receipt = deepcopy(event)
            receipt['kind'] = 'receipt'
            self.assertEqual(run('record', receipt)['requests'][0]['outcome'], 'untrusted-evidence')
            triage = {'request_id': saved['requests'][0]['request_id'], 'finding_index': 0,
                      'finding_sha256': reviews.digest(json.loads(observation(saved)['observation']['summary'])['findings'][0]),
                      'revision': 'a' * 40, 'disposition': 'confirmed', 'evidence': 'Verified fixture source',
                      'repair_route': 'Ralph stop/report/rerun under remaining budget'}
            self.assertEqual(run('disposition', triage)['dispositions'], [triage])
            ended = run('close', {'current_tree_hash': 'd' * 64})
            self.assertTrue(ended['closed'])
            self.assertEqual(ended['dispatches'], [])
            closed_ledger = ledger.read_bytes()
            self.assertEqual(run('close', {'current_tree_hash': 'f' * 64}), ended)
            self.assertEqual(run('close', {}), ended)
            self.assertEqual(ledger.read_bytes(), closed_ledger)
            self.assertEqual(run('prepare', data)['dispatches'], [])
            run('record', observation(saved))
            status = run('status')
            self.assertEqual(status['requests'][0]['outcome'], 'untrusted-evidence')
            self.assertEqual(status['dispositions'], [triage])
            self.assertEqual(status['requests'][0]['findings'],
                             json.loads(observation(saved)['observation']['summary'])['findings'])
            # Contention must skip immediately, never make optional work wait on a lock.
            with open(ledger.with_suffix('.lock'), 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                proc = subprocess.run([sys.executable, helper, 'status', '--state', ledger],
                                      cwd=box.base, env=box.env, capture_output=True, text=True, timeout=5)
                self.assertEqual(proc.returncode, 0)
                self.assertIn('optional_error', json.loads(proc.stdout))
            ledger.write_text('malformed')
            self.assertIn('optional_error', run('status'))
            self.assertEqual(ledger.read_text(), 'malformed', 'never reset a damaged ledger to relaunch')

    def test_workflow_hooks_ship_in_installed_packages(self):
        hooks = {'ralph': 'playbooks/loop.md', 'imps': 'references/delegation.md',
                 'babysitter': 'playbooks/maintain.md', 'agent-tuneup': 'references/job-plan.md',
                 'elephant-goldfish': 'references/document-jobs.md'}
        with tempfile.TemporaryDirectory() as tmp:
            box = Sandbox(Path(tmp))
            for plugin, hook in hooks.items():
                package, _ = box.install(plugin)
                self.assertIn('PKG/shared/supplemental-reviews.md', (package / hook).read_text())
                self.assertTrue((package / 'shared' / 'supplemental_reviews.py').is_file())
                if plugin == 'babysitter':
                    text = (package / hook).read_text()
                    self.assertIn("coordinator checkout is already at the reviewed PR HEAD", text)
                    self.assertIn("Never change checkouts merely to enable extras", text)
            guide = (ROOT / 'docs/supplemental-reviews.md').read_text()
            self.assertIn('coordinator checkout is already at the reviewed PR HEAD', guide)
            self.assertIn('Never change checkouts merely to enable extras', guide)


if __name__ == '__main__':
    unittest.main()
