"""agent-tuneup coordinator workflow: routing, boundaries, worker contracts and synthetic
end-to-end jobs through the installed job helpers and the pinned validate_audit.py.

Everything runs in temporary homes and state roots. No model is called and nothing
touches GitHub or the owner's provider settings.
"""
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

from support import source_entry

from support import skill_manifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.jobs.store import canonical  # noqa: E402
from tests.test_model_ids import MODEL_ID  # noqa: E402

PLUGIN = ROOT / 'plugins' / 'agent-tuneup'
OPERATIONS = ['tuneup']
WORKERS = ('agent-tuneup/config-researcher', 'agent-tuneup/config-verifier')
# Synthetic routing records; the coordinator's record, not proof of the model that ran.
RESEARCH_TARGET = {'providerInstanceId': 'fixture-a', 'model': 'fixture-model-a', 'lineage': 'lineage-a'}
VERIFY_TARGET = {'providerInstanceId': 'fixture-b', 'model': 'fixture-model-b', 'lineage': 'lineage-b'}
AUDIT_CRITERIA = {'operation': 'audit', 'findings_allowed': True, 'live_enforcement_required': False}
APPLY_CRITERIA = {'operation': 'apply', 'findings_allowed': True, 'live_enforcement_required': False}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def words(path):
    return len(path.read_text().split())


def folded(text):
    return ' '.join(text.split())


class Installed:
    """One isolated installation with its own home, prefix, agent root and state root."""

    def __init__(self, base):
        self.base = base
        self.home = base / 'home'
        self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(base / 'config'),
                    'XDG_STATE_HOME': str(base / 'xdg-state')}
        self.prefix, self.agents, self.state = base / 'prefix', base / 'agents', base / 'jobs'
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'agent-tuneup',
                               '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                              capture_output=True, text=True, env=self.env, timeout=60)
        if proc.returncode:
            raise AssertionError(proc.stdout + proc.stderr)
        self.pkg = Path(json.loads(proc.stdout)['data']['version_dir'])
        self.manifest = json.loads((self.pkg / 'install-manifest.json').read_text())
        self.validator = self.pkg / 'scripts' / 'validate_audit.py'

    def caller(self, workflow):
        return {'actor': 'coordinator', 'installation_id': self.manifest['installation_id'],
                'workflow': workflow, 'package_digest': self.manifest['package_digest']}

    def run(self, script, *args, check=True):
        proc = subprocess.run([sys.executable, str(self.pkg / script), *map(str, args)], capture_output=True,
                              text=True, env=self.env, cwd=self.base, timeout=60)
        if check and proc.returncode:
            raise AssertionError(f'{script} {args[:1]} exited {proc.returncode}: {proc.stdout}{proc.stderr}')
        return proc

    def payload(self, name, data):
        path = self.base / 'inputs' / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def job(self, command, job_id, data, check=True, **flags):
        if command == 'create':
            from tests.model_selection_fixtures import attach_selection
            attach_selection(data, {'providerInstanceId':'fixture-provider','model':'gpt-fixture'})
        extra = [f'--{k.replace("_", "-")}={v}' for k, v in flags.items()]
        proc = self.run('shared/job_cli.py', command, '--state-root', self.state, '--job', job_id,
                        '--input', self.payload(f'{job_id}-{command}-{len(os.listdir(self.base))}.json', data),
                        *extra, check=check)
        if command == 'create' and proc.returncode == 0:
            selected=data['model_selection']
            caps=dict(selected['capabilities'], parentThreadId='fixture-parent',
                inheritedProviderInstanceId=selected['coordinator']['providerInstanceId'],inheritedModel=selected['coordinator']['model'],
                inheritedOptions=selected['coordinator'].get('observed_options') or {})
            for stage in data['stages']:
                if stage.get('execution_mode')=='direct' and not any(t['stage_id']==stage['id'] for t in data['tasks']):
                    self.job('direct-execution',job_id,{'caller':self.caller(data['workflow']),'stage_id':stage['id']},
                             capabilities=self.payload('direct-capabilities.json',caps))
        return json.loads(proc.stdout) if proc.returncode == 0 else proc

    def accept(self, action, job_id, data):
        proc = self.run('shared/job_acceptance_cli.py', action, '--state-root', self.state, '--job', job_id,
                        '--input', self.payload(f'{job_id}-{action}-{len(os.listdir(self.base))}.json', data),
                        check=False)
        return proc


