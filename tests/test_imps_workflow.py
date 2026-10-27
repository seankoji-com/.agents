"""Issue #28 Stage 4 imps coordinator adapter.

Routing, direct cheap operations, worker definitions and stated boundaries are checked
against the shipped files and the request helper. One synthetic whole job then runs
through an isolated installed imps package: installed job_cli.py, the stage-local gate
`validate` (through validate_stage.py) and the new final gate. No live model, no GitHub.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import source_entry

from support import skill_manifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support import CoreTestCase  # noqa: E402
from tests.test_model_ids import MODEL_ID  # noqa: E402

PLUGIN = ROOT / 'plugins' / 'imps'
ENTRY = source_entry(PLUGIN)
JOBS_REF = PLUGIN / 'references' / 'jobs.md'
MANIFEST = skill_manifest(PLUGIN / 'plugin.json')
OPERATIONS = ['doctor', 'run', 'resume', 'status', 'cancel', 'verification-init', 'blast-radius', 'audit',
              'issues', 'prs', 'checklist', 'discussion']
PERSPECTIVES = {'solution-architect', 'grumpy-engineer', 'sre', 'business-analyst', 'ux-designer'}


def paragraph(text, marker):
    """The entry paragraph that starts with a bold operation marker."""
    start = text.index(marker)
    end = text.find('\n\n', start)
    return text[start:end if end != -1 else None]


def frontmatter(path):
    head = path.read_text().split('---\n')[1]
    return dict(line.split(': ', 1) for line in head.strip().splitlines())


class ImpsRoutingTest(unittest.TestCase):
    def test_every_operation_keeps_its_name_and_routes(self):
        self.assertEqual(MANIFEST['operations'], OPERATIONS)
        entry = ENTRY.read_text()
        examples = {'run': 'run fix the counter', 'issues': '42 43', 'discussion': 'discussion 5',
                    'resume': 'resume run-1', 'status': 'status run-1', 'cancel': 'cancel run-1',
                    'prs': 'prs repo owner/name', 'checklist': None}
        with tempfile.TemporaryDirectory() as td:
            listing = Path(td) / 'claims.md'
            listing.write_text('- [ ] claim\n  Verify: `true`\n')
            examples['checklist'] = f'checklist {listing}'
            for op in OPERATIONS:
                with self.subTest(op=op):
                    request = Path(td) / 'request.json'
                    request.write_text(json.dumps({'text': examples.get(op) or op}))
                    proc = subprocess.run([sys.executable, str(PLUGIN / 'scripts/input.py'), '--input', str(request)],
                                          capture_output=True, text=True, timeout=60)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertEqual(json.loads(proc.stdout)['data']['operation'], op)
                    self.assertRegex(entry, r'\*\*' + re.escape(op) + r'( <[a-z-]+>)?(\.)?\*\*')
        for op in ('blast-radius', 'audit', 'issues', 'checklist', 'discussion'):
            self.assertIn(f'`PKG/playbooks/{op}.md`', entry)
            self.assertTrue((PLUGIN / 'playbooks' / f'{op}.md').is_file())

    def test_prs_resolves_babysitter_through_the_job_pin(self):
        entry, jobs = ENTRY.read_text(), JOBS_REF.read_text()
        prs = entry[entry.index('**prs**'):]
        self.assertIn('agents --pin PIN --job JOB path babysitter', prs)
        self.assertNotIn('`agents path babysitter`', entry)
        self.assertIn('agents --job JOBS/JOB/job.json path babysitter', jobs)
        self.assertIn('{"key": "imps", "plugin": "imps"}', jobs)

    def test_entry_loads_only_the_coordination_contract_and_selected_files(self):
        entry = ENTRY.read_text()
        self.assertLess(len(entry.split()), 1500)
        self.assertIn('`PKG/shared/job-coordination.md`', entry)
        self.assertIn('`PKG/references/jobs.md`', entry)
        self.assertIn('`PKG/shared/job-coordination.md`', JOBS_REF.read_text())
        named = set(re.findall(r'`PKG/([\w./-]+)`', entry + JOBS_REF.read_text()))
        # shared/ and core/ are bundled into the package at install time.
        local = {n for n in named if not n.startswith(('shared/', 'core/'))}
        for name in local:
            self.assertTrue((PLUGIN / name).exists(), name)
        # The entry names playbooks but does not inline them; each loads only for its operation.
        for playbook in (PLUGIN / 'playbooks').glob('*.md'):
            self.assertNotIn(playbook.read_text().splitlines()[2], entry)

    def test_cheap_operations_stay_direct(self):
        entry = ENTRY.read_text()
        for marker in ('**doctor.**', '**status <run-id>.**', '**verification-init.**'):
            text = paragraph(entry, marker)
            self.assertIn('direct', text.lower(), marker)
            for launch in ('delegate_task', 'prepare', 'create'):
                self.assertNotIn(launch, text, marker)
        self.assertIn('doctor/status stay direct, without jobs or agents', entry)
        self.assertIn('authored facts need review', entry)
        self.assertIn('never create a job or launch an agent', ' '.join(JOBS_REF.read_text().split()))


class ImpsBoundaryTest(unittest.TestCase):
    def test_gate_authority_verification_slot_fallback_and_final_gate(self):
        jobs = ' '.join(JOBS_REF.read_text().split())
        for statement in (
                'The stage gate `validate` is the authority; the adapter runs it and cannot replace it.',
                'create its gate run yourself, so the run has parent ownership',
                'may write only that gate subtree and `artifacts/tasks/<task-id>/`',
                'It calls `snapshot` before each check',
                '"verification": "coordinator-fallback"',
                'taking a new `snapshot` before each one',
                'Never certify earlier tests retroactively or broaden permissions',
                'Final readiness uses a new final gate.',
                'Declare the final integration stage now',
                'A terminal task is not an accepted stage.',
                'Missing required independent review stays a blocker.',
                'Job metadata lives outside the gate runs.',
                'Major-version-1 runs need the previous installed package.'):
            self.assertIn(statement, jobs)

    def test_approval_waits_use_the_native_picker(self):
        jobs = JOBS_REF.read_text()
        self.assertIn('native question picker', jobs)
        self.assertIn('`PKG/shared/t3-runtime.md`', jobs)
        self.assertIn('native question picker', (ROOT / 'shared/t3-runtime.md').read_text())

    def test_optional_perspectives_survive_and_are_pinned_before_review(self):
        text = (PLUGIN / 'references/personas.md').read_text()
        panel = json.loads(text[text.index('```json') + 7:text.index('```', text.index('```json') + 7)])
        self.assertEqual(set(panel), PERSPECTIVES)
        self.assertTrue(all(isinstance(v, str) and v.strip() for v in panel.values()))
        self.assertIn("Pin each selected perspective's full text before any review starts.", text)
        self.assertIn('never against this file', text)
        self.assertIn('resources.perspectives', JOBS_REF.read_text())

    def test_read_only_operations_keep_their_boundaries(self):
        audit = (PLUGIN / 'playbooks/audit.md').read_text()
        self.assertIn('Auditing does not authorize', audit)
        self.assertIn('Authorization stays read-only', audit)
        self.assertIn('This operation is read-only; do not fix findings.', (PLUGIN / 'playbooks/blast-radius.md').read_text())
        self.assertIn('Post a reply only if the operator authorized it.', (PLUGIN / 'playbooks/discussion.md').read_text())
        self.assertIn('only when implementation is authorized', (PLUGIN / 'playbooks/discussion.md').read_text())


class WorkerDefinitionTest(unittest.TestCase):
    def test_manifest_workers_have_contract_definitions(self):
        workers = {w['id']: w for w in MANIFEST['workers']}
        self.assertEqual(set(workers), {'imps/stage-executor', 'imps/investigator', 'imps/auditor', 'imps/reviewer'})
        self.assertEqual({p.stem for p in (PLUGIN / 'agents').glob('*.md')}, {w.split('/')[1] for w in workers})
        for wid, meta in workers.items():
            with self.subTest(worker=wid):
                path = PLUGIN / meta['path']
                front = frontmatter(path)
                self.assertEqual(front['worker_id'], wid)
                self.assertEqual(front['role'], meta['responsibility'])
                text = ' '.join(path.read_text().split())
                self.assertIsNone(MODEL_ID.search(text))
                for required in ('brief path and its SHA-256', 'check the hash before acting',
                                 'Do not dispatch children', 'extra_work_requests', '`worker-result.schema.json` v1',
                                 'artifact envelope', 'no prose or code fences', '## Redaction',
                                 'Never infer approval from silence'):
                    self.assertIn(required, text)
                self.assertRegex(text, r'Do not accept (your own work|the change or your own review)')
                for status in ('ready-for-acceptance', 'needs-followup', 'blocked', 'failed'):
                    self.assertIn(f'`{status}`', text)
                for field in ('revision', 'binding', 'snapshot', 'path', 'sha256', 'bytes'):
                    self.assertIn(f'`{field}`', text)
                self.assertIn("`binding` to the brief's `snapshot`", text)
                self.assertIn('integer `bytes`', text)
                for severity in ('blocker', 'major', 'minor', 'note'):
                    self.assertIn(f'`{severity}`', text)
                self.assertIn('grants', text)  # no definition grants push/merge/settings edits
                if wid == 'imps/reviewer':
                    for verdict in ('approve', 'adverse', 'unavailable'):
                        self.assertIn(f'`{verdict}`', text)
                    self.assertIn('as a separate step, set `review_verdict`', text)
                else:
                    self.assertIn('Set `review_verdict` to null', text)
                    self.assertIn('`blocker` or `major` finding, set it to `adverse`', text)
                    self.assertIn('Never use `approve`', text)

    def test_stage_executor_is_the_bounded_verification_slot(self):
        text = ' '.join((PLUGIN / 'agents/stage-executor.md').read_text().split())
        self.assertIn('you are its verification slot', text)
        self.assertIn('Before each check, call `snapshot`', text)
        self.assertIn('Write only the assigned gate subtree and `artifacts/tasks/<task-id>/`', text)
        self.assertIn('Report the requirement as `unavailable` with the exact diagnostic', text)
        self.assertIn('Only the coordinator\'s stage gate `validate` decides acceptance', text)


class ImpsWholeJobTest(CoreTestCase):
    """A synthetic two-stage job through the installed package; results are fixtures."""

    def install(self, base, env, plugin):
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', plugin, '--prefix',
                               str(base / 'prefix'), '--agents-root', str(base / 'agents')],
                              capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        version = Path(json.loads(proc.stdout)['data']['version_dir'])
        return version, json.loads((version / 'install-manifest.json').read_text())

    def test_installed_job_runs_stage_gate_and_final_gate(self):
        base = self.tmp
        env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_CONFIG_HOME': str(base / 'config'),
               'XDG_STATE_HOME': str(base / 'xdg-state')}
        (base / 'home').mkdir()
        version, manifest = self.install(base, env, 'imps')
        baby_version, _ = self.install(base, env, 'babysitter')
        gates, jobs, private = base / 'gates', base / 'jobs', base / 'coordinator'
        private.mkdir()

        # The coordinator creates the stage gate run itself (parent thread recorded in the plan).
        self.state_root = gates / 'impl'
        repo = self.make_repo()
        from tests.imps_plan_review_fixtures import admitted_gate, select_legacy_imps_job
        run = admitted_gate(self, version, manifest, env, self.plan(repo, policy={'review': {'required': True, 'role': 'reviewer'}}))
        self.assertEqual(run.state['host']['parent_thread_id'], 'thread-parent-0001')
        validator = version / 'scripts' / 'validate_stage.py'
        stage_hash = hashlib.sha256(validator.read_bytes()).hexdigest()
        final_plan = {'state_root': str(gates), 'package_root': str(version), 'required_stages': ['impl'],
                      'stages': [{'id': 'impl', 'state_subdir': 'impl', 'run_id': run.run_id,
                                  'stage_sha256': stage_hash}]}
        plan_path = private / 'final-plan.json'
        plan_path.write_text(json.dumps(final_plan))

        caller = {'actor': 'coordinator', 'installation_id': manifest['installation_id'],
                  'workflow': 'imps/run', 'package_digest': manifest['package_digest']}
        gate = {'state_root': str(gates / 'impl'), 'run_id': run.run_id}
        job = {
            'schema_version': 1, 'job_id': 'imps-e2e', 'installation_id': manifest['installation_id'],
            'workflow': 'imps/run', 'owner': {'id': 'owner'}, 'objective': 'fix the multi-line count',
            'requirements': {'R1': 'count splits on any whitespace'},
            'authorization': {'actions': ['edit', 'local-checks']},
            'constraints': ['Do not change the CLI usage text.'],
            'dependencies': [{'key': 'imps', 'plugin': 'imps'}, {'key': 'babysitter', 'plugin': 'babysitter'}],
            'pins': {}, 'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
            'result_contract': {'schema_version': 1},
            'stages': [
                {'id': 'impl', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                 'execution_mode': 'workers', 'validator_dependency': 'imps', 'revision': 'impl-r1',
                 'validator_contract': gate, 'resources': {'gate': gate}},
                {'id': 'final', 'depends_on': ['impl'], 'requirements': ['R1'], 'status': 'pending',
                 'execution_mode': 'direct', 'validator_dependency': 'imps', 'revision': 'final-r1',
                 'validator_contract': {'final_plan': final_plan}}],
            'tasks': [{'task_id': 'impl-exec', 'stage_id': 'impl', 'logical_slot_id': 'primary',
                       'request_id': 'impl-exec-r0', 'worker_id': 'imps/stage-executor', 'dependency_key': 'imps',
                       'status': 'pending', 'attempt': 0, 'handles': [], 'followups': [], 'dispatch_retries': 0,
                       'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/impl-exec'}}],
            'decisions': [], 'history': [], 'metrics': {}}

        job_cli = version / 'shared' / 'job_cli.py'

        def call(script, *args, payload=None):
            argv = [sys.executable, str(script), *args]
            if payload is not None:
                path = private / f'input-{len(list(private.iterdir()))}.json'
                path.write_text(json.dumps(payload))
                argv += ['--input', str(path)]
            return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)

        def jobs_call(command, payload=None, *extra):
            return call(job_cli, command, '--state-root', str(jobs), '--job', 'imps-e2e', *extra, payload=payload)

        from tests.model_selection_fixtures import attach_selection
        select_legacy_imps_job(job, base, version, manifest, env)
        created = jobs_call('create', job, '--prefix', str(base / 'prefix'), '--agents-root', str(base / 'agents'),
                            '--config', str(base / 'config' / 'workers.json'))
        self.assertEqual(created.returncode, 0, created.stderr)
        job_file = jobs / 'imps-e2e' / 'job.json'

        # prs: babysitter resolves only through the declared job pin; undeclared plugins are refused.
        catalog = [sys.executable, str(ROOT / 'scripts/catalog.py'), '--prefix', str(base / 'prefix'),
                   '--agents-root', str(base / 'agents'), '--job', str(job_file), 'path']
        pinned = subprocess.run(catalog + ['babysitter'], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(pinned.returncode, 0, pinned.stderr)
        self.assertEqual(Path(pinned.stdout.strip()), baby_version / 'entry.md')
        undeclared = subprocess.run(catalog + ['ape'], capture_output=True, text=True, env=env, timeout=60)
        self.assertNotEqual(undeclared.returncode, 0)
        self.assertIn('undeclared job dependency', undeclared.stdout + undeclared.stderr)

        # Dispatch preparation prints only the brief locator; the brief carries the gate and the definition.
        prepared = jobs_call('prepare', {'caller': caller, 'task_id': 'impl-exec', 'target_reason': 'workhorse tier'})
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        locator = json.loads(prepared.stdout)
        self.assertEqual(set(locator), {'path', 'sha256', 'bytes', 'provenance'})
        raw = Path(locator['path']).read_bytes()
        self.assertEqual((hashlib.sha256(raw).hexdigest(), len(raw)), (locator['sha256'], locator['bytes']))
        from shared.compact_briefs import deserialize
        brief = deserialize(raw)
        self.assertEqual(brief['resources']['gate'], gate)
        definition = brief['effective_definition']['bytes'] if brief['schema_version'] == 1 else brief['definition']
        self.assertIn('you are its verification slot', ' '.join(definition.split()))
        if brief['schema_version'] == 2:
            self.assertEqual(brief['verification_tool']['argv_prefix'], ['python3', str(version / 'cli.py')])
            self.assertEqual(brief['verification_tool']['sha256'], hashlib.sha256((version / 'cli.py').read_bytes()).hexdigest())
        self.assertEqual(brief['constraints'], job['constraints'])

        def observe(brief, n):
            handle = {'request_id': brief['request_id'], 'host_task_id': f'host-task-{n}', 'child_thread_id': f'child-{n}'}
            selection = brief['model_selection']
            target = selection.get('dispatch', {}).get('target', selection.get('target'))
            for event in ({**handle, 'kind': 'accepted', 'status': 'running', 'work_state': 'working',
                           'has_pending_child_runs': False},
                          {**handle, 'kind': 'completion', 'completion_id': f'done-{n}', 'status': 'completed',
                           'work_state': 'result_available', 'has_pending_child_runs': False}):
                event['status_identity'] = {**target, 'options': target.get('options', {})}
                observed = jobs_call('task-observation', {'caller': caller, 'task_id': 'impl-exec', 'event': event})
                self.assertEqual(observed.returncode, 0, observed.stderr)

        def result_for(brief):
            result = {'schema_version': 1, 'status': 'ready-for-acceptance', 'conclusion': 'count fixed',
                      'requirements': [{'id': 'R1', 'status': 'passed', 'evidence': ['gate run evidence']}],
                      'review_verdict': None, 'findings': [], 'gaps': [], 'uncertainties': [], 'changes': [],
                      'commands': [], 'artifacts': [], 'binding': brief['snapshot'], 'extra_work_requests': [],
                      'metrics': {'tokens': {'value': None, 'reason': 'synthetic fixture'}}}
            for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id',
                        'effective_brief_sha256', 'revision'):
                result[key] = brief[key]
            return json.dumps(result)

        # A reply wrapped in prose is never extracted: it charges the attempt as a malformed result.
        observe(brief, 1)
        prose = jobs_call('result', {'caller': caller, 'task_id': 'impl-exec', 'request_id': brief['request_id'],
                                     'completion_id': 'done-1', 'result': {'json': 'Done!\n' + result_for(brief)}})
        self.assertEqual(prose.returncode, 0, prose.stderr)
        task = json.loads(prose.stdout)
        self.assertEqual((task['status'], task['last_execution_status'], task['attempt']),
                         ('failed', 'malformed-result', 1))
        repaired = jobs_call('retry', {'caller': caller, 'task_id': 'impl-exec', 'reason': 'malformed result'})
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        again = jobs_call('prepare', {'caller': caller, 'task_id': 'impl-exec', 'target_reason': 'workhorse tier'})
        self.assertEqual(again.returncode, 0, again.stderr)
        retry_brief = deserialize(Path(json.loads(again.stdout)['path']).read_bytes())
        self.assertNotEqual(retry_brief['request_id'], brief['request_id'])
        self.assertEqual(retry_brief['attempt'], 1)
        observe(retry_brief, 2)

        # The worker, as verification slot, submits evidence and a check, each with a binding captured first.
        artifact = run.scratch('impl-evidence.txt', 'verified fixture evidence\n')
        run.evidence('REQ-MULTILINE', artifact)
        self.assertEqual(self.run_check(run)['result']['status'], 'passed')
        # Without the required review the stage gate refuses: the validator, not the worker, decides.
        refused = subprocess.run([sys.executable, str(validator), '--state-root', gate['state_root'],
                                  '--run-id', run.run_id], capture_output=True, text=True, timeout=120)
        self.assertEqual(refused.returncode, 1)
        self.assertFalse(json.loads(refused.stdout)['accepted'])
        review_log = run.scratch('review.txt', 'reviewed the current binding; no findings\n')
        run.child(task_id='review-1', status='completed')
        run.submit('review', {'binding': run.binding(), 'task_id': 'review-1', 'perspective_id': 'default',
                              'verdict': 'approve', 'findings': [], 'artifacts': [str(review_log)]})

        ingested = jobs_call('result', {'caller': caller, 'task_id': 'impl-exec',
                                        'request_id': retry_brief['request_id'], 'completion_id': 'done-2',
                                        'result': {'json': result_for(retry_brief)}})
        self.assertEqual(ingested.returncode, 0, ingested.stderr)
        self.assertEqual(json.loads(ingested.stdout)['last_execution_status'], 'ready-for-acceptance')

        acceptance_cli = version / 'shared' / 'job_acceptance_cli.py'

        def accept(action, payload):
            return call(acceptance_cli, action, '--state-root', str(jobs), '--job', 'imps-e2e', payload=payload)

        # The worker could not run the gate here: record coordinator fallback in the bound descriptor.
        descriptor = private / 'impl-gate.json'
        descriptor.write_text(json.dumps({**gate, 'verification': 'coordinator-fallback',
                                          'reason': 'fixture: worker sandbox denied the gate state root'}))
        frozen = jobs_call('observation', {'caller': caller, 'stage_id': 'impl', 'input_file': str(descriptor)})
        self.assertEqual(frozen.returncode, 0, frozen.stderr)
        stage_argv = [str(validator), '--state-root', gate['state_root'], '--run-id', run.run_id]
        wrong = accept('accept-stage', {'caller': caller, 'stage_id': 'impl', 'revision': 'impl-r1',
                                        'input_file': json.loads(frozen.stdout)['path'],
                                        'validator_argv': stage_argv[:-1] + ['another-run']})
        self.assertNotEqual(wrong.returncode, 0)
        accepted = accept('accept-stage', {'caller': caller, 'stage_id': 'impl', 'revision': 'impl-r1',
                                           'input_file': json.loads(frozen.stdout)['path'],
                                           'validator_argv': stage_argv})
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertTrue(json.loads(accepted.stdout)['accepted'])

        # Final readiness: a new final gate over every declared stage gate at current inputs.
        final_descriptor = private / 'final-gate.json'
        final_descriptor.write_text(json.dumps({'state_root': str(gates), 'final_plan': str(plan_path)}))
        frozen_final = jobs_call('observation', {'caller': caller, 'stage_id': 'final',
                                                 'input_file': str(final_descriptor)})
        self.assertEqual(frozen_final.returncode, 0, frozen_final.stderr)
        final_argv = [str(validator), '--state-root', str(gates), '--final-plan', str(plan_path)]
        final_input = json.loads(frozen_final.stdout)['path']
        final = accept('accept-stage', {'caller': caller, 'stage_id': 'final', 'revision': 'final-r1',
                                        'input_file': final_input, 'validator_argv': final_argv})
        # Source readiness cannot certify the agreed Open PR endpoint from a
        # local-only fixture without a declared repository/delivery observation.
        self.assertNotEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertIn('declared repository worktree', final.stdout + final.stderr)
        overview = jobs_call('overview')
        self.assertEqual(overview.returncode, 0, overview.stderr)
        self.assertNotIn('Traceback', overview.stdout)
        stages = {s['id']: s['status'] for s in json.loads(job_file.read_text())['stages']}
        self.assertEqual(stages['impl'], 'accepted-at-snapshot')
        self.assertNotEqual(stages['final'], 'accepted-at-snapshot')

        # A regression injected after acceptance fails the fresh final gate.
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text() + '\n# injected regression\n')
        fresh = accept('validate-final', {'caller': caller, 'validator_argv_by_stage': {'final': final_argv},
                                          'input_file_by_stage': {'final': final_input}})
        self.assertEqual(fresh.returncode, 1, fresh.stdout + fresh.stderr)


if __name__ == '__main__':
    unittest.main()
