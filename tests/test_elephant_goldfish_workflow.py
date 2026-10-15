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
import shutil
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
        self.capabilities = self.base / 'capabilities.json'
        caps = json.loads((ROOT / 'tests/fixtures/t3/capabilities.json').read_text())
        self.capabilities.write_text(json.dumps(caps))

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
        # Every newly created fixture goes through job_cli's observed-identity
        # policy. Dispatch fixtures add synthetic status observations in dispatch().
        self.assertEqual(self.job_state(job['job_id'])['policy']['identity'], 'observed')

    def job_state(self, job_id):
        return json.loads((self.state / job_id / 'job.json').read_text())

    def base_job(self, job_id, workflow, requirements, stages, tasks, policy=None):
        for task in tasks:
            task.setdefault('target', {'providerInstanceId': 'codex',
                                       'model': 'gpt-6.1-sol', 'lineage': 'openai'})
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
                 requirement='passed', findings=(), conclusion='checked', report_identity=True):
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
        target = next(t for t in self.job_state(job_id)['tasks'] if t['task_id'] == task_id)['target']
        if report_identity:
            event['status_identity'] = {'providerInstanceId': target['providerInstanceId'], 'model': target['model']}
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
        render = subprocess.run([sys.executable, str(self.scripts / 'render_handoff.py'), slug, '--root', str(root), '--capabilities', str(self.capabilities)],
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
        render = lambda: self.assertEqual(subprocess.run(
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


class ElephantDocumentJobTests(InstalledJobFixture):
    """G-EG-SEPARATION, cold-reader isolation and coordinator-owned repair rounds."""

    WORKFLOW = 'elephant-goldfish/elephant'

    def document(self, text='# Problem\nFlaky deploys.\n\n# Technical plan\nRun `make test` in `ci/`.\n'):
        repo = self.base / 'docs' / 'repo'
        repo.mkdir(parents=True, exist_ok=True)
        path = repo / 'elephant.md'
        path.write_text(text)
        caps = json.loads((ROOT / 'tests/fixtures/t3/capabilities.json').read_text())
        caps.update(inheritedProviderInstanceId='antigravity', inheritedModel='gemini-3.8-flash-high')
        caps['parentThreadId'] = 'synthetic-elephant-author'
        cap_path = self.base / 'elephant-author-capabilities.json'
        cap_path.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(path), '--capabilities', str(cap_path)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        return path

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

    def _assert_later_record_keeps_sidecar_authors(self, recreate_draft):
        document = self.document()
        draft = document.parent / 'draft.md'
        draft.write_bytes(document.read_bytes() + b'B edited this copy.\n')
        caps = json.loads(self.capabilities.read_text())
        caps.update(inheritedProviderInstanceId='codex', inheritedModel='gpt-6.1-sol',
                    parentThreadId='synthetic-p6-editor')
        editor_caps = self.base / 'p6-editor-caps.json'; editor_caps.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(draft), '--capabilities', str(editor_caps)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        if recreate_draft:
            os.replace(draft, document)
            shutil.copyfile(document, draft)
        else:
            shutil.copyfile(draft, document)
        document.write_bytes(document.read_bytes() + b'C edited in place.\n')
        caps.update(inheritedProviderInstanceId='claudeAgent', inheritedModel='claude-opus-5-5',
                    parentThreadId='synthetic-p6-third-author')
        third_caps = self.base / 'p6-third-caps.json'; third_caps.write_text(json.dumps(caps))
        recorded = subprocess.run([sys.executable, str(PLUGIN / 'scripts/record_document_author.py'),
                                   str(document), '--capabilities', str(third_caps)], capture_output=True,
                                  text=True, env=self.env)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        current_hash = sha(document.read_bytes())
        sidecar = json.loads((document.parent / 'document-authors.json').read_text())
        self.assertEqual({row['lineage'] for row in sidecar[current_hash]['authors']},
                         {'google', 'openai', 'anthropic'})
        job_id = 'copy-kept-draft' if not recreate_draft else 'recreated-draft'
        job = self.elephant_job(job_id, document, factual=False)
        job['tasks'][0]['target'] = {'providerInstanceId': 'codex', 'model': 'gpt-6.1-sol', 'lineage': 'openai'}
        self.create(job)
        refused = self.run_helper('job_cli.py', 'prepare', job_id,
                                  {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('differ from every document author', refused.stderr)

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

    def contract(self, document, mode, digest=None):
        return {'root': str(document.parent.parent), 'slug': document.parent.name, 'mode': mode,
                'document_path': str(document), 'document_sha256': digest or sha(document.read_bytes())}

    def cold_slot(self, document, task_id='c0', role=None, digest=None):
        subject = {'path': str(document), 'sha256': digest or sha(document.read_bytes())}
        slot = {'task_id': task_id, 'stage_id': 'cold-read', 'logical_slot_id': 'cold-read', 'request_id': 'req-' + task_id,
                'worker_id': 'elephant-goldfish/cold-reader', 'dependency_key': 'eg', 'context_policy': 'document-only',
                'document': subject, 'write_scope': {'mode': 'coordinator-only'}, 'independent_of_author': True}
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
                          'write_scope': {'mode': 'coordinator-only'}, 'independent_of_author': True})
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
            'document': {'path': str(document), 'sha256': digest or sha(document.read_bytes())}},
            capabilities=self.capabilities)

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