class RoutingAndBoundaryTest(unittest.TestCase):
    """Operation names, cheap-operation routing and stated boundaries survive the rebuild."""

    def setUp(self):
        self.entry = (source_entry(PLUGIN)).read_text()
        self.meta = skill_manifest(PLUGIN / 'plugin.json')

    def test_one_workflow_includes_every_stage_and_concrete_approval(self):
        self.assertEqual(self.meta['operations'], OPERATIONS)
        self.assertEqual(self.meta['default_operation'], 'tuneup')
        for stage in ('readiness', 'Inventory every provider', 'usage-frequency scan',
                      'prepare reviewed changes', 'private backup', 'If approved', 'verification'):
            self.assertIn(stage, self.entry)
        self.assertIn('Invocation alone does not approve unseen settings changes', folded(self.entry))
        self.assertIn('Do not offer audit, align, apply, scan or doctor as public', self.entry)
        self.assertIn('`python3 PKG/scripts/scan_perms.py --json`', self.entry)
        self.assertIn('`python3 PKG/scripts/audit.py --list-adapters`', self.entry)

    def test_entry_names_only_existing_files_and_every_playbook_and_reference(self):
        named = set(re.findall(r'`PKG/([\w./-]+)`', self.entry))
        self.assertIn('shared/job-coordination.md', named)
        self.assertIn('shared/t3-runtime.md', named)
        for name in named:
            if name == 'shared/job-coordination.md' and not (ROOT / name).exists():
                continue  # written by the shared Stage 4 implementer; integration makes it present
            self.assertTrue((PLUGIN / name).exists() or (ROOT / name).exists(), name)
        for folder in ('playbooks', 'references'):
            for path in (PLUGIN / folder).glob('*.md'):
                self.assertIn(f'{folder}/{path.name}', named | set(re.findall(r'`PKG/([\w./-]+)`', (
                    PLUGIN / 'playbooks/audit.md').read_text())))

    def test_cheap_operations_are_direct(self):
        text = folded(self.entry)
        self.assertIn('Check local readiness directly', text)
        self.assertIn('local usage-frequency scan', text)
        with tempfile.TemporaryDirectory() as td:
            inst = Installed(Path(td))
            doctor = inst.run('scripts/audit.py', '--list-adapters')
            self.assertIn('claude', doctor.stdout)
            scan = inst.run('scripts/scan_perms.py', '--json', check=False)
            self.assertIn(scan.returncode, (0, 1), scan.stderr)
            settings = inst.home / 'settings.json'
            for body, code in (('{"permissions":{"allow":["Read(./docs/**)"]}}', 0),
                               ('{"permissions":{"allow":["Bash"]}}', 1), ('{not json', 2)):
                settings.write_text(body)
                proc = inst.run('scripts/audit.py', '--provider', 'claude', '--settings', settings, check=False)
                self.assertEqual(proc.returncode, code, proc.stdout)
            # Direct operations leave no job state anywhere in the isolated roots.
            self.assertFalse(inst.state.exists())
            self.assertFalse((inst.base / 'xdg-state' / 'agents' / 'jobs').exists())

    def test_guarantees_and_boundaries_are_stated(self):
        text = folded(self.entry)
        for heading in ('Deterministic format checks.', 'Local usage scan.', 'Report first.',
                        'Authorized, backed-up settings edits only.', 'No permission expansion.',
                        'Distinct observations.'):
            self.assertIn(f'**{heading}**', text)
        self.assertIn('`doctor`, `scan`, `audit` and `align` write no settings', text)
        self.assertIn('Unknown enforcement stays `unverified`; it blocks acceptance only when the task requires live enforcement', text)
        self.assertIn('Never disable sandboxing or approvals', text)
        self.assertIn('An audit or alignment request is not permission to widen access', text)
        self.assertIn('Worker definitions grant no settings-edit, push, merge or message authority', text)
        self.assertIn('`PKG/scripts/validate_audit.py`', text)
        self.assertIn('correctly reported findings and exit `1` completes when the criteria allow findings', text)

    def test_owner_approvals_route_through_the_native_picker(self):
        text = folded(self.entry)
        self.assertIn('native question picker with the recommended option first', text)
        self.assertIn('`settings-change:<change-id>`', text)
        reference = folded((PLUGIN / 'references/job-plan.md').read_text())
        self.assertIn('Ask the owner through the native question picker', reference)
        self.assertIn('`approval-wait` task observation; it blocks acceptance until resolved', reference)
        runtime = (ROOT / 'shared/t3-runtime.md').read_text()
        self.assertIn("host's native question picker", runtime)

    def test_word_budgets(self):
        self.assertLess(words(source_entry(PLUGIN)), 1500)
        for path in (PLUGIN / 'agents').glob('*.md'):
            self.assertLess(words(path), 700, path.name)


