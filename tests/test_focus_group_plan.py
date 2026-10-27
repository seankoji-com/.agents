"""focus-group FG-1: command routing, editable panel planning, limits and the study contract.

Every check runs `plugins/focus-group/scripts/study.py` (or the installed copy) as a
subprocess against temporary job roots, invented personas and an invented model
catalog. Nothing calls a model, a browser, T3 or GitHub. These are local contract
fixtures; dispatch, ingestion and cancellation through T3 are integrated later.
"""
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
from tests import focus_group_fixtures as fixtures  # noqa: E402
# Package-qualified: installed fixtures import this module as tests.test_focus_group_plan.
from tests.support import skill_manifest, source_entry  # noqa: E402
from tests.test_model_ids import MODEL_ID  # noqa: E402

PLUGIN = ROOT / 'plugins' / 'focus-group'
HELPER = PLUGIN / 'scripts' / 'study.py'
TEMPLATE = PLUGIN / 'templates' / 'study-draft.example.json'
OPERATIONS = ['plan', 'run', 'resume', 'status', 'cancel', 'doctor']
WORKERS = ('focus-group/participant', 'focus-group/analyst', 'focus-group/fidelity-reviewer', 'focus-group/plan-reviewer')
BEFORE, AFTER = '2029-06-01T00:00:00Z', '2030-01-01T00:00:01Z'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def provider(pid, models, runnable=True, options=None):
    return {'providerInstanceId': pid, 'driverKind': pid, 'displayName': pid, 'canRunChildTask': runnable,
            'models': [{'id': m, 'options': options or []} for m in models], 'constraints': []}


EFFORT = [{'id': 'reasoningEffort', 'type': 'select', 'options': [{'id': 'low'}, {'id': 'high'}]}]
CAPS = {'providers': [provider('fixture-a', ['alpha-swift', 'alpha-deep'], options=EFFORT),
                      provider('fixture-b', ['beta-one']), provider('fixture-c', ['gamma-pro']),
                      provider('fixture-off', ['delta-x'], runnable=False)]}
ALPHA_ONLY = {'providers': [provider('fixture-a', ['alpha-swift', 'alpha-deep'])]}
ALL_CLASSES = ['stimulus', 'persona', 'participant-response', 'journey-evidence', 'analysis-report']
# Journeys need a verified fixture context binding, which only a fixture-environment target accepts.
FIXTURE_ORIGIN = 'http://127.0.0.1:9'
FIXTURE_TARGET = {'kind': 'url', 'url': FIXTURE_ORIGIN + '/welcome', 'environment': 'fixture',
                  'label': 'Invented loopback Pantry Planner prototype'}
DELIVERED = {'state': 'delivered', 'source': 'fixture attachment receipt'}


def target(pid, model, **options):
    return {'providerInstanceId': pid, 'model': model, 'options': options}


