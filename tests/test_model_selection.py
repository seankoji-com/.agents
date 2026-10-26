"""Admission and failure paths through source CLI and shared job preparation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import model_selection as models
from shared.job_coordinator import selection_for_task, prepare_task
from core.jobs.store import JobError
from tests.model_selection_fixtures import answer, selection_input, canonical_selection_input, replacement


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = selection_input()
        self.record = models.freeze(self.data)

    def cli(self, action, data, helper=None):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'input.json'
            path.write_text(json.dumps(data))
            return subprocess.run([sys.executable, str(helper or ROOT / 'shared/model_selection_cli.py'),
                                   action, '--input', str(path)], cwd=ROOT, text=True,
                                  capture_output=True, timeout=30,
                                  env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})

    def test_missing_answer_blocks_investigation_drafting_and_dispatch_through_cli(self):
        for action in ('investigate', 'draft', 'dispatch'):
            result = self.cli('gate', {'record': None, 'invocation_id': 'new', 'scope_id': 'scope', 'action': action})
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('collect upfront choices', result.stderr)
        data = deepcopy(self.data); data['source'] = None
        self.assertEqual(self.cli('freeze', data).returncode, 2)

    def test_preflight_and_deterministic_do_not_require_choices_or_dispatch(self):
        for action in models.PREFLIGHT | {'deterministic'}:
            result = self.cli('gate', {'record': None, 'invocation_id': 'doctor', 'scope_id': 'scope', 'action': action})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'allowed': True, 'chooser': False, 'dispatch': False})
        self.assertEqual(self.cli('gate', {'record': None, 'invocation_id': 'doctor', 'scope_id': 'scope',
                                          'action': 'dispatch'}).returncode, 2)

    def test_explicit_command_answer_and_exact_custom_targets_reach_dispatch(self):
        self.data['source'] = answer('fixture command: explicit custom work/high and review/high')
        record = models.freeze(self.data)
        result = self.cli('dispatch', {'record': record, 'role': 'workhorse', 'expected': record['selection_sha256']})
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['target'], self.data['work']['workhorse'])
        self.assertEqual(plan['execution'], 'child')
        self.assertEqual(record['coordinator'], self.data['coordinator'])
        self.assertEqual(models.correlate(plan, plan['target'])['options'], 'matched')

    def test_options_never_silently_dropped_or_mapped_to_another_provider_name(self):
        for options in ({'effort': 'high'}, {'reasoningEffort': 'unsupported'}, {'reasoningEffort': True}):
            data = deepcopy(self.data); data['work']['workhorse']['options'] = options
            self.assertEqual(self.cli('freeze', data).returncode, 2)
        plan = models.dispatch(self.record, role='workhorse')
        self.assertEqual(models.correlate(plan, {k: v for k, v in plan['target'].items() if k != 'options'})['options'], 'unreported')
        with self.assertRaisesRegex(models.SelectionError, 'options mismatch'):
            models.correlate(plan, {**plan['target'], 'options': {}})
        with self.assertRaisesRegex(models.SelectionError, 'provider/model mismatch'):
            models.correlate(plan, {**plan['target'], 'model': 'other'})

    def test_current_context_actual_settings_and_same_model_child(self):
        data = deepcopy(self.data); data['work']['workhorse']['execution'] = 'current-context'
        record = models.freeze(data)
        self.assertEqual(models.dispatch(record, role='workhorse')['execution'], 'current-context')
        data['coordinator']['observed_options'] = None
        with self.assertRaisesRegex(models.SelectionError, 'same-model child'):
            models.freeze(data)
        data['work']['workhorse'].update(options={}, accept_actual_settings=True)
        record = models.freeze(data)
        self.assertIsNone(record['coordinator']['observed_options'])
        data['coordinator']['observed_options'] = {'reasoningEffort': 'low'}
        data['work']['workhorse'].update(options={'reasoningEffort': 'high'}, accept_actual_settings=False)
        with self.assertRaises(models.SelectionError): models.freeze(data)
        data['work']['workhorse']['execution'] = 'child'
        record = models.freeze(data)
        self.assertEqual(record['coordinator']['observed_options'], {'reasoningEffort': 'low'})
        self.assertEqual(models.dispatch(record, role='workhorse')['target']['options'], {'reasoningEffort': 'high'})

    def test_live_discovery_no_config_labels_not_identity_and_missing_capabilities(self):
        result = models.discover(self.data['capabilities'], self.data['profiles'], role='reviewer')
        self.assertEqual(len(result['candidates']), 3)
        self.assertFalse(result['configured'])
        self.assertTrue(all(t['target']['options'] for t in result['candidates']))
        for caps in (None, {}, {'providers': 'missing'}):
            with self.assertRaises(models.SelectionError): models.discover(caps, self.data['profiles'])
        with self.assertRaises(models.SelectionError):
            models.validate_target({'providerInstanceId': 'Duplicate label', 'model': 'Duplicate label'}, self.data['capabilities'])

    def test_configuration_gap_distinct_from_policy_excluded(self):
        for config in ({}, {'roles': {'reviewer': []}}, {'roles': {'reviewer': 'malformed'}}):
            with self.assertRaisesRegex(models.SelectionError, 'configuration gap'):
                models.discover(self.data['capabilities'], self.data['profiles'], config, 'reviewer')
        config = {'roles': {'reviewer': [self.data['review_panel'][0]['target']]}}
        result = models.discover(self.data['capabilities'], self.data['profiles'], config, 'reviewer')
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(all('policy-excluded' in x['reason'] for x in result['excluded']))

    def test_discovery_rejects_nonobject_routing_options_before_catalog_filtering(self):
        for role in ('workhorse', 'reviewer'):
            for options in (None, 'high', [], [['effort', 'high']], 1, 1.5, True, False):
                with self.subTest(role=role, options=options):
                    # Even an unavailable entry must report its malformed field.
                    config = {'roles': {role: [self.data['work']['workhorse'],
                        {'providerInstanceId': 'absent', 'model': 'absent', 'options': options}]}}
                    before = deepcopy(config)
                    result = self.cli('discover', {'capabilities': self.data['capabilities'],
                        'profiles': self.data['profiles'], 'routing': config, 'role': role})
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(f'configuration gap: roles.{role}[1].options must be an object', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertEqual(result.stdout, '')
                    with self.assertRaisesRegex(models.SelectionError, 'configuration gap'):
                        models.discover(self.data['capabilities'], self.data['profiles'], config, role)
                    self.assertEqual(config, before)

    def test_cheap_or_first_model_is_not_quality_proof_and_fixed_effort_reason(self):
        data = deepcopy(self.data); data['profiles']['models'][0]['quality'] = 0
        result = models.discover(data['capabilities'], data['profiles'], role='reviewer')
        self.assertEqual(len(result['candidates']), 2)
        data = deepcopy(self.data)
        data['capabilities']['providers'][1]['models'][0]['options'] = []
        data['review_panel'][0]['target']['options'] = {}
        with self.assertRaisesRegex(models.SelectionError, 'fixed-effort review needs a suitability reason'):
            models.freeze(data)
        data['profiles']['models'][1]['fixed_effort_reason'] = 'Fixture fixed-effort model meets bounded judgement floor.'
        self.assertTrue(models.freeze(data))

    def test_profile_container_gaps_fail_at_discovery_and_suitability_boundaries(self):
        for role in ('workhorse', 'reviewer'):
            target = self.data['work']['workhorse'] if role == 'workhorse' else self.data['review_panel'][0]['target']
            for field in ('roles', 'required_options', 'source'):
                invalid = (None, [], 'high', 1, True) if field != 'source' else ([], {}, 1, True)
                for value in invalid:
                    with self.subTest(role=role, field=field, value=value):
                        profiles = deepcopy(self.data['profiles'])
                        if field == 'roles':
                            profiles['roles'] = value
                            locator = 'profiles.roles as an object'
                        else:
                            profiles['roles'][role][field] = value
                            locator = f'profiles.roles.{role}.{field}'
                        before = deepcopy(profiles)
                        for invoke in (
                                lambda: models.discover(self.data['capabilities'], profiles, role=role),
                                lambda: models.suitability(target, role, profiles, self.data['capabilities'])):
                            with self.assertRaises(models.SelectionError) as caught:
                                invoke()
                            self.assertIn('configuration gap', str(caught.exception))
                            self.assertIn(locator, str(caught.exception))
                        result = self.cli('discover', {'capabilities': self.data['capabilities'],
                                                     'profiles': profiles, 'role': role})
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn(locator, result.stderr)
                        self.assertNotIn('Traceback', result.stderr)
                        self.assertEqual(result.stdout, '')
                        self.assertEqual(profiles, before)

    def test_optional_floor_source_and_required_options_keep_compatible_profiles(self):
        for role in ('workhorse', 'reviewer'):
            target = self.data['work']['workhorse'] if role == 'workhorse' else self.data['review_panel'][0]['target']
            for policy_source in (None, '', 'fixture-policy.md#role'):
                profiles = deepcopy(self.data['profiles'])
                profiles['roles'][role].update(source=policy_source, required_options=target['options'])
                self.assertTrue(models.suitability(target, role, profiles, self.data['capabilities']))
                result = models.discover(self.data['capabilities'], profiles, role=role)
                self.assertTrue(any(row['target'] == target for row in result['candidates']))

    def test_present_nonobject_role_policy_names_the_gap_before_candidate_discovery(self):
        for role in ('workhorse', 'reviewer'):
            target = self.data['work']['workhorse'] if role == 'workhorse' else self.data['review_panel'][0]['target']
            message = (f'configuration gap: profiles.roles.{role} must be an object; '
                       f'provide profiles.roles.{role} as an object containing the role policy.')
            for value in (None, [], 'strict', 1, 1.5, True, False):
                with self.subTest(role=role, value=value):
                    data = deepcopy(self.data)
                    data['profiles']['roles'][role] = value
                    before = deepcopy(data)
                    for invoke in (
                            lambda: models.suitability(target, role, data['profiles'], data['capabilities']),
                            lambda: models.freeze(data),
                            lambda: models.discover(data['capabilities'], data['profiles'], role=role),
                            lambda: models.discover({'providers': []}, data['profiles'], role=role)):
                        with self.assertRaises(models.SelectionError) as caught:
                            invoke()
                        self.assertEqual(str(caught.exception), message)
                    for capabilities in (data['capabilities'], {'providers': []}):
                        result = self.cli('discover', {'capabilities': capabilities,
                            'profiles': data['profiles'], 'role': role})
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertEqual(result.stderr.strip(), 'selection_error: ' + message)
                        self.assertEqual(result.stdout, '')
                    self.assertEqual(data, before)

    def test_preference_treats_missing_or_malformed_independence_as_unverified(self):
        preferred = {'providerInstanceId': 'fixture-work', 'model': 'preferred'}
        routing = {'roles': {'workhorse': [preferred]}, 'preferred_workhorse': preferred}
        for annotation in ({}, {'independent': None}, {'independent': 'invalid'},
                           {'independent': []}, {'independent': {}}, {'independent': 1},
                           {'independent': 0}, {'independent': 1.0}):
            with self.subTest(annotation=annotation):
                rows = [dict(preferred, **annotation),
                        {'providerInstanceId': 'fixture-work', 'model': 'same', 'independent': False},
                        {'providerInstanceId': 'fixture-work', 'model': 'unknown', 'independent': None},
                        {'providerInstanceId': 'fixture-work', 'model': 'verified', 'independent': True}]
                result = models.prefer_workhorse({'candidates': rows}, routing, 'workhorse')
                self.assertEqual([row['model'] for row in result['candidates']],
                                 ['verified', 'preferred', 'unknown', 'same'])
                self.assertEqual({k: v for k, v in result['candidates'][1].items()
                                  if k == 'independent'}, annotation)
                self.assertTrue(result['candidates'][1]['preferred'])
                self.assertEqual(result['preference_status'], 'available')
        # Discovery has no independence annotations; an ordinary preference still floats.
        rows = [{'target': {'providerInstanceId': 'fixture-work', 'model': 'other'}},
                {'target': deepcopy(preferred)}]
        result = models.prefer_workhorse({'candidates': rows}, routing, 'workhorse')
        self.assertEqual(result['candidates'][0]['target'], preferred)
        self.assertTrue(result['candidates'][0]['preferred'])
        for policy, role in (({'roles': routing['roles']}, 'workhorse'), (routing, 'reviewer')):
            original = {'candidates': [dict(preferred, independent=[])]}
            before = deepcopy(original)
            self.assertIs(models.prefer_workhorse(original, policy, role), original)
            self.assertEqual(original, before)

    def test_selected_options_are_validated_without_recommendation_substitution(self):
        data = deepcopy(self.data)
        # The role's low requirement and configured answer outrank high defaults.
        data['work']['workhorse']['options'] = {'reasoningEffort': 'low'}
        data['profiles']['roles']['workhorse']['required_options'] = {'reasoningEffort': 'low'}
        data['routing'] = {'roles': {'workhorse': [data['work']['workhorse']],
                                    'reviewer': [data['review_panel'][0]['target']]}}
        discovered = models.discover(data['capabilities'], data['profiles'], data['routing'])
        self.assertEqual(discovered['candidates'][0]['target'], data['work']['workhorse'])
        self.assertFalse(any(e['target']['model'] == 'alpha-work' for e in discovered['excluded']))
        record = models.freeze(data)
        plan = models.dispatch(record, role='workhorse')
        self.assertEqual(plan['target'], data['work']['workhorse'])
        self.assertFalse(plan['substituted'])
        # A role requirement also guides recommendations without configured options.
        data['routing']['roles']['workhorse'][0] = {k: v for k, v in data['work']['workhorse'].items()
                                                    if k != 'options'}
        self.assertEqual(models.discover(data['capabilities'], data['profiles'], data['routing'])[
            'candidates'][0]['target']['options'], {'reasoningEffort': 'low'})

    def test_configured_endorsement_is_ordinary_quality_source_without_model_row(self):
        for missing in ('quality', 'row', 'floor'):
            with self.subTest(missing=missing):
                data = canonical_selection_input()
                work = data['work']['workhorse']
                data['routing'] = {'roles': {'workhorse': [{**work, 'lineage': 'openai'}],
                                            'reviewer': [data['review_panel'][0]['target']]}}
                data['source'] = answer('Use the configured alpha-work as workhorse globally')
                data['routing_scope'] = 'global'
                del data['profiles']['models'][0]['quality']
                if missing in ('row', 'floor'):
                    del data['profiles']['models'][0]
                if missing == 'floor':
                    del data['profiles']['roles']['workhorse']
                data['schedule'] = {'schedule_id': 'fixture-schedule',
                                    'source': answer('Reuse these exact choices for this fixture schedule.')}
                original = deepcopy(data)
                record = models.freeze(data)
                plan = models.dispatch(record, role='workhorse')
                self.assertEqual(plan['target'], work)
                self.assertEqual(plan['routing_scope'], 'global')
                self.assertEqual(data, original)
                self.assertEqual(record['profiles'], original['profiles'])
                self.assertEqual(record['source'], original['source'])
                scheduled = {'invocation_id': record['invocation_id'], 'scope_id': record['scope_id'],
                             'event': 'schedule', 'schedule_id': 'fixture-schedule',
                             'capabilities': data['capabilities'], 'policy_digests': {
                                 name: record[name] for name in ('routing_sha256', 'profiles_sha256')}}
                self.assertTrue(models.gate(record, **scheduled)['allowed'])
                absent = deepcopy(data['capabilities'])
                absent['providers'].pop(0)
                with self.assertRaisesRegex(models.SelectionError, 'provider absent'):
                    models.gate(record, **dict(scheduled, capabilities=absent))

    def test_endorsement_does_not_override_stricter_workhorse_evidence(self):
        data = deepcopy(self.data)
        work = data['work']['workhorse']
        data['routing'] = {'roles': {'workhorse': [{**work, 'lineage': 'alpha'}]}}
        del data['profiles']['models'][0]['quality']
        data['profiles']['roles']['workhorse']['minimum'] = 2
        with self.assertRaisesRegex(models.SelectionError, 'quality >= 2'):
            models.freeze(data)
        data['profiles']['roles']['workhorse'] = {'minimum': 1, 'source': 'fixture-policy.md#work'}
        with self.assertRaisesRegex(models.SelectionError, 'quality >= 1.*fixture-policy.md#work'):
            models.freeze(data)
        del data['profiles']['models'][0]
        with self.assertRaisesRegex(models.SelectionError, 'one profiles.models entry.*fixture-policy.md#work'):
            models.freeze(data)
        data['profiles']['roles']['workhorse'] = {'minimum': 1, 'judgement': True}
        with self.assertRaisesRegex(models.SelectionError, 'model suitability missing'):
            models.freeze(data)

    def authored_job(self, record):
        return {'model_selection': record, 'tasks': [{
            'role': 'worker', 'target': deepcopy(record['work']['workhorse']),
            'selection_binding': {'role': 'workhorse', 'selection_sha256': record['selection_sha256']},
            'handles': [{'target': deepcopy(record['work']['workhorse']),
                         'observed_identity': {'status': 'verified'}}],
        }]}

    def test_owner_endorsed_dispatched_authors_keep_known_lineage(self):
        from shared.job_coordinator import actual_author_lineages
        for missing in ('quality', 'row', 'floor'):
            with self.subTest(missing=missing):
                data = canonical_selection_input()
                work = data['work']['workhorse']
                data['routing'] = {'roles': {'workhorse': [{**work, 'lineage': 'openai'}],
                                            'reviewer': [data['review_panel'][0]['target']]}}
                del data['profiles']['models'][0]['quality']
                if missing in ('row', 'floor'):
                    del data['profiles']['models'][0]
                if missing == 'floor':
                    del data['profiles']['roles']['workhorse']
                record = models.freeze(data)
                models.dispatch(record, role='workhorse')
                job = self.authored_job(record)
                before = deepcopy(job)
                authors = actual_author_lineages(job)
                self.assertEqual(authors, {'openai'})
                review = models.dispatch(record, role='reviewer', slot_id='review', author_lineages=authors)
                self.assertEqual(review['target'], data['review_panel'][0]['target'])
                self.assertEqual(job, before, 'lineage derivation must not fill or rewrite frozen evidence')

    def test_author_endorsement_keeps_identity_policy_and_option_failures_unknown(self):
        from shared.job_coordinator import actual_author_lineages
        data = canonical_selection_input()
        work = data['work']['workhorse']
        data['routing'] = {'roles': {'workhorse': [{**work, 'lineage': 'openai'}],
                                    'reviewer': [data['review_panel'][0]['target']]}}
        del data['profiles']['models'][0]
        record = models.freeze(data)
        for boundary in ('unreported', 'mismatched', 'floor', 'policy', 'options', 'answer', 'unendorsed', 'custom'):
            with self.subTest(boundary=boundary):
                job = self.authored_job(deepcopy(record))
                producing = job['model_selection']
                if boundary in ('unreported', 'mismatched'):
                    job['tasks'][0]['handles'][0]['observed_identity']['status'] = boundary
                elif boundary == 'floor':
                    producing['profiles']['roles']['workhorse']['minimum'] = 2
                elif boundary == 'policy':
                    producing['profiles']['roles']['workhorse']['source'] = 'fixture-policy.md#strict'
                elif boundary == 'options':
                    producing['profiles']['roles']['workhorse']['required_options'] = {'reasoningEffort': 'low'}
                elif boundary == 'answer':
                    producing['source']['sha256'] = '0' * 64
                elif boundary == 'unendorsed':
                    producing['routing'] = None
                else:
                    producing['capabilities']['providers'][0]['driverKind'] = 'fixture'
                    producing['routing']['roles']['workhorse'][0]['lineage'] = work['model']
                before = deepcopy(job)
                self.assertIn('unknown', actual_author_lineages(job))
                self.assertEqual(job, before)
        job = self.authored_job(record)
        job['tasks'][0]['followups'] = [{'target': deepcopy(work), 'observed_identity': {'status': 'unreported'}}]
        self.assertIn('unknown', actual_author_lineages(job), 'an unknown followup author remains sticky')

    def test_historical_author_uses_its_producing_selection_and_blocks_same_lineage_review(self):
        from shared.job_coordinator import actual_author_lineages
        data = canonical_selection_input()
        work = data['work']['workhorse']
        data['routing'] = {'roles': {'workhorse': [{**work, 'lineage': 'openai'}],
                                    'reviewer': [data['review_panel'][0]['target']]}}
        del data['profiles']['models'][0]
        current = models.freeze(data)
        old_data = canonical_selection_input()
        old_data['capabilities']['providers'][0]['driverKind'] = 'claudeAgent'
        old_data['capabilities']['providers'][1]['driverKind'] = 'codex'
        old_data['coordinator']['lineage'] = 'anthropic'
        old_data['profiles']['models'][0]['lineage'] = 'anthropic'
        old_data['profiles']['models'][1]['lineage'] = 'openai'
        old = models.freeze(old_data)
        old_author = self.authored_job(old)['tasks'][0]
        old_author['status'] = 'failed'
        job = self.authored_job(current)
        job['model_selection_history'] = {old['selection_sha256']: old}
        job['history'] = [{'tasks': [old_author]}]
        self.assertEqual(actual_author_lineages(job), {'openai', 'anthropic'})
        with self.assertRaisesRegex(models.SelectionError, 'stronger independent slot'):
            models.dispatch(current, role='reviewer', slot_id='review', author_lineages=actual_author_lineages(job))

    def test_endorsement_does_not_grant_unknown_lineage_or_review_independence(self):
        data = deepcopy(self.data)
        work = data['work']['workhorse']
        work['model'] = '123fixture'
        data['capabilities']['providers'][0]['models'][0]['id'] = work['model']
        data['routing'] = {'roles': {'workhorse': [work], 'reviewer': [data['review_panel'][0]['target']]}}
        del data['profiles']['models'][0]
        with self.assertRaisesRegex(models.SelectionError, 'independent of every'):
            models.freeze(data)
        work['model'] = 'beta-work'
        data['capabilities']['providers'][0]['models'][0]['id'] = work['model']
        with self.assertRaisesRegex(models.SelectionError, 'independent of every'):
            models.freeze(data)

    def test_configured_custom_basename_cannot_establish_review_independence(self):
        for driver in ('cursor', 'opencode', 'pi'):
            for label in (None, 'myvendor', 'other-unverified', 'google', 'anthropic'):
                with self.subTest(driver=driver, label=label):
                    data = canonical_selection_input()
                    data['routing_scope'] = 'global'
                    data['capabilities']['runtimeMode'] = 'full-access'
                    provider = data['capabilities']['providers'][0]
                    provider['driverKind'] = driver
                    provider['runtimeModes'] = ['auto', 'full-access']
                    provider['models'][0]['id'] = 'myvendor-custom'
                    work = data['work']['workhorse']
                    work.update(model='myvendor-custom', runtimeMode='full-access')
                    entry = {**work, **({'lineage': label} if label else {})}
                    data['routing'] = {'roles': {'workhorse': [entry],
                                                'reviewer': [data['review_panel'][0]['target']]}}
                    del data['profiles']['models'][0]
                    original = deepcopy(data)
                    if label == 'google':
                        record = models.freeze(data)
                        self.assertEqual(models.dispatch(record, role='workhorse')['target'], work)
                        self.assertEqual(models.dispatch(record, role='workhorse')['routing_scope'], 'global')
                        self.assertEqual(models.dispatch(record, role='reviewer', slot_id='review')[
                            'routing_scope'], 'invocation-only')
                    else:
                        with self.assertRaisesRegex(models.SelectionError, 'independent of every'):
                            models.freeze(data)
                    self.assertEqual(data, original)
                    # A separately sourced profile can confirm a custom lineage.
                    data['profiles']['models'].append({'target': deepcopy(work), 'lineage': 'myvendor',
                        'lineage_source': 'fixture:owner-confirmed-family'})
                    self.assertEqual(models.dispatch(models.freeze(data), role='workhorse')['target'], work)

    def test_lineage_conflict_names_origin_and_correction_without_changing_selection(self):
        for origin, role, family in (('routing', 'workhorse', 'openai'),
                                     ('profile', 'workhorse', 'openai'),
                                     ('profile', 'reviewer', 'anthropic')):
            with self.subTest(origin=origin, role=role):
                data = canonical_selection_input()
                data['routing_scope'] = 'global'
                if origin == 'routing':
                    row = {**data['work']['workhorse'], 'lineage': 'not-alpha'}
                    data['routing'] = {'roles': {'workhorse': [row],
                                                'reviewer': [data['review_panel'][0]['target']]}}
                    del data['profiles']['models'][0]
                    field = 'routing.roles.workhorse.lineage'
                else:
                    row = data['profiles']['models'][0 if role == 'workhorse' else 1]
                    row.update(lineage='not-' + family, lineage_source='fixture:profile')
                    field = 'profiles.models.lineage'
                original = deepcopy(data)
                with self.assertRaises(models.SelectionError) as caught:
                    models.freeze(data)
                error = str(caught.exception)
                target = data['work']['workhorse'] if role == 'workhorse' else data['review_panel'][0]['target']
                self.assertIn(role + ' ' + '/'.join(models.key(target)), error)
                self.assertIn('set ' + field + ' to ' + family + ' or omit that field', error)
                self.assertEqual(data, original)
                for correction in ('canonical', 'omit'):
                    if correction == 'canonical':
                        row['lineage'] = family
                    else:
                        del row['lineage']
                    record = models.freeze(data)
                    plan = models.dispatch(record, role=role, **({'slot_id': 'review'} if role == 'reviewer' else {}))
                    self.assertEqual(plan['target'], target)
                    self.assertEqual(plan['routing_scope'], 'global' if role == 'workhorse' else 'invocation-only')

    def test_missing_reviewer_evidence_names_only_reviewer_next_step(self):
        for missing, field in (('reason', 'reason'), ('judgement', 'judgement'),
                               ('fixed_effort_reason', 'fixed_effort_reason')):
            with self.subTest(missing=missing):
                data = deepcopy(self.data)
                if missing == 'fixed_effort_reason':
                    data['capabilities']['providers'][1]['models'][0]['options'] = []
                    data['review_panel'][0]['target']['options'] = {}
                else:
                    del data['profiles']['models'][1][missing]
                with self.assertRaises(models.SelectionError) as caught:
                    models.freeze(data)
                error = str(caught.exception)
                self.assertIn('reviewer fixture-review/beta-review', error)
                self.assertIn('provide profiles.models.' + field, error)
                self.assertNotIn('workhorse', error)

    def test_old_record_without_routing_scope_keeps_invocation_default(self):
        legacy = deepcopy(self.record)
        del legacy['routing_scope']
        del legacy['selection_sha256']
        legacy['selection_sha256'] = models.digest(legacy)
        self.assertEqual(models.validate(legacy), legacy)
        self.assertEqual(models.dispatch(legacy, role='workhorse')['routing_scope'], 'invocation-only')
        with self.assertRaisesRegex(models.SelectionError, 'workhorse routing scope missing'):
            models.freeze(legacy)

    def test_new_scope_must_be_recorded_without_reinterpreting_owner_prose(self):
        for scope, quote in (('global', 'Use the configured alpha-work as workhorse globally'),
                             ('invocation-only', 'Use alpha-work for this run')):
            with self.subTest(scope=scope):
                data = deepcopy(self.data)
                data['source'] = answer(quote)
                data['routing'] = {'roles': {'workhorse': [data['work']['workhorse']],
                                            'reviewer': [data['review_panel'][0]['target']]}}
                del data['routing_scope']
                original = deepcopy(data)
                blocked = self.cli('freeze', data)
                self.assertEqual(blocked.returncode, 2)
                self.assertIn('record routing_scope as global or invocation-only from the owner answer', blocked.stderr)
                self.assertIn('ask only which scope applies', blocked.stderr)
                self.assertEqual(data, original)
                data['routing_scope'] = scope
                record = models.freeze(data)
                self.assertEqual(models.dispatch(record, role='workhorse')['routing_scope'], scope)
                self.assertEqual(record['source'], original['source'])
                self.assertEqual(record['routing'], original['routing'])

    def test_configured_owner_choice_reuses_suitability_and_preserves_scope(self):
        for scope in ('invocation-only', 'global'):
            with self.subTest(scope=scope):
                data = deepcopy(self.data)
                data['source'] = answer('Use the configured alpha-work as workhorse ' + scope)
                data['routing_scope'] = scope
                data['profiles']['models'][0]['reason'] = data['source']['answer']
                data['routing'] = {'roles': {'workhorse': [data['work']['workhorse']],
                                            'reviewer': [data['review_panel'][0]['target']]}}
                original = deepcopy(data)
                record = models.freeze(data)
                self.assertEqual(record['source'], original['source'])
                self.assertEqual(record['routing_scope'], scope)
                plan = models.dispatch(record, role='workhorse')
                self.assertEqual(plan['routing_scope'], scope)
                self.assertEqual(plan['scope_id'], data['scope_id'])
                self.assertEqual(plan['role'], 'workhorse')
                self.assertEqual(models.dispatch(record, role='workhorse')['target'], data['work']['workhorse'])
                self.assertEqual(data, original)  # No mutation of global routing or answers.
                review_plan = models.dispatch(record, role='reviewer', slot_id='review')
                self.assertEqual(review_plan['target'], data['review_panel'][0]['target'])
                self.assertEqual(review_plan['routing_scope'], 'invocation-only')
                spare = data['profiles']['models'][2]['target']
                data['routing']['roles']['workhorse'].append(spare)
                data['work_replacements'] = [replacement(data, spare)]
                record = models.freeze(data)
                substitute = models.dispatch(record, role='workhorse', target=spare,
                    unavailable={'kind': 'capacity', 'reference': 'fixture:capacity'})
                self.assertEqual(substitute['routing_scope'], 'invocation-only')
                self.assertEqual(record['routing_scope'], scope)

    def test_invalid_routing_scope_fails_without_narrowing(self):
        data = deepcopy(self.data); data['routing_scope'] = 'unspecified'
        with self.assertRaisesRegex(models.SelectionError, 'never silently narrow'):
            models.freeze(data)

    def test_missing_profile_names_exact_role_target_fields_and_next_step(self):
        data = deepcopy(self.data)
        data['profiles']['models'].pop(0)
        result = self.cli('freeze', data)
        self.assertEqual(result.returncode, 2)
        for text in ('workhorse fixture-work/alpha-work', 'provide one profiles.models entry',
                     'this exact provider/model'):
            self.assertIn(text, result.stderr)
        for text in ('profiles.roles.workhorse', 'judgement', 'fixed_effort_reason'):
            self.assertNotIn(text, result.stderr)
        data = deepcopy(self.data)
        del data['profiles']['roles']['workhorse']
        result = self.cli('freeze', data)
        self.assertIn('provide profiles.roles.workhorse.minimum', result.stderr)
        self.assertNotIn('profiles.models', result.stderr)
        data['profiles'] = 'nope'
        result = self.cli('freeze', data)
        self.assertIn('provide a profiles object', result.stderr)
        self.assertNotIn('profiles.roles.workhorse', result.stderr)
        for field, value, required in (
                ('reason', '', 'provide profiles.models.reason'),
                ('quality', 0, 'provide sourced profiles.models.quality >= 1')):
            data = deepcopy(self.data)
            data['profiles']['models'][0][field] = value
            result = self.cli('freeze', data)
            self.assertEqual(result.returncode, 2)
            self.assertIn('workhorse fixture-work/alpha-work', result.stderr)
            self.assertIn(required, result.stderr)
        # An ordinary workhorse endorsement cannot satisfy a stricter judgement floor.
        data = deepcopy(self.data)
        data['routing'] = {'roles': {'workhorse': [data['work']['workhorse']]}}
        data['source'] = answer('Use the configured alpha-work as workhorse globally')
        data['profiles']['models'][0].update(reason=data['source']['answer'], judgement=False)
        data['profiles']['roles']['workhorse']['judgement'] = True
        result = self.cli('freeze', data)
        self.assertEqual(result.returncode, 2)
        self.assertIn('workhorse fixture-work/alpha-work', result.stderr)
        self.assertIn('provide profiles.models.judgement evidence', result.stderr)
        self.assertIn('profiles.roles.workhorse.judgement', result.stderr)

    def test_separate_reviewer_pool_and_concrete_reviewer_conflicts(self):
        data = deepcopy(self.data)
        work, review = data['work']['workhorse'], data['review_panel'][0]['target']
        data['routing'] = {'roles': {'workhorse': [work], 'reviewer': [review]}}
        self.assertEqual(models.dispatch(models.freeze(data), role='reviewer', slot_id='review')['target'], review)
        data['profiles']['models'][1]['judgement'] = False
        with self.assertRaisesRegex(models.SelectionError, 'judgement-capable model required'):
            models.freeze(data)
        data['profiles']['models'][1]['judgement'] = True
        data['routing']['roles']['workhorse'] = [review]
        with self.assertRaisesRegex(models.SelectionError, 'routing.roles.workhorse: fixture-work/alpha-work'):
            models.freeze(data)

    def test_short_round_contract_retains_answers_and_preserves_gates(self):
        contract = (ROOT / 'shared/model-selection.md').read_text()
        for text in ('one decision per question', 'wait for its', 'still-missing decisions',
                     '"Use it globally" answers this round', 'Run-only never writes routing',
                     'independently of the workhorse pool', 'Before dispatch',
                     'never privacy, suitability, scope or review-independence gates'):
            self.assertIn(text, contract)
        ralph = ' '.join((ROOT / 'plugins/ralph/playbooks/loop.md').read_text().split())
        self.assertIn('then each still-missing option or backup decision in separate questions', ralph)
        self.assertIn('keep the implementer answer', ralph)
        self.assertIn("target's correction, retaining other answers", ralph)
        for name in ('shared/t3-runtime.md', 'shared/adopter-planning.md',
                     'plugins/focus-group/entry.md', 'plugins/focus-group/playbooks/plan.md',
                     'plugins/ape/references/planning-review.md', 'shared/upfront-agreement.md',
                     'plugins/imps/references/brief-probes.md'):
            self.assertIn('short rounds', (ROOT / name).read_text())
        probes = ' '.join((ROOT / 'plugins/imps/references/brief-probes.md').read_text().split())
        self.assertIn('one decision per question', probes)
        self.assertIn('Wait for the answer before the next round', probes)
        self.assertIn('routing scope (`routing_scope`: `invocation-only` or `global`)', probes)
        self.assertIn('and scoped work/paths are frozen', probes)
        self.assertIn('Retain supplied answers and skip their questions', probes)
        self.assertIn('only operation/capability/identity/resumable-scope preflight', probes)
        self.assertIn('independent authorised work may continue while unrelated later product questions', probes)
        self.assertIn('routing scope only if ambiguous', ralph)
        for directory in ('shared', 'plugins'):
            for path in sorted((ROOT / directory).rglob('*.md')):
                text = ' '.join(path.read_text().lower().split())
                for obsolete in ('batch only missing consequential decisions', 'ask a small batch'):
                    with self.subTest(path=str(path.relative_to(ROOT)), obsolete=obsolete):
                        self.assertNotIn(obsolete, text)
        for text in ('only recognized routing', 'setup-inferred custom basename',
                     '`profiles.models.lineage`', '`profiles.models.lineage_source`',
                     '`preferred_workhorse`', '`preferred: true`'):
            self.assertIn(text, contract)
        for family in set(models.FAMILY_LINEAGE.values()) | set(models.DRIVER_LINEAGE.values()):
            self.assertIn('`' + family + '`', contract)

    def test_saved_preference_discovery_prioritizes_only_eligible_exact_workhorse(self):
        data = canonical_selection_input()
        cheap = deepcopy(data['work']['workhorse'])
        cheap['model'] = 'alpha-small'
        data['capabilities']['providers'][0]['models'].insert(0,
            {**deepcopy(data['capabilities']['providers'][0]['models'][0]), 'id': cheap['model']})
        data['profiles']['models'].append({**deepcopy(data['profiles']['models'][0]), 'target': cheap})
        preferred = {k: data['work']['workhorse'][k] for k in ('providerInstanceId', 'model')}
        routing = {'roles': {'workhorse': [{**cheap, 'tier': 'low'},
                                          {**data['work']['workhorse'], 'tier': 'high'}]},
                   'preferred_workhorse': preferred}
        before = deepcopy(routing)
        legacy = {'roles': deepcopy(routing['roles'])}
        old = models.discover(data['capabilities'], data['profiles'], legacy)
        self.assertEqual([c['target']['model'] for c in old['candidates']], ['alpha-small', 'alpha-work'])
        self.assertNotIn('preferred_workhorse', old)
        for _ in range(2):
            result = models.discover(data['capabilities'], data['profiles'], routing)
            self.assertEqual([c['target']['model'] for c in result['candidates']], ['alpha-work', 'alpha-small'])
            self.assertTrue(result['candidates'][0]['preferred'])
            self.assertEqual(result['preference_status'], 'available')
        data['profiles']['models'][0]['quality'] = 0
        blocked = models.discover(data['capabilities'], data['profiles'], routing)
        self.assertEqual(blocked['preference_status'], 'unavailable')
        self.assertIn('quality >= 1', next(c for c in blocked['excluded'] if
                      c['target']['model'] == 'alpha-work')['reason'])
        self.assertFalse(any(c.get('preferred') for c in blocked['candidates']))
        data['capabilities']['providers'][0]['models'].pop()
        absent = models.discover(data['capabilities'], data['profiles'], routing)
        self.assertEqual(absent['preference_status'], 'unavailable')
        self.assertIn('absent from live capabilities', absent['excluded'][-1]['reason'])
        self.assertEqual(routing, before)
        del routing['preferred_workhorse']
        self.assertNotIn('preferred_workhorse', models.discover(data['capabilities'], data['profiles'], routing))

    def test_discovery_refuses_malformed_saved_preference(self):
        for preferred in (None, {}, {'providerInstanceId': 'fixture-work', 'model': 'absent'}):
            with self.subTest(preferred=preferred), self.assertRaisesRegex(models.SelectionError, 'preferred_workhorse'):
                models.discover(self.data['capabilities'], self.data['profiles'],
                                {'roles': {'workhorse': [self.data['work']['workhorse']]},
                                 'preferred_workhorse': preferred})

    def test_agreement_dispatch_preserves_global_scope_and_native_option_judgement(self):
        from tests.upfront_fixtures import agree
        data = canonical_selection_input()
        data.update(operation='ralph/run', routing_scope='global',
                    source=answer('Use the configured alpha-work as workhorse globally'))
        data['routing'] = {'roles': {'workhorse': [data['work']['workhorse']],
                                    'reviewer': [data['review_panel'][0]['target']]}}
        del data['profiles']['models'][0]
        # Native catalog values must still count as selectable effort, so a
        # reviewer does not need fixed-effort evidence for an adjustable model.
        data['capabilities']['providers'][1]['models'][0]['options'] = [
            {'id': 'effort', 'values': ['low', 'high']}]
        agree(data)
        record = models.freeze(data)
        plan = models.dispatch(record, role='workhorse')
        self.assertEqual(plan['routing_scope'], 'global')
        self.assertEqual(plan['agreement_sha256'], record['agreement']['agreement_sha256'])
        review = models.dispatch(record, role='reviewer', slot_id='review')
        self.assertEqual(review['routing_scope'], 'invocation-only')
        self.assertEqual(review['agreement_sha256'], plan['agreement_sha256'])
        with self.assertRaisesRegex(models.SelectionError, 'observed exact options unreported'):
            models.correlate(plan, {k: v for k, v in plan['target'].items() if k != 'options'})
        data['profiles']['models'][0]['judgement'] = False
        with self.assertRaisesRegex(models.SelectionError, 'provide profiles.models.judgement evidence'):
            models.freeze(data)

    def test_all_work_role_floors_and_joint_author_lineage(self):
        data = deepcopy(self.data); data['work']['judgement'] = deepcopy(data['work']['workhorse'])
        data['profiles']['models'][0]['quality'] = 1
        with self.assertRaises(models.SelectionError): models.freeze(data)
        data['profiles']['models'][0]['quality'] = 2
        models.freeze(data)
        data['work']['judgement'] = data['review_panel'][0]['target']
        with self.assertRaisesRegex(models.SelectionError, 'every actual/prospective author'):
            models.freeze(data)

    def test_two_primary_panel_members_are_obligations_not_alternatives(self):
        data = deepcopy(self.data)
        spare = {'providerInstanceId': 'fixture-spare', 'model': 'gamma-spare', 'options': {'effort': 'high'}}
        data['review_panel'].append({**deepcopy(data['review_panel'][0]), 'slot_id': 'second', 'target': spare})
        record = models.freeze(data)
        report = models.panel_report(record, [{'execution_id': 'one', 'slot_id': 'review', 'mode': 'cross-lineage'}])
        self.assertEqual(report['missing'], ['second'])
        report = models.panel_report(record, [{'execution_id': 'self', 'mode': 'self-review'}])
        self.assertEqual(report['actual_passes'], 1); self.assertTrue(report['degraded'])
        with self.assertRaisesRegex(models.SelectionError, 'several panel'):
            models.panel_report(record, [{'execution_id': 'same'}, {'execution_id': 'same'}])

    def test_unused_preference_does_not_enable_optional_code_review(self):
        data = deepcopy(self.data); data['review_panel'][0]['required'] = False
        record = models.freeze(data)
        with self.assertRaisesRegex(models.SelectionError, 'unused review preference'):
            models.dispatch(record, role='reviewer', slot_id='review')
        self.assertEqual(models.panel_report(record, [])['unused'], ['review'])

    def test_work_escalation_and_direct_fallback_need_work_authority(self):
        target = {'providerInstanceId': 'fixture-spare', 'model': 'gamma-spare', 'options': {'effort': 'high'}}
        data = deepcopy(self.data); data['review_replacements'] = [replacement(data, target, review=True)]
        record = models.freeze(data)
        failure = {'kind': 'technical', 'reference': 'fixture:failed-host-call'}
        with self.assertRaisesRegex(models.SelectionError, 'not authorised'):
            models.dispatch(record, role='workhorse', target=target, unavailable=failure)
        data['work_replacements'] = [replacement(data, target)]
        record = models.freeze(data)
        self.assertTrue(models.dispatch(record, role='workhorse', target=target, unavailable=failure)['substituted'])
        direct = {**data['work']['workhorse'], 'execution': 'current-context'}
        with self.assertRaises(models.SelectionError): models.dispatch(record, role='workhorse', target=direct, unavailable=failure)
        data['work_replacements'].append(replacement(data, direct))
        self.assertEqual(models.dispatch(models.freeze(data), role='workhorse', target=direct, unavailable=failure)['execution'], 'current-context')

    def test_replacement_authority_needs_no_monetary_budget(self):
        target = {'providerInstanceId': 'fixture-spare', 'model': 'gamma-spare', 'options': {'effort': 'high'}}
        data = deepcopy(self.data); data['work_replacements'] = [replacement(data, target)]
        limits = data['work_replacements'][0]['authority']['limits']
        limits.pop('max_cost')
        record = models.freeze(data)
        self.assertNotIn('max_cost', record['work_replacements'][0]['authority']['limits'])
        failure = {'kind': 'technical', 'reference': 'fixture:failed-host-call'}
        self.assertTrue(models.dispatch(record, role='workhorse', target=target, unavailable=failure)['substituted'])
        for value in (None, True, -1, '100', float('inf'), float('nan')):
            with self.subTest(value=value):
                limits['max_cost'] = value
                with self.assertRaisesRegex(models.SelectionError, 'cost limit'):
                    models.freeze(data)

    def test_no_unapproved_effort_increase_and_no_adverse_fallback_or_uncertain_duplicate(self):
        target = {'providerInstanceId': 'fixture-spare', 'model': 'gamma-spare', 'options': {'effort': 'high'}}
        data = deepcopy(self.data); data['work_replacements'] = [replacement(data, target)]
        record = models.freeze(data)
        for failure in (None, {'kind': 'adverse', 'reference': 'fixture:review'}):
            with self.assertRaises(models.SelectionError): models.dispatch(record, role='workhorse', target=target, unavailable=failure)
        with self.assertRaisesRegex(models.SelectionError, 'reconcile'):
            models.dispatch(record, role='workhorse', target=target, live_tasks=['uncertain'],
                            unavailable={'kind': 'technical', 'reference': 'fixture:host'})
        data['work_replacements'][0]['authority']['limits']['options'] = {'effort': ['low']}
        with self.assertRaisesRegex(models.SelectionError, 'exceeds authority'): models.freeze(data)

    def test_stronger_panel_refuses_same_lineage_replacement(self):
        data = deepcopy(self.data); target = deepcopy(data['work']['workhorse'])
        data['review_replacements'] = [replacement(data, target, review=True)]
        record = models.freeze(data)
        with self.assertRaisesRegex(models.SelectionError, 'stronger independent slot'):
            models.dispatch(record, role='reviewer', slot_id='review', target=target,
                            unavailable={'kind': 'technical', 'reference': 'fixture:host'})
        data['review_panel'][0]['independent'] = False
        self.assertTrue(models.dispatch(models.freeze(data), role='reviewer', slot_id='review', target=target,
                                       unavailable={'kind': 'technical', 'reference': 'fixture:host'})['substituted'])

    def test_primary_ordinary_scope_and_confidential_class_permission(self):
        models.dispatch(self.record, role='workhorse', data_classes=['repository', 'topic'])
        with self.assertRaisesRegex(models.SelectionError, 'confidential-class'):
            models.dispatch(self.record, role='workhorse', data_classes=['private-settings'])
        self.data['sharing'] = [{'target': self.data['work']['workhorse'], 'data_classes': ['private-settings'],
                                 'source': answer('Share the fixture private settings with this recipient.')}]
        models.dispatch(models.freeze(self.data), role='workhorse', data_classes=['private-settings'])

    def test_scope_continuations_aliases_new_commands_and_pinned_resume(self):
        for event in models.CONTINUATIONS | {'new'}:
            models.gate(self.record, invocation_id='fixture-invocation', scope_id='fixture-output', event=event)
        with self.assertRaisesRegex(models.SelectionError, 'new choices'):
            models.gate(self.record, invocation_id='fresh', scope_id='fixture-output')
        with self.assertRaises(models.SelectionError):
            models.gate(self.record, invocation_id='fixture-invocation', scope_id='another-output', event='forward')
        for retain in (None, False):
            with self.assertRaisesRegex(models.SelectionError, 'retain-or-stop'):
                models.gate(self.record, invocation_id='fixture-invocation', scope_id='fixture-output',
                            event='resume', pinned=True, retain=retain)
        models.gate(self.record, invocation_id='fixture-invocation', scope_id='fixture-output', event='resume', pinned=True, retain=True)

    def test_scheduled_reuse_requires_real_bound_authority_and_fresh_capabilities(self):
        kwargs = {'invocation_id': 'fixture-invocation', 'scope_id': 'fixture-output', 'event': 'schedule',
                  'schedule_id': 'fixture-schedule', 'capabilities': self.data['capabilities'],
                  'policy_digests': {name: self.record[name] for name in ('routing_sha256', 'profiles_sha256')}}
        with self.assertRaises(models.SelectionError): models.gate(self.record, **kwargs)
        self.data['schedule'] = {'schedule_id': 'fixture-schedule', 'source': answer('Reuse these choices for this fixture schedule.')}
        record = models.freeze(self.data); models.gate(record, **kwargs)
        kwargs['schedule_id'] = 'other'
        with self.assertRaises(models.SelectionError): models.gate(record, **kwargs)

    def test_tampering_producing_options_invalidates_and_prospective_changes_keep_evidence(self):
        changed = deepcopy(self.record); changed['work']['workhorse']['options']['reasoningEffort'] = 'low'
        with self.assertRaisesRegex(models.SelectionError, 'tampered'): models.validate(changed)
        data = deepcopy(self.data); data['work']['workhorse']['options']['reasoningEffort'] = 'low'
        current = models.freeze(data)
        with self.assertRaises(models.SelectionError): models.validate(current, self.record['selection_sha256'])
        state = {'accepted': [{'selection_sha256': self.record['selection_sha256'], 'content': 'same'}],
                 'findings': ['open-objection'], 'rounds_used': 2, 'round_limit': 3}
        new = models.prospective(self.record, current, state, requested_rereview=True)
        self.assertEqual(new['accepted'], state['accepted']); self.assertEqual(new['findings'], state['findings'])
        self.assertEqual(new['rounds_used'], 3)
        with self.assertRaises(models.SelectionError): models.prospective(self.record, current, new, requested_rereview=True)
        with self.assertRaises(models.SelectionError): models.prospective(self.record, current, {**state, 'live_tasks': ['owned']})

    def test_disputed_major_retains_original_lineage_obligation(self):
        rows = models.dispute_slots(self.record, [{'id': 'F-1', 'severity': 'major', 'disposition': 'rejected',
                                                   'reviewer_lineage': 'beta'}])
        self.assertEqual(rows[0]['dispute_only_slots'], ['review']); self.assertFalse(rows[0]['cleared'])

    def test_producing_receipt_survives_prospective_choice_but_not_producing_tampering(self):
        from shared.job_acceptance import _semantic_binding, AcceptanceError
        from shared.job_coordinator import selection_plan_revision
        task = {'task_id': 'fixture', 'stage_id': 'work', 'target': self.data['work']['workhorse'],
                'selection_binding': {'role': 'workhorse', 'selection_sha256': self.record['selection_sha256']}}
        stage = {'id': 'work', 'requirements': [], 'depends_on': []}
        job = {'tasks': [task], 'stages': [stage], 'dependencies': [],
               'policy': {'model_selection_required': True}, 'model_selection': self.record,
               'model_selection_sha256': self.record['selection_sha256']}
        before = _semantic_binding(job, stage)
        data = deepcopy(self.data); data['work']['workhorse']['options']['reasoningEffort'] = 'low'
        newer = models.freeze(data)
        changed = {**job, 'model_selection': newer, 'model_selection_sha256': newer['selection_sha256'],
                   'model_selection_history': {self.record['selection_sha256']: self.record}}
        self.assertEqual(before, _semantic_binding(changed, stage))
        selection_for_task(changed, task)
        proposed = {'tasks': [deepcopy(task)]}
        proposed['tasks'][0]['target'] = newer['work']['workhorse']
        with self.assertRaisesRegex(JobError, 'target/options differ'):
            selection_plan_revision(job, proposed)
        changed['model_selection_history'] = {self.record['selection_sha256']: newer}
        with self.assertRaises(AcceptanceError): _semantic_binding(changed, stage)

    def test_plan_revision_owner_decision_can_raise_agreed_repair_limit(self):
        from shared.job_coordinator import selection_plan_revision
        from core.jobs.store import digest
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'owner.txt'
            source.write_text('Owner approves the scoped repair budget increase.')
            decision = {'id': 'owner-limit', 'scope': 'plan:limit-one',
                        'quote': 'approves the scoped repair budget increase.',
                        'source': str(source), 'source_sha256': digest(source.read_bytes())}
            current = {'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 1024},
                       'model_selection': {'agreement': {'limits': {'max_repair_cycles': 3}}},
                       'decisions': [decision]}
            proposed = {'policy': {'max_repair_cycles': 4}}
            selection_plan_revision(current, proposed,
                                    {'id': 'limit-one', 'owner_decision_id': 'owner-limit'})
            with self.assertRaisesRegex(JobError, 'scoped owner decision'):
                selection_plan_revision(current, proposed,
                                        {'id': 'different-plan', 'owner_decision_id': 'owner-limit'})
            source.write_text('The owner record changed after review.')
            with self.assertRaisesRegex(JobError, 'scoped owner decision'):
                selection_plan_revision(current, proposed,
                                        {'id': 'limit-one', 'owner_decision_id': 'owner-limit'})

    def test_revision_cannot_enable_selection_without_proposed_choice(self):
        from shared.job_coordinator import selection_plan_revision
        current = {'policy': {'model_selection_required': False}, 'tasks': []}
        proposed = {'policy': {'model_selection_required': True}}
        with self.assertRaisesRegex(JobError, 'requires a proposed model_selection'):
            selection_plan_revision(current, proposed)

    def test_real_routing_cli_no_config_uses_profiles_and_keeps_recommendations_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            caps = root/'caps.json'; caps.write_text(json.dumps(self.data['capabilities']))
            profiles = root/'profiles.json'; profiles.write_text(json.dumps(self.data['profiles']))
            proc = subprocess.run([sys.executable, str(ROOT/'bin/t3-plugins'), 'resolve', 'reviewer',
                                   '--repo', str(root), '--profiles', str(profiles), '--capabilities', str(caps)],
                                  text=True, capture_output=True, timeout=30,
                                  env={**os.environ, 'HOME': str(root), 'XDG_CONFIG_HOME': str(root/'config')})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result['recommendation_only']); self.assertEqual(len(result['candidates']), 3)
            self.assertFalse((root/'config').exists())

    def test_invocation_only_not_persisted_and_project_grants_private_reusable_and_tamper_checked(self):
        grant = replacement(self.data, self.data['work']['workhorse'])['authority']
        with tempfile.TemporaryDirectory() as temporary:
            env = {'XDG_STATE_HOME': temporary}
            self.assertFalse(models.save_authority('fixture-project', grant, env)['persisted'])
            self.assertIsNone(models.load_authority('fixture-project', env))
            grant['scope'] = 'standing-project'
            saved = models.save_authority('fixture-project', grant, env)
            path = Path(saved['path']); self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(models.load_authority('fixture-project', env)['grant'], grant)
            self.assertEqual(models.applicable_authority('fixture-project', self.data['work']['workhorse'],
                                                        self.record, ['repository'], env), grant)
            self.assertIsNone(models.applicable_authority('fixture-project', self.data['work']['workhorse'],
                                                         self.record, ['private-settings'], env))
            data = json.loads(path.read_text()); data['grant']['limits'] = {}; path.write_text(json.dumps(data))
            with self.assertRaises(models.SelectionError): models.load_authority('fixture-project', env)
            with self.assertRaises(models.SelectionError): models.authority_path('../escape', env)

    def test_real_job_create_gate_refuses_missing_selection_before_install_or_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root / 'input.json'; path.write_text(json.dumps({'job_id': 'fixture-job'}))
            result = subprocess.run([sys.executable, str(ROOT / 'shared/job_cli.py'), 'create', '--state-root',
                                     str(root/'state'), '--job', 'fixture-job', '--prefix', str(root/'prefix'),
                                     '--agents-root', str(root/'agents'), '--input', str(path)],
                                    text=True, capture_output=True, cwd=ROOT, timeout=30)
            self.assertEqual(result.returncode, 2); self.assertIn('model selection missing', result.stderr)
            self.assertFalse((root/'state').exists())

    def test_real_prepare_gate_prevents_dropped_options_and_carries_frozen_brief_summary(self):
        task = {'task_id': 'fixture-task', 'request_id': 'fixture-request', 'role': 'worker', 'target': deepcopy(self.data['work']['workhorse']),
                'selection_binding': {'selection_sha256': self.record['selection_sha256'], 'role': 'workhorse'}}
        job = {'workflow': 'fixture/plan', 'tasks': [task], 'policy': {'model_selection_required': True}, 'model_selection': self.record,
               'model_selection_sha256': self.record['selection_sha256'], 'dependencies': []}
        class FixtureStore:
            def load(self): return job
            def transact(self, caller, callback, action): return callback(job)
        def atomic_prepare(store, caller, task_id, *args, bind_inputs=None, **kwargs):
            store.transact(caller, bind_inputs, 'prepare')
            return {'fixture': 'brief'}
        with mock.patch('core.jobs.prepare', side_effect=atomic_prepare) as prepared:
            result = prepare_task(FixtureStore(), {}, task['task_id'], lambda *_: True, lambda *_: True)
            self.assertEqual(result, {'fixture': 'brief'}); prepared.assert_called_once()
            self.assertEqual(task['model_selection']['dispatch']['target']['options'], {'reasoningEffort': 'high'})
            task['target']['options'] = {}
            with self.assertRaisesRegex(JobError, 'target/options differ'):
                prepare_task(FixtureStore(), {}, task['task_id'], lambda *_: True, lambda *_: True)
            self.assertEqual(prepared.call_count, 2)  # The second transaction refuses options before producing a brief.

    def test_actual_direct_stage_adapter_refuses_delegated_choice_and_missing_binding(self):
        from shared.job_coordinator import selection_for_direct_stage
        job = {'tasks': [], 'policy': {'model_selection_required': True}, 'model_selection': self.record,
               'model_selection_sha256': self.record['selection_sha256']}
        stage = {'id': 'direct', 'selection_binding': {'role': 'workhorse',
                 'selection_sha256': self.record['selection_sha256']}}
        with self.assertRaisesRegex(JobError, 'requires a child'):
            selection_for_direct_stage(job, stage, self.data['coordinator'])
        with self.assertRaisesRegex(JobError, 'current-context work binding'):
            selection_for_direct_stage(job, {'id': 'direct'}, self.data['coordinator'])
        data = deepcopy(self.data); data['work']['workhorse']['execution'] = 'current-context'
        record = models.freeze(data); job['model_selection'] = record
        stage['selection_binding']['selection_sha256'] = record['selection_sha256']
        evidence = selection_for_direct_stage(job, stage, {**data['coordinator'], 'options': {'reasoningEffort': 'high'}})
        self.assertEqual(evidence['observation']['options'], 'matched')


if __name__ == '__main__':
    unittest.main()
