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


class ElephantAuthorJobTests(ElephantDocumentJobFixture):
    def test_policy_enforces_author_lineage_when_factual_slot_flag_is_missing(self):
        document = self.document()
        job = self.elephant_job('policy-author-flag', document)
        job['tasks'] = [t for t in job['tasks'] if t['task_id'] == 'f0']
        job['stages'] = [s for s in job['stages'] if s['id'] == 'factual']
        job['tasks'][0]['target'] = {'providerInstanceId': 'antigravity',
                                     'model': 'gemini-3.8-flash-high', 'lineage': 'google'}
        caller = self.caller(self.WORKFLOW)
        self.create(job)
        state = self.job_state('policy-author-flag')
        state['tasks'][0].pop('independent_of_author', None)
        (self.state / 'policy-author-flag' / 'job.json').write_text(json.dumps(state))
        refused = self.run_helper('job_cli.py', 'prepare', 'policy-author-flag',
                                  {'caller': caller, 'task_id': 'f0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_cli_prepare_rejects_unknown_and_noncanonical_author_lineage(self):
        document = self.document()
        for label in ('unknown', 'sonnet'):
            job_id = 'noncanonical-author-lineage-' + label
            job = self.elephant_job(job_id, document, factual=False)
            job['tasks'][0]['target'] = {'providerInstanceId': 'opencode', 'model': label,
                                         'lineage': label}
            self.create(job)
            refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                      {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
            self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
            self.assertIn('unknown or non-canonical', refused.stderr)


    def test_cli_prepare_rejects_lineage_label_that_disagrees_with_target_model(self):
        document = self.document()
        job_id = 'mislabeled-author-lineage'
        job = self.elephant_job(job_id, document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'antigravity',
                                     'model': 'gemini-3.8-flash-high', 'lineage': 'openai'}
        self.create(job)
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('disagrees with provider and model', refused.stderr)


    def test_check_workflow_imports_authors_and_rejects_same_lineage_worker(self):
        document = self.document()
        task = {'task_id': 'check-worker', 'stage_id': 'check', 'logical_slot_id': 'factual',
                'request_id': 'check-worker-request', 'worker_id': 'elephant-goldfish/factual-checker',
                'dependency_key': 'eg', 'write_scope': {'mode': 'coordinator-only'},
                'independent_of_author': True,
                'target': {'providerInstanceId': 'antigravity', 'model': 'gemini-3.8-flash-high', 'lineage': 'google'}}
        stage = {'id': 'check', 'depends_on': [], 'requirements': ['R-CHECK'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'check-r1',
                 'validator_contract': self.contract(document, 'factual')}
        job = self.base_job('check-known-author-same-lineage', 'elephant-goldfish/check',
                            {'R-CHECK': 'factual observations match'}, [stage], [task])
        self.create(job)
        factual = self.job_state(job['job_id'])['tasks'][0]
        self.assertEqual({author['lineage'] for author in factual['document_authors']}, {'google'})
        self.assertTrue(factual['independent_of_author'])
        refused = self.run_helper('job_cli.py', 'prepare', job['job_id'],
                                  {'caller': self.caller('elephant-goldfish/check'), 'task_id': 'check-worker'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_check_workflow_rejects_unreported_worker_at_acceptance(self):
        document = self.document()
        caller = self.caller('elephant-goldfish/check')
        task = {'task_id': 'check-worker', 'stage_id': 'check', 'logical_slot_id': 'factual',
                'request_id': 'check-worker-request', 'worker_id': 'elephant-goldfish/factual-checker',
                'dependency_key': 'eg', 'write_scope': {'mode': 'coordinator-only'},
                'independent_of_author': True,
                'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}}
        stage = {'id': 'check', 'depends_on': [], 'requirements': ['R-CHECK'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'check-r1',
                 'validator_contract': self.contract(document, 'factual')}
        job = self.base_job('check-unreported-worker', 'elephant-goldfish/check',
                            {'R-CHECK': 'factual observations match'}, [stage], [task])
        self.create(job)
        self.dispatch(job['job_id'], caller, 'check-worker', report_identity=False)
        observation = self.publish(job['job_id'], caller, 'check', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
        refused = self.accept(job['job_id'], caller, 'check', argv, observation, 'check-r1')
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('unreported or mismatched', refused.stderr)


    def test_check_job_extra_unknown_subject_keeps_author_enforcement(self):
        document = self.document()
        extra = document.parent / 'unrecorded-notes.md'
        extra.write_text('Unrecorded extra subject.\n')
        task = {'task_id': 'check-worker', 'stage_id': 'check', 'logical_slot_id': 'factual',
                'request_id': 'check-extra-subject', 'worker_id': 'elephant-goldfish/factual-checker',
                'dependency_key': 'eg', 'write_scope': {'mode': 'coordinator-only'},
                'reviewed_documents': [{'path': str(extra), 'sha256': sha(extra.read_bytes())}],
                'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}}
        stage = {'id': 'check', 'depends_on': [], 'requirements': ['R-CHECK'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'check-r-extra',
                 'validator_contract': self.contract(document, 'factual')}
        job = self.base_job('check-extra-unknown-subject', 'elephant-goldfish/check',
                            {'R-CHECK': 'factual observations match'}, [stage], [task])
        self.create(job)
        factual = self.job_state(job['job_id'])['tasks'][0]
        self.assertTrue(factual['independent_of_author'])
        self.assertTrue(any(row.get('unknown') for row in factual['document_authors']))
        refused = self.run_helper('job_cli.py', 'prepare', job['job_id'],
                                  {'caller': self.caller('elephant-goldfish/check'), 'task_id': 'check-worker'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('author unrecorded', refused.stderr)


    def test_check_job_slot_copy_must_match_validated_document(self):
        document = self.document()
        changed_copy = document.parent / 'copy.md'
        changed_copy.write_text(document.read_text() + 'one byte extra\n')
        task = {'task_id': 'check-worker', 'stage_id': 'check', 'logical_slot_id': 'factual',
                'request_id': 'check-copy', 'worker_id': 'elephant-goldfish/factual-checker',
                'dependency_key': 'eg', 'write_scope': {'mode': 'coordinator-only'},
                'document': {'path': str(changed_copy), 'sha256': sha(changed_copy.read_bytes())}}
        stage = {'id': 'check', 'depends_on': [], 'requirements': ['R-CHECK'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'check-r-copy',
                 'validator_contract': self.contract(document, 'factual')}
        job = self.base_job('check-copy-subject', 'elephant-goldfish/check',
                            {'R-CHECK': 'factual observations match'}, [stage], [task])
        refused = self.run_helper('job_cli.py', 'create', job['job_id'], job, prefix=self.prefix,
                                  agents_root=self.agents, config=self.base / 'config' / 'workers.json')
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('must match the stage validated document', refused.stderr)


    def test_zero_slot_direct_cold_read_cannot_use_coordinator_observation(self):
        document = self.document()
        job_id = 'direct-cold-read-no-fallback'
        job = self.elephant_job(job_id, document)
        job['tasks'] = [task for task in job['tasks'] if task['task_id'] == 'f0']
        cold = next(stage for stage in job['stages'] if stage['id'] == 'cold-read')
        cold.update(execution_mode='direct', revision='cold-direct-r1')
        caller = self.caller(self.WORKFLOW)
        self.create(job)
        self.accept_factual(job_id, caller, document)
        observation = self.publish(job_id, caller, 'cold-read', self.cold_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'cold-read', observation)
        refused = self.accept(job_id, caller, 'cold-read', argv, observation, 'cold-direct-r1')
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('cold-read cannot fall back to the coordinator', refused.stderr)


    def test_plan_revision_rejects_added_slot_for_different_document(self):
        document = self.document()
        other_dir = self.base / 'docs' / 'other'
        other_dir.mkdir(parents=True)
        other = other_dir / 'elephant.md'
        other.write_text('# Other document\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-other-doc-author')
        caps_path = self.base / 'other-doc-capabilities.json'; caps_path.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'), str(other),
                                   '--capabilities', str(caps_path)], capture_output=True, text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        job_id, caller = 'plan-revision-other-document', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document, factual=False))
        state = self.job_state(job_id)
        plan = {key: copy.deepcopy(state[key]) for key in
                ('requirements', 'dependencies', 'stages', 'tasks', 'constraints', 'authorization', 'policy')}
        slot = copy.deepcopy(plan['tasks'][0])
        slot.update(task_id='c1', logical_slot_id='cold-read-2', request_id='req-c1',
                    target={'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'},
                    document={'path': str(other), 'sha256': sha(other.read_bytes())})
        plan['tasks'].append(slot)
        source = self.base / 'owner-add-other-doc.txt'; source.write_text('Owner approves another reader.')
        decision = {'id': 'owner-add-other-doc', 'scope': 'plan:add-other-doc', 'requirement_ids': [],
                    'quote': 'Owner approves another reader.', 'source': str(source),
                    'source_sha256': sha(source.read_bytes())}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))
        refused = self.run_helper('job_cli.py', 'plan-revision', job_id,
                                  {'caller': caller, 'revision': {'id': 'add-other-doc',
                                   'owner_decision_id': decision['id']}, 'new_plan': plan})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('must match the stage validated document', refused.stderr)


    def test_plan_revision_reimports_authors_when_existing_slot_and_stage_document_change(self):
        original = self.document()
        other_dir = self.base / 'docs' / 'other'
        other_dir.mkdir(parents=True)
        other = other_dir / 'elephant.md'
        other.write_text('# Other document\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-openai-document-author')
        caps_path = self.base / 'other-doc-capabilities.json'; caps_path.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'), str(other),
                                   '--capabilities', str(caps_path)], capture_output=True, text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        job_id, caller = 'plan-revision-retarget-document', self.caller(self.WORKFLOW)
        job = self.elephant_job(job_id, other, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}
        self.create(job)
        state = self.job_state(job_id)
        plan = {key: copy.deepcopy(state[key]) for key in
                ('requirements', 'dependencies', 'stages', 'tasks', 'constraints', 'authorization', 'policy')}
        subject = {'path': str(original), 'sha256': sha(original.read_bytes())}
        plan['tasks'][0]['document'] = subject
        plan['tasks'][0]['target'] = {'providerInstanceId': 'antigravity',
                                      'model': 'gemini-3.8-flash-high', 'lineage': 'google'}
        plan['stages'][0]['validator_contract'] = self.contract(original, 'cold-read')
        source = self.base / 'owner-retarget-doc.txt'; source.write_text('Owner approves retargeting the reader.')
        decision = {'id': 'owner-retarget-doc', 'scope': 'plan:retarget-doc', 'requirement_ids': [],
                    'quote': 'Owner approves retargeting the reader.', 'source': str(source),
                    'source_sha256': sha(source.read_bytes())}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))
        self.ok(self.run_helper('job_cli.py', 'plan-revision', job_id,
                                {'caller': caller, 'revision': {'id': 'retarget-doc',
                                 'owner_decision_id': decision['id']}, 'new_plan': plan}))
        current = self.job_state(job_id)['tasks'][0]
        self.assertEqual({row['lineage'] for row in current['document_authors']}, {'google', 'openai'})
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': caller, 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_recorded_copy_edit_moved_into_place_keeps_destination_authors(self):
        document = self.document()
        old_hash = sha(document.read_bytes())
        draft = document.parent / 'draft.md'
        draft.write_bytes(document.read_bytes() + b'Edited at a temporary path.\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-moved-copy-editor')
        caps_path = self.base / 'move-editor-capabilities.json'; caps_path.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'), str(draft),
                                   '--capabilities', str(caps_path)], capture_output=True, text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        os.replace(draft, document)
        new_hash = sha(document.read_bytes())
        job_id = 'moved-copy-author-inheritance'
        job = self.elephant_job(job_id, document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'antigravity',
                                     'model': 'gemini-3.8-flash-high', 'lineage': 'google'}
        self.create(job)
        authors = self.job_state(job_id)['tasks'][0]['document_authors']
        self.assertEqual({row['lineage'] for row in authors}, {'google', 'openai'})
        self.assertIn(old_hash, json.loads((document.parent / 'document-authors.json').read_text()))
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_rerecord_after_move_keeps_moved_copy_editor_and_refuses_that_lineage(self):
        document = self.document()
        draft = document.parent / 'draft.md'
        draft.write_bytes(document.read_bytes() + b'B edited this copy.\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-moved-copy-editor-rerecord')
        editor_caps = self.base / 'editor-caps.json'; editor_caps.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(draft), '--capabilities', str(editor_caps)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        os.replace(draft, document)

        # A records the moved bytes again. The current hash and destination path
        # hash must both contribute their authors to the replacement record.
        original_caps = json.loads(self.capabilities.read_text())
        original_caps.update(inheritedProviderInstanceId='antigravity', inheritedModel='gemini-3.8-flash-high')
        original_caps['parentThreadId'] = 'synthetic-original-author-rerecord'
        original_path = self.base / 'original-caps.json'; original_path.write_text(json.dumps(original_caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(document), '--capabilities', str(original_path)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        current_hash = sha(document.read_bytes())
        sidecar = json.loads((document.parent / 'document-authors.json').read_text())
        self.assertEqual({row['lineage'] for row in sidecar[current_hash]['authors']}, {'google', 'openai'})

        job_id = 'rerecorded-moved-copy-author-union'
        job = self.elephant_job(job_id, document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}
        self.create(job)
        self.assertEqual({row['lineage'] for row in self.job_state(job_id)['tasks'][0]['document_authors']},
                         {'google', 'openai'})
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)


    def test_third_author_record_after_move_keeps_moved_copy_editor(self):
        document = self.document()
        draft = document.parent / 'draft.md'
        draft.write_bytes(document.read_bytes() + b'B edited this copy.\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-p1a-editor')
        editor_caps = self.base / 'p1a-editor-caps.json'; editor_caps.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(draft), '--capabilities', str(editor_caps)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        os.replace(draft, document)

        document.write_bytes(document.read_bytes() + b'C fixed a typo in place.\n')
        caps.update(inheritedProviderInstanceId='claudeAgent', inheritedModel='claude-opus-5-5',
                    parentThreadId='synthetic-p1a-third-author')
        third_caps = self.base / 'p1a-third-caps.json'; third_caps.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(document), '--capabilities', str(third_caps)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        current_hash = sha(document.read_bytes())
        sidecar = json.loads((document.parent / 'document-authors.json').read_text())
        self.assertEqual({row['lineage'] for row in sidecar[current_hash]['authors']},
                         {'google', 'openai', 'anthropic'})
        job_id = 'third-author-after-move'
        job = self.elephant_job(job_id, document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}
        self.create(job)
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)



if __name__ == '__main__':
    unittest.main()
