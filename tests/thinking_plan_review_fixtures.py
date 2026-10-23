"""Real planning-job fixtures shared by thinking's public-flow regressions.

Only host observations are synthetic. No receipt, validator or gate is mocked.
"""
import json
from pathlib import Path
import re
import sys

from shared import model_selection as models
from tests.model_selection_fixtures import selection_input, replacement, answer
from tests.test_rebuild_installed import Sandbox, ROOT


def upfront_selection(slug, plugin='elephant-goldfish', operation='thinking', output_root='thinking'):
    """Fixture answer obtained before topic creation, never at review time."""
    from shared import planning_review as p
    data = json.loads(json.dumps(selection_input()).replace('alpha-work', 'gpt-fixture').replace(
        'beta-review', 'claude-fixture').replace('gamma-spare', 'gemini-fixture').replace(
        '"alpha"', '"openai"').replace('"beta"', '"anthropic"').replace('"gamma"', '"google"'))
    data.update(operation=plugin + '/' + operation, scope_id=p.logical_output_id(
        'fixture:request:' + slug, output_root + '/' + slug + '/handoff.md'))
    data['coordinator']['lineage'] = 'openai'
    data['review_panel'][0]['independent'] = False
    row = replacement(data, data['coordinator'], review=True)
    row.pop('target'); row['execution'] = 'self-review'
    data['review_replacements'].append(row)
    return models.freeze(data)


def init_selection_args(directory, slug, **workflow):
    path = Path(directory) / ('selection-' + slug + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(upfront_selection(slug, **workflow)))
    return ['--selection', str(path), '--request-reference', 'fixture:request:' + slug]


