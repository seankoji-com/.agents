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


class ElephantRepairJobTests(ElephantDocumentJobFixture):
    def test_factual_and_cold_read_acceptance_stay_distinct_and_cold_reader_is_isolated(self):
        document = self.document()
        job_id, caller = 'elephant-separation', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document))
        factual_argv, factual_input = self.accept_factual(job_id, caller, document)

        brief, raw = self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed',
                                   requirement='failed', findings=self.NOT_READY,
                                   conclusion='VERDICT: NOT READY. GAP-1 blocks a newcomer.')
        text = raw.decode()
        for leak in ('PRIVATE-OBJECTIVE-MARKER', 'PRIVATE-REQUIREMENT-MARKER', 'FACT-FINDING-MARKER',
                     'factual-observation', 'ci/Makefile'):
            self.assertNotIn(leak, text)
        self.assertEqual(brief['document'], {'path': str(document), 'sha256': sha(document.read_bytes())})
        self.assertEqual(brief['requirements'], [{'id': 'R-COLD'}])
        self.assertEqual(brief['authorization']['read'], [str(document)])
        definition = brief['effective_definition'] if brief['schema_version'] == 1 else brief['definition']
        self.assertIn('Assess only the supplied document', json.dumps(definition))
        self.assertNotIn('objective', brief)

        cold_argv = lambda path: self.doc_argv(document.parent.parent, document.parent.name, 'cold-read', path)
        # A factual observation can never satisfy the cold-read stage, nor the reverse.
        factual_as_cold = self.publish(job_id, caller, 'cold-read', self.factual_observation(document))
        self.assertNotEqual(self.accept(job_id, caller, 'cold-read', cold_argv(factual_as_cold), factual_as_cold).returncode, 0)
        cold_input = self.publish(job_id, caller, 'cold-read', self.cold_observation(document))
        self.assertNotEqual(self.accept(job_id, caller, 'factual', self.doc_argv(
            document.parent.parent, document.parent.name, 'factual', cold_input), cold_input, 'doc-r1').returncode, 0)
        # NOT READY maps to adverse and blocks acceptance even beside a "ready" observation.
        refused = self.accept(job_id, caller, 'cold-read', cold_argv(cold_input), cold_input)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('lacks a current ready result: c0', refused.stdout + refused.stderr)
        self.assertEqual(next(t for t in self.job_state(job_id)['tasks'] if t['task_id'] == 'c0')
                         ['execution_history'][-1]['result']['review_verdict'], 'adverse')
        # The coordinator's own not-ready observation is refused by the cold-read validator.
        not_ready = self.cold_observation(document, 'not-ready')
        path = self.base / 'not-ready.json'
        path.write_text(json.dumps(not_ready))
        direct = subprocess.run([sys.executable, *cold_argv(str(path))], capture_output=True, text=True, env=self.env)
        self.assertEqual(direct.returncode, 1)
        self.assertEqual(json.loads(direct.stdout)['mode'], 'cold-read')
        # Final acceptance needs both distinct stages; the factual receipt alone is not enough.
        final = self.run_helper('job_acceptance_cli.py', 'validate-final', job_id, {
            'caller': caller, 'validator_argv_by_stage': {'factual': factual_argv, 'cold-read': cold_argv(cold_input)},
            'input_file_by_stage': {'factual': factual_input, 'cold-read': cold_input}})
        self.assertEqual(final.returncode, 1, final.stdout + final.stderr)


    def test_factual_checker_major_finding_is_ingested_and_retained_for_disposition(self):
        document = self.document()
        caller = self.caller(self.WORKFLOW)
        # The old instruction (null verdict beside a major finding) is malformed and drops the finding.
        self.create(self.elephant_job('factual-null', document))
        self.dispatch('factual-null', caller, 'f0', verdict=None, status='failed', requirement='failed', findings=self.REFUTED)
        task = next(t for t in self.job_state('factual-null')['tasks'] if t['task_id'] == 'f0')
        self.assertTrue(task['execution_history'][-1].get('malformed'))
        self.assertEqual(task.get('finding_dispositions', []), [])
        # The corrected definition: adverse beside a blocker/major finding parses and retains it.
        self.create(self.elephant_job('factual-major', document))
        self.dispatch('factual-major', caller, 'f0', verdict='adverse', status='failed', requirement='failed',
                      findings=self.REFUTED, conclusion='Claim C1 refuted.')
        task = next(t for t in self.job_state('factual-major')['tasks'] if t['task_id'] == 'f0')
        self.assertFalse(task['execution_history'][-1].get('malformed'))
        self.assertEqual(task['execution_history'][-1]['result']['review_verdict'], 'adverse')
        self.assertEqual([(d['finding_id'], d['disposition']) for d in task['finding_dispositions']], [('CLAIM-C1', None)])
        self.assertEqual(task['status'], 'failed')
        # The adverse factual result never accepts the stage.
        path = self.publish('factual-major', caller, 'factual', self.factual_observation(document))
        refused = self.accept('factual-major', caller, 'factual',
                              self.doc_argv(document.parent.parent, document.parent.name, 'factual', path), path, 'doc-r1')
        self.assertNotEqual(refused.returncode, 0)


    def test_document_revision_then_in_place_record_keeps_repairer_for_new_job(self):
        document = self.document()
        caller = self.caller(self.WORKFLOW)
        repair_caps = json.loads(self.capabilities.read_text())
        repair_caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                           parentThreadId='synthetic-repairer-b')
        self.capabilities.write_text(json.dumps(repair_caps))
        job_id = 'revision-record-lineage'
        self.create(self.elephant_job(job_id, document, factual=False))
        self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed', requirement='failed',
                      findings=self.NOT_READY, conclusion='VERDICT: NOT READY')
        revised = document.read_bytes() + b'\nB repaired the deployment instructions.\n'
        document.write_bytes(revised)
        self.ok(self.revise(job_id, caller, document))

        repair_sidecar = json.loads((document.parent / 'document-authors.json').read_text())
        repaired_hash = sha(revised)
        path_key = str(document.resolve())
        self.assertEqual(repair_sidecar['_document_paths'][path_key]['sha256'], repaired_hash)
        self.assertEqual(repair_sidecar['_document_paths'][path_key]['order'], repair_sidecar[repaired_hash]['order'])
        self.assertEqual(repair_sidecar[repaired_hash]['document_path'], path_key)
        self.assertNotIn('document_author_records', self.job_state(job_id))

        document.write_bytes(document.read_bytes() + b'\nC fixed a typo in place.\n')
        later_caps = copy.deepcopy(repair_caps)
        later_caps.update(inheritedProviderInstanceId='claudeAgent', inheritedModel='claude-opus-5-5',
                          parentThreadId='synthetic-editor-c')
        later_caps_path = self.base / 'later-editor-capabilities.json'
        later_caps_path.write_text(json.dumps(later_caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'), str(document),
                                   '--capabilities', str(later_caps_path)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        new_job = 'revision-record-lineage-new'
        self.create(self.elephant_job(new_job, document, factual=False))
        imported = next(t for t in self.job_state(new_job)['tasks'] if t['task_id'] == 'c0')['document_authors']
        self.assertEqual({author.get('lineage') for author in imported}, {'google', 'openai', 'anthropic'})
        prepared = self.run_helper('job_cli.py', 'prepare', new_job, {'caller': caller, 'task_id': 'c0'})
        self.assertEqual(prepared.returncode, 2, prepared.stdout + prepared.stderr)
        self.assertIn('differ from every document author', prepared.stderr)


    def test_document_revision_writes_the_author_record_only_after_the_job_commits(self):
        document = self.document()
        caller = self.caller(self.WORKFLOW)
        job_id = 'revision-commit-order'
        self.create(self.elephant_job(job_id, document, factual=False))
        self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed', requirement='failed',
                      findings=self.NOT_READY, conclusion='VERDICT: NOT READY')
        document.write_bytes(document.read_bytes() + b'\nRepaired before a failed job write.\n')
        sidecar = document.parent / 'document-authors.json'
        before_sidecar, before_job = sidecar.read_bytes(), self.job_state(job_id)
        data = self.base / 'commit-order-input.json'
        data.write_text(json.dumps({'caller': caller, 'task_id': 'c0', 'reason': 'coordinator repaired NOT READY gaps',
                                    'document': {'path': str(document), 'sha256': sha(document.read_bytes())}}))
        # Run the real job_cli with only the job.json write failing.
        driver = ('import runpy, sys\n'
                  'sys.path.insert(0, sys.argv[1])\n'
                  'import core.jobs.store as store\n'
                  'real = store._atomic\n'
                  'def atomic(path, data, exclusive=False):\n'
                  '    if str(path).endswith("job.json"):\n'
                  '        raise OSError("fixture job write failure")\n'
                  '    return real(path, data, exclusive)\n'
                  'store._atomic = atomic\n'
                  'sys.argv = sys.argv[2:]\n'
                  'runpy.run_path(sys.argv[0], run_name="__main__")\n')
        failed = subprocess.run([sys.executable, '-c', driver, str(self.version), str(self.version / 'shared/job_cli.py'),
                                 'document-revision', '--state-root', str(self.state), '--job', job_id,
                                 '--input', str(data), '--capabilities', str(self.capabilities)],
                                capture_output=True, text=True, env=self.env)
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertIn('fixture job write failure', failed.stdout + failed.stderr)
        self.assertEqual(sidecar.read_bytes(), before_sidecar, 'the sidecar must not record an uncommitted revision')
        self.assertEqual(self.job_state(job_id), before_job)
        # Inner JobErrors keep their own message instead of the generic wrapper.
        sidecar.write_text('[]')
        refused = self.revise(job_id, caller, document)
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('document author records must be an object', refused.stderr)


    def test_repair_round_rebinds_the_document_within_the_round_budget_without_an_owner_decision(self):
        document = self.document()
        job_id, caller = 'elephant-repair', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document))
        # The fixture's synthetic author lineage is independent of its worker targets.
        self.assertEqual({a['lineage'] for a in next(t for t in self.job_state(job_id)['tasks'] if t['task_id'] == 'c0')['document_authors']}, {'google'})
        self.assertEqual({a['lineage'] for a in next(t for t in self.job_state(job_id)['tasks'] if t['task_id'] == 'f0')['document_authors']}, {'google'})
        self.accept_factual(job_id, caller, document)
        self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed', requirement='failed',
                      findings=self.NOT_READY, conclusion='VERDICT: NOT READY')
        old_sha = sha(document.read_bytes())
        # The coordinator, not a worker, repairs the document.
        document.write_text(document.read_text() + '\nDeploy from `main` only.\n')
        new_sha = sha(document.read_bytes())
        # A generic plan edit of the same contract is still an undeclared expansion.
        state = self.job_state(job_id)
        plan = {k: copy.deepcopy(state[k]) for k in ('requirements', 'dependencies', 'stages', 'tasks', 'constraints',
                                                       'authorization', 'policy')}
        for stage in plan['stages']:
            stage['validator_contract']['document_sha256'] = new_sha
        undeclared = self.run_helper('job_cli.py', 'plan-revision', job_id, {
            'caller': caller, 'revision': {'id': 'repair-round-2'}, 'new_plan': plan})
        self.assertEqual(undeclared.returncode, 2)
        self.assertIn('must match the stage validated document', undeclared.stderr)
        # Keep the slot subject consistent so the document consistency guard
        # cannot pre-empt the owner-decision check for a hash-only revision.
        for task in plan['tasks']:
            if task.get('document', {}).get('path') == str(document):
                task['document']['sha256'] = new_sha
        undeclared_hash_change = self.run_helper('job_cli.py', 'plan-revision', job_id, {
            'caller': caller, 'revision': {'id': 'repair-round-2-hash-only'}, 'new_plan': plan})
        self.assertEqual(undeclared_hash_change.returncode, 2,
                         undeclared_hash_change.stdout + undeclared_hash_change.stderr)
        self.assertIn('undeclared_expansion: owner decision required', undeclared_hash_change.stderr)
        # A declared repair needs the current bytes and a changed hash, but no owner decision.
        for wrong in (old_sha, 'f' * 64):
            refused = self.revise(job_id, caller, document, digest=wrong)
            self.assertEqual(refused.returncode, 2, refused.stdout)
        missing_parent = json.loads(self.capabilities.read_text())
        missing_parent.pop('parentThreadId')
        bad_capabilities = self.base / 'missing-parent-capabilities.json'
        bad_capabilities.write_text(json.dumps(missing_parent))
        refused = self.run_helper('job_cli.py', 'document-revision', job_id, {
            'caller': caller, 'task_id': 'c0', 'reason': 'coordinator repair',
            'document': {'path': str(document), 'sha256': new_sha}}, capabilities=bad_capabilities)
        self.assertEqual(refused.returncode, 2)
        self.assertIn('capabilities', refused.stderr)
        record = self.ok(self.revise(job_id, caller, document))
        self.assertEqual((record['previous_sha256'], record['sha256']), (old_sha, new_sha))
        self.assertEqual((record['rounds_performed'], record['max_rounds']), (1, 21))
        state = self.job_state(job_id)
        self.assertEqual(state['decisions'], [])
        self.assertEqual({s['id']: s['status'] for s in state['stages']}, {'factual': 'stale', 'cold-read': 'stale'})
        self.assertEqual({s['validator_contract']['document_sha256'] for s in state['stages']}, {new_sha})
        cold = next(t for t in state['tasks'] if t['task_id'] == 'c0')
        self.assertEqual(cold['document']['sha256'], new_sha)
        retry = lambda task_id: self.ok(self.run_helper('job_cli.py', 'retry', job_id, {
            'caller': caller, 'task_id': task_id, 'reason': 'document repaired'}))
        # Stale slots need a charged retry, and the cold read waits for a fresh factual
        # acceptance of the repaired bytes.
        self.assertNotEqual(self.run_helper('job_cli.py', 'prepare', job_id, {'caller': caller, 'task_id': 'c0'}).returncode, 0)
        retry('f0')
        self.accept_factual(job_id, caller, document)
        retry('c0')
        brief, raw = self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed', requirement='failed',
                                   findings=self.NOT_READY, conclusion='VERDICT: NOT READY')
        self.assertEqual(brief['document']['sha256'], new_sha)
        self.assertNotIn('GAP-1', raw.decode())  # earlier cold-read findings never reach the fresh reader
        self.assertEqual(next(s for s in self.job_state(job_id)['stages'] if s['id'] == 'cold-read')['cycle'], 1)


    def test_new_documents_get_the_default_rounds_and_legacy_loops_keep_their_remaining_five(self):
        # New topic: the default policy snapshot (initial read plus max_repair_cycles repairs).
        self.assertEqual(self.rounds('rounds-new'), 21)
        self.assertEqual(self.job_state('rounds-new')['policy']['max_repair_cycles'], 20)
        # Legacy loop under the five-round instruction with two rounds already performed.
        self.assertEqual(self.rounds('rounds-legacy', {'max_repair_cycles': 5 - 2 - 1,
                                                        'max_artifact_bytes': 16 * 1024 * 1024}), 3)


    def test_ready_cold_read_from_a_document_subject_review_slot_is_accepted(self):
        document = self.document()
        job_id, caller = 'elephant-ready', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document, cold_role='review'))
        factual_argv, factual_input = self.accept_factual(job_id, caller, document)
        brief, _ = self.dispatch(job_id, caller, 'c0', verdict='approve', conclusion='VERDICT: READY')
        subject = {'path': str(document), 'sha256': sha(document.read_bytes())}
        self.assertEqual((brief['role'], brief['review_inputs']), ('review', {'documents': [subject]}))
        cold_input = self.publish(job_id, caller, 'cold-read', self.cold_observation(document))
        cold_argv = self.doc_argv(document.parent.parent, document.parent.name, 'cold-read', cold_input)
        self.ok(self.accept(job_id, caller, 'cold-read', cold_argv, cold_input))
        final = {'caller': caller, 'validator_argv_by_stage': {'factual': factual_argv, 'cold-read': cold_argv},
                 'input_file_by_stage': {'factual': factual_input, 'cold-read': cold_input}}
        self.ok(self.run_helper('job_acceptance_cli.py', 'validate-final', job_id, final))
        # A document changed after its review makes the review stale: no current acceptance remains.
        document.write_text(document.read_text() + 'Edited after the cold read.\n')
        overview = self.ok(self.run_helper('job_cli.py', 'overview', job_id))
        self.assertEqual(next(s for s in overview['stages'] if s['id'] == 'cold-read')['status'], 'stale')
        again = self.accept(job_id, caller, 'cold-read', cold_argv, cold_input)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('the review is stale', again.stdout + again.stderr)
        self.assertNotEqual(self.run_helper('job_acceptance_cli.py', 'validate-final', job_id, final).returncode, 0)


    def test_legacy_job_fixture_without_identity_accepts_review_target_only(self):
        document = self.document()
        job_id, caller = 'legacy-review-target-only', self.caller(self.WORKFLOW)
        stage = {'id': 'factual', 'depends_on': [], 'requirements': ['R-FACT'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'legacy-r1',
                 'validator_contract': self.contract(document, 'factual')}
        subject = {'task_id': 'f0', 'stage_id': 'factual', 'logical_slot_id': 'factual',
                   'request_id': 'legacy-f0', 'worker_id': 'elephant-goldfish/factual-checker',
                   'dependency_key': 'eg', 'write_scope': {'mode': 'coordinator-only'},
                   'review_required': True, 'review_task_ids': ['r0'],
                   'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}}
        reviewer = {'task_id': 'r0', 'stage_id': 'factual', 'logical_slot_id': 'review',
                    'request_id': 'legacy-r0', 'worker_id': 'elephant-goldfish/cold-reader',
                    'dependency_key': 'eg', 'role': 'review', 'reviewed_task_ids': ['f0'],
                    'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5', 'lineage': 'anthropic'},
                    'write_scope': {'mode': 'coordinator-only'}}
        job = self.base_job(job_id, self.WORKFLOW, {'R-FACT': 'every cited claim is confirmed'},
                            [stage], [subject, reviewer])
        # This pre-marker fixture is loaded through core storage, not created by the new-job CLI.
        job['policy'] = {'max_repair_cycles': 3, 'max_artifact_bytes': 16 * 1024 * 1024,
                         'max_live_workers': 2}
        from core.jobs import create_job
        from shared.job_coordinator import verified_pins
        pins = verified_pins(job, self.state, self.prefix, self.agents,
                             self.base / 'config' / 'workers.json')
        create_job(job, self.state, pins)
        self.assertNotIn('identity', self.job_state(job_id)['policy'])
        self.dispatch(job_id, caller, 'f0', report_identity=False)
        self.dispatch(job_id, caller, 'r0', verdict='approve', report_identity=False)
        factual_input = self.publish(job_id, caller, 'factual', self.factual_observation(document))
        factual_argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', factual_input)
        accepted = self.accept(job_id, caller, 'factual', factual_argv, factual_input, 'legacy-r1')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


    def test_marked_acceptance_requires_observed_identity_for_subject_and_reviewer(self):
        document = self.document()
        caller = self.caller(self.WORKFLOW)
        for missing in ('subject', 'reviewer'):
            job_id = 'marked-unreported-' + missing
            stage = {'id': 'factual', 'depends_on': [], 'requirements': ['R-FACT'], 'status': 'pending',
                     'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'marked-r1',
                     'validator_contract': self.contract(document, 'factual')}
            subject = {'task_id': 'f0', 'stage_id': 'factual', 'logical_slot_id': 'factual',
                       'request_id': 'marked-f0', 'worker_id': 'elephant-goldfish/factual-checker',
                       'dependency_key': 'eg', 'write_scope': {'mode': 'coordinator-only'},
                       'review_required': True, 'review_task_ids': ['r0'],
                       'target': {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}}
            reviewer = {'task_id': 'r0', 'stage_id': 'factual', 'logical_slot_id': 'review',
                        'request_id': 'marked-r0', 'worker_id': 'elephant-goldfish/cold-reader',
                        'dependency_key': 'eg', 'role': 'review', 'reviewed_task_ids': ['f0'],
                        'target': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5', 'lineage': 'anthropic'},
                        'write_scope': {'mode': 'coordinator-only'}}
            self.create(self.base_job(job_id, self.WORKFLOW, {'R-FACT': 'claims are confirmed'},
                                      [stage], [subject, reviewer]))
            self.dispatch(job_id, caller, 'f0')
            self.dispatch(job_id, caller, 'r0', verdict='approve')
            state = self.job_state(job_id)
            task_id = 'f0' if missing == 'subject' else 'r0'
            task = next(row for row in state['tasks'] if row['task_id'] == task_id)
            task['handles'][0].pop('observed_identity', None)
            (self.state / job_id / 'job.json').write_text(json.dumps(state))
            observation = self.publish(job_id, caller, 'factual', self.factual_observation(document))
            argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
            refused = self.accept(job_id, caller, 'factual', argv, observation, 'marked-r1')
            self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
            self.assertIn('unreported or mismatched', refused.stderr)


    def test_direct_factual_cli_requires_latest_executor_waiver_and_replacement_after_resume(self):
        from shared.document_authors import stage_waiver_binding
        document = self.document()
        job_id, caller = 'direct-factual-lineage', self.caller(self.WORKFLOW)
        digest = sha(document.read_bytes())
        author_rows = next(iter(json.loads((document.parent / 'document-authors.json').read_text()).values()))['authors']
        stage = {'id': 'factual', 'depends_on': [], 'requirements': ['R-FACT'], 'status': 'pending',
                 'execution_mode': 'direct', 'independent_of_author': True, 'document_authors': author_rows,
                 'validator_dependency': 'eg', 'revision': 'direct-r1',
                 'validator_contract': self.contract(document, 'factual')}
        self.create(self.base_job(job_id, self.WORKFLOW, {'R-FACT': 'every claim is confirmed'}, [stage], []))

        def record_executor(capabilities):
            path = self.base / f'caps-executor-{self.counter}.json'; path.write_text(json.dumps(capabilities))
            self.counter += 1
            result = self.run_helper('job_cli.py', 'direct-execution', job_id,
                                     {'caller': caller, 'stage_id': 'factual'}, capabilities=path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        def add_stage_waiver(label):
            state = self.job_state(job_id); current = state['stages'][0]
            executor = current['direct_execution_history'][-1]['identity']
            binding = stage_waiver_binding(current, current['document_authors'], digest, executor)
            source = self.base / f'owner-{label}.txt'; source.write_text('Owner approves factual lineage waiver ' + label)
            decision = {'id': 'decision-' + label, 'scope': 'lineage-waiver:stage:factual',
                        'requirement_ids': [], 'binding': binding, 'source': str(source),
                        'source_sha256': sha(source.read_bytes()), 'quote': 'Owner approves factual lineage waiver ' + label}
            self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))

        caps = json.loads(self.capabilities.read_text())
        record_executor(caps)
        observation_path = self.publish(job_id, caller, 'factual', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation_path)
        refused = self.accept(job_id, caller, 'factual', argv, observation_path, 'direct-r1')
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('current stage-scoped lineage waiver', refused.stderr)
        add_stage_waiver('first')
        accepted = self.accept(job_id, caller, 'factual', argv, observation_path, 'direct-r1')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        resumed = json.loads(self.capabilities.read_text())
        resumed.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                       parentThreadId='synthetic-resumed-executor')
        self.choose_direct_work(job_id, caller, resumed, 'factual')
        record_executor(resumed)
        stale = self.accept(job_id, caller, 'factual', argv, observation_path, 'direct-r1')
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('current stage-scoped lineage waiver', stale.stderr)
        add_stage_waiver('replacement')
        observation_path = self.publish(job_id, caller, 'factual', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation_path)
        accepted = self.accept(job_id, caller, 'factual', argv, observation_path, 'direct-r1')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


    def test_plan_revision_converts_delegated_factual_stage_to_direct_with_a_new_waiver(self):
        from shared.document_authors import stage_waiver_binding
        document = self.document()
        job_id, caller = 'convert-factual-to-direct', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document))
        # Finish a delegated factual pass, then change its declared execution contract.
        self.accept_factual(job_id, caller, document)
        state = self.job_state(job_id)
        plan = {key: copy.deepcopy(state[key]) for key in ('requirements', 'dependencies', 'stages', 'tasks',
                'constraints', 'authorization', 'policy')}
        factual = next(row for row in plan['stages'] if row['id'] == 'factual')
        factual.update(execution_mode='direct', independent_of_author=True,
                       lineage_waiver={'scope': 'lineage-waiver:stage:factual'})
        plan['tasks'] = [row for row in plan['tasks'] if row['task_id'] != 'f0']
        source = self.base / 'owner-conversion.txt'; source.write_text('Owner approves delegated to direct conversion')
        revision = {'id': 'convert-factual-r2'}
        owner = {'id': 'owner-conversion', 'scope': 'plan:convert-factual-r2', 'requirement_ids': [],
                 'quote': 'Owner approves delegated to direct conversion', 'source': str(source),
                 'source_sha256': sha(source.read_bytes())}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': owner}))
        self.ok(self.run_helper('job_cli.py', 'plan-revision', job_id,
                                {'caller': caller, 'revision': {**revision, 'owner_decision_id': owner['id']},
                                 'new_plan': plan}))
        converted = self.job_state(job_id)
        self.assertFalse(any(t['stage_id'] == 'factual' for t in converted['tasks']))
        factual = next(row for row in converted['stages'] if row['id'] == 'factual')
        self.assertEqual((factual['execution_mode'], factual['independent_of_author']), ('direct', True))
        caps = json.loads(self.capabilities.read_text())
        self.choose_direct_work(job_id, caller, caps, 'factual')
        record_path = self.base / 'conversion-capabilities.json'; record_path.write_text(json.dumps(caps))
        observed = self.run_helper('job_cli.py', 'direct-execution', job_id,
                                   {'caller': caller, 'stage_id': 'factual'}, capabilities=record_path)
        self.assertEqual(observed.returncode, 0, observed.stdout + observed.stderr)
        factual = next(row for row in self.job_state(job_id)['stages'] if row['id'] == 'factual')
        executor = factual['direct_execution_history'][-1]['identity']
        binding = stage_waiver_binding(factual, factual.get('document_authors', [{'unknown': True}]),
                                       sha(document.read_bytes()), executor)
        waiver_source = self.base / 'owner-stage-waiver.txt'; waiver_source.write_text('Owner approves replacement stage waiver')
        waiver = {'id': 'stage-conversion-waiver', 'scope': 'lineage-waiver:stage:factual',
                  'requirement_ids': [], 'binding': binding, 'source': str(waiver_source),
                  'source_sha256': sha(waiver_source.read_bytes()), 'quote': 'Owner approves replacement stage waiver'}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': waiver}))
        observation = self.publish(job_id, caller, 'factual', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', observation)
        accepted = self.accept(job_id, caller, 'factual', argv, observation, 'doc-r1')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


    def test_document_subject_review_slots_refuse_ambiguous_empty_changed_or_escaping_subjects(self):
        document = self.document()
        # Both subject forms at once.
        job = self.elephant_job('review-both', document, cold_role='review')
        job['tasks'][-1]['reviewed_task_ids'] = ['f0']
        self.refused_review('review-both', job, 'exactly one subject form')
        # An empty subject list is not a review.
        job = self.elephant_job('review-empty', document, cold_role='review')
        job['tasks'][-1]['reviewed_documents'] = []
        self.assertNotEqual(self.run_helper('job_cli.py', 'create', 'review-empty', job, prefix=self.prefix,
                                            agents_root=self.agents).returncode, 0)
        # A subject other than the document-only slot's own document.
        job = self.elephant_job('review-other', document, cold_role='review')
        job['tasks'][-1]['reviewed_documents'] = [{'path': str(document), 'sha256': 'a' * 64}]
        self.refused_review('review-other', job, 'names exactly its supplied document')
        # The declared hash no longer matches the bytes at preparation.
        job = self.elephant_job('review-changed', document, cold_role='review', factual=False)
        document.write_text(document.read_text() + 'Changed before preparation.\n')
        self.refused_review('review-changed', job, 'the review is stale')
        # Symlinked, traversing and job-state subjects are refused.
        link = document.parent / 'linked.md'
        link.symlink_to(document)
        self.refused_review('review-link', self.elephant_job('review-link', link, cold_role='review', factual=False,
                                                             digest=sha(document.read_bytes())), 'crosses a symlink')
        dotted = document.parent / '..' / document.parent.name / document.name
        self.refused_review('review-dotdot', self.elephant_job('review-dotdot', dotted, cold_role='review', factual=False),
                            'without parent traversal')
        inside = self.state / 'review-inside' / 'evidence.md'
        self.create(self.elephant_job('review-inside', inside, cold_role='review', factual=False, digest=sha(b'# Doc\n')))
        inside.write_bytes(b'# Doc\n')
        proc = self.run_helper('job_cli.py', 'prepare', 'review-inside', {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn('cannot be job state', proc.stderr)



if __name__ == '__main__':
    unittest.main()