class WorkerDefinitionTest(unittest.TestCase):
    """Definitions satisfy the worker contract and never grant settings-edit authority."""

    def test_definitions_satisfy_the_worker_contract(self):
        declared = {w['id']: w for w in skill_manifest(PLUGIN / 'plugin.json')['workers']}
        self.assertEqual(set(declared), set(WORKERS))
        for worker_id, row in declared.items():
            with self.subTest(worker=worker_id):
                text = (PLUGIN / row['path']).read_text()
                flat = folded(text)
                self.assertTrue(text.startswith(f'---\nworker_id: {worker_id}\n'))
                self.assertIsNone(MODEL_ID.search(text))
                for phrase in ('check its SHA-256 and byte count', 'return `blocked`',
                               'Do not dispatch child tasks', 'Do not accept your own work',
                               '`worker-result.schema.json` version 1', 'artifact envelope',
                               '`ready-for-acceptance`, `needs-followup`, `blocked` or `failed`',
                               '(`blocker`, `major`, `minor`, `note`)', 'never grants settings-edit',
                               '## Redaction', 'Never return secrets'):
                    self.assertIn(phrase, flat)
                self.assertNotRegex(flat.lower(), r'\b(may|can) (edit|write|apply) settings')

    def test_verifier_keeps_parse_load_and_enforcement_distinct(self):
        flat = folded((PLUGIN / 'agents/config-verifier.md').read_text())
        self.assertIn('Report three separate outcomes: parse, load and live enforcement', flat)
        self.assertIn('without one they stay `unverified`', flat)
        self.assertIn('Never apply, restore, edit, chmod or move settings', flat)
        self.assertIn('any blocker or major finding makes it `adverse`', flat)
        researcher = folded((PLUGIN / 'agents/config-researcher.md').read_text())
        self.assertIn('never run `align.py plan` or `align.py apply`', researcher)
        self.assertIn('Never recommend a broader permission because a tool is used often', researcher)

    def test_installed_registry_materializes_the_same_definitions(self):
        with tempfile.TemporaryDirectory() as td:
            inst = Installed(Path(td))
            for worker_id in WORKERS:
                name = worker_id.split('/', 1)[1]
                source = (PLUGIN / 'agents' / f'{name}.md').read_bytes()
                materialized = list(inst.agents.rglob(f'workers/{name}.md'))
                self.assertEqual(len(materialized), 1, materialized)
                self.assertEqual(materialized[0].read_bytes(), source)


