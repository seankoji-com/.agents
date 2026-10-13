"""Stage 4 elephant-goldfish coordinator adapter: routing, boundaries and synthetic jobs.

Every job here runs through an isolated installed package: the pinned
`shared/job_cli.py`, `shared/job_acceptance_cli.py`, `scripts/thinking_state.py`,
`scripts/render_handoff.py` and `scripts/validate_document.py`. Worker results are
synthetic JSON; no model is called and GitHub is never touched.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.store import canonical  # noqa: E402

PLUGIN = ROOT / 'plugins' / 'elephant-goldfish'
OPERATIONS = ['doctor', 'thinking', 'elephant', 'check']
WORKERS = {'elephant-goldfish/factual-checker', 'elephant-goldfish/cold-reader'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def words(path: Path) -> int:
    return len(path.read_text().split())


def section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split('\n## ', 1)[0]


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
        self.assertIn('You run steps 1 to 6 yourself', runs)
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
        self.assertIn('Four rounds in total', limits)
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


class InstalledJobFixture(unittest.TestCase):
    """One isolated installation per class; each test owns its own job state."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='eg-workflow-')
        cls.addClassCleanup(cls._tmp.cleanup)
        base = Path(cls._tmp.name)
        (base / 'home').mkdir()
        cls.env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_CONFIG_HOME': str(base / 'config'),
                   'XDG_STATE_HOME': str(base / 'xdg')}
        cls.prefix, cls.agents = base / 'prefix', base / 'agents'
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'elephant-goldfish',
                               '--prefix', str(cls.prefix), '--agents-root', str(cls.agents)],
                              capture_output=True, text=True, env=cls.env)
        if proc.returncode:
            raise AssertionError(proc.stdout + proc.stderr)
        cls.version = Path(json.loads(proc.stdout)['data']['version_dir'])
        cls.install = json.loads((cls.version / 'install-manifest.json').read_text())
        cls.scripts = cls.version / 'scripts'
        cls.validator = cls.scripts / 'validate_document.py'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='eg-job-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.state = self.base / 'jobs'
        self.counter = 0

    # -- installed helpers -------------------------------------------------
    def caller(self, workflow):
        return {'installation_id': self.install['installation_id'], 'workflow': workflow,
                'package_digest': self.install['package_digest'], 'actor': 'coordinator'}

    def run_helper(self, tool, command, job_id, data=None, **flags):
        argv = [sys.executable, str(self.version / 'shared' / tool), command,
                '--state-root', str(self.state), '--job', job_id]
        if data is not None:
            self.counter += 1
            path = self.base / f'input-{self.counter}.json'
            path.write_text(json.dumps(data))
            argv += ['--input', str(path)]
        for key, value in flags.items():
            argv += [f'--{key.replace("_", "-")}', str(value)]
        return subprocess.run(argv, capture_output=True, text=True, env=self.env)

    def ok(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def thinking_state(self, root, *args):
        return subprocess.run([sys.executable, str(self.scripts / 'thinking_state.py'), '--root', str(root), *args],
                              capture_output=True, text=True, env=self.env)

    def create(self, job):
        self.ok(self.run_helper('job_cli.py', 'create', job['job_id'], job, prefix=self.prefix,
                                agents_root=self.agents, config=self.base / 'config' / 'workers.json'))

    def job_state(self, job_id):
        return json.loads((self.state / job_id / 'job.json').read_text())

    def base_job(self, job_id, workflow, requirements, stages, tasks, policy=None):
        job = {'schema_version': 1, 'job_id': job_id, 'installation_id': self.install['installation_id'],
               'workflow': workflow, 'owner': {'id': 'owner'},
               'objective': 'PRIVATE-OBJECTIVE-MARKER plan the retry rollout',
               'requirements': requirements, 'authorization': {'actions': ['read']},
               'constraints': ['offline synthetic fixture'], 'dependencies': [{'key': 'eg', 'plugin': 'elephant-goldfish'}],
               'pins': {}, 'result_contract': {'schema_version': 1}, 'stages': stages, 'tasks': tasks,
               'decisions': [], 'history': [], 'metrics': {}}
        if policy is not None:
            job['policy'] = policy
        return job

    # -- synthetic worker lifecycle -----------------------------------------
    def dispatch(self, job_id, caller, task_id, *, verdict=None, status='ready-for-acceptance',
                 requirement='passed', findings=(), conclusion='checked'):
        """prepare -> accepted handle -> ingested result -> terminal observation."""
        ref = self.ok(self.run_helper('job_cli.py', 'prepare', job_id, {'caller': caller, 'task_id': task_id}))
        self.assertEqual(set(ref), {'path', 'sha256', 'bytes', 'provenance'})
        raw = Path(ref['path']).read_bytes()
        self.assertEqual(sha(raw), ref['sha256'])
        brief = json.loads(raw)
        host = f'host-{brief["request_id"]}'
        event = {'kind': 'accepted', 'request_id': brief['request_id'], 'host_task_id': host,
                 'child_thread_id': 'child-' + host, 'status': 'running', 'work_state': 'working',
                 'has_pending_child_runs': False}
        self.ok(self.run_helper('job_cli.py', 'task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': event}))
        result = {'schema_version': 1, 'status': status, 'conclusion': conclusion,
                  'requirements': [{'id': r['id'], 'status': requirement, 'evidence': ['synthetic fixture evidence']}
                                   for r in brief['requirements']],
                  'review_verdict': verdict, 'findings': list(findings), 'gaps': [], 'uncertainties': [], 'changes': [],
                  'commands': [], 'artifacts': [], 'binding': brief['snapshot'], 'extra_work_requests': [], 'metrics': {},
                  **{k: brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id',
                                           'effective_brief_sha256', 'revision')}}
        self.ok(self.run_helper('job_cli.py', 'result', job_id, {
            'caller': caller, 'task_id': task_id, 'request_id': brief['request_id'], 'completion_id': host + '-done',
            'result': {'json': json.dumps(result)}}))
        event.update(kind='completion', status='completed', work_state='result_available', completion_id=host + '-done')
        self.ok(self.run_helper('job_cli.py', 'task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': event}))
        return brief, raw

    def observation_row(self, kind, content):
        return {'observer': 'coordinator', 'kind': kind, 'source': 'synthetic host task', 'content': content,
                'sha256': sha(canonical(content))}

    def factual_observation(self, document, outcome='confirmed'):
        digest = sha(document.read_bytes())
        content = {'document_sha256': digest, 'claim_id': 'C1', 'outcome': outcome}
        return {'kind': 'factual-observation', 'document_path': str(document), 'document_sha256': digest,
                'claims': [{'claim_id': 'C1', 'outcome': outcome, 'evidence': [self.observation_row('factual-claim', content)]}]}

    def cold_observation(self, document, verdict='ready'):
        digest = sha(document.read_bytes())
        content = {'document_sha256': digest, 'verdict': verdict}
        return {'kind': 'cold-read-observation', 'document_path': str(document), 'document_sha256': digest,
                'verdict': verdict, 'evidence': [self.observation_row('cold-read', content)]}

    def publish(self, job_id, caller, stage_id, data):
        path = self.base / f'observation-{stage_id}-{self.counter}.json'
        self.counter += 1
        path.write_text(json.dumps(data))
        return self.ok(self.run_helper('job_cli.py', 'observation', job_id,
                                       {'caller': caller, 'stage_id': stage_id, 'input_file': str(path)}))['path']

    def accept(self, job_id, caller, stage_id, argv, input_file, revision=None):
        return self.run_helper('job_acceptance_cli.py', 'accept-stage', job_id, {
            'caller': caller, 'stage_id': stage_id, 'validator_argv': argv, 'input_file': input_file, 'revision': revision})

    def doc_argv(self, root, slug, mode, input_file=None):
        argv = [str(self.validator), '--root', str(root), '--slug', slug, '--mode', mode]
        return argv + ['--input', input_file] if input_file else argv


