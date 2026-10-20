"""focus-group FG-3: model identity, pilots, host-backed sessions, lifecycle and resume.

Each study runs through the real entry points: `study.py`, `evidence.py` and `lifecycle.py` from the
source plugin, and the generic job helper `shared/job_cli.py` from a package installed once into a
temporary prefix. The T3 host is invented: the tests record the observations and complete worker
results a coordinator would transcribe (`task-observation`, `result`). Nothing calls a model, a browser,
T3 or GitHub, and nothing here says anything about live provider compatibility.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_plan import (AFTER, BEFORE, CAPS, DELIVERED, EFFORT, PLUGIN, TEMPLATE, Workspace,  # noqa: E402
                                         provider, sha, target)
from tests.test_model_ids import MODEL_ID  # noqa: E402

LIFECYCLE = PLUGIN / 'scripts' / 'lifecycle.py'
LATER = '2029-06-01T00:00:30Z'  # a fresher catalog observation at the controlled clock
INSTALL = {}


def setUpModule():
    tmp = tempfile.TemporaryDirectory()
    INSTALL['tmp'] = tmp
    base = Path(tmp.name)
    (base / 'home').mkdir()
    env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_CONFIG_HOME': str(base / 'config'),
           'XDG_STATE_HOME': str(base / 'xdg-state'), 'PYTHONDONTWRITEBYTECODE': '1'}
    prefix, agents = base / 'prefix', base / 'agents'
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'focus-group', '--prefix',
                           str(prefix), '--agents-root', str(agents)], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    package = Path(json.loads(proc.stdout)['data']['version_dir'])
    INSTALL.update(env=env, prefix=prefix, agents=agents, package=package,
                   installation=json.loads((package / 'install-manifest.json').read_text())['installation_id'])


def tearDownModule():
    INSTALL['tmp'].cleanup()


class Host(Workspace):
    """A Workspace with a real generic job and an invented T3 host the tests drive by hand."""

    def __init__(self, base):
        super().__init__(base)
        self.view = None
        self.hosts = 0
        self.observations = None

    def catalog(self, now=BEFORE, caps=None, observations=None, observed_at=None):
        """Every pre-dispatch observation in one test shows the same schema facts unless it says otherwise."""
        return super().catalog(now, caps, observations if observations is not None else self.observations, observed_at)

    # --- entry points

    def lc(self, *args, now=None):
        argv = [sys.executable, str(LIFECYCLE), *map(str, args)]
        if now:
            argv += ['--now', now]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=self.base,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (proc.stdout, proc.stderr)
        return proc.returncode, json.loads(lines[0])

    def lc_ok(self, *args, now=None):
        code, out = self.lc(*args, now=now)
        assert code == 0, out
        return out['data']

    def study(self, *names):
        return [*names, '--state-root', self.root, '--study', self.view['study_id']]

    def job(self, command, payload):
        self.counter += 1
        path = self.write(f'job-{command}-{self.counter}.json', payload)
        proc = subprocess.run([sys.executable, str(INSTALL['package'] / 'shared/job_cli.py'), command, '--state-root',
                               str(self.root), '--job', self.view['study_id'], '--input', str(path)],
                              capture_output=True, text=True, env=INSTALL['env'], timeout=60)
        return proc.returncode, (json.loads(proc.stdout) if proc.returncode == 0 else proc.stderr)

    def job_ok(self, command, payload):
        code, out = self.job(command, payload)
        assert code == 0, out
        return out

    def job_state(self):
        return json.loads((self.root / self.view['study_id'] / 'job.json').read_text())

    def ledger_bytes(self):
        return (self.root / self.view['study_id'] / 'focus-group' / 'ledger.json').read_bytes()

    @property
    def caller(self):
        job = self.job_state()
        return {'actor': 'coordinator', 'installation_id': job['installation_id'], 'workflow': job['workflow'],
                'package_digest': job['pins']['focus-group']['package_digest']}

    # --- study set-up

    def document(self, n, stage, task):
        self.counter += 1
        code, out = self.call_evidence('brief', '--state-root', self.root, '--study', self.view['study_id'], '--input',
                                       self.write(f'doc-{self.counter}.json', {
                                           'revision': self.view['revision'], 'cell_id': self.cell(n),
                                           'stage': stage, 'task_id': task}))
        assert code == 0, out
        return out['data']['document']

    def start(self, personas=2, **changes):
        """An approved study of `personas` personas on two models, and its job with first-impression slots."""
        draft = self.draft(**changes)
        draft['personas'] = draft['personas'][:personas]
        self.view = self.plan(draft)
        self.approve(self.view)
        self.create_job()
        return self.view

    def create_job(self):
        documents = {f'fi-{n + 1:02d}': self.document(n, 'first-impression', f'fi-{n + 1:02d}')
                     for n in range(len(self.view['cells']))}
        spec = self.ok('job-spec', '--state-root', self.root, '--study', self.view['study_id'], '--installation-id',
                       INSTALL['installation'], '--documents', self.write('fi-docs.json', documents), '--defer-journeys',
                       '--capabilities', self.catalog(), now=BEFORE)
        proc = subprocess.run([sys.executable, str(INSTALL['package'] / 'shared/job_cli.py'), 'create', '--state-root',
                               str(self.root), '--job', self.view['study_id'], '--input',
                               str(self.write('job.json', spec['job'])), '--prefix', str(INSTALL['prefix']),
                               '--agents-root', str(INSTALL['agents'])],
                              capture_output=True, text=True, env=INSTALL['env'], timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        self.documents = documents

    def cell(self, n):
        return self.view['cells'][n]['cell_id']

    def target_of(self, n):
        return {k: self.view['cells'][n][k] for k in ('providerInstanceId', 'model')}

    # --- the invented host

    def admit_slot(self, n, stage, request_id, purpose='initial', **kw):
        return self.admit(self.view, request_id, stage, self.cell(n), purpose=purpose, **kw)

    def prepare(self, task_id):
        out = self.job_ok('prepare', {'caller': self.caller, 'task_id': task_id})
        return json.loads(Path(out['path']).read_text())

    def observe(self, task_id, **event):
        return self.job('task-observation', {'caller': self.caller, 'task_id': task_id, 'event': event})

    def launch(self, task_id, request_id, identity='default', n=0):
        """delegate_task returned a host task ID: record it with the host-reported identity."""
        self.hosts += 1
        host = f'host-{self.hosts}'
        event = {'kind': 'accepted', 'request_id': request_id, 'host_task_id': host, 'child_thread_id': f'thread-{host}',
                 'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False}
        if identity == 'default':
            identity = self.target_of(n)
        if identity is not None:
            event['status_identity'] = identity
        code, out = self.observe(task_id, **event)
        assert code == 0, out
        return host

    def complete(self, task_id, request_id, host, completion, status='completed', work_state='result_available',
                 pending=False, kind='completion'):
        event = {'kind': kind, 'request_id': request_id, 'host_task_id': host, 'status': status,
                 'work_state': work_state, 'has_pending_child_runs': pending}
        if kind == 'completion':
            event['completion_id'] = completion
        return self.observe(task_id, **event)

    def payload_file(self, task_id, payload, name='payload.json'):
        folder = self.root / self.view['study_id'] / 'artifacts' / 'tasks' / task_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        data = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(data)
        return {'path': f'artifacts/tasks/{task_id}/{name}', 'sha256': sha(data), 'bytes': len(data)}

    @staticmethod
    def worker_result(brief, artifacts, **changes):
        result = {'schema_version': 1, **{k: brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id',
                                                                 'worker_id', 'effective_brief_sha256')},
                  'status': 'ready-for-acceptance', 'conclusion': 'Invented participant fixture response.',
                  'requirements': [{'id': r['id'], 'status': 'passed', 'evidence': 'payload.json'}
                                   for r in brief['requirements']],
                  'review_verdict': None, 'findings': [], 'gaps': [], 'uncertainties': [], 'changes': [], 'commands': [],
                  'artifacts': artifacts, 'revision': brief.get('revision'), 'binding': brief.get('snapshot'),
                  'extra_work_requests': [], 'metrics': {}}
        result.update(changes)
        return result

    def transport(self, value):
        self.counter += 1
        path = self.inputs / f'transport-{self.counter}.json'
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return path

    def deliver(self, task_id, request_id, completion, path, form='path'):
        result = {'path': str(path)} if form == 'path' else {'json': path.read_text()}
        return self.job('result', {'caller': self.caller, 'task_id': task_id, 'request_id': request_id,
                                   'completion_id': completion, 'result': result})

    def ingest(self, task_id, request_id, completion, path, now=BEFORE, catalog=None, **extra):
        self.counter += 1
        request = {'task_id': task_id, 'request_id': request_id, 'completion_id': completion, 'transport': str(path),
                   **extra}
        if task_id.startswith('fi') and 'image_delivery' not in extra:
            request['image_delivery'] = DELIVERED
        return self.lc(*self.study('ingest'), '--input', self.write(f'ingest-{self.counter}.json', request),
                       '--capabilities', catalog or self.catalog(now), now=now)

    def first(self, n, request=None, identity='default', payload=None, result=None, admit=True):
        """One first impression end to end: admit, prepare, launch, complete, deliver and ingest."""
        task = f'fi-{n + 1:02d}'
        request = request or f'{task}-r0'
        if admit:
            code, out = self.admit_slot(n, 'first-impression', request)
            assert code == 0, out
        brief = self.prepare(task)
        host = self.launch(task, request, identity, n)
        body = payload or self.first_payload(self.view, self.cell(n), self.documents[task]['sha256'])
        item = self.payload_file(task, body)
        path = self.transport(result(brief, item) if result else self.worker_result(brief, [item]))
        completion = f'done-{request}'
        assert self.complete(task, request, host, completion)[0] == 0
        delivered = self.deliver(task, request, completion, path)
        code, out = self.ingest(task, request, completion, path)
        self.reconcile()  # the coordinator reconciles on every host notification
        return {'code': code, 'out': out, 'host': host, 'brief': brief, 'transport': path, 'completion': completion,
                'delivered': delivered, 'task': task, 'request': request}

    def journey_ready(self, n):
        """Bind a verified fixture context, build the journey brief and add its job slot."""
        task = f'jr-{n + 1:02d}'
        self.bound_context(self.view, self.cell(n))
        document = self.document(n, 'journey', task)
        out = self.lc_ok(*self.study('journey-slots'), '--documents', self.write(f'{task}-docs.json', {task: document}))
        if out['added']:
            self.job_ok('decision', out['decision_input'])
            self.job_ok('plan-revision', out['plan_revision_input'])
        return document

    def journey(self, n, request=None, identity='default'):
        task = f'jr-{n + 1:02d}'
        request = request or f'{task}-r0'
        document = self.journey_ready(n)
        code, out = self.admit_slot(n, 'journey', request)
        assert code == 0, out
        brief = self.prepare(task)
        host = self.launch(task, request, identity, n)
        context = self.bound_context(self.view, self.cell(n))
        item = self.payload_file(task, self.journey_payload(self.view, self.cell(n), document['sha256'], context))
        path = self.transport(self.worker_result(brief, [item]))
        completion = f'done-{request}'
        assert self.complete(task, request, host, completion)[0] == 0
        assert self.deliver(task, request, completion, path)[0] == 0
        outcome = self.ingest(task, request, completion, path, context={'class': 'fresh-anonymous', **context})
        self.reconcile()
        return outcome

    def revise_job(self):
        """Move the job to the current study revision through lifecycle.py job-revision: list its slots, build
        the brief of every unfilled first-impression slot for the task it names, then record the owner decision
        (the approval of this exact revision) and the plan revision through the shared job helper."""
        listed = self.lc_ok(*self.study('job-revision'))
        ids = [c['cell_id'] for c in self.view['cells']]
        documents = {row['task_id']: self.document(ids.index(row['slot'].split(':')[0]), 'first-impression',
                                                   row['task_id'])
                     for row in listed['slots'] if row['state'] == 'needs-brief'
                     and row['slot'].endswith(':first-impression')}
        out = self.lc_ok(*self.study('job-revision'), '--documents', self.write(f'revise-{self.counter}.json', documents))
        if out['changed']:
            self.job_ok('decision', out['decision_input'])
            self.job_ok('plan-revision', out['plan_revision_input'])
        return out, documents

    def reconcile(self, now=BEFORE):
        return self.lc_ok(*self.study('reconcile'), now=now)

    def resume(self, now=BEFORE, catalog=None):
        return self.lc_ok(*self.study('resume'), '--capabilities', catalog or self.catalog(now), now=now)

    def progress(self):
        return self.lc_ok(*self.study('progress'))

    def charged(self):
        return self.status(self.view)['charged']

    def session(self, request_id):
        folder = self.root / self.view['study_id'] / 'focus-group' / 'sessions' / request_id
        return [json.loads(p.read_text()) for p in sorted(folder.glob('*.json'))]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Host(Path(self.tmp.name).resolve())

    def refused(self, outcome, code):
        self.assertEqual((outcome[0], outcome[1]['error']['code']), (1, code), outcome[1])
        return outcome[1]


# ----------------------------------------------------------------------------- REQ-IDENTITY


class IdentityTest(Case):
    """Requested and host-observed identity stay separate; only verified identity is verified coverage."""

    def identity_of(self, run):
        self.assertEqual(run['code'], 0, run['out'])
        return run['out']['data']['identity']

    def test_requested_target_is_not_observed_identity(self):
        self.h.start()
        verified = self.h.first(0)
        self.assertEqual(self.identity_of(verified), 'verified')
        # No host identity at all, and a provider without a model, are unreported, never filled from the target.
        self.assertEqual(self.identity_of(self.h.first(1, identity=None)), 'unreported')
        missing = self.h.first(2, identity={'providerInstanceId': 'fixture-a'})
        self.assertEqual(self.identity_of(missing), 'unreported')
        cells = {c['cell_id']: c for c in self.h.progress()['cells']}
        row = cells[self.h.cell(2)]['first-impression']
        self.assertEqual((row['identity'], row['verified_coverage'], row['observed']['model']), ('unreported', False, None))
        self.assertEqual(cells[self.h.cell(2)]['requested']['model'], 'alpha-swift')
        self.assertIsNone(cells[self.h.cell(1)]['first-impression']['observed'])
        coverage = self.h.evidence_ok('coverage', '--state-root', self.h.root, '--study', self.h.view['study_id'])
        self.assertEqual([r.get('first_identity') for r in coverage['cells']],
                         ['verified', 'unreported', 'unreported', None])
        self.assertEqual(coverage['verified_identity'], {'first_impressions': 1, 'journeys': 0})
        self.assertTrue(cells[self.h.cell(0)]['first-impression']['verified_coverage'])
        # A missing model stays missing: there is nothing for the owner to accept, so the record is a visible hold.
        source = self.h.base / 'owner.txt'
        source.write_text('Selected option: Accept\n')
        out = self.refused(self.h.lc(*self.h.study('accept-identity'), '--input', self.h.write('missing.json', {
            'record_sha256': missing['out']['data']['record_sha256'], 'message_ref': 'picker-identity',
            'statement': 'Accept', 'source': str(source), 'source_sha256': sha(source.read_bytes())})),
            'identity_unreported')
        evidence = out['data']['evidence']
        self.assertEqual((evidence['readings'], evidence['requested']['model'], evidence['instruction']),
                         ([{'source': 'status', 'providerInstanceId': 'fixture-a', 'model': None}], 'alpha-swift', None))
        self.assertEqual(cells[self.h.cell(2)]['first-impression']['problems'], ['identity_unverified'])

    def test_wrong_model_and_alias_are_excluded_until_the_owner_accepts_the_visible_discrepancy(self):
        self.h.start()
        wrong = self.h.first(0, identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        self.assertEqual(self.identity_of(wrong), 'mismatched')
        alias = self.h.first(1, identity={'providerInstanceId': 'fixture-b', 'model': 'beta-latest'})
        self.assertEqual(self.identity_of(alias), 'ambiguous')
        self.assertIn('never resolved to the request', alias['out']['data']['identity_reason'])
        # A pilot with unverified identity gates its model's other cells; nothing is charged for the refusal.
        before = self.h.charged()
        out = self.refused(self.h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(out['data']['pilot']['reasons'], ['identity mismatched'])
        self.assertEqual(self.h.charged(), before)
        record = wrong['out']['data']['record_sha256']
        instruction = ('Accept observed model fixture-a/alpha-deep for focus-group cell '
                       f'{self.h.cell(0)} first-impression request fi-01-r0 (requested fixture-a/alpha-swift)')

        def decide(statement, source_text):
            self.h.counter += 1
            source = self.h.base / 'owner' / f'identity-{self.h.counter}.txt'
            source.parent.mkdir(exist_ok=True)
            source.write_text(source_text)
            return self.h.lc(*self.h.study('accept-identity'), '--input', self.h.write(f'id-{self.h.counter}.json', {
                'record_sha256': record, 'message_ref': 'picker-identity', 'statement': statement,
                'source': str(source), 'source_sha256': sha(source.read_bytes())}))

        self.refused(decide(instruction, f'Selected option: Do not {instruction}\n'), 'approval_not_affirmative')
        code, out = decide(instruction, f'Selected option: {instruction}\n')
        self.assertEqual((code, out['data']['identity'], out['data']['verified']),
                         (0, 'owner-accepted-discrepancy', False), out)
        row = {c['cell_id']: c for c in self.h.progress()['cells']}[self.h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['verified_coverage'], row['observed']['model']),
                         ('owner-accepted-discrepancy', False, 'alpha-deep'))
        # Consistent wrong-model evidence: one observed model beside the request, and the decision is bound to
        # the hash of exactly the evidence shown.
        found, decision = row['identity_evidence'], out['data']['decision']
        self.assertEqual((found['kind'], found['observed'], found['instruction']),
                         ('wrong-model', {'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'}, instruction))
        self.assertEqual((decision['discrepancy_sha256'], decision['discrepancy']['kind'],
                          [(r['source'], r['model']) for r in decision['discrepancy']['readings']]),
                         (found['discrepancy_sha256'], 'wrong-model', [('status', 'alpha-deep')]))
        self.assertEqual(self.h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        # An owner-accepted discrepancy is still not verified identity, so it never carries forward.
        draft = self.h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        mapping = self.h.plan(draft)['carry_forward']
        entry = next(e for e in mapping['entries'] if e['record_sha256'] == record)
        self.assertEqual(entry['status'], 'stale')
        self.assertIn('observed model identity is not verified against the request', entry['reasons'])

    def test_unsupported_or_withdrawn_option_never_changes_the_matrix(self):
        caps = {'providers': [provider('fixture-a', ['alpha-swift'], options=EFFORT), provider('fixture-b', ['beta-one']),
                              provider('fixture-c', ['gamma-pro'])]}
        h = self.h
        draft = h.draft(participant_models=[target('fixture-a', 'alpha-swift', reasoningEffort='max'),
                                            target('fixture-b', 'beta-one')])
        code, out = h.plan(draft, expect=1, caps=caps)
        self.assertEqual((code, out['error']['code'], out['data']['problems'][0]['problem']),
                         (1, 'matrix_unavailable', 'unsupported_option'))
        draft['participant_models'][0] = target('fixture-a', 'alpha-swift', reasoningEffort='high')
        view = h.plan(draft, caps=caps)
        h.approve(view)
        h.view = view
        # The option disappears from the fresh catalog: admission refuses and charges nothing.
        withdrawn = {'providers': [provider('fixture-a', ['alpha-swift']), *caps['providers'][1:]]}
        out = self.refused(h.admit(view, 'fi-01-r0', 'first-impression', view['cells'][0]['cell_id'],
                                   catalog=h.catalog(caps=withdrawn, observed_at=LATER)), 'readiness_stale')
        self.assertEqual(out['data']['catalog_problems'][0]['problem'], 'unsupported_option')
        self.assertEqual(h.status(view)['charged'], {})

    def test_plugin_scripts_hard_code_no_current_model_id(self):
        for name in ('study.py', 'evidence.py', 'lifecycle.py'):
            self.assertIsNone(MODEL_ID.search((PLUGIN / 'scripts' / name).read_text()), name)


# ----------------------------------------------------------------------------- REQ-PILOT


class PilotTest(Case):
    """Each model's pilot gates its own remaining cells, separately for capture and journeys."""

    def test_failed_capture_validation_locks_only_that_models_capture_cells(self):
        self.h.start()
        # Model A's pilot answers with a visual claim on a text-only basis: invalid capture output.
        body = self.h.first_payload(self.h.view, self.h.cell(0), self.h.documents['fi-01']['sha256'])
        body['image_use'] = {'saw_images': False, 'basis': 'text-only'}
        body['claims'][0]['kind'] = 'visual'
        bad = self.h.first(0, payload=body)
        self.assertEqual(bad['code'], 1, bad['out'])
        self.assertEqual(bad['out']['data']['category'], 'evidence')
        before = self.h.charged()
        out = self.refused(self.h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(out['data']['pilot']['pilot_cell'], self.h.cell(0))
        self.assertEqual(self.h.charged(), before)
        # Model B is unaffected: its pilot passes and unlocks its own second cell.
        self.assertEqual(self.h.first(1)['code'], 0)
        self.assertEqual(self.h.first(3)['code'], 0)
        pilots = {(p['pilot_cell'], p['stage']): p['state'] for p in self.h.lc_ok(*self.h.study('pilots'))['pilots']}
        self.assertEqual((pilots[(self.h.cell(0), 'first-impression')], pilots[(self.h.cell(1), 'first-impression')]),
                         ('failed', 'passed'))
        self.assertEqual(pilots[(self.h.cell(1), 'journey')], 'pending')

    def test_pending_pilot_holds_other_cells_and_an_accepted_pilot_is_never_dispatched_again(self):
        self.h.start()
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        self.refused(self.h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_pending')
        self.assertEqual(self.h.first(0, admit=False)['code'], 0)
        self.assertEqual(self.h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        # The accepted pilot occupies its normal cell: no second dispatch, and resume lists it as accepted.
        self.refused(self.h.admit_slot(0, 'first-impression', 'fi-01-r9', purpose='resume'), 'slot_already_filled')
        slots = {s['slot']: s for s in self.h.resume()['slots']}
        self.assertEqual((slots[f'{self.h.cell(0)}:first-impression']['state'],
                          slots[f'{self.h.cell(0)}:first-impression']['pilot']), ('accepted', True))
        self.assertEqual(slots[f'{self.h.cell(2)}:first-impression']['state'], 'in-flight')

    def test_unavailable_journey_capability_never_blocks_valid_capture_cells(self):
        observations = [{'fact': 'isolation', 'state': 'unavailable', 'providerInstanceId': 'fixture-a',
                         'source': 'fixture tool schema'}]
        self.h.observations = observations
        self.h.start()
        catalog = self.h.catalog()
        for n in range(4):
            self.assertEqual(self.h.first(n)['code'], 0)
        out = self.refused(self.h.admit(self.h.view, 'jr-01-r0', 'journey', self.h.cell(0), catalog=catalog),
                           'journey_unavailable')
        self.assertEqual(out['data']['capabilities']['isolation']['state'], 'unavailable')
        # Model B has no recorded absence: its pilot journey runs and only then unlocks its second journey.
        self.h.journey_ready(3)
        self.refused(self.h.admit_slot(3, 'journey', 'jr-04-r0'), 'pilot_pending')
        self.assertEqual(self.h.journey(1)[0], 0)
        self.assertEqual(self.h.admit_slot(3, 'journey', 'jr-04-r0')[0], 0)
        resumed = self.h.resume()
        self.assertTrue(resumed['capture_scope_filled'])
        self.assertIsNone(resumed['combined_scope_complete'])
        self.assertFalse(resumed['complete'])

    def test_an_unverified_journey_context_marks_that_models_journeys_unavailable(self):
        self.h.start()
        for n in range(4):
            self.assertEqual(self.h.first(n)['code'], 0)
        # Model A's pilot child has no browser tools: its binding is not verified and no brief can be built.
        ids = [c['cell_id'] for c in self.h.view['cells']]
        probe = self.h.evidence_ok('probe-plan', '--state-root', self.h.root, '--study', self.h.view['study_id'],
                                   '--input', self.h.write('probe-a.json', {'revision': self.h.view['revision'],
                                                                           'cell_ids': ids}))
        readings = {cid: {'origin': probe['origin'], 'shared': dict.fromkeys(('cookie', 'local', 'session'), row['value']),
                          'others_own_seen': dict.fromkeys(('cookie', 'local', 'session'), False), 'cleared': False}
                    for cid, row in probe['cells'].items()}
        tools = {'schema_version': 1, 'observed_at': BEFORE, 'source': 'fixture child tool observation',
                 'native_browser': None, 'tools': [{'name': 'Read'}]}
        code, out = self.h.call_evidence('bind-context', '--state-root', self.h.root, '--study', self.h.view['study_id'],
                                         '--input', self.h.write('bind-a.json', {
                                             'revision': self.h.view['revision'], 'cell_id': self.h.cell(0),
                                             'child_tools': tools, 'context': {'reference': 'fixture-a-ctx',
                                                                               'boundary': 'isolated-context'},
                                             'assignment': {'kind': 'host-enforced', 'source': 'fixture host receipt',
                                                            'receipt_sha256': sha(b'fixture-a-ctx'),
                                                            'child_ref': self.h.cell(0)},
                                             'evidence_class': 'fixture',
                                             'probe': {'probe_id': probe['probe_id'], 'readings': readings}}))
        self.assertEqual(code, 1, out)
        self.refused(self.h.admit_slot(0, 'journey', 'jr-01-r0'), 'journey_brief_missing')
        pilots = {(p['pilot_cell'], p['stage']): p for p in self.h.lc_ok(*self.h.study('pilots'))['pilots']}
        self.assertEqual(pilots[(self.h.cell(0), 'journey')]['state'], 'unavailable')
        self.refused(self.h.admit_slot(2, 'journey', 'jr-03-r0'), 'journey_brief_missing')
        self.assertEqual(self.h.charged(), {'first': 4})

    def test_protocol_change_invalidates_the_pilot_and_capture_only_completes_only_its_scope(self):
        self.h.start()
        for n in range(4):
            self.assertEqual(self.h.first(n)['code'], 0)
        charged = self.h.charged()
        # A capture-only revision carries every unchanged first impression; combined scope stays incomplete.
        draft = self.h.draft(mode='capture-only', journeys=[])
        draft['personas'] = draft['personas'][:2]
        draft.pop('journey_context', None)
        draft['prompts'].pop('journey', None)
        capture = self.h.plan(draft)
        self.h.approve(capture)
        self.h.ok('carry', '--state-root', self.h.root, '--study', capture['study_id'], '--write')
        self.h.view = capture
        resumed = self.h.resume()
        self.assertTrue(resumed['capture_scope_filled'])
        self.assertEqual((resumed['combined_scope_complete'], resumed['complete']), (False, False))
        self.assertEqual({s['state'] for s in resumed['slots']}, {'accepted'})
        self.assertEqual(self.h.charged(), charged)
        # A protocol change is a new revision: every first impression is stale, the old pilot is not relabelled,
        # and the model's other cells wait for a fresh pilot.
        draft['prompts']['first_impression'] = draft['prompts']['first_impression'] + ' Note one thing that works.'
        changed = self.h.plan(draft)
        self.assertEqual({e['status'] for e in changed['carry_forward']['entries']}, {'stale'})
        self.h.approve(changed)
        self.h.ok('carry', '--state-root', self.h.root, '--study', changed['study_id'], '--write')
        self.h.view = changed
        # FG3-R4: the job still prepares an earlier revision, so nothing is admitted or charged until the job
        # follows the approved revision through the supported route.
        self.refused(self.h.admit_slot(0, 'first-impression', 'fi-01-new'), 'job_revision_stale')
        self.assertEqual(self.h.charged(), charged)
        self.h.revise_job()
        self.refused(self.h.admit_slot(2, 'first-impression', 'fi-03-new'), 'pilot_pending')
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-new')[0], 0)


# ----------------------------------------------------------------------------- REQ-SESSION


class SessionTest(Case):
    """Complete outputs pass the shared parser; every failure keeps its raw bytes and reason."""

    def setUp(self):
        super().setUp()
        self.h.start()

    def attempt(self, n, value, completion='c1', form='path', request=None, identity='default'):
        task = f'fi-{n + 1:02d}'
        request = request or f'{task}-r0'
        if request not in json.loads(self.h.ledger_bytes())['requests']:
            assert self.h.admit_slot(n, 'first-impression', request)[0] == 0
        brief = self.h.prepare(task)
        host = self.h.launch(task, request, identity, n)
        item = self.h.payload_file(task, self.h.first_payload(self.h.view, self.h.cell(n),
                                                              self.h.documents[task]['sha256']))
        raw = value(brief, item) if callable(value) else value
        path = self.h.transport(raw)
        assert self.h.complete(task, request, host, completion)[0] == 0
        delivered = self.h.deliver(task, request, completion, path, form)
        return path, delivered, self.h.ingest(task, request, completion, path)

    def assert_session_failure(self, outcome, code, reason=None):
        path, _, (exit_code, out) = outcome
        self.assertEqual((exit_code, out['error']['code']), (1, code), out)
        self.assertEqual((out['data']['category'], out['data']['product_friction']), ('session', False))
        raw = self.h.root / self.h.view['study_id'] / 'focus-group' / out['data']['raw_retained']
        self.assertEqual(raw.read_bytes(), path.read_bytes())
        if reason:
            self.assertIn(reason, out['error']['message'])
        return out

    def retry(self, task):
        """A charged new attempt: the job records a new request ID, which the study then admits."""
        self.h.reconcile()
        self.h.job_ok('retry', {'caller': self.h.caller, 'task_id': task, 'reason': 'malformed result'})
        return next(t for t in self.h.job_state()['tasks'] if t['task_id'] == task)['request_id']

    def test_missing_extra_duplicate_key_and_wrong_slot_results_keep_raw_bytes_and_reasons(self):
        # Both pilots take two attempts each, so every shape runs on a real first or charged retry.
        shapes = [
            (0, lambda b, i: {k: v for k, v in self.h.worker_result(b, [i]).items() if k != 'metrics'}, 'metrics'),
            (1, lambda b, i: dict(self.h.worker_result(b, [i]), verdict='great'), 'verdict'),
            (0, lambda b, i: json.dumps(self.h.worker_result(b, [i]))[:-1].encode() + b', "status": "failed"}',
             'duplicate'),
            (1, lambda b, i: self.h.worker_result(b, [i], logical_slot_id='fi-01'), 'logical_slot_id'),
        ]
        seen = set()
        for k, (n, value, reason) in enumerate(shapes):
            task = f'fi-{n + 1:02d}'
            request = self.retry(task) if task in seen else None
            seen.add(task)
            with self.subTest(shape=reason):
                out = self.assert_session_failure(self.attempt(n, value, completion=f'c{k}', request=request),
                                                  'malformed_result', reason)
                self.assertIn('transport_path', out['data']['transport'])
        failures = self.h.progress()['session_failures']
        self.assertEqual(([f['code'] for f in failures], {f['category'] for f in failures}),
                         (['malformed_result'] * 4, {'session'}))
        self.assertEqual(self.h.charged(), {'first': 2, 'participant_repairs': 2})
        # Neither pilot passed, so once their tasks are reconciled neither model's other cells may start.
        self.h.reconcile()
        self.refused(self.h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.refused(self.h.admit_slot(3, 'first-impression', 'fi-04-r0'), 'pilot_failed')

    def test_truncated_and_oversize_transports_are_never_truncated_or_accepted(self):
        out = self.assert_session_failure(
            self.attempt(0, lambda b, i: json.dumps(self.h.worker_result(b, [i])).encode()[:150]), 'malformed_result')
        self.assertIn('transport', out['data'])
        big = lambda b, i: self.h.worker_result(b, [i], conclusion='word ' * 7000)
        path, delivered, outcome = self.attempt(1, big, completion='c-big', form='json')
        self.assertEqual(delivered[0], 0, delivered)  # the job retains the oversize transport as malformed
        self.assert_session_failure((path, delivered, outcome), 'oversize_transport')
        self.assertGreater(path.stat().st_size, 32768)

    def test_wrong_cell_broken_hash_and_conflicting_duplicates_through_ingestion(self):
        # Another cell's payload inside this task's result.
        def foreign(brief, item):
            path = self.h.root / self.h.view['study_id'] / item['path']
            body = self.h.first_payload(self.h.view, self.h.cell(1), self.h.documents['fi-02']['sha256'])
            path.write_bytes(json.dumps(body, sort_keys=True).encode())
            return self.h.worker_result(brief, [dict(item, sha256=sha(path.read_bytes()), bytes=path.stat().st_size)])
        _, _, (code, out) = self.attempt(0, foreign)
        self.assertEqual((code, out['error']['code'], out['data']['product_friction']), (1, 'payload_invalid', False))
        # A valid result, then a second, different response for the same request.
        path, _, (code, out) = self.attempt(1, lambda b, i: self.h.worker_result(b, [i]), completion='first')
        self.assertEqual(code, 0, out)
        brief = json.loads(Path(self.h.job_state()['tasks'][1]['brief']['path']).read_text())
        other = self.h.transport(self.h.worker_result(brief, [], conclusion='A conflicting second answer.'))
        self.assertEqual(self.h.deliver('fi-02', 'fi-02-r0', 'second', other)[0], 2)
        code, out = self.h.ingest('fi-02', 'fi-02-r0', 'second', other)
        self.assertEqual((code, out['error']['code']), (1, 'conflicting_duplicate'))
        # The identical response again is idempotent: one record, no second log entry.
        log = self.h.session('fi-02-r0')
        code, again = self.h.ingest('fi-02', 'fi-02-r0', 'first', path)
        self.assertEqual((code, again['data']['duplicate']), (0, True))
        self.assertEqual(len(self.h.session('fi-02-r0')), len(log))
        self.assertEqual([r['outcome'] for r in log], ['accepted', 'refused'])
        accepted = list((self.h.root / self.h.view['study_id'] / 'focus-group' / 'accepted').glob('*.json'))
        self.assertEqual(len([p for p in accepted if self.h.cell(1) in p.name]), 1)
        # A worker result citing bytes that are not the payload's (model B's pilot has passed).
        _, _, (code, out) = self.attempt(3, lambda b, i: self.h.worker_result(b, [dict(i, sha256='0' * 64)]),
                                         completion='c-hash')
        self.assertEqual((code, out['error']['code']), (1, 'hash_mismatch'))
        raw = self.h.root / self.h.view['study_id'] / 'focus-group' / 'sessions' / 'raw'
        self.assertEqual({p.read_bytes() for p in raw.iterdir()} >= {path.read_bytes(), other.read_bytes()}, True)

    def test_blocked_participant_and_unparsed_transport_are_session_outcomes(self):
        blocked = lambda b, i: self.h.worker_result(b, [i], status='blocked', gaps=['images were not delivered'],
                                                     requirements=[{'id': r['id'], 'status': 'unavailable',
                                                                    'evidence': 'no images', 'reason': 'not delivered'}
                                                                   for r in b['requirements']])
        out = self.assert_session_failure(self.attempt(0, blocked), 'participant_not_ready')
        self.assertEqual(out['data']['gaps'], ['images were not delivered'])
        # A transport the coordinator never gave the shared parser is retained and refused.
        self.assertEqual(self.h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)
        self.h.prepare('fi-02')
        self.h.launch('fi-02', 'fi-02-r0', n=1)
        stray = self.h.transport(b'{"not": "parsed"}')
        code, out = self.h.ingest('fi-02', 'fi-02-r0', 'never-delivered', stray)
        self.assertEqual((code, out['error']['code'], out['data']['category']), (1, 'not_ingested_by_job', 'session'))
        code, out = self.h.ingest('fi-02', 'fi-01-r0', 'never-delivered', stray)
        self.assertEqual((code, out['error']['code']), (1, 'wrong_slot'))

    def test_late_prior_revision_result_keeps_its_revision_and_joins_only_by_mapping(self):
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        old = self.h.view
        draft = self.h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        revised = self.h.plan(draft)
        self.h.approve(revised)
        self.h.ok('carry', '--state-root', self.h.root, '--study', old['study_id'], '--write')
        run = self.h.first(0, admit=False)
        self.assertEqual(run['code'], 0, run['out'])
        record = json.loads(next((self.h.root / old['study_id'] / 'focus-group' / 'accepted').glob('*.json')).read_text())
        self.assertEqual(record['revision'], old['revision'])
        self.h.view = revised
        row = {c['cell_id']: c for c in self.h.progress()['cells']}[self.h.cell(0)]
        self.assertEqual(row['first-impression'], {'state': 'unfilled'})


# ----------------------------------------------------------------------------- REQ-LIFECYCLE


class LifecycleTest(Case):
    """T3 owns dispatch; the helpers only read recorded observations once and never loop."""

    def setUp(self):
        super().setUp()
        self.h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=2))

    def row(self, view, request):
        return next(r for r in view['requests'] if r['request_id'] == request)

    def test_request_recorded_before_launch_and_response_loss_reuses_it_uncharged(self):
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        self.h.prepare('fi-01')
        view = self.h.reconcile()
        self.assertEqual(self.row(view, 'fi-01-r0')['state'], 'prepared-not-dispatched')
        self.assertEqual(view['actions']['dispatch_same_request'], [{'task_id': 'fi-01', 'request_id': 'fi-01-r0'}])
        # delegate_task's response is lost: the job records uncertainty, and the retry keeps the request ID.
        self.assertEqual(self.h.observe('fi-01', kind='uncertain', request_id='fi-01-r0')[0], 0)
        self.assertEqual(self.row(self.h.reconcile(), 'fi-01-r0')['state'], 'dispatch-uncertain')
        code, out = self.h.admit_slot(0, 'first-impression', 'fi-01-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False))
        host = self.h.launch('fi-01', 'fi-01-r0')
        self.assertEqual(self.row(self.h.reconcile(), 'fi-01-r0')['state'], 'running')
        self.assertEqual(self.h.charged(), {'first': 1})
        self.assertTrue(host)

    def test_concurrency_is_checked_before_every_launch_and_only_a_host_terminal_frees_it(self):
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        self.assertEqual(self.h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)
        self.refused(self.h.admit_slot(0, 'first-impression', 'fi-01-x'), 'concurrency_limit')
        # A claimed status or summary cannot close a request once a job exists.
        self.refused((self.h.call('release', '--state-root', self.h.root, '--study', self.h.view['study_id'],
                                  '--input', self.h.write('claim.json', {'request_id': 'fi-01-r0',
                                                                          'terminal_status': 'completed',
                                                                          'source': 'summary says done'}))),
                     'reconcile_required')
        brief = self.h.prepare('fi-01')
        host = self.h.launch('fi-01', 'fi-01-r0')
        item = self.h.payload_file('fi-01', self.h.first_payload(self.h.view, self.h.cell(0),
                                                                 self.h.documents['fi-01']['sha256']))
        path = self.h.transport(self.h.worker_result(brief, [item]))
        # The parent is terminal and its summary says done, but a later child run is still pending.
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, 'c1', pending=True)[0], 0)
        view = self.h.reconcile()
        self.assertEqual((self.row(view, 'fi-01-r0')['state'], view['quiescent']), ('pending-descendants', False))
        self.refused(self.h.admit_slot(0, 'first-impression', 'fi-01-x'), 'concurrency_limit')
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, None, kind='reconciled')[0], 0)
        view = self.h.reconcile()
        self.assertEqual(self.row(view, 'fi-01-r0')['state'], 'terminal-confirmed')
        self.assertEqual(view['actions']['ingest'], [{'task_id': 'fi-01', 'request_id': 'fi-01-r0'}])
        self.assertEqual(self.h.deliver('fi-01', 'fi-01-r0', 'c1', path)[0], 0)
        self.assertEqual(self.h.ingest('fi-01', 'fi-01-r0', 'c1', path)[0], 0)
        self.assertEqual(self.h.reconcile()['actions']['ingest'], [])
        self.assertEqual(self.h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)

    def test_duplicate_and_out_of_order_notifications_are_idempotent_and_never_reset_budget(self):
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        self.h.prepare('fi-01')
        host = self.h.launch('fi-01', 'fi-01-r0')
        for _ in range(2):
            self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, 'note-1')[0], 0)
        first = self.h.reconcile()
        ledger = self.h.ledger_bytes()
        self.assertEqual(self.h.reconcile(), first)
        self.assertEqual(self.h.ledger_bytes(), ledger)
        # An older running observation recorded after the terminal one: not quiescent, nothing reopened or refunded.
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, None, status='running', work_state='working',
                                         kind='reconciled')[0], 0)
        view = self.h.reconcile()
        row = self.row(view, 'fi-01-r0')
        self.assertEqual((row['state'], row['ledger_state'], view['quiescent']),
                         ('conflicting-observations', 'terminal', False))
        self.assertEqual(view['actions']['task_status'], [{'host_task_id': host, 'request_id': 'fi-01-r0'}])
        self.assertEqual(self.h.charged(), {'first': 1})
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, None, kind='reconciled')[0], 0)
        self.assertTrue(self.h.reconcile()['quiescent'])

    def test_pending_question_provider_outage_and_charged_retry(self):
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        self.h.prepare('fi-01')
        host = self.h.launch('fi-01', 'fi-01-r0')
        self.assertEqual(self.h.observe('fi-01', kind='approval-wait', request_id='fi-01-r0', wait_id='q-1')[0], 0)
        view = self.h.reconcile()
        self.assertEqual((self.row(view, 'fi-01-r0')['state'], self.row(view, 'fi-01-r0')['waits']),
                         ('pending-question', ['q-1']))
        self.assertEqual(self.h.observe('fi-01', kind='approval-resolved', request_id='fi-01-r0', wait_id='q-1')[0], 0)
        # The provider fails mid-task: a provider outcome, not product friction; the request closes, never refunded.
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, 'c-fail', status='failed')[0], 0)
        view = self.h.reconcile()
        self.assertEqual((self.row(view, 'fi-01-r0')['state'], view['quiescent']), ('provider-failure', True))
        path = self.h.transport(b'Provider error: upstream unavailable')
        self.assertEqual(self.h.deliver('fi-01', 'fi-01-r0', 'c-fail', path)[0], 0)
        code, out = self.h.ingest('fi-01', 'fi-01-r0', 'c-fail', path)
        self.assertEqual((code, out['error']['code'], out['data']['product_friction']), (1, 'malformed_result', False))
        # A charged new attempt takes the job's new recorded request ID from the shared repair pool.
        self.h.job_ok('retry', {'caller': self.h.caller, 'task_id': 'fi-01', 'reason': 'provider failure'})
        task = self.h.job_state()['tasks'][0]
        self.assertNotEqual(task['request_id'], 'fi-01-r0')
        self.assertIn('fi-01-r0', task['retired_request_ids'])
        code, out = self.h.admit_slot(0, 'first-impression', task['request_id'], purpose='repair')
        self.assertEqual((code, out['data']['pool']), (0, 'participant_repairs'), out)
        self.assertEqual(self.h.charged(), {'first': 1, 'participant_repairs': 1})
        # The host catalog shows the provider down: nothing more launches, and nothing is charged.
        down = {'providers': [provider('fixture-a', ['alpha-swift', 'alpha-deep'], runnable=False), *CAPS['providers'][1:]]}
        self.refused(self.h.admit(self.h.view, 'fi-02-r0', 'first-impression', self.h.cell(1),
                                  catalog=self.h.catalog(caps=down, observed_at=LATER)), 'readiness_stale')
        self.assertEqual(self.h.charged(), {'first': 1, 'participant_repairs': 1})

    def test_deadline_expiry_and_unconfirmed_cancellation_stay_visible(self):
        self.assertEqual(self.h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        self.h.prepare('fi-01')
        host = self.h.launch('fi-01', 'fi-01-r0')
        view = self.h.reconcile(now=AFTER)
        self.assertEqual((view['deadline_expired'], view['actions']['task_cancel']),
                         (True, [{'host_task_id': host, 'request_id': 'fi-01-r0'}]))
        self.assertEqual((view['quiescent'], view['complete']), (False, False))
        self.refused(self.h.admit_slot(1, 'first-impression', 'fi-02-r0', now=AFTER), 'deadline_passed')
        # Cancellation records intent; the parent's terminal state with pending children is not quiescence.
        cancel = self.h.ok('cancel', '--state-root', self.h.root, '--study', self.h.view['study_id'])
        self.assertEqual((cancel['cancel'], cancel['cancellation_confirmed']), (['fi-01-r0'], False))
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, None, status='cancelled', pending=True,
                                         kind='reconciled')[0], 0)
        self.h.job_ok('cancel', {'caller': self.h.caller, 'reason': 'owner cancelled the study'})
        self.assertEqual(self.h.job_state()['status'], 'cancelled')
        view = self.h.lc_ok(*self.h.study('reconcile'), now=AFTER)
        self.assertEqual((view['cancellation_confirmed'], self.row(view, 'fi-01-r0')['state']),
                         (False, 'pending-descendants'))
        self.assertEqual(view['actions']['task_cancel'], [{'host_task_id': host, 'request_id': 'fi-01-r0'}])
        self.assertEqual(self.h.complete('fi-01', 'fi-01-r0', host, None, status='cancelled', kind='reconciled')[0], 0)
        view = self.h.lc_ok(*self.h.study('reconcile'), now=AFTER)
        self.assertEqual((view['cancellation_confirmed'], view['quiescent']), (True, True))
        # Only owned handles are ever named, and the artifacts stay.
        self.assertTrue((self.h.root / self.h.view['study_id'] / 'briefs').is_dir())

    def test_cancel_is_not_confirmed_when_a_closed_request_later_shows_pending_work(self):
        h = self.h
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        h.prepare('fi-01')
        host = h.launch('fi-01', 'fi-01-r0')
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, 'c1')[0], 0)
        view = h.reconcile()
        self.assertEqual((self.row(view, 'fi-01-r0')['ledger_state'], view['quiescent']), ('terminal', True))
        control = h.first(1)  # an unrelated owned cell, accepted and closed: never touched by cancellation
        self.assertEqual(control['code'], 0, control['out'])
        # A later recorded reconciliation of the closed request shows a pending descendant.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, None, pending=True, kind='reconciled')[0], 0)
        charged = h.charged()
        expected = [{'host_task_id': host, 'request_id': 'fi-01-r0'}]
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['cancel'], cancel['task_cancel']),
                         (False, ['fi-01-r0'], expected))
        ledger = h.ledger_bytes()
        self.assertEqual(h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id']), cancel)
        self.assertEqual(h.ledger_bytes(), ledger)
        status = h.status(h.view)
        self.assertEqual((status['cancel_pending_confirmation'], status['complete']), (['fi-01-r0'], False))
        view = h.reconcile()
        self.assertEqual((view['cancellation_confirmed'], view['unresolved'], view['actions']['task_cancel'],
                          view['actions']['task_status']), (False, ['fi-01-r0'], expected, []))
        self.assertEqual(h.reconcile(), view)
        self.assertEqual(h.ledger_bytes(), ledger)
        # The earlier closure, the charges and the control's accepted record are all kept.
        self.assertEqual(self.row(view, 'fi-01-r0')['ledger_state'], 'terminal')
        self.assertEqual(self.row(view, control['request'])['state'], 'terminal-confirmed')
        self.assertNotIn(control['host'], json.dumps([view['actions'], cancel]))
        self.assertEqual(h.charged(), charged)
        cells = {c['cell_id']: c for c in h.progress()['cells']}
        self.assertEqual(cells[h.cell(1)]['first-impression']['state'], 'accepted')
        wake = h.ok('wake', '--state-root', h.root, '--study', h.view['study_id'], now=AFTER)
        self.assertEqual((wake['cancel'], wake['task_cancel'], wake['cancellation_confirmed']),
                         (['fi-01-r0'], expected, False))
        # Only a fresh terminal reading with no pending runs confirms the cancellation.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, None, status='cancelled', kind='reconciled')[0], 0)
        view = h.reconcile(now=AFTER)
        self.assertEqual((view['cancellation_confirmed'], view['quiescent'], view['actions']['task_cancel']),
                         (True, True, []))
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['cancel'], cancel['task_cancel']), (True, [], []))
        self.assertEqual(h.charged(), charged)
        # FG3-R7: the wake reads the same confirmation as cancel and reconcile.
        wake = h.ok('wake', '--state-root', h.root, '--study', h.view['study_id'], now=AFTER)
        self.assertEqual((wake['cancellation_confirmed'], wake['cancel'], wake['task_cancel'], wake['new_tasks_permitted']),
                         (True, [], [], False))