class ThinkingPlanFixture:
    plugin = 'elephant-goldfish'
    operation = 'thinking'
    output_root = 'thinking'
    state_script = 'thinking_state.py'
    def __init__(self, base):
        self.box = Sandbox(Path(base))
        self.package = self.manifest = None
        self.jobs = {}
        self.count = 0

    def install(self):
        if self.package is None:
            self.package, self.manifest = self.box.install(self.plugin)
        return self.package

    def command(self, scripts, root, slug, command, *args, ok=True):
        if command == 'init' and '--selection' not in args:
            args = (*args, *init_selection_args(self.box.private, slug, plugin=self.plugin,
                                               operation=self.operation, output_root=self.output_root))
        proc = self.box.run([sys.executable, scripts / self.state_script, '--root', root,
                             command, slug, *args], check=False)
        if proc.returncode != (0 if ok else 1):
            raise AssertionError(proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def cli(self, command, data=None, ok=True):
        payload = dict(data or {})
        if command not in ('create', 'validate'):
            payload.setdefault('caller', self.caller)
        argv = [sys.executable, self.package / 'shared/planning_review_cli.py', command,
                '--input', self.box.payload(payload), '--state-root', self.box.jobs, '--job', self.job_id]
        if command == 'create':
            argv += ['--prefix', self.box.prefix, '--agents-root', self.box.agents]
        proc = self.box.run(argv, check=False)
        if proc.returncode != (0 if ok else 2):
            raise AssertionError(proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if ok else proc.stderr

    def prepare(self, scripts, root, slug, *, template_dir=None, attachments=(), evidence=()):
        self.install()
        topic = Path(root).absolute() / slug
        reqs = list(dict.fromkeys(re.findall(r'\[(REQ-[A-Z0-9_-]+)\]', (topic / 'spec.md').read_text())))
        request = self.box.private / (slug + '-request.txt')
        request.write_text('Produce the declared safe fixture plan and its observable acceptance.')
        decision = self.box.private / (slug + '-decision.txt')
        decision.write_text('Keep execution separately authorised.')
        def verbatim(path, ref):
            return {'path': str(path), 'reference': ref, 'clauses': [
                {'start': 0, 'end': len(path.read_text()), 'requirement': reqs[0]}]}
        repo = self.box.base / 'repository'
        if not repo.exists():
            repo.mkdir()
            self.box.run(['git', 'init', '-q', repo])
            self.box.run(['git', '-C', repo, '-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                          'commit', '-qm', 'fixture', '--allow-empty'])
        source = repo / 'source.py'
        if not source.exists():
            source.write_text('VALUE = 1\n')
        inputs = {'requests': [verbatim(request, 'fixture:request:' + slug)],
                  'decisions': [verbatim(decision, 'fixture:decision:' + slug)],
                  'requirements': {r: 'Fixture acceptance ' + r for r in reqs},
                  'load_bearing_decisions': ['D1'], 'attachments': list(map(str, attachments)),
                  'repository_root': str(repo), 'evidence_paths': [str(source), *map(str, evidence)]}
        args = ['--input', str(self.box.payload(inputs))]
        if template_dir:
            args += ['--template-dir', str(template_dir)]
        prepared = self.command(scripts, root, slug, 'plan-review', *args)
        self.snapshot = prepared['snapshot']
        self.inputs = inputs
        return prepared

    def begin(self, *, direct=False, rounds=12):
        scope = self.snapshot['logical_output_id']
        self.count += 1
        if scope in self.jobs:
            self.job_id, self.caller, self.selection = self.jobs[scope]
            self.cli('begin', {'snapshot': self.snapshot})
            return
        self.job_id = 'thinking-' + str(self.count)
        self.selection = self.snapshot['thinking_admission']['selection']
        made = self.cli('create', {'job_id': self.job_id, 'installation_id': self.manifest['installation_id'],
            'plugin': self.plugin, 'project_id': self.selection['project_id'], 'owner': 'fixture-owner',
            'invocation_id': self.selection['invocation_id'], 'scope_id': scope,
            'selection': self.selection, 'snapshot': self.snapshot})
        self.caller = made['caller']
        if rounds > 3:
            source = answer('Fixture owner permits ' + str(rounds) + ' content rounds for boundary scenarios.')
            source_file = self.box.private / ('budget-' + self.job_id + '.txt')
            source_file.write_text(source['answer'])
            self.cli('owner-decision', {'decision': {'kind': 'limit-increase',
                'logical_output_id': scope, 'round_limit': rounds, 'technical_limit': 2 * rounds,
                'source': source, 'source_file': str(source_file)}})
        self.jobs[scope] = (self.job_id, self.caller, self.selection)
        self.cli('begin')

    def assessment(self):
        return {'coverage': [{'id': r, 'outcome': 'supported', 'evidence': 'fixture:counterexample-and-source'}
                             for r in [*self.snapshot['requirements'], *self.snapshot['load_bearing_decisions']]],
                'inspected_paths': self.snapshot['declared_paths'], 'responses': []}

    def approve(self, scripts, root, slug, *, direct=False, attach=True, **kwargs):
        self.prepare(scripts, root, slug, **kwargs)
        self.begin(direct=direct)
        attempt = self.cli('launch', {'slot_id': 'review', 'request_id': self.job_id + '-request-' + str(self.count)})
        if direct:
            self.cli('unavailable', {'task_id': attempt['task_id'], 'failure': {'kind': 'technical',
                'tool': 'fixture-delegate', 'call_id': 'fixture-call', 'request_id': attempt['request_id'],
                'receipt': {'error': 'fixture prelaunch unavailable'}, 'prelaunch': True}})
            self.cli('direct', {'observation': {'schema_version': 1, 'kind': 'planning-direct',
                'pass_id': 'fixture-self-pass', 'identity': {k: self.selection['coordinator'][k]
                    for k in ('providerInstanceId', 'model', 'observed_options')},
                'identity_reference': 'fixture:active-session', 'snapshot_sha256': self.snapshot['sha256'],
                'selection_sha256': self.selection['selection_sha256'], 'review_verdict': 'approve', 'findings': [],
                'requirements': [{'id': r, 'status': 'passed', 'evidence': 'fixture:self-check'} for r in self.snapshot['requirements']],
                'assessment': self.assessment()}})
        else:
            target = attempt['target']
            self.cli('host-event', {'task_id': attempt['task_id'], 'event': {'kind': 'accepted',
                'request_id': attempt['request_id'], 'host_task_id': 'host-' + attempt['request_id'],
                'child_thread_id': 'child-' + attempt['request_id'], 'status': 'completed',
                'work_state': 'result_available', 'has_pending_child_runs': False,
                'status_identity': {k: target[k] for k in ('providerInstanceId', 'model', 'options')}}})
            brief = json.loads(Path(attempt['path']).read_text())
            result = {k: brief[k] for k in ('schema_version', 'job_id', 'stage_id', 'logical_slot_id', 'request_id',
                                           'worker_id', 'effective_brief_sha256', 'revision')}
            result.update(status='ready-for-acceptance', conclusion='Fixture source and counterexamples support the plan.',
                requirements=[{'id': r['id'], 'status': 'passed', 'evidence': 'fixture:observed'} for r in brief['requirements']],
                review_verdict='approve', findings=[], gaps=[], uncertainties=[], changes=[], commands=[], artifacts=[],
                binding=brief.get('snapshot'), extra_work_requests=[], metrics={}, planning_review=self.assessment())
            self.cli('result', {'task_id': attempt['task_id'], 'result_file': str(self.box.payload(result)),
                                'completion_id': 'fixture-completion-' + str(self.count)})
        completed = self.cli('finish')
        if not completed['accepted']:
            raise AssertionError(completed)
        self.reference = completed['reference']
        if attach:
            return self.command(scripts, root, slug, 'plan-review', '--receipt', self.reference['path'])
        return completed