class ThinkingHandoffJobTests(InstalledJobFixture):
    """G-EG-DISCOVERY / G-EG-HANDOFF through the installed gate, renderer and job."""

    def write_statement(self, topic, text):
        path = topic / 'review-statement.txt'
        path.write_text(text)
        return str(path)

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
        render = subprocess.run([sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(render.returncode, 0, render.stdout + render.stderr)
        # The cold-read budget is recorded in the topic and changes neither phase nor authority.
        budget = self.thinking_state(root, 'set', slug, 'cold_read.max_rounds=4', 'cold_read.rounds_performed=0',
                                     'cold_read.limit_source=new-topic-default')
        state = json.loads(budget.stdout)
        self.assertEqual(state['meta']['cold_read'], {'max_rounds': 4, 'rounds_performed': 0,
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
        self.assertEqual(self.thinking_state(root, 'review', slug, '--decision', 'accepted', '--scope', 'finalise-brief',
                                             '--discovery-sha256', sha(discovery.encode()), '--evidence-ref', 'msg:1',
                                             '--operator-statement-file',
                                             self.write_statement(topic, 'I accept this discovery.')).returncode, 0)
        render = lambda: self.assertEqual(subprocess.run(
            [sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root)],
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
        render()
        self.assertEqual(self.thinking_state(root, 'gate', slug, '--require', 'discovery,spec,handoff').returncode, 0)
        # The old handoff receipt no longer matches the re-rendered bytes; a fresh direct pass accepts them.
        stale = self.run_helper('job_acceptance_cli.py', 'validate', job_id, {'caller': caller, 'stage_id': 'handoff'})
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        descriptor = self.publish(job_id, caller, 'handoff', contract)
        self.ok(self.accept(job_id, caller, 'handoff', self.doc_argv(root, slug, 'handoff'), descriptor, 'handoff-r1'))
        new_sha = sha(handoff.read_bytes())
        record = self.ok(self.run_helper('job_cli.py', 'document-revision', job_id, {
            'caller': caller, 'task_id': 'c0', 'reason': 'spec repaired', 'document': {'path': str(handoff), 'sha256': new_sha}}))
        self.assertEqual(record['stale_stages'], ['cold-read'])
        state = self.job_state(job_id)
        self.assertEqual(state['decisions'], [])
        self.assertEqual(next(s for s in state['stages'] if s['id'] == 'handoff')['status'], 'accepted-at-snapshot')
        self.ok(self.run_helper('job_cli.py', 'retry', job_id, {'caller': caller, 'task_id': 'c0', 'reason': 'NOT READY'}))
        brief, raw = self.dispatch(job_id, caller, 'c0', verdict='approve', conclusion='VERDICT: READY')
        self.assertEqual(brief['document']['sha256'], new_sha)
        self.assertNotIn('GAP-1', raw.decode())
        self.assertEqual(next(s for s in self.job_state(job_id)['stages'] if s['id'] == 'cold-read')['cycle'], 1)


class ElephantDocumentJobTests(InstalledJobFixture):
    """G-EG-SEPARATION, cold-reader isolation and coordinator-owned repair rounds."""

    WORKFLOW = 'elephant-goldfish/elephant'

    def document(self, text='# Problem\nFlaky deploys.\n\n# Technical plan\nRun `make test` in `ci/`.\n'):
        repo = self.base / 'docs' / 'repo'
        repo.mkdir(parents=True, exist_ok=True)
        path = repo / 'elephant.md'
        path.write_text(text)
        return path

    def contract(self, document, mode, digest=None):
        return {'root': str(document.parent.parent), 'slug': document.parent.name, 'mode': mode,
                'document_path': str(document), 'document_sha256': digest or sha(document.read_bytes())}

    def cold_slot(self, document, task_id='c0', role=None, digest=None):
        subject = {'path': str(document), 'sha256': digest or sha(document.read_bytes())}
        slot = {'task_id': task_id, 'stage_id': 'cold-read', 'logical_slot_id': 'cold-read', 'request_id': 'req-' + task_id,
                'worker_id': 'elephant-goldfish/cold-reader', 'dependency_key': 'eg', 'context_policy': 'document-only',
                'document': subject, 'write_scope': {'mode': 'coordinator-only'}}
        if role:
            # A cold reader reviews a document, not a worker task: the document-subject review form.
            slot.update(role=role, reviewed_documents=[dict(subject)])
        return slot

    def elephant_job(self, job_id, document, *, cold_role=None, factual=True, policy=None, digest=None):
        stages, tasks, requirements = [], [], {}
        if factual:
            requirements['R-FACT'] = 'PRIVATE-REQUIREMENT-MARKER every cited claim is confirmed'
            stages.append({'id': 'factual', 'depends_on': [], 'requirements': ['R-FACT'], 'status': 'pending',
                           'validator_dependency': 'eg', 'revision': 'doc-r1',
                           'validator_contract': self.contract(document, 'factual')})
            tasks.append({'task_id': 'f0', 'stage_id': 'factual', 'logical_slot_id': 'factual', 'request_id': 'req-f0',
                          'worker_id': 'elephant-goldfish/factual-checker', 'dependency_key': 'eg',
                          'write_scope': {'mode': 'coordinator-only'}})
        requirements['R-COLD'] = 'a fresh reader finds no blocking gap'
        stages.append({'id': 'cold-read', 'depends_on': ['factual'] if factual else [], 'requirements': ['R-COLD'],
                       'status': 'pending', 'validator_dependency': 'eg',
                       'validator_contract': self.contract(document, 'cold-read', digest)})
        tasks.append(self.cold_slot(document, role=cold_role, digest=digest))
        return self.base_job(job_id, self.WORKFLOW, requirements, stages, tasks, policy)

    def accept_factual(self, job_id, caller, document, revision='doc-r1'):
        brief, _ = self.dispatch(job_id, caller, 'f0', conclusion='FACT-FINDING-MARKER claim C1 confirmed at ci/Makefile:3')
        path = self.publish(job_id, caller, 'factual', self.factual_observation(document))
        argv = self.doc_argv(document.parent.parent, document.parent.name, 'factual', path)
        self.ok(self.accept(job_id, caller, 'factual', argv, path, revision))
        return argv, path

    NOT_READY = [{'id': 'GAP-1', 'severity': 'blocker', 'scenario': 'A newcomer cannot tell which branch to deploy.',
                  'source_evidence': 'quoted: "Run `make test` in `ci/`."'}]

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
        self.assertIn('Assess only the supplied document', json.dumps(brief['effective_definition']))
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

    REFUTED = [{'id': 'CLAIM-C1', 'severity': 'major', 'scenario': 'The plan says `make test` runs in `ci/`; a newcomer gets "No rule to make target".',
                'source_evidence': 'ci/Makefile:1-12 declares no test target'}]

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

    def revise(self, job_id, caller, document, task_id='c0', digest=None):
        return self.run_helper('job_cli.py', 'document-revision', job_id, {
            'caller': caller, 'task_id': task_id, 'reason': 'coordinator repaired NOT READY gaps',
            'document': {'path': str(document), 'sha256': digest or sha(document.read_bytes())}})

    def test_repair_round_rebinds_the_document_within_the_round_budget_without_an_owner_decision(self):
        document = self.document()
        job_id, caller = 'elephant-repair', self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document))
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
        self.assertIn('undeclared_expansion', undeclared.stderr)
        # A declared repair needs the current bytes and a changed hash, but no owner decision.
        for wrong in (old_sha, 'f' * 64):
            refused = self.revise(job_id, caller, document, digest=wrong)
            self.assertEqual(refused.returncode, 2, refused.stdout)
        record = self.ok(self.revise(job_id, caller, document))
        self.assertEqual((record['previous_sha256'], record['sha256']), (old_sha, new_sha))
        self.assertEqual((record['rounds_performed'], record['max_rounds']), (1, 4))
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

    def rounds(self, job_id, policy=None):
        """Run NOT READY rounds with declared repairs until the persisted budget refuses one."""
        document = self.document()
        caller = self.caller(self.WORKFLOW)
        self.create(self.elephant_job(job_id, document, factual=False, policy=policy))
        executed = 0
        while True:
            self.dispatch(job_id, caller, 'c0', verdict='adverse', status='failed', requirement='failed',
                          findings=self.NOT_READY, conclusion='VERDICT: NOT READY')
            executed += 1
            document.write_text(document.read_text() + f'\nRepair {executed}.\n')
            revised = self.revise(job_id, caller, document)
            if revised.returncode:
                self.assertIn('attempt_budget_exhausted', revised.stderr)
                self.assertIn('owner_decision_required', revised.stderr)
                retry = self.run_helper('job_cli.py', 'retry', job_id, {'caller': caller, 'task_id': 'c0', 'reason': 'NOT READY'})
                self.assertIn('budget exhausted', retry.stderr)
                # Resume cannot reset the count: a fresh preparation is refused as well.
                again = self.run_helper('job_cli.py', 'prepare', job_id, {'caller': caller, 'task_id': 'c0'})
                self.assertNotEqual(again.returncode, 0)
                self.assertEqual(self.job_state(job_id)['decisions'], [])
                return executed
            self.assertEqual(json.loads(revised.stdout)['rounds_performed'], executed)
            self.ok(self.run_helper('job_cli.py', 'retry', job_id, {'caller': caller, 'task_id': 'c0', 'reason': 'NOT READY'}))
            self.assertLess(executed, 10, 'cold-read budget was not enforced')

    def test_new_documents_get_four_rounds_and_legacy_loops_keep_their_remaining_five(self):
        # New topic: the default policy snapshot (initial read plus three repairs).
        self.assertEqual(self.rounds('rounds-new'), 4)
        self.assertEqual(self.job_state('rounds-new')['policy']['max_repair_cycles'], 3)
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

    def refused_review(self, job_id, job, needle):
        self.create(job)
        proc = self.run_helper('job_cli.py', 'prepare', job_id, {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn(needle, proc.stderr)
        briefs = self.state / job_id / 'briefs'
        self.assertFalse(briefs.exists() and any(briefs.iterdir()))

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