# ----------------------------------------------------------------------------- REQ-RESUME and FG2-F1/F3


class ResumeTest(Case):
    """Resume reconciles first, then lists only unfilled valid slots; nothing is duplicated or reset."""

    def test_interrupts_before_and_after_dispatch_after_acceptance_and_during_review(self):
        h = self.h
        h.start()
        self.assertEqual(h.first(0)['code'], 0)                       # interrupted after acceptance
        self.assertEqual(h.first(1)['code'], 0)
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        h.prepare('fi-03')                                             # interrupted before dispatch
        self.assertEqual(h.admit_slot(3, 'first-impression', 'fi-04-r0')[0], 0)
        h.prepare('fi-04')
        host4 = h.launch('fi-04', 'fi-04-r0', n=3)                     # interrupted after dispatch
        self.assertEqual(h.admit(h.view, 'review-r0', 'review')[0], 0)  # interrupted during review
        charged = h.charged()
        resumed = h.resume()
        slots = {s['slot']: s for s in resumed['slots']}
        self.assertEqual([slots[f'{h.cell(n)}:first-impression']['state'] for n in range(4)],
                         ['accepted', 'accepted', 'in-flight', 'in-flight'])
        self.assertEqual(resumed['reconciliation']['actions']['dispatch_same_request'],
                         [{'task_id': 'fi-03', 'request_id': 'fi-03-r0'}])
        self.assertEqual(resumed['later_stages'][1]['state'], 'in-flight')
        self.assertIn('review-r0', resumed['unresolved_owned_work'])
        self.assertEqual((resumed['complete'], h.charged()), (False, charged))
        # Changed material stales downstream work: resume holds every slot until a new revision.
        image = h.pack / 'initial-viewport.png'
        original = image.read_bytes()
        image.write_bytes(original + b'drift')
        drifted = h.resume()
        self.assertEqual(drifted['blockers'][0]['code'], 'inputs_changed')
        self.assertTrue(all(s['state'] in ('accepted', 'held') for s in drifted['slots']))
        image.write_bytes(original)
        # Resume each interrupted slot without a new request or charge.
        host3 = h.launch('fi-03', 'fi-03-r0', n=2)
        for task, request, host, n in (('fi-03', 'fi-03-r0', host3, 2), ('fi-04', 'fi-04-r0', host4, 3)):
            brief = json.loads(Path(next(t for t in h.job_state()['tasks'] if t['task_id'] == task)['brief']['path'])
                               .read_text())
            item = h.payload_file(task, h.first_payload(h.view, h.cell(n), h.documents[task]['sha256']))
            path = h.transport(h.worker_result(brief, [item]))
            self.assertEqual(h.complete(task, request, host, f'done-{request}')[0], 0)
            self.assertEqual(h.deliver(task, request, f'done-{request}', path)[0], 0)
            self.assertEqual(h.ingest(task, request, f'done-{request}', path)[0], 0)
        final = h.resume()
        self.assertEqual({s['state'] for s in final['slots'] if s['slot'].endswith('first-impression')}, {'accepted'})
        accepted = list((h.root / h.view['study_id'] / 'focus-group' / 'accepted').glob('*.json'))
        self.assertEqual(len(accepted), 4)
        self.assertEqual(h.charged(), charged)
        self.assertIn('review-r0', final['unresolved_owned_work'])
        self.assertFalse(final['complete'])

    def test_journey_brief_before_admission_and_recorded_slot_addition(self):
        h = self.h
        h.start()
        # FG2-F1: a journey whose cell has no frozen first impression cannot be briefed, so it is never charged.
        self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'journey_brief_missing')
        self.assertEqual(h.charged(), {})
        self.assertEqual(h.first(0)['code'], 0)
        before = h.job_state()
        fi_tasks = {t['task_id']: t for t in before['tasks'] if t['stage_id'] == 'first-impression'}
        # FG2-F3: the journey slot is added through the shared plan-revision route, bound to the owner's
        # approval of this exact revision; existing slots, results and counters are untouched.
        document = h.journey_ready(0)
        after = h.job_state()
        added = next(t for t in after['tasks'] if t['task_id'] == 'jr-01')
        self.assertEqual((added['document'], added['request_id'], added['stage_id']), (document, 'jr-01-r0', 'journey'))
        # The shared plan revision may only add a slot pass counter's default (cycle 0); nothing else changes.
        kept = {t['task_id']: t for t in after['tasks'] if t['stage_id'] == 'first-impression'}
        self.assertEqual({k: {f: v for f, v in t.items() if f != 'cycle'} for k, t in kept.items()},
                         {k: {f: v for f, v in t.items() if f != 'cycle'} for k, t in fi_tasks.items()})
        self.assertEqual({k: t.get('cycle', 0) for k, t in kept.items()}, {k: t.get('cycle', 0) for k, t in fi_tasks.items()})
        self.assertEqual(after['plan_revisions'][-1]['expanded'], True)
        self.assertEqual(after['decisions'][-1]['quote'], h.view['approval_instruction'])
        self.assertEqual(h.charged(), {'first': 1})
        again = h.lc_ok(*h.study('journey-slots'), '--documents', h.write('again.json', {'jr-01': document}))
        self.assertEqual(again['added'], [])
        code, out = h.admit_slot(0, 'journey', 'jr-01-r0')
        self.assertEqual((code, out['data']['charged']), (0, True))
        code, out = h.admit_slot(0, 'journey', 'jr-01-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False))
        brief = h.prepare('jr-01')
        self.assertEqual(brief['document'], document)
        # The journey stage stays unaccepted: no study validator yet, and coverage never claims combined scope.
        self.assertNotEqual(next(s for s in h.job_state()['stages'] if s['id'] == 'journey')['status'],
                            'accepted-at-snapshot')

    def test_full_combined_cell_through_the_job_and_cancel_keeps_artifacts(self):
        h = self.h
        h.start()
        self.assertEqual(h.first(0)['code'], 0)
        code, out = h.journey(0)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['identity'], 'verified')
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        row = next(r for r in coverage['cells'] if r['cell_id'] == h.cell(0))
        self.assertEqual((row['first_impression'], row['journey']['state']), ('frozen', 'hands-on-evidence'))
        self.assertEqual(row['journey']['evidence_class'], 'fixture')
        self.assertFalse(row['journey']['live_isolation_claim'])
        self.assertEqual(h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)
        h.prepare('fi-02')
        host = h.launch('fi-02', 'fi-02-r0', n=1)
        files = {p for p in (h.root / h.view['study_id']).rglob('*') if p.is_file() and 'artifacts' in p.parts}
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual(cancel['cancel'], ['fi-02-r0'])
        view = h.reconcile()
        self.assertEqual((view['actions']['task_cancel'], view['quiescent']),
                         ([{'host_task_id': host, 'request_id': 'fi-02-r0'}], False))
        self.assertEqual(h.progress()['complete'], False)
        self.assertTrue(files <= {p for p in (h.root / h.view['study_id']).rglob('*') if p.is_file()})