class SyntheticJobTest(unittest.TestCase):
    """Whole jobs through the installed job_cli.py and the pinned validator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.inst = Installed(self.base)

    def plan(self, job_id, workflow, stages, tasks, actions=('read',)):
        return {'schema_version': 1, 'job_id': job_id, 'installation_id': self.inst.manifest['installation_id'],
                'workflow': workflow, 'owner': {'id': 'owner'}, 'objective': 'synthetic tuneup fixture',
                'requirements': {s['requirements'][0]: 'fixture requirement ' + s['id'] for s in stages},
                'authorization': {'actions': list(actions)}, 'constraints': ['never widen permissions'],
                'dependencies': [{'key': 'tuneup', 'plugin': 'agent-tuneup'}], 'pins': {},
                'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216}, 'stages': stages,
                'tasks': tasks, 'decisions': [], 'history': [], 'metrics': {}, 'result_contract': {'schema_version': 1}}

    @staticmethod
    def stage(stage_id, requirement, criteria, depends=(), mode='workers'):
        return {'id': stage_id, 'depends_on': list(depends), 'requirements': [requirement], 'status': 'pending',
                'execution_mode': mode, 'validator_dependency': 'tuneup', 'revision': stage_id + '-r1',
                'validator_contract': {'criteria': criteria}}

    @staticmethod
    def slot(task_id, stage_id, worker, target):
        return {'task_id': task_id, 'stage_id': stage_id, 'logical_slot_id': 'primary', 'request_id': task_id + '-r0',
                'worker_id': worker, 'dependency_key': 'tuneup', 'status': 'pending', 'attempt': 0, 'handles': [],
                'followups': [], 'dispatch_retries': 0, 'dispatch_history': [], 'target': target,
                'write_scope': {'mode': 'worker-evidence', 'path': f'artifacts/tasks/{task_id}'}}

    def create(self, job):
        out = self.inst.job('create', job['job_id'], job, prefix=self.inst.prefix, agents_root=self.inst.agents,
                            config=self.base / 'config/workers.json')
        self.assertTrue(Path(out['job']).is_file())
        return self.inst.caller(job['workflow'])

    def run_worker(self, job_id, caller, task_id, findings=(), verdict=None):
        """Coordinator path: prepare, record the host handle, wake on completion, ingest strictly."""
        prepared = self.inst.job('prepare', job_id, {'caller': caller, 'task_id': task_id,
                                                     'target_reason': 'lowest suitable configured tier'})
        self.assertEqual(set(prepared) & {'path', 'sha256', 'bytes'}, {'path', 'sha256', 'bytes'})
        raw = Path(prepared['path']).read_bytes()
        self.assertEqual((sha(raw), len(raw)), (prepared['sha256'], prepared['bytes']))
        from shared.compact_briefs import deserialize
        brief = deserialize(raw)
        declared = next(t for t in self.state(job_id)['tasks'] if t['task_id'] == task_id)
        self.assertEqual(brief['worker_id'], declared['worker_id'])
        host = 'host-' + task_id
        event = {'request_id': brief['request_id'], 'host_task_id': host, 'child_thread_id': 'child-' + host,
                 'has_pending_child_runs': False, 'status_identity':{k:brief['target'].get(k,{} if k=='options' else None) for k in ('providerInstanceId','model','options')}}
        self.inst.job('task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': {
            **event, 'kind': 'accepted', 'status': 'running', 'work_state': 'working'}})
        self.inst.job('task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': {
            **event, 'kind': 'completion', 'status': 'completed', 'work_state': 'result_available',
            'completion_id': host + '-done'}})
        result = {'schema_version': 1, 'status': 'ready-for-acceptance', 'conclusion': 'synthetic fixture result',
                  'requirements': [{'id': r['id'], 'status': 'passed', 'evidence': ['synthetic evidence']}
                                   for r in brief['requirements']],
                  'review_verdict': verdict, 'findings': list(findings), 'gaps': [], 'uncertainties': [],
                  'changes': [], 'commands': [], 'artifacts': [], 'binding': brief['snapshot'],
                  'extra_work_requests': [], 'metrics': {}}
        for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256',
                    'revision'):
            result[key] = brief[key]
        return self.inst.job('result', job_id, {'caller': caller, 'task_id': task_id,
                                                'request_id': brief['request_id'], 'completion_id': host + '-done',
                                                'result': {'json': json.dumps(result)}})

    def publish(self, job_id, caller, stage_id, data):
        state=self.state(job_id)
        if state['workflow'] in ('agent-tuneup/audit','agent-tuneup/align') and not any(stage_id in s['depends_on'] for s in state['stages']):
            from tests.adopter_plan_review_fixtures import review_existing_tuneup_report
            data={**data,'adopter_output':review_existing_tuneup_report(self.inst.pkg,self.inst.manifest,self.inst.env,
                self.inst.state,job_id,data,self.base)}
        source = self.base / 'coordinator' / f'{stage_id}-{sha(canonical(data))[:12]}.json'
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(data))
        return self.inst.job('observation', job_id, {'caller': caller, 'stage_id': stage_id,
                                                     'input_file': str(source)})['path']

    def accept(self, job_id, caller, stage_id, observed):
        return self.inst.accept('accept-stage', job_id, {
            'caller': caller, 'stage_id': stage_id, 'input_file': observed, 'revision': stage_id + '-r1',
            'validator_argv': [str(self.inst.validator), '--input', observed]})

    def test_audit_job_accepts_reported_findings_and_rejects_settings_changes(self):
        job = self.plan('tuneup-audit', 'agent-tuneup/audit',
                        [self.stage('inspect', 'R-FORMAT', AUDIT_CRITERIA, mode='direct'),
                         self.stage('semantics', 'R-SEMANTICS', AUDIT_CRITERIA, depends=['inspect'])],
                        [self.slot('research-1', 'semantics', WORKERS[0], RESEARCH_TARGET)])
        caller = self.create(job)
        settings = self.inst.home / '.claude' / 'settings.json'
        settings.parent.mkdir()
        settings.write_text('{"permissions":{"allow":["Bash","Bash"]}}')
        before = settings.read_bytes()
        audit = self.inst.run('scripts/audit.py', '--provider', 'claude', '--settings', settings, check=False)
        self.assertEqual(audit.returncode, 1, audit.stdout)
        receipt = json.loads(audit.stdout)
        findings = [{'code': f['code'], 'location': 'global:' + str(f.get('path', f.get('location', 'settings')))}
                    for f in receipt['findings']]
        self.assertTrue(findings)
        report = {'criteria': AUDIT_CRITERIA, 'audit_exit_code': 1, 'findings': findings, 'changes': []}

        # A report-only stage cannot record a settings change; refused before any pass is charged.
        smuggled = self.publish('tuneup-audit', caller, 'inspect', {**report, 'changes': [{'id': 'x'}]})
        refused = self.accept('tuneup-audit', caller, 'inspect', smuggled)
        self.assertNotEqual(refused.returncode, 0)
        direct = subprocess.run([str(self.inst.validator), '--input', smuggled], capture_output=True, text=True, env=self.inst.env)
        self.assertEqual(direct.returncode, 1)
        self.assertIn('report-only audit cannot accept settings changes', direct.stdout)

        accepted = self.accept('tuneup-audit', caller, 'inspect', self.publish('tuneup-audit', caller, 'inspect', report))
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)['outcomes']['audit-criteria']['status'], 'passed')

        finding = {'id': 'F1', 'severity': 'note', 'title': 'duplicate exact rule',
                   'scenario': 'two identical allow strings in one scope',
                   'source_evidence': ['provider docs, fixture version']}
        self.run_worker('tuneup-audit', caller, 'research-1', findings=[finding])
        self.assertEqual(self.state('tuneup-audit')['tasks'][0]['status'], 'awaiting-acceptance')
        # A terminal, ingested worker result is not acceptance: no coordinator observation, no gate.
        early = self.accept('tuneup-audit', caller, 'semantics', str(self.base / 'coordinator' / 'unpublished.json'))
        self.assertNotEqual(early.returncode, 0)
        self.assertIn('published coordinator observation', early.stderr)
        self.assertNotEqual(self.state('tuneup-audit')['stages'][1]['status'], 'accepted-at-snapshot')
        observed = self.publish('tuneup-audit', caller, 'semantics', report)
        accepted = self.accept('tuneup-audit', caller, 'semantics', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

        stages = ('inspect', 'semantics')
        final = self.inst.accept('validate-final', 'tuneup-audit', {
            'caller': caller,
            'validator_argv_by_stage': {s: self.final_argv('tuneup-audit', s) for s in stages},
            'input_file_by_stage': {s: self.observed('tuneup-audit', s) for s in stages}})
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        overview = self.inst.job('overview', 'tuneup-audit', {})
        self.assertEqual([s['status'] for s in overview['stages']], ['accepted-at-snapshot'] * 2)
        self.assertEqual(settings.read_bytes(), before, 'an audit job never writes settings')

    def state(self, job_id):
        return json.loads((self.inst.state / job_id / 'job.json').read_text())

    def observed(self, job_id, stage_id):
        return next(s for s in self.state(job_id)['stages'] if s['id'] == stage_id)['observation_ref']['path']

    def final_argv(self, job_id, stage_id):
        return [str(self.inst.validator), '--input', self.observed(job_id, stage_id)]

    def test_apply_job_needs_recorded_owner_approval_backup_and_distinct_observations(self):
        job = self.plan('tuneup-apply', 'agent-tuneup/apply',
                        [self.stage('apply', 'R-EDIT', APPLY_CRITERIA)],
                        [self.slot('verify-1', 'apply', WORKERS[1], VERIFY_TARGET)], actions=('read', 'settings-apply'))
        caller = self.create(job)
        private = self.base / 'private'
        private.mkdir(mode=0o700)
        target = self.inst.home / '.claude' / 'settings.json'
        target.parent.mkdir()
        target.write_text('{"permissions":{"allow":["Read(*)"]},"env":{"TOKEN":"fixture-secret"}}')
        target.chmod(0o600)
        candidate = private / 'candidate.json'
        candidate.write_text('{"permissions":{"allow":[]},"env":{"TOKEN":"fixture-secret"}}')
        candidate.chmod(0o600)
        plan_file = private / 'plan.json'
        planned = json.loads(self.inst.run('scripts/align.py', 'plan', '--adapter', 'claude', '--target', target,
                                           '--candidate', candidate, '--allow-key', '/permissions/allow',
                                           '--out', plan_file).stdout)
        self.assertEqual(planned['settings_writes'], 0)

        from tests.imps_plan_review_fixtures import legacy_box
        from tests.adopter_plan_review_fixtures import reviewed_apply_context
        box=legacy_box(self.base/'proposal-review',self.inst.pkg,self.inst.manifest,self.inst.env)
        apply_context=reviewed_apply_context(box,self.inst.pkg,self.inst.manifest,json.loads(plan_file.read_text()))
        context_file=self.inst.payload('apply-context.json',apply_context)

        # The owner question is pending: an approval wait blocks acceptance.
        wait = {'kind': 'approval-wait', 'request_id': 'verify-1-r0', 'wait_id': 'apply-change-1',
                'question': 'apply change-1?'}
        self.inst.job('task-observation', 'tuneup-apply', {'caller': caller, 'task_id': 'verify-1', 'event': wait})
        self.assertTrue(self.inst.job('overview', 'tuneup-apply', {}))

        # The picker answer is saved outside job state and recorded as a scoped decision.
        answer = self.base / 'owner' / 'answer.txt'
        answer.parent.mkdir()
        quote = 'Apply change-1 with digest ' + planned['approval_digest']
        answer.write_text(quote + '\n')
        owner = {'id': 'owner-change-1', 'quote': quote, 'source': str(answer),
                 'source_sha256': sha(answer.read_bytes()), 'scope': 'settings-change:change-1'}
        self.inst.job('decision', 'tuneup-apply', {'caller': caller, 'decision': owner})
        before = private / 'before.json'
        shutil.copyfile(target, before)
        backup = private / 'backup.json'
        applied = json.loads(self.inst.run('scripts/align.py', 'apply', '--plan', plan_file, '--approval',
                                           planned['approval_digest'], '--backup', backup,'--context',context_file).stdout)
        self.assertTrue(applied['ok'])
        self.assertEqual(target.read_bytes(), candidate.read_bytes())
        parse = self.inst.run('scripts/audit.py', '--provider', 'claude', '--settings', target, check=False)
        self.assertEqual(parse.returncode, 0, parse.stdout)

        content = {'authorization_ref': owner['id'], 'backup_path': str(backup), 'backup_sha256': sha(backup.read_bytes()),
                   'before_path': str(before), 'before_sha256': sha(before.read_bytes()), 'parse_result': 'passed',
                   'load_result': 'passed', 'enforcement_result': 'unverified'}
        change = {**content, 'id': 'change-1', 'enforcement_required': False,
                  'observation': {'observer': 'coordinator', 'kind': 'settings-change',
                                  'source': 'synthetic fresh-session load fixture', 'content': content,
                                  'sha256': sha(canonical(content))}}
        report = {'criteria': APPLY_CRITERIA, 'audit_exit_code': 0, 'findings': [], 'changes': [change],
                  'authorization_records': [owner], 'apply_context':apply_context, 'applied_plan':json.loads(plan_file.read_text())}
        self.run_worker('tuneup-apply', caller, 'verify-1')
        observed = self.publish('tuneup-apply', caller, 'apply', report)
        waiting = self.accept('tuneup-apply', caller, 'apply', observed)
        self.assertNotEqual(waiting.returncode, 0)
        self.assertIn('approval waits', waiting.stderr)
        self.inst.job('task-observation', 'tuneup-apply', {'caller': caller, 'task_id': 'verify-1', 'event': {
            'kind': 'approval-resolved', 'request_id': 'verify-1-r0', 'wait_id': 'apply-change-1'}})

        # Validator-level refusals (run directly so no stage pass is charged).
        def rejected(mutate, reason):
            data = json.loads(json.dumps(report))
            mutate(data)
            path = self.base / 'coordinator' / 'negative.json'
            path.write_text(json.dumps(data))
            proc = subprocess.run([str(self.inst.validator), '--input', str(path)], capture_output=True, text=True, env=self.inst.env)
            self.assertEqual(proc.returncode, 1, reason)
            self.assertIn(reason, proc.stdout)

        rejected(lambda d: d.update(authorization_records=[]), 'recorded scoped owner authorization')
        rejected(lambda d: d['authorization_records'][0].update(scope='settings-change:other'),
                 'recorded scoped owner authorization')
        rejected(lambda d: d['changes'][0].update(enforcement_required=True), 'required live enforcement is unverified')
        rejected(lambda d: d['changes'][0].update(backup_sha256='0' * 64), 'backup differs')

        def unloaded(d):
            for row in (d['changes'][0], d['changes'][0]['observation']['content']):
                row['load_result'] = 'unverified'
            d['changes'][0]['observation']['sha256'] = sha(canonical(d['changes'][0]['observation']['content']))
        rejected(unloaded, 'parse or load failed')
        rejected(lambda d: d.update(criteria={**APPLY_CRITERIA, 'live_enforcement_required': True}),
                 'explicit coordinator observation is required')

        # The authorization record must be the job's adopted decision, not a copied claim.
        forged = json.loads(json.dumps(report))
        forged['authorization_records'][0]['quote'] = 'Apply change-1'
        refused = self.accept('tuneup-apply', caller, 'apply', self.publish('tuneup-apply', caller, 'apply', forged))
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('adopted immutable owner record', refused.stderr)

        observed = self.publish('tuneup-apply', caller, 'apply', report)
        accepted = self.accept('tuneup-apply', caller, 'apply', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        final = self.inst.accept('validate-final', 'tuneup-apply', {
            'caller': caller, 'validator_argv_by_stage': {'apply': self.final_argv('tuneup-apply', 'apply')},
            'input_file_by_stage': {'apply': observed}})
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

        # Changing the backup after acceptance stales the evidence.
        backup.chmod(0o600)
        backup.write_text('{}')
        self.assertFalse(json.loads(self.inst.accept('validate', 'tuneup-apply', {
            'caller': caller, 'stage_id': 'apply'}).stdout or '{"accepted": false}')['accepted'])


if __name__ == '__main__':
    unittest.main()
