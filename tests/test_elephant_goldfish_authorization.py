"""Stage 4 elephant-goldfish coordinator adapter: routing, boundaries and synthetic jobs.

Every job here runs through an isolated installed package: the pinned
`shared/job_cli.py`, `shared/job_acceptance_cli.py`, `scripts/thinking_state.py`,
`scripts/render_handoff.py` and `scripts/validate_document.py`. Worker results are
synthetic JSON; no model is called and GitHub is never touched."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.store import canonical  # noqa: E402
from tests.elephant_goldfish_job_fixtures import (  # noqa: E402
    PLUGIN, OPERATIONS, WORKERS, sha, words, section, ElephantDocumentJobFixture,
)


class ElephantAuthorizationJobTests(ElephantDocumentJobFixture):
    def test_cold_reader_refuses_extra_context_files_in_worker_and_review_slots(self):
        from tests.adopter_plan_review_fixtures import ensure_legacy_elephant_design
        document = self.document()
        extra = self.base / 'prior-review-findings.txt'
        extra.write_text('Synthetic prior findings must never reach the cold reader.\n')
        for role in (None, 'review'):
            with self.subTest(role=role):
                job_id = 'cold-extra-' + (role or 'worker')
                job = self.elephant_job(job_id, document, cold_role=role, factual=False)
                job['tasks'][0]['context_files'] = [{'path': str(extra), 'sha256': sha(extra.read_bytes())}]
                self.create(job)
                ensure_legacy_elephant_design(self, job_id)
                refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                          {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
                self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                self.assertIn('cold reader must read only its supplied document', refused.stderr)

    def test_copy_recorded_draft_kept_then_in_place_record_retains_its_author(self):
        self._assert_later_record_keeps_sidecar_authors(False)


    def test_recreated_draft_after_move_then_in_place_record_retains_its_author(self):
        self._assert_later_record_keeps_sidecar_authors(True)


    def test_plan_revision_cannot_remove_retained_authors_after_reimport(self):
        document = self.document()
        job_id, caller = 'plan-revision-retained-authors', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document, factual=False))
        state = self.job_state(job_id)
        state['tasks'][0]['document_authors'].append({'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol',
                                                       'parentThreadId': 'synthetic-retained-author',
                                                       'lineage': 'openai'})
        (self.state / job_id / 'job.json').write_text(json.dumps(state))
        plan = {key: copy.deepcopy(state[key]) for key in
                ('requirements', 'dependencies', 'stages', 'tasks', 'constraints', 'authorization', 'policy')}
        current_hash = sha(document.read_bytes())
        sidecar_path = document.parent / 'document-authors.json'
        sidecar = json.loads(sidecar_path.read_text())
        sidecar[current_hash]['authors'] = [row for row in sidecar[current_hash]['authors']
                                            if row['lineage'] == 'google']
        sidecar_path.write_text(json.dumps(sidecar))
        revised = self.run_helper('job_cli.py', 'plan-revision', job_id,
                                  {'caller': caller, 'revision': {'id': 'retain-authors'}, 'new_plan': plan})
        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        authors = self.job_state(job_id)['tasks'][0]['document_authors']
        self.assertEqual({row['lineage'] for row in authors}, {'google', 'openai'})


    def test_author_independence_policy_cannot_be_disabled_with_owner_decision(self):
        document = self.document()
        job_id, caller = 'author-policy-immutable', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document, factual=False))
        state = self.job_state(job_id)
        plan = {key: copy.deepcopy(state[key]) for key in
                ('requirements', 'dependencies', 'stages', 'tasks', 'constraints', 'authorization', 'policy')}
        plan['policy']['author_independence'] = False
        source = self.base / 'owner-policy.txt'; source.write_text('Owner approves a policy change.')
        decision = {'id': 'owner-policy', 'scope': 'plan:disable-author-policy', 'requirement_ids': [],
                    'quote': 'Owner approves a policy change.', 'source': str(source),
                    'source_sha256': sha(source.read_bytes())}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))
        refused = self.run_helper('job_cli.py', 'plan-revision', job_id,
                                  {'caller': caller,
                                   'revision': {'id': 'disable-author-policy', 'owner_decision_id': 'owner-policy'},
                                   'new_plan': plan})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('author independence policy is immutable', refused.stderr)


    def test_check_direct_factual_stage_requires_executor_and_stage_waiver_for_known_authors(self):
        from shared.document_authors import stage_waiver_binding
        unrecorded_dir = self.base / 'docs' / 'unrecorded'
        unrecorded_dir.mkdir(parents=True)
        unrecorded = unrecorded_dir / 'elephant.md'
        unrecorded.write_text('# Unrecorded check document\n')
        unknown_id, unknown_caller = 'check-direct-stage-unrecorded', self.caller('elephant-goldfish/check')
        unknown_stage = {'id': 'check', 'depends_on': [], 'requirements': ['R-CHECK'], 'status': 'pending',
                         'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'check-direct-unknown',
                         'validator_contract': self.contract(unrecorded, 'factual')}
        self.create(self.base_job(unknown_id, 'elephant-goldfish/check',
                                  {'R-CHECK': 'factual observations match'}, [unknown_stage], []))
        unknown_observation = self.publish(unknown_id, unknown_caller, 'check', self.factual_observation(unrecorded))
        unknown_argv = self.doc_argv(unrecorded.parent.parent, unrecorded.parent.name, 'factual', unknown_observation)
        unknown_result = self.accept(unknown_id, unknown_caller, 'check', unknown_argv,
                                     unknown_observation, 'check-direct-unknown')
        self.assertEqual(unknown_result.returncode, 0, unknown_result.stdout + unknown_result.stderr)
        self.assertIn('author unrecorded', unknown_result.stdout)

        document = self.document()
        job_id, caller = 'check-direct-stage-waiver', self.caller('elephant-goldfish/check')
        stage = {'id': 'check', 'depends_on': [], 'requirements': ['R-CHECK'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'check-direct-r1',
                 'validator_contract': self.contract(document, 'factual')}
        self.create(self.base_job(job_id, 'elephant-goldfish/check',
                                  {'R-CHECK': 'factual observations match'}, [stage], []))
        self.assertEqual({row['lineage'] for row in self.job_state(job_id)['stages'][0]['document_authors']}, {'google'})
        observation = self.publish(job_id, caller, 'check', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
        refused = self.accept(job_id, caller, 'check', argv, observation, 'check-direct-r1')
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('current stage-scoped lineage waiver', refused.stderr)

        capabilities = json.loads(self.capabilities.read_text())
        capabilities.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                            parentThreadId='synthetic-direct-checker')
        caps_path = self.base / 'check-direct-capabilities.json'; caps_path.write_text(json.dumps(capabilities))
        self.choose_direct_work(job_id, caller, capabilities, 'check')
        executed = self.run_helper('job_cli.py', 'direct-execution', job_id,
                                   {'caller': caller, 'stage_id': 'check'}, capabilities=caps_path)
        self.ok(executed)
        state = self.job_state(job_id); current = state['stages'][0]
        executor = current['direct_execution_history'][-1]['identity']
        binding = stage_waiver_binding(current, current['document_authors'], sha(document.read_bytes()), executor)
        source = self.base / 'owner-check-direct-waiver.txt'; source.write_text('Owner approves direct check lineage.')
        decision = {'id': 'owner-check-direct-waiver', 'scope': 'lineage-waiver:stage:check',
                    'requirement_ids': [], 'binding': binding, 'source': str(source),
                    'source_sha256': sha(source.read_bytes()), 'quote': 'Owner approves direct check lineage.'}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))
        observation = self.publish(job_id, caller, 'check', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
        accepted = self.accept(job_id, caller, 'check', argv, observation, 'check-direct-r1')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


    def test_zero_slot_direct_factual_stage_requires_waiver_and_known_authors(self):
        for unknown in (False, True):
            document = self.document()
            current_hash = sha(document.read_bytes())
            if unknown:
                sidecar = document.parent / 'document-authors.json'
                records = json.loads(sidecar.read_text())
                records.pop(current_hash)
                sidecar.write_text(json.dumps(records))
            job_id, workflow = 'direct-factual-unknown' if unknown else 'direct-factual-no-waiver', self.WORKFLOW
            stage = {'id': 'factual', 'depends_on': [], 'requirements': ['R-FACT'], 'status': 'pending',
                     'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'direct-r1',
                     'validator_contract': self.contract(document, 'factual')}
            job = self.base_job(job_id, workflow, {'R-FACT': 'claims are confirmed'}, [stage], [])
            self.create(job)
            if not unknown:
                created_state = self.job_state(job_id)
                self.assertEqual(created_state['tasks'], [])
                self.assertEqual(created_state['policy']['author_independence'], True)
                self.assertEqual({row['lineage'] for row in created_state['stages'][0]['document_authors']}, {'google'})
            caller = self.caller(workflow)
            observation = self.publish(job_id, caller, 'factual', self.factual_observation(document))
            if not unknown:
                after_observation = self.job_state(job_id)
                self.assertEqual(after_observation['stages'][0]['document_authors'], created_state['stages'][0]['document_authors'])
                self.assertEqual({row['lineage'] for row in after_observation['stages'][0]['document_authors']}, {'google'})
            argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
            before_execution = self.accept(job_id, caller, 'factual', argv, observation, 'direct-r1')
            self.assertEqual(before_execution.returncode, 2, before_execution.stdout + before_execution.stderr)
            self.assertTrue(any(message in before_execution.stderr for message in
                                ('current stage-scoped lineage waiver', 'author unrecorded')))
            caps_path = self.base / f'{job_id}-capabilities.json'
            caps_path.write_text(self.capabilities.read_text())
            recorded = self.run_helper('job_cli.py', 'direct-execution', job_id,
                                       {'caller': caller, 'stage_id': 'factual'}, capabilities=caps_path)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            observation = self.publish(job_id, caller, 'factual', self.factual_observation(document))
            argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
            refused = self.accept(job_id, caller, 'factual', argv, observation, 'direct-r1')
            self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
            if unknown:
                self.assertIn('author unrecorded', refused.stderr)
            else:
                self.assertIn('current stage-scoped lineage waiver', refused.stderr)


    def test_task_lineage_waiver_flows_through_prepare_and_acceptance(self):
        from shared.document_authors import waiver_binding
        document = self.document()
        job_id, caller = 'task-waiver-e2e', self.caller(self.WORKFLOW)
        job = self.elephant_job(job_id, document, factual=False)
        slot = job['tasks'][0]
        slot['target'] = {'providerInstanceId': 'antigravity',
                          'model': 'gemini-3.8-flash-high', 'lineage': 'google'}
        self.create(job)
        state = self.job_state(job_id)
        task = state['tasks'][0]
        self.assertEqual({a.get('lineage') for a in task['document_authors']}, {'google'})

        def add_waiver(label, target_job=job_id):
            current = self.job_state(target_job)['tasks'][0]
            source = self.base / f'owner-task-waiver-{label}.txt'
            source.write_text('Owner approves same-lineage document review ' + label)
            decision = {'id': 'owner-task-waiver-' + label,
                        'scope': 'lineage-waiver:task:' + current['task_id'],
                        'requirement_ids': [], 'binding': waiver_binding(current),
                        'source': str(source), 'source_sha256': sha(source.read_bytes()),
                        'quote': 'Owner approves same-lineage document review ' + label}
            self.ok(self.run_helper('job_cli.py', 'decision', target_job,
                                    {'caller': caller, 'decision': decision}))

        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': caller, 'task_id': task['task_id']})
        self.assertEqual(refused.returncode, 2)
        self.assertIn('differ from every document author', refused.stderr)
        add_waiver('initial')
        self.dispatch(job_id, caller, task['task_id'])
        observation = self.publish(job_id, caller, 'cold-read', self.cold_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'cold-read', observation)
        accepted = self.accept(job_id, caller, 'cold-read', argv, observation)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

        baseline = self.job_state(job_id)
        stale_mutations = (
            ('target', lambda task: task.update(target={'providerInstanceId': 'antigravity-resumed',
                'model': 'gemini-3.8-flash-high', 'lineage': 'google'})),
            ('authors', lambda task: task['document_authors'].append({'providerInstanceId': 'other-google',
                'model': 'gemini-3.8-pro', 'lineage': 'google', 'parentThreadId': 'synthetic-other-author'})),
            ('contract', lambda task: task.update(max_followups=1)),
            ('document', lambda task: task['document'].update(sha256='f' * 64)),
        )
        for label, mutate in stale_mutations:
            changed = copy.deepcopy(baseline)
            mutate(changed['tasks'][0])
            (self.state / job_id / 'job.json').write_text(json.dumps(changed))
            stale = self.accept(job_id, caller, 'cold-read', argv, observation)
            self.assertEqual(stale.returncode, 2, f'{label}: {stale.stdout}{stale.stderr}')
            self.assertIn('differ from every document author', stale.stderr, label)
        (self.state / job_id / 'job.json').write_text(json.dumps(baseline))

        # A separate first-pass job proves the waiver cannot excuse a failed worker
        # requirement before the document validator runs.
        failed_job = 'task-waiver-failed-requirement'
        failed_plan = self.elephant_job(failed_job, document, factual=False)
        failed_plan['tasks'][0]['target'] = {'providerInstanceId': 'antigravity',
            'model': 'gemini-3.8-flash-high', 'lineage': 'google'}
        self.create(failed_plan)
        add_waiver('failed-requirement', failed_job)
        self.dispatch(failed_job, caller, 'c0', status='ready-for-acceptance', requirement='failed')
        failed_observation = self.publish(failed_job, caller, 'cold-read', self.cold_observation(document))
        failed_argv = self.doc_argv(document.parent.parent, document.parent.name, 'cold-read', failed_observation)
        rejected = self.accept(failed_job, caller, 'cold-read', failed_argv, failed_observation)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('current ready result', rejected.stdout + rejected.stderr)


    def test_acceptance_lineage_refusal_uses_task_observation_evidence(self):
        document = self.document()
        job_id, caller = 'observed-author-refusal', self.caller(self.WORKFLOW)
        job = self.elephant_job(job_id, document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'grok', 'model': 'grok-3', 'lineage': 'xai'}
        self.create(job)
        self.dispatch(job_id, caller, 'c0')
        state = self.job_state(job_id)
        handle = state['tasks'][0]['handles'][0]
        self.assertEqual(handle['observed_identity']['status'], 'verified')
        # Authorship changes after the host observation, so acceptance must re-check
        # the actual recorded execution against the current document authors.
        state['tasks'][0]['document_authors'].append({'providerInstanceId': 'grok', 'model': 'grok-3',
            'lineage': 'xai', 'parentThreadId': 'synthetic-late-author'})
        (self.state / job_id / 'job.json').write_text(json.dumps(state))
        observation = self.publish(job_id, caller, 'cold-read', self.cold_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'cold-read', observation)
        refused = self.accept(job_id, caller, 'cold-read', argv, observation)
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_create_refuses_factual_document_mismatch(self):
        document = self.document()
        other = document.parent / 'other.md'
        other.write_text('unrelated document\n')
        job = self.elephant_job('document-mismatch', document)
        job['tasks'] = [t for t in job['tasks'] if t['task_id'] == 'f0']
        job['stages'] = [s for s in job['stages'] if s['id'] == 'factual']
        job['tasks'][0]['document'] = {'path': str(other), 'sha256': sha(other.read_bytes())}
        caller = self.caller(self.WORKFLOW)
        created = self.run_helper('job_cli.py', 'create', 'document-mismatch', job, prefix=self.prefix,
                                  agents_root=self.agents, config=self.base / 'config' / 'workers.json')
        self.assertEqual(created.returncode, 2, created.stdout + created.stderr)
        self.assertIn('must match the stage validated document', created.stderr)


    def test_refused_document_revision_leaves_new_hash_authors_untouched(self):
        document = self.document()
        caller = self.caller(self.WORKFLOW)
        self.create(self.elephant_job('premature-revision', document))
        document.write_text(document.read_text() + '\nA changed paragraph.\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='claudeAgent', inheritedModel='claude-opus-5-5',
                    parentThreadId='synthetic-repair-author')
        caps_path = self.base / 'repair-author-capabilities.json'
        caps_path.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(document), '--capabilities', str(caps_path)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        new_hash = sha(document.read_bytes())
        sidecar = document.parent / 'document-authors.json'
        before = json.loads(sidecar.read_text())[new_hash]
        refused = self.run_helper('job_cli.py', 'document-revision', 'premature-revision', {
            'caller': caller, 'task_id': 'c0', 'reason': 'premature',
            'document': {'path': str(document), 'sha256': new_hash}}, capabilities=caps_path)
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertEqual(json.loads(sidecar.read_text())[new_hash], before)


    def test_recording_an_edited_document_preserves_previous_authors_and_blocks_them(self):
        document = self.document()
        old_hash = sha(document.read_bytes())
        original = json.loads((document.parent / 'document-authors.json').read_text())
        self.assertEqual({row['lineage'] for row in original[old_hash]['authors']}, {'google'})
        document.write_bytes(document.read_bytes() + b'\nEdited by another coordinator.\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-editor-b')
        caps_path = self.base / 'editor-b-capabilities.json'
        caps_path.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(document), '--capabilities', str(caps_path)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        new_hash = sha(document.read_bytes())
        authors = json.loads((document.parent / 'document-authors.json').read_text())[new_hash]['authors']
        self.assertEqual({row['lineage'] for row in authors}, {'google', 'openai'})
        job = self.elephant_job('edited-document-author-union', document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'antigravity',
                                     'model': 'gemini-3.8-flash-high', 'lineage': 'google'}
        self.create(job)
        refused = self.run_helper('job_cli.py', 'prepare', job['job_id'],
                                  {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_plan_revision_reimports_authors_for_new_slots(self):
        document = self.document()
        job_id, caller = 'plan-revision-author-import', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document, factual=False))
        state = self.job_state(job_id)
        plan = {key: copy.deepcopy(state[key]) for key in
                ('requirements', 'dependencies', 'stages', 'tasks', 'constraints', 'authorization', 'policy')}
        slot = copy.deepcopy(plan['tasks'][0])
        slot.update(task_id='c1', logical_slot_id='cold-reader-2', request_id='req-c1',
                    target={'providerInstanceId': 'antigravity', 'model': 'gemini-3.8-flash-high', 'lineage': 'google'},
                    document_authors=[{'providerInstanceId': 'xai', 'model': 'grok-3',
                                       'parentThreadId': 'synthetic-forged-author', 'lineage': 'xai'}])
        plan['tasks'].append(slot)
        revision_id = 'add-second-cold-reader'
        source = self.base / 'owner-add-cold-reader.txt'; source.write_text('Owner approves a second cold reader.')
        decision = {'id': 'owner-add-cold-reader', 'scope': 'plan:' + revision_id, 'requirement_ids': [],
                    'quote': 'Owner approves a second cold reader.', 'source': str(source),
                    'source_sha256': sha(source.read_bytes())}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))
        self.ok(self.run_helper('job_cli.py', 'plan-revision', job_id,
                                {'caller': caller, 'revision': {'id': revision_id,
                                 'owner_decision_id': decision['id']}, 'new_plan': plan}))
        imported = next(task for task in self.job_state(job_id)['tasks'] if task['task_id'] == 'c1')
        self.assertEqual({author['lineage'] for author in imported['document_authors']}, {'google'})
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': caller, 'task_id': 'c1'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)



if __name__ == '__main__':
    unittest.main()
