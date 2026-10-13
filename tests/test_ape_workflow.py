"""Ape coordinator workflow: routing, boundaries, worker contracts and a synthetic job.

The end-to-end cases drive the installed, pinned `job_cli.py`, `job_acceptance_cli.py`
and `validate_report.py` with synthetic host observations and worker results. Nothing
here calls a model, a T3 host or GitHub; live follow-up support stays unverified.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APE = ROOT / 'plugins' / 'ape'
OPERATIONS = ('doctor', 'forage', 'study', 'clean')
MODEL_ID = re.compile(r'\b(?:claude-(?:opus|sonnet|haiku)|gpt-\d|gemini-\d|o[134]-mini)', re.I)


def words(path):
    return len(path.read_text().split())


def section(text, heading):
    """Body of one `## heading` section of a Markdown file."""
    match = re.search(rf'^## {re.escape(heading)}\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not match:
        raise AssertionError(f'missing section {heading!r}')
    return match.group(1)


def operation_rows(text):
    rows = {}
    for line in text.splitlines():
        match = re.match(r'\| `(\w+)(?: [^`]*)?` \|(.*)\|(.*)\|$', line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


class ApeEntryRoutingTests(unittest.TestCase):
    def setUp(self):
        self.entry = (APE / 'entry.md').read_text()
        self.rows = operation_rows(self.entry)

    def test_every_manifest_operation_routes_with_its_meaning(self):
        manifest = json.loads((APE / 'plugin.json').read_text())
        self.assertEqual(manifest['operations'], list(OPERATIONS))
        self.assertEqual(set(self.rows), set(OPERATIONS))
        meanings = {'doctor': 'change nothing', 'forage': 'at most five', 'study': 'one pinned source',
                    'clean': 'explicit authorization'}
        for op, phrase in meanings.items():
            self.assertIn(phrase, self.rows[op][0], op)
        for op in ('forage', 'study', 'clean'):
            self.assertIn(f'`PKG/playbooks/{op}.md`', self.rows[op][1])
            self.assertTrue((APE / 'playbooks' / f'{op}.md').is_file())

    def test_cheap_operations_stay_direct(self):
        for op in ('doctor', 'clean'):
            self.assertIn('Direct', self.rows[op][1], op)
            self.assertIn('no agents', self.rows[op][1].lower(), op)
        clean = (APE / 'playbooks' / 'clean.md').read_text()
        self.assertIn('Never create a job or delegate', clean)
        for word in ('delegate_task', 'job_cli', 'followup'):
            self.assertNotIn(word, clean)

    def test_entry_names_coordination_protocol_and_every_loadable_file(self):
        named = set(re.findall(r'`PKG/([\w./-]+)`', self.entry))
        self.assertIn('shared/job-coordination.md', named)
        for required in ('shared/t3-runtime.md', 'shared/delegation.md', 'shared/learnings.md',
                         'scripts/validate_report.py'):
            self.assertIn(required, named)
        for folder in ('playbooks', 'references'):
            for path in (APE / folder).glob('*.md'):
                self.assertIn(f'{folder}/{path.name}', named, f'entry never names {folder}/{path.name}')
        for name in named - {'shared/job-coordination.md'}:
            self.assertTrue((APE / name).exists() or (ROOT / name).exists(), name)

    def test_shared_coordination_protocol_exists_once_integrated(self):
        target = ROOT / 'shared' / 'job-coordination.md'
        if not target.exists():
            self.skipTest('shared/job-coordination.md is written by the parallel shared Stage 4 owner')
        self.assertIn('job-coordination.md', (ROOT / 'shared' / 't3-runtime.md').read_text())

    def test_word_budgets(self):
        self.assertLess(words(APE / 'entry.md'), 1500)
        for path in [*(APE / 'playbooks').glob('*.md'), *(APE / 'references').glob('*.md'),
                     *(APE / 'agents').glob('*.md')]:
            self.assertLess(words(path), 700, path.name)

    def test_boundaries_and_picker_are_stated(self):
        bounds = section(self.entry, 'Boundaries')
        for phrase in ('read-only in the current project and in every target', 'never authorize',
                       'implementation', 'running an experiment', 'planning-to-engineering',
                       'at most five', 'SHA-256', 'marker-owned workspace', 'native question picker',
                       'Silence is not approval'):
            self.assertIn(phrase, ' '.join(bounds.split()), phrase)
        self.assertIn('native question picker', (APE / 'playbooks' / 'clean.md').read_text())

    def test_acceptance_authority_and_followup_policy(self):
        accept = ' '.join(section(self.entry, 'Acceptance').split())
        self.assertIn('`PKG/scripts/validate_report.py`', accept)
        self.assertIn('is not acceptance', accept)
        self.assertIn('validate-final', accept)
        follow = ' '.join(section(self.entry, 'Same-scope follow-up').split())
        for phrase in ('one declared follow-up', 'terminal with no pending runs', 'followup-prepare',
                       'immutable', 'new task ID', 'same request ID', 'reuse-fallback', 'owner decision'):
            self.assertIn(phrase, follow, phrase)
        visible = ' '.join(section(self.entry, 'Fallback and visibility').split())
        self.assertIn('fallback: direct (context isolation lost)', visible)
        self.assertIn('overview', visible)


class ApeWorkerDefinitionTests(unittest.TestCase):
    def test_manifest_workers_have_contract_definitions(self):
        manifest = json.loads((APE / 'plugin.json').read_text())
        self.assertEqual({w['id'] for w in manifest['workers']}, {'ape/source-researcher', 'ape/synthesizer'})
        for worker in manifest['workers']:
            text = (APE / worker['path']).read_text()
            flat = ' '.join(text.split())
            self.assertIn(f'worker_id: {worker["id"]}', text)
            self.assertIsNone(MODEL_ID.search(text), worker['id'])
            for phrase in ('check its SHA-256', 'Never dispatch children', 'accept your own work',
                           'exactly one JSON object', 'worker-result.schema.json', 'version 1',
                           '`ready-for-acceptance`, `needs-followup`, `blocked` or `failed`',
                           'severity (blocker, major, minor, note)', '`review_verdict` is null unless',
                           'Redact', 'never widens'):
                self.assertIn(phrase, flat, (worker['id'], phrase))
            for action in ('push', 'merge', 'edit settings'):
                self.assertRegex(flat, rf'Never [^.]*{action}', (worker['id'], action))
            self.assertRegex(flat, r'never authorizes? implementation|not authorization: do not implement')

    def test_source_researcher_is_read_only_on_targets(self):
        flat = ' '.join((APE / 'agents' / 'source-researcher.md').read_text().split())
        self.assertIn('Never run, build, test or install third-party code', flat)
        self.assertIn('Write only inside your `artifacts/tasks/<task-id>/` subtree', flat)


class Installed:
    def __init__(self, case, base):
        self.base = base
        home = base / 'home'
        home.mkdir()
        self.prefix, self.agents, self.state = base / 'prefix', base / 'agents', base / 'state'
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(base / 'config'),
               'XDG_STATE_HOME': str(base / 'xdg-state')}
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'ape',
                               '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                              capture_output=True, text=True, env=env, timeout=120)
        case.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.version = Path(json.loads(proc.stdout)['data']['version_dir'])
        self.manifest = json.loads((self.version / 'install-manifest.json').read_text())
        self.validator = self.version / 'scripts' / 'validate_report.py'
        self.case = case
        self.seq = 0

    def caller(self, workflow):
        return {'installation_id': self.manifest['installation_id'], 'workflow': workflow,
                'package_digest': self.manifest['package_digest'], 'actor': 'coordinator'}

    def write(self, name, data):
        self.seq += 1
        path = self.base / f'{self.seq:03d}-{name}.json'
        path.write_text(json.dumps(data))
        return path

    def cli(self, script, command, job, data=None, expect=0, extra=()):
        argv = [sys.executable, str(self.version / 'shared' / script), command,
                '--state-root', str(self.state), '--job', job, *extra]
        if data is not None:
            argv += ['--input', str(self.write(command, data))]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        self.case.assertEqual(proc.returncode, expect, (command, proc.stdout, proc.stderr))
        self.stderr = proc.stderr
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def job(self, *args, **kw):
        return self.cli('job_cli.py', *args, **kw)

    def accept(self, *args, **kw):
        return self.cli('job_acceptance_cli.py', *args, **kw)

    def create(self, job):
        return self.job('create', job['job_id'], job, extra=('--prefix', str(self.prefix), '--agents-root',
                                                             str(self.agents), '--config',
                                                             str(self.base / 'config' / 'workers.json')))

    def validate(self, report):
        path = self.write('direct-report', report)
        proc = subprocess.run([sys.executable, str(self.validator), '--input', str(path)],
                              capture_output=True, text=True, timeout=60)
        return proc.returncode, json.loads(proc.stdout)


from tests.test_ape_validate_report import (CRITERIA, descriptor, fingerprint, pin_source,  # noqa: E402
                                             research_findings, research_markdown, synthesis_descriptor,
                                             synthesis_findings, synthesis_markdown)


def research_task(task_id, stage_id, worker='ape/source-researcher', followups=1):
    return {'task_id': task_id, 'stage_id': stage_id, 'logical_slot_id': 'primary', 'request_id': 'req-' + task_id,
            'worker_id': worker, 'dependency_key': 'ape', 'status': 'pending', 'attempt': 0, 'handles': [],
            'followups': [], 'dispatch_retries': 0, 'dispatch_history': [], 'max_followups': followups,
            'write_scope': {'mode': 'worker-evidence', 'path': f'artifacts/tasks/{task_id}'}}


def stage(stage_id, requirements, sources, depends_on=()):
    return {'id': stage_id, 'depends_on': list(depends_on), 'requirements': requirements, 'status': 'pending',
            'validator_dependency': 'ape', 'revision': 'rev-1', 'criteria': CRITERIA,
            'validator_contract': {'sources': sources},
            'attempts': {'primary': 0, 'support': 0, 'review': 0, 'final': 0}}


def plan(installed, job_id, workflow, requirements, stages, tasks):
    return {'schema_version': 1, 'job_id': job_id, 'installation_id': installed.manifest['installation_id'],
            'workflow': workflow, 'owner': {'id': 'owner-fixture'}, 'objective': 'synthetic ape research',
            'requirements': requirements, 'authorization': {'actions': ['read']},
            'constraints': ['no writes to the current project or targets'],
            'dependencies': [{'key': 'ape', 'plugin': 'ape'}], 'pins': {},
            'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
            'result_contract': {'schema_version': 1}, 'stages': stages, 'tasks': tasks,
            'decisions': [], 'history': [], 'metrics': {}}


class ApeSyntheticJobTests(unittest.TestCase):
    """Synthetic coordinator runs through the installed pinned helpers."""

    def worker_result(self, brief_path, status='ready-for-acceptance', artifact=None):
        brief = json.loads(Path(brief_path).read_text())
        result = {'schema_version': 1, 'status': status, 'conclusion': 'synthetic comparison',
                  'requirements': [{'id': r['id'], 'status': 'passed', 'evidence': ['report.md']}
                                   for r in brief['requirements']],
                  'review_verdict': None, 'findings': [], 'gaps': [], 'uncertainties': [], 'changes': [],
                  'commands': [], 'artifacts': [artifact] if artifact else [], 'binding': brief['snapshot'],
                  'extra_work_requests': [], 'metrics': {'tokens': {'value': None, 'reason': 'synthetic'}}}
        for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256',
                    'revision'):
            result[key] = brief[key]
        return result

    def worker_report(self, ins, job_id, task_id, stage_id, workflow, body):
        from core.jobs import worker_write
        from shared.job_coordinator import pinned_store
        store = pinned_store(ins.state, job_id)
        task = next(t for t in store.load()['tasks'] if t['task_id'] == task_id)
        worker = {**ins.caller(workflow), 'actor': 'worker', 'task_id': task_id, 'stage_id': stage_id,
                  'scope': task['write_scope']}
        written = worker_write(store, worker, task_id, f'artifacts/tasks/{task_id}/report.md', body.encode())
        return written

    def run_task(self, ins, job_id, workflow, task_id, stage_id, body, host, status='ready-for-acceptance'):
        caller = ins.caller(workflow)
        prepared = ins.job('prepare', job_id, {'caller': caller, 'task_id': task_id,
                                               'target_reason': 'lowest suitable workhorse (synthetic)'})
        self.assertEqual(set(prepared), {'path', 'sha256', 'bytes', 'provenance'})
        self.assertEqual(hashlib.sha256(Path(prepared['path']).read_bytes()).hexdigest(), prepared['sha256'])
        request = prepared['provenance']['request_id']
        ins.job('task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': {
            'kind': 'accepted', 'request_id': request, 'host_task_id': host, 'child_thread_id': 'thread-' + host,
            'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False}})
        report = self.worker_report(ins, job_id, task_id, stage_id, workflow, body)
        ins.job('task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': {
            'kind': 'completion', 'request_id': request, 'host_task_id': host, 'completion_id': 'done-' + host,
            'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False}})
        result = self.worker_result(prepared['path'], status,
                                    {'path': f'artifacts/tasks/{task_id}/report.md', 'sha256': report['sha256'],
                                     'bytes': report['bytes']})
        ins.job('result', job_id, {'caller': caller, 'task_id': task_id, 'request_id': request,
                                   'completion_id': 'done-' + host, 'result': {'json': json.dumps(result)}})
        from shared.job_coordinator import pinned_store
        task = next(t for t in pinned_store(ins.state, job_id).load()['tasks'] if t['task_id'] == task_id)
        expected = 'awaiting-followup' if status == 'needs-followup' else 'awaiting-acceptance'
        self.assertEqual(task['status'], expected, task.get('execution_history'))
        return prepared, Path(report['path'])

    def freeze(self, ins, job_id, workflow, stage_id, data):
        path = ins.write('descriptor-' + stage_id, data)
        return ins.job('observation', job_id, {'caller': ins.caller(workflow), 'stage_id': stage_id,
                                               'input_file': str(path)})['path']

    @staticmethod
    def report_pin(path):
        path = Path(path)
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_study_job_runs_tracked_followup_and_accepts_through_pinned_validator(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ins = Installed(self, base)
            src = pin_source(base, 'src-1')
            job = plan(ins, 'ape-study', 'ape/study', {'R-SRC-1': 'pinned comparison of src-1'},
                       [stage('research', ['R-SRC-1'], [src])], [research_task('source-1', 'research')])
            ins.create(job)
            caller = ins.caller('ape/study')
            overview = ins.job('overview', 'ape-study')
            self.assertEqual([s['id'] for s in overview['stages']], ['research'])

            # Original execution asks for a same-scope follow-up.
            original, report_path = self.run_task(ins, 'ape-study', 'ape/study', 'source-1', 'research',
                                                  research_markdown(src), 'host-1', 'needs-followup')
            original_bytes = Path(original['path']).read_bytes()
            followup = ins.job('followup-prepare', 'ape-study',
                               {'caller': caller, 'task_id': 'source-1', 'request_id': 'req-source-1-fu1'})
            fu_brief = json.loads(Path(followup['path']).read_text())
            self.assertEqual((fu_brief['followup_of'], fu_brief['request_id']), ('req-source-1', 'req-source-1-fu1'))
            self.assertEqual(fu_brief['worker_id'], 'ape/source-researcher')
            # A second follow-up in the same slot exceeds the one declared follow-up.
            event = {'kind': 'followup', 'request_id': 'req-source-1-fu1', 'host_task_id': 'host-1-fu',
                     'parent_host_task_id': 'host-1', 'child_thread_id': 'thread-host-1', 'target': None,
                     'scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/source-1'}}
            ins.job('task-observation', 'ape-study', {'caller': caller, 'task_id': 'source-1', 'event': event})
            ins.job('task-observation', 'ape-study', {'caller': caller, 'task_id': 'source-1', 'event': {
                'kind': 'completion', 'request_id': 'req-source-1-fu1', 'host_task_id': 'host-1-fu',
                'completion_id': 'done-host-1-fu', 'status': 'completed', 'work_state': 'result_available',
                'has_pending_child_runs': False}})
            result = self.worker_result(followup['path'])
            ins.job('result', 'ape-study', {'caller': caller, 'task_id': 'source-1', 'request_id': 'req-source-1-fu1',
                                            'completion_id': 'done-host-1-fu', 'result': {'json': json.dumps(result)}})
            ins.job('followup-prepare', 'ape-study',
                    {'caller': caller, 'task_id': 'source-1', 'request_id': 'req-source-1-fu2'}, expect=2)
            self.assertIn('declared slot', ins.stderr)
            self.assertEqual(Path(original['path']).read_bytes(), original_bytes, 'original brief is immutable')
            from shared.job_coordinator import pinned_store
            task = pinned_store(ins.state, 'ape-study').load()['tasks'][0]
            hosts = [h.get('host_task_id', h.get('task_id')) for h in task['handles'] + task['followups']]
            self.assertEqual(hosts, ['host-1', 'host-1-fu'])

            data = descriptor('study', [src], [{'id': 'R-SRC-1', 'source_ids': ['src-1']}], fingerprint(base),
                              self.report_pin(report_path), research_findings(src))
            # The validator rejects an unconfirmed quote without spending the stage budget.
            invented = json.loads(json.dumps(data))
            invented['findings'][0]['quote'] = 'invented'
            code, verdict = ins.validate(invented)
            self.assertEqual((code, verdict['accepted']), (1, False))
            # It also rejects a report the coordinator has not recorded inspecting.
            uninspected = {**data, 'inspections': [r for r in data['inspections'] if r['category'] != 'adopt']}
            code, verdict = ins.validate(uninspected)
            self.assertEqual((code, verdict['accepted']), (1, False))
            self.assertIn('receipt for adopt finding',
                          verdict['requirement_outcomes']['report-acceptance']['evidence']['reason'])
            # The adapter binds the declared operation and requirements to the stage before running it.
            for wrong in ({**data, 'operation': 'forage-research'},
                          {**data, 'requirements': [{'id': 'R-OTHER', 'source_ids': ['src-1']}]}):
                bad = self.freeze(ins, 'ape-study', 'ape/study', 'research', wrong)
                ins.accept('accept-stage', 'ape-study', {'caller': caller, 'stage_id': 'research', 'revision': 'rev-1',
                                                         'validator_argv': [str(ins.validator), '--input', bad],
                                                         'input_file': bad}, expect=2)
                self.assertRegex(ins.stderr, 'operation differs|requirements differ')
            observation = self.freeze(ins, 'ape-study', 'ape/study', 'research', data)
            argv = [str(ins.validator), '--input', observation]
            receipt = ins.accept('accept-stage', 'ape-study', {'caller': caller, 'stage_id': 'research',
                                                               'validator_argv': argv, 'input_file': observation,
                                                               'revision': 'rev-1'})
            self.assertTrue(receipt['accepted'], receipt)
            final = ins.accept('validate-final', 'ape-study', {'caller': caller,
                                                               'validator_argv_by_stage': {'research': argv},
                                                               'input_file_by_stage': {'research': observation}})
            self.assertTrue(final['accepted'], final)

            # Changing a pinned source after acceptance withdraws it.
            Path(src['path']).write_text('def retry(call):\n    pass\n')
            ins.accept('validate', 'ape-study', {'stage_id': 'research'}, expect=1)

    def test_forage_synthesis_waits_for_accepted_research_and_caps_five_sources(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ins = Installed(self, base)
            sources = [pin_source(base, f'src-{n}') for n in (1, 2)]
            stages = [stage(f'research-{n}', [f'R-SRC-{n}'], [sources[n - 1]]) for n in (1, 2)]
            for n in (1, 2):
                stages[n - 1]['outputs'] = [str(ins.state / 'ape-forage' / f'artifacts/tasks/source-{n}/report.md')]
            # Synthesis pins every candidate snapshot up front, so its contract never changes mid-job.
            stages.append(stage('synthesis', ['R-SYNTH'], sources, depends_on=['research-1', 'research-2']))
            tasks = [research_task(f'source-{n}', f'research-{n}', followups=0) for n in (1, 2)]
            tasks.append(research_task('synth', 'synthesis', 'ape/synthesizer', followups=0))
            requirements = {'R-SRC-1': 'compare src-1', 'R-SRC-2': 'compare src-2', 'R-SYNTH': 'compare reports'}
            job = plan(ins, 'ape-forage', 'ape/forage', requirements, stages, tasks)
            ins.create(job)
            caller = ins.caller('ape/forage')
            # Synthesis cannot start before its research dependencies are accepted.
            ins.job('prepare', 'ape-forage', {'caller': caller, 'task_id': 'synth'}, expect=2)
            self.assertIn('predecessor acceptance is not current', ins.stderr)
            argv, inputs, consumed = {}, {}, []
            for n in (1, 2):
                pin = sources[n - 1]
                _, path = self.run_task(ins, 'ape-forage', 'ape/forage', f'source-{n}', f'research-{n}',
                                        research_markdown(pin), f'host-{n}')
                self.assertEqual(str(path), stages[n - 1]['outputs'][0])
                consumed.append({'id': f'rep-{n}', 'source_id': pin['id'], **self.report_pin(path)})
                obs = self.freeze(ins, 'ape-forage', 'ape/forage', f'research-{n}', descriptor(
                    'forage-research', [pin], [{'id': f'R-SRC-{n}', 'source_ids': [pin['id']]}], fingerprint(base),
                    consumed[-1], research_findings(pin)))
                argv[f'research-{n}'], inputs[f'research-{n}'] = [str(ins.validator), '--input', obs], obs
                receipt = ins.accept('accept-stage', 'ape-forage', {
                    'caller': caller, 'stage_id': f'research-{n}', 'revision': 'rev-1', 'input_file': obs,
                    'validator_argv': argv[f'research-{n}']})
                self.assertTrue(receipt['accepted'], receipt)
            prepared, synth_path = self.run_task(ins, 'ape-forage', 'ape/forage', 'synth', 'synthesis',
                                                 synthesis_markdown(sources, consumed), 'host-synth')
            brief = json.loads(Path(prepared['path']).read_text())
            self.assertEqual(brief['worker_id'], 'ape/synthesizer')
            self.assertEqual(brief['authorization'], {'actions': ['read']})
            # The synthesizer reads exactly the accepted research reports.
            self.assertEqual(brief['consumed_outputs'], [stages[0]['outputs'][0], stages[1]['outputs'][0]])
            for path in brief['consumed_outputs']:
                self.assertIn('## Provenance', Path(path).read_text())
            synthesis = descriptor('forage-synthesis', sources, [{'id': 'R-SYNTH', 'source_ids': ['src-1', 'src-2']}],
                                   fingerprint(base), self.report_pin(synth_path),
                                   synthesis_findings(sources, consumed), consumed)
            # Synthesis must consume exactly the accepted dependency outputs, not another copy.
            elsewhere = json.loads(json.dumps(synthesis))
            elsewhere['consumed_reports'][0]['path'] = str(base / 'copy.md')
            bad = self.freeze(ins, 'ape-forage', 'ape/forage', 'synthesis', elsewhere)
            ins.accept('accept-stage', 'ape-forage', {'caller': caller, 'stage_id': 'synthesis', 'revision': 'rev-1',
                                                      'input_file': bad,
                                                      'validator_argv': [str(ins.validator), '--input', bad]},
                       expect=2)
            self.assertIn('accepted dependency outputs', ins.stderr)
            obs = self.freeze(ins, 'ape-forage', 'ape/forage', 'synthesis', synthesis)
            argv['synthesis'], inputs['synthesis'] = [str(ins.validator), '--input', obs], obs
            receipt = ins.accept('accept-stage', 'ape-forage', {'caller': caller, 'stage_id': 'synthesis',
                                                                'revision': 'rev-1', 'input_file': obs,
                                                                'validator_argv': argv['synthesis']})
            self.assertTrue(receipt['accepted'], receipt)
            final = ins.accept('validate-final', 'ape-forage', {'caller': caller, 'validator_argv_by_stage': argv,
                                                                'input_file_by_stage': inputs})
            self.assertTrue(final['accepted'], final)

            # Six candidates exceed the forage cap at the authoritative validator.
            code, verdict = ins.validate(synthesis_descriptor(base / 'six', 6))
            self.assertEqual((code, verdict['accepted']), (1, False))
            self.assertIn('at most 5 candidates',
                          verdict['requirement_outcomes']['report-acceptance']['evidence']['reason'])
            code, verdict = ins.validate(synthesis_descriptor(base / 'five', 5))
            self.assertEqual((code, verdict['accepted']), (0, True))

    def test_worker_cannot_widen_scope_or_accept_and_extra_slot_needs_owner(self):
        from core.jobs import JobError, worker_write
        from shared.job_coordinator import pinned_store
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ins = Installed(self, base)
            src = pin_source(base, 'src-1')
            job = plan(ins, 'ape-bounds', 'ape/study', {'R-SRC-1': 'compare src-1'},
                       [stage('research', ['R-SRC-1'], [src])], [research_task('source-1', 'research')])
            ins.create(job)
            store = pinned_store(ins.state, 'ape-bounds')
            worker = {**ins.caller('ape/study'), 'actor': 'worker', 'task_id': 'source-1', 'stage_id': 'research',
                      'scope': store.load()['tasks'][0]['write_scope']}
            with self.assertRaisesRegex(JobError, 'scope|outside|confined|owned'):
                worker_write(store, worker, 'source-1', 'artifacts/tasks/other/report.md', b'x')
            written = worker_write(store, worker, 'source-1', 'artifacts/tasks/source-1/report.md', b'in scope')
            self.assertEqual(Path(written['path']).read_bytes(), b'in scope')
            # Worker identity cannot use coordinator operations such as observation or acceptance.
            descriptor = ins.write('worker-descriptor', {'sources': [src], 'findings': [], 'criteria': CRITERIA[:1]})
            ins.job('observation', 'ape-bounds', {'caller': worker, 'stage_id': 'research',
                                                  'input_file': str(descriptor)}, expect=2)
            self.assertIn('coordinator-only', ins.stderr)
            # A sixth candidate (or any added slot) is undeclared expansion without an owner decision.
            wider = store.load()
            wider['tasks'].append(research_task('source-2', 'research', followups=0))
            ins.job('plan-revision', 'ape-bounds', {'caller': ins.caller('ape/study'), 'revision': {'id': 'add-slot'},
                                                    'new_plan': wider}, expect=2)
            self.assertIn('undeclared_expansion', ins.stderr)
            self.assertEqual(len(store.load()['tasks']), 1)


if __name__ == '__main__':
    unittest.main()
