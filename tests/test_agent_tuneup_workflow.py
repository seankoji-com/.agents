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
from shared.adopter_planning import tuneup_report_adapter  # noqa: E402
from tests.test_model_ids import MODEL_ID  # noqa: E402

PLUGIN = ROOT / 'plugins' / 'agent-tuneup'
REPORT_INSTRUCTIONS = tuneup_report_adapter(PLUGIN).RESEARCH_INSTRUCTIONS
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
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENTS_', 'XDG_',
                    'OPENAI_', 'ANTHROPIC_', 'GEMINI_', 'GOOGLE_', 'CODEX_', 'CLAUDE_',
                    'OPENCODE_', 'MUSE_', 'AWS_', 'AZURE_', 'GROQ_', 'HF_', 'GH_', 'GITHUB_')) and
                    k not in ('PYTHONPATH', 'PYTHONHOME', 'SSH_AUTH_SOCK') and
                    not any(s in k for s in ('TOKEN', 'SECRET', 'KEY', 'PASSWORD', 'CREDENTIAL'))}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(base / 'config'),
                        XDG_STATE_HOME=str(base / 'xdg-state'), XDG_DATA_HOME=str(base / 'data'),
                        XDG_CACHE_HOME=str(base / 'cache'), TMPDIR=str(base / 'scratch'))
        (base / 'scratch').mkdir()
        self.prefix, self.agents, self.state = base / 'prefix', base / 'agents', base / 'jobs'
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'agent-tuneup',
                               '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                              capture_output=True, text=True, env=self.env, cwd=base, timeout=60)
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


class NativeReportRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inst = Installed(Path(self.tmp.name).resolve())

    def audit(self, provider, data):
        return self.inst.run('scripts/audit.py', '--provider', provider, '--settings',
                             self.inst.payload('settings.json', data), check=False)

    def test_native_ordered_permissions_and_agents_are_audited(self):
        data = {'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'},
                                {'action': 'shell', 'resource': 'git push *', 'effect': 'deny'}],
                'agents': {'fixture-secret': {'permissions': [
                    {'action': 'shell', 'resource': '*', 'effect': 'allow'}]}}}
        p = self.audit('opencode', data)
        self.assertEqual(p.returncode, 1, p.stdout)
        findings = json.loads(p.stdout)['findings']
        self.assertIn('constrained_broad_allow', {f['code'] for f in findings})
        self.assertTrue(any(f['location'].startswith('agents[0]') for f in findings))
        self.assertNotIn('fixture-secret', p.stdout + p.stderr)

    def test_native_mcp_is_not_a_server_named_servers_or_timeout(self):
        data = {'permissions': [], 'mcp': {'timeout': {'startup': 45000}, 'servers': {
            'fixture-secret': {'type': 'remote', 'url': 'https://example.invalid', 'disabled': True}}}}
        settings = self.inst.payload('native.json', data)
        catalog = self.inst.payload('catalog.json', {'providers': [{'providerInstanceId': 'oc'}]})
        inventory = self.inst.payload('inventory.json', {'version': 1, 'providers': [
            {'provider_instance_id': 'oc', 'adapter': 'opencode', 'sources': [
                {'path': str(settings), 'scope': 'global'}]}], 'capabilities': [
            {'kind': 'mcp', 'members': {'oc': 'fixture-secret'}}]})
        p = self.inst.run('scripts/align.py', 'audit', '--catalog', catalog, '--inventory', inventory, check=False)
        self.assertEqual(json.loads(p.stdout)['capabilities'][0]['states'], ['disabled'])
        self.assertNotIn('fixture-secret', p.stdout + p.stderr)

    def test_unknown_and_mixed_opencode_shapes_do_not_pass(self):
        for data in ({'permissions': {'fixture-secret': 'allow'}},
                     {'permission': 'allow', 'permissions': []},
                     {'agents': {'fixture-secret': {'permission': 'allow'}}},
                     {'agent': {'fixture-secret': {'permissions': []}}},
                     {'mcp': {'servers': {}, 'other': {'type': 'local', 'command': ['true']}}}):
            with self.subTest(data=data):
                p = self.audit('opencode', data)
                self.assertEqual(p.returncode, 2, p.stdout)
                self.assertNotIn('fixture-secret', p.stdout + p.stderr)

    def test_installed_native_plugin_inventory_and_unsupported_forms(self):
        settings = self.inst.payload('plugin-settings.json', {'plugins': [
            {'package': 'fixture-secret', 'options': {'credential': 'invented-credential'}}]})
        catalog = self.inst.payload('plugin-catalog.json', {'providers': [{'providerInstanceId': 'oc'}]})
        inventory = self.inst.payload('plugin-inventory.json', {'version': 1, 'providers': [
            {'provider_instance_id': 'oc', 'adapter': 'opencode', 'sources': [
                {'path': str(settings), 'scope': 'global'}]}], 'capabilities': [
            {'kind': 'plugin', 'members': {'oc': 'fixture-secret'}}]})
        proc = self.inst.run('scripts/align.py', 'audit', '--catalog', catalog, '--inventory', inventory, check=False)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)  # Wiring remains unverified.
        self.assertTrue(json.loads(proc.stdout)['ok'])
        self.assertEqual(json.loads(proc.stdout)['capabilities'][0]['states'], ['configured'])
        for secret in ('fixture-secret', 'invented-credential', str(settings)):
            self.assertNotIn(secret, proc.stdout + proc.stderr)
        for data in ({'plugin': [], 'plugins': ['fixture-secret']},
                     {'plugins': [{'package': 'fixture-secret', 'enabled': False}]},
                     {'plugins': ['-fixture-secret']}):
            proc = self.audit('opencode', data)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['error'], 'settings_unreadable_or_invalid')
            self.assertNotIn('fixture-secret', proc.stdout + proc.stderr)

    def test_muse_gap_survives_validator_and_cannot_be_ignored_by_exit_zero(self):
        p = self.audit('muse', {'permissions': {'profiles': {}}})
        self.assertEqual(p.returncode, 1, p.stdout)
        findings = json.loads(p.stdout)['findings']
        self.assertIn('coverage_gap', {f['code'] for f in findings})
        report = {'criteria': dict(AUDIT_CRITERIA, findings_allowed=False),
                  'audit_exit_code': 0, 'findings': findings, 'changes': []}
        p = self.inst.run('scripts/validate_audit.py', '--input', self.inst.payload('report.json', report), check=False)
        self.assertEqual(p.returncode, 1, p.stdout)

    def test_explicit_zero_finding_report_requires_quality_review(self):
        contract = {'schema_version': 1, 'finding_scope': 'audited-target',
                    'reports': [{'task_id': 'research', 'path': 'artifacts/tasks/research/target-findings.json'}],
                    'quality_review': 'integrated-adopter-planning'}
        data = {'criteria': AUDIT_CRITERIA, 'target_report': contract, 'report_stage': 'integrated', 'audit_exit_code': 0,
                'findings': [], 'changes': []}
        p = self.inst.run('scripts/validate_audit.py', '--input', self.inst.payload('report.json', data), check=False)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('independent quality review required', p.stdout)

    def test_installed_legacy_native_and_invalid_receipts_redact_values(self):
        for data, code in (({'permission': {'bash': 'allow'}, 'apiKey': 'invented-credential'}, 1),
                           ({'permissions': [{'action': 'shell', 'resource': '*', 'effect': 'allow'}],
                             'apiKey': 'invented-credential'}, 1),
                           ({'permissions': [{'action': 'invented-credential', 'resource': '*', 'effect': 'bogus'}]}, 2)):
            p = self.audit('opencode', data)
            self.assertEqual(p.returncode, code, p.stdout)
            self.assertNotIn('invented-credential', p.stdout + p.stderr)
        for key in ('permission', 'permissions'):
            before = {key: 'allow' if key == 'permission' else [{'action': 'shell', 'resource': '*', 'effect': 'allow'}],
                      'provider': {'fixture': {'apiKey': 'invented-credential'}}}
            after = {**before, key: 'ask' if key == 'permission' else [{'action': 'shell', 'resource': '*', 'effect': 'ask'}]}
            target = self.inst.payload('before.json', before); target.chmod(0o600)
            candidate = self.inst.payload('after.json', after); candidate.chmod(0o600)
            out = self.inst.base / (key + '-plan.json')
            p = self.inst.run('scripts/align.py', 'plan', '--adapter', 'opencode', '--target', target,
                              '--candidate', candidate, '--allow-key', '/' + key, '--out', out)
            self.assertNotIn('invented-credential', p.stdout + p.stderr)


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
        specialization = folded(REPORT_INSTRUCTIONS)
        self.assertIn('Carry every assigned deterministic inspect finding and gap from consumed_outputs', specialization)
        self.assertIn('Preserve assigned IDs, severities and whole objects', specialization)

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

    def run_worker(self, job_id, caller, task_id, findings=(), verdict=None, target_findings=None,
                   result_mutate=None, check=True, identity=None):
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
        if identity is not None:
            event['status_identity'] = identity
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
        if target_findings is not None:
            if callable(target_findings):
                target_findings = target_findings(brief)
            rel = f'artifacts/tasks/{task_id}/target-findings.json'
            path = self.inst.state / job_id / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = canonical({'schema_version': 1, 'findings': target_findings})
            path.write_bytes(raw)
            result['artifacts'] = [{'path': rel, 'sha256': sha(raw), 'bytes': len(raw)}]
        if result_mutate:
            result_mutate(result)
        return self.inst.job('result', job_id, {'caller': caller, 'task_id': task_id,
                                                'request_id': brief['request_id'], 'completion_id': host + '-done',
                                                'result': {'json': json.dumps(result)}}, check=check)

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
        self.last_accept = (job_id, stage_id, observed)
        return self.inst.accept('accept-stage', job_id, {
            'caller': caller, 'stage_id': stage_id, 'input_file': observed, 'revision': stage_id + '-r1',
            'validator_argv': [str(self.inst.validator), '--input', observed]})

    def assert_refused(self, proc, reason):
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        output = proc.stdout + proc.stderr
        if 'validator pre-check failed' in output:
            # Public acceptance deliberately masks adapter errors. Re-run its
            # read-only installed adapter on exactly that job/stage/input to pin
            # the underlying refusal, without weakening production redaction.
            job_id, stage_id, observed = self.last_accept
            script = ('import errno,json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                      'from shared.job_acceptance import _adapter; '
                      'from shared.job_coordinator import verify_all_pins; from core.jobs.store import Store; '
                      'job=verify_all_pins(Store(sys.argv[2],sys.argv[3])); '
                      'stage=next(s for s in job["stages"] if s["id"]==sys.argv[4]);\n'
                      'try: _adapter(job,stage,[str(Path(sys.argv[1])/"scripts/validate_audit.py"),'
                      '"--input",sys.argv[5]],sys.argv[5])\n'
                      'except (ValueError,OSError) as exc:\n'
                      ' print(str(exc), errno.errorcode.get(getattr(exc,"errno",None),"")); sys.exit(1)\n')
            probe = subprocess.run([sys.executable, '-I', '-c', script, str(self.inst.pkg),
                str(self.inst.state), job_id, stage_id, observed], capture_output=True, text=True,
                env=self.inst.env, cwd=self.base, timeout=60)
            self.assertEqual(probe.returncode, 1, probe.stdout + probe.stderr)
            self.assertFalse(probe.stderr, probe.stderr)
            output = probe.stdout
        self.assertIn(reason, output)

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
        direct = subprocess.run([str(self.inst.validator), '--input', smuggled], capture_output=True,
                                text=True, env=self.inst.env, cwd=self.base)
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

    def report_job(self, job_id='target-audit', findings=None):
        contract = {'schema_version': 1, 'finding_scope': 'audited-target',
                    'reports': [{'task_id': 'research', 'path': 'artifacts/tasks/research/target-findings.json'}],
                    'quality_review': 'integrated-adopter-planning'}
        stages = [self.stage('semantics', 'R-RESEARCH', AUDIT_CRITERIA),
                  self.stage('report', 'R-REPORT', AUDIT_CRITERIA, depends=['semantics'], mode='direct')]
        for stage, phase in zip(stages, ('research', 'integrated')):
            stage['validator_contract'].update(target_report=contract, report_stage=phase)
        stages[0]['resources'] = {'target_report': json.loads(json.dumps(contract)),
                                  'target_report_instructions': REPORT_INSTRUCTIONS}
        job = self.plan(job_id, 'agent-tuneup/audit', stages,
                        [self.slot('research', 'semantics', WORKERS[0],
                                   {'providerInstanceId': 'fixture-research', 'model': 'gpt-fixture', 'lineage': 'openai'})])
        if findings is None:
            findings = [{'id': 'T1', 'severity': 'major', 'code': 'coverage_gap',
                         'location': 'approval-policy-store', 'scenario': 'native coverage is unsupported',
                         'source_evidence': ['fixture:schema-v1'], 'original_detail': {'retained': True}},
                        {'id': 'T2', 'severity': 'minor', 'code': 'unsupported', 'location': 'policy',
                         'scenario': 'unknown policy dimension', 'source_evidence': 'fixture:schema-v1'}]
        return job, {'criteria': AUDIT_CRITERIA, 'target_report': contract, 'report_stage': 'research',
                     'audit_exit_code': 1 if findings else 0, 'findings': findings, 'changes': []}

    def test_installed_target_specialization_reaches_full_and_compact_briefs(self):
        from shared.compact_briefs import COMPACT, deserialize
        recipe = (PLUGIN / 'references/job-plan.md').read_text()
        self.assertEqual(recipe.split('```text\n', 1)[1].split('\n```', 1)[0], REPORT_INSTRUCTIONS)
        for compact in (False, True):
            with self.subTest(compact=compact):
                job, report = self.report_job('specialized-' + str(compact).lower())
                if compact:
                    job['policy']['worker_brief_transport'] = COMPACT
                original = canonical(job)
                tuneup_report_adapter(PLUGIN).validate_job(job)
                self.assertEqual(canonical(job), original, 'admission must not inject resources into job state')
                caller = self.create(job)
                prepared = self.inst.job('prepare', job['job_id'], {'caller': caller, 'task_id': 'research'})
                raw = Path(prepared['path']).read_bytes()
                self.assertEqual((sha(raw), len(raw)), (prepared['sha256'], prepared['bytes']))
                brief = deserialize(raw)
                self.assertEqual(brief['resources'], job['stages'][0]['resources'])
                self.assertEqual(brief['resources']['target_report'], report['target_report'])
                self.assertEqual(brief['resources']['target_report']['reports'], [
                    {'task_id': 'research', 'path': 'artifacts/tasks/research/target-findings.json'}])
                if compact:
                    self.assertEqual(brief['transport'], COMPACT)
                instructions = brief['resources']['target_report_instructions']
                for clause in ('target-findings.json', '{"schema_version":1,"findings":[...]}',
                               'stable id, severity (blocker, major, minor, note), code',
                               'redacted location, concrete scenario and source_evidence',
                               'whole objects, severity and order', 'exact path, SHA-256 and byte count',
                               'consumed_outputs', 'assigned IDs', 'assigned order',
                               'Add research\nfindings after those rows', 'coverage_gap and unsupported',
                               'Never omit or demote a gap', 'requires review_verdict: adverse',
                               'Otherwise review_verdict is null', 'not a prerequisite',
                               'Never fetch raw remote settings for local redaction',
                               'transfer raw/aggregate transcripts', 'Do not bypass a guard refusal',
                               'install/execute a remote extractor', 'safe extraction is unsupported'):
                    self.assertIn(clause, instructions)

    def test_target_report_successor_does_not_waive_proposal_review(self):
        job, report = self.report_job('proposal-before-report')
        job['stages'].insert(1, self.stage('proposal', 'R-PROPOSAL', AUDIT_CRITERIA, depends=['semantics']))
        job['stages'][-1]['depends_on'].append('proposal')
        job['requirements']['R-PROPOSAL'] = 'Review the candidate conclusions independently'
        job['tasks'].append(self.slot('verify', 'proposal', WORKERS[1], VERIFY_TARGET))
        caller = self.create(job)
        self.run_worker(job['job_id'], caller, 'research', target_findings=report['findings'])
        observed = self.publish(job['job_id'], caller, 'semantics', report)
        self.assertEqual(self.accept(job['job_id'], caller, 'semantics', observed).returncode, 0)
        self.run_worker(job['job_id'], caller, 'verify')
        proposal = {'criteria': AUDIT_CRITERIA, 'audit_exit_code': 0, 'findings': [], 'changes': []}
        observed = self.publish(job['job_id'], caller, 'proposal', proposal)
        refused = self.accept(job['job_id'], caller, 'proposal', observed)
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        self.assertIn('integrated tuneup conclusions require the producing planning descriptor', refused.stderr)
        from tests.adopter_plan_review_fixtures import review_existing_tuneup_report
        proposal['adopter_output'] = review_existing_tuneup_report(self.inst.pkg, self.inst.manifest, self.inst.env,
            self.inst.state, job['job_id'], proposal, self.base, review_name='proposal-quality')
        observed = self.publish(job['job_id'], caller, 'proposal', proposal)
        accepted = self.accept(job['job_id'], caller, 'proposal', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        observed = self.publish(job['job_id'], caller, 'report', {**report, 'report_stage': 'integrated'})
        accepted = self.accept(job['job_id'], caller, 'report', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        final = self.inst.accept('validate-final', job['job_id'], {'caller': caller,
            'validator_argv_by_stage': {s: self.final_argv(job['job_id'], s) for s in ('semantics', 'proposal', 'report')},
            'input_file_by_stage': {s: self.observed(job['job_id'], s) for s in ('semantics', 'proposal', 'report')}})
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_muse_inspect_gaps_are_consumed_preserved_and_reviewed_in_final_report(self):
        settings = self.inst.payload('muse-settings.json', {'permissions': {'profiles': {}}})
        audit = self.inst.run('scripts/audit.py', '--provider', 'muse', '--settings', settings, check=False)
        self.assertEqual(audit.returncode, 1, audit.stdout + audit.stderr)
        findings = [{**row, 'id': 'M' + str(i), 'severity': 'major',
                     'scenario': 'native approval-policy store remains uninspected',
                     'source_evidence': ['fixture:installed-muse-inspect']}
                    for i, row in enumerate(json.loads(audit.stdout)['findings'], 1)]
        self.assertEqual({f['code'] for f in findings}, {'coverage_gap', 'unsupported'})
        job, report = self.report_job('muse-inspect-report', findings=findings)
        inspect = self.stage('inspect', 'R-INSPECT', AUDIT_CRITERIA, mode='direct')
        inspect_data = {'criteria': AUDIT_CRITERIA, 'audit_exit_code': 1, 'findings': findings, 'changes': []}
        output = self.inst.payload('muse-inspect-output.json', inspect_data)
        inspect['outputs'] = [str(output)]
        job['stages'].insert(0, inspect)
        job['stages'][1]['depends_on'] = ['inspect']
        job['requirements']['R-INSPECT'] = 'Retain deterministic native store gaps'
        caller = self.create(job)
        observed = self.publish(job['job_id'], caller, 'inspect', inspect_data)
        accepted = self.accept(job['job_id'], caller, 'inspect', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        def consumed_findings(brief):
            self.assertEqual(brief['consumed_outputs'], [str(output)])
            return json.loads(Path(brief['consumed_outputs'][0]).read_text())['findings']
        self.run_worker(job['job_id'], caller, 'research', target_findings=consumed_findings)
        observed = self.publish(job['job_id'], caller, 'semantics', report)
        accepted = self.accept(job['job_id'], caller, 'semantics', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        observed = self.publish(job['job_id'], caller, 'report', {**report, 'report_stage': 'integrated'})
        accepted = self.accept(job['job_id'], caller, 'report', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(json.loads(Path(observed).read_text())['findings'], findings)

    def test_explicit_target_major_is_preserved_and_reviewed_after_research(self):
        job, report = self.report_job()
        caller = self.create(job)
        self.run_worker(job['job_id'], caller, 'research', target_findings=report['findings'])
        observed = self.publish(job['job_id'], caller, 'semantics', report)
        accepted = self.accept(job['job_id'], caller, 'semantics', observed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertNotIn('adopter_output', json.loads(Path(observed).read_text()))
        final = {**report, 'report_stage': 'integrated'}
        # The final gate must fail without the actual producing quality receipt.
        unreviewed = self.inst.job('observation', job['job_id'], {'caller': caller, 'stage_id': 'report',
            'input_file': str(self.inst.payload('unreviewed.json', final))})['path']
        refused = self.accept(job['job_id'], caller, 'report', unreviewed)
        self.assert_refused(refused, 'independent quality review required, even with zero findings')
        reviewed = self.publish(job['job_id'], caller, 'report', final)
        accepted = self.accept(job['job_id'], caller, 'report', reviewed)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(json.loads(Path(reviewed).read_text())['findings'], report['findings'])
        final_gate = self.inst.accept('validate-final', job['job_id'], {'caller': caller,
            'validator_argv_by_stage': {s: self.final_argv(job['job_id'], s) for s in ('semantics', 'report')},
            'input_file_by_stage': {s: self.observed(job['job_id'], s) for s in ('semantics', 'report')}})
        self.assertEqual(final_gate.returncode, 0, final_gate.stdout + final_gate.stderr)
        path = self.inst.state / job['job_id'] / report['target_report']['reports'][0]['path']
        path.write_bytes(path.read_bytes() + b'\n')
        stale = self.inst.accept('validate', job['job_id'], {'caller': caller, 'stage_id': 'report'})
        self.assertNotEqual(stale.returncode, 0, stale.stdout + stale.stderr)
        self.assertFalse(json.loads(stale.stdout)['accepted'])
        self.assertEqual(json.loads(stale.stdout)['reason'],
                         'dependency_stale: predecessor acceptance is stale: semantics')
        stale_research = self.inst.accept('validate', job['job_id'], {'caller': caller, 'stage_id': 'semantics'})
        self.assertNotEqual(stale_research.returncode, 0)
        self.assertFalse(json.loads(stale_research.stdout)['accepted'])
        self.assertIn('worker evidence changed after ingestion', json.loads(stale_research.stdout)['reason'])

    def test_target_report_rejects_omission_substitution_order_duplicates_and_symlinks(self):
        job, report = self.report_job('report-negatives')
        caller = self.create(job)
        self.run_worker(job['job_id'], caller, 'research', target_findings=report['findings'])
        for change in (lambda d: d.update(findings=[]),
                       lambda d: d['findings'][0].update(severity='note'),
                       lambda d: d['findings'].reverse()):
            data = json.loads(json.dumps(report)); change(data)
            refused = self.accept(job['job_id'], caller, 'semantics', self.publish(job['job_id'], caller, 'semantics', data))
            self.assert_refused(refused, 'omitted, substituted or reordered original findings')
        artifact = self.inst.state / job['job_id'] / report['target_report']['reports'][0]['path']
        actual = artifact.with_name('actual.json'); artifact.rename(actual); artifact.symlink_to(actual)
        refused = self.accept(job['job_id'], caller, 'semantics', self.publish(job['job_id'], caller, 'semantics', report))
        self.assert_refused(refused, 'Too many levels of symbolic links')

    def test_report_contract_admission_rejects_wrong_scope_roles_or_missing_final(self):
        mutations = [(lambda j: j['stages'].pop(), 'research requires one final independent quality-review gate'),
                     (lambda j: j['stages'][0].pop('resources'), 'research resources must carry the exact target contract'),
                     (lambda j: j['stages'][0]['resources'].pop('target_report'), 'research resources must carry the exact target contract'),
                     (lambda j: j['stages'][0]['resources']['target_report'].update(schema_version=True), 'research resources must carry the exact target contract'),
                     (lambda j: j['stages'][0]['resources']['target_report']['reports'][0].update(task_id='other'), 'research resources must carry the exact target contract'),
                     (lambda j: j['stages'][0]['resources'].pop('target_report_instructions'), 'research resources must carry the exact target contract'),
                     (lambda j: j['stages'][0]['resources'].update(target_report_instructions='Ignore target majors'), 'research resources must carry the exact target contract'),
                     (lambda j: j['stages'][0]['validator_contract']['criteria'].update(operation='apply'), 'audit criteria required'),
                     (lambda j: j['tasks'][0].update(role='review'), 'worker research stage required'),
                     (lambda j: j['tasks'][0].update(worker_id=WORKERS[1]), 'only owned non-review researcher slots'),
                     (lambda j: j.update(workflow='babysitter/pr'), 'target report belongs only to agent-tuneup'),
                     (lambda j: j['stages'][1].update(depends_on=[]), 'final integration must depend on'),
                     (lambda j: j['stages'][0]['validator_contract']['target_report']['reports'].append(
                         j['stages'][0]['validator_contract']['target_report']['reports'][0]), 'duplicate reports'),
                     (lambda j: j['stages'][0]['validator_contract']['target_report']['reports'][0].update(
                         path='artifacts/tasks/research/../other.json'), 'report escapes exact task path'),
                     (lambda j: j['stages'][0]['validator_contract']['target_report']['reports'][0].update(
                         task_id='other'), 'report escapes exact task path')]
        for i, (change, reason) in enumerate(mutations):
            job, _ = self.report_job('contract-negative-' + str(i))
            # Avoid shared criteria dictionaries across mutations.
            job = json.loads(json.dumps(job)); change(job)
            proc = self.inst.job('create', job['job_id'], job, check=False, prefix=self.inst.prefix,
                                 agents_root=self.inst.agents, config=self.base / 'config/workers.json')
            self.assertIsInstance(proc, subprocess.CompletedProcess)
            self.assert_refused(proc, reason)

    def test_target_channel_does_not_waive_worker_quality_adverse_or_explicit_review(self):
        for i, verdict in enumerate(('adverse', None)):
            job, report = self.report_job('worker-quality-' + str(i))
            if verdict is None:
                job['tasks'][0]['review_required'] = True
            caller = self.create(job)
            quality = [{'id': 'Q1', 'severity': 'major', 'title': 'report omitted evidence',
                        'scenario': 'cannot establish report correctness', 'source_evidence': ['fixture:quality']}] if verdict else []
            self.run_worker(job['job_id'], caller, 'research', findings=quality, verdict=verdict,
                            target_findings=report['findings'])
            refused = self.accept(job['job_id'], caller, 'semantics', self.publish(job['job_id'], caller, 'semantics', report))
            self.assert_refused(refused, 'unresolved retained blocker or major finding' if verdict else
                                'required_review_unavailable: required independent review task IDs are absent')

    def test_worker_result_major_still_requires_adverse_and_exact_correlation(self):
        changes = [lambda r: r.update(findings=[{'id': 'Q1', 'severity': 'major', 'title': 'bad report',
                    'scenario': 'missing evidence', 'source_evidence': ['fixture:quality']}]),
                   lambda r: r.update(worker_id='other/worker'),
                   lambda r: r.update(effective_brief_sha256='0' * 64)]
        for i, change in enumerate(changes):
            job, report = self.report_job('result-negative-' + str(i)); caller = self.create(job)
            proc = self.run_worker(job['job_id'], caller, 'research', target_findings=report['findings'],
                                   result_mutate=change, check=False)
            if isinstance(proc, subprocess.CompletedProcess):
                self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(self.state(job['job_id'])['tasks'][0]['status'], 'failed')
            self.assertIn(('blocker/major findings require an adverse verdict',
                           'result correlation mismatch: worker_id',
                           'result correlation mismatch: effective_brief_sha256')[i],
                          self.state(job['job_id'])['tasks'][0]['execution_history'][-1]['reason'])
            refused = self.accept(job['job_id'], caller, 'semantics', self.publish(job['job_id'], caller, 'semantics', report))
            self.assert_refused(refused, 'declared task slot lacks a current ready result: research')

    def test_zero_findings_still_needs_nonadverse_review_with_original_artifact_evidence(self):
        from tests.adopter_plan_review_fixtures import review_existing_tuneup_report
        for i, (options, reason) in enumerate((({'adverse': True}, 'actual planning receipt missing'),
                ({'target_evidence': False}, 'quality review must declare the original target artifacts as evidence'),
                ({'target_inspected': False}, 'every required quality-review pass must inspect'), ({}, None))):
            job, report = self.report_job('quality-review-' + str(i), findings=[])
            caller = self.create(job)
            self.run_worker(job['job_id'], caller, 'research', target_findings=[])
            observed = self.publish(job['job_id'], caller, 'semantics', report)
            self.assertEqual(self.accept(job['job_id'], caller, 'semantics', observed).returncode, 0)
            final = {**report, 'report_stage': 'integrated'}
            desc = review_existing_tuneup_report(self.inst.pkg, self.inst.manifest, self.inst.env,
                self.inst.state, job['job_id'], final, self.base, **options)
            final['adopter_output'] = desc
            observation = self.inst.job('observation', job['job_id'], {'caller': caller, 'stage_id': 'report',
                'input_file': str(self.inst.payload('quality-observation.json', final))})['path']
            refused = self.accept(job['job_id'], caller, 'report', observation)
            if options:
                self.assert_refused(refused, reason)
            else:
                self.assertEqual(refused.returncode, 0, refused.stdout + refused.stderr)

    def test_target_contract_keeps_identity_mismatch_sticky(self):
        job, report = self.report_job('identity-report'); caller = self.create(job)
        self.run_worker(job['job_id'], caller, 'research', target_findings=report['findings'],
                        identity={'providerInstanceId': 'wrong-provider', 'model': 'wrong-model', 'options': {}})
        refused = self.accept(job['job_id'], caller, 'semantics', self.publish(job['job_id'], caller, 'semantics', report))
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('identity', refused.stderr)

    def test_original_artifact_requires_unique_ids_and_exact_ingested_ownership(self):
        for i, mode in enumerate(('duplicate-id', 'missing-descriptor', 'other-task')):
            job, report = self.report_job('artifact-negative-' + str(i)); caller = self.create(job)
            findings = list(report['findings'])
            if mode == 'duplicate-id':
                findings.append(findings[0])
            def mutate(result):
                if mode == 'missing-descriptor':
                    result['artifacts'] = []
                elif mode == 'other-task':
                    rel = 'artifacts/tasks/other/target-findings.json'
                    path = self.inst.state / job['job_id'] / rel
                    path.parent.mkdir(parents=True)
                    path.write_bytes((self.inst.state / job['job_id'] / result['artifacts'][0]['path']).read_bytes())
                    result['artifacts'][0]['path'] = rel
            self.run_worker(job['job_id'], caller, 'research', target_findings=findings, result_mutate=mutate)
            refused = self.accept(job['job_id'], caller, 'semantics', self.publish(job['job_id'], caller, 'semantics', report))
            self.assert_refused(refused, {'duplicate-id': 'duplicate finding ID',
                'missing-descriptor': 'exact ingested artifact descriptor required',
                'other-task': 'result evidence escapes its task subtree'}[mode])

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
            proc = subprocess.run([str(self.inst.validator), '--input', str(path)], capture_output=True,
                                  text=True, env=self.inst.env, cwd=self.base)
            self.assertEqual(proc.returncode, 1, reason)
            self.assertIn(reason, proc.stdout)

        rejected(lambda d: d.update(authorization_records=[]), 'recorded scoped owner authorization')
        rejected(lambda d: d['changes'][0].pop('backup_sha256'), 'settings change lacks authorization or backup')
        rejected(lambda d: d.update(findings=[{'code': 'unsafe-policy', 'location': 'policy', 'severity': 'major'}]),
                 'unresolved safety findings')
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