class Workspace:
    """One temporary job root, pack and capability file."""

    def __init__(self, base: Path, helper=HELPER):
        self.base, self.helper = base, helper
        self.policy_env = {'XDG_STATE_HOME': str(base / 'policy-state')}
        self.root = base / 'jobs'
        self.inputs = base / 'inputs'
        self.inputs.mkdir()
        self.pack = base / 'pack'
        self.pack_files = fixtures.write_pack(self.pack)
        self.image = self.pack / 'initial-viewport.png'
        self.caps = self.write('caps.json', CAPS)
        self.counter = 0
        self.stimuli = {}
        self.briefs, self.contexts = {}, {}

    def stimulus(self, study_id):
        """The invented pack validated for this study (FG-2: approval needs a recorded, cleared pack)."""
        if study_id not in self.stimuli:
            path = self.write(f'manifest-{study_id}.json', fixtures.manifest(self.pack_files))
            proc = subprocess.run([sys.executable, str(self.helper.with_name('evidence.py')), 'pack', '--state-root',
                                   str(self.root), '--study', study_id, '--input', str(path)],
                                  capture_output=True, text=True, timeout=60, cwd=self.base)
            assert proc.returncode == 0, proc.stdout + proc.stderr
            self.stimuli[study_id] = dict(json.loads(proc.stdout)['data']['stimulus'], coordinator_inspected=True)
        return copy.deepcopy(self.stimuli[study_id])

    def write(self, name, data):
        path = self.inputs / name
        path.write_text(json.dumps(data))
        return path

    def call(self, *args, now=None):
        argv = [sys.executable, str(self.helper), *map(str, args)]
        if now:
            argv += ['--now', now]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=self.base,
                              env={**os.environ, **self.policy_env, 'PYTHONDONTWRITEBYTECODE': '1'})
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (proc.stdout, proc.stderr)
        return proc.returncode, json.loads(lines[0])

    def call_evidence(self, *args):
        proc = subprocess.run([sys.executable, str(self.helper.with_name('evidence.py')), *map(str, args)],
                              capture_output=True, text=True, timeout=60, cwd=self.base)
        return proc.returncode, json.loads(proc.stdout)

    def ok(self, *args, now=None):
        code, out = self.call(*args, now=now)
        assert code == 0, out
        return out['data']

    def refused(self, code_name, *args, now=None, exit_code=1):
        code, out = self.call(*args, now=now)
        assert (code, out['error']['code']) == (exit_code, code_name), out
        return out

    def draft(self, **changes):
        draft = json.loads(TEMPLATE.read_text())
        draft['participant_models'] = [target('fixture-a', 'alpha-swift'), target('fixture-b', 'beta-one')]
        draft['analysis'] = target('fixture-a', 'alpha-swift')
        draft['review'] = target('fixture-c', 'gamma-pro')
        draft['sharing'] = [{'providerInstanceId': p, 'consumers': ['participant', 'analysis', 'review'],
                             'material_classes': ALL_CLASSES} for p in ('fixture-a', 'fixture-b', 'fixture-c')]
        draft['target'] = copy.deepcopy(FIXTURE_TARGET)
        for key, value in changes.items():
            draft[key] = value
        if 'stimulus' not in changes:
            draft['stimulus'] = self.stimulus(draft['study_id'])
        return draft

    def plan(self, draft, observations=None, expect=0, caps=None, review=True):
        self.counter += 1
        self.plan_admission = fixtures.policy_selection(self, draft, caps)
        actual_caps = copy.deepcopy(caps or self.plan_admission['selection']['capabilities'])
        if caps:
            frozen = self.plan_admission['selection']['capabilities']
            for key in ('parentThreadId','inheritedProviderInstanceId','inheritedModel'):
                actual_caps[key] = frozen[key]
            actual_caps['providers'].append(next(p for p in frozen['providers'] if p['providerInstanceId'] == 'fixture-coordinator'))
        args = ['plan', '--state-root', self.root, '--study', draft['study_id'],
                '--input', self.write(f'draft-{self.counter}.json', draft),
                '--admission', self.write(f'choice-{self.counter}.json', self.plan_admission),
                '--capabilities', self.write(f'caps-{self.counter}.json', actual_caps)]
        if observations is not None:
            args += ['--observations', self.write(f'obs-{self.counter}.json', observations)]
        if expect:
            return self.call(*args)
        view = self.ok(*args)
        if review:
            fixtures.policy_review(self, view)
            fixtures.policy_run(self, draft)
        return view

    def approval(self, view, statement=None, inside=False, source_text=None, message_ref='picker-answer-1'):
        statement = statement or view['approval_instruction']
        folder = (self.root / view['study_id']) if inside else (self.base / 'owner')
        folder.mkdir(parents=True, exist_ok=True)
        self.counter += 1
        source = folder / f'answer-{view["revision"][:8]}-{self.counter}.txt'
        source.write_text(source_text if source_text is not None else f'Selected option: {statement}\n')
        return self.write(f'approval-{view["revision"][:8]}-{self.counter}.json', {
            'revision': view['revision'], 'message_ref': message_ref, 'statement': statement,
            'source': str(source), 'source_sha256': sha(source.read_bytes())})

    def approve(self, view, **kw):
        return self.ok('approve', '--state-root', self.root, '--study', view['study_id'], '--input',
                       self.approval(view, **kw))

    def catalog(self, now=BEFORE, caps=None, observations=None, observed_at=None):
        """A fresh pre-dispatch catalog observation, dated at the controlled clock by default."""
        self.counter += 1
        return self.write(f'catalog-{self.counter}.json', {
            'schema_version': 1, 'observed_at': observed_at or now, 'source': 'fixture orchestrator_capabilities',
            'response': caps or CAPS, 'observations': observations or []})

    def check_run(self, view, now=BEFORE, expect=None, exit_code=1, **kw):
        args = ('check-run', '--state-root', self.root, '--study', view['study_id'],
                '--capabilities', self.catalog(now, **kw))
        return self.refused(expect, *args, now=now, exit_code=exit_code) if expect else self.ok(*args, now=now)

    def approved(self, **changes):
        view = self.plan(self.draft(**changes))
        self.approve(view)
        return view

    def admission(self, view, request_id, stage, cell=None, purpose='initial', classes=None, target_override=None):
        if stage in ('analysis', 'review'):
            tgt = view[stage]
        elif target_override:
            tgt = target_override
        else:
            tgt = next(c for c in view['cells'] if c['cell_id'] == cell)
            tgt = {k: tgt[k] for k in ('providerInstanceId', 'model', 'options', 'runtimeMode') if k in tgt}
        default = {'first-impression': ['stimulus', 'persona'], 'journey': ['stimulus', 'persona', 'participant-response'],
                   'analysis': ['stimulus', 'persona', 'participant-response', 'journey-evidence'],
                   'review': ALL_CLASSES}[stage]
        self.counter += 1
        return self.write(f'admit-{self.counter}.json', {
            'revision': view['revision'], 'request_id': request_id, 'stage': stage, 'cell_id': cell,
            'target': target_override or tgt, 'material_classes': default if classes is None else classes,
            'purpose': purpose})

    def admit(self, view, request_id, stage, cell=None, now=BEFORE, catalog=None, **kw):
        return self.call('admit', '--state-root', self.root, '--study', view['study_id'],
                         '--input', self.admission(view, request_id, stage, cell, **kw),
                         '--capabilities', catalog or self.catalog(now), now=now)

    def release(self, view, request_id):
        return self.ok('release', '--state-root', self.root, '--study', view['study_id'], '--input',
                       self.write(f'release-{request_id}.json', {'request_id': request_id, 'terminal_status': 'failed',
                                                                 'source': 'fixture task_status'}))

    def status(self, view):
        return self.ok('status', '--state-root', self.root, '--study', view['study_id'])

    def files(self):
        return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}

    # FG-2: record-acceptance ingests only a valid payload bound to its generated brief (and, for a journey,
    # to the cell's verified context), so these fixtures build invented participant evidence through the
    # real evidence helper rather than writing arbitrary bytes.

    def evidence_ok(self, *args):
        code, out = self.call_evidence(*args)
        assert code == 0, out
        return out['data']

    def participant_brief(self, view, cell, stage, task_id):
        """The generated brief's SHA-256 for this task, or None when the helper refuses to build it now."""
        key = (view['revision'], stage, task_id)
        if key not in self.briefs:
            self.counter += 1
            code, out = self.call_evidence('brief', '--state-root', self.root, '--study', view['study_id'], '--input',
                                           self.write(f'brief-{self.counter}.json', {
                                               'revision': view['revision'], 'cell_id': cell, 'stage': stage,
                                               'task_id': task_id}))
            if code != 0:
                return None
            self.briefs[key] = out['data']['document']['sha256']
        return self.briefs[key]

    def bound_context(self, view, cell):
        """Bind a verified fixture context to every cell of the revision (once) and return this cell's."""
        if (view['revision'], cell) not in self.contexts:
            ids = [c['cell_id'] for c in view['cells']]
            self.counter += 1
            probe = self.evidence_ok('probe-plan', '--state-root', self.root, '--study', view['study_id'], '--input',
                                     self.write(f'probe-{self.counter}.json', {'revision': view['revision'], 'cell_ids': ids}))
            readings = {cid: {'origin': probe['origin'], 'shared': dict.fromkeys(('cookie', 'local', 'session'), row['value']),
                              'others_own_seen': dict.fromkeys(('cookie', 'local', 'session'), False), 'cleared': False}
                        for cid, row in probe['cells'].items()}
            tools = {'schema_version': 1, 'observed_at': BEFORE, 'source': 'fixture child tool observation',
                     'native_browser': None, 'tools': [{'name': f'mcp__t3-code__preview_{n}'} for n in ('open', 'evaluate')]}
            for cid in ids:
                reference = f'fixture-context-{sha(cid.encode())[:12]}'
                self.counter += 1
                data = self.evidence_ok('bind-context', '--state-root', self.root, '--study', view['study_id'], '--input',
                                        self.write(f'bind-{self.counter}.json', {
                                            'revision': view['revision'], 'cell_id': cid, 'child_tools': tools,
                                            'context': {'reference': reference, 'boundary': 'isolated-context'},
                                            'assignment': {'kind': 'host-enforced', 'source': 'fixture host binding receipt',
                                                           'receipt_sha256': sha(reference.encode()), 'child_ref': cid},
                                            'evidence_class': 'fixture',
                                            'probe': {'probe_id': probe['probe_id'], 'readings': readings}}))
                self.contexts[(view['revision'], cid)] = {'reference': reference, 'binding_sha256': data['binding_sha256']}
        return self.contexts[(view['revision'], cell)]

    @staticmethod
    def first_payload(view, cell, brief_sha, variant=''):
        tag = sha(f'{cell}{variant}'.encode())[:10]
        return {'schema': 'focus-group/first-impression', 'schema_version': 1, 'cell_id': cell,
                'study_revision': view['revision'], 'brief_sha256': brief_sha,
                'image_use': {'saw_images': True, 'basis': 'image-and-text'},
                'initial_viewport': {'file': 'initial-viewport.png', 'reaction': f'Invented first reaction {tag}.',
                                     'observed': ['a heading above a green button'], 'inferred': []},
                'walkthrough': [{'file': 'welcome.txt', 'reaction': 'Short and clear.',
                                 'observed': ['three dinners in a few taps'], 'inferred': []}],
                'claims': [{'id': 'c1', 'kind': 'textual', 'statement': 'It promises a few taps.', 'files': ['welcome.txt']}],
                'simulated': True}

    @staticmethod
    def journey_payload(view, cell, brief_sha, context):
        return {'schema': 'focus-group/journey', 'schema_version': 1, 'cell_id': cell, 'study_revision': view['revision'],
                'brief_sha256': brief_sha, 'driver': 'participant-child', 'context': dict(context),
                'target': {'url': FIXTURE_TARGET['url'], 'environment': 'fixture'},
                'environment_drift': {'state': 'unavailable', 'detail': 'the fixture origin exposes no deployment ID'},
                'started_at': '2029-06-01T00:05:00Z', 'ended_at': '2029-06-01T00:09:00Z',
                'goals': [{'journey_id': 'plan-three-dinners', 'outcome': 'partial',
                           'steps': [{'at': '2029-06-01T00:06:00Z', 'kind': 'tap', 'permitted_action': 'browse recipes',
                                      'description': 'opened recipes', 'url': FIXTURE_ORIGIN + '/recipes', 'field': None}],
                           'reactions': ['Quick, but I lost my place once.'], 'observed_events': ['the recipe list loaded'],
                           'inferences': [], 'evidence': []}],
                'gaps': []}

    def result_sha(self, view, task_id):
        return sha((self.root / view['study_id'] / 'artifacts' / 'tasks' / task_id / 'result.json').read_bytes())


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(Path(self.tmp.name).resolve())