# ----------------------------------------------------------------------------- FG3 review round 0 (R1-R7, N1)


class ReviewRoundTest(Case):
    """Each scenario of the round-0 review, through the installed job helper and the source study helpers."""

    def task(self, task_id):
        return next(t for t in self.h.job_state()['tasks'] if t['task_id'] == task_id)

    def accepted_bytes(self):
        folder = self.h.root / self.h.view['study_id'] / 'focus-group' / 'accepted'
        return {p.name: p.read_bytes() for p in folder.glob('*.json')}

    def decide(self, record_sha, statement):
        """The owner's sole answer `statement`, saved outside the job, offered to accept-identity."""
        h = self.h
        h.counter += 1
        source = h.base / 'owner' / f'identity-{h.counter}.txt'
        source.parent.mkdir(exist_ok=True)
        source.write_text(f'Selected option: {statement}\n')
        return h.lc(*h.study('accept-identity'), '--input', h.write(f'id-{h.counter}.json', {
            'record_sha256': record_sha, 'message_ref': 'picker-identity', 'statement': statement,
            'source': str(source), 'source_sha256': sha(source.read_bytes())}))

    def disclosures(self):
        """Every consumer's disclosure gate: consumer -> (exit code, output)."""
        h = self.h
        return {c: h.call_evidence('disclosure', '--state-root', h.root, '--study', h.view['study_id'], '--consumer', c)
                for c in ('participant', 'analysis', 'review', 'export')}

    def cells(self):
        return {c['cell_id']: c for c in self.h.progress()['cells']}

    def test_r1_a_closed_request_whose_host_work_reopens_still_occupies_concurrency(self):
        h = self.h
        h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=1))
        run = h.first(0)
        self.assertEqual(run['code'], 0, run['out'])
        view = h.reconcile()
        self.assertEqual((next(r for r in view['requests'] if r['request_id'] == 'fi-01-r0')['ledger_state'],
                          view['quiescent']), ('terminal', True))
        # A later recorded reading of the closed request's own host task shows a pending descendant.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', run['host'], None, pending=True, kind='reconciled')[0], 0)
        charged, records = h.charged(), self.accepted_bytes()
        out = self.refused(h.admit_slot(1, 'first-impression', 'fi-02-r0'), 'concurrency_limit')
        self.assertEqual(out['data']['occupied'], ['fi-01-r0'])
        self.assertEqual(h.charged(), charged)
        slots = {s['slot']: s for s in h.resume()['slots']}
        held = slots[f'{h.cell(1)}:first-impression']
        self.assertEqual((held['state'], held['code']), ('held', 'concurrency_limit'))
        self.assertEqual(h.reconcile()['unresolved'], ['fi-01-r0'])
        # The earlier closure, its charge and the accepted record stay; only the host's own terminal reading
        # without pending runs frees the slot, and only an admitted request is then prepared.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', run['host'], None, kind='reconciled')[0], 0)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['charged']), (0, True), out)
        self.assertEqual(h.prepare('fi-02')['request_id'], 'fi-02-r0')
        self.assertEqual((h.charged(), self.accepted_bytes()), ({'first': 2}, records))

    def test_r2_a_retained_conflicting_host_task_keeps_cancellation_pending_until_its_own_terminal_reading(self):
        h = self.h
        h.start()
        run, control = h.first(0), h.first(1)
        self.assertEqual((run['code'], control['code']), (0, 0))
        # The host returns a second task for the same request: the shared job refuses it as a handle and retains
        # it as a conflict. A refused observation does not prove the returned task never ran.
        code, _ = h.observe('fi-01', kind='accepted', request_id='fi-01-r0', host_task_id='host-dup',
                            child_thread_id='thread-dup', status='running', work_state='working',
                            has_pending_child_runs=False)
        self.assertEqual(code, 2)
        self.assertEqual([c['host_task_id'] for c in self.task('fi-01')['host_conflicts']], ['host-dup'])
        view = h.reconcile()
        row = next(r for r in view['requests'] if r['request_id'] == 'fi-01-r0')
        self.assertEqual((row['state'], row['ledger_state'], view['quiescent'], view['unresolved']),
                         ('conflicting-host', 'terminal', False, ['fi-01-r0']))
        self.assertEqual(view['actions']['task_status'], [{'host_task_id': 'host-dup', 'request_id': 'fi-01-r0'}])
        charged, records = h.charged(), self.accepted_bytes()
        expected = [{'host_task_id': 'host-dup', 'request_id': 'fi-01-r0'}]
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['cancel'], cancel['task_cancel']),
                         (False, ['fi-01-r0'], expected))
        # The unrelated accepted control and the original, settled handle are never named.
        self.assertNotIn(control['host'], json.dumps(cancel))
        self.assertNotIn(run['host'], json.dumps(cancel['task_cancel']))
        wake = h.ok('wake', '--state-root', h.root, '--study', h.view['study_id'], now=BEFORE)
        self.assertEqual((wake['cancellation_confirmed'], wake['task_cancel']), (False, expected))
        # A non-terminal reading of the conflicting task is refused by the shared job and confirms nothing.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', 'host-dup', None, status='running', work_state='working',
                                    kind='reconciled')[0], 2)
        self.assertEqual(h.reconcile()['actions']['task_cancel'], expected)
        # Its own terminal reconciliation without pending runs, recorded by the shared job, confirms it.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', 'host-dup', None, status='cancelled', kind='reconciled')[0], 0)
        view = h.reconcile()
        self.assertEqual((view['cancellation_confirmed'], view['quiescent'], view['actions']['task_cancel']),
                         (True, True, []))
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['task_cancel']), (True, []))
        self.assertEqual((h.charged(), self.accepted_bytes()), (charged, records))

    def two_hosts_for_one_request(self):
        """FG3-C2: at max_concurrency 2, one request owns two unresolved host tasks, its handle and a conflict."""
        h = self.h
        h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=2))
        # Both models' pilots are accepted first, so only concurrency can hold the later cells.
        self.assertEqual((h.first(0)['code'], h.first(1)['code']), (0, 0))
        h.journey_ready(0)
        h.journey_ready(1)
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        h.prepare('fi-03')
        primary = h.launch('fi-03', 'fi-03-r0', n=2)
        conflict = dict(kind='accepted', request_id='fi-03-r0', host_task_id='host-dup', child_thread_id='thread-dup',
                        status='running', work_state='working', has_pending_child_runs=False)
        self.assertEqual(h.observe('fi-03', **conflict)[0], 2)
        # Repeated notifications of either host task are the same physical work and never inflate the count.
        self.assertEqual(h.observe('fi-03', **conflict)[0], 2)
        h.observe('fi-03', **dict(conflict, host_task_id=primary, child_thread_id=f'thread-{primary}'))
        view = h.reconcile()
        self.assertEqual(view['actions']['task_status'], [{'host_task_id': primary, 'request_id': 'fi-03-r0'},
                                                          {'host_task_id': 'host-dup', 'request_id': 'fi-03-r0'}])
        charged = h.charged()
        out = self.refused(h.admit_slot(3, 'first-impression', 'fi-04-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['occupied'], out['data']['occupied_count']), (['fi-03-r0'], 2))
        self.assertEqual(sorted(w['host_task_id'] for w in out['data']['occupied_work']), sorted([primary, 'host-dup']))
        self.assertEqual(h.charged(), charged)
        held = {s['slot']: s for s in h.resume()['slots']}[f'{h.cell(3)}:first-impression']
        self.assertEqual((held['state'], held['code']), ('held', 'concurrency_limit'))
        return primary

    def settle_one_then_both(self, first, second):
        h = self.h
        # Settling either owned host task through its own terminal reading frees exactly one slot.
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', first, None, status='cancelled', kind='reconciled')[0], 0)
        slots = {s['slot']: s for s in h.resume()['slots']}
        self.assertEqual(slots[f'{h.cell(3)}:first-impression']['state'], 'dispatchable')
        code, out = h.admit_slot(3, 'first-impression', 'fi-04-r0')
        self.assertEqual((code, out['data']['charged']), (0, True), out)
        self.assertEqual(h.prepare('fi-04')['request_id'], 'fi-04-r0')
        other = h.launch('fi-04', 'fi-04-r0', n=3)
        out = self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['occupied'], out['data']['occupied_count']), (['fi-03-r0', 'fi-04-r0'], 2))
        self.assertEqual(sorted(w['host_task_id'] for w in out['data']['occupied_work']), sorted([second, other]))
        # Settling the request's other host task frees its last slot; the request then occupies nothing.
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', second, None, status='cancelled', kind='reconciled')[0], 0)
        self.assertNotIn('fi-03-r0', h.reconcile()['unresolved'])
        self.assertEqual(h.admit_slot(0, 'journey', 'jr-01-r0')[0], 0)
        # An admitted request with no host task yet keeps its reservation.
        out = self.refused(h.admit_slot(1, 'journey', 'jr-02-r0'), 'concurrency_limit')
        self.assertEqual(out['data']['occupied'], ['fi-04-r0', 'jr-01-r0'])
        self.assertEqual(h.charged(), {'first': 5})

    def test_c2_a_conflicting_host_task_occupies_its_own_slot_until_its_terminal_reading(self):
        primary = self.two_hosts_for_one_request()
        self.settle_one_then_both('host-dup', primary)

    def test_c2_a_settled_handle_frees_its_slot_while_the_conflict_still_occupies_one(self):
        primary = self.two_hosts_for_one_request()
        self.settle_one_then_both(primary, 'host-dup')

    def test_r3_a_later_host_source_naming_another_model_withdraws_verified_use(self):
        h = self.h
        h.start()
        run = h.first(0)
        self.assertEqual(run['out']['data']['identity'], 'verified')
        records = self.accepted_bytes()
        # An authoritative reading of the same host task later names another model of that provider.
        code, _ = h.observe('fi-01', kind='reconciled', request_id='fi-01-r0', host_task_id=run['host'],
                            status='completed', work_state='result_available', has_pending_child_runs=False,
                            status_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        self.assertEqual(code, 0)
        self.assertEqual(self.task('fi-01')['handles'][0]['observed_identity']['status'], 'mismatched')
        row = {c['cell_id']: c for c in h.progress()['cells']}[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['verified_coverage'], row['accepted_identity'], row['observed']['model']),
                         ('mismatched', False, 'verified', 'alpha-deep'))
        pilots = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual((pilots[(h.cell(0), 'first-impression')]['state'],
                          pilots[(h.cell(0), 'first-impression')]['reasons']), ('failed', ['identity mismatched']))
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((coverage['cells'][0]['first_identity'], coverage['verified_identity']['first_impressions']),
                         ('mismatched', 0))
        charged = h.charged()
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(h.charged(), charged)
        # The accepted record is history and never rewritten.
        self.assertEqual(self.accepted_bytes(), records)
        # Only the owner's exact decision on the discrepancy shown now permits disclosed use, never `verified`.
        # The launch reading named the requested model and the later one another (FG3-R8): an instruction naming
        # only the later model hides that contradiction and is refused; the accepted one names every model.
        hidden = (f'Accept observed model fixture-a/alpha-deep for focus-group cell {h.cell(0)} '
                  'first-impression request fi-01-r0 (requested fixture-a/alpha-swift)')
        instruction = (f'Accept contradictory host identity for focus-group cell {h.cell(0)} first-impression request '
                       'fi-01-r0 (requested fixture-a/alpha-swift; readings fixture-a/alpha-deep, fixture-a/alpha-swift; '
                       'resolved fixture-a/alpha-deep, fixture-a/alpha-swift; now fixture-a/alpha-deep)')
        self.assertEqual(row['identity_evidence']['instruction'], instruction)
        out = self.refused(self.decide(run['out']['data']['record_sha256'], hidden), 'approval_scope_mismatch')
        self.assertEqual(out['data']['expected'], instruction)
        code, out = self.decide(run['out']['data']['record_sha256'], instruction)
        self.assertEqual(code, 0, out)
        decided = out['data']
        self.assertEqual((decided['identity'], decided['verified'], decided['decision']['recorded_identity'],
                          decided['decision']['current_identity']),
                         ('owner-accepted-discrepancy', False, 'verified', 'mismatched'))
        row = {c['cell_id']: c for c in h.progress()['cells']}[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['verified_coverage']), ('owner-accepted-discrepancy', False))
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        # It never carries into another revision.
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        entry = next(e for e in h.plan(draft)['carry_forward']['entries']
                     if e['record_sha256'] == run['out']['data']['record_sha256'])
        self.assertEqual(entry['status'], 'stale')
        self.assertIn('observed model identity is not verified against the request', entry['reasons'])

    def record(self, record_sha):
        return next(r for r in map(json.loads, self.accepted_bytes().values()) if r['record_sha256'] == record_sha)

    def withdraw(self, task, request, host, **source):
        """An authoritative terminal reading of the request's own host task naming another identity."""
        code, out = self.h.observe(task, kind='reconciled', request_id=request, host_task_id=host, status='completed',
                                   work_state='result_available', has_pending_child_runs=False, **source)
        self.assertEqual(code, 0, out)

    def test_r3_withdrawn_identity_stops_every_consumer_of_the_record_and_its_journey_until_the_owner_decides(self):
        h = self.h
        h.start()
        first, other = h.first(0), h.first(1)
        journey = h.journey(0)
        self.assertEqual((first['code'], other['code'], journey[0], journey[1]['data']['identity']),
                         (0, 0, 0, 'verified'), journey[1])
        fi, jr = first['out']['data']['record_sha256'], journey[1]['data']['record_sha256']
        self.assertEqual({c: out[0] for c, out in self.disclosures().items()}, dict.fromkeys(
            ('participant', 'analysis', 'review', 'export'), 0))
        records, charged = self.accepted_bytes(), h.charged()
        self.withdraw('fi-01', 'fi-01-r0', first['host'],
                      status_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        # Every consumer refuses the first impression and the journey built on it; the raw records stay.
        for consumer, (code, out) in self.disclosures().items():
            with self.subTest(consumer=consumer):
                self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'), out)
                self.assertEqual({(p['record_sha256'], p['code']) for p in out['data']['material']},
                                 {(fi, 'identity_unverified'), (jr, 'predecessor_unusable')})
        for command, record_sha in (('freeze-first', fi), ('accept-journey', jr)):
            code, out = h.call_evidence(command, '--state-root', h.root, '--study', h.view['study_id'], '--input',
                                        h.write(f'{command}.json', {'record_sha256': record_sha,
                                                                    'payload': self.record(record_sha)['result']}))
            self.assertEqual((code, out['error']['code']), (1, 'material_unusable'), out)
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        row = coverage['cells'][0]
        self.assertEqual((row['first_impression'], row['first_identity'], row['journey']['state'], row['journey_identity']),
                         ('identity-unverified', 'mismatched', 'predecessor-unusable', 'verified'))
        self.assertEqual((coverage['verified_identity'], coverage['journey_gaps']),
                         ({'first_impressions': 1, 'journeys': 0}, 1))
        pilots = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual(pilots[(h.cell(0), 'first-impression')]['reasons'], ['identity mismatched'])
        self.assertEqual((pilots[(h.cell(0), 'journey')]['state'], pilots[(h.cell(0), 'journey')]['reasons']),
                         ('failed', ['predecessor_unusable']))
        row = self.cells()[h.cell(0)]
        self.assertEqual((row['first-impression']['state'], row['first-impression']['problems'],
                          row['journey']['state'], row['journey']['problems'], row['journey']['identity']),
                         ('unusable', ['identity_unverified'], 'unusable', ['predecessor_unusable'], 'verified'))
        slots = {s['slot']: s['state'] for s in h.resume()['slots']}
        self.assertEqual((slots[f'{h.cell(0)}:first-impression'], slots[f'{h.cell(0)}:journey']),
                         ('accepted-unusable', 'accepted-unusable'))
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        # The other model's records are unaffected: its pilot journey is briefed, admitted and accepted.
        control = h.journey(1)
        self.assertEqual((control[0], control[1]['data']['identity']), (0, 'verified'), control[1])
        pilots = {(p['pilot_cell'], p['stage']): p['state'] for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual((pilots[(h.cell(1), 'first-impression')], pilots[(h.cell(1), 'journey')]), ('passed', 'passed'))
        after = self.accepted_bytes()
        self.assertEqual(({k: after[k] for k in records}, len(after)), (records, len(records) + 1))
        self.assertEqual(h.charged(), {'first': charged['first'] + 1})
        # The owner sees every reading and accepts exactly this discrepancy: use is permitted, visibly, never
        # as verified identity, and nothing is carried.
        found = self.cells()[h.cell(0)]['first-impression']['identity_evidence']
        self.assertEqual((found['kind'], [(r['source'], r['model']) for r in found['readings']]),
                         ('contradictory', [('status', 'alpha-swift'), ('status', 'alpha-deep')]))
        code, out = self.decide(fi, found['instruction'])
        self.assertEqual((code, out['data']['decision']['discrepancy_sha256']), (0, found['discrepancy_sha256']), out)
        for consumer, (code, out) in self.disclosures().items():
            with self.subTest(consumer=consumer, decided=True):
                self.assertEqual(code, 0, out)
                ids = {r['record_sha256']: r for r in out['data']['identities']}
                self.assertEqual((ids[fi]['identity'], ids[fi]['verified'], ids[fi]['discrepancy_sha256'],
                                  [r['model'] for r in ids[fi]['readings']]),
                                 ('owner-accepted-discrepancy', False, found['discrepancy_sha256'],
                                  ['alpha-swift', 'alpha-deep']))
                self.assertEqual((ids[jr]['identity'], ids[jr]['verified']), ('verified', True))
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((coverage['cells'][0]['first_identity'], coverage['cells'][0]['journey']['state']),
                         ('owner-accepted-discrepancy', 'hands-on-evidence'))
        self.assertEqual(coverage['verified_identity'], {'first_impressions': 1, 'journeys': 2})
        self.assertEqual(self.accepted_bytes(), after)
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        entries = {e['record_sha256']: e['status'] for e in h.plan(draft)['carry_forward']['entries']}
        self.assertEqual((entries[fi], entries[jr]), ('stale', 'stale'))

    def test_r3_a_journey_is_never_briefed_admitted_or_ingested_on_its_own_unusable_first(self):
        h = self.h
        h.start()
        first, other = h.first(0), h.first(1)
        # Model A's pilot journey is briefed and declared while its first impression is still verified.
        h.journey_ready(0)
        # Model B's pilot journey is admitted, prepared and launched on a then-verified first impression.
        document = h.journey_ready(1)
        self.assertEqual(h.admit_slot(1, 'journey', 'jr-02-r0')[0], 0)
        brief = h.prepare('jr-02')
        host = h.launch('jr-02', 'jr-02-r0', n=1)
        # A receipt reading of each first impression's own host task names another model of its provider.
        for task, run, provider_id, model in (('fi-01', first, 'fixture-a', 'alpha-deep'),
                                              ('fi-02', other, 'fixture-b', 'beta-two')):
            code, out = h.observe(task, kind='identity', request_id=f'{task}-r0', host_task_id=run['host'],
                                  receipt_identity={'providerInstanceId': provider_id, 'model': model})
            self.assertEqual(code, 0, out)
        charged, records = h.charged(), self.accepted_bytes()
        # Being its model's pilot is no proof of its predecessor: no new brief, and the earlier one admits nothing.
        code, out = h.call_evidence('brief', '--state-root', h.root, '--study', h.view['study_id'], '--input',
                                    h.write('rebrief.json', {'revision': h.view['revision'], 'cell_id': h.cell(0),
                                                             'stage': 'journey', 'task_id': 'jr-01'}))
        self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'), out)
        self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'predecessor_unusable')
        held = {s['slot']: s for s in h.resume()['slots']}[f'{h.cell(0)}:journey']
        self.assertEqual((held['state'], held['code']), ('held', 'predecessor_unusable'))
        # The journey already running finishes; its complete result is retained and refused, not product friction.
        context = h.bound_context(h.view, h.cell(1))
        item = h.payload_file('jr-02', h.journey_payload(h.view, h.cell(1), document['sha256'], context))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('jr-02', 'jr-02-r0', host, 'done-jr-02')[0], 0)
        self.assertEqual(h.deliver('jr-02', 'jr-02-r0', 'done-jr-02', path)[0], 0)
        ingest = dict(context={'class': 'fresh-anonymous', **context})
        code, out = h.ingest('jr-02', 'jr-02-r0', 'done-jr-02', path, **ingest)
        self.assertEqual((code, out['error']['code'], out['data']['category'], out['data']['product_friction']),
                         (1, 'predecessor_unusable', 'evidence', False), out)
        raw = h.root / h.view['study_id'] / 'focus-group' / out['data']['raw_retained']
        self.assertEqual(raw.read_bytes(), path.read_bytes())
        self.assertEqual((self.accepted_bytes(), h.charged()), (records, charged))
        # The owner accepts model B's contradiction as shown; the same retained completion is then accepted on it.
        # Model A's first impression is untouched by that decision and still admits nothing.
        found = self.cells()[h.cell(1)]['first-impression']['identity_evidence']
        self.assertEqual((found['kind'], found['reported_models']), ('contradictory', ['beta-one', 'beta-two']))
        self.assertEqual(self.decide(other['out']['data']['record_sha256'], found['instruction'])[0], 0)
        code, out = h.ingest('jr-02', 'jr-02-r0', 'done-jr-02', path, **ingest)
        self.assertEqual((code, out['data']['identity'], out['data']['predecessor_records'][0]['record_sha256']),
                         (0, 'verified', other['out']['data']['record_sha256']), out)
        self.assertEqual([r['outcome'] for r in h.session('jr-02-r0')], ['refused', 'accepted'])
        self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'predecessor_unusable')
        self.assertEqual(h.charged(), charged)

    def test_r3_identity_follows_the_exact_original_request_through_a_retry_and_a_new_revision(self):
        h = self.h
        h.start()
        old = h.first(0)
        self.assertEqual((old['code'], h.first(1)['code']), (0, 0))
        old_sha = old['out']['data']['record_sha256']
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['prompts']['first_impression'] += ' Note one thing that works.'
        revised = h.plan(draft)
        h.approve(revised)
        h.ok('carry', '--state-root', h.root, '--study', revised['study_id'], '--write')
        h.view = revised
        _, documents = h.revise_job()
        h.documents.update(documents)
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'fi-01', 'reason': 'protocol revision'})
        request = self.task('fi-01')['request_id']
        new = h.first(0, request=request)
        self.assertEqual((new['code'], new['out']['data']['identity']), (0, 'verified'), new['out'])
        new_sha = new['out']['data']['record_sha256']
        records = self.accepted_bytes()
        # A reading of the retired request's own host task withdraws only that execution's record.
        self.withdraw('fi-01', 'fi-01-r0', old['host'],
                      status_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        out = self.refused(self.decide(old_sha, 'Accept nothing'), 'approval_scope_mismatch')
        evidence = out['data']['evidence']
        self.assertEqual((evidence['request_id'], evidence['host_task_id'], evidence['reported_models']),
                         ('fi-01-r0', old['host'], ['alpha-deep', 'alpha-swift']))
        self.refused(self.decide(new_sha, 'Accept nothing'), 'identity_verified')
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['state'], row['observed']['model']), ('verified', 'accepted', 'alpha-swift'))
        # The old record is excluded history of this revision: private, never disclosed, never blocking.
        code, out = self.disclosures()['analysis']
        self.assertEqual((code, out['data']['selected_records'], out['data']['excluded_history_records']),
                         (0, [new_sha], 2), out)
        # A reading of the current request withdraws the current record and names only it; nothing is replaced.
        self.withdraw('fi-01', request, new['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        code, out = self.disclosures()['analysis']
        self.assertEqual((code, [(p['record_sha256'], p['code']) for p in out['data']['material']]),
                         (1, [(new_sha, 'identity_unverified')]), out)
        self.assertEqual(self.accepted_bytes(), records)
        self.assertIn('fi-01-r0', self.task('fi-01')['retired_request_ids'])

    def test_r8_contradictory_host_sources_are_shown_whole_and_bind_the_owner_decision(self):
        h = self.h
        h.start()
        run, other = h.first(0), h.first(1)
        fi, fb = run['out']['data']['record_sha256'], other['out']['data']['record_sha256']
        records = self.accepted_bytes()
        # The status source keeps the requested model; a receipt names another (the original R8 case).
        self.withdraw('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((row['identity'], row['observed']['model'], found['shared_status'], found['kind'],
                          found['observed'], found['hold']), ('mismatched', 'alpha-swift', 'mismatched', 'contradictory',
                                                              None, None))
        self.assertEqual(found['current_sources'], {'status': {'providerInstanceId': 'fixture-a', 'model': 'alpha-swift'},
                                                    'receipt': {'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'}})
        self.assertEqual([(r['source'], r['model']) for r in found['readings']],
                         [('status', 'alpha-swift'), ('receipt', 'alpha-deep')])
        # An instruction naming the request as observed, or only one of the reported models, is refused.
        for model in ('alpha-swift', 'alpha-deep'):
            out = self.refused(self.decide(fi, f'Accept observed model fixture-a/{model} for focus-group cell '
                                               f'{h.cell(0)} first-impression request fi-01-r0 '
                                               '(requested fixture-a/alpha-swift)'),
                               'approval_scope_mismatch')
            self.assertEqual((out['data']['expected'], out['data']['evidence']['discrepancy_sha256']),
                             (found['instruction'], found['discrepancy_sha256']))
        self.assertIn('readings fixture-a/alpha-deep, fixture-a/alpha-swift; resolved fixture-a/alpha-swift; '
                      'now fixture-a/alpha-swift)', found['instruction'])
        decisions = h.root / h.view['study_id'] / 'focus-group' / 'identity'
        self.assertFalse(decisions.exists() and any(decisions.iterdir()))
        charged = h.charged()
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(h.charged(), charged)
        code, out = self.decide(fi, found['instruction'])
        self.assertEqual(code, 0, out)
        decision = out['data']['decision']
        self.assertEqual((decision['observed'], decision['discrepancy_sha256'], decision['discrepancy']['readings']),
                         (None, found['discrepancy_sha256'], found['readings']))
        stored = {p.name: p.read_bytes() for p in decisions.iterdir()}
        self.assertEqual(list(stored), [f"{fi}.{found['discrepancy_sha256'][:16]}.json"])
        # A repeated equivalent reading keeps the evidence, so the decision still applies; nothing is asked again.
        self.withdraw('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['identity_evidence']['discrepancy_sha256'], row['verified_coverage']),
                         ('owner-accepted-discrepancy', found['discrepancy_sha256'], False))
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        # A configuration source naming a third model is evidence that decision never covered.
        code, out = h.observe('fi-01', kind='identity', request_id='fi-01-r0', host_task_id=run['host'],
                              configuration_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-max'})
        self.assertEqual(code, 0, out)
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['problems'], row['identity_evidence']['reported_models']),
                         ('mismatched', ['identity_unverified'], ['alpha-deep', 'alpha-max', 'alpha-swift']))
        self.assertNotEqual(row['identity_evidence']['discrepancy_sha256'], found['discrepancy_sha256'])
        self.refused(self.decide(fi, found['instruction']), 'approval_scope_mismatch')
        self.assertEqual(self.disclosures()['analysis'][1]['error']['code'], 'disclosure_blocked')
        self.assertEqual({p.name: p.read_bytes() for p in decisions.iterdir()}, stored)
        # Model B: the status source names another model and then the requested one again. The shared handle
        # keeps one row per source, now equal to the request; the earlier reading stays in the evidence.
        for model in ('beta-two', 'beta-one'):
            self.withdraw('fi-02', 'fi-02-r0', other['host'],
                          status_identity={'providerInstanceId': 'fixture-b', 'model': model})
        row = self.cells()[h.cell(1)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((found['current_sources'], row['observed']['model'], row['identity'], found['reported_models']),
                         ({'status': {'providerInstanceId': 'fixture-b', 'model': 'beta-one'}}, 'beta-one', 'mismatched',
                          ['beta-one', 'beta-two']))
        self.refused(self.decide(fb, f'Accept observed model fixture-b/beta-one for focus-group cell {h.cell(1)} '
                                     'first-impression request fi-02-r0 (requested fixture-b/beta-one)'),
                     'approval_scope_mismatch')
        self.assertEqual(self.accepted_bytes(), records)

    def identify(self, task, request, host, **sources):
        code, out = self.h.observe(task, kind='identity', request_id=request, host_task_id=host, **sources)
        self.assertEqual(code, 0, out)

    def blocked_everywhere(self, record_sha):
        """Every disclosure consumer refuses the record, the pilot fails, and the model's next cell is refused
        without a charge."""
        h = self.h
        for consumer, (code, out) in self.disclosures().items():
            with self.subTest(consumer=consumer):
                self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'), out)
                self.assertIn((record_sha, 'identity_unverified'),
                              {(p['record_sha256'], p['code']) for p in out['data']['material']})
        pilot = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}[
            (h.cell(0), 'first-impression')]
        self.assertEqual(pilot['state'], 'failed')
        charged = h.charged()
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(h.charged(), charged)

    def test_r8_a_new_association_or_status_provider_withdraws_the_decision_and_its_quote(self):
        h = self.h
        h.start()
        run, other = h.first(0), h.first(1)
        fi = run['out']['data']['record_sha256']
        records = self.accepted_bytes()
        decisions = h.root / h.view['study_id'] / 'focus-group' / 'identity'
        # The reviewer's sequence: verified on fixture-a/alpha-swift, then a receipt naming fixture-b/alpha-deep.
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-deep'})
        before = self.cells()[h.cell(0)]['first-impression']['identity_evidence']
        self.assertEqual((before['kind'], before['canonical'], before['resolutions']),
                         ('contradictory', {'providerInstanceId': 'fixture-a', 'model': 'alpha-swift'},
                          [{'providerInstanceId': 'fixture-a', 'model': 'alpha-swift'}]))
        old_quote = before['instruction']
        self.assertIn('readings fixture-a/alpha-swift, fixture-b/alpha-deep; resolved fixture-a/alpha-swift; '
                      'now fixture-a/alpha-swift)', old_quote)
        self.assertEqual(self.decide(fi, old_quote)[0], 0)
        self.assertEqual(self.cells()[h.cell(0)]['first-impression']['identity'], 'owner-accepted-discrepancy')
        self.assertEqual(self.disclosures()['analysis'][0], 0)
        stored = {p.name: p.read_bytes() for p in decisions.iterdir()}
        # The same provider set and model set, paired the other way, and the status provider is now fixture-b.
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((before['reported_providers'], before['reported_models']),
                         (found['reported_providers'], found['reported_models']))
        self.assertNotEqual(found['discrepancy_sha256'], before['discrepancy_sha256'])
        self.assertEqual((row['identity'], row['problems'], found['observed'], found['canonical']),
                         ('mismatched', ['identity_unverified'], None,
                          {'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'}))
        self.assertEqual([(p['providerInstanceId'], p['model']) for p in found['associations']],
                         [('fixture-a', 'alpha-deep'), ('fixture-a', 'alpha-swift'), ('fixture-b', 'alpha-deep'),
                          ('fixture-b', 'alpha-swift')])
        self.assertEqual([(r['source'], r['providerInstanceId'], r['model']) for r in found['readings']],
                         [('status', 'fixture-a', 'alpha-swift'), ('receipt', 'fixture-b', 'alpha-deep'),
                          ('receipt', 'fixture-a', 'alpha-deep'), ('status', 'fixture-b', 'alpha-swift')])
        self.blocked_everywhere(fi)
        # The old owner quote no longer matches the evidence, so it cannot authorise it again.
        out = self.refused(self.decide(fi, old_quote), 'approval_scope_mismatch')
        self.assertEqual(out['data']['expected'], found['instruction'])
        self.assertIn('resolved fixture-a/alpha-swift, fixture-b/alpha-swift; now fixture-b/alpha-swift)',
                      found['instruction'])
        self.assertEqual({p.name: p.read_bytes() for p in decisions.iterdir()}, stored)
        # An equivalent repeat changes nothing and asks nothing.
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        self.assertEqual(self.cells()[h.cell(0)]['first-impression']['identity_evidence']['discrepancy_sha256'],
                         found['discrepancy_sha256'])
        # Only a fresh decision on exactly this evidence permits disclosed use again, never as verified.
        code, out = self.decide(fi, found['instruction'])
        self.assertEqual((code, out['data']['verified'], out['data']['decision']['observed'],
                          out['data']['decision']['discrepancy']['canonical']),
                         (0, False, None, found['canonical']), out)
        self.assertEqual(self.disclosures()['analysis'][0], 0)
        charged = h.charged()
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        self.assertEqual(h.charged(), {'first': charged['first'] + 1})
        # An unrelated slot change (model B's journey slot) keeps the decision; nothing is asked again.
        h.journey_ready(1)
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['identity_evidence']['discrepancy_sha256']),
                         ('owner-accepted-discrepancy', found['discrepancy_sha256']))
        self.assertEqual(self.accepted_bytes(), records)
        self.assertEqual(other['out']['data']['identity'], 'verified')

    def test_r9_incomplete_sources_never_make_an_observed_pair(self):
        h = self.h
        h.start()
        # The reviewer's case: a status model with no provider, then a receipt provider with no model.
        run = h.first(0, identity={'model': 'alpha-deep'})
        other = h.first(1, identity={'providerInstanceId': 'fixture-b'})
        self.assertEqual((run['code'], other['code']), (0, 0), (run['out'], other['out']))
        fi, fb = run['out']['data']['record_sha256'], other['out']['data']['record_sha256']
        records = self.accepted_bytes()
        self.identify('fi-01', 'fi-01-r0', run['host'], receipt_identity={'providerInstanceId': 'fixture-b'})
        row = self.cells()[h.cell(0)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((found['observed'], found['kind'], found['hold_code'], found['missing'], found['canonical'],
                          found['instruction']),
                         (None, None, 'identity_unreported', ['providerInstanceId'],
                          {'providerInstanceId': None, 'model': 'alpha-deep'}, None))
        self.assertEqual([(r['source'], r['providerInstanceId'], r['model']) for r in found['readings']],
                         [('status', None, 'alpha-deep'), ('receipt', 'fixture-b', None)])
        self.assertEqual(row['problems'], ['identity_unverified'])
        # Neither the pair no source reported nor the requested target can be accepted as what ran.
        for observed in ('fixture-b/alpha-deep', 'fixture-a/alpha-swift'):
            out = self.refused(self.decide(fi, f'Accept observed model {observed} for focus-group cell {h.cell(0)} '
                                               'first-impression request fi-01-r0 (requested fixture-a/alpha-swift)'),
                               'identity_unreported')
            self.assertIsNone(out['data']['evidence']['observed'])
        self.blocked_everywhere(fi)
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(0)}:first-impression'],
                         'accepted-unusable')
        code, out = h.call_evidence('brief', '--state-root', h.root, '--study', h.view['study_id'], '--input',
                                    h.write('r9-brief.json', {'revision': h.view['revision'], 'cell_id': h.cell(0),
                                                              'stage': 'journey', 'task_id': 'jr-01'}))
        self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'), out)
        # Complementary readings the canonical rules do resolve: the status provider and a receipt model.
        self.identify('fi-02', 'fi-02-r0', other['host'], receipt_identity={'model': 'beta-two'})
        found = self.cells()[h.cell(1)]['first-impression']['identity_evidence']
        self.assertEqual((found['kind'], found['observed'], found['missing']),
                         ('wrong-model', {'providerInstanceId': 'fixture-b', 'model': 'beta-two'}, []))
        self.refused(self.decide(fb, f'Accept observed model fixture-b/beta-one for focus-group cell {h.cell(1)} '
                                     'first-impression request fi-02-r0 (requested fixture-b/beta-one)'),
                     'approval_scope_mismatch')
        self.assertEqual(self.decide(fb, found['instruction'])[0], 0)
        self.assertEqual(h.admit_slot(3, 'first-impression', 'fi-04-r0')[0], 0)
        # One complete receipt reading without the status provider the canonical rules need stays a hold.
        late = h.first(3, request='fi-04-r0', identity=None, admit=False)
        self.assertEqual(late['code'], 0, late['out'])
        self.identify('fi-04', 'fi-04-r0', late['host'],
                      receipt_identity={'providerInstanceId': 'fixture-b', 'model': 'beta-two'})
        found = self.cells()[h.cell(3)]['first-impression']['identity_evidence']
        self.assertEqual((found['observed'], found['hold_code'], found['missing']),
                         (None, 'identity_unreported', ['providerInstanceId']))
        self.refused(self.decide(late['out']['data']['record_sha256'], 'Accept observed model fixture-b/beta-two for '
                                 f'focus-group cell {h.cell(3)} first-impression request fi-04-r0 '
                                 '(requested fixture-b/beta-one)'), 'identity_unreported')
        after = self.accepted_bytes()
        self.assertEqual({k: after[k] for k in records}, records)

    def r10_admitted_then_invalidated(self, before_change=None):
        """The reviewer's R10 sequence: model A's pilot is accepted on fixture-a/alpha-swift, a receipt names
        fixture-b/alpha-deep, the owner accepts that exact contradiction, and fi-03-r0 is admitted (charged). Then
        a status fixture-b/alpha-swift and receipt fixture-a/alpha-deep reading changes the evidence, so the
        decision no longer applies and the pilot fails. Returns what later checks compare against."""
        h = self.h
        h.start()
        run, other = h.first(0), h.first(1)
        fi = run['out']['data']['record_sha256']
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-deep'})
        old_quote = self.cells()[h.cell(0)]['first-impression']['identity_evidence']['instruction']
        self.assertEqual(self.decide(fi, old_quote)[0], 0)
        out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
        self.assertEqual((out[0], out[1]['data']['charged']), (0, True), out)
        if before_change:
            before_change()
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        found = self.cells()[h.cell(0)]['first-impression']['identity_evidence']
        self.refused(self.decide(fi, old_quote), 'approval_scope_mismatch')
        pilot = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}[
            (h.cell(0), 'first-impression')]
        self.assertEqual((pilot['state'], pilot['reasons']), ('failed', ['identity mismatched']))
        return {'fi': fi, 'found': found, 'run': run, 'other': other, 'charged': h.charged(),
                'records': self.accepted_bytes(), 'ledger': json.loads(h.ledger_bytes())}

    def held_without_launch(self, base, state):
        """fi-03-r0 keeps its ID, charge and reservation, but nothing offers or permits starting it."""
        h = self.h
        out = self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual((out['data']['request_id'], out['data']['charged'], out['data']['pilot']['state']),
                         ('fi-03-r0', False, 'failed'))
        # Every new request for this model's cells stays held; the other model is not affected.
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-new'), 'pilot_failed')
        view = h.reconcile()
        row = next(r for r in view['requests'] if r['request_id'] == 'fi-03-r0')
        self.assertEqual((row['state'], row['ledger_state'], row['launch_hold']['code']), (state, 'open', 'pilot_failed'))
        self.assertEqual(view['actions']['dispatch_same_request'], [])
        self.assertEqual([(a['request_id'], a['clientRequestId'], a['code']) for a in view['actions']['launch_held']],
                         [('fi-03-r0', 'fi-03-r0', 'pilot_failed')])
        self.assertIn('fi-03-r0', view['unresolved'])
        resumed = h.resume()
        slot = {s['slot']: s for s in resumed['slots']}[f'{h.cell(2)}:first-impression']
        self.assertEqual((slot['state'], slot['code'], slot['requests'], resumed['blockers']),
                         ('held', 'pilot_failed', ['fi-03-r0'], []))
        self.assertEqual(resumed['reconciliation']['actions']['dispatch_same_request'], [])
        self.assertEqual(h.charged(), base['charged'])
        self.assertEqual(json.loads(h.ledger_bytes())['requests'], base['ledger']['requests'])
        self.assertEqual(self.accepted_bytes(), base['records'])

    def test_r10_an_open_request_never_prepared_waits_for_its_pilot_and_a_fresh_exact_decision_restores_it(self):
        h = self.h
        base = self.r10_admitted_then_invalidated()
        self.assertEqual(base['charged'], {'first': 3})
        self.held_without_launch(base, 'admitted-not-prepared')
        # A fresh decision on exactly the current evidence restores the pilot and the same charged ID, uncharged.
        code, out = self.decide(base['fi'], base['found']['instruction'])
        self.assertEqual((code, out['data']['verified']), (0, False), out)
        for _ in range(2):  # an equivalent reading, then an unrelated slot change, ask nothing again
            code, out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
            self.assertEqual((code, out['data']['duplicate'], out['data']['charged'], out['data']['host_started']),
                             (0, True, False, False), out)
            self.identify('fi-01', 'fi-01-r0', base['run']['host'],
                          status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                          receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        h.journey_ready(1)
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        self.assertEqual(h.charged(), base['charged'])
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request']), ([], []))
        self.assertEqual(h.prepare('fi-03')['request_id'], 'fi-03-r0')
        self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                         [{'task_id': 'fi-03', 'request_id': 'fi-03-r0'}])
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(2)}:first-impression'],
                         'in-flight')
        self.assertEqual((h.charged(), self.accepted_bytes()), (base['charged'], base['records']))

    def test_r10_a_prepared_request_with_a_lost_response_is_held_but_its_started_task_is_still_owned(self):
        h = self.h

        def lost_response():
            h.prepare('fi-03')
            self.assertEqual(h.observe('fi-03', kind='uncertain', request_id='fi-03-r0')[0], 0)
            # While the pilot passes, a genuine response-loss retry keeps the same ID, uncharged.
            code, out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
            self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False), out)
            self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                             [{'task_id': 'fi-03', 'request_id': 'fi-03-r0'}])

        base = self.r10_admitted_then_invalidated(lost_response)
        self.held_without_launch(base, 'dispatch-uncertain')
        # The host finds the task the lost response started: it is owned work, read and ingested as usual.
        host = h.launch('fi-03', 'fi-03-r0', n=2)
        code, out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
        self.assertEqual((code, out['data']['host_started'], out['data']['charged']), (0, True, False), out)
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request'],
                          view['actions']['task_status']),
                         ([], [], [{'host_task_id': host, 'request_id': 'fi-03-r0'}]))
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(2)}:first-impression'],
                         'in-flight')
        brief = json.loads(Path(self.task('fi-03')['brief']['path']).read_text())
        item = h.payload_file('fi-03', h.first_payload(h.view, h.cell(2), h.documents['fi-03']['sha256']))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', host, 'done-fi-03-r0')[0], 0)
        self.assertEqual(h.deliver('fi-03', 'fi-03-r0', 'done-fi-03-r0', path)[0], 0)
        code, out = h.ingest('fi-03', 'fi-03-r0', 'done-fi-03-r0', path)
        self.assertEqual((code, out['data']['identity']), (0, 'verified'), out)
        view = h.reconcile()
        self.assertEqual(next(r for r in view['requests'] if r['request_id'] == 'fi-03-r0')['ledger_state'], 'terminal')
        self.assertEqual(h.charged(), base['charged'])

    def r11_admitted_then_old_host_reopens(self, before_reopen=None):
        """The reviewer's R11 sequence at max_concurrency 1: fi-01 is accepted and closed, fi-02-r0 is admitted while
        capacity is free (its reservation only), then a later reading of fi-01's host shows a pending descendant."""
        h = self.h
        h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=1))
        run = h.first(0)
        self.assertEqual(run['code'], 0, run['out'])
        out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((out[0], out[1]['data']['charged']), (0, True), out)
        # Its own reservation is the only occupied unit: never counted against its own start.
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged'], out['data']['host_started']),
                         (0, True, False, False), out)
        if before_reopen:
            before_reopen()
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', run['host'], None, pending=True, kind='reconciled')[0], 0)
        self.assertEqual(h.reconcile()['unresolved'], ['fi-01-r0', 'fi-02-r0'])
        return {'run': run, 'charged': h.charged(), 'records': self.accepted_bytes(),
                'ledger': json.loads(h.ledger_bytes())}

    def held_by_capacity(self, base, state):
        """fi-02-r0 keeps its ID, charge and reservation, but nothing offers or permits starting it."""
        h = self.h
        old = {'kind': 'host', 'host_task_id': base['run']['host'], 'request_id': 'fi-01-r0'}
        own = {'kind': 'reservation', 'host_task_id': None, 'request_id': 'fi-02-r0'}
        out = self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['occupied'], out['data']['occupied_count']), (['fi-01-r0', 'fi-02-r0'], 2))
        out = self.refused(h.admit_slot(1, 'first-impression', 'fi-02-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['request_id'], out['data']['charged'], out['data']['occupied'],
                          out['data']['occupied_count'], out['data']['occupied_work'], out['data']['excluded']),
                         ('fi-02-r0', False, ['fi-01-r0'], 1, [old], own))
        view = h.reconcile()
        row = next(r for r in view['requests'] if r['request_id'] == 'fi-02-r0')
        self.assertEqual((row['state'], row['ledger_state'], row['launch_hold']['code'],
                          row['launch_hold']['occupied_work']), (state, 'open', 'concurrency_limit', [old]))
        self.assertEqual(view['actions']['dispatch_same_request'], [])
        self.assertEqual([(a['request_id'], a['clientRequestId'], a['code']) for a in view['actions']['launch_held']],
                         [('fi-02-r0', 'fi-02-r0', 'concurrency_limit')])
        self.assertEqual((view['actions']['task_status'], view['actions']['task_cancel']),
                         ([{'host_task_id': base['run']['host'], 'request_id': 'fi-01-r0'}], []))
        resumed = h.resume()
        slot = {s['slot']: s for s in resumed['slots']}[f'{h.cell(1)}:first-impression']
        self.assertEqual((slot['state'], slot['code'], slot['requests'], resumed['blockers']),
                         ('held', 'concurrency_limit', ['fi-02-r0'], []))
        self.assertEqual(resumed['reconciliation']['actions']['dispatch_same_request'], [])
        self.assertEqual(h.charged(), base['charged'])
        self.assertEqual(json.loads(h.ledger_bytes())['requests'], base['ledger']['requests'])
        self.assertEqual(self.accepted_bytes(), base['records'])

    def test_r11_a_never_prepared_request_waits_while_a_reopened_host_fills_capacity_and_starts_once_it_settles(self):
        h = self.h
        base = self.r11_admitted_then_old_host_reopens()
        self.assertEqual(base['charged'], {'first': 2})
        self.held_by_capacity(base, 'admitted-not-prepared')
        # The shared job can still freeze its brief; the hold stays until capacity is free.
        self.assertEqual(h.prepare('fi-02')['request_id'], 'fi-02-r0')
        self.held_by_capacity(base, 'prepared-not-dispatched')
        # Only the old host's own terminal reading without pending runs frees it: the same ID then starts, uncharged.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', base['run']['host'], None, kind='reconciled')[0], 0)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged'], out['data']['host_started']),
                         (0, True, False, False), out)
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request']),
                         ([], [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}]))
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(1)}:first-impression'],
                         'in-flight')
        # A fresh ID is still refused: the open request's reservation fills the limit.
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'concurrency_limit')
        self.assertEqual((h.charged(), self.accepted_bytes()), (base['charged'], base['records']))

    def test_r11_a_prepared_request_is_held_but_a_task_it_already_started_is_owned_and_ingested(self):
        h = self.h
        base = self.r11_admitted_then_old_host_reopens(lambda: h.prepare('fi-02'))
        self.held_by_capacity(base, 'prepared-not-dispatched')
        # The host finds a task this request already started: it is owned work, even above the limit, and is read,
        # completed and ingested as usual. It is never dispatched again or cancelled because capacity changed.
        host = h.launch('fi-02', 'fi-02-r0', n=1)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['host_started'], out['data']['charged']), (0, True, False), out)
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request'],
                          view['actions']['task_cancel'], view['actions']['task_status']),
                         ([], [], [], [{'host_task_id': base['run']['host'], 'request_id': 'fi-01-r0'},
                                       {'host_task_id': host, 'request_id': 'fi-02-r0'}]))
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(1)}:first-impression'],
                         'in-flight')
        brief = json.loads(Path(self.task('fi-02')['brief']['path']).read_text())
        item = h.payload_file('fi-02', h.first_payload(h.view, h.cell(1), h.documents['fi-02']['sha256']))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('fi-02', 'fi-02-r0', host, 'done-fi-02-r0')[0], 0)
        self.assertEqual(h.deliver('fi-02', 'fi-02-r0', 'done-fi-02-r0', path)[0], 0)
        code, out = h.ingest('fi-02', 'fi-02-r0', 'done-fi-02-r0', path)
        self.assertEqual((code, out['data']['identity']), (0, 'verified'), out)
        view = h.reconcile()
        self.assertEqual(next(r for r in view['requests'] if r['request_id'] == 'fi-02-r0')['ledger_state'], 'terminal')
        self.assertEqual(view['unresolved'], ['fi-01-r0'])
        self.assertEqual(h.charged(), base['charged'])

    def test_r11_a_lost_response_retry_waits_for_capacity_then_keeps_its_request_id(self):
        h = self.h

        def lost_response():
            h.prepare('fi-02')
            self.assertEqual(h.observe('fi-02', kind='uncertain', request_id='fi-02-r0')[0], 0)
            # While capacity is free, a genuine response-loss retry keeps the same ID, uncharged.
            code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
            self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False), out)
            self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                             [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}])

        base = self.r11_admitted_then_old_host_reopens(lost_response)
        self.held_by_capacity(base, 'dispatch-uncertain')
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', base['run']['host'], None, kind='reconciled')[0], 0)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False), out)
        self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                         [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}])
        host = h.launch('fi-02', 'fi-02-r0', n=1)
        self.assertEqual(next(r for r in h.reconcile()['requests'] if r['request_id'] == 'fi-02-r0')['state'], 'running')
        self.assertTrue(host)
        self.assertEqual(h.charged(), base['charged'])

    def test_r4_a_revised_study_moves_the_job_before_any_launch_and_never_duplicates_old_work(self):
        h = self.h
        h.start()
        self.assertEqual(h.first(0)['code'], 0)                      # model A's pilot, accepted in the old revision
        self.assertEqual(h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)
        h.prepare('fi-02')
        h.launch('fi-02', 'fi-02-r0', n=1)                           # model B's pilot, still running
        old_brief = self.task('fi-01')['brief']
        old_bytes, records, charged = Path(old_brief['path']).read_bytes(), self.accepted_bytes(), h.charged()
        old_doc = self.task('fi-02')['document']
        # The owner approves a protocol revision; its carry mapping is written and the pilot's new brief built.
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['prompts']['first_impression'] += ' Note one thing that works.'
        revised = h.plan(draft)
        h.approve(revised)
        h.ok('carry', '--state-root', h.root, '--study', revised['study_id'], '--write')
        h.view = revised
        document = h.document(0, 'first-impression', 'fi-01')
        # Until the job follows, resume reports nothing dispatchable and admission refuses, uncharged.
        resumed = h.resume()
        self.assertEqual(resumed['blockers'][0]['code'], 'job_revision_stale')
        self.assertNotIn('dispatchable', {s['state'] for s in resumed['slots']})
        self.refused(h.admit_slot(0, 'first-impression', 'fi-01-new'), 'job_revision_stale')
        self.assertEqual(h.charged(), charged)
        # job-revision lists each slot; the live old task's slot is held, never rewritten under it.
        listed = h.lc_ok(*h.study('job-revision'))
        states = {row['task_id']: row['state'] for row in listed['slots']}
        self.assertEqual((states['fi-01'], states['fi-02']), ('needs-brief', 'held-live'))
        out = h.lc_ok(*h.study('job-revision'), '--documents', h.write('revision-docs.json', {'fi-01': document}))
        self.assertTrue(out['changed'])
        self.assertEqual(out['decision_input']['decision']['quote'], revised['approval_instruction'])
        h.job_ok('decision', out['decision_input'])
        h.job_ok('plan-revision', out['plan_revision_input'])
        job = h.job_state()
        self.assertEqual({s['validator_contract']['study_revision'] for s in job['stages']}, {revised['revision']})
        self.assertEqual((self.task('fi-01')['document'], self.task('fi-02')['document']), (document, old_doc))
        self.assertEqual(self.task('fi-02')['handles'][0]['status'], 'running')
        self.assertEqual(h.lc_ok(*h.study('job-revision'), '--documents',
                                 h.write('again.json', {'fi-01': document}))['changed'], False)
        # Resume: the pilot slot is a charged retry, the live old pilot of model B is not duplicated.
        slots = {s['slot']: s for s in h.resume()['slots']}
        self.assertEqual(slots[f'{h.cell(0)}:first-impression']['state'], 'dispatchable')
        self.assertIn('charged retry', slots[f'{h.cell(0)}:first-impression']['next'])
        self.assertEqual((slots[f'{h.cell(1)}:first-impression']['state'],
                          slots[f'{h.cell(1)}:first-impression']['code']), ('held', 'job_slot_stale'))
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'fi-01', 'reason': 'protocol revision'})
        request = self.task('fi-01')['request_id']
        code, admitted = h.admit_slot(0, 'first-impression', request)
        self.assertEqual((code, admitted['data']['charged']), (0, True), admitted)
        brief = h.prepare('fi-01')
        self.assertEqual((brief['document'], brief['request_id']), (document, request))
        self.assertEqual(self.task('fi-01')['target'], {k: revised['cells'][0][k] for k in
                                                       ('providerInstanceId', 'model', 'options')})
        # The old brief, accepted record, request history and charges are kept; nothing was reset.
        self.assertEqual((Path(old_brief['path']).read_bytes(), self.accepted_bytes()), (old_bytes, records))
        self.assertIn('fi-01-r0', self.task('fi-01')['retired_request_ids'])
        self.assertEqual(h.charged(), {'first': charged['first'] + 1})

    def test_r5_direct_record_acceptance_never_stands_in_for_host_ingestion_once_a_job_exists(self):
        h = self.h
        h.start()
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        h.prepare('fi-01')
        h.launch('fi-01', 'fi-01-r0', identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        item = h.payload_file('fi-01', h.first_payload(h.view, h.cell(0), h.documents['fi-01']['sha256']))
        record = {'revision': h.view['revision'], 'cell_id': h.cell(0), 'stage': 'first-impression', 'task_id': 'fi-01',
                  'request_id': 'fi-01-r0', 'result': {'path': str(h.root / h.view['study_id'] / item['path']),
                                                       'sha256': item['sha256']},
                  'observed': {'providerInstanceId': 'fixture-a', 'model': 'alpha-swift', 'source': 'a supplied claim'},
                  'predecessors': [], 'context': None, 'image_delivery': DELIVERED}
        h.refused('host_ingest_required', 'record-acceptance', '--state-root', h.root, '--study', h.view['study_id'],
                  '--input', h.write('direct.json', record))
        self.assertEqual(self.accepted_bytes(), {})
        pilots = {(p['pilot_cell'], p['stage']): p['state'] for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual(pilots[(h.cell(0), 'first-impression')], 'running')
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_pending')

    def test_r6_a_delayed_completion_offered_with_an_aged_catalog_is_retained_logged_and_later_accepted(self):
        h = self.h
        h.start()
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        brief = h.prepare('fi-01')
        host = h.launch('fi-01', 'fi-01-r0')
        item = h.payload_file('fi-01', h.first_payload(h.view, h.cell(0), h.documents['fi-01']['sha256']))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, 'late')[0], 0)
        self.assertEqual(h.deliver('fi-01', 'fi-01-r0', 'late', path)[0], 0)
        late = '2029-06-01T00:30:00Z'                                # the catalog saved at BEFORE is now too old
        code, out = h.ingest('fi-01', 'fi-01-r0', 'late', path, now=late, catalog=h.catalog(BEFORE))
        self.assertEqual((code, out['error']['code'], out['data']['category'], out['data']['product_friction']),
                         (1, 'stale_observation', 'lifecycle', False))
        raw = h.root / h.view['study_id'] / 'focus-group' / out['data']['raw_retained']
        self.assertEqual(raw.read_bytes(), path.read_bytes())
        self.assertEqual([(r['outcome'], r['code']) for r in h.session('fi-01-r0')], [('refused', 'stale_observation')])
        self.assertEqual(self.accepted_bytes(), {})
        # The same retained completion is ingested once a fresh observation is saved.
        code, out = h.ingest('fi-01', 'fi-01-r0', 'late', path, now=late, catalog=h.catalog(late))
        self.assertEqual((code, out['data']['identity']), (0, 'verified'), out)
        self.assertEqual([r['outcome'] for r in h.session('fi-01-r0')], ['refused', 'accepted'])

    def test_n1_cancel_without_a_recorded_host_handle_names_the_request_and_never_invents_its_end(self):
        h = self.h
        h.start()
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        h.prepare('fi-01')                                           # prepared: a lost response may have started it
        self.assertEqual(h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)   # admitted, never prepared
        charged = h.charged()
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['cancel'], cancel['task_cancel']),
                         (False, ['fi-01-r0'], []))
        self.assertEqual([{k: r[k] for k in ('task_id', 'request_id', 'clientRequestId', 'state')}
                          for r in cancel['rediscover']],
                         [{'task_id': 'fi-01', 'request_id': 'fi-01-r0', 'clientRequestId': 'fi-01-r0',
                           'state': 'prepared-not-dispatched'}])
        ledger = json.loads(h.ledger_bytes())['requests']
        self.assertEqual((ledger['fi-02-r0']['state'], ledger['fi-02-r0']['terminal_kind']), ('terminal', 'never-prepared'))
        self.assertEqual(ledger['fi-01-r0']['state'], 'cancel-requested')
        view = h.reconcile()
        self.assertEqual((view['actions']['dispatch_same_request'], view['unresolved']), ([], ['fi-01-r0']))
        self.assertEqual(h.status(h.view)['cancel_pending_confirmation'], ['fi-01-r0'])
        # The host finds the task by its clientRequestId: the existing accepted observation records it.
        host = h.launch('fi-01', 'fi-01-r0')
        view = h.reconcile()
        self.assertEqual((view['actions']['task_cancel'], view['actions']['rediscover']),
                         ([{'host_task_id': host, 'request_id': 'fi-01-r0'}], []))
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, None, status='cancelled', kind='reconciled')[0], 0)
        self.assertTrue(h.reconcile()['cancellation_confirmed'])
        # A brief prepared later for the closed request reopens it: the closure never hides recorded work.
        h.prepare('fi-02')
        view = h.reconcile()
        self.assertEqual((view['cancellation_confirmed'], view['unresolved'],
                          [r['request_id'] for r in view['actions']['rediscover']]), (False, ['fi-02-r0'], ['fi-02-r0']))
        self.assertEqual(h.charged(), charged)


if __name__ == '__main__':
    unittest.main()
