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
    PLUGIN, OPERATIONS, WORKERS, sha, words, section, InstalledJobFixture,
)


class InstructionContractTests(unittest.TestCase):
    """Entry, playbook, reference and worker-definition contract."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((PLUGIN / 'plugin.json').read_text())
        cls.entry = (PLUGIN / 'entry.md').read_text()
        cls.thinking = (PLUGIN / 'playbooks/thinking.md').read_text()
        cls.elephant = (PLUGIN / 'playbooks/elephant.md').read_text()
        cls.reference = (PLUGIN / 'references/document-jobs.md').read_text()

    def test_every_operation_keeps_its_name_meaning_and_route(self):
        self.assertEqual(self.manifest['operations'], OPERATIONS)
        rows = {}
        for line in self.entry.splitlines():
            match = re.match(r'^\| `([a-z-]+)', line)
            if match:
                rows[match.group(1)] = line
        self.assertEqual(sorted(rows), sorted(OPERATIONS))
        self.assertIn('Run it directly', rows['doctor'])
        self.assertIn('`PKG/playbooks/thinking.md`', rows['thinking'])
        self.assertIn('thinking list', rows['thinking'])
        self.assertIn('`PKG/playbooks/elephant.md`', rows['elephant'])
        self.assertIn('`check` section of `PKG/playbooks/elephant.md`', rows['check'])
        self.assertIn('no cold read', rows['check'])
        self.assertIn('## check', self.elephant)
        self.assertIn('never start a cold read from `check`', section(self.elephant, '## check'))
        for rel in set(re.findall(r'`PKG/((?:playbooks|references)/[\w./-]+)`', self.entry)):
            self.assertTrue((PLUGIN / rel).is_file(), rel)
        for folder in ('playbooks', 'references'):
            for path in (PLUGIN / folder).glob('*.md'):
                self.assertIn(f'PKG/{folder}/{path.name}', self.entry + self.thinking + self.elephant)

    def test_entry_uses_the_shared_protocol_and_stays_small(self):
        for shared in ('job-coordination.md', 't3-runtime.md', 'delegation.md', 'learnings.md'):
            self.assertIn(f'`PKG/shared/{shared}`', self.entry)
        # Plugin policy only: the generic dispatch/lifecycle protocol is not restated.
        for generic in ('clientRequestId', 'delegate_task', 'task-observation', 'same-ID'):
            self.assertNotIn(generic, self.entry)
        self.assertLess(words(PLUGIN / 'entry.md'), 1500)
        # Each operation loads the entry plus one playbook (and the reference only before delegation).
        for loaded in ('playbooks/thinking.md', 'playbooks/elephant.md', 'references/document-jobs.md'):
            self.assertLess(words(PLUGIN / loaded), 1300, loaded)

    def test_cheap_operations_stay_direct(self):
        direct = section(self.entry, '## Direct operations')
        for op in ('`doctor`', '`thinking list`', '`gate`', '`render_handoff.py --check`'):
            self.assertIn(op, direct)
        self.assertIn('never launch an agent', direct)

    def test_interactive_discovery_and_acceptance_stay_with_the_coordinator(self):
        who = section(self.entry, '## Who does what')
        self.assertIn('Interactive discovery is never delegated', who)
        runs = section(self.thinking, '## Who runs each step')
        self.assertIn('You coordinate steps 1 to 6', runs)
        self.assertIn('never conduct discovery', runs)
        self.assertIn('Only you prepare, dispatch, ingest and accept', self.entry)

    def test_acceptance_authorities_and_distinct_verdicts_are_named(self):
        authority = section(self.entry, '## Acceptance authority')
        for name in ('thinking_state.py gate', 'render_handoff.py <slug> --check',
                     'validate_document.py --mode factual', 'validate_document.py --mode cold-read'):
            self.assertIn(name, authority)
        self.assertIn('separate stages with separate observations and receipts', authority)
        self.assertIn('Never let one stage cover both', self.reference)

    def test_boundaries_and_approvals(self):
        boundaries = section(self.entry, '## Boundaries')
        for term in ('Drafts, reminders, scheduled continuations, resume', 'requirement changes never launch implementation',
                     'bypass the readiness gate', 'issue #25', 'grant no execution authority', 'exact scope'):
            self.assertIn(term.lower(), ' '.join(boundaries.split()).lower())
        approvals = section(self.entry, '## Approvals')
        self.assertIn('native question picker', approvals)
        self.assertIn('`PKG/shared/t3-runtime.md`', approvals)
        self.assertIn('recommended option first', approvals)
        self.assertIn('question picker', section(self.reference, '## Repair rounds'))
        # The older thinking boundary and its regression scenarios survive unchanged.
        self.assertIn('implementation children, imps runs', self.thinking)
        self.assertIn('never replaces the gate and never grants execution', self.thinking)

    def test_cold_reader_isolation_and_round_policy_are_stated(self):
        slots = section(self.reference, '## Slots')
        self.assertIn('context_policy: document-only', slots)
        self.assertIn('only the brief path, its\n  SHA-256', slots)
        for leak in ('planning notes', 'factual findings', 'repository answers', 'earlier cold-read'):
            self.assertIn(leak, slots)
        self.assertIn('never use a follow-up', slots)
        limits = section(self.reference, '## Round limits')
        self.assertIn('Twelve rounds', limits)
        self.assertIn('Keep the recorded limit', limits)
        self.assertIn('limit of five and the rounds already performed', limits)
        self.assertIn('You repair cold-read gaps yourself', self.reference)
        self.assertIn('A cold read cannot fall back to you', self.reference)

    def test_worker_definitions_satisfy_the_worker_contract(self):
        declared = {w['id']: w for w in self.manifest['workers']}
        self.assertEqual(set(declared), WORKERS)
        model_id = re.compile(r'\b(claude-[a-z0-9-]+|gpt-\d|haiku|sonnet|opus|gemini-\d)', re.I)
        for worker_id, worker in declared.items():
            with self.subTest(worker=worker_id):
                text = (PLUGIN / worker['path']).read_text()
                self.assertTrue(text.startswith(f'---\nworker_id: {worker_id}\n'))
                self.assertIn(worker['responsibility'], text)
                for term in ('SHA-256', 'Do not dispatch children', 'accept your own',
                             'worker-result.schema.json', 'Redact'):
                    self.assertIn(term, text)
                self.assertIsNone(model_id.search(text))
                self.assertLess(words(PLUGIN / worker['path']), 450)
        cold = (PLUGIN / 'agents/cold-reader.md').read_text()
        self.assertIn('Do not open the repository', cold)
        self.assertIn('`approve` for READY and `adverse` for NOT READY', cold)
        self.assertIn('never\n  READY', cold)
        factual = (PLUGIN / 'agents/factual-checker.md').read_text()
        self.assertIn('Set `review_verdict` to null', factual)
        # Blocker/major findings force adverse in the result parser, for every role.
        self.assertIn('`major` finding, set it to `adverse`', ' '.join(factual.split()))
        self.assertIn('Never use `approve`', factual)
        self.assertIn('Never edit the\ndocument', factual)
        for status in ('ready-for-acceptance', 'needs-followup', 'blocked', 'failed'):
            self.assertIn(status, factual)



class ThinkingHandoffJobTests(InstalledJobFixture):
    """G-EG-DISCOVERY / G-EG-HANDOFF through the installed gate, renderer and job."""

    def write_statement(self, topic, text):
        path = topic / 'review-statement.txt'
        path.write_text(text)
        return str(path)

    def test_job_cli_prepare_and_acceptance_refuse_a_lineage_found_in_the_rendered_handoff(self):
        root, slug = self.base / 'thinking', 'lineage-handoff'
        topic = root / slug
        self.assertEqual(self.thinking_state(root, 'init', slug, '--output-type', 'implementation').returncode, 0)
        discovery = '# Discovery\n\nRetries must never double-charge.\n'
        spec = '# Spec\n\n[REQ-RETRY] Retry a timed-out charge once.\n'
        (topic / 'discovery.md').write_text(discovery)
        (topic / 'spec.md').write_text(spec)
        self.assertEqual(self.thinking_state(root, 'review', slug, '--decision', 'accepted', '--scope', 'finalise-brief',
            '--discovery-sha256', sha(discovery.encode()), '--evidence-ref', 'synthetic:owner-review',
            '--operator-statement-file', self.write_statement(topic, 'I accept this discovery.')).returncode, 0)
        caps_a = json.loads(self.capabilities.read_text())
        caps_a.update(inheritedProviderInstanceId='antigravity', inheritedModel='gemini-3.8-flash-high')
        caps_a['parentThreadId'] = 'synthetic-author-a'
        caps_b = json.loads(self.capabilities.read_text())
        caps_b.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol')
        caps_b['parentThreadId'] = 'synthetic-renderer-b'
        caps_a_path, caps_b_path = self.base / 'caps-a.json', self.base / 'caps-b.json'
        caps_a_path.write_text(json.dumps(caps_a)); caps_b_path.write_text(json.dumps(caps_b))
        for name in ('discovery.md', 'spec.md'):
            self.assertEqual(self.thinking_state(root, 'author', slug, name, '--capabilities', str(caps_a_path)).returncode, 0)
        self.review_plan(root, slug)
        render = subprocess.run([sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root),
                                 '--capabilities', str(caps_b_path)], capture_output=True, text=True, env=self.env)
        self.assertEqual(render.returncode, 0, render.stdout + render.stderr)
        handoff = topic / 'handoff.md'
        handoff.write_text(handoff.read_text() + '\n')
        recorded_handoff = self.thinking_state(root, 'author', slug, 'handoff.md',
                                               '--capabilities', str(caps_b_path))
        self.assertEqual(recorded_handoff.returncode, 0, recorded_handoff.stdout + recorded_handoff.stderr)
        digest = sha(handoff.read_bytes())
        job_id, caller = 'handoff-lineage-e2e', self.caller('elephant-goldfish/thinking')
        contract = {'root': str(root), 'slug': slug, 'mode': 'cold-read', 'document_path': str(handoff),
                    'document_sha256': digest}
        task = {'task_id': 'cold-a', 'stage_id': 'cold', 'logical_slot_id': 'cold', 'request_id': 'req-cold-a',
                'worker_id': 'elephant-goldfish/cold-reader', 'dependency_key': 'eg', 'context_policy': 'document-only',
                'document': {'path': str(handoff), 'sha256': digest}, 'write_scope': {'mode': 'coordinator-only'},
                'independent_of_author': True, 'target': {'providerInstanceId': 'antigravity',
                'model': 'gemini-3.8-flash-high', 'lineage': 'google'}}
        self.create(self.base_job(job_id, 'elephant-goldfish/thinking', {'R-COLD': 'independent cold read'},
            [{'id': 'cold', 'depends_on': [], 'requirements': ['R-COLD'], 'status': 'pending',
              'validator_dependency': 'eg', 'validator_contract': contract}], [task]))
        prepared = self.run_helper('job_cli.py', 'prepare', job_id, {'caller': caller, 'task_id': 'cold-a'})
        self.assertEqual(prepared.returncode, 2, prepared.stdout)
        self.assertIn('differ from every document author', prepared.stderr)
        # A different canonical reader can execute a review round. Coordinator C
        # edits both source files and records each new hash before B renders again.
        repair_id = 'handoff-revision-lineage-e2e'
        repair_task = {**task, 'task_id': 'cold-openai', 'logical_slot_id': 'cold-openai',
                       'request_id': 'req-cold-openai', 'target': {'providerInstanceId': 'claudeAgent',
                       'model': 'claude-opus-5-5', 'lineage': 'anthropic'}}
        self.create(self.base_job(repair_id, 'elephant-goldfish/thinking', {'R-COLD': 'independent cold read'},
            [{'id': 'cold', 'depends_on': [], 'requirements': ['R-COLD'], 'status': 'pending',
              'validator_dependency': 'eg', 'validator_contract': contract}], [repair_task]))
        self.dispatch(repair_id, caller, 'cold-openai')
        discovery = '# Discovery\n\n[REQ-RETRY] The retry must not charge twice.\n'
        spec = '# Spec\n\n[REQ-RETRY] Retry a timed-out charge exactly once per request ID.\n'
        (topic / 'discovery.md').write_text(discovery)
        (topic / 'spec.md').write_text(spec)
        caps_c = json.loads(self.capabilities.read_text())
        caps_c.update(inheritedProviderInstanceId='claudeAgent', inheritedModel='claude-opus-5-5')
        caps_c['parentThreadId'] = 'synthetic-repair-c'
        caps_c_path = self.base / 'caps-c.json'; caps_c_path.write_text(json.dumps(caps_c))
        self.assertEqual(self.thinking_state(root, 'review', slug, '--decision', 'accepted', '--scope', 'finalise-brief',
            '--discovery-sha256', sha(discovery.encode()), '--evidence-ref', 'synthetic:owner-review-after-edit',
            '--operator-statement', 'I accept the edited discovery.').returncode, 0)
        self.assertEqual(self.thinking_state(root, 'author', slug, 'discovery.md', '--capabilities', str(caps_c_path)).returncode, 0)
        self.assertEqual(self.thinking_state(root, 'author', slug, 'spec.md', '--capabilities', str(caps_c_path)).returncode, 0)
        self.review_plan(root, slug)
        render = subprocess.run([sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root),
                                 '--capabilities', str(caps_b_path)], capture_output=True, text=True, env=self.env)
        self.assertEqual(render.returncode, 0, render.stdout + render.stderr)
        revised_sha = sha(handoff.read_bytes())
        revision = self.run_helper('job_cli.py', 'document-revision', repair_id, {
            'caller': caller, 'task_id': 'cold-openai', 'reason': 'coordinator B re-rendered after C repaired the specification',
            'document': {'path': str(handoff), 'sha256': revised_sha}}, capabilities=caps_b_path)
        self.assertEqual(revision.returncode, 0, revision.stdout + revision.stderr)
        repaired_task = next(t for t in self.job_state(repair_id)['tasks'] if t['task_id'] == 'cold-openai')
        self.assertEqual({row['lineage'] for row in repaired_task['document_authors']},
                         {'anthropic', 'openai', 'google'})
        self.assertIn('synthetic-repair-c', {row.get('parentThreadId') for row in repaired_task['document_authors']})
        repaired_records = json.loads((topic / 'document-authors.json').read_text())
        self.assertEqual({row['lineage'] for row in repaired_records[revised_sha]['authors']},
                         {'anthropic', 'openai', 'google'})
        self.ok(self.run_helper('job_cli.py', 'retry', repair_id,
            {'caller': caller, 'task_id': 'cold-openai', 'reason': 'prepare against repaired handoff'}))
        prepared = self.run_helper('job_cli.py', 'prepare', repair_id,
                                   {'caller': caller, 'task_id': 'cold-openai'})
        self.assertEqual(prepared.returncode, 2, prepared.stdout + prepared.stderr)
        self.assertIn('differ from every document author', prepared.stderr)
        # Repeat through document-revision with a repaired source that has no hash
        # record. The renderer and the revision must preserve unknown authorship.
        unknown_job = 'handoff-unknown-revision-e2e'; unknown_sha = sha(handoff.read_bytes())
        unknown_contract = {**contract, 'document_sha256': unknown_sha}
        unknown_task = {**task, 'task_id': 'unknown-source', 'logical_slot_id': 'unknown-source',
                        'request_id': 'req-unknown-source', 'document': {'path': str(handoff), 'sha256': unknown_sha}}
        unknown_task['target'] = {'providerInstanceId': 'grok', 'model': 'grok-3', 'lineage': 'xai'}
        self.create(self.base_job(unknown_job, 'elephant-goldfish/thinking', {'R-COLD': 'document review'},
            [{'id': 'cold', 'depends_on': [], 'requirements': ['R-COLD'], 'status': 'pending',
              'validator_dependency': 'eg', 'validator_contract': unknown_contract}], [unknown_task]))
        self.dispatch(unknown_job, caller, 'unknown-source')
        first_missing_spec = '# Spec\n\n[REQ-RETRY] Retry once, as written by an unrecorded source.\n'
        (topic / 'spec.md').write_text(first_missing_spec + '\nA further repair with no author receipt.\n')
        self.review_plan(root, slug)
        render = subprocess.run([sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root),
                                 '--capabilities', str(caps_b_path)], capture_output=True, text=True, env=self.env)
        self.assertEqual(render.returncode, 0, render.stdout + render.stderr)
        unknown_sha = sha(handoff.read_bytes())
        unknown_revision = self.run_helper('job_cli.py', 'document-revision', unknown_job, {
            'caller': caller, 'task_id': 'unknown-source', 'reason': 'unrecorded source repair',
            'document': {'path': str(handoff), 'sha256': unknown_sha}}, capabilities=caps_c_path)
        self.assertEqual(unknown_revision.returncode, 0, unknown_revision.stdout + unknown_revision.stderr)
        unknown_authors = next(t for t in self.job_state(unknown_job)['tasks']
                               if t['task_id'] == 'unknown-source')['document_authors']
        self.assertEqual(unknown_authors, [{'unknown': True}])
        self.ok(self.run_helper('job_cli.py', 'retry', unknown_job,
            {'caller': caller, 'task_id': 'unknown-source', 'reason': 'unknown source authorship'}))
        refused_unknown = self.run_helper('job_cli.py', 'prepare', unknown_job,
            {'caller': caller, 'task_id': 'unknown-source'})
        self.assertEqual(refused_unknown.returncode, 2, refused_unknown.stdout + refused_unknown.stderr)
        self.assertIn('author unrecorded', refused_unknown.stderr)

    def test_handoff_acceptance_is_content_bound_and_never_grants_execution(self):
        root = self.base / 'thinking'
        slug = 'retry-policy'
        topic = root / slug
        self.assertEqual(self.thinking_state(root, 'init', slug, '--output-type', 'implementation').returncode, 0)
        # A draft (stop request / "what you have so far") cannot be accepted or gated.
        (topic / 'discovery.md').write_text('# Discovery\n\n<!-- thinking:draft -->\nDRAFT. Non-executable.\n\nOpen question.\n')
        draft_sha = json.loads(self.thinking_state(root, 'resolve', slug).stdout)['artifacts']['discovery.md']['sha256']
        refused = self.thinking_state(root, 'review', slug, '--decision', 'accepted', '--scope', 'finalise-brief',
                                      '--discovery-sha256', draft_sha, '--evidence-ref', 'msg:1',
                                      '--operator-statement-file', self.write_statement(topic, 'Looks good.'))
        self.assertNotEqual(refused.returncode, 0)
        discovery = '# Discovery\n\nDuplicate charges after a timeout matter more than latency.\n'
        (topic / 'discovery.md').write_text(discovery)
        (topic / 'spec.md').write_text('# Spec\n\n[REQ-RETRY] A timed-out charge is retried once, idempotently.\n')
        self.assertNotEqual(self.thinking_state(root, 'gate', slug, '--require', 'discovery,spec').returncode, 0)
        reviewed = self.thinking_state(root, 'review', slug, '--decision', 'accepted', '--scope', 'finalise-brief',
                                       '--discovery-sha256', sha(discovery.encode()), '--evidence-ref', 'msg:2',
                                       '--operator-statement-file', self.write_statement(topic, 'I accept this discovery.'))
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout)
        self.review_plan(root, slug)
        render = subprocess.run([sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root), '--capabilities', str(self.capabilities)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(render.returncode, 0, render.stdout + render.stderr)
        # The cold-read budget is recorded in the topic and changes neither phase nor authority.
        budget = self.thinking_state(root, 'set', slug, 'cold_read.max_rounds=12', 'cold_read.rounds_performed=0',
                                     'cold_read.limit_source=new-topic-default')
        state = json.loads(budget.stdout)
        self.assertEqual(state['meta']['cold_read'], {'max_rounds': 12, 'rounds_performed': 0,
                                                      'limit_source': 'new-topic-default'})
        self.assertEqual(state['next_phase'], 'complete')
        self.assertIs(state['execution_authorized'], False)

        job_id, workflow = 'thinking-retry-policy', 'elephant-goldfish/thinking'
        caller = self.caller(workflow)
        contract = {'root': str(root), 'slug': slug, 'mode': 'handoff'}
        self.create(self.base_job(job_id, workflow, {'R-HANDOFF': 'reviewed, provenance-checked handoff'},
                                  [{'id': 'handoff', 'depends_on': [], 'requirements': ['R-HANDOFF'], 'status': 'pending',
                                    'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'handoff-r1',
                                    'validator_contract': contract}], []))
        descriptor = self.publish(job_id, caller, 'handoff', contract)
        argv = self.doc_argv(root, slug, 'handoff')
        accepted = self.accept(job_id, caller, 'handoff', argv, descriptor, 'handoff-r1')
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        final = {'caller': caller, 'validator_argv_by_stage': {'handoff': argv}, 'input_file_by_stage': {'handoff': descriptor}}
        self.ok(self.run_helper('job_acceptance_cli.py', 'validate-final', job_id, final))
        self.assertIs(json.loads(self.thinking_state(root, 'resolve', slug).stdout)['execution_authorized'], False)

        # Requirement change on resume: edited discovery reopens review; readiness fails closed.
        (topic / 'discovery.md').write_text(discovery + 'Switch to the official API.\n')
        gate = self.thinking_state(root, 'gate', slug, '--require', 'discovery,spec,handoff')
        self.assertNotEqual(gate.returncode, 0)
        self.assertIn('discovery changed since operator review', gate.stdout + gate.stderr)
        again = self.run_helper('job_acceptance_cli.py', 'validate-final', job_id, final)
        self.assertEqual(again.returncode, 1, again.stdout + again.stderr)
        overview = self.ok(self.run_helper('job_cli.py', 'overview', job_id))
        self.assertNotEqual(next(s for s in overview['stages'] if s['id'] == 'handoff')['status'], 'accepted-at-snapshot')

    def test_thinking_cold_read_repair_rerenders_and_revalidates_the_handoff_without_a_factual_slot(self):
        root, slug = self.base / 'thinking', 'cold-handoff'
        topic = root / slug
        self.assertEqual(self.thinking_state(root, 'init', slug, '--output-type', 'implementation').returncode, 0)
        discovery = '# Discovery\n\nRetries must never double-charge.\n'
        (topic / 'discovery.md').write_text(discovery)
        (topic / 'spec.md').write_text('# Spec\n\n[REQ-RETRY] Retry a timed-out charge once.\n')
        author_caps = json.loads(self.capabilities.read_text())
        author_caps.update(inheritedProviderInstanceId='antigravity',
                           inheritedModel='gemini-3.8-flash-high', parentThreadId='synthetic-thinking-author')
        author_caps_path = self.base / 'thinking-author-capabilities.json'
        author_caps_path.write_text(json.dumps(author_caps))
        for name in ('discovery.md', 'spec.md'):
            recorded = self.thinking_state(root, 'author', slug, name, '--capabilities', str(author_caps_path))
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        self.assertEqual(self.thinking_state(root, 'review', slug, '--decision', 'accepted', '--scope', 'finalise-brief',
                                             '--discovery-sha256', sha(discovery.encode()), '--evidence-ref', 'msg:1',
                                             '--operator-statement-file',
                                             self.write_statement(topic, 'I accept this discovery.')).returncode, 0)
        def render():
            self.review_plan(root, slug)
            self.assertEqual(subprocess.run(
                [sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root), '--capabilities', str(self.capabilities)],
                capture_output=True, text=True, env=self.env).returncode, 0)
        render()
        handoff = topic / 'handoff.md'
        job_id, workflow = 'thinking-cold-handoff', 'elephant-goldfish/thinking'
        caller = self.caller(workflow)
        contract = {'root': str(root), 'slug': slug, 'mode': 'handoff'}
        cold_contract = {**contract, 'mode': 'cold-read', 'document_path': str(handoff),
                         'document_sha256': sha(handoff.read_bytes())}
        subject = {'path': str(handoff), 'sha256': sha(handoff.read_bytes())}
        self.create(self.base_job(job_id, workflow, {'R-HANDOFF': 'reviewed, provenance-checked handoff',
                                                     'R-COLD': 'a fresh reader finds no blocking gap'},
                                  [{'id': 'handoff', 'depends_on': [], 'requirements': ['R-HANDOFF'], 'status': 'pending',
                                    'execution_mode': 'direct', 'validator_dependency': 'eg', 'revision': 'handoff-r1',
                                    'validator_contract': contract},
                                   {'id': 'cold-read', 'depends_on': ['handoff'], 'requirements': ['R-COLD'],
                                    'status': 'pending', 'validator_dependency': 'eg', 'validator_contract': cold_contract}],
                                  [{'task_id': 'c0', 'stage_id': 'cold-read', 'logical_slot_id': 'cold-read',
                                    'request_id': 'req-c0', 'worker_id': 'elephant-goldfish/cold-reader',
                                    'dependency_key': 'eg', 'context_policy': 'document-only', 'role': 'review',
                                    'document': subject, 'reviewed_documents': [dict(subject)],
                                    'write_scope': {'mode': 'coordinator-only'}}]))
        descriptor = self.publish(job_id, caller, 'handoff', contract)
        self.ok(self.accept(job_id, caller, 'handoff', self.doc_argv(root, slug, 'handoff'), descriptor, 'handoff-r1'))
        gap = [{'id': 'GAP-1', 'severity': 'blocker', 'scenario': 'A newcomer cannot tell what "once" bounds.',
                'source_evidence': 'quoted: "Retry a timed-out charge once."'}]
        self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed', requirement='failed',
                      findings=gap, conclusion='VERDICT: NOT READY')
        # Repair through the spec, re-render, and revalidate the handoff stage (no factual slot exists).
        (topic / 'spec.md').write_text('# Spec\n\n[REQ-RETRY] Retry a timed-out charge exactly once per request ID.\n')
        repaired_source = self.thinking_state(root, 'author', slug, 'spec.md', '--capabilities', str(self.capabilities))
        self.assertEqual(repaired_source.returncode, 0, repaired_source.stdout + repaired_source.stderr)
        render()
        self.assertEqual(self.thinking_state(root, 'gate', slug, '--require', 'discovery,spec,handoff').returncode, 0)
        # The old handoff receipt no longer matches the re-rendered bytes; a fresh direct pass accepts them.
        stale = self.run_helper('job_acceptance_cli.py', 'validate', job_id, {'caller': caller, 'stage_id': 'handoff'})
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        descriptor = self.publish(job_id, caller, 'handoff', contract)
        self.ok(self.accept(job_id, caller, 'handoff', self.doc_argv(root, slug, 'handoff'), descriptor, 'handoff-r1'))
        new_sha = sha(handoff.read_bytes())
        record = self.ok(self.run_helper('job_cli.py', 'document-revision', job_id, {
            'caller': caller, 'task_id': 'c0', 'reason': 'spec repaired', 'document': {'path': str(handoff), 'sha256': new_sha}},
            capabilities=self.capabilities))
        self.assertEqual(record['stale_stages'], ['cold-read'])
        state = self.job_state(job_id)
        self.assertEqual(state['decisions'], [])
        self.assertEqual(next(s for s in state['stages'] if s['id'] == 'handoff')['status'], 'accepted-at-snapshot')
        self.ok(self.run_helper('job_cli.py', 'retry', job_id, {'caller': caller, 'task_id': 'c0', 'reason': 'NOT READY'}))
        brief, raw = self.dispatch(job_id, caller, 'c0', verdict='approve', conclusion='VERDICT: READY')
        self.assertEqual(brief['document']['sha256'], new_sha)
        self.assertNotIn('GAP-1', raw.decode())
        self.assertEqual(next(s for s in self.job_state(job_id)['stages'] if s['id'] == 'cold-read')['cycle'], 1)



if __name__ == '__main__':
    unittest.main()