class CommandTest(FixtureCase):
    """REQ-COMMAND: manifest, routing, workers, guide and zero-dispatch direct operations."""

    def setUp(self):
        super().setUp()
        self.meta = skill_manifest(PLUGIN / 'plugin.json')
        self.entry = (source_entry(PLUGIN)).read_text()

    def test_manifest_exposes_every_operation_through_the_catalog_routes(self):
        self.assertEqual(self.meta['operations'], OPERATIONS)
        self.assertEqual(self.meta['picker'], ['plan', 'run', 'status', 'doctor'])
        self.assertEqual({w['id'] for w in self.meta['workers']}, set(WORKERS))
        self.assertEqual({w['role'] for w in self.meta['workers']}, {'workhorse', 'judgement', 'reviewer'})
        sys.path.insert(0, str(ROOT / 'scripts'))
        try:
            import skills
            skills.validate_picker(self.meta)
        finally:
            sys.path.remove(str(ROOT / 'scripts'))

        def route(request):
            return next((r['operation'] for r in self.meta['routes'] if re.fullmatch(r['pattern'], request)), None)
        cases = {'doctor': 'doctor', 'plan the pantry planner onboarding': 'plan', 'plan pantry-planner-onboarding': 'plan',
                 'https://staging.example/welcome first screen only': 'plan', 'run pantry-planner-onboarding': 'run',
                 'resume pantry-planner-onboarding': 'resume', 'status pantry-planner-onboarding': 'status',
                 'cancel pantry-planner-onboarding': 'cancel', 'run': None, 'status': None,
                 'delete everything': None}
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(route(request), expected)
        self.assertLess(len(self.entry.split()), 1500)
        for path in (PLUGIN / 'agents').glob('*.md'):
            self.assertIsNone(MODEL_ID.search(path.read_text()), path.name)
        self.assertIsNone(MODEL_ID.search(HELPER.read_text()))

    def test_entry_loads_selected_playbooks_and_states_direct_operations(self):
        named = set(re.findall(r'`PKG/([\w./-]+)`', self.entry))
        for name in named:
            self.assertTrue((PLUGIN / name).exists() or (ROOT / name).exists(), name)
        for rel in ('playbooks/plan.md', 'playbooks/run.md', 'references/study-contract.md',
                    'shared/t3-runtime.md', 'shared/job-coordination.md'):
            self.assertIn(rel, named)
        flat = ' '.join(self.entry.split())
        for phrase in ("host's native question picker", 'recommended option first', 'Silence is not approval',
                       '`status` and `doctor` create no delegated task, schedule nothing',
                       'Planning never launches the participant panel', 'never creates, locks or rewrites',
                       'never call them independent model families', 'never silently changes the matrix',
                       'A task ceiling is not a dollar cap'):
            self.assertIn(phrase, flat)
        self.assertTrue((ROOT / 'docs' / 'plugins' / 'focus-group.md').is_file())

    def test_worker_definitions_follow_the_worker_contract(self):
        for row in self.meta['workers']:
            with self.subTest(worker=row['id']):
                text = (PLUGIN / row['path']).read_text()
                flat = ' '.join(text.split())
                self.assertTrue(text.startswith(f"---\nworker_id: {row['id']}\n"))
                for phrase in ('check its SHA-256 and byte count', 'return `blocked`', 'Do not dispatch child tasks',
                               'Do not accept your own work', '`worker-result.schema.json` version 1',
                               '(`blocker`, `major`, `minor`, `note`)', '## Redaction'):
                    self.assertIn(phrase, flat)
        participant = ' '.join((PLUGIN / 'agents/participant.md').read_text().split())
        self.assertIn("If your brief contains another cell's response, a preferred finding, source code or a backlog",
                      participant)
        self.assertIn('Never enter, request or invent credentials', participant)

    def test_doctor_reports_capability_facts_and_creates_nothing(self):
        env_state = self.ws.base / 'xdg-state'
        code, out = self.ws.call('doctor', '--capabilities', self.ws.caps)
        self.assertEqual(code, 0, out)
        catalog = out['data']['catalog']
        self.assertEqual(sorted(catalog['lineages']), ['alpha', 'beta', 'gamma'])
        self.assertTrue(catalog['suggested_panel_possible'])
        self.assertTrue(catalog['independent_reviewer_possible'])
        for facts in catalog['capabilities'].values():
            self.assertEqual({f['state'] for f in facts.values()}, {'unknown-until-pilot'})
        self.assertEqual(catalog['hard_stop']['state'], 'unknown-until-pilot')
        self.assertNotIn('passed', json.dumps(out))
        self.assertFalse(self.ws.root.exists())
        self.assertFalse(env_state.exists())
        code, out = self.ws.call('doctor', '--capabilities', self.ws.write('one.json', ALPHA_ONLY))
        self.assertFalse(out['data']['catalog']['suggested_panel_possible'])
        self.assertFalse(out['data']['catalog']['independent_reviewer_possible'])

    def test_plan_and_status_create_no_job_brief_or_task_and_status_writes_nothing(self):
        view = self.ws.plan(self.ws.draft())
        self.assertEqual(view['dispatched'], 0)
        study = self.ws.root / view['study_id']
        self.assertFalse((study / 'job.json').exists())
        self.assertFalse((study / 'briefs').exists())
        before = self.ws.files()
        status = self.ws.status(view)
        self.assertEqual(status['approval']['state'], 'unapproved')
        self.assertEqual(status['charged_tasks'], 0)
        self.ws.ok('doctor', '--capabilities', self.ws.caps)
        self.assertEqual(self.ws.files(), before)
        self.ws.refused('unknown_study', 'status', '--state-root', self.ws.root, '--study', 'no-such-study', exit_code=2)
        self.assertFalse((self.ws.root / 'no-such-study').exists())

    def test_installed_package_routes_bare_invocation_to_the_picker_and_materialises_workers(self):
        home = self.ws.base / 'home'
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENTS_', 'XDG_'))}
        env.update(HOME=str(home), XDG_STATE_HOME=str(self.ws.base / 'xdg-state'),
                   XDG_CONFIG_HOME=str(self.ws.base / 'config'), PYTHONDONTWRITEBYTECODE='1')
        prefix, agents = self.ws.base / 'prefix', self.ws.base / 'agents'
        cli = [sys.executable, str(ROOT / 'scripts' / 'catalog.py'), '--prefix', str(prefix), '--agents-root', str(agents)]
        run = lambda *a: subprocess.run([*cli, *a], capture_output=True, text=True, env=env, timeout=60)
        installed = run('install', 'focus-group')
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        prompt = run('prompt', 'focus-group')
        self.assertIn("Ask through the host's native question picker.", prompt.stdout)
        self.assertIn('Options: plan, run, status, doctor.', prompt.stdout)
        routed = run('prompt', 'focus-group', 'status', 'pantry-planner-onboarding')
        self.assertIn('and run: status pantry-planner-onboarding', routed.stdout)
        entry = Path(run('path', 'focus-group').stdout.strip())
        self.assertEqual(entry.read_text(), self.entry)
        package = entry.parent
        for rel in ('playbooks/plan.md', 'playbooks/run.md', 'scripts/study.py', 'shared/lineage.py',
                    'core/jobs/store.py', 'templates/study-draft.example.json'):
            self.assertTrue((package / rel).is_file(), rel)
        for worker in WORKERS:
            name = worker.split('/', 1)[1]
            materialized = list(agents.rglob(f'workers/{name}.md'))
            self.assertEqual(len(materialized), 1, worker)
            self.assertEqual(materialized[0].read_bytes(), (PLUGIN / 'agents' / f'{name}.md').read_bytes())
        doctor = subprocess.run([sys.executable, str(package / 'scripts/study.py'), 'doctor'], capture_output=True,
                                text=True, env=env, timeout=60, cwd=self.ws.base)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertTrue(all(json.loads(doctor.stdout)['data']['package_files'].values()))
        self.assertFalse((self.ws.base / 'xdg-state' / 'agents' / 'jobs').exists())


