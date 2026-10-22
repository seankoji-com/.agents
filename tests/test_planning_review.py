"""Public CLI planning acceptance with real pinned jobs; synthetic host events.

No model/provider calls. Source and installed entry points use the same receipts.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.jobs import store as job_store
from core.jobs.store import canonical, digest, JobError
from shared import model_selection as models
from shared import planning_review as planning
from tests.model_selection_fixtures import selection_input, replacement, answer
from tests.test_rebuild_installed import Sandbox, ROOT


class PlanningReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.box = Sandbox(Path(cls.temp.name))
        cls.package, cls.manifest = cls.box.install('imps')
        cls.serial = 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        type(self).serial += 1
        self.job_id = 'planning-' + str(self.serial)
        self.inputs = self.box.private / self.job_id
        self.inputs.mkdir()
        self.request = self.write('request.txt', 'Produce a safe fixture plan. Include recovery.')
        self.decision = self.write('decision.txt', 'Keep the fixture read-only.')
        self.plan = self.write('plan.md', '# Plan\nRead fixture, compare outcomes, report limitations.\n')
        self.rubric = self.write('rubric.md', 'Cover request satisfaction, feasibility, failure/recovery and a simpler alternative.')
        self.template = self.write('template.md', 'Render exact reviewed source.')
        self.source = self.write('source.py', 'VALUE = 1\n')
        self.extra = self.write('extra.py', 'EXTRA = 1\n')
        self.selection_data = json.loads(json.dumps(selection_input()).replace('alpha-work', 'gpt-fixture').replace('beta-review', 'claude-fixture').replace('gamma-spare', 'gemini-fixture').replace('"alpha"', '"openai"').replace('"beta"', '"anthropic"').replace('"gamma"', '"google"'))
        # Explicit degraded policy here applies only to this separate planning job.
        self.selection_data['review_panel'][0]['independent'] = False
        self.selection_data['review_panel'][0]['coverage'] = ['R1', 'R2', 'D1']
        self.selection_data['coordinator']['lineage'] = 'openai'
        self.snapshot_data = {'output_name': 'fixture-plan', 'output_type': 'implementation-plan',
            'requirements': {'R1': 'Safe fixture plan', 'R2': 'Recovery is explicit'}, 'load_bearing_decisions': ['D1'],
            'requests': [self.verbatim(self.request, 'fixture:request:' + self.job_id, 'R1')],
            'decisions': [self.verbatim(self.decision, 'fixture:decision:' + self.job_id, 'R2')],
            'documents': [str(self.plan)], 'rubrics': [str(self.rubric)], 'templates': [str(self.template)],
            'evidence_paths': [str(self.source), str(self.extra)], 'declared_paths': [str(self.source)],
            'authors': [self.selection_data['coordinator']], 'repository_head': 'fixture-head-before'}
        self.caller = None
        self.sequence = 0

    def write(self, name, text):
        path = self.inputs / name
        path.write_text(text)
        return path

    def verbatim(self, path, reference, requirement):
        return {'path': str(path), 'reference': reference, 'clauses': [
            {'start': 0, 'end': len(path.read_text()), 'requirement': requirement}]}

    def cli(self, command, data=None, ok=True, installed=False, job_id=None):
        self.sequence += 1
        data = dict(data or {})
        if command not in ('capture', 'create', 'validate'):
            data.setdefault('caller', self.caller)
        argv = [sys.executable, (self.package if installed else ROOT) / 'shared/planning_review_cli.py', command,
                '--input', self.box.payload(data), '--state-root', self.box.jobs, '--job', job_id or self.job_id]
        if command == 'create':
            argv += ['--prefix', self.box.prefix, '--agents-root', self.box.agents]
        proc = self.box.run(argv, check=False)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stdout[-1000:] + proc.stderr)
            return json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 2, proc.stdout[-1000:] + proc.stderr)
        return proc.stderr

    def create(self, *, extra=None, snapshot=None, installed=False, begin=True):
        self.snapshot = snapshot or self.cli('capture', self.snapshot_data)
        self.selection_data['scope_id'] = self.snapshot['logical_output_id']
        self.selection = models.freeze(self.selection_data)
        payload = {'job_id': self.job_id, 'installation_id': self.manifest['installation_id'],
                   'plugin': 'imps', 'project_id': self.selection['project_id'], 'owner': 'fixture-owner',
                   'invocation_id': self.selection['invocation_id'], 'scope_id': self.selection['scope_id'],
                   'selection': self.selection, 'snapshot': self.snapshot}
        payload.update(extra or {})
        self.created = self.cli('create', payload, installed=installed)
        self.caller = self.created['caller']
        if begin:
            self.cli('begin')
        return payload

    def attempt(self, slot='review'):
        return self.cli('launch', {'slot_id': slot, 'request_id': self.job_id + '-req-' + str(self.sequence)})

    def event(self, attempt, *, status='completed', identity=True, event_extra=None):
        target = attempt['target']
        event = {'kind': 'accepted', 'request_id': attempt['request_id'], 'host_task_id': 'host-' + attempt['request_id'],
                 'child_thread_id': 'child-' + attempt['request_id'], 'status': status,
                 'work_state': 'result_available' if status == 'completed' else 'working', 'has_pending_child_runs': False}
        if identity:
            event['status_identity'] = {k: target[k] for k in ('providerInstanceId', 'model', 'options')}
        event.update(event_extra or {})
        self.cli('host-event', {'task_id': attempt['task_id'], 'event': event})
        return event

    def assessment(self, responses=()):
        return {'coverage': [{'id': r, 'outcome': 'supported', 'evidence': 'fixture:read-and-counterexample'} for r in ('R1', 'R2', 'D1')],
                'inspected_paths': [str(self.source)], 'responses': list(responses)}

    def result(self, attempt, *, findings=(), verdict='approve', edit=None, identity=True, observe=True):
        if observe:
            self.event(attempt, identity=identity)
        brief = json.loads(Path(attempt['path']).read_text())
        result = {k: brief[k] for k in ('schema_version', 'job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision')}
        result.update(status='ready-for-acceptance', conclusion='Fixture evidence supports the declared plan.',
            requirements=[{'id': r['id'], 'status': 'passed', 'evidence': 'fixture:observed'} for r in brief['requirements']],
            review_verdict=verdict, findings=list(findings), gaps=[], uncertainties=[], changes=[], commands=[], artifacts=[],
            binding=brief.get('snapshot'), extra_work_requests=[], metrics={}, planning_review=self.assessment())
        if edit:
            edit(result)
        path = self.write('result-' + str(self.sequence) + '.json', json.dumps(result))
        return self.cli('result', {'task_id': attempt['task_id'], 'result_file': str(path), 'completion_id': 'done-' + attempt['request_id']})

    def finding(self, severity='major', id='F1'):
        return {'id': id, 'severity': severity, 'scenario': 'Recovery omits the interrupted-read case.',
                'source_evidence': 'fixture:plan-recovery', 'smallest_correction': 'Describe interrupted-read recovery.'}

    def unavailable(self, attempt):
        return self.cli('unavailable', {'task_id': attempt['task_id'], 'failure': {'kind': 'technical',
            'tool': 'fixture-delegate', 'call_id': 'call-' + attempt['request_id'], 'request_id': attempt['request_id'],
            'receipt': {'error': 'fixture prelaunch unavailable'}, 'prelaunch': True}})

    def add_self(self):
        row = replacement(self.selection_data, self.selection_data['coordinator'], review=True)
        row.pop('target')
        row['execution'] = 'self-review'
        self.selection_data['review_replacements'].append(row)

    def direct(self, *, responses=(), findings=(), verdict='approve', change=None, ok=True):
        obs = {'schema_version': 1, 'kind': 'planning-direct', 'pass_id': 'self-' + self.job_id + '-' + str(self.sequence),
            'identity': {k: self.selection['coordinator'][k] for k in ('providerInstanceId', 'model', 'observed_options')},
            'identity_reference': 'fixture:active-session-report', 'snapshot_sha256': self.snapshot['sha256'],
            'selection_sha256': self.selection['selection_sha256'], 'requirements': [
                {'id': r, 'status': 'passed', 'evidence': 'fixture:explicit-self-check'} for r in ('R1', 'R2')],
            'review_verdict': verdict, 'findings': list(findings), 'assessment': self.assessment(responses)}
        if change:
            change(obs)
        return self.cli('direct', {'observation': obs}, ok=ok)

    def finish(self, accepted=True):
        out = self.cli('finish')
        self.assertEqual(out['accepted'], accepted)
        return out['reference']

    def test_delegated_public_acceptance_and_installed_parent_consumption(self):
        self.create(installed=True)
        attempt = self.attempt()
        self.assertEqual(attempt['target']['options'], {'effort': 'high'})
        outcome = self.result(attempt)
        self.assertEqual(outcome['outcome'], 'approved')
        reference = self.finish()
        receipt = self.cli('validate', {'reference': reference, 'expected_snapshot': self.snapshot['sha256']}, installed=True)
        self.assertEqual(receipt['passes'][0]['mode'], 'cross-lineage')
        self.assertEqual(receipt['rounds_used'], 1)
        # Unrelated file/HEAD metadata is absent from the relevant evidence set.
        self.write('unrelated.py', 'UNRELATED = 2\n')
        self.cli('validate', {'reference': reference})

    def test_prepare_failure_does_not_charge_subject(self):
        for failure in ('brief', 'schema'):
            with self.subTest(failure=failure):
                if self.caller:
                    self.setUp()
                self.create(begin=False)
                store = planning.pinned_store(self.box.jobs, self.job_id)
                subject = Path(self.created['subject_file'])
                before = (store.file.read_bytes(), subject.read_bytes())
                self.assertIn('begin a counted content round', self.cli('launch', {
                    'slot_id': 'review', 'request_id': 'before-begin'}, ok=False))
                self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)
                self.cli('begin')
                before = (store.file.read_bytes(), subject.read_bytes())
                validate = job_store.validate
                def reject_prepared(job):
                    validate(job)
                    if job['tasks']:
                        raise JobError('fixture post-binding schema rejection')
                    return job
                injection = (patch('core.jobs._retain', side_effect=JobError('fixture brief write rejection'))
                             if failure == 'brief' else patch.object(job_store, 'validate', reject_prepared))
                with injection, self.assertRaisesRegex(JobError, 'fixture'):
                    planning.launch(store, self.caller, 'review', 'failed-prepare', environ=self.box.env)
                self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)
                attempt = self.cli('launch', {'slot_id': 'review', 'request_id': 'failed-prepare'})
                self.assertEqual(attempt['task_id'], 'review-1')
                self.assertEqual(json.loads(subject.read_bytes())['technical_used'], 1)

    def test_committed_preparation_recovers_subject_charge_once(self):
        for failure in ('subject-save', 'overview-after-commit'):
            with self.subTest(failure=failure):
                if self.caller:
                    self.setUp()
                self.create()
                store = planning.pinned_store(self.box.jobs, self.job_id)
                subject = Path(self.created['subject_file'])
                before = subject.read_bytes()
                injection = (patch.object(planning.Subject, 'save', side_effect=OSError('fixture interrupted save'))
                             if failure == 'subject-save' else
                             patch.object(store, 'overview', side_effect=OSError('fixture interrupted overview')))
                payload = {'slot_id': 'review', 'request_id': 'recover-charge'}
                with injection, self.assertRaisesRegex(OSError, 'fixture interrupted'):
                    planning.launch(store, self.caller, **payload, environ=self.box.env)
                prepared = store.file.read_bytes()
                self.assertEqual(subject.read_bytes(), before)
                self.assertEqual(len(store.load()['tasks']), 1)
                self.assertIn('brief', store.load()['tasks'][0])
                self.assertIn('same-request', self.cli('launch', dict(payload, request_id='replacement'), ok=False))
                self.assertIn('same-request', self.cli('release', ok=False))
                replay = self.cli('launch', payload)
                self.assertEqual(replay['task_id'], 'review-1')
                self.assertEqual(store.file.read_bytes(), prepared)
                charged = subject.read_bytes()
                state = json.loads(charged)
                self.assertEqual(state['technical_used'], 1)
                self.assertEqual(state['rounds'][-1]['attempts'], store.load()['planning']['attempts'])
                self.cli('launch', payload)
                self.assertEqual((store.file.read_bytes(), subject.read_bytes()), (prepared, charged))

    def test_retained_replay_rejects_changed_target(self):
        self.create()
        attempt = self.attempt()
        store = planning.pinned_store(self.box.jobs, self.job_id)
        def drift(job):
            job['planning']['attempts'][0]['target']['model'] = 'different-fixture-model'
        store.mutate(self.caller, drift)
        subject = Path(self.created['subject_file'])
        before = (store.file.read_bytes(), subject.read_bytes())
        self.assertIn('target binding differs', self.cli('launch', {
            'slot_id': 'review', 'request_id': attempt['request_id']}, ok=False))
        self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)

    def test_uncharged_attempt_refuses_outcomes_without_writes(self):
        self.create()
        store = planning.pinned_store(self.box.jobs, self.job_id)
        subject = Path(self.created['subject_file'])
        payload = {'slot_id': 'review', 'request_id': 'interrupted-charge'}
        with patch.object(planning.Subject, 'save', side_effect=OSError('fixture interrupted charge')):
            with self.assertRaises(OSError):
                planning.launch(store, self.caller, **payload, environ=self.box.env)
        task = store.load()['tasks'][0]
        attempt = dict(task['brief'], target=task['target'], mode='cross-lineage')
        before = (store.file.read_bytes(), subject.read_bytes())
        failure = {'kind': 'technical', 'tool': 'fixture-delegate', 'call_id': 'fixture-failed-call',
                   'request_id': payload['request_id'], 'receipt': {'error': 'fixture prelaunch refusal'},
                   'prelaunch': True}
        self.assertIn('same-request launch reconciliation', self.cli('unavailable', {
            'task_id': task['task_id'], 'failure': failure}, ok=False))
        self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)
        self.assertIn('same-request', self.cli('release', ok=False))
        self.assertIn('same-request', self.cli('launch', dict(payload, request_id='replacement'), ok=False))
        # Even an observed owned completion cannot ingest material before replay
        # recovers the durable technical charge. Host observations do not dispatch.
        self.event(attempt)
        before = (store.file.read_bytes(), subject.read_bytes())
        raw = self.write('unreconciled-result.json', '{}')
        self.assertIn('same-request launch reconciliation', self.cli('result', {
            'task_id': task['task_id'], 'result_file': str(raw), 'completion_id': 'uncharged-completion'}, ok=False))
        self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)
        replay = self.cli('launch', payload)
        self.assertEqual(json.loads(subject.read_bytes())['technical_used'], 1)
        self.assertEqual(self.result(replay, observe=False)['outcome'], 'approved')
        self.assertEqual(json.loads(subject.read_bytes())['technical_used'], 1)

    def test_owned_request_replay_is_read_only(self):
        self.create()
        attempt = self.attempt()
        event = self.event(attempt, status='running')
        store = planning.pinned_store(self.box.jobs, self.job_id)
        subject = Path(self.created['subject_file'])
        for phase in ('accepted', 'completed'):
            with self.subTest(phase=phase):
                if phase == 'completed':
                    event.update(kind='completion', completion_id='replay-completion', status='completed',
                                 work_state='result_available')
                    self.cli('host-event', {'task_id': attempt['task_id'], 'event': event})
                before = (store.file.read_bytes(), subject.read_bytes())
                replay = self.cli('launch', {'slot_id': 'review', 'request_id': attempt['request_id']})
                for key in ('path', 'sha256', 'target', 'task_id', 'request_id', 'mode'):
                    self.assertEqual(replay[key], attempt[key])
                self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)

    def test_host_event_uses_local_receipt_time(self):
        self.create()
        attempt = self.attempt()
        event = self.event(attempt, status='running')
        store = planning.pinned_store(self.box.jobs, self.job_id)
        subject = Path(self.created['subject_file'])
        for kind in ('identity', 'approval-wait', 'approval-resolved'):
            for stamp in ('1999-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00', None):
                before = (store.file.read_bytes(), subject.read_bytes())
                supplied = dict(event, kind=kind, wait_id='owner-choice', recorded_at=stamp)
                self.assertIn('local receipt time', self.cli('host-event', {
                    'task_id': attempt['task_id'], 'event': supplied}, ok=False))
                self.assertEqual((store.file.read_bytes(), subject.read_bytes()), before)
        for kind, stamp in (('approval-wait', '2026-01-01T00:00:00+00:00'),
                            ('approval-resolved', '2026-01-01T00:00:30+00:00')):
            observation = dict(event, kind=kind, wait_id='owner-choice')
            with patch('shared.planning_review.observed_now', return_value=stamp):
                planning.host_event(store, self.caller, attempt['task_id'], observation)
            self.assertNotIn('recorded_at', observation)
            self.assertEqual(store.load()['tasks'][0]['dispatch_history'][-1]['recorded_at'], stamp)
        from shared.job_coordination import coordination_metrics
        self.assertEqual(coordination_metrics(store.load())['resolved_decision_wait_seconds'], 30)

    def test_separate_manifest_policy_and_stronger_slot_relabelling_refused(self):
        self.snapshot = self.cli('capture', self.snapshot_data)
        self.selection_data['scope_id'] = self.snapshot['logical_output_id']
        self.selection = models.freeze(self.selection_data)
        payload = {'job_id': self.job_id, 'installation_id': self.manifest['installation_id'], 'plugin': 'imps',
            'project_id': self.selection['project_id'], 'owner': 'fixture-owner', 'invocation_id': self.selection['invocation_id'],
            'scope_id': self.selection['scope_id'], 'selection': self.selection, 'snapshot': self.snapshot,
            'stages': [{'id': 'cold-read', 'independent_of_author': True}]}
        self.assertIn('cannot relabel', self.cli('create', payload, ok=False))
        payload.pop('stages'); payload['plugin'] = 'ape'
        self.assertIn('planning_review_error', self.cli('create', payload, ok=False))
        self.snapshot_data['output_type'] = 'code-review'
        bad = self.cli('capture', self.snapshot_data)
        payload.update(plugin='imps', snapshot=bad)
        self.assertIn('not permitted', self.cli('create', payload, ok=False))

    def test_provider_limits_freeze_and_installed_launch_refuses_without_charging(self):
        config = self.box.config / 't3-plugins/workers.json'
        old = config.read_bytes() if config.exists() else None
        self.addCleanup(lambda: config.write_bytes(old) if old is not None else config.unlink())
        config.parent.mkdir(parents=True, exist_ok=True)
        target = self.selection_data['review_panel'][0]['target']
        caps = {target['providerInstanceId']: 1}
        config.write_text(json.dumps({'schema_version': 1, 'max_live_workers': None,
            'max_live_workers_by_provider': caps, 'max_repair_cycles': 20, 'overrides': []}))
        self.create(installed=True)
        store = planning.pinned_store(self.box.jobs, self.job_id)
        self.assertEqual(store.load()['policy']['max_live_workers_by_provider'], caps)
        held = {'kind': 'conflicting-host-handle', 'task_id': 'retained-task',
                'request_id': 'retained-request', 'host_task_id': 'retained-host'}
        store.mutate(self.caller, lambda job: job.setdefault('blockers', []).append(held))
        before_job = store.file.read_bytes()
        subject = Path(self.created['subject_file'])
        before_subject = subject.read_bytes()
        payload = {'slot_id': 'review', 'request_id': self.job_id + '-admission'}
        self.assertIn('provider_worker_limit', self.cli('launch', payload, ok=False, installed=True))
        self.assertEqual(store.file.read_bytes(), before_job)
        self.assertEqual(subject.read_bytes(), before_subject)
        def settled(job):
            job['blockers'][-1]['reconciled'] = {'status': 'cancelled',
                'work_state': 'result_available', 'has_pending_child_runs': False}
        store.mutate(self.caller, settled)
        attempt = self.cli('launch', payload, installed=True)
        from shared.job_coordination import coordination_metrics, occupancy
        self.assertEqual(len(occupancy(store.load())), 1)
        before_job, before_subject = store.file.read_bytes(), subject.read_bytes()
        replay = self.cli('launch', payload, installed=True)
        for key in ('path', 'sha256', 'target', 'task_id', 'request_id', 'mode'):
            self.assertEqual(replay[key], attempt[key])
        self.assertEqual(store.file.read_bytes(), before_job)
        self.assertEqual(subject.read_bytes(), before_subject)
        self.cli('host-event', {'task_id': attempt['task_id'],
            'event': {'kind': 'capacity-deferred', 'request_id': attempt['request_id']}})
        before_job, before_subject = store.file.read_bytes(), subject.read_bytes()
        self.assertIn('owned_completion_required', self.cli('launch', payload, ok=False, installed=True))
        self.assertEqual(store.file.read_bytes(), before_job)
        self.assertEqual(subject.read_bytes(), before_subject)
        self.unavailable(attempt)
        self.assertEqual(occupancy(store.load()), [])
        self.assertEqual(coordination_metrics(store.load())['executions_with_results'], 0)
        self.assertEqual(len(json.loads(subject.read_text())['rounds'][-1]['attempts']), 1)

    def test_missing_and_tampered_selection_refused(self):
        self.selection_data['source']['sha256'] = '0'*64
        with self.assertRaises(models.SelectionError):
            models.freeze(self.selection_data)
        self.selection_data['source'] = answer()
        self.create()
        attempt = self.attempt()
        self.result(attempt)
        reference = self.finish()
        file = self.box.jobs / self.job_id / 'job.json'
        data = json.loads(file.read_text());data['model_selection']['review_panel'][0]['target']['options'] = {}
        file.write_text(json.dumps(data))
        self.assertIn('changed', self.cli('validate', {'reference': reference}, ok=False))

    def test_strict_partial_and_contradictory_results_retain_findings(self):
        for missing_coverage in (True, False):
            with self.subTest(missing_coverage=missing_coverage):
                if self.caller:
                    self.setUp()
                self.create()
                a = self.attempt()
                def edit(result):
                    if missing_coverage:
                        result['planning_review']['coverage'].pop()
                    else:
                        result['review_verdict'] = 'approve'
                outcome = self.result(a, findings=[self.finding()], verdict='adverse', edit=edit)
                self.assertEqual(outcome['outcome'], 'incomplete')
                self.finish(accepted=False)
                state = json.loads(Path(self.created['subject_file']).read_text())
                self.assertIn('anthropic:F1', state['findings'])
                self.assertEqual(state['findings']['anthropic:F1']['status'], 'open')
                self.assertIn('substantive', self.cli('unavailable', {'task_id': a['task_id'], 'failure': {}}, ok=False))

    def test_complete_adverse_never_becomes_technical_fallback(self):
        self.add_self();self.create()
        a = self.attempt()
        out = self.result(a, findings=[self.finding()], verdict='adverse')
        self.assertEqual(out['outcome'], 'adverse')
        self.assertIn('slot already reviewed', self.cli('launch', {'slot_id': 'review', 'request_id': 'shopping'}, ok=False))
        self.direct(ok=False)
        self.finish(accepted=False)

    def test_incomplete_responses_preserve_findings_for_child_and_direct(self):
        for direct in (False, True):
            for invalid_first in (False, True):
                with self.subTest(direct=direct, invalid_first=invalid_first):
                    if self.caller:
                        self.setUp()
                    self.add_self()
                    self.create()
                    self.result(self.attempt(), findings=[self.finding()], verdict='adverse')
                    reference = self.finish(accepted=False)
                    original = json.loads(Path(reference['path']).read_text())['findings']['anthropic:F1']
                    self.plan.write_text(self.plan.read_text() + 'Handle interrupted reads explicitly.\n')
                    self.snapshot = self.cli('capture', self.snapshot_data)
                    self.cli('begin', {'snapshot': self.snapshot})
                    responses = [
                        {'finding_key': 'anthropic:F1', 'status': 'fixed', 'evidence': 'fixture:repair'},
                        {'finding_key': 'anthropic:unknown', 'status': 'fixed', 'evidence': 'fixture:invalid'}]
                    if invalid_first:
                        responses.reverse()
                    if direct:
                        self.unavailable(self.attempt())
                        outcome = self.direct(responses=responses)
                    else:
                        def edit(result):
                            result['planning_review']['responses'] = responses
                        outcome = self.result(self.attempt(), edit=edit)
                    self.assertEqual(outcome['outcome'], 'incomplete')
                    self.assertIn('unknown retained finding', outcome['error'])
                    reference = self.finish(accepted=False)
                    receipt = json.loads(Path(reference['path']).read_text())
                    if receipt['findings']['anthropic:F1'] != original:
                        raise AssertionError('incomplete pass changed the retained finding or its history')
                    self.assertIn('anthropic:F1', receipt['open_adverse_findings'])
                    # A later approval must still address the original major.
                    self.cli('begin', {'snapshot': self.snapshot})
                    attempt = self.attempt()
                    brief = json.loads(Path(attempt['path']).read_text())
                    self.assertIn('anthropic:F1', json.dumps(brief))
                    self.assertEqual(self.result(attempt)['outcome'], 'adverse')
                    self.finish(accepted=False)

    def test_cross_lineage_replacement_then_same_lineage_after_real_failures(self):
        self.selection_data['review_replacements'] = [replacement(self.selection_data,
            {'providerInstanceId': 'fixture-spare', 'model': 'gemini-fixture', 'options': {'effort': 'high'}}, review=True),
            replacement(self.selection_data, self.selection_data['work']['workhorse'], review=True)]
        self.create()
        first = self.attempt();self.unavailable(first)
        spare = self.attempt();self.assertEqual(spare['target']['providerInstanceId'], 'fixture-spare');self.unavailable(spare)
        same = self.attempt();self.assertEqual(same['mode'], 'same-lineage')
        self.result(same)
        ref = self.finish()
        receipt = self.cli('validate', {'reference': ref})
        self.assertTrue(receipt['degraded_panel']);self.assertEqual(receipt['rounds_used'], 1)
        self.assertEqual(receipt['technical_used'], 3)

    def test_direct_after_finite_chain_no_fabricated_child_identity(self):
        self.add_self();self.create()
        self.direct(ok=False)
        self.unavailable(self.attempt())
        self.direct(change=lambda o:o.update(host_task_id='fabricated'), ok=False)
        out = self.direct()
        self.assertEqual(out['mode'], 'self-review')
        ref = self.finish()
        receipt = self.cli('validate', {'reference': ref})
        self.assertTrue(receipt['degraded_panel']);self.assertEqual(len(receipt['passes']), 1)
        self.assertNotIn('child_thread_id', receipt['passes'][0])

    def test_uncertain_launch_stable_request_and_no_replacement_or_direct(self):
        self.add_self();self.create()
        a = self.attempt()
        self.cli('host-event', {'task_id': a['task_id'], 'event': {'kind': 'uncertain', 'request_id': a['request_id']}})
        self.assertIn('uncertain', self.cli('launch', {'slot_id': 'review', 'request_id': 'replacement'}, ok=False))
        self.assertIn('uncertain', self.cli('unavailable', {'task_id': a['task_id'], 'failure': {}}, ok=False))
        self.direct(ok=False)
        self.event(a)
        self.result(a, observe=False)
        self.finish()

    def test_wrong_observed_identity_options_and_pending_work_block(self):
        for kind in ('missing', 'options', 'pending', 'provider'):
            with self.subTest(kind=kind):
                if self.caller:
                    self.setUp()
                self.create();a = self.attempt()
                observed = {k:a['target'][k] for k in ('providerInstanceId','model','options')}
                if kind == 'options':observed['options'] = {'effort':'low'}
                if kind == 'provider':observed['providerInstanceId'] = 'wrong'
                self.event(a, identity=kind != 'missing', status='running' if kind == 'pending' else 'completed',
                           event_extra={'status_identity': observed} if kind in ('options','provider') else {})
                if kind == 'pending':
                    with self.assertRaises(AssertionError):
                        self.result(a, observe=False)
                    self.cli('finish', ok=False)
                else:
                    out=self.result(a, observe=False)
                    self.assertEqual(out['outcome'], 'incomplete')
                    self.finish(accepted=False)

    def test_tampered_result_request_artifact_and_relevant_drift_refused(self):
        self.create();a = self.attempt();self.result(a);ref = self.finish()
        self.source.write_text('VALUE = 2\n')
        self.assertIn('drift', self.cli('validate', {'reference': ref}, ok=False))
        self.source.write_text('VALUE = 1\n')
        self.decision.write_text('Changed owner decision.')
        self.assertIn('drift', self.cli('validate', {'reference': ref}, ok=False))
        self.decision.write_text('Keep the fixture read-only.')
        job = self.box.state_of(self.job_id)
        path = Path(job['tasks'][0]['result_ref']['transport_path']);path.write_text('{}')
        self.assertIn('changed', self.cli('validate', {'reference': ref}, ok=False))

    def test_request_clause_omission_and_unexpected_dirty_read_refused(self):
        self.snapshot_data['requests'][0]['clauses'][0]['end'] -= 1
        self.assertIn('omitted', self.cli('capture', self.snapshot_data, ok=False))
        self.snapshot_data['requests'][0]['clauses'][0]['end'] += 1
        self.create();a = self.attempt()
        self.extra.write_text('EXTRA = 2\n')
        def edit(result):result['planning_review']['inspected_paths'].append(str(self.extra))
        outcome = self.result(a, edit=edit)
        self.assertEqual(outcome['outcome'], 'incomplete');self.assertIn('drift', outcome['error'])
        self.finish(accepted=False)

    def test_persistent_budget_new_jobs_and_explicit_owner_limit(self):
        self.create()
        for number in range(3):
            if number:self.cli('begin', {'requested_rereview': True})
            self.result(self.attempt(), findings=[self.finding()], verdict='adverse')
            self.finish(accepted=False)
        self.assertIn('budget exhausted', self.cli('begin', {'requested_rereview':True}, ok=False))
        self.cli('release')
        self.job_id += '-replacement'
        self.assertRaises(AssertionError, self.create, snapshot=self.snapshot, begin=False)
        # The failed reset cannot alter the retained subject history.
        state = json.loads(Path(self.created['subject_file']).read_text())
        self.assertEqual(state['rounds_used'], 3);self.assertIn('anthropic:F1', state['findings'])

    def test_same_output_concurrent_job_refused_across_adopter_labels(self):
        self.create()
        original = self.job_id
        self.job_id += '-second'
        with self.assertRaises(AssertionError):self.create(snapshot=self.snapshot, begin=False)
        state = json.loads(Path(self.created['subject_file']).read_text())
        self.assertEqual(state['active_job']['job_id'], original)
        self.assertEqual(state['rounds_used'], 0)

    def test_rejected_major_requires_original_lineage_child_or_actual_repair(self):
        self.create();self.result(self.attempt(), findings=[self.finding()], verdict='adverse');self.finish(accepted=False)
        evidence = self.write('rebuttal.txt', 'Interrupted fixture reads are restarted by the caller.')
        self.cli('disposition', {'finding_key':'anthropic:F1','status':'rejected','evidence':{'reason':'Caller owns restart','source':str(evidence)}})
        self.cli('begin', {'requested_rereview':True})
        response = {'finding_key':'anthropic:F1','status':'rebuttal-agreed','evidence':'fixture:caller-restart-source'}
        outcome = self.result(self.attempt(), edit=lambda r:r['planning_review'].update(responses=[response]))
        self.assertEqual(outcome['outcome'], 'approved');self.finish()

    def test_self_review_cannot_erase_unchanged_rejected_major(self):
        self.add_self();self.create();self.result(self.attempt(), findings=[self.finding()], verdict='adverse');self.finish(accepted=False)
        evidence = self.write('rebuttal.txt', 'Author disagrees.')
        self.cli('disposition', {'finding_key':'anthropic:F1','status':'rejected','evidence':{'reason':'disagree','source':str(evidence)}})
        self.cli('begin', {'requested_rereview':True});self.unavailable(self.attempt())
        response = {'finding_key':'anthropic:F1','status':'rebuttal-agreed','evidence':'fixture:author-opinion'}
        out = self.direct(responses=[response])
        self.assertEqual(out['outcome'], 'incomplete');self.finish(accepted=False)
        self.cli('begin', {'requested_rereview':True});self.unavailable(self.attempt())
        out = self.direct()
        self.assertEqual(out['outcome'],'adverse');self.finish(accepted=False)

    def test_repaired_content_and_minor_deferral_are_reviewed(self):
        self.create();self.result(self.attempt(), findings=[self.finding(), self.finding('minor','F2')], verdict='adverse');self.finish(accepted=False)
        self.plan.write_text(self.plan.read_text() + '\nInterrupted reads restart without writes.\n')
        self.snapshot = self.cli('capture', self.snapshot_data)
        self.cli('begin', {'snapshot':self.snapshot})
        responses = [{'finding_key':'anthropic:F1','status':'fixed','evidence':'fixture:added-recovery'},
            {'finding_key':'anthropic:F2','status':'deferred','evidence':'fixture:bounded-impact','impact':'Stylistic example only','owner':'fixture-owner','next_action':'Revisit on next substantive edit'}]
        self.result(self.attempt(), edit=lambda r:r['planning_review'].update(responses=responses))
        self.finish()

    def test_private_evidence_recomputes_sharing_and_rejects_invented_exclusions(self):
        self.add_self()
        self.snapshot_data['documents'] = [{'path':str(self.plan),'data_class':'private-settings'}]
        self.create()
        next_ = self.cli('next', {'slot_id':'review','exclusions':{'privacy':'invented'}})
        self.assertIsNone(next_)
        # Primary selection permits ordinary topic data only; no confidential launch occurs.
        self.assertIn('unavailable', self.cli('launch', {'slot_id':'review','request_id':'private'}, ok=False))
        self.direct(ok=False)  # Review replacement grant also lacks private-settings.

    def test_private_explicit_grant_then_revocation_and_ordinary_boundary_reuse(self):
        target = self.selection_data['review_panel'][0]['target']
        self.selection_data['sharing'] = [{'target':target,'data_classes':['private-settings'],
                                          'source':answer('Share this fixture private-settings input with the selected reviewer.')}]
        self.snapshot_data['documents'] = [{'path':str(self.plan),'data_class':'private-settings'}]
        self.create()
        self.cli('next', {'slot_id':'review','sharing':[]}, ok=False)
        self.assertIsNotNone(self.cli('next', {'slot_id':'review'}))
        revocation=self.write('revocation.txt','Revoke this fixture private-settings recipient grant.')
        self.cli('revoke-sharing', {'grants':self.selection['sharing'],'source':answer(revocation.read_text()),'source_file':str(revocation)})
        self.assertIsNone(self.cli('next', {'slot_id':'review'}))
        self.cli('launch', {'slot_id':'review','request_id':'revoked-private'}, ok=False)
        self.cli('release');self.job_id+='-new';self.create(snapshot=self.snapshot)
        self.assertIsNone(self.cli('next', {'slot_id':'review'}))

    def test_repaired_snapshot_recomputes_confidential_child_and_direct_scope(self):
        self.add_self()
        self.create()
        self.result(self.attempt(), verdict='adverse')
        self.finish(accepted=False)
        self.snapshot_data['documents'] = [{'path':str(self.plan),'data_class':'private-settings'}]
        self.snapshot = self.cli('capture', self.snapshot_data)
        self.cli('begin', {'snapshot':self.snapshot})
        state = self.box.state_of(self.job_id)
        self.assertIn('private-settings', state['planning']['data_classes'])
        self.assertEqual(state['planning']['snapshot'], self.snapshot)
        self.assertIsNone(self.cli('next', {'slot_id':'review'}))
        self.assertIn('unavailable', self.cli('launch',
            {'slot_id':'review','request_id':'private-repair'}, ok=False))
        self.assertIn('sharing exceeds authority', self.direct(ok=False))
        self.assertEqual(len(self.box.state_of(self.job_id)['tasks']), 1,
                         'no private child brief was prepared for the repair')

    def test_snapshot_scope_refresh_retains_explicit_classes_only(self):
        self.snapshot_data['documents'] = [{'path':str(self.plan),'data_class':'private-settings'}]
        self.create(extra={'data_classes':['repository','public']}, begin=False)
        # Before the first round the candidate becomes ordinary; private-settings
        # came from the replaced input, while the explicit public scope remains.
        self.snapshot_data['documents'] = [str(self.plan)]
        self.snapshot = self.cli('capture', self.snapshot_data)
        self.cli('begin', {'snapshot':self.snapshot})
        state = self.box.state_of(self.job_id)
        self.assertIn('public', state['planning']['data_classes'])
        self.assertNotIn('private-settings', state['planning']['data_classes'])
        self.assertIsNotNone(self.cli('next', {'slot_id':'review'}))

    def test_panel_members_are_obligations_not_fallback_alternatives(self):
        spare = deepcopy(self.selection_data['review_panel'][0]);spare['slot_id']='second'
        spare['target']={'providerInstanceId':'fixture-spare','model':'gemini-fixture','options':{'effort':'high'}}
        self.selection_data['review_panel'].append(spare)
        self.create();self.result(self.attempt())
        self.finish(accepted=False)
        self.cli('begin', {'requested_rereview':True});self.result(self.attempt());self.result(self.attempt('second'));self.finish()

    def test_changed_finding_reemission_remains_finishable_and_retained(self):
        for mode in ('child', 'partial-child', 'direct'):
            with self.subTest(mode=mode):
                if mode != 'child':
                    self.setUp()
                if mode == 'direct':
                    self.add_self()
                self.create()
                original = self.finding()
                if mode == 'direct':
                    self.unavailable(self.attempt()); self.direct(findings=[original], verdict='adverse')
                else:
                    self.result(self.attempt(), findings=[original], verdict='adverse')
                self.finish(accepted=False)
                self.plan.write_text(self.plan.read_text() + 'Handle interrupted reads explicitly.\n')
                self.snapshot = self.cli('capture', self.snapshot_data)
                self.cli('begin', {'snapshot': self.snapshot})
                changed = dict(original, source_evidence='fixture:repaired-plan-still-missing-recovery')
                if mode == 'direct':
                    self.unavailable(self.attempt()); out = self.direct(findings=[changed], verdict='adverse')
                else:
                    out = self.result(self.attempt(), findings=[changed], verdict='adverse',
                        edit=(lambda result: result.pop('conclusion')) if mode == 'partial-child' else None)
                self.assertEqual(out['outcome'], 'incomplete' if mode == 'partial-child' else 'adverse')
                self.assertEqual(out['finding_collisions'][0]['original_key'],
                                 ('openai' if mode == 'direct' else 'anthropic') + ':F1')
                if mode == 'partial-child':
                    self.assertIsNotNone(out['error'])
                else:
                    self.assertIsNone(out['error'])
                reference = self.finish(accepted=False)
                state = json.loads(Path(self.created['subject_file']).read_text())
                self.assertEqual(len(state['findings']), 2)
                self.assertEqual([row['finding'] for row in state['findings'].values()].count(original), 1)
                self.assertEqual([row['finding'] for row in state['findings'].values()].count(changed), 1)
                self.assertTrue(all(row['status'] == 'open' for row in state['findings'].values()))
                self.assertEqual(state['rounds_used'], 2)
                self.assertEqual(len(state['rounds'][-1]['passes']), 1)
                self.cli('validate', {'reference': reference}, ok=False)
                released = self.cli('release')
                self.job_id += '-replacement'
                self.create(installed=True, begin=False)
                self.assertEqual(released['findings'], state['findings'])
                replaced = json.loads(Path(self.created['subject_file']).read_text())
                self.assertEqual(replaced['rounds_used'], 2)
                self.assertEqual(replaced['findings'], state['findings'])

    def test_same_lineage_panel_finding_collision_retains_both_slots(self):
        second = deepcopy(self.selection_data['review_panel'][0]); second['slot_id'] = 'second'
        self.selection_data['review_panel'].append(second)
        self.create()
        original = self.finding()
        first = self.result(self.attempt(), findings=[original], verdict='adverse')
        changed = dict(original, source_evidence='fixture:second-reviewer-evidence')
        out = self.result(self.attempt('second'), findings=[changed], verdict='adverse')
        self.assertEqual(first['outcome'], 'adverse')
        self.assertEqual(out['outcome'], 'adverse')
        self.assertIsNone(out['error'])
        self.assertEqual(out['finding_collisions'][0]['original_key'], 'anthropic:F1')
        self.finish(accepted=False)
        state = json.loads(Path(self.created['subject_file']).read_text())
        self.assertEqual(len(state['findings']), 2)
        self.assertEqual(len(state['rounds'][-1]['passes']), 2)
        self.assertEqual(state['rounds_used'], 1)
        released = self.cli('release')
        self.job_id += '-replacement'
        self.create(installed=True, begin=False)
        self.assertEqual(released['findings'], state['findings'])
        replaced = json.loads(Path(self.created['subject_file']).read_text())
        self.assertEqual(replaced['rounds_used'], 1)
        self.assertEqual(replaced['findings'], state['findings'])

    def test_same_lineage_approved_notes_can_share_a_finding_id(self):
        second = deepcopy(self.selection_data['review_panel'][0]); second['slot_id'] = 'second'
        self.selection_data['review_panel'].append(second)
        self.create()
        first_note = self.finding('note')
        second_note = dict(first_note, scenario='Step two wording is ambiguous.',
                           source_evidence='fixture:step-two')
        first = self.result(self.attempt(), findings=[first_note])
        second = self.result(self.attempt('second'), findings=[second_note])
        self.assertEqual([first['outcome'], second['outcome']], ['approved', 'approved'])
        self.assertIsNone(second['error'])
        receipt = self.cli('validate', {'reference': self.finish()})
        self.assertEqual(receipt['rounds_used'], 1)
        self.assertEqual(len(receipt['findings']), 2)
        collision = second['finding_collisions'][0]
        self.assertEqual(collision['original_key'], 'anthropic:F1')
        self.assertNotEqual(collision['retained_key'], collision['original_key'])
        self.assertEqual(receipt['findings'][collision['original_key']]['finding'], first_note)
        self.assertEqual(receipt['findings'][collision['retained_key']]['finding'], second_note)
        for key in (collision['original_key'], collision['retained_key']):
            self.assertEqual(receipt['findings'][key]['history'][0], collision)
            self.assertEqual(receipt['findings'][key]['status'], 'open')

    def test_restated_note_keeps_valid_major_repair_response(self):
        for direct in (False, True):
            with self.subTest(direct=direct):
                if direct:
                    self.setUp(); self.add_self()
                self.create()
                major, note = self.finding(), self.finding('note', 'F2')
                if direct:
                    self.unavailable(self.attempt()); self.direct(findings=[major, note], verdict='adverse')
                else:
                    self.result(self.attempt(), findings=[major, note], verdict='adverse')
                self.finish(accepted=False)
                self.plan.write_text(self.plan.read_text() + 'Handle interrupted reads explicitly.\n')
                self.snapshot = self.cli('capture', self.snapshot_data)
                self.cli('begin', {'snapshot': self.snapshot})
                family = 'openai' if direct else 'anthropic'
                responses = [{'finding_key': family + ':F1', 'status': 'fixed', 'evidence': 'fixture:repair-line-3'},
                             {'finding_key': family + ':F2', 'status': 'open', 'evidence': 'fixture:still-minor'}]
                updated = dict(note, source_evidence='fixture:note-now-on-line-four')
                if direct:
                    self.unavailable(self.attempt()); outcome = self.direct(findings=[updated], responses=responses)
                else:
                    outcome = self.result(self.attempt(), findings=[updated],
                        edit=lambda result: result['planning_review'].update(responses=responses))
                self.assertEqual(outcome['outcome'], 'approved')
                self.assertIsNone(outcome['error'])
                receipt = self.cli('validate', {'reference': self.finish()})
                self.assertEqual(receipt['rounds_used'], 2)
                self.assertEqual(receipt['findings'][family + ':F1']['status'], 'fixed')
                self.assertEqual(receipt['findings'][family + ':F1']['clearing']['mode'],
                                 'self-review' if direct else 'cross-lineage')
                self.assertEqual(len(receipt['findings']), 3)
                collision = outcome['finding_collisions'][0]
                self.assertEqual(collision['original_key'], family + ':F2')
                self.assertEqual(receipt['findings'][collision['original_key']]['finding'], note)
                self.assertEqual(receipt['findings'][collision['retained_key']]['finding'], updated)

    def test_replacement_rereview_supersedes_receipt_without_major_findings(self):
        for index, objection in enumerate(('minor', 'contradicted')):
            with self.subTest(objection=objection):
                if index:
                    self.setUp()
                self.create()
                self.result(self.attempt())
                original = self.finish()
                self.cli('validate', {'reference': original})
                self.cli('release')
                self.job_id += '-second-opinion'
                self.create(snapshot=self.snapshot, begin=False)
                self.cli('begin', {'requested_rereview': True})

                def contradict(result):
                    result['status'] = 'needs-followup'
                    result['requirements'][1]['status'] = 'failed'
                    result['planning_review']['coverage'][1]['outcome'] = 'contradicted'

                result = self.result(self.attempt(), verdict='adverse',
                    findings=[self.finding('minor')] if objection == 'minor' else [],
                    edit=contradict if objection == 'contradicted' else None)
                self.assertEqual(result['outcome'], 'adverse')
                self.finish(accepted=False)
                error = self.cli('validate', {'reference': original,
                    'expected_snapshot': self.snapshot['sha256']}, ok=False)
                self.assertIn('later substantive review', error)
                # A subsequent successful assessment issues its own current
                # receipt; it cannot make the superseded receipt current again.
                self.cli('begin', {'requested_rereview': True})
                self.result(self.attempt())
                current = self.cli('validate', {'reference': self.finish()})
                self.assertEqual(current['rounds_used'], 3)
                self.assertIn('later substantive review',
                    self.cli('validate', {'reference': original}, ok=False))

    def test_charged_replacement_supersedes_receipt_before_panel_finishes(self):
        for index, panel in enumerate((False, True)):
            with self.subTest(panel=panel):
                if index:
                    self.setUp()
                if panel:
                    second = deepcopy(self.selection_data['review_panel'][0])
                    second['slot_id'] = 'second'
                    second['target'] = deepcopy(self.selection_data['profiles']['models'][2]['target'])
                    self.selection_data['review_panel'].append(second)
                self.create()
                self.result(self.attempt())
                if panel:
                    self.result(self.attempt('second'))
                reference = self.finish()
                self.cli('release')
                self.job_id += '-pending-review'
                self.create(snapshot=self.snapshot, begin=False)
                self.cli('begin', {'requested_rereview': True})
                # Merely trying another reviewer is not substantive evidence.
                self.cli('validate', {'reference': reference})
                self.result(self.attempt(), verdict='adverse', findings=[self.finding('minor')])
                if panel:
                    self.event(self.attempt('second'), status='running')
                    self.assertIn('pending/uncertain', self.cli('finish', ok=False))
                self.assertIn('later substantive review',
                    self.cli('validate', {'reference': reference}, ok=False))
                self.assertIn('live/uncertain jobs' if panel else 'unfinished content round',
                    self.cli('release', ok=False))

    def test_technical_only_replacement_keeps_accepted_receipt_current(self):
        self.create()
        self.result(self.attempt())
        reference = self.finish()
        original = self.cli('validate', {'reference': reference})
        self.cli('release')
        self.job_id += '-technical-only'
        self.create(snapshot=self.snapshot, begin=False)
        self.cli('begin', {'requested_rereview': True})
        self.unavailable(self.attempt())
        self.cli('release')
        self.assertEqual(self.cli('validate', {'reference': reference}), original)

    def test_owner_scoped_finding_decision_and_limit_increase(self):
        self.create();self.result(self.attempt(), findings=[self.finding()], verdict='adverse');self.finish(accepted=False)
        owner = self.write('owner-answer.txt','Accept this scoped finding risk and permit four content rounds.')
        base = {'source':answer(owner.read_text()),'source_file':str(owner),'logical_output_id':self.snapshot['logical_output_id']}
        self.cli('owner-decision', {'decision':dict(base,kind='finding-decision',finding_key='anthropic:F1')})
        self.cli('owner-decision', {'decision':dict(base,kind='limit-increase',round_limit=4)})
        self.cli('begin', {'requested_rereview':True});self.result(self.attempt());ref=self.finish()
        receipt=self.cli('validate', {'reference':ref});self.assertEqual(receipt['round_limit'],4)
        owner.write_text('Revoked decision.')
        self.cli('validate', {'reference':ref}, ok=False)

    def test_stable_uncertain_request_is_idempotent_and_prepared_request_cannot_duplicate(self):
        self.create();a=self.attempt()
        self.cli('launch', {'slot_id':'review','request_id':'duplicate'}, ok=False)
        for _ in range(3):
            self.cli('host-event', {'task_id':a['task_id'],'event':{'kind':'uncertain','request_id':a['request_id']}})
            recovered=self.cli('launch', {'slot_id':'review','request_id':a['request_id']})
            self.assertEqual(recovered['path'],a['path'])
        self.cli('host-event', {'task_id':a['task_id'],'event':{'kind':'uncertain','request_id':a['request_id']}}, ok=False)
        state=json.loads(Path(self.created['subject_file']).read_text())
        self.assertEqual(state['technical_used'],1)
        self.assertEqual(len(self.box.state_of(self.job_id)['tasks']),1)

    def test_stronger_selected_independence_refuses_same_lineage_and_direct(self):
        self.selection_data['review_panel'][0]['independent']=True
        self.add_self();self.create();self.unavailable(self.attempt())
        self.assertIn('independent',self.direct(ok=False))

    def test_bad_request_and_missing_requirements_are_incomplete_not_accepted(self):
        self.create();a=self.attempt()
        outcome=self.result(a,edit=lambda r:r.update(request_id='wrong-request'))
        self.assertEqual(outcome['outcome'],'incomplete');self.finish(accepted=False)
        self.cli('begin', {'requested_rereview':True})
        out=self.result(self.attempt(),findings=[self.finding()],verdict='adverse',edit=lambda r:r['requirements'].pop())
        self.assertEqual(out['outcome'],'incomplete');self.finish(accepted=False)
        state=json.loads(Path(self.created['subject_file']).read_text())
        self.assertIn('anthropic:F1',state['findings'])

    def test_terminal_failed_handle_retains_real_tool_failure_and_allows_fallback(self):
        self.add_self();self.create();a=self.attempt()
        event=self.event(a,event_extra={'status':'failed','work_state':'result_available'})
        failure={'kind':'technical','tool':'fixture-task-status','call_id':'fixture:failed-read','request_id':a['request_id'],
            'host_task_id':event['host_task_id'],'receipt':{'status':'failed','error':'fixture host executor failed'}}
        self.cli('unavailable', {'task_id':a['task_id'],'failure':failure})
        self.direct();ref=self.finish();receipt=self.cli('validate', {'reference':ref})
        self.assertEqual(receipt['passes'][0]['mode'],'self-review')

    def test_changed_requirements_scope_and_template_cannot_pass(self):
        self.create();self.result(self.attempt());ref=self.finish()
        self.template.write_text('Different template.')
        self.cli('validate', {'reference':ref}, ok=False)
        revised=deepcopy(self.snapshot_data);revised['requirements']['R2']='Weakened recovery.'
        snapshot=self.cli('capture', revised)
        self.assertIn('weaken',self.cli('begin', {'snapshot':snapshot}, ok=False))

    def test_new_job_preserves_findings_attempts_and_round_budget(self):
        self.create();self.result(self.attempt(),findings=[self.finding()],verdict='adverse');self.finish(accepted=False)
        self.cli('release');original_file=self.created['subject_file']
        self.job_id+='-new';self.create(snapshot=self.snapshot)
        state=json.loads(Path(original_file).read_text())
        self.assertEqual(state['rounds_used'],1);self.assertEqual(state['technical_used'],1)
        self.assertIn('anthropic:F1',state['findings'])
        self.result(self.attempt());self.finish(accepted=False)

    def test_technical_only_replacement_does_not_charge_content_or_reset_attempts(self):
        self.create();self.unavailable(self.attempt());self.cli('release')
        self.job_id+='-new';self.create(snapshot=self.snapshot)
        state=json.loads(Path(self.created['subject_file']).read_text())
        self.assertEqual(state['rounds_used'],0);self.assertEqual(state['technical_used'],1)
        self.assertEqual(state['technical_limit'],6)

    def test_forged_privacy_exclusion_does_not_hide_available_ordinary_reviewer(self):
        self.create()
        candidate=self.cli('next', {'slot_id':'review','exclusions':[{'kind':'privacy','reason':'invented'}]})
        self.assertEqual(candidate['target'],self.selection['review_panel'][0]['target'])
        self.cli('next', {'slot_id':'review','sharing':[{'target':candidate['target'],'data_classes':['private-settings'],'source':answer()}]}, ok=False)

    def test_real_unrelated_head_move_is_reported_without_staling_review(self):
        repo=self.inputs/'repository';repo.mkdir()
        self.box.run(['git','init',repo])
        unchanged=repo/'reviewed.py';unchanged.write_text('VALUE = 1\n')
        self.box.run(['git','-C',repo,'add','reviewed.py'])
        self.box.run(['git','-C',repo,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture baseline'])
        self.snapshot_data.update(repository_root=str(repo),evidence_paths=[str(unchanged)],declared_paths=[str(unchanged)])
        self.source=unchanged
        self.create();self.result(self.attempt());ref=self.finish()
        (repo/'unrelated.py').write_text('UNRELATED = 1\n')
        self.box.run(['git','-C',repo,'add','unrelated.py'])
        self.box.run(['git','-C',repo,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','unrelated fixture change'])
        validated=self.cli('validate', {'reference':ref,'report_head':True})
        self.assertTrue(validated['receipt']['accepted']);self.assertTrue(validated['head_observation']['changed'])

    def test_worker_artifact_tampering_invalidates_real_accepted_result(self):
        self.create();a=self.attempt()
        relative=Path('artifacts/tasks')/a['task_id']/'evidence.txt'
        artifact=self.box.jobs/self.job_id/relative;artifact.parent.mkdir(parents=True);artifact.write_text('Fixture cited evidence.')
        raw=artifact.read_bytes()
        edit=lambda r:r['artifacts'].append({'path':relative.as_posix(),'sha256':digest(raw),'bytes':len(raw)})
        self.result(a,edit=edit);ref=self.finish();self.cli('validate', {'reference':ref})
        artifact.write_text('Tampered evidence.')
        self.assertIn('artifact changed',self.cli('validate', {'reference':ref}, ok=False))

    def test_custom_provider_alias_uses_host_driver_lineage(self):
        data=self.selection_data
        old='claude-fixture';custom='custom-review-alias'
        # Host driver identity, not a model display name, establishes canonical lineage.
        provider=next(p for p in data['capabilities']['providers'] if p['providerInstanceId']=='fixture-review')
        provider['driverKind']='claudeAgent';provider['models'][0]['id']=custom
        data['review_panel'][0]['target']['model']=custom
        next(p for p in data['profiles']['models'] if p['target']['model']==old)['target']['model']=custom
        self.create();out=self.result(self.attempt());self.assertEqual(out['mode'],'cross-lineage');self.finish()

    def open_code_family(self, provider_id, family):
        provider = next(p for p in self.selection_data['capabilities']['providers']
                        if p['providerInstanceId'] == provider_id)
        provider.update(driverKind='opencode', runtimeModes=['full-access'])
        provider['models'][0].update(id=family + '-fixture', options=[{
            'id': 'variant', 'type': 'select', 'options': [{'id': 'high'}]}])
        self.selection_data['capabilities']['runtimeMode'] = 'full-access'
        target = {'providerInstanceId': provider_id, 'model': family + '-fixture',
                  'options': {'variant': 'high'}, 'runtimeMode': 'full-access'}
        profile = next(p for p in self.selection_data['profiles']['models']
                       if p['target']['providerInstanceId'] == provider_id)
        profile.update(target=deepcopy(target), lineage=family)
        return target

    def independent_family_review(self, reviewer, author):
        target = self.open_code_family('fixture-review', reviewer)
        self.selection_data['review_panel'][0].update(target=target, independent=True)
        coauthor = self.open_code_family('fixture-spare', author)
        self.snapshot_data['authors'].append({
            'providerInstanceId': coauthor['providerInstanceId'], 'model': coauthor['model'],
            'driver_kind': 'opencode', 'lineage': author})

    def assert_family_acceptance(self, reviewer, author):
        self.independent_family_review(reviewer, author)
        self.create(installed=True)
        candidate = self.cli('next', {'slot_id': 'review'}, installed=True)
        self.assertEqual((candidate['mode'], candidate['lineage']), ('cross-lineage', reviewer))
        attempt = self.attempt()
        self.assertEqual(attempt['target'], self.selection['review_panel'][0]['target'])
        self.assertEqual(attempt['target']['runtimeMode'], 'full-access')
        self.assertEqual(attempt['target']['options'], {'variant': 'high'})
        outcome = self.result(attempt)
        self.assertEqual((outcome['outcome'], outcome['mode']), ('approved', 'cross-lineage'))
        reference = self.finish()
        receipt = self.cli('validate', {'reference': reference}, installed=True)
        self.assertTrue(receipt['accepted'])
        self.assertFalse(receipt['degraded_panel'])
        self.assertEqual((receipt['passes'][0]['mode'], receipt['passes'][0]['lineage']),
                         ('cross-lineage', reviewer))

    def test_deepseek_reviewer_and_qwen_author_reach_pinned_planning_acceptance(self):
        self.assert_family_acceptance('deepseek', 'qwen')

    def test_qwen_reviewer_and_deepseek_author_reach_pinned_planning_acceptance(self):
        self.assert_family_acceptance('qwen', 'deepseek')

    def assert_family_refusal_before_charge(self):
        self.create(installed=True)
        state = self.box.jobs / self.job_id / 'job.json'
        before = state.read_bytes()
        for command, data in [('next', {'slot_id': 'review'}),
                              ('launch', {'slot_id': 'review', 'request_id': self.job_id + '-refused'})]:
            self.assertIn('stronger selected independent slot', self.cli(command, data, ok=False, installed=True))
            self.assertEqual(state.read_bytes(), before)
        job = json.loads(before)
        subject = json.loads(Path(job['planning']['subject_file']).read_text())
        self.assertEqual((job['tasks'], job['planning']['attempts'], subject['rounds_used'],
                          subject['technical_used']), ([], [], 0, 0))

    def test_registered_same_family_author_still_blocks_independent_review_before_charge(self):
        self.independent_family_review('qwen', 'qwen')
        self.assert_family_refusal_before_charge()

    def test_unregistered_model_family_still_blocks_independent_review_before_charge(self):
        self.independent_family_review('unregistered', 'qwen')
        self.assert_family_refusal_before_charge()

    def test_unknown_author_still_blocks_registered_independent_reviewer_before_charge(self):
        self.independent_family_review('deepseek', 'qwen')
        self.snapshot_data['authors'] = [{'unknown': True, 'lineage': 'unknown'}]
        self.assert_family_refusal_before_charge()

    def test_unqualified_main_context_cannot_satisfy_final_judgement(self):
        self.add_self()
        profile=next(p for p in self.selection_data['profiles']['models'] if p['lineage']=='openai')
        profile.update(quality=1,judgement=False)
        self.create();self.unavailable(self.attempt())
        self.assertIn('floor',self.direct(ok=False))

    def test_executing_unpinned_acceptance_code_is_refused(self):
        self.create();self.result(self.attempt());ref=self.finish()
        altered=self.inputs/'altered';shutil.copytree(self.package,altered)
        helper=altered/'shared/planning_review.py';helper.write_text(helper.read_text()+'\n# altered validator bytes\n')
        proc=self.box.run([sys.executable,altered/'shared/planning_review_cli.py','validate','--input',self.box.payload({'reference':ref})],check=False)
        self.assertEqual(proc.returncode,2);self.assertIn('runtime differs',proc.stderr)

    def test_replacement_job_cannot_reuse_a_previous_reviewer_child(self):
        self.create();first=self.attempt();self.result(first,findings=[self.finding()],verdict='adverse');self.finish(accepted=False)
        self.cli('release');self.job_id+='-replacement';self.create(snapshot=self.snapshot)
        second=self.attempt()
        self.event(second,event_extra={'child_thread_id':'child-'+first['request_id']})
        out=self.result(second,observe=False)
        self.assertEqual(out['outcome'],'incomplete');self.assertIn('fresh owned execution',out['error'])
        self.finish(accepted=False)

    def test_unrecorded_author_never_claims_cross_lineage_independence(self):
        self.snapshot_data['authors']=[{'unknown':True,'lineage':'unknown'}]
        self.create();a=self.attempt();self.assertEqual(a['mode'],'non-independent')
        self.result(a);ref=self.finish();receipt=self.cli('validate', {'reference':ref})
        self.assertTrue(receipt['degraded_panel'])

    def test_partial_panel_combined_self_review_preserves_child_and_exact_slots(self):
        second = deepcopy(self.selection_data['review_panel'][0])
        second.update(slot_id='second', target={'providerInstanceId': 'fixture-spare',
                      'model': 'gemini-fixture', 'options': {'effort': 'high'}})
        self.selection_data['review_panel'].append(second)
        self.add_self()
        row = deepcopy(self.selection_data['review_replacements'][0]); row['slot_id'] = 'second'
        self.selection_data['review_replacements'].append(row)
        self.create(installed=True)
        first = self.result(self.attempt())
        self.assertEqual(first['outcome'], 'approved')
        self.direct(ok=False)  # The second primary is still suitable.
        self.unavailable(self.attempt('second'))
        direct = self.direct()
        self.assertEqual(direct['covered_slot_ids'], ['second'])
        self.direct(ok=False)  # One combined pass only.
        receipt = self.cli('validate', {'reference': self.finish()}, installed=True)
        self.assertEqual(receipt['passes'][0], first)
        self.assertEqual(len(receipt['passes']), 2)
        self.assertTrue(receipt['degraded_panel'])
        self.assertEqual(receipt['slot_modes'], {'review': 'cross-lineage', 'second': 'self-review'})
        for slots in (['second', 'second'], ['review'], ['arbitrary']):
            bad = deepcopy(receipt['passes']); bad[1]['covered_slot_ids'] = slots
            with self.assertRaises(ValueError):
                planning._panel_coverage(bad, {'review', 'second'})
        self.assertNotEqual(set(planning._panel_coverage([first], {'review', 'second'})), {'review', 'second'})

    def test_major_repair_clearing_mode_and_lineage_survive_self_fallback(self):
        self.add_self(); self.create()
        self.result(self.attempt(), findings=[self.finding()], verdict='adverse')
        self.finish(accepted=False)
        self.plan.write_text(self.plan.read_text() + 'Handle interrupted reads explicitly.\n')
        self.snapshot = self.cli('capture', self.snapshot_data)
        self.cli('begin', {'snapshot': self.snapshot})
        self.unavailable(self.attempt())
        self.direct(responses=[{'finding_key': 'anthropic:F1', 'status': 'fixed',
                                'evidence': 'fixture:interrupted-read repair inspected'}])
        receipt = self.cli('validate', {'reference': self.finish()}, installed=True)
        row = receipt['findings']['anthropic:F1']
        self.assertEqual(row['lineage'], 'anthropic')
        self.assertEqual(row['clearing']['mode'], 'self-review')
        self.assertEqual(row['clearing']['lineage'], 'openai')
        self.assertEqual(row['clearing']['disposition'], 'fixed-by-self-review')
        self.assertEqual(receipt['round_history'][0]['passes'][0]['outcome'], 'adverse')

    def test_public_catalog_planning_command_routes_without_nested_selection(self):
        proc=self.box.t3('planning-review','capture','--input',self.box.payload(self.snapshot_data))
        self.assertEqual(json.loads(proc.stdout)['output_type'],'implementation-plan')

    def test_relocated_installed_cli_uses_manifest_pins(self):
        relocated=self.inputs/'relocated';shutil.copytree(self.package,relocated)
        proc=self.box.run([sys.executable,relocated/'shared/planning_review_cli.py','capture','--input',self.box.payload(self.snapshot_data)])
        self.assertEqual(json.loads(proc.stdout)['logical_output_id'],planning.logical_output_id('fixture:request:'+self.job_id,'fixture-plan'))


if __name__ == '__main__':
    unittest.main()
