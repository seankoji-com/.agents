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
from tests.model_selection_fixtures import answer, selection_input, replacement


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

    def test_cheap_or_first_model_is_not_quality_proof_and_fixed_effort_reason(self):
        data = deepcopy(self.data); data['profiles']['models'][0]['quality'] = 0
        result = models.discover(data['capabilities'], data['profiles'], role='reviewer')
        self.assertEqual(len(result['candidates']), 2)
        data = deepcopy(self.data)
        data['capabilities']['providers'][1]['models'][0]['options'] = []
        data['review_panel'][0]['target']['options'] = {}
        with self.assertRaisesRegex(models.SelectionError, 'unavailable or excluded'):
            models.freeze(data)
        data['profiles']['models'][1]['fixed_effort_reason'] = 'Fixture fixed-effort model meets bounded judgement floor.'
        self.assertTrue(models.freeze(data))

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