class PlanTest(FixtureCase):
    """REQ-PLAN: editable personas, exact revisions, sharing authority and approval."""

    def test_a_pack_target_is_refused_in_combined_mode_and_accepted_in_capture_only(self):
        draft = self.ws.draft(target={'kind': 'pack', 'environment': 'fixture', 'label': 'Invented supplied pack'})
        before = self.ws.files()
        code, out = self.ws.plan(draft, expect=2)
        self.assertEqual((code, out['error']['code']), (2, 'invalid_plan'), out)
        self.assertIn('combined mode requires a URL target', out['error']['message'])
        self.assertEqual(self.ws.files(), before)
        draft.update(mode='capture-only', journeys=[])
        view = self.ws.plan(draft)
        self.assertEqual(view['expected_mode'], 'capture-only')

    def test_plan_records_brief_and_presents_revision_ceiling_mode_and_limits(self):
        view = self.ws.plan(self.ws.draft())
        self.assertRegex(view['revision'], r'^[0-9a-f]{64}$')
        record = json.loads((self.ws.root / view['study_id'] / 'focus-group' / 'plans' / f"{view['revision']}.json").read_text())
        plan = record['plan']
        self.assertEqual(sha((json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()),
                         view['revision'])
        for field in ('audience', 'decision', 'target', 'journeys', 'exclusions', 'personas', 'prompts',
                      'capture_profile', 'stimulus', 'sharing', 'limits', 'coverage_policy'):
            self.assertIn(field, plan)
        self.assertEqual(plan['journeys'][0]['excluded_actions'],
                         ['create an account', 'enter payment details', 'place a grocery order'])
        self.assertEqual(view['expected_mode'], 'combined')
        self.assertEqual(view['task_counts']['max_tasks'], 22)
        self.assertIn('ceiling 22 tasks', view['approval_instruction'])
        self.assertIn(view['revision'][:12], view['approval_instruction'])
        self.assertTrue(any('unknown until each model pilot' in l for l in view['assessment']['limitations']))
        self.assertEqual(view['approval']['state'], 'unapproved')

    def test_personas_are_editable_and_a_time_poor_parent_is_one_invented_individual(self):
        first = self.ws.plan(self.ws.draft())
        draft = self.ws.draft()
        draft['personas'][0]['priorities'] = ['finishing before the school run', 'meals her two children eat']
        draft['limits']['max_concurrency'] = 2
        draft['capture_profile']['viewport'] = {'width': 412, 'height': 915}
        second = self.ws.plan(draft)
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(self.ws.status(second)['previous_revisions'], [first['revision']])
        plans = self.ws.root / draft['study_id'] / 'focus-group' / 'plans'
        self.assertEqual(len([p for p in plans.glob('*.json') if re.fullmatch(r'[0-9a-f]{64}', p.stem)]), 2)
        parent = second['cells'][0]
        self.assertEqual(parent['persona'], 'time-poor-parent')
        # The guide's own example is refused; the lint covers listed phrasings, not every group claim.
        for claim in ('All parents want fewer taps', 'parents always prefer pictures', 'Most families need meal plans',
                      'parents want fewer taps', 'Busy at work. Parents need fewer steps'):
            with self.subTest(claim=claim):
                bad = self.ws.draft()
                bad['personas'][0]['priorities'] = [claim]
                code, out = self.ws.plan(bad, expect=True)
                self.assertEqual((code, out['error']['code']), (2, 'population_claim'))
        bad = self.ws.draft()
        bad['personas'][0]['goal'] = 'parents want fewer taps'
        self.assertEqual(self.ws.plan(bad, expect=True)[1]['error']['code'], 'population_claim')
        # One parent's own household detail is not a group claim.
        fine = self.ws.draft()
        fine['personas'][0]['constraints'] = ['her two kids need dinner by six']
        self.ws.plan(fine)
        bad = self.ws.draft()
        bad['personas'][0]['invented'] = False
        self.assertEqual(self.ws.plan(bad, expect=True)[1]['error']['code'], 'invalid_persona')

    def test_unapproved_revision_refuses_run_and_dispatch(self):
        view = self.ws.plan(self.ws.draft())
        out = self.ws.check_run(view, expect='unapproved_revision')
        self.assertIn(view['revision'][:12], out['data']['instruction'])
        code, out = self.ws.admit(view, 'fi-01-r0', 'first-impression', view['cells'][0]['cell_id'])
        self.assertEqual((code, out['error']['code']), (1, 'unapproved_revision'))
        self.assertFalse((self.ws.root / view['study_id'] / 'focus-group' / 'ledger.json').exists())

    def test_approval_must_quote_this_revision_and_ceiling_from_a_source_outside_the_job(self):
        view = self.ws.plan(self.ws.draft())
        args = ('approve', '--state-root', self.ws.root, '--study', view['study_id'], '--input')
        self.ws.refused('approval_scope_mismatch', *args, self.ws.approval(view, statement='Yes, go ahead'))
        wrong_ceiling = view['approval_instruction'].replace('ceiling 22 tasks', 'ceiling 40 tasks')
        self.ws.refused('approval_scope_mismatch', *args, self.ws.approval(view, statement=wrong_ceiling))
        other = dict(view, revision='f' * 64)
        self.ws.refused('stale_revision', *args, self.ws.approval(other))
        self.ws.refused('invalid_approval', *args, self.ws.approval(view, inside=True), exit_code=2)
        path = self.ws.approval(view)
        payload = json.loads(path.read_text())
        payload['source_sha256'] = '0' * 64
        self.ws.refused('invalid_approval', *args, self.ws.write('tampered.json', payload), exit_code=2)
        approved = self.ws.ok(*args, self.ws.approval(view))
        self.assertEqual(approved['approval']['statement'], view['approval_instruction'])
        self.assertEqual(approved['approval']['message_ref'], 'picker-answer-1')
        self.ws.check_run(view)
        # Prior authority that already covers these exact inputs is not requested again.
        again = self.ws.plan(self.ws.draft())
        self.assertEqual((again['revision'], again['approval']['state']), (view['revision'], 'approved'))

    def test_uninspected_material_cannot_be_approved(self):
        draft = self.ws.draft()
        draft['stimulus']['coordinator_inspected'] = False
        view = self.ws.plan(draft)
        self.assertTrue(any('not inspected' in l for l in view['assessment']['limitations']))
        self.ws.refused('stimulus_uninspected', 'approve', '--state-root', self.ws.root, '--study', view['study_id'],
                        '--input', self.ws.approval(view))

    def test_post_approval_pack_change_refuses_run_until_a_new_revision_is_approved(self):
        view = self.ws.approved()
        self.ws.image.write_bytes(b'a different screenshot')
        out = self.ws.check_run(view, expect='inputs_changed')
        self.assertEqual(out['data']['changed'][0]['name'], 'initial-viewport.png')
        code, out = self.ws.admit(view, 'fi-01-r0', 'first-impression', view['cells'][0]['cell_id'])
        self.assertEqual(out['error']['code'], 'inputs_changed')
        self.assertTrue(self.ws.status(view)['stimulus_changed'])
        # Recapture is a new immutable attempt (FG-2), then a new revision that needs authority matching it.
        first = self.ws.stimulus(view['study_id'])['manifest_sha256']
        overwritten = fixtures.manifest(self.ws.pack_files, attempt={'number': 2, 'previous_manifest_sha256': first})
        code, out = self.ws.call_evidence('pack', '--state-root', self.ws.root, '--study', view['study_id'], '--input',
                                          self.ws.write('overwritten.json', overwritten))
        self.assertEqual((code, out['error']['code']), (1, 'pack_failed'))
        self.assertIn('artifact_overwritten', {p['code'] for p in out['data']['problems']})
        files = fixtures.write_pack(self.ws.base / 'recapture', prefix='r2-')
        code, out = self.ws.call_evidence('pack', '--state-root', self.ws.root, '--study', view['study_id'], '--input',
                                          self.ws.write('recapture.json', fixtures.manifest(files, attempt={
                                              'number': 3, 'previous_manifest_sha256': out['data']['manifest_sha256']})))
        self.assertEqual(code, 0, out)
        recaptured = self.ws.approved(stimulus=dict(out['data']['stimulus'], coordinator_inspected=True))
        self.assertNotEqual(recaptured['revision'], view['revision'])

    def test_removed_provider_sharing_grant_blocks_approval_and_dispatch(self):
        view = self.ws.approved()
        draft = self.ws.draft()
        draft['sharing'] = [g for g in draft['sharing'] if g['providerInstanceId'] != 'fixture-b']
        revised = self.ws.plan(draft)
        self.assertEqual(revised['expected_mode'], 'blocked')
        self.assertEqual({g['providerInstanceId'] for g in revised['assessment']['sharing_gaps']}, {'fixture-b'})
        self.ws.refused('plan_blocked', 'approve', '--state-root', self.ws.root, '--study', view['study_id'],
                        '--input', self.ws.approval(revised))
        code, out = self.ws.admit(view, 'fi-02-r0', 'first-impression', view['cells'][1]['cell_id'])
        self.assertEqual((code, out['error']['code']), (1, 'unapproved_revision'))


class PanelTest(FixtureCase):
    """REQ-PANEL: catalog-derived suggestion, arithmetic, diversity and preflight disclosure."""

    def test_suggestion_is_four_personas_across_two_catalog_lineages_with_a_distinct_reviewer(self):
        draft = json.loads(TEMPLATE.read_text())
        admission = fixtures.policy_selection(self.ws, dict(draft,
            participant_models=[target('fixture-a','alpha-swift'),target('fixture-b','beta-one')],
            analysis=target('fixture-a','alpha-swift'),review=target('fixture-c','gamma-pro')))
        out = self.ws.ok('suggest', '--input', self.ws.write('template.json', draft), '--capabilities', self.ws.caps,
                         '--admission', self.ws.write('suggest-choice.json', admission))
        filled = out['draft']
        self.assertEqual(len(filled['personas']), 4)
        self.assertEqual([(m['providerInstanceId'], m['model']) for m in filled['participant_models']],
                         [('fixture-a', 'alpha-swift'), ('fixture-b', 'beta-one')])
        self.assertEqual(filled['analysis']['providerInstanceId'], 'fixture-a')
        self.assertEqual(filled['review']['providerInstanceId'], 'fixture-b')
        self.assertEqual(out['writes'], 'none')
        self.assertFalse(self.ws.root.exists())

    def test_task_arithmetic_counts_every_stage_pilot_and_repair(self):
        view = self.ws.plan(self.ws.draft())
        counts = view['task_counts']
        self.assertEqual(len(view['cells']), 8)
        self.assertEqual(counts['participant_first_attempts'], 16)
        self.assertEqual(counts['pilots'], 2)
        self.assertTrue(counts['pilots_included_in_cells'])
        self.assertEqual(sum(c['pilot'] for c in view['cells']), 2)
        self.assertEqual(counts['first_attempt_tasks'], 18)
        self.assertEqual(counts['max_tasks'], 18 + 2 + 1 + 1)
        self.assertEqual(counts['unknown_dependent_tasks'], 8)
        self.assertEqual(counts['capture_only_first_attempt_tasks'], 10)
        self.assertIn('not a human sample size', ' '.join(counts['notes']))
        for cell in view['cells']:
            self.assertEqual(set(cell) >= {'cell_id', 'persona', 'providerInstanceId', 'model', 'options', 'pilot'}, True)
        capture = self.ws.draft(mode='capture-only', journeys=[], study_id='capture-study')
        capture['prompts'].pop('journey')
        counts = self.ws.plan(capture)['task_counts']
        self.assertEqual((counts['participant_first_attempts'], counts['first_attempt_tasks']), (8, 10))

    def test_same_lineage_models_show_reduced_diversity_and_one_model_is_refused(self):
        draft = self.ws.draft(participant_models=[target('fixture-a', 'alpha-swift'), target('fixture-a', 'alpha-deep')])
        view = self.ws.plan(draft)
        self.assertEqual(view['assessment']['diversity'], 'single-lineage')
        self.assertTrue(any('not independent model families' in l for l in view['assessment']['limitations']))
        self.assertEqual(len(view['cells']), 8)
        single = self.ws.draft(participant_models=[target('fixture-a', 'alpha-swift'),
                                                   target('fixture-a', 'alpha-swift', reasoningEffort='high')])
        self.assertEqual(self.ws.plan(single, expect=True)[1]['error']['code'], 'not_multi_model')

    def test_unavailable_independent_reviewer_blocks_the_plan(self):
        code, same = self.ws.plan(self.ws.draft(review=target('fixture-a', 'alpha-deep')), expect=True)
        self.assertEqual((code, same['error']['code']), (1, 'model_selection_required'))
        self.assertIn('independent fidelity', same['error']['message'])
        self.assertFalse((self.ws.root / 'pantry-planner-onboarding' / 'focus-group' / 'current.json').exists())
        draft = self.ws.draft(review=None, analysis=None,
                              participant_models=[target('fixture-a', 'alpha-swift'), target('fixture-a', 'alpha-deep')])
        draft.pop('review')
        draft.pop('analysis')
        self.ws.refused('reviewer_unavailable', 'suggest', '--input', self.ws.write('alpha.json', draft),
                        '--capabilities', self.ws.write('alpha-caps.json', ALPHA_ONLY),
                        '--admission', self.ws.write('alpha-choice.json', fixtures.policy_selection(self.ws,self.ws.draft())))

    def test_missing_models_options_or_providers_never_change_the_matrix(self):
        for change, problem in ((target('fixture-b', 'beta-two'), 'model_unavailable'),
                                (target('fixture-a', 'alpha-deep', reasoningEffort='extreme'), 'unsupported_option'),
                                (target('fixture-off', 'delta-x'), 'provider_unavailable')):
            with self.subTest(problem=problem):
                draft = self.ws.draft(participant_models=[target('fixture-a', 'alpha-swift'), change])
                code, out = self.ws.plan(draft, expect=True)
                self.assertEqual((code, out['error']['code']), (1, 'matrix_unavailable'))
                self.assertEqual(out['data']['problems'][0]['problem'], problem)
                self.assertFalse((self.ws.root / draft['study_id'] / 'focus-group' / 'current.json').exists())

    def test_capability_facts_stay_unknown_until_pilot_and_observed_absence_changes_mode(self):
        view = self.ws.plan(self.ws.draft())
        for facts in view['assessment']['capabilities'].values():
            self.assertEqual({f['state'] for f in facts.values()}, {'unknown-until-pilot'})
            self.assertTrue(all(f['verified'] is False for f in facts.values()))
        code, out = self.ws.plan(self.ws.draft(), observations=[
            {'fact': 'isolation', 'state': 'verified', 'providerInstanceId': 'fixture-a', 'source': 'assumed'}], expect=True)
        self.assertEqual(out['error']['code'], 'pilot_claim_before_pilot')
        absent = [{'fact': 'browser_tools', 'state': 'unavailable', 'providerInstanceId': None,
                   'source': 'child tool schema lists no browser tools'}]
        view = self.ws.plan(self.ws.draft(), observations=absent)
        self.assertEqual(view['expected_mode'], 'capture-only')
        self.assertTrue(any('only capture results' in l for l in view['assessment']['limitations']))
        self.assertEqual(view['assessment']['dollar_cost']['state'], 'unavailable')


class LimitsTest(FixtureCase):
    """REQ-LIMITS: bounded limits, deadline semantics, sharing refusals and shared budgets."""

    def test_limits_must_be_positive_bounded_and_complete(self):
        for key, value in (('max_concurrency', 0), ('max_attempts_per_slot', 11), ('participant_repairs', -1),
                           ('deadline', '2030-01-01'), ('hard_stop_required', 'no')):
            with self.subTest(key=key):
                draft = self.ws.draft()
                draft['limits'][key] = value
                code, out = self.ws.plan(draft, expect=True)
                self.assertEqual(code, 2, out)
        draft = self.ws.draft()
        del draft['limits']['review_repairs']
        self.assertEqual(self.ws.plan(draft, expect=True)[0], 2)

    def test_controlled_clock_stops_new_tasks_at_the_deadline_and_wake_lists_open_work(self):
        view = self.ws.approved()
        cells = [c['cell_id'] for c in view['cells']]
        self.assertEqual(self.ws.admit(view, 'fi-01-r0', 'first-impression', cells[0])[0], 0)
        self.assertEqual(self.ws.admit(view, 'fi-02-r0', 'first-impression', cells[1])[0], 0)
        early = self.ws.ok('wake', '--state-root', self.ws.root, '--study', view['study_id'], now=BEFORE)
        self.assertEqual((early['deadline_expired'], early['cancel']), (False, []))
        code, out = self.ws.admit(view, 'fi-03-r0', 'first-impression', cells[2], now=AFTER)
        self.assertEqual((code, out['error']['code']), (1, 'deadline_passed'))
        late = self.ws.ok('wake', '--state-root', self.ws.root, '--study', view['study_id'], now=AFTER)
        self.assertEqual(late['cancel'], ['fi-01-r0', 'fi-02-r0'])
        self.assertFalse(late['cancellation_confirmed'])
        self.assertFalse(late['new_tasks_permitted'])
        status = self.ws.status(view)
        self.assertEqual(status['cancel_pending_confirmation'], ['fi-01-r0', 'fi-02-r0'])
        self.assertIs(status['complete'], False)
        self.ws.release(view, 'fi-01-r0')
        self.ws.release(view, 'fi-02-r0')
        self.assertEqual(self.ws.status(view)['cancel_pending_confirmation'], [])
        self.assertEqual(self.ws.status(view)['charged_tasks'], 2)

    def test_hard_stop_promise_is_held_without_host_support(self):
        draft = self.ws.draft()
        draft['limits']['hard_stop_required'] = True
        view = self.ws.plan(draft)
        self.ws.approve(view)
        self.ws.check_run(view, expect='hard_stop_unsupported')
        self.assertEqual(self.ws.admit(view, 'fi-01-r0', 'first-impression', view['cells'][0]['cell_id'])[1]['error']['code'],
                         'hard_stop_unsupported')
        # Host support comes from the fresh pre-dispatch observation, not from planning.
        later = '2029-06-01T00:05:00Z'
        self.ws.check_run(view, now=later, observations=[{'fact': 'hard_stop', 'state': 'available',
                                                          'providerInstanceId': None,
                                                          'source': 'host task schema exposes a runtime limit'}])

    def test_unauthorised_participant_analyst_and_reviewer_disclosure_is_refused(self):
        draft = self.ws.draft()
        draft['sharing'] = [{'providerInstanceId': 'fixture-a', 'consumers': ['participant'],
                             'material_classes': ['stimulus', 'persona', 'participant-response']},
                            {'providerInstanceId': 'fixture-a', 'consumers': ['analysis'],
                             'material_classes': ['stimulus', 'persona', 'participant-response', 'journey-evidence']},
                            {'providerInstanceId': 'fixture-b', 'consumers': ['participant'],
                             'material_classes': ['stimulus', 'persona', 'participant-response']},
                            {'providerInstanceId': 'fixture-c', 'consumers': ['review'], 'material_classes': ALL_CLASSES}]
        view = self.ws.plan(draft)
        self.ws.approve(view)
        cell = view['cells'][0]['cell_id']
        # Participant and analyst ask for a class their provider instance was not granted for that role.
        code, out = self.ws.admit(view, 'fi-x', 'first-impression', cell, classes=['stimulus', 'persona', 'journey-evidence'])
        self.assertEqual((code, out['error']['code'], out['data']['missing']), (1, 'sharing_not_authorised', ['journey-evidence']))
        code, out = self.ws.admit(view, 'an-x', 'analysis', classes=ALL_CLASSES)
        self.assertEqual((code, out['error']['code'], out['data']['missing']), (1, 'sharing_not_authorised', ['analysis-report']))
        # A reviewer moved onto a provider instance without a review grant is outside the approved plan.
        code, out = self.ws.admit(view, 'rv-x', 'review', classes=ALL_CLASSES, target_override=target('fixture-a', 'alpha-swift'))
        self.assertEqual((code, out['error']['code']), (1, 'outside_matrix'))
        self.assertEqual(self.ws.status(view)['charged_tasks'], 0)
        self.assertEqual(self.ws.admit(view, 'rv-y', 'review', classes=ALL_CLASSES)[0], 0)
        # A reviewer grant that omits a class the review needs blocks the revision before any dispatch.
        draft['sharing'][-1]['material_classes'] = ['stimulus', 'persona', 'participant-response', 'analysis-report']
        revised = self.ws.plan(draft)
        self.assertEqual(revised['assessment']['sharing_gaps'],
                         [{'providerInstanceId': 'fixture-c', 'consumer': 'review', 'stage': 'review',
                           'missing': ['journey-evidence']}])
        self.ws.refused('plan_blocked', 'approve', '--state-root', self.ws.root, '--study', view['study_id'],
                        '--input', self.ws.approval(revised))
        code, out = self.ws.admit(revised, 'rv-z', 'review', classes=ALL_CLASSES)
        self.assertEqual((code, out['error']['code']), (1, 'unapproved_revision'))

    def test_resume_replacement_and_repair_share_one_budget(self):
        draft = self.ws.draft()
        draft['limits'].update(participant_repairs=1, max_attempts_per_slot=3, max_concurrency=1)
        view = self.ws.plan(draft)
        self.ws.approve(view)
        a, b = view['cells'][0]['cell_id'], view['cells'][1]['cell_id']
        self.assertEqual(self.ws.admit(view, 'a-r0', 'first-impression', a)[1]['data']['pool'], 'first')
        code, out = self.ws.admit(view, 'b-r0', 'first-impression', b)
        self.assertEqual(out['error']['code'], 'concurrency_limit')
        duplicate = self.ws.admit(view, 'a-r0', 'first-impression', a)[1]['data']
        self.assertEqual((duplicate['duplicate'], duplicate['charged']), (True, False))
        self.assertEqual(self.ws.admit(view, 'a-r0', 'journey', a)[1]['error']['code'], 'request_conflict')
        self.ws.release(view, 'a-r0')
        self.assertEqual(self.ws.admit(view, 'a-r1', 'first-impression', a, purpose='repair')[1]['data']['pool'],
                         'participant_repairs')
        self.ws.release(view, 'a-r1')
        self.assertEqual(self.ws.admit(view, 'b-r0', 'first-impression', b)[1]['data']['pool'], 'first')
        self.ws.release(view, 'b-r0')
        for purpose in ('replacement', 'resume', 'repair'):
            with self.subTest(purpose=purpose):
                code, out = self.ws.admit(view, f'b-{purpose}', 'first-impression', b, purpose=purpose)
                self.assertEqual((code, out['error']['code']), (1, 'budget_exhausted'))
        self.assertEqual(self.ws.status(view)['charged'], {'first': 2, 'participant_repairs': 1})

    def test_capture_only_revision_declares_no_journeys_and_matrix_is_enforced(self):
        draft = self.ws.draft(mode='capture-only', journeys=[])
        draft['prompts'].pop('journey')
        view = self.ws.plan(draft)
        self.ws.approve(view)
        cell = view['cells'][0]['cell_id']
        self.assertEqual(self.ws.admit(view, 'j-r0', 'journey', cell)[1]['error']['code'], 'outside_matrix')
        self.assertEqual(self.ws.admit(view, 'x-r0', 'first-impression', cell,
                                       target_override=target('fixture-c', 'gamma-pro'))[1]['error']['code'],
                         'outside_matrix')
        self.assertEqual(self.ws.admit(view, 'z-r0', 'first-impression', 'nobody--0000000000',
                                       target_override=target('fixture-a', 'alpha-swift'))[1]['error']['code'],
                         'outside_matrix')


class ContractTest(FixtureCase):
    """REQ-CONTRACT: generic job, accepted-result bindings and explicit carry-forward."""

    def accept(self, view, cell, stage, task_id, variant='', predecessors=(), observed=True, path=None, admit=True,
               context=None):
        """Write an invented participant payload for `task_id` and submit it to record-acceptance. The payload
        answers the brief the generator built for this task; when the helper refuses to build one (the record
        is then refused for another reason) it names no recorded brief."""
        # FG-3 admits a journey only once its own current brief exists (FG2-F1), so the brief is built first.
        folder = self.ws.root / view['study_id'] / 'artifacts' / 'tasks' / task_id
        if stage == 'journey':
            bound = self.ws.bound_context(view, cell)
        brief = self.ws.participant_brief(view, cell, stage, task_id) or '0' * 64
        if admit and not folder.exists():
            code, out = self.ws.admit(view, f'{task_id}-r0', stage, cell)
            self.assertEqual(code, 0, out)
            self.ws.release(view, f'{task_id}-r0')
        folder.mkdir(parents=True, exist_ok=True)
        payload = (self.ws.first_payload(view, cell, brief, variant) if stage == 'first-impression'
                   else self.ws.journey_payload(view, cell, brief, bound))
        result = path or folder / 'result.json'
        result.write_bytes(json.dumps(payload, sort_keys=True).encode())
        model = next(c for c in view['cells'] if c['cell_id'] == cell)
        record = {'revision': view['revision'], 'cell_id': cell, 'stage': stage, 'task_id': task_id,
                  'request_id': f'{task_id}-r0', 'result': {'path': str(result), 'sha256': sha(result.read_bytes())},
                  'observed': ({'providerInstanceId': model['providerInstanceId'], 'model': model['model'],
                                'source': 'fixture task_status'} if observed else None),
                  'predecessors': list(predecessors),
                  'context': context if context is not None or stage != 'journey' else self.context(view, cell)}
        if stage == 'first-impression':
            record['image_delivery'] = DELIVERED
        return self.ws.call('record-acceptance', '--state-root', self.ws.root, '--study', view['study_id'],
                            '--input', self.ws.write(f'accept-{task_id}-{stage}.json', record))

    def context(self, view, cell, cls='fresh-anonymous'):
        """The verified browser context a journey in this cell ran in, as record-acceptance records it."""
        return {'class': cls, **self.ws.bound_context(view, cell)}

    def result_sha(self, view, task_id):
        return self.ws.result_sha(view, task_id)

    def accept_all(self, view):
        shas = {}
        for n, cell in enumerate(view['cells'], 1):
            code, out = self.accept(view, cell['cell_id'], 'first-impression', f'fi-{n:02d}')
            self.assertEqual(code, 0, out)
            first = self.result_sha(view, f'fi-{n:02d}')
            code, out = self.accept(view, cell['cell_id'], 'journey', f'jr-{n:02d}', predecessors=[first])
            self.assertEqual(code, 0, out)
            shas[cell['cell_id']] = first
        return shas

    def carry(self, view):
        return self.ws.ok('carry', '--state-root', self.ws.root, '--study', view['study_id'])

    def statuses(self, mapping):
        return {(e['cell_id'], e['stage']): e['status'] for e in mapping['entries']}

    def test_record_acceptance_binds_scope_hash_predecessor_and_one_result_per_slot(self):
        view = self.ws.approved()
        cell, other = view['cells'][0]['cell_id'], view['cells'][1]['cell_id']
        outside = self.ws.base / 'elsewhere.json'
        code, out = self.accept(view, cell, 'first-impression', 'fi-01', path=outside)
        self.assertEqual(out['error']['code'], 'out_of_scope_artifact')
        code, out = self.accept(view, cell, 'first-impression', 'fi-01')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['identity'], 'verified')
        result = self.ws.root / view['study_id'] / 'artifacts/tasks/fi-01/result.json'
        first = sha(result.read_bytes())
        payload = {'revision': view['revision'], 'cell_id': cell, 'stage': 'first-impression', 'task_id': 'fi-01',
                   'request_id': 'fi-01-r0', 'result': {'path': str(result), 'sha256': '0' * 64},
                   'observed': None, 'predecessors': [], 'context': None}
        self.ws.refused('hash_mismatch', 'record-acceptance', '--state-root', self.ws.root, '--study', view['study_id'],
                        '--input', self.ws.write('mismatch.json', payload))
        code, out = self.accept(view, cell, 'first-impression', 'fi-01', variant='a second, different answer',
                                path=result.with_name('second.json'))
        self.assertEqual(out['error']['code'], 'conflicting_acceptance')
        # The other cell needs its own first impression before its journey can be briefed and admitted.
        self.assertEqual(self.accept(view, other, 'first-impression', 'fi-02')[0], 0)
        code, out = self.accept(view, other, 'journey', 'jr-02', predecessors=[first])
        self.assertEqual(out['error']['code'], 'foreign_predecessor')
        code, out = self.accept(view, cell, 'journey', 'jr-01', predecessors=[first])
        self.assertEqual(code, 0, out)
        # A completion with no admitted request, or one borrowed from another cell, is forged.
        code, out = self.accept(view, view['cells'][2]['cell_id'], 'first-impression', 'fi-03', admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'forged_completion'))
        code, out = self.accept(view, view['cells'][3]['cell_id'], 'first-impression', 'fi-01', admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'forged_completion'))

    def test_limit_deadline_reviewer_and_budget_changes_carry_every_participant_cell_and_keep_counters(self):
        view = self.ws.approved()
        self.ws.admit(view, 'fi-01-r0', 'first-impression', view['cells'][0]['cell_id'])
        self.accept_all(view)
        draft = self.ws.draft()
        draft['limits'].update(deadline='2031-01-01T00:00:00Z', participant_repairs=5)
        draft['review'] = target('fixture-b', 'beta-one')
        revised = self.ws.plan(draft)
        self.assertEqual(revised['budget_change']['raised_pools'], ['participant_repairs'])
        self.assertTrue(revised['budget_change']['needs_explicit_authority'])
        self.assertEqual(revised['charged_tasks'], 16)
        self.assertEqual((revised['task_counts']['max_tasks'], revised['remaining_tasks']), (25, 9))
        mapping = revised['carry_forward']
        self.assertEqual(set(self.statuses(mapping).values()), {'carried'})
        self.assertEqual(len(mapping['filled_slots']), 16)
        self.ws.approve(revised)
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', view['study_id'], '--write')
        code, out = self.ws.admit(revised, 'fi-01-r9', 'first-impression', view['cells'][0]['cell_id'], purpose='resume')
        self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
        self.assertEqual(self.ws.status(revised)['charged'], {'first': 16})

    def test_persona_change_stales_only_its_cells_and_successors(self):
        view = self.ws.approved()
        self.accept_all(view)
        draft = self.ws.draft()
        draft['personas'][1]['constraints'] = ['small kitchen', 'no oven']
        statuses = self.statuses(self.ws.plan(draft)['carry_forward'])
        stale = {key for key, value in statuses.items() if value == 'stale'}
        self.assertEqual({cell.split('--')[0] for cell, _ in stale}, {'budget-student'})
        self.assertEqual(len(stale), 4)
        self.assertEqual(sum(v == 'carried' for v in statuses.values()), 12)

    def test_changed_cells_rerun_as_first_attempts_inside_the_revision_ceiling(self):
        draft = self.ws.draft()
        draft['limits'].update(max_attempts_per_slot=1, participant_repairs=0)
        view = self.ws.plan(draft)
        self.ws.approve(view)
        self.accept_all(view)
        draft['personas'][1]['constraints'] = ['small kitchen', 'no oven']
        revised = self.ws.plan(draft)
        # 16 charged, 4 staled participant slots plus analysis and review, analysis/review repairs 1 + 1.
        self.assertEqual(revised['ceiling']['first_attempts_needed'], 6)
        self.assertEqual((revised['ceiling']['max_tasks'], revised['remaining_tasks']), (24, 8))
        self.assertIn('(ceiling 24 tasks)', revised['approval_instruction'])
        self.ws.approve(revised)
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', view['study_id'], '--write')
        changed = [c['cell_id'] for c in revised['cells'] if c['persona'] == 'budget-student']
        for n, cell in enumerate(changed):
            code, out = self.ws.admit(revised, f'new-{n}', 'first-impression', cell)
            self.assertEqual((code, out['data']['pool']), (0, 'first'), out)
            self.ws.release(revised, f'new-{n}')
            code, out = self.ws.admit(revised, f'again-{n}', 'first-impression', cell, purpose='repair')
            self.assertEqual((code, out['error']['code']), (1, 'budget_exhausted'))
        unchanged = next(c['cell_id'] for c in revised['cells'] if c['persona'] != 'budget-student')
        code, out = self.ws.admit(revised, 'old-0', 'first-impression', unchanged, purpose='resume')
        self.assertEqual((code, out['error']['code']), (1, 'slot_already_filled'))
        self.assertEqual(self.ws.status(revised)['ceiling']['max_tasks'], 24)

    def test_capture_only_revision_carries_first_impressions_and_stales_journeys(self):
        view = self.ws.approved()
        self.accept_all(view)
        draft = self.ws.draft(mode='capture-only', journeys=[])
        draft['prompts'].pop('journey')
        mapping = self.ws.plan(draft, review=False)['carry_forward']
        statuses = self.statuses(mapping)
        self.assertEqual({v for (c, s), v in statuses.items() if s == 'first-impression'}, {'carried'})
        self.assertEqual({v for (c, s), v in statuses.items() if s == 'journey'}, {'stale'})
        self.assertIs(mapping['combined_scope_complete'], False)

    def test_carry_reopens_shared_evidence_once_and_refreshes_between_checks(self):
        from unittest.mock import patch
        sys.path.insert(0, str(PLUGIN / 'scripts'))
        import study as fg
        ev = fg.evidence_module()
        view = self.ws.plan(self.ws.draft(mode='capture-only'))
        self.ws.approve(view)
        for n, cell in enumerate(view['cells'][:2]):
            code, out = self.accept(view, cell['cell_id'], 'first-impression', f'old-{n}')
            self.assertEqual(code, 0, out)
        draft = self.ws.draft(mode='capture-only')
        draft['limits']['max_concurrency'] = 1
        revised = self.ws.plan(draft)
        self.ws.approve(revised)
        self.ws.ok('carry', '--state-root', self.ws.root, '--study', view['study_id'], '--write')
        code, out = self.accept(revised, revised['cells'][2]['cell_id'], 'first-impression', 'native')
        self.assertEqual(code, 0, out)
        study = fg.Study(self.ws.root, view['study_id'])
        kept = {p: p.read_bytes() for p in (study.dir/'accepted').glob('*.json')}
        charged = copy.deepcopy(study.ledger()['charged'])
        mapping = fg.mapping_for(study, revised['revision'])
        self.assertEqual(len(mapping['filled_slots']), 2)
        with patch.object(ev, 'records', wraps=ev.records) as reads:
            errors, actual = fg.validate_mapping(study, mapping)
        self.assertEqual((errors, actual), ([], mapping))
        self.assertEqual(sum(call.args[1] == 'traces' for call in reads.call_args_list), 1)
        old = next(r for r in study.accepted() if r['task_id'] == 'old-0')
        path = study.job_dir/old['result']['path'] if not Path(old['result']['path']).is_absolute() else Path(old['result']['path'])
        original = path.read_bytes()
        path.write_bytes(original + b' ')
        errors, _ = fg.validate_mapping(study, mapping)
        self.assertTrue(any(e['code'] == 'ineligible_reuse' for e in errors), errors)
        path.write_bytes(original)
        self.assertEqual(fg.validate_mapping(study, mapping), ([], mapping))
        # A later host identity snapshot must also be reread by the next check.
        job_path = study.job_dir/'job.json'
        self.assertFalse(job_path.exists())
        wrong = {'providerInstanceId': 'fixture-other', 'model': 'wrong-model'}
        job_path.write_text(json.dumps({'tasks': [{'task_id': old['task_id'],
            'request_id': old['request_id'], 'handles': [{'task_id': 'invented-host',
                'request_id': old['request_id'], 'observed_identity':
                dict(wrong, status='mismatched', sources={'status': wrong})}]}]}))
        errors, _ = fg.validate_mapping(study, mapping)
        self.assertTrue(any(e['code'] == 'ineligible_reuse' for e in errors), errors)
        job_path.unlink()
        self.assertEqual(fg.validate_mapping(study, mapping), ([], mapping))
        for state in ('contaminated', 'clean-in-trace'):
            row = ev.sealed({'request_id': old['request_id'], 'compliance': state, 'limits': []})
            study.retain(ev.ev(f'traces/{row["record_sha256"]}.json'), row, 'fixture trace')
            errors, _ = fg.validate_mapping(study, mapping)
            self.assertTrue(any(e['code'] == 'ineligible_reuse' for e in errors), errors)
        self.assertEqual({p: p.read_bytes() for p in kept}, kept)
        self.assertEqual(study.ledger()['charged'], charged)

    def test_changed_inputs_withdrawn_authority_and_unverified_identity_prevent_reuse(self):
        view = self.ws.approved()
        self.accept_all(view)
        draft = self.ws.draft()
        draft['prompts']['first_impression'] = 'A reworded first-impression prompt.'
        self.assertEqual(set(self.statuses(self.ws.plan(draft)['carry_forward']).values()), {'stale'})
        draft = self.ws.draft()
        draft['sharing'] = [g if g['providerInstanceId'] != 'fixture-c' else
                            dict(g, material_classes=['stimulus', 'persona', 'analysis-report']) for g in draft['sharing']]
        mapping = self.ws.plan(draft, review=False)['carry_forward']
        self.assertEqual(set(self.statuses(mapping).values()), {'stale'})
        self.assertTrue(all('does not permit disclosure to review' in ' '.join(e['reasons']) for e in mapping['entries']))

    def test_validate_carry_rejects_forged_pooled_changed_and_mismatched_entries(self):
        view = self.ws.approved()
        self.accept_all(view)
        draft = self.ws.draft()
        draft['personas'][1]['constraints'] = ['small kitchen', 'no oven']
        revised = self.ws.plan(draft)
        mapping = revised['carry_forward']
        carried = [e for e in mapping['entries'] if e['status'] == 'carried']
        stale = next(e for e in mapping['entries'] if e['status'] == 'stale')
        args = ('validate-carry', '--state-root', self.ws.root, '--study', view['study_id'], '--input')
        self.ws.ok(*args, self.ws.write('good.json', mapping))
        cases = {
            'forged_completion': dict(carried[0], record_sha256='e' * 64, result_sha256='e' * 64),
            'silent_pooling': dict(carried[1], cell_id=carried[0]['cell_id']),
            'ineligible_reuse': dict(stale, status='carried', binding_sha256='0' * 64),
            'hash_mismatch': dict(carried[2], binding_sha256='1' * 64),
        }
        for name, entry in cases.items():
            with self.subTest(case=name):
                bad = dict(mapping, entries=[entry])
                out = self.ws.refused('carry_forward_rejected', *args, self.ws.write(f'{name}.json', bad))
                self.assertEqual(out['data']['errors'][0]['code'], name)
        doubled = dict(mapping, entries=[carried[0], dict(carried[0])])
        out = self.ws.refused('carry_forward_rejected', *args, self.ws.write('doubled.json', doubled))
        self.assertEqual(out['data']['errors'][0]['code'], 'silent_pooling')

    def test_job_spec_declares_final_review_and_pins_workers_through_the_generic_job_helper(self):
        view = self.ws.approved()
        args = ('job-spec', '--state-root', self.ws.root, '--study', view['study_id'], '--installation-id', 'pending',
                '--capabilities', self.ws.catalog())
        self.ws.refused('participant_brief_missing', *args, now=BEFORE)
        # FG-2: a hand-written brief is refused; only the generator's recorded per-cell briefs are used.
        documents = {}
        briefs = self.ws.base / 'briefs'
        briefs.mkdir()
        for n in range(1, 9):
            for prefix in ('fi', 'jr'):
                path = briefs / f'{prefix}-{n:02d}.md'
                path.write_text(f'Invented participant brief {prefix}-{n:02d}: persona, material and tasks only.\n')
                documents[f'{prefix}-{n:02d}'] = {'path': str(path), 'sha256': sha(path.read_bytes())}
        self.ws.refused('participant_brief_unrecorded', *args, '--documents', self.ws.write('hand.json', documents),
                        now=BEFORE)
        evidence = [sys.executable, str(PLUGIN / 'scripts' / 'evidence.py')]
        documents = {}
        for n, cell in enumerate(view['cells'], 1):
            request = self.ws.write(f'brief-{n}.json', {'revision': view['revision'], 'cell_id': cell['cell_id'],
                                                        'stage': 'first-impression', 'task_id': f'fi-{n:02d}'})
            proc = subprocess.run([*evidence, 'brief', '--state-root', str(self.ws.root), '--study', view['study_id'],
                                   '--input', str(request)], capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            documents[f'fi-{n:02d}'] = json.loads(proc.stdout)['data']['document']
        # A journey brief needs the cell's accepted, frozen first impression, so journeys are deferred here
        # (the complete path is exercised in test_focus_group_evidence.py).
        self.ws.refused('participant_brief_missing', *args, '--documents', self.ws.write('fi-only.json', documents),
                        now=BEFORE)
        docs = self.ws.write('docs.json', documents)
        # Install, then build the job for that installation and create it with the shared job helper.
        home = self.ws.base / 'home'
        home.mkdir()
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(self.ws.base / 'config'),
               'XDG_STATE_HOME': str(self.ws.base / 'xdg-state'), 'PYTHONDONTWRITEBYTECODE': '1'}
        prefix, agents = self.ws.base / 'prefix', self.ws.base / 'agents'
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'focus-group', '--prefix',
                               str(prefix), '--agents-root', str(agents)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        package = Path(json.loads(proc.stdout)['data']['version_dir'])
        installation = json.loads((package / 'install-manifest.json').read_text())['installation_id']
        installed = Workspace.__new__(Workspace)
        installed.__dict__.update(self.ws.__dict__, helper=package / 'scripts/study.py')
        spec = installed.ok('job-spec', '--state-root', self.ws.root, '--study', view['study_id'], '--installation-id',
                            installation, '--documents', docs, '--defer-journeys', '--capabilities', self.ws.catalog(),
                            now=BEFORE)
        job = spec['job']
        self.assertEqual([d['task_id'] for d in spec['deferred_journey_tasks']], [f'jr-{n:02d}' for n in range(1, 9)])
        self.assertEqual([s['id'] for s in job['stages']], ['first-impression', 'journey', 'analysis', 'review'])
        self.assertEqual(job['stages'][-1]['depends_on'], ['analysis'])
        review = next(t for t in job['tasks'] if t['task_id'] == 'review')
        # FG-4: the final review is declared fail-closed, with no subject until report.py review-slot binds the exact
        # report documents, their recorded authors and author independence (tests/test_focus_group_report.py).
        self.assertEqual((review['role'], review['max_followups']), ('review', 0))
        self.assertFalse({'reviewed_task_ids', 'reviewed_documents', 'review_required'} & set(review))
        analysis = next(t for t in job['tasks'] if t['task_id'] == 'analysis')
        self.assertEqual((analysis['context_policy'], analysis.get('document')), ('document-only', None))
        self.assertEqual(review['worker_id'], 'focus-group/fidelity-reviewer')
        participants = [t for t in job['tasks'] if t['worker_id'] == 'focus-group/participant']
        self.assertEqual(len(participants), 8)
        self.assertTrue(all(t['context_policy'] == 'document-only' and t['max_followups'] == 0 for t in participants))
        self.assertEqual(sum(t['focus_group']['pilot'] for t in participants), 2)
        job_path = self.ws.write('job.json', job)
        created = subprocess.run([sys.executable, str(package / 'shared/job_cli.py'), 'create', '--state-root',
                                  str(self.ws.root), '--job', view['study_id'], '--input', str(job_path), '--prefix',
                                  str(prefix), '--agents-root', str(agents)],
                                 capture_output=True, text=True, env={**env, **self.ws.policy_env}, timeout=60)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        stored = json.loads((self.ws.root / view['study_id'] / 'job.json').read_text())
        pinned = stored['pins']['focus-group']['effective_workers']
        self.assertEqual(set(pinned), set(WORKERS))
        self.assertEqual(stored['tasks'][0]['write_scope'], {'mode': 'worker-evidence', 'path': 'artifacts/tasks/fi-01'})
        # The study records and the generic job share one private job directory.
        self.assertTrue((self.ws.root / view['study_id'] / 'focus-group' / 'current.json').is_file())
        self.assertEqual(self.ws.status(view)['revision'], view['revision'])

    def test_plugin_policy_stays_out_of_core(self):
        for path in (ROOT / 'core').rglob('*.py'):
            self.assertNotIn('focus', path.read_text().lower(), path)




if __name__ == '__main__':
    unittest.main()
