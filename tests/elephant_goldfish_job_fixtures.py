"""Shared installed fixtures for bounded Elephant Goldfish test modules."""
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
from tests.thinking_plan_review_fixtures import ThinkingPlanFixture, init_selection_args

PLUGIN = ROOT / 'plugins' / 'elephant-goldfish'
OPERATIONS = ['doctor', 'thinking', 'elephant', 'check']
WORKERS = {'elephant-goldfish/factual-checker', 'elephant-goldfish/cold-reader', 'elephant-goldfish/plan-reviewer'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def words(path: Path) -> int:
    return len(path.read_text().split())


def section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split('\n## ', 1)[0]


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
        caps['inheritedOptions'] = {}  # Explicit synthetic host observation, not inferred production settings.
        self.capabilities.write_text(json.dumps(caps))
        self.plan_fixture = ThinkingPlanFixture(self.base / 'plan-fixture')
        self.plan_fixture.box.env = dict(self.env)

    # -- installed helpers -------------------------------------------------
    def caller(self, workflow):
        return {'installation_id': self.install['installation_id'], 'workflow': workflow,
                'package_digest': self.install['package_digest'], 'actor': 'coordinator'}

    def run_helper(self, tool, command, job_id, data=None, **flags):
        if command == 'create' and data is not None:
            from tests.model_selection_fixtures import attach_selection
            active = json.loads(self.capabilities.read_text())
            attach_selection(data, {'providerInstanceId': active['inheritedProviderInstanceId'], 'model': active['inheritedModel']})
        if command == 'plan-revision' and data is not None:
            from tests.model_selection_fixtures import attach_revision
            attach_revision(data, self.job_state(job_id))
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
        if args[0] == 'init':
            args = (*args, *init_selection_args(self.base, args[1]))
        return subprocess.run([sys.executable, str(self.scripts / 'thinking_state.py'), '--root', str(root), *args],
                              capture_output=True, text=True, env=self.env)

    def review_plan(self, root, slug):
        self.plan_fixture.approve(self.scripts, root, slug)

    def create(self, job):
        self.ok(self.run_helper('job_cli.py', 'create', job['job_id'], job, prefix=self.prefix,
                                agents_root=self.agents, config=self.base / 'config' / 'workers.json'))
        # Every newly created fixture goes through job_cli's observed-identity
        # policy. Dispatch fixtures add synthetic status observations in dispatch().
        self.assertEqual(self.job_state(job['job_id'])['policy']['identity'], 'observed')

    def job_state(self, job_id):
        return json.loads((self.state / job_id / 'job.json').read_text())

    def choose_direct_work(self, job_id, caller, capabilities, stage_id):
        """An explicit fixture model answer, separate from the lineage waiver."""
        from tests.model_selection_fixtures import attach_selection
        state = self.job_state(job_id)
        candidate = copy.deepcopy(state)
        candidate.pop('model_selection', None)
        attach_selection(candidate, {'providerInstanceId': capabilities['inheritedProviderInstanceId'],
                                     'model': capabilities['inheritedModel']})
        label = 'choose-direct-' + str(self.counter)
        source = self.base / (label + '.txt')
        quote = ('Fixture owner chooses current-context work for ' + stage_id + ': ' +
                 capabilities['inheritedProviderInstanceId'] + '/' + capabilities['inheritedModel'] +
                 ', accepting actual or unreported session settings.')
        source.write_text(quote)
        decision = {'id': label, 'scope': 'plan:' + label, 'quote': quote, 'source': str(source),
                    'source_sha256': sha(source.read_bytes())}
        self.ok(self.run_helper('job_cli.py', 'decision', job_id, {'caller': caller, 'decision': decision}))
        plan = {name: candidate[name] for name in ('tasks', 'stages', 'model_selection', 'model_selection_sha256')}
        self.ok(self.run_helper('job_cli.py', 'plan-revision', job_id, {'caller': caller, 'new_plan': plan,
                                'revision': {'id': label, 'owner_decision_id': label}}))

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
        if task_id == 'c0':
            from tests.adopter_plan_review_fixtures import ensure_legacy_elephant_design
            ensure_legacy_elephant_design(self,job_id)
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
            event['status_identity'] = {'providerInstanceId': target['providerInstanceId'], 'model': target['model'],
                                        'options': target.get('options', {})}
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



class ElephantDocumentJobFixture(InstalledJobFixture):
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
                       'validator_contract': self.contract(document, 'cold-read', digest),
                       'resources':{'adopter_design_file':str(self.base/(job_id+'-design.json'))}})
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


    REFUTED = [{'id': 'CLAIM-C1', 'severity': 'major', 'scenario': 'The plan says `make test` runs in `ci/`; a newcomer gets "No rule to make target".',
                'source_evidence': 'ci/Makefile:1-12 declares no test target'}]


    def revise(self, job_id, caller, document, task_id='c0', digest=None):
        return self.run_helper('job_cli.py', 'document-revision', job_id, {
            'caller': caller, 'task_id': task_id, 'reason': 'coordinator repaired NOT READY gaps',
            'document': {'path': str(document), 'sha256': digest or sha(document.read_bytes())}},
            capabilities=self.capabilities)


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
                self.assertTrue(all(d['scope'].startswith('plan:design-') for d in self.job_state(job_id)['decisions']))
                return executed
            self.assertEqual(json.loads(revised.stdout)['rounds_performed'], executed)
            self.ok(self.run_helper('job_cli.py', 'retry', job_id, {'caller': caller, 'task_id': 'c0', 'reason': 'NOT READY'}))
            self.assertLess(executed, 25, 'cold-read budget was not enforced')


    def refused_review(self, job_id, job, needle):
        self.create(job)
        proc = self.run_helper('job_cli.py', 'prepare', job_id, {'caller': self.caller(self.WORKFLOW), 'task_id': 'c0'})
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn(needle, proc.stderr)
        briefs = self.state / job_id / 'briefs'
        self.assertFalse(briefs.exists() and any(briefs.iterdir()))
