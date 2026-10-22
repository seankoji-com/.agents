"""focus-group FG-2: shared captures, blind briefs, frozen first impressions and isolated journeys.

Every check runs `plugins/focus-group/scripts/evidence.py` and `study.py` as subprocesses against
temporary job roots, invented packs and an invented catalog. Browser isolation is exercised with a
fake host whose cookies travel over a real loopback HTTP server; its local and session storage are
in-memory. That is fixture evidence for the refusal and recovery paths, never live isolation.
Nothing calls a model, a real browser, T3 or GitHub.
"""
import copy
import http.cookiejar
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import focus_group_fixtures as fixtures  # noqa: E402
from tests.test_focus_group_plan import BEFORE, DELIVERED, PLUGIN, TEMPLATE, Workspace, sha  # noqa: E402

EVIDENCE = PLUGIN / 'scripts' / 'evidence.py'
LATER = '2029-06-01T00:05:00Z'
# Deliberately written into temporary artifacts to test quarantine and redaction.
# This invented marker is public test data, not a credential.
SYNTHETIC_MARKER = 'FAKE-INVENTED-0123456789abcdef'


# ----------------------------------------------------------------------------- loopback browser fixture


class ProbeServer(http.server.ThreadingHTTPServer):
    """Loopback origin: /set stores a cookie, /read echoes the cookies the client sent."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                query = dict(urllib.parse.parse_qsl(url.query))
                body = b'{}'
                self.send_response(200)
                if url.path == '/set':
                    self.send_header('Set-Cookie', f'{query["k"]}={query["v"]}; Path=/')
                elif url.path == '/read':
                    body = json.dumps({'cookie': self.headers.get('Cookie', '')}).encode()
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        super().__init__(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.server_address[1]}'

    def close(self):
        self.shutdown()
        self.server_close()


class FakeContext:
    """One fake host browser context. A tab in a shared profile shares the jar and localStorage
    but has its own sessionStorage, as browsers do."""

    def __init__(self, server, shared=None):
        self.server = server
        self.jar = shared.jar if shared else http.cookiejar.CookieJar()
        self.local = shared.local if shared else {}
        self.session = {}
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, path):
        with self.opener.open(self.server.origin + path, timeout=10) as response:
            return json.loads(response.read())

    def write(self, key, value, own):
        for name, item in ((key, value), (own, '1')):
            self.get('/set?' + urllib.parse.urlencode({'k': name, 'v': item}))
            self.local[name] = item
            self.session[name] = item

    def read(self, key, others):
        header = self.get('/read')['cookie']
        cookies = dict(part.split('=', 1) for part in header.split('; ') if part)
        return {'origin': self.server.origin,
                'shared': {'cookie': cookies.get(key), 'local': self.local.get(key), 'session': self.session.get(key)},
                'others_own_seen': {'cookie': any(o in cookies for o in others),
                                    'local': any(o in self.local for o in others),
                                    'session': any(o in self.session for o in others)},
                'cleared': False}


def child_tools(*names, native=None):
    return {'schema_version': 1, 'observed_at': BEFORE, 'source': 'fixture child tool observation',
            'tools': [{'name': n} for n in names], 'native_browser': native}


PREVIEW = child_tools('mcp__t3-code__preview_open', 'mcp__t3-code__preview_navigate', 'mcp__t3-code__preview_snapshot',
                      'mcp__t3-code__preview_evaluate', 'mcp__t3-code__preview_click', 'Read')


# ----------------------------------------------------------------------------- harness


class Lab(Workspace):
    """A Workspace plus the FG-2 evidence entry points."""

    def ev(self, *args):
        proc = subprocess.run([sys.executable, str(EVIDENCE), *map(str, args)], capture_output=True, text=True,
                              timeout=60, cwd=self.base)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (proc.stdout, proc.stderr)
        self.last_output = proc.stdout + proc.stderr
        return proc.returncode, json.loads(lines[0])

    def ev_ok(self, *args):
        code, out = self.ev(*args)
        assert code == 0, out
        return out['data']

    def study_args(self, study, name, payload=None):
        args = [name, '--state-root', self.root, '--study', study]
        if payload is not None:
            self.counter += 1
            args += ['--input', self.write(f'{name}-{self.counter}.json', payload)]
        return args

    def validate_pack(self, study, manifest):
        return self.ev(*self.study_args(study, 'pack', manifest))

    def small(self, **changes):
        """A two-persona combined study (four cells)."""
        personas = json.loads(TEMPLATE.read_text())['personas'][:2]
        return self.draft(personas=personas, **changes)


class EvidenceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lab = Lab(Path(self.tmp.name).resolve())

    # helpers shared by the requirement classes

    def approved(self, draft=None):
        view = self.lab.plan(draft or self.lab.small())
        self.lab.approve(view)
        return view

    def brief(self, view, n, stage, expect=0):
        cell = view['cells'][n]['cell_id']
        task = f"{'fi' if stage == 'first-impression' else 'jr'}-{n + 1:02d}"
        code, out = self.lab.ev(*self.lab.study_args(view['study_id'], 'brief', {
            'revision': view['revision'], 'cell_id': cell, 'stage': stage, 'task_id': task}))
        self.assertEqual(code, expect, out)
        return out['data'] if code == 0 else out

    def task_dir(self, view, task):
        folder = self.lab.root / view['study_id'] / 'artifacts' / 'tasks' / task
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def first_payload(self, view, n, brief_sha, **changes):
        cell = view['cells'][n]['cell_id']
        payload = {'schema': 'focus-group/first-impression', 'schema_version': 1, 'cell_id': cell,
                   'study_revision': view['revision'], 'brief_sha256': brief_sha,
                   'image_use': {'saw_images': True, 'basis': 'image-and-text'},
                   'initial_viewport': {'file': 'initial-viewport.png', 'reaction': f'Calm first screen for cell {n}.',
                                        'observed': ['a large heading and one green button'],
                                        'inferred': ['the button probably starts planning']},
                   'walkthrough': [{'file': 'shopping-list.png', 'reaction': 'Handy list.',
                                    'observed': ['items grouped by aisle'], 'inferred': []},
                                   {'file': 'welcome.txt', 'reaction': 'Short and clear.',
                                    'observed': ['promises three dinners in a few taps'], 'inferred': []}],
                   'claims': [{'id': 'c1', 'kind': 'visual', 'statement': 'The button is green.',
                               'files': ['initial-viewport.png']},
                              {'id': 'c2', 'kind': 'textual', 'statement': 'It promises a few taps.',
                               'files': ['welcome.txt']}],
                   'simulated': True}
        payload.update(changes)
        return payload

    def write_payload(self, view, task, payload, name='payload.json'):
        path = self.task_dir(view, task) / name
        path.write_bytes(json.dumps(payload).encode())
        return {'path': str(path), 'sha256': sha(path.read_bytes())}

    @staticmethod
    def inspection(ref, **flags):
        """The coordinator's inspection record for every screenshot a journey payload cites (None if none)."""
        try:
            payload = json.loads(Path(ref['path']).read_text())
        except (OSError, ValueError):
            return None
        goals = payload.get('goals') if isinstance(payload, dict) else None
        shots = sorted({e['sha256'] for g in goals if isinstance(g, dict) for e in g.get('evidence', [])
                        if isinstance(e, dict) and e.get('kind') == 'screenshot'} if isinstance(goals, list) else ())
        if not shots:
            return None
        seen = {'viewed': True, 'secrets_visible': False, 'personal_data_visible': False, **flags}
        return {'inspector': 'coordinator', 'inspected_at': '2029-06-01T00:10:00Z', 'files': {s: seen for s in shots}}

    def check(self, view, n, stage, task, ref, delivery=None, inspection='auto'):
        request = {'revision': view['revision'], 'cell_id': view['cells'][n]['cell_id'], 'stage': stage,
                   'task_id': task, 'payload': ref}
        if stage == 'first-impression':
            request['image_delivery'] = delivery or DELIVERED
        else:
            inspection = self.inspection(ref) if inspection == 'auto' else inspection
            if inspection is not None:
                request['material_inspection'] = inspection
        return self.lab.ev(*self.lab.study_args(view['study_id'], 'check-payload', request))

    def record(self, view, n, stage, task, ref, predecessors=(), context=None, admit=True, delivery=None,
               inspection='auto', request_id=None):
        """record-acceptance: the ingestion boundary, which screens and validates the exact bytes itself."""
        cell = view['cells'][n]['cell_id']
        request_id = request_id or f'{task}-r0'
        if admit:
            code, out = self.lab.admit(view, request_id, stage, cell)
            self.assertEqual(code, 0, out)
            self.lab.release(view, request_id)
        model = view['cells'][n]
        request = {'revision': view['revision'], 'cell_id': cell, 'stage': stage, 'task_id': task,
                   'request_id': request_id, 'result': ref,
                   'observed': {'providerInstanceId': model['providerInstanceId'], 'model': model['model'],
                                'source': 'fixture task_status'},
                   'predecessors': list(predecessors), 'context': context}
        if stage == 'first-impression':
            request['image_delivery'] = delivery or DELIVERED
        else:
            inspection = self.inspection(ref) if inspection == 'auto' else inspection
            if inspection is not None:
                request['material_inspection'] = inspection
        self.lab.counter += 1
        code, out = self.lab.call('record-acceptance', '--state-root', self.lab.root, '--study', view['study_id'],
                                  '--input', self.lab.write(f'record-{task}-{self.lab.counter}.json', request))
        self.lab.last_output = json.dumps(out)
        return code, out

    def freeze(self, view, record_sha, ref, delivery=None):
        return self.lab.ev(*self.lab.study_args(view['study_id'], 'freeze-first', {
            'record_sha256': record_sha, 'payload': ref, 'image_delivery': delivery or DELIVERED}))

    def accepted_first(self, view, n, **changes):
        """Brief, payload, advisory check and record one cell's first impression (record-acceptance freezes
        it), then verify the frozen record through freeze-first."""
        task = f'fi-{n + 1:02d}'
        brief = self.brief(view, n, 'first-impression')
        ref = self.write_payload(view, task, self.first_payload(view, n, brief['document']['sha256'], **changes))
        code, out = self.check(view, n, 'first-impression', task, ref)
        self.assertEqual(code, 0, out)
        code, out = self.record(view, n, 'first-impression', task, ref)
        self.assertEqual(code, 0, out)
        record_sha = out['data']['record_sha256']
        code, out = self.freeze(view, record_sha, ref)
        self.assertEqual((code, out['data']['duplicate']), (0, True), out)
        return {'record_sha256': record_sha, 'ref': ref, 'brief': brief}

    def study_dir(self, view, *parts):
        return self.lab.root.joinpath(view['study_id'], *parts)


class IsolationHarness(EvidenceCase):
    """A fixture-environment study whose target is a loopback origin."""

    def setUp(self):
        super().setUp()
        self.server = ProbeServer()
        self.addCleanup(self.server.close)

    def fixture_study(self, **changes):
        draft = self.lab.small(target={'kind': 'url', 'url': self.server.origin + '/welcome', 'environment': 'fixture',
                                       'label': 'Invented loopback prototype'}, **changes)
        return self.approved(draft)

    def probe(self, view, cells):
        return self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'probe-plan', {
            'revision': view['revision'], 'cell_ids': [view['cells'][n]['cell_id'] for n in cells]}))

    def run_probe(self, view, probe, contexts):
        """Every write, then every read, each in its own (fake) context; returns readings by cell."""
        ids = list(probe['cells'])
        for cell_id in ids:
            row = probe['cells'][cell_id]
            contexts[cell_id].write(probe['shared_key'], row['value'], row['own_key'])
        return {cell_id: contexts[cell_id].read(probe['shared_key'],
                                                [probe['cells'][o]['own_key'] for o in ids if o != cell_id])
                for cell_id in ids}

    def bind(self, view, n, probe, readings, reference=None, boundary='isolated-context', tools=PREVIEW,
             assignment=None, evidence_class='fixture'):
        cell = view['cells'][n]['cell_id']
        return self.lab.ev(*self.lab.study_args(view['study_id'], 'bind-context', {
            'revision': view['revision'], 'cell_id': cell, 'child_tools': tools,
            'context': {'reference': reference or f'fixture-context-{n}', 'boundary': boundary},
            'assignment': assignment or {'kind': 'host-enforced', 'source': 'fixture host binding receipt',
                                         'receipt_sha256': sha(f'receipt {n}'.encode()), 'child_ref': f'child-{n}'},
            'evidence_class': evidence_class, 'probe': {'probe_id': probe['probe_id'], 'readings': readings}}))

    def isolated(self, view, cells=(0, 1)):
        probe = self.probe(view, cells)
        contexts = {view['cells'][n]['cell_id']: FakeContext(self.server) for n in cells}
        readings = self.run_probe(view, probe, contexts)
        bindings = {}
        for n in cells:
            code, out = self.bind(view, n, probe, readings)
            self.assertEqual(code, 0, out)
            bindings[n] = out['data']['binding_sha256']
        return bindings

    def journey_payload(self, view, n, brief_sha, binding_sha, task, reference=None, **changes):
        shot = self.task_dir(view, task) / 'live-step-1.png'
        shot.write_bytes(fixtures.png(390, 844, ((255, 255, 255), (10, 120, 200), (0, 0, 0))))
        payload = {'schema': 'focus-group/journey', 'schema_version': 1, 'cell_id': view['cells'][n]['cell_id'],
                   'study_revision': view['revision'], 'brief_sha256': brief_sha, 'driver': 'participant-child',
                   'context': {'reference': reference or f'fixture-context-{n}', 'binding_sha256': binding_sha},
                   'target': {'url': self.server.origin + '/welcome', 'environment': 'fixture'},
                   'environment_drift': {'state': 'unavailable', 'detail': 'fixture server exposes no deployment ID'},
                   'started_at': LATER, 'ended_at': '2029-06-01T00:09:00Z',
                   'goals': [{'journey_id': 'plan-three-dinners', 'outcome': 'partial',
                              'steps': [{'at': '2029-06-01T00:06:00Z', 'kind': 'tap',
                                         'permitted_action': 'browse recipes', 'description': 'opened recipes',
                                         'url': self.server.origin + '/recipes', 'field': None},
                                        {'at': '2029-06-01T00:07:00Z', 'kind': 'tap',
                                         'permitted_action': 'add recipes to a plan', 'description': 'added two',
                                         'url': self.server.origin + '/plan', 'field': None}],
                              'reactions': ['Quick, but I lost my place once.'],
                              'observed_events': ['the plan showed two of three dinners'],
                              'inferences': ['the back button may reset filters'],
                              'evidence': [{'kind': 'screenshot', 'path': str(shot), 'sha256': sha(shot.read_bytes())}]}],
                   'gaps': []}
        payload.update(changes)
        return payload


# ----------------------------------------------------------------------------- REQ-CAPTURE


class CaptureTest(EvidenceCase):
    """REQ-CAPTURE: safe context, provenance, rehash, inspection, quarantine and immutable attempts."""

    def files(self, prefix, **kw):
        return fixtures.write_pack(self.lab.base / f'pack-{prefix}', prefix=prefix, **kw)

    def problems(self, out):
        return {p['code'] for p in out['data']['problems']}

    def test_cleared_pack_records_provenance_profile_and_unavailable_status(self):
        files = self.files('a-')
        manifest = fixtures.manifest(files)
        manifest['request']['http_status'] = 'unavailable-from-mechanism'
        code, out = self.lab.validate_pack('capture-study', manifest)
        self.assertEqual(code, 0, out)
        data = out['data']
        self.assertEqual(data['verdict'], 'cleared')
        self.assertEqual(data['http_status'], 'unavailable-from-mechanism')
        provenance = data['stimulus']['provenance']
        self.assertEqual(provenance['context']['class'], 'fresh-anonymous')
        self.assertEqual(provenance['initial_viewport'], 'a-initial-viewport.png')
        self.assertEqual(provenance['profile'], fixtures.PROFILE)
        self.assertEqual([f['sha256'] for f in data['stimulus']['files']], sorted(
            [f['sha256'] for f in files], key=lambda s: [f['name'] for f in files if f['sha256'] == s][0]))
        self.assertIn('Rendering is not proof of HTTP 200.', data['notes'])
        self.assertIn('does not establish assistive-technology testing', ' '.join(data['notes']))
        # A missing status is never inferred from rendering.
        manifest = fixtures.manifest(self.files('b-'))
        manifest['request']['http_status'] = None
        code, out = self.lab.validate_pack('capture-study', manifest)
        self.assertEqual((code, out['error']['code']), (1, 'pack_failed'))
        self.assertIn('http_status_unrecorded', self.problems(out))

    def test_fr4_a_fresh_capture_keeps_its_host_context_reference_and_missing_provenance_never_clears(self):
        # FG2-R4: capture.md asks for the host reference of the fresh context; it is retained, not refused.
        manifest = fixtures.manifest(self.files('ref-'))
        manifest['context']['reference'] = 'fixture-host-capture-context-42'
        code, out = self.lab.validate_pack('ref-study', manifest)
        self.assertEqual((code, out['data']['verdict']), (0, 'cleared'), out)
        context = out['data']['stimulus']['provenance']['context']
        self.assertEqual((context['reference'], context['user_state'], out['data']['disclosure']['non_fresh_state']),
                         ('fixture-host-capture-context-42', 'new', False))
        # Without the reference a capture fails and a supplied pack is held; the helper never invents it.
        for reference in (None, '  '):
            with self.subTest(reference=reference):
                manifest = fixtures.manifest(self.files(f'noref-{len(reference or "")}-'))
                manifest['context']['reference'] = reference
                code, out = self.lab.validate_pack('ref-study', manifest)
                self.assertEqual((code, out['error']['code']), (1, 'pack_failed'), out)
                self.assertEqual(self.problems(out), {'context_reference_missing'})
                self.assertIn('supplied pack', out['data']['offer'])
        manifest = fixtures.manifest(self.files('supplied-noref-'), kind='supplied', request=None,
                                     supplied={'source': 'owner export of the prototype', 'supplied_by': 'study owner',
                                               'obtained_at': '2029-05-31T20:00:00Z', 'offline': True})
        manifest['context']['reference'] = None
        code, out = self.lab.validate_pack('ref-study', manifest)
        self.assertEqual((code, out['error']['code']), (1, 'pack_held'), out)
        self.assertIn('context_reference_missing', self.problems(out))
        # A reference never excuses seeded state or a returning user in a context declared fresh.
        for name, change in (('cookie', lambda c: c['pre_existing_state']['cookies'].append('seen_tour')),
                             ('returning', lambda c: c.update(user_state='returning'))):
            with self.subTest(contradiction=name):
                manifest = fixtures.manifest(self.files(f'contra-{name}-'))
                change(manifest['context'])
                code, out = self.lab.validate_pack('ref-study', manifest)
                self.assertEqual((code, out['error']['code']), (1, 'pack_failed'), out)
                self.assertIn('freshness_contradicted', self.problems(out))
        # The shipped template names a host reference for its fresh context.
        template = json.loads((PLUGIN / 'templates' / 'capture-manifest.example.json').read_text())
        self.assertEqual(template['context']['class'], 'fresh-anonymous')
        self.assertTrue(template['context']['reference'].strip())

    def test_drift_missing_failed_readiness_blank_error_and_uninspected_material_fail(self):
        def case(name, change, code_name):
            files = self.files(f'{name}-')
            manifest = fixtures.manifest(files)
            change(manifest, files)
            code, out = self.lab.validate_pack(f'study-{name}', manifest)
            self.assertEqual((code, out['error']['code']), (1, 'pack_failed'), out)
            self.assertIn(code_name, self.problems(out))
            # The failed attempt is kept, immutable, under the study's evidence.
            record = self.lab.root / f'study-{name}' / 'focus-group' / 'evidence' / 'packs' / \
                f"{out['data']['manifest_sha256']}.json"
            self.assertEqual(json.loads(record.read_text())['verdict'], 'failed')

        def drift(m, files):
            Path(files[1]['path']).write_bytes(b'changed after capture')

        def missing(m, files):
            Path(files[2]['path']).unlink()

        def readiness(m, files):
            m['readiness'] = {'state': 'timeout', 'signal': 'heading never appeared', 'observed_at': BEFORE}

        def uninspected(m, files):
            m['inspection']['files']['drift-initial-viewport.png'.replace('drift', 'uninspected')]['viewed'] = False

        def blank(m, files):
            data = fixtures.png(390, 844, ((255, 255, 255),))
            Path(files[0]['path']).write_bytes(data)
            files[0].update(sha256=sha(data), bytes=len(data))

        def error(m, files):
            data = b'404 Not Found\nThe page you requested could not be found.\n'
            Path(files[3]['path']).write_bytes(data)
            files[3].update(sha256=sha(data), bytes=len(data))

        def status(m, files):
            m['request']['http_status'] = 503

        def viewport(m, files):
            m['profile']['viewport'] = {'width': 412, 'height': 915}

        for name, change, code_name in (('drift', drift, 'hash_drift'), ('missing', missing, 'missing_file'),
                                        ('readiness', readiness, 'readiness_failed'),
                                        ('uninspected', uninspected, 'uninspected_image'),
                                        ('blank', blank, 'blank_material'), ('error', error, 'error_material'),
                                        ('status', status, 'error_status'), ('viewport', viewport, 'viewport_mismatch')):
            with self.subTest(case=name):
                case(name, change, code_name)
        # A record for missing coordinator inspection of a text file fails too.
        files = self.files('nolook-')
        manifest = fixtures.manifest(files)
        del manifest['inspection']['files']['nolook-welcome.txt']
        code, out = self.lab.validate_pack('study-nolook', manifest)
        self.assertIn('uninspected_material', self.problems(out))

    def test_personal_context_is_refused_and_unresolved_supplied_pack_is_held(self):
        for cls in ('personal-profile', 'default-profile', 'saved-profile'):
            with self.subTest(context=cls):
                manifest = fixtures.manifest(self.files(f'{cls}-'))
                manifest['context'].update({'class': cls, 'reference': 'operator browser', 'freshness': None})
                code, out = self.lab.validate_pack(f'study-{cls}', manifest)
                self.assertEqual((code, out['error']['code']), (1, 'pack_failed'))
                self.assertIn('personal_context_refused', self.problems(out))
                self.assertIn('supplied pack', out['data']['offer'])
        # Freshness is never invented: a "fresh" context with seeded state is contradicted.
        manifest = fixtures.manifest(self.files('seeded-'))
        manifest['context']['pre_existing_state']['cookies'] = ['onboarding_done']
        code, out = self.lab.validate_pack('study-seeded', manifest)
        self.assertIn('freshness_contradicted', self.problems(out))
        # A supplied pack with unknown provenance is held; the helper never fills the gaps in.
        manifest = fixtures.manifest(self.files('supplied-'), kind='supplied', request=None,
                                     supplied={'source': 'owner upload', 'supplied_by': 'unknown',
                                               'obtained_at': 'unknown', 'offline': True})
        manifest['context'].update({'class': 'unknown', 'freshness': None, 'user_state': 'unknown'})
        code, out = self.lab.validate_pack('study-supplied', manifest)
        self.assertEqual((code, out['error']['code']), (1, 'pack_held'), out)
        self.assertTrue({'supplied_provenance_unresolved', 'context_unresolved'} <= self.problems(out))
        # The same pack with equivalent declared provenance clears.
        manifest = fixtures.manifest(self.files('declared-'), kind='supplied', request=None,
                                     supplied={'source': 'owner export of the prototype', 'supplied_by': 'study owner',
                                               'obtained_at': '2029-05-31T20:00:00Z', 'offline': True})
        self.assertEqual(self.lab.validate_pack('study-declared', manifest)[0], 0)

    def test_approved_non_fresh_test_context_is_disclosed_and_unapproved_one_fails(self):
        owner = self.lab.base / 'owner'
        owner.mkdir()
        answer = owner / 'test-context.txt'
        statement = 'Approve isolated test context fixture-test-account-7 for focus-group capture'
        answer.write_text(f'Selected option: {statement}\n')

        def manifest(prefix, approval):
            value = fixtures.manifest(self.files(prefix))
            value['context'] = {'class': 'preauthenticated-test', 'reference': 'fixture-test-account-7',
                                'freshness': {'verified': False, 'method': 'seeded test account', 'observed_at': BEFORE},
                                'pre_existing_state': {'cookies': ['session_marker'], 'storage': ['tour_seen'],
                                                       'onboarding': 'completed'},
                                'user_state': 'returning', 'approval': approval}
            return value
        approval = {'message_ref': 'picker-1', 'statement': statement, 'source': str(answer),
                    'source_sha256': sha(answer.read_bytes())}
        code, out = self.lab.validate_pack('test-context', manifest('t1-', approval))
        self.assertEqual(code, 0, out)
        self.assertTrue(out['data']['disclosure']['show_beside_first_impressions'])
        self.assertEqual(out['data']['stimulus']['provenance']['context']['user_state'], 'returning')
        cancelled = owner / 'cancelled.txt'
        cancelled.write_text(f'Selected option: {statement}\nActually, cancel that.\n')
        code, out = self.lab.validate_pack('test-context', manifest('t2-', dict(approval, source=str(cancelled),
                                                                        source_sha256=sha(cancelled.read_bytes()))))
        self.assertEqual((code, out['error']['code']), (1, 'pack_failed'))
        self.assertIn('test_context_unapproved', self.problems(out))

    def test_planted_secret_is_quarantined_before_any_disclosure_without_echoing_its_value(self):
        text = fixtures.PAGE_TEXT + f'debug: api_key={SYNTHETIC_MARKER}\nContact jo.invented@example.test\n'
        image = fixtures.png(390, 844, text_chunks=[('Comment', f'token={SYNTHETIC_MARKER}')])
        files = fixtures.write_pack(self.lab.base / 'secret-pack', text=text, initial=image)
        code, out = self.lab.validate_pack('pantry-planner-onboarding', fixtures.manifest(files))
        self.assertEqual((code, out['error']['code']), (1, 'pack_quarantined'), out)
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        self.assertNotIn('jo.invented', self.lab.last_output)
        classes = {(h['location'].split(':')[0], h['class']) for h in out['data']['secret_findings']}
        self.assertTrue({('welcome.txt', 'credential-assignment'), ('welcome.txt', 'email-address'),
                         ('initial-viewport.png', 'credential-assignment')} <= classes, classes)
        self.assertEqual(out['data']['disclosure']['consumers'], [])
        # A plan on the quarantined pack can be drafted but never approved, briefed or dispatched.
        draft = self.lab.small(stimulus=dict(out['data']['stimulus'], coordinator_inspected=True))
        view = self.lab.plan(draft)
        self.assertTrue(any('pack_quarantined' in line for line in view['assessment']['limitations']))
        self.lab.refused('pack_quarantined', 'approve', '--state-root', self.lab.root, '--study', view['study_id'],
                         '--input', self.lab.approval(view))
        code, out = self.lab.ev('disclosure', '--state-root', self.lab.root, '--study', view['study_id'],
                                '--consumer', 'export')
        self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'))
        self.assertNotIn(SYNTHETIC_MARKER, json.dumps(out))
        # A sanitised derivative keeps the parent's provenance, gets new hashes and needs a new approval.
        parent = out['data']
        quarantined = json.loads(next((self.lab.root / view['study_id'] / 'focus-group' / 'evidence' / 'packs')
                                      .glob('*.json')).read_text())
        clean = fixtures.write_pack(self.lab.base / 'sanitised', prefix='s-')
        derived = fixtures.manifest(clean, derived_from={'manifest_sha256': quarantined['manifest_sha256'],
                                                         'sanitisation': {'method': 'redacted debug line and email',
                                                                          'performed_at': '2029-05-31T23:30:00Z'}})
        code, out = self.lab.validate_pack(view['study_id'], derived)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['data']['stimulus']['provenance']['derived_from']['manifest_sha256'],
                         quarantined['manifest_sha256'])
        revised = self.lab.plan(self.lab.small(stimulus=dict(out['data']['stimulus'], coordinator_inspected=True)))
        self.assertNotEqual(revised['revision'], view['revision'])
        self.assertEqual(revised['approval']['state'], 'unapproved')
        self.lab.approve(revised)
        self.lab.ev_ok('disclosure', '--state-root', self.lab.root, '--study', view['study_id'], '--consumer', 'export')
        self.assertIn('quarantined', json.dumps(parent))
        # A derivative that keeps a quarantined file unchanged, or changes provenance, fails.
        bad = fixtures.manifest(files, derived_from=derived['derived_from'])
        code, out = self.lab.validate_pack(view['study_id'], bad)
        self.assertIn('derivative_unchanged', self.problems(out))

    def test_common_profile_must_match_the_plan_and_recapture_is_a_new_immutable_attempt(self):
        draft = self.lab.small()
        draft['capture_profile'] = dict(draft['capture_profile'], extra_views=['shopping list'])
        view = self.lab.plan(draft)
        self.lab.refused('pack_profile_mismatch', 'approve', '--state-root', self.lab.root, '--study', view['study_id'],
                         '--input', self.lab.approval(view))
        # A failed attempt is kept; its recapture names it and uses new files.
        files = self.files('r1-')
        Path(files[0]['path']).unlink()
        first = fixtures.manifest(files)
        code, out = self.lab.validate_pack('recapture', first)
        self.assertEqual(code, 1)
        failed_sha = out['data']['manifest_sha256']
        # The same manifest cannot be re-presented with a different verdict once files reappear.
        Path(files[0]['path']).write_bytes(fixtures.png(390, 844, ((1, 2, 3), (4, 5, 6))))
        files[0].update(sha256=sha(Path(files[0]['path']).read_bytes()))
        code, out = self.lab.validate_pack('recapture', fixtures.manifest(files, attempt={'number': 1,
                                                                                 'previous_manifest_sha256': None}))
        self.assertIn('artifact_overwritten', self.problems(out))
        renamed = self.files('r2-')
        code, out = self.lab.validate_pack('recapture', fixtures.manifest(renamed, attempt={
            'number': 2, 'previous_manifest_sha256': failed_sha}))
        self.assertEqual(code, 0, out)
        code, out = self.lab.validate_pack('recapture', fixtures.manifest(self.files('r3-'), attempt={
            'number': 5, 'previous_manifest_sha256': failed_sha}))
        self.assertIn('attempt_chain_invalid', self.problems(out))
        packs = list((self.lab.root / 'recapture' / 'focus-group' / 'evidence' / 'packs').glob('*.json'))
        self.assertGreaterEqual(len(packs), 4)

    def test_page_text_is_scanned_whole_and_a_non_png_view_never_clears(self):
        # A marker after a long clean prefix is still found: no unscanned tail is cleared.
        text = fixtures.PAGE_TEXT + 'Fresh herbs keep longer in a jar of water. ' * 8000 + f'api_key={SYNTHETIC_MARKER}\n'
        files = fixtures.write_pack(self.lab.base / 'long-text', text=text)
        self.assertGreater(len(text), 256 * 1024)
        code, out = self.lab.validate_pack('long-text', fixtures.manifest(files))
        self.assertEqual((code, out['error']['code']), (1, 'pack_quarantined'), out)
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        # v1 reads PNG only, so another image format's metadata is never silently cleared.
        files = self.files('gif-')
        data = b'GIF89a' + b'\0' * 32
        Path(files[1]['path']).write_bytes(data)
        files[1].update(sha256=sha(data), bytes=len(data), media_type='image/gif')
        code, out = self.lab.validate_pack('gif-view', fixtures.manifest(files))
        self.assertEqual((code, out['error']['code']), (1, 'pack_failed'))
        self.assertIn('image_unreadable', self.problems(out))

    def test_png_text_is_decoded_and_unsupported_png_metadata_never_clears(self):
        # FG2-A3-1: compressed iTXt is inflated and scanned; a chunk v1 does not decode is refused.
        marker = f'api_key={SYNTHETIC_MARKER}'.encode()
        for name, chunk, code_name in (
                ('itxt', b'Comment\0\1\0\0\0' + zlib.compress(marker), 'pack_quarantined'),
                ('private', marker, 'pack_failed')):
            with self.subTest(name=name):
                files = self.files(f'{name}-')
                data = fixtures.with_chunk(Path(files[1]['path']).read_bytes(), b'iTXt' if name == 'itxt' else b'prVt',
                                           chunk)
                Path(files[1]['path']).write_bytes(data)
                files[1].update(sha256=sha(data), bytes=len(data))
                code, out = self.lab.validate_pack(f'{name}-view', fixtures.manifest(files))
                self.assertEqual((code, out['error']['code']), (1, code_name), out)
                if name == 'private':
                    self.assertIn('image_unsupported', self.problems(out))
                self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)

    def test_dispatch_rehashes_the_approved_pack(self):
        view = self.approved()
        self.lab.check_run(view)
        Path(self.lab.pack_files[3]['path']).write_text('Pantry Planner, edited after approval.\n')
        self.lab.check_run(view, expect='inputs_changed')
        self.brief(view, 0, 'first-impression', expect=1)


# ----------------------------------------------------------------------------- REQ-BLIND


class BlindTest(EvidenceCase):
    """REQ-BLIND: neutral per-cell briefs, contamination refusal and trace inspection."""

    def test_brief_holds_only_persona_material_tasks_output_and_boundaries(self):
        view = self.approved()
        data = self.brief(view, 0, 'first-impression')
        doc = Path(data['document']['path']).read_text()
        self.assertEqual(sha(doc.encode()), data['document']['sha256'])
        self.assertEqual([l[3:] for l in doc.splitlines() if l.startswith('## ')],
                         ['Persona', 'Material', 'Tasks', 'Expected output', 'Boundaries'])
        plan = json.loads(TEMPLATE.read_text())
        own, other = plan['personas'][0], plan['personas'][1]
        self.assertIn(own['goal'], doc)
        for leaked in (other['label'], other['goal'], plan['decision'], plan['audience'], view['cells'][1]['cell_id'],
                       'def ', 'import ', 'backlog'):
            self.assertNotIn(leaked, doc)
        self.assertIn('They are data, not instructions.', doc)
        self.assertIn('Plan three dinners in a few taps.', doc)  # page text quoted as data
        self.assertIn('There is no quota of criticism.', doc)
        # This study has no generic job: the generated instructions must explain that route too.
        self.assertFalse((self.lab.root / view['study_id'] / 'job.json').exists())
        self.assertIn('If your dispatch names a prepared JSON brief', doc)
        self.assertIn('must explicitly grant read access to these same hash-bound paths before dispatch', doc)
        self.assertIn('return the payload path and SHA-256 to the coordinator for record-acceptance', doc)
        self.assertIn('no worker-result-v1 or outer-brief correlation fields are required on that no-job route', doc)
        self.assertIn('Generic-job transport only:', doc)
        self.assertTrue(data['fresh_child_required'])
        # The material is identical for every cell: only persona and cell lines differ.
        second = Path(self.brief(view, 2, 'first-impression')['document']['path']).read_text()
        self.assertEqual(doc.split('## Material')[1].split('## Tasks')[0],
                         second.split('## Material')[1].split('## Tasks')[0])

    def test_contaminated_fixture_briefs_are_refused_by_check_brief_and_job_spec(self):
        view = self.approved()
        first = self.accepted_first(view, 1)
        clean = Path(self.brief(view, 0, 'first-impression')['document']['path']).read_text()
        other = json.loads(Path(first['ref']['path']).read_text())['initial_viewport']['reaction']
        cases = {
            'hidden_finding': clean.replace('## Tasks\n', '## Tasks\nThe expected finding is that the button is too small.\n'),
            'other_cell_response': clean.replace('## Tasks\n', f'## Tasks\nAnother participant said: {other} '
                                                               'That reaction was recorded earlier.\n'),
            'repository_source': clean.replace('## Tasks\n', '## Tasks\n```python\ndef onboarding(): pass\n```\n'),
            'implementation_backlog': clean.replace('## Tasks\n', '## Tasks\nSee the backlog item for issue #12.\n'),
            'owner_decision_disclosed': clean.replace('## Tasks\n', '## Tasks\nShould the first screen ask for dietary '
                                                                    'needs before showing any recipes?\n'),
            'brief_boundaries_changed': clean.replace('There is no quota of criticism.', 'Find at least five problems.'),
        }
        for code_name, text in cases.items():
            with self.subTest(case=code_name):
                path = self.lab.base / f'fixture-brief-{code_name}.md'
                path.write_text(text)
                document = {'path': str(path), 'sha256': sha(path.read_bytes())}
                code, out = self.lab.ev(*self.lab.study_args(view['study_id'], 'check-brief', {
                    'revision': view['revision'], 'cell_id': view['cells'][0]['cell_id'], 'stage': 'first-impression',
                    'document': document}))
                self.assertEqual((code, out['error']['code']), (1, 'brief_contaminated'), out)
                self.assertIn(code_name, {p['code'] for p in out['data']['problems']})
        # The generator's own brief passes the same lint.
        path = self.lab.base / 'clean.md'
        path.write_text(clean)
        out = self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'check-brief', {
            'revision': view['revision'], 'cell_id': view['cells'][0]['cell_id'], 'stage': 'first-impression',
            'document': {'path': str(path), 'sha256': sha(path.read_bytes())}}))
        self.assertIn('not sandbox enforcement', out['note'])
        # job-spec takes only recorded generator briefs, so an edited copy is refused even if it lints clean.
        docs = {'fi-01': {'path': str(path), 'sha256': sha(path.read_bytes())}}
        self.lab.refused('participant_brief_unrecorded', 'job-spec', '--state-root', self.lab.root, '--study',
                         view['study_id'], '--installation-id', 'fixture', '--defer-journeys', '--documents',
                         self.lab.write('docs.json', docs), '--capabilities', self.lab.catalog(), now=BEFORE)

    def test_trace_inspection_reports_unverified_without_a_trace_and_refuses_contamination(self):
        view = self.approved()
        brief = self.brief(view, 0, 'first-impression')['document']
        cell = view['cells'][0]['cell_id']
        self.assertEqual(self.lab.admit(view, 'fi-01-r0', 'first-impression', cell)[0], 0)
        base = {'revision': view['revision'], 'cell_id': cell, 'stage': 'first-impression', 'task_id': 'fi-01',
                'request_id': 'fi-01-r0', 'host_task_id': 'host-task-1', 'brief': brief, 'first_host_task_id': None}
        out = self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'inspect-trace', dict(base, trace=None)))
        self.assertEqual((out['compliance'], out['attempt_compliance']), ('unverified', 'unverified'))
        self.assertIn('not enforced by any sandbox', out['note'])
        trace = {'source': 'fixture host trace', 'events': [{'tool': 'Read', 'path': brief['path']}]}
        self.assertEqual(self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'inspect-trace', dict(base, trace=trace)))
                         ['compliance'], 'clean-in-trace')
        for event, code_name in (({'tool': 'Read', 'path': str(ROOT / 'plugins/focus-group/scripts/study.py')},
                                  'read_outside_brief'),
                                 ({'tool': 'mcp__t3-code__t3_thread_read', 'thread_id': 'other'}, 'other_context_access')):
            with self.subTest(code=code_name):
                code, out = self.lab.ev(*self.lab.study_args(view['study_id'], 'inspect-trace', dict(
                    base, trace={'source': 'fixture host trace', 'events': [event]})))
                self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'))
                self.assertEqual(out['data']['problems'][0]['code'], code_name)
        # A later clean trace of the same execution never clears what an earlier inspection found.
        code, out = self.lab.ev(*self.lab.study_args(view['study_id'], 'inspect-trace', dict(base, trace=trace)))
        self.assertEqual((code, out['data']['compliance'], out['data']['attempt_compliance']),
                         (1, 'clean-in-trace', 'contaminated'))


class TraceTest(IsolationHarness):
    """FG2-R1 and FG2-R2 through the real CLIs: a trace binds to one owned execution (admitted request,
    task, generated brief, host task and result); its scope is that brief, the approved pack and the
    task's own directory; and known contamination stops acceptance, use and disclosure of exactly that
    execution, never a distinct retry. The traces are invented fixture events, not host receipts."""

    def inspect(self, view, n, stage, task, request_id, host, brief, events=None, first_host=None, result=None):
        body = {'revision': view['revision'], 'cell_id': view['cells'][n]['cell_id'], 'stage': stage, 'task_id': task,
                'request_id': request_id, 'host_task_id': host, 'brief': brief, 'first_host_task_id': first_host,
                'trace': None if events is None else {'source': 'fixture host trace', 'events': events}}
        if result is not None:
            body['result'] = result
        return self.lab.ev(*self.lab.study_args(view['study_id'], 'inspect-trace', body))

    def disclosure(self, view, consumer='analysis'):
        return self.lab.ev('disclosure', '--state-root', self.lab.root, '--study', view['study_id'], '--consumer', consumer)

    def coverage(self, view):
        out = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        return {r['cell_id']: r for r in out['cells']}

    def test_fr1_a_contaminated_attempt_is_never_accepted_while_a_distinct_clean_retry_is(self):
        view = self.fixture_study()
        cell = view['cells'][0]['cell_id']
        doc = self.brief(view, 0, 'first-impression')['document']
        self.assertEqual(self.lab.admit(view, 'fi-01-r0', 'first-impression', cell)[0], 0)
        self.lab.release(view, 'fi-01-r0')
        a = self.write_payload(view, 'fi-01', self.first_payload(view, 0, doc['sha256']), name='attempt-a.json')
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-a', doc,
                                 [{'tool': 'Read', 'path': str(ROOT / 'plugins/focus-group/scripts/study.py')}], result=a)
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        code, out = self.record(view, 0, 'first-impression', 'fi-01', a, admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'attempt_contaminated'), out)
        attempts = self.study_dir(view, 'focus-group', 'evidence', 'attempts')
        self.assertTrue(list(attempts.glob('record-*.json')))  # the raw attempt is kept
        self.assertEqual(list(self.study_dir(view, 'focus-group', 'accepted').glob('*.json')), [])
        # A later clean inspection of the same execution does not erase what was found.
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-a', doc,
                                 [{'tool': 'Read', 'path': doc['path']}], result=a)
        self.assertEqual((code, out['data']['attempt_compliance']), (1, 'contaminated'), out)
        self.assertEqual(self.record(view, 0, 'first-impression', 'fi-01', a, admit=False)[1]['error']['code'],
                         'attempt_contaminated')
        # A distinct retry (new request, host task and bytes) is judged on its own trace.
        self.assertEqual(self.lab.admit(view, 'fi-01-r1', 'first-impression', cell, purpose='replacement')[0], 0)
        self.lab.release(view, 'fi-01-r1')
        payload = self.first_payload(view, 0, doc['sha256'])
        payload['initial_viewport']['reaction'] = 'Calm first screen, seen again for cell 0.'
        b = self.write_payload(view, 'fi-01', payload, name='attempt-b.json')
        # One host task is one execution. The contradiction is recorded and contaminates every execution it
        # names, so it is shown on another cell's request here; this cell's retry keeps its own host task.
        other_doc = self.brief(view, 1, 'first-impression')['document']
        self.assertEqual(self.lab.admit(view, 'fi-02-r0', 'first-impression', view['cells'][1]['cell_id'])[0], 0)
        code, out = self.inspect(view, 1, 'first-impression', 'fi-02', 'fi-02-r0', 'host-fi-a', other_doc, [])
        self.assertEqual((code, out['error']['code']), (1, 'trace_binding_conflict'), out)
        notes = self.task_dir(view, 'fi-01') / 'notes.txt'
        notes.write_text('scratch notes\n')
        events = [{'tool': 'Read', 'path': doc['path']}, {'tool': 'Read', 'path': str(notes)},
                  {'tool': 'view', 'path': self.lab.pack_files[0]['path']}]
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r1', 'host-fi-b', doc, events, result=b)
        self.assertEqual((code, out['data']['attempt_compliance']), (0, 'clean-in-trace'), out)
        code, out = self.record(view, 0, 'first-impression', 'fi-01', b, admit=False, request_id='fi-01-r1')
        self.assertEqual((code, out['data']['trace_compliance']), (0, 'clean-in-trace'), out)
        self.assertEqual(self.disclosure(view)[0], 0)
        row = self.coverage(view)[cell]
        self.assertEqual((row['first_impression'], row['first_trace_compliance']), ('frozen', 'clean-in-trace'))

    def test_fr1_contamination_found_after_acceptance_stops_use_and_disclosure_without_rewriting(self):
        view = self.fixture_study()
        self.isolated(view)
        first = self.accepted_first(view, 0)
        other = self.accepted_first(view, 1)
        cell, cell1 = view['cells'][0]['cell_id'], view['cells'][1]['cell_id']
        frozen = self.study_dir(view, 'focus-group', 'evidence', 'first', f'{first["record_sha256"]}.json')
        self.assertEqual(json.loads(frozen.read_text())['trace_compliance_at_acceptance'], 'unverified')
        kept = {p: p.read_bytes() for p in self.study_dir(view, 'focus-group', 'accepted').glob('*.json')}
        kept[frozen] = frozen.read_bytes()
        self.assertEqual(self.disclosure(view)[0], 0)
        self.assertEqual(self.coverage(view)[cell]['first_trace_compliance'], 'unverified')  # no trace: not clean
        # The host trace arrives after acceptance: cell 0's child read cell 1's accepted payload.
        doc = first['brief']['document']
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1', doc,
                                 [{'tool': 'Read', 'path': other['ref']['path']}], result=first['ref'])
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        self.assertEqual(out['data']['problems'][0]['code'], 'read_other_task')
        self.assertEqual(out['data']['accepted_records'], [first['record_sha256']])
        for consumer in ('participant', 'analysis', 'review', 'export'):
            with self.subTest(consumer=consumer):
                code, out = self.disclosure(view, consumer)
                self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'), out)
                self.assertEqual({(p['cell_id'], p['code']) for p in out['data']['material']},
                                 {(cell, 'trace_contaminated')})
        code, out = self.freeze(view, first['record_sha256'], first['ref'])
        self.assertEqual((code, out['error']['code']), (1, 'material_unusable'))
        self.assertEqual(self.brief(view, 0, 'journey', expect=1)['error']['code'], 'predecessor_unusable')
        code, out = self.lab.admit(view, 'jr-01-r0', 'journey', cell)
        self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'), out)
        # Cell 1 is a distinct, clean execution: its journey brief still builds.
        self.brief(view, 1, 'journey')
        rows = self.coverage(view)
        self.assertEqual((rows[cell]['first_impression'], rows[cell1]['first_impression']), ('trace-contaminated', 'frozen'))
        # The accepted raw evidence is never rewritten, and a later clean trace does not restore its use.
        self.assertEqual({p: p.read_bytes() for p in kept}, kept)
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1', doc,
                                 [{'tool': 'Read', 'path': doc['path']}])
        self.assertEqual((code, out['data']['attempt_compliance']), (1, 'contaminated'))
        self.assertEqual(self.disclosure(view)[0], 1)

    def test_fr2_a_trace_reads_only_its_brief_approved_material_and_own_task_directory(self):
        view = self.fixture_study()
        other = self.accepted_first(view, 1)  # artifacts/tasks/fi-02/payload.json now exists
        doc = self.brief(view, 0, 'first-impression')['document']
        cell = view['cells'][0]['cell_id']
        self.assertEqual(self.lab.admit(view, 'fi-01-r0', 'first-impression', cell)[0], 0)
        own = self.task_dir(view, 'fi-01')
        (own / 'notes.txt').write_text('scratch\n')
        clean = [{'tool': 'Read', 'path': doc['path']}, {'tool': 'Read', 'path': str(own / 'notes.txt')},
                 {'tool': 'ls', 'path': str(own)}] + [{'tool': 'mcp__fs__read_file', 'path': f['path']}
                                                     for f in self.lab.pack_files]
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1', doc, clean)
        self.assertEqual((code, out['data']['compliance']), (0, 'clean-in-trace'), out)
        # An inspection binds to an admitted request and the brief built for this task, or is refused.
        unbound = {'request not admitted': dict(request_id='fi-01-r9'),
                   'another cell\'s brief': dict(brief=other['brief']['document']),
                   'brief built for another task': dict(task='fi-03'),
                   'request of another stage': dict(stage='journey')}
        for name, change in unbound.items():
            with self.subTest(unbound=name):
                args = dict(stage='first-impression', task='fi-01', request_id='fi-01-r0', brief=doc) | change
                code, out = self.inspect(view, 0, args['stage'], args['task'], args['request_id'], 'host-fi-1',
                                         args['brief'], [])
                self.assertEqual((code, out['error']['code']), (1, 'trace_unbound'), out)
        # Real containment, not a string prefix: another task, '..', a sibling sharing the prefix and a
        # symlink out of the task directory are all other tasks' artifacts.
        sibling = own.parent / 'fi-01-extra'
        sibling.mkdir()
        (sibling / 'payload.json').write_text('{}')
        (own / 'link.json').symlink_to(other['ref']['path'])
        cases = {'read_other_task': [other['ref']['path'], str(own / '..' / 'fi-02' / 'payload.json'),
                                     str(sibling / 'payload.json'), str(own / 'link.json')],
                 'read_outside_brief': ['payload.json', str(ROOT / 'plugins/focus-group/scripts/study.py'),
                                        other['brief']['document']['path']]}
        for code_name, paths in cases.items():
            for path in paths:
                with self.subTest(path=path):
                    code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1', doc,
                                             [{'tool': 'Read', 'path': path}])
                    self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
                    self.assertEqual([p['code'] for p in out['data']['problems']], [code_name])

    def test_fr2_a_journey_gets_its_earlier_response_only_through_its_brief(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        first = self.accepted_first(view, 0)
        cell = view['cells'][0]['cell_id']
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1', first['brief']['document'],
                                 [{'tool': 'Read', 'path': first['brief']['document']['path']}])
        self.assertEqual(code, 0, out)
        doc = self.brief(view, 0, 'journey')['document']
        self.assertEqual(self.lab.admit(view, 'jr-01-r0', 'journey', cell)[0], 0)
        self.lab.release(view, 'jr-01-r0')
        events = [{'tool': 'Read', 'path': doc['path']},
                  {'tool': 'mcp__t3-code__preview_navigate', 'url': self.server.origin + '/recipes',
                   'context_reference': 'fixture-context-0'}]
        code, out = self.inspect(view, 0, 'journey', 'jr-01', 'jr-01-r0', 'host-jr-1', doc, events, first_host='host-fi-1')
        self.assertEqual((code, out['data']['compliance']), (0, 'clean-in-trace'), out)
        # Its own cell's accepted first impression, read from the first task's directory, is still contamination.
        code, out = self.inspect(view, 0, 'journey', 'jr-01', 'jr-01-r0', 'host-jr-1', doc,
                                 [{'tool': 'Read', 'path': first['ref']['path']}], first_host='host-fi-1')
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        self.assertEqual([p['code'] for p in out['data']['problems']], ['read_other_task'])
        ref = self.write_payload(view, 'jr-01', self.journey_payload(view, 0, doc['sha256'], bindings[0], 'jr-01'))
        context = {'class': 'fresh-anonymous', 'reference': 'fixture-context-0', 'binding_sha256': bindings[0]}
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']], context=context,
                                admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'attempt_contaminated'), out)
        self.assertEqual(self.coverage(view)[cell]['journey'], {'state': 'pending'})
        # A journey in the first impression's own host task is not a fresh child, and one host task binds
        # one execution.
        self.assertEqual(self.lab.admit(view, 'jr-01-r1', 'journey', cell, purpose='replacement')[0], 0)
        code, out = self.inspect(view, 0, 'journey', 'jr-01', 'jr-01-r1', 'host-fi-1', doc, None)
        self.assertEqual((code, [p['code'] for p in out['data']['problems']]), (1, ['not_fresh_child']), out)
        code, out = self.inspect(view, 0, 'journey', 'jr-01', 'jr-01-r1', 'host-jr-1', doc, [])
        self.assertEqual((code, out['error']['code']), (1, 'trace_binding_conflict'), out)

    # FG2-R6 to FG2-R10: execution identity, opaque events, host reuse and the current input selection.

    def brief_task(self, view, n, stage, task):
        return self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'brief', {
            'revision': view['revision'], 'cell_id': view['cells'][n]['cell_id'], 'stage': stage, 'task_id': task}))

    def admitted(self, view, n, stage, request_id, purpose='initial'):
        code, out = self.lab.admit(view, request_id, stage, view['cells'][n]['cell_id'], purpose=purpose)
        self.assertEqual(code, 0, out)
        self.lab.release(view, request_id)

    def clean_first(self, view, n, task, host, purpose='initial'):
        """Brief, admit, inspect a clean trace and accept one first impression in its own task."""
        doc = self.brief_task(view, n, 'first-impression', task)['document']
        self.admitted(view, n, 'first-impression', f'{task}-r0', purpose)
        ref = self.write_payload(view, task, self.first_payload(view, n, doc['sha256']))
        code, out = self.inspect(view, n, 'first-impression', task, f'{task}-r0', host, doc,
                                 [{'tool': 'Read', 'path': doc['path']}], result=ref)
        self.assertEqual((code, out['data']['attempt_compliance']), (0, 'clean-in-trace'), out)
        code, out = self.record(view, n, 'first-impression', task, ref, admit=False, request_id=f'{task}-r0')
        self.assertEqual((code, out['data']['trace_compliance']), (0, 'clean-in-trace'), out)
        return {'record_sha256': out['data']['record_sha256'], 'ref': ref, 'doc': doc}

    def accepted_journey(self, view, n, task, bindings, first_sha, purpose='initial'):
        doc = self.brief_task(view, n, 'journey', task)['document']
        self.admitted(view, n, 'journey', f'{task}-r0', purpose)
        ref = self.write_payload(view, task, self.journey_payload(view, n, doc['sha256'], bindings[n], task))
        context = {'class': 'fresh-anonymous', 'reference': f'fixture-context-{n}', 'binding_sha256': bindings[n]}
        code, out = self.record(view, n, 'journey', task, ref, predecessors=[first_sha], context=context, admit=False,
                                request_id=f'{task}-r0')
        self.assertEqual(code, 0, out)
        return {'record_sha256': out['data']['record_sha256'], 'ref': ref, 'via': out['data']['predecessor_records']}

    def revise(self, view):
        """A deadline-only revision of the fixture study, approved, with its carry mapping written."""
        limits = dict(json.loads(TEMPLATE.read_text())['limits'], deadline='2031-01-01T00:00:00Z')
        revised = self.lab.plan(self.lab.small(target={'kind': 'url', 'url': self.server.origin + '/welcome',
                                                       'environment': 'fixture', 'label': 'Invented loopback prototype'},
                                               limits=limits))
        self.assertNotEqual(revised['revision'], view['revision'])
        self.lab.approve(revised)
        mapping = self.lab.ok('carry', '--state-root', self.lab.root, '--study', view['study_id'], '--write')
        return revised, {(e['cell_id'], e['stage']): e for e in mapping['entries']}

    def accept_journey(self, view, journey):
        return self.lab.ev(*self.lab.study_args(view['study_id'], 'accept-journey', {
            'record_sha256': journey['record_sha256'], 'payload': journey['ref']}))

    def kept(self, view, *folders):
        return {p: p.read_bytes() for folder in folders for p in self.study_dir(view, *folder.split('/')).rglob('*')
                if p.is_file()}

    def test_fr7_a_distinct_retry_returning_identical_bytes_is_its_own_execution(self):
        view = self.fixture_study()
        cell = view['cells'][0]['cell_id']
        doc = self.brief(view, 0, 'first-impression')['document']
        self.admitted(view, 0, 'first-impression', 'fi-01-r0')
        payload = self.first_payload(view, 0, doc['sha256'])
        a = self.write_payload(view, 'fi-01', payload, name='attempt-a.json')
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-a', doc,
                                 [{'tool': 'Read', 'path': str(ROOT / 'plugins/focus-group/scripts/study.py')}], result=a)
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        self.assertEqual(self.record(view, 0, 'first-impression', 'fi-01', a, admit=False)[1]['error']['code'],
                         'attempt_contaminated')
        # A new request in a new host task independently returns the same bytes, at another path.
        self.admitted(view, 0, 'first-impression', 'fi-01-r1', 'replacement')
        b = self.write_payload(view, 'fi-01', payload, name='attempt-b.json')
        self.assertEqual(a['sha256'], b['sha256'])
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r1', 'host-fi-b', doc,
                                 [{'tool': 'Read', 'path': doc['path']}], result=b)
        self.assertEqual((code, out['data']['attempt_compliance'], out['data']['inspections']),
                         (0, 'clean-in-trace', 1), out)
        code, out = self.record(view, 0, 'first-impression', 'fi-01', b, admit=False, request_id='fi-01-r1')
        self.assertEqual((code, out['data']['trace_compliance']), (0, 'clean-in-trace'), out)
        # The contaminated execution is unchanged and still refused, whatever bytes it returned.
        self.assertEqual(self.record(view, 0, 'first-impression', 'fi-01', a, admit=False)[1]['error']['code'],
                         'attempt_contaminated')
        self.assertEqual(self.disclosure(view)[0], 0)
        self.assertEqual(self.coverage(view)[cell]['first_trace_compliance'], 'clean-in-trace')
        # Inside one execution the result is a consistency binding: another result for it is a contradiction.
        changed = dict(payload, initial_viewport=dict(payload['initial_viewport'], reaction='Another answer.'))
        c = self.write_payload(view, 'fi-01', changed, name='attempt-c.json')
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r1', 'host-fi-b', doc, [], result=c)
        self.assertEqual((code, out['error']['code'], out['data']['conflicts']),
                         (1, 'trace_binding_conflict', [{'code': 'result_rebound', 'request_id': 'fi-01-r1'}]), out)
        self.assertEqual(self.disclosure(view)[0], 1)

    def test_fr8_ordinary_shell_and_unknown_tool_events_are_inspected_and_never_certified_clean(self):
        view = self.fixture_study()
        other = self.accepted_first(view, 1)['ref']['path']  # cell 1's accepted payload
        # FG-3: cell 2 waits for model A's pilot (cell 0), so the limit cases use cell 3, whose model B pilot
        # (cell 1) is accepted, and the clean control is cell 0's own distinct retry.
        docs = {n: self.brief(view, n, 'first-impression')['document'] for n in (0, 3)}
        for n in (0, 3):
            self.admitted(view, n, 'first-impression', f'fi-{n + 1:02d}-r0')
        # The reviewer's case: an ordinary exec_command event names another cell's payload.
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-1', docs[0],
                                 [{'tool': 'exec_command', 'path': other, 'cmd': f'cat {other}'}])
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        self.assertEqual([p['code'] for p in out['data']['problems']], ['read_other_task'])
        ref = self.write_payload(view, 'fi-01', self.first_payload(view, 0, docs[0]['sha256']))
        self.assertEqual(self.record(view, 0, 'first-impression', 'fi-01', ref, admit=False)[1]['error']['code'],
                         'attempt_contaminated')
        # Without a path field, a study path the command names is still checked; the command is never run.
        accepted_dir = str(self.study_dir(view, 'focus-group', 'accepted'))
        for event, code_name in (({'tool': 'Bash', 'command': f"cat '{other}' | head -n 1"}, 'read_other_task'),
                                 ({'tool': 'exec_command', 'cmd': ['ls', '-l', accepted_dir]}, 'read_outside_brief')):
            with self.subTest(event=event['tool']):
                code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-1', docs[0], [event])
                self.assertEqual((code, out['data']['compliance']), (1, 'contaminated'), out)
                self.assertEqual([p['code'] for p in out['data']['problems']], [code_name])
        # Opaque commands and unknown tools are limits: unverified, never clean, even when nothing they name
        # is outside the task's scope.
        own = self.task_dir(view, 'fi-04')
        (own / 'notes.txt').write_text('scratch\n')
        cases = {'opaque_event': [{'tool': 'exec_command', 'cmd': f'cat {own}/notes.txt'}],
                 'opaque_event ': [{'tool': 'Bash', 'command': 'date 2>/dev/null'}],
                 'unsupported_event': [{'tool': 'mcp__web__fetch_page', 'url': 'https://example.invalid/'}],
                 'unscoped_file_access': [{'tool': 'grep', 'pattern': 'dinner'}]}
        for limit, events in cases.items():
            with self.subTest(limit=limit):
                code, out = self.inspect(view, 3, 'first-impression', 'fi-04', 'fi-04-r0', 'host-4', docs[3], events)
                self.assertEqual((code, out['data']['compliance'], out['data']['problems']), (0, 'unverified', []), out)
                self.assertEqual([x['code'] for x in out['data']['limits']], [limit.strip()])
        code, out = self.inspect(view, 3, 'first-impression', 'fi-04', 'fi-04-r0', 'host-4', docs[3],
                                 [{'tool': 'Read', 'path': docs[3]['path']}])
        self.assertEqual((code, out['data']['compliance'], out['data']['attempt_compliance']),
                         (0, 'clean-in-trace', 'unverified'), out)
        ref4 = self.write_payload(view, 'fi-04', self.first_payload(view, 3, docs[3]['sha256']))
        code, out = self.record(view, 3, 'first-impression', 'fi-04', ref4, admit=False)
        self.assertEqual((code, out['data']['trace_compliance']), (0, 'unverified'), out)
        # Control: recognised file tools on the brief, the pack and the task's own files are clean, here in
        # a distinct retry of cell 0 in its own host task.
        self.admitted(view, 0, 'first-impression', 'fi-01-r1', 'replacement')
        own = self.task_dir(view, 'fi-01')
        events = [{'tool': 'Read', 'path': docs[0]['path']}, {'tool': 'Write', 'file_path': str(own / 'notes.txt')},
                  {'tool': 'mcp__fs__read_file', 'path': self.lab.pack_files[0]['path']}]
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r1', 'host-5', docs[0], events)
        self.assertEqual((code, out['data']['compliance'], out['data']['limits']), (0, 'clean-in-trace', []), out)
        code, out = self.record(view, 0, 'first-impression', 'fi-01', ref, admit=False, request_id='fi-01-r1')
        self.assertEqual((code, out['data']['trace_compliance']), (0, 'clean-in-trace'), out)
        rows = self.coverage(view)
        self.assertEqual([rows[view['cells'][n]['cell_id']]['first_trace_compliance'] for n in (3, 0)],
                         ['unverified', 'clean-in-trace'])

    def test_fr9_one_host_task_reported_for_two_cells_contaminates_both_executions(self):
        view = self.fixture_study()
        cells = [c['cell_id'] for c in view['cells']]
        first = self.clean_first(view, 0, 'fi-01', 'host-shared')
        kept = self.kept(view, 'focus-group/accepted', 'focus-group/evidence/traces', 'focus-group/evidence/first')
        doc = self.brief(view, 1, 'first-impression')['document']
        self.admitted(view, 1, 'first-impression', 'fi-02-r0')
        ref = self.write_payload(view, 'fi-02', self.first_payload(view, 1, doc['sha256']))
        code, out = self.inspect(view, 1, 'first-impression', 'fi-02', 'fi-02-r0', 'host-shared', doc,
                                 [{'tool': 'Read', 'path': doc['path']}], result=ref)
        self.assertEqual((code, out['error']['code']), (1, 'trace_binding_conflict'), out)
        self.assertEqual((out['data']['contaminated_requests'], out['data']['accepted_records']),
                         (['fi-01-r0', 'fi-02-r0'], [first['record_sha256']]))
        # Neither execution is independent evidence: the new one is refused, the accepted one stops being used.
        self.assertEqual(self.record(view, 1, 'first-impression', 'fi-02', ref, admit=False)[1]['error']['code'],
                         'attempt_contaminated')
        code, out = self.freeze(view, first['record_sha256'], first['ref'])
        self.assertEqual((code, out['error']['code']), (1, 'material_unusable'), out)
        self.assertEqual(self.coverage(view)[cells[0]]['first_impression'], 'trace-contaminated')
        code, out = self.disclosure(view, 'export')
        self.assertEqual({(p['cell_id'], p['code']) for p in out['data']['material']}, {(cells[0], 'trace_contaminated')})
        # Nothing earlier is rewritten, and a later clean inspection does not restore it.
        self.assertEqual({p: p.read_bytes() for p in kept}, kept)
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-shared', first['doc'],
                                 [{'tool': 'Read', 'path': first['doc']['path']}])
        self.assertEqual((code, out['data']['attempt_compliance']), (1, 'contaminated'), out)
        # FG-3: model A's pilot (cell 0) is now unusable, so its other cells wait for a passing pilot.
        self.assertEqual(self.lab.admit(view, 'fi-03-r0', 'first-impression', cells[2])[1]['error']['code'], 'pilot_failed')
        # Control: a distinct host task is a distinct, clean execution (cell 1's own retry).
        doc = self.brief_task(view, 1, 'first-impression', 'fi-02')['document']
        self.admitted(view, 1, 'first-impression', 'fi-02-r1', 'replacement')
        code, out = self.inspect(view, 1, 'first-impression', 'fi-02', 'fi-02-r1', 'host-distinct', doc,
                                 [{'tool': 'Read', 'path': doc['path']}])
        self.assertEqual((code, out['data']['attempt_compliance']), (0, 'clean-in-trace'), out)
        code, out = self.record(view, 1, 'first-impression', 'fi-02', ref, admit=False, request_id='fi-02-r1')
        self.assertEqual((code, out['data']['trace_compliance']), (0, 'clean-in-trace'), out)
        self.assertEqual(self.coverage(view)[cells[1]]['first_trace_compliance'], 'clean-in-trace')

    def test_fr10_a_journey_on_a_first_impression_found_contaminated_later_is_unusable_until_a_new_revision(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        cells = [c['cell_id'] for c in view['cells']]
        firsts = {n: self.accepted_first(view, n) for n in (0, 1)}
        journeys = {n: self.accepted_journey(view, n, f'jr-{n + 1:02d}', bindings, firsts[n]['ref']['sha256'])
                    for n in (0, 1)}
        self.assertEqual(self.coverage(view)[cells[0]]['journey']['state'], 'hands-on-evidence')
        kept = self.kept(view, 'focus-group/accepted', 'focus-group/evidence/first', 'focus-group/evidence/journeys',
                         'artifacts')
        charged = self.lab.status(view)['charged']
        # Cell 0's first-impression trace arrives after both of its records were accepted.
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1',
                                 firsts[0]['brief']['document'], [{'tool': 'Read', 'path': firsts[1]['ref']['path']}],
                                 result=firsts[0]['ref'])
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        rows = {r['cell_id']: r for r in coverage['cells']}
        self.assertEqual((rows[cells[0]]['first_impression'], rows[cells[0]]['journey']['state'],
                          rows[cells[0]]['journey']['problem']),
                         ('trace-contaminated', 'predecessor-unusable', 'predecessor_unusable'))
        self.assertEqual((rows[cells[1]]['first_impression'], rows[cells[1]]['journey']['state']),
                         ('frozen', 'hands-on-evidence'))
        self.assertEqual((coverage['journey_gaps'], coverage['combined_scope_complete']), (1, False))
        code, out = self.accept_journey(view, journeys[0])
        self.assertEqual((code, out['error']['code']), (1, 'material_unusable'), out)
        self.assertEqual([p['code'] for p in out['data']['problems']], ['predecessor_unusable'])
        self.assertEqual(self.accept_journey(view, journeys[1])[0], 0)  # the unrelated clean cell is unaffected
        for consumer in ('participant', 'analysis', 'review', 'export'):
            code, out = self.disclosure(view, consumer)
            self.assertEqual({(p['cell_id'], p['code']) for p in out['data']['material']},
                             {(cells[0], 'trace_contaminated'), (cells[0], 'predecessor_unusable')})
        # The raw records, artifacts and charges are retained exactly.
        self.assertEqual(({p: p.read_bytes() for p in kept}, self.lab.status(view)['charged']), (kept, charged))
        # Recovery: a new revision stales the pair, carries the clean cell and reruns cell 0 on its new first.
        revised, entries = self.revise(view)
        self.assertEqual([entries[(c, s)]['status'] for c in cells[:2] for s in ('first-impression', 'journey')],
                         ['stale', 'stale', 'carried', 'carried'])
        fresh = self.isolated(revised, (0, 1))
        first = self.clean_first(revised, 0, 'fi-new', 'host-fi-new', 'repair')
        journey = self.accepted_journey(revised, 0, 'jr-new', fresh, first['ref']['sha256'], 'repair')
        self.assertEqual([(s['record_sha256'], s['via']) for s in journey['via']], [(first['record_sha256'], 'native')])
        rows = self.coverage(revised)
        self.assertEqual([(rows[c]['first_via'], rows[c]['journey']['state'], rows[c]['journey_via']) for c in cells[:2]],
                         [('native', 'hands-on-evidence', 'native'), ('carry', 'hands-on-evidence', 'carry')])
        self.assertEqual((self.accept_journey(revised, journey)[0], self.accept_journey(revised, journeys[1])[0]), (0, 0))
        code, out = self.disclosure(revised, 'export')
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out['data']['selected_records']),
                         {first['record_sha256'], journey['record_sha256'], firsts[1]['record_sha256'],
                          journeys[1]['record_sha256']})
        self.assertEqual({p: p.read_bytes() for p in kept}, kept)

    def test_fr6_a_clean_replacement_in_a_new_revision_is_disclosed_without_the_excluded_history(self):
        view = self.fixture_study()
        cells = [c['cell_id'] for c in view['cells']]
        firsts = {n: self.accepted_first(view, n) for n in (0, 1)}
        code, out = self.inspect(view, 0, 'first-impression', 'fi-01', 'fi-01-r0', 'host-fi-1',
                                 firsts[0]['brief']['document'],
                                 [{'tool': 'Read', 'path': str(ROOT / 'plugins/focus-group/scripts/study.py')}])
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        self.assertEqual(self.disclosure(view, 'export')[0], 1)
        kept = self.kept(view, 'focus-group/accepted', 'focus-group/evidence', 'artifacts/tasks/fi-01')
        revised, entries = self.revise(view)
        self.assertEqual((entries[(cells[0], 'first-impression')]['status'], entries[(cells[1], 'first-impression')]['status']),
                         ('stale', 'carried'))
        self.assertIn('contaminated', ' '.join(entries[(cells[0], 'first-impression')]['reasons']))
        new = self.clean_first(revised, 0, 'fi-new', 'host-fi-new', 'repair')
        for consumer in ('participant', 'analysis', 'review', 'export'):
            with self.subTest(consumer=consumer):
                code, out = self.disclosure(revised, consumer)
                self.assertEqual((code, out['data']['permitted']), (0, True), out)
                self.assertEqual(set(out['data']['selected_records']),
                                 {new['record_sha256'], firsts[1]['record_sha256']})
                self.assertEqual(out['data']['excluded_history_records'], 1)
        rows = self.coverage(revised)
        self.assertEqual([(rows[c]['first_impression'], rows[c]['first_via'], rows[c]['first_trace_compliance'])
                          for c in cells[:2]], [('frozen', 'native', 'clean-in-trace'), ('frozen', 'carry', 'unverified')])
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        self.assertIsNot(coverage['combined_scope_complete'], True)  # journeys are still pending
        # The excluded history is retained exactly, never disclosed or rewritten.
        for path, data in kept.items():
            self.assertEqual(path.read_bytes(), data)
        # Selected evidence that becomes unusable still holds: the carried first impression is found contaminated.
        code, out = self.inspect(view, 1, 'first-impression', 'fi-02', 'fi-02-r0', 'host-fi-2',
                                 firsts[1]['brief']['document'], [{'tool': 'Read', 'path': firsts[0]['ref']['path']}])
        self.assertEqual((code, out['error']['code']), (1, 'contaminated_attempt'), out)
        code, out = self.disclosure(revised, 'export')
        self.assertEqual((code, [p['code'] for p in out['data']['material']]), (1, ['carry_invalid']), out)

    def test_fr6_material_drift_and_quarantine_recover_through_a_replacement_without_old_history(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        cell = view['cells'][0]['cell_id']
        first = self.accepted_first(view, 0)
        old = self.accepted_journey(view, 0, 'jr-01', bindings, first['ref']['sha256'])
        # A leaky attempt is quarantined and retained; it was never accepted.
        leaky = self.journey_payload(view, 0, self.brief_task(view, 0, 'journey', 'jr-01')['document']['sha256'],
                                     bindings[0], 'jr-01')
        leaky['goals'][0]['observed_events'].append(f'the page printed Authorization: Bearer {SYNTHETIC_MARKER}')
        code, out = self.check(view, 0, 'journey', 'jr-01', self.write_payload(view, 'jr-01', leaky, 'leaky.json'))
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        # The accepted journey's screenshot drifts after acceptance.
        shot = self.task_dir(view, 'jr-01') / 'live-step-1.png'
        shot.write_bytes(fixtures.png(390, 844, ((0, 0, 0), (200, 10, 10), (255, 255, 255))))
        code, out = self.disclosure(view, 'export')
        self.assertEqual({(p['cell_id'], p['code']) for p in out['data']['material']}, {(cell, 'hash_mismatch')})
        self.assertEqual(self.accept_journey(view, old)[1]['error']['code'], 'material_unusable')
        self.assertEqual(self.coverage(view)[cell]['journey']['state'], 'unusable')
        kept = self.kept(view, 'focus-group/accepted', 'artifacts/tasks/jr-01')
        revised, entries = self.revise(view)
        self.assertEqual((entries[(cell, 'first-impression')]['status'], entries[(cell, 'journey')]['status']),
                         ('carried', 'stale'))
        self.assertIn('live-step-1.png', ' '.join(entries[(cell, 'journey')]['reasons']))
        fresh = self.isolated(revised, (0, 1))
        new = self.accepted_journey(revised, 0, 'jr-new', fresh, first['ref']['sha256'], 'repair')
        self.assertEqual([(s['record_sha256'], s['via']) for s in new['via']], [(first['record_sha256'], 'carry')])
        code, out = self.disclosure(revised, 'export')
        self.assertEqual(code, 0, out)
        self.assertEqual((set(out['data']['selected_records']), out['data']['quarantined']),
                         ({first['record_sha256'], new['record_sha256']}, []))
        self.assertGreaterEqual(out['data']['retained_quarantine'], 1)
        row = self.coverage(revised)[cell]
        self.assertEqual((row['first_via'], row['journey']['state'], row['journey_via']),
                         ('carry', 'hands-on-evidence', 'native'))
        # Selected current evidence still blocks: the replacement's own screenshot drifts, then is restored.
        new_shot = self.task_dir(revised, 'jr-new') / 'live-step-1.png'
        saved = new_shot.read_bytes()
        new_shot.write_bytes(shot.read_bytes())
        code, out = self.disclosure(revised, 'export')
        self.assertEqual((code, [(p['record_sha256'], p['code']) for p in out['data']['material']]),
                         (1, [(new['record_sha256'], 'hash_mismatch')]))
        new_shot.write_bytes(saved)
        self.assertEqual(self.disclosure(revised, 'export')[0], 0)
        self.assertEqual({p: p.read_bytes() for p in kept}, kept)


# ----------------------------------------------------------------------------- REQ-FIRST-IMPRESSION


class FirstImpressionTest(IsolationHarness):
    """REQ-FIRST-IMPRESSION: accepted, hashed and frozen before any journey brief."""

    def test_journey_brief_waits_for_the_cells_own_accepted_frozen_first_impression(self):
        view = self.fixture_study()
        self.isolated(view)
        attempts = self.lab.root / view['study_id'] / 'focus-group' / 'evidence' / 'attempts'
        out = self.brief(view, 0, 'journey', expect=1)
        self.assertEqual(out['error']['code'], 'first_impression_missing')
        self.assertEqual(len(list(attempts.glob('brief-*.json'))), 1)  # the raw attempt is kept
        # Another cell's accepted first impression never substitutes for this cell's.
        self.accepted_first(view, 1)
        self.assertEqual(self.brief(view, 0, 'journey', expect=1)['error']['code'], 'first_impression_missing')
        # record-acceptance freezes the first impression it ingests; without that frozen record (removed
        # here to simulate tampering) no journey brief is built from anything else.
        brief = self.brief(view, 0, 'first-impression')
        ref = self.write_payload(view, 'fi-01', self.first_payload(view, 0, brief['document']['sha256']))
        code, out = self.record(view, 0, 'first-impression', 'fi-01', ref)
        self.assertEqual(code, 0, out)
        record_sha = out['data']['record_sha256']
        frozen = self.study_dir(view, 'focus-group', 'evidence', 'first', f'{record_sha}.json')
        self.assertEqual(json.loads(frozen.read_text())['payload'], ref)
        saved = frozen.read_bytes()
        frozen.unlink()
        self.assertEqual(self.brief(view, 0, 'journey', expect=1)['error']['code'], 'first_impression_unfrozen')
        frozen.write_bytes(saved)
        self.assertEqual(self.freeze(view, record_sha, ref)[0], 0)
        journey = self.brief(view, 0, 'journey')
        self.assertEqual(journey['inputs']['predecessor_record_sha256'], record_sha)
        doc = Path(journey['document']['path']).read_text()
        self.assertIn('Calm first screen for cell 0.', doc)       # its own earlier response
        self.assertNotIn('Calm first screen for cell 1.', doc)    # never another cell's
        # A foreign-cell predecessor is refused at acceptance too.
        foreign = sha(Path(self.lab.root / view['study_id'] / 'artifacts/tasks/fi-02/payload.json').read_bytes())
        journey_ref = self.write_payload(view, 'jr-01', {'fixture': 'journey result'})
        code, out = self.record(view, 0, 'journey', 'jr-01', journey_ref, predecessors=[foreign],
                                context={'class': 'fresh-anonymous', 'reference': 'fixture-context-0',
                                         'binding_sha256': '0' * 64})
        self.assertEqual((code, out['error']['code']), (1, 'foreign_predecessor'))

    def test_changed_predecessor_and_later_responses_never_replace_the_frozen_first_impression(self):
        view = self.fixture_study()
        self.isolated(view)
        first = self.accepted_first(view, 0)
        # A later, different response for the same accepted record is refused and retained.
        later = self.write_payload(view, 'fi-01', self.first_payload(view, 0, first['brief']['document']['sha256'],
                                                                     claims=[]), name='later.json')
        code, out = self.freeze(view, first['record_sha256'], later)
        self.assertEqual((code, out['error']['code']), (1, 'payload_not_accepted'))
        self.assertEqual(self.freeze(view, first['record_sha256'], first['ref'])[1]['data']['duplicate'], True)
        # Changing the frozen payload's bytes makes it unusable for a journey brief.
        Path(first['ref']['path']).write_text('{"rewritten": true}')
        out = self.brief(view, 0, 'journey', expect=1)
        self.assertIn(out['error']['code'], ('predecessor_unusable', 'predecessor_changed'))

    def test_visual_claims_need_a_verified_image_basis_and_the_initial_viewport_stays_separate(self):
        view = self.approved()
        brief = self.brief(view, 0, 'first-impression')['document']['sha256']
        cases = {
            'visual_claim_text_only': (self.first_payload(view, 0, brief, image_use={'saw_images': False,
                                                                                     'basis': 'text-only'}), None),
            'image_basis_unverified': (self.first_payload(view, 0, brief),
                                       {'state': 'not-delivered', 'source': 'fixture: attachments unsupported'}),
            'initial_viewport_separate': (self.first_payload(view, 0, brief, initial_viewport={
                'file': 'shopping-list.png', 'reaction': 'x', 'observed': [], 'inferred': []}), None),
            'payload_shape': (dict(self.first_payload(view, 0, brief), live_events=['clicked']), None),
        }
        for n, (code_name, (payload, delivery)) in enumerate(cases.items()):
            with self.subTest(case=code_name):
                ref = self.write_payload(view, 'fi-01', payload, name=f'case-{n}.json')
                code, out = self.check(view, 0, 'first-impression', 'fi-01', ref, delivery)
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertIn(code_name, {p['code'] for p in out['data']['problems']})
        # Text-only with textual claims is a valid, honestly limited first impression.
        payload = self.first_payload(view, 0, brief, image_use={'saw_images': False, 'basis': 'text-only'},
                                     claims=[{'id': 'c2', 'kind': 'textual', 'statement': 'It promises a few taps.',
                                              'files': ['welcome.txt']}])
        ref = self.write_payload(view, 'fi-01', payload)
        delivery = {'state': 'unknown', 'source': 'fixture: no delivery receipt'}
        self.assertEqual(self.check(view, 0, 'first-impression', 'fi-01', ref, delivery)[0], 0)
        code, out = self.record(view, 0, 'first-impression', 'fi-01', ref, delivery=delivery)
        self.assertEqual(code, 0, out)
        frozen = self.freeze(view, out['data']['record_sha256'], ref, delivery)[1]['data']
        # The delivery evidence is the one recorded on ingestion; different evidence is refused.
        code, out = self.freeze(view, out['data']['record_sha256'], ref)
        self.assertEqual((code, out['error']['code']), (1, 'image_delivery_mismatch'))
        self.assertFalse(frozen['visual_claims_supported'])
        self.assertIn('not a measured human five-second test', frozen['label'])
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        row = coverage['cells'][0]
        self.assertEqual((row['first_impression'], row['visual_claims_supported']), ('frozen', False))


# ----------------------------------------------------------------------------- REQ-ISOLATION


class IsolationTest(IsolationHarness):
    """REQ-ISOLATION: host mechanism selection, distinct verified contexts and the loopback probe."""

    def test_mechanism_prefers_preview_tools_and_never_accepts_an_unverified_native_browser(self):
        out = self.lab.ev_ok('select-mechanism', '--input', self.lab.write('preview.json', PREVIEW))
        self.assertEqual(out['mechanism']['kind'], 't3-preview')
        native = child_tools('mcp__claude-in-chrome__navigate', 'mcp__claude-in-chrome__read_page')
        code, out = self.lab.ev('select-mechanism', '--input', self.lab.write('native.json', native))
        self.assertEqual((code, out['error']['code'], out['data']['relay']), (1, 'journey_unavailable', 'prohibited'))
        verified = child_tools('browser_navigate', native={'cell_bound_state': 'verified', 'profile': 'isolated',
                                                           'source': 'fixture host isolation receipt'})
        self.assertEqual(self.lab.ev_ok('select-mechanism', '--input', self.lab.write('verified.json', verified))
                         ['mechanism']['kind'], 'provider-native')
        code, out = self.lab.ev('select-mechanism', '--input', self.lab.write('none.json', child_tools('Read', 'Write')))
        self.assertEqual(out['error']['code'], 'journey_unavailable')

    def test_loopback_probe_isolates_two_contexts_and_a_shared_profile_tab_fails(self):
        view = self.fixture_study()
        probe = self.probe(view, (0, 1))
        a, b = view['cells'][0]['cell_id'], view['cells'][1]['cell_id']
        readings = self.run_probe(view, probe, {a: FakeContext(self.server), b: FakeContext(self.server)})
        # Conflicting values under one key: each cell still reads its own, and neither sees the other's key.
        self.assertNotEqual(readings[a]['shared']['cookie'], readings[b]['shared']['cookie'])
        code, out = self.bind(view, 0, probe, readings)
        self.assertEqual(code, 0, out)
        self.assertEqual((out['data']['state'], out['data']['live_isolation_claim']), ('verified', False))
        # A new tab in the same profile shares cookies and localStorage (not sessionStorage).
        profile = FakeContext(self.server)
        probe = self.probe(view, (2, 3))
        c, d = view['cells'][2]['cell_id'], view['cells'][3]['cell_id']
        readings = self.run_probe(view, probe, {c: profile, d: FakeContext(self.server, shared=profile)})
        code, out = self.bind(view, 2, probe, readings, reference='shared-tab-2', boundary='isolated-context')
        self.assertEqual((code, out['error']['code']), (1, 'journey_unavailable'))
        detail = next(p['detail'] for p in out['data']['problems'] if p['code'] == 'isolation_failed')
        self.assertIn('cookie', detail)
        self.assertIn('local', detail)
        self.assertNotIn('session under the shared key', detail)
        code, out = self.bind(view, 3, probe, readings, reference='shared-tab-3', boundary='shared-profile-tab')
        self.assertIn('shared_profile_not_isolation', {p['code'] for p in out['data']['problems']})
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        rows = {r['cell_id']: r for r in coverage['cells']}
        self.assertEqual(rows[c]['journey']['state'], 'gap')
        self.assertEqual(rows[c]['capture'], 'cleared')
        self.assertIs(coverage['combined_scope_complete'], False)

    def test_reused_unverified_cleared_or_fixture_for_real_target_contexts_are_refused(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        probe = self.probe(view, (2, 3))
        ids = [view['cells'][n]['cell_id'] for n in (2, 3)]
        readings = self.run_probe(view, probe, {i: FakeContext(self.server) for i in ids})
        cases = {
            'context_shared': dict(reference='fixture-context-0'),
            'assigned_context_unverified': dict(assignment={'kind': 'none', 'source': '', 'receipt_sha256': '',
                                                            'child_ref': ''}),
            'browser_tools_unavailable': dict(tools=child_tools('Read')),
        }
        for code_name, kw in cases.items():
            with self.subTest(case=code_name):
                code, out = self.bind(view, 2, probe, readings, **kw)
                self.assertEqual((code, out['error']['code']), (1, 'journey_unavailable'))
                self.assertIn(code_name, {p['code'] for p in out['data']['problems']})
                self.assertEqual((out['data']['relay'], out['data']['capture_results']), ('prohibited', 'retained'))
        cleared = copy.deepcopy(readings)
        cleared[ids[0]]['cleared'] = True
        code, out = self.bind(view, 2, probe, cleared)
        self.assertIn('never cleared', json.dumps(out['data']['problems']))
        # Fixture isolation evidence can never bind a staging or live target.
        staging = self.approved(self.lab.small(study_id='staging-study', target=json.loads(TEMPLATE.read_text())['target']))
        probe = self.probe(staging, (0, 1))
        readings = self.run_probe(staging, probe, {staging['cells'][n]['cell_id']: FakeContext(self.server)
                                                   for n in (0, 1)})
        code, out = self.bind(staging, 0, probe, readings)
        self.assertIn('fixture_binding_for_real_target', {p['code'] for p in out['data']['problems']})
        self.assertEqual(len(bindings), 2)

    def test_rebinding_after_resume_needs_a_fresh_probe_and_stales_the_old_journey_brief(self):
        view = self.fixture_study()
        self.isolated(view, (0, 1))
        self.accepted_first(view, 0)
        old = self.brief(view, 0, 'journey')
        # Resume: the host gives cell 0 a new context; it is verified again with a new probe.
        probe = self.probe(view, (0, 1))
        ids = [view['cells'][n]['cell_id'] for n in (0, 1)]
        readings = self.run_probe(view, probe, {i: FakeContext(self.server) for i in ids})
        code, out = self.bind(view, 0, probe, readings, reference='fixture-context-0-resumed')
        self.assertEqual(code, 0, out)
        new = self.brief(view, 0, 'journey')
        self.assertNotEqual(old['document']['sha256'], new['document']['sha256'])
        self.assertIn('fixture-context-0-resumed', Path(new['document']['path']).read_text())
        payload = self.journey_payload(view, 0, old['document']['sha256'], out['data']['binding_sha256'], 'jr-01',
                                       reference='fixture-context-0-resumed')
        ref = self.write_payload(view, 'jr-01', payload)
        code, out = self.check(view, 0, 'journey', 'jr-01', ref)
        self.assertIn('context_rebound', {p['code'] for p in out['data']['problems']})


# ----------------------------------------------------------------------------- REQ-JOURNEY


class JourneyTest(IsolationHarness):
    """REQ-JOURNEY: child-driven journeys, scope, credentials, secrets, timestamps and visible gaps."""

    def ready(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        first = self.accepted_first(view, 0)
        brief = self.brief(view, 0, 'journey')
        return view, bindings, first, brief

    def test_task_relative_journey_files_are_reopened_without_allowing_scope_escapes(self):
        view, bindings, first, brief = self.ready()
        payload = self.journey_payload(view, 0, brief['document']['sha256'], bindings[0], 'jr-01')
        job_dir = self.lab.root / view['study_id']
        folder = self.task_dir(view, 'jr-01')
        note = folder / 'notes.txt'
        note.write_text('The recipe list opened.\n')
        events = folder / 'events.jsonl'
        events.write_text('{"event": "tap", "target": "recipes"}\n')
        payload['goals'][0]['evidence'] += [
            {'kind': kind, 'path': str(path), 'sha256': sha(path.read_bytes())}
            for kind, path in (('text', note), ('event-log', events))]
        absolute = self.write_payload(view, 'jr-01', payload, name='absolute.json')
        self.assertEqual(self.check(view, 0, 'journey', 'jr-01', absolute)[0], 0)
        for item in payload['goals'][0]['evidence']:
            item['path'] = str(Path(item['path']).relative_to(job_dir))
        relative = self.write_payload(view, 'jr-01', payload, name='relative.json')
        self.assertEqual(self.check(view, 0, 'journey', 'jr-01', relative)[0], 0)
        other = self.task_dir(view, 'jr-02') / 'notes.txt'
        other.write_bytes(note.read_bytes())
        (folder / 'linked.txt').symlink_to(note)
        (folder / 'linked-directory').symlink_to(folder, target_is_directory=True)
        for n, bad_path in enumerate(('artifacts/tasks/jr-01/../jr-01/notes.txt',
                                       'artifacts/tasks/jr-02/notes.txt', 'notes.txt',
                                       'artifacts/tasks/jr-01/linked.txt',
                                       'artifacts/tasks/jr-01/linked-directory/notes.txt')):
            with self.subTest(path=bad_path):
                bad = copy.deepcopy(payload)
                bad['goals'][0]['evidence'][1]['path'] = bad_path
                ref = self.write_payload(view, 'jr-01', bad, name=f'escaped-{n}.json')
                code, out = self.check(view, 0, 'journey', 'jr-01', ref)
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertIn('out_of_scope_artifact', {p['code'] for p in out['data']['problems']})
        context = {'class': 'fresh-anonymous', 'reference': 'fixture-context-0', 'binding_sha256': bindings[0]}
        code, out = self.record(view, 0, 'journey', 'jr-01', relative,
                                predecessors=[first['ref']['sha256']], context=context)
        self.assertEqual(code, 0, out)
        record_sha = out['data']['record_sha256']
        request = {'record_sha256': record_sha, 'payload': relative}
        self.assertEqual(self.lab.ev(*self.lab.study_args(view['study_id'], 'accept-journey', request))[0], 0)
        self.assertEqual(self.lab.ev('disclosure', '--state-root', self.lab.root,
                                     '--study', view['study_id'], '--consumer', 'export')[0], 0)
        note.write_text('Changed after acceptance.\n')
        code, out = self.lab.ev(*self.lab.study_args(view['study_id'], 'accept-journey', request))
        self.assertEqual((code, out['error']['code']), (1, 'material_unusable'), out)
        self.assertIn('hash_mismatch', {p['code'] for p in out['data']['problems']})

    def test_a_valid_child_driven_journey_is_accepted_as_labelled_fixture_evidence(self):
        view, bindings, first, brief = self.ready()
        doc = Path(brief['document']['path']).read_text()
        self.assertIn('Excluded actions (record a gap instead): create an account', doc)
        self.assertIn('Any route is fine', doc)
        payload = self.journey_payload(view, 0, brief['document']['sha256'], bindings[0], 'jr-01')
        ref = self.write_payload(view, 'jr-01', payload)
        self.assertEqual(self.check(view, 0, 'journey', 'jr-01', ref)[0], 0)
        result_sha = sha(Path(first['ref']['path']).read_bytes())
        context = {'class': 'fresh-anonymous', 'reference': 'fixture-context-0', 'binding_sha256': bindings[0]}
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[result_sha], context=context)
        self.assertEqual(code, 0, out)
        accepted = self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'accept-journey', {
            'record_sha256': out['data']['record_sha256'], 'payload': ref}))
        self.assertEqual((accepted['evidence_class'], accepted['live_isolation_claim']), ('fixture', False))
        record = json.loads(next((self.lab.root / view['study_id'] / 'focus-group' / 'evidence' / 'journeys')
                                 .glob('*.json')).read_text())
        self.assertNotEqual(record['started_at'], record['captured_at'])
        self.assertEqual(record['environment'], 'fixture')
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        self.assertEqual(coverage['cells'][0]['journey']['state'], 'hands-on-evidence')
        self.assertIsNone(coverage['combined_scope_complete'])

    def test_relay_unbound_context_excluded_or_credential_actions_and_frozen_stimuli_are_refused(self):
        view, bindings, first, brief = self.ready()
        doc_sha = brief['document']['sha256']
        base = self.journey_payload(view, 0, doc_sha, bindings[0], 'jr-01')
        pack_image = next(f for f in self.lab.pack_files if f['role'] == 'initial-viewport')

        def step(**kw):
            row = copy.deepcopy(base['goals'][0]['steps'][0])
            row.update(kw)
            goal = dict(base['goals'][0], steps=[row])
            return {'goals': [goal]}
        cases = {
            'coordinator_relay_prohibited': {'driver': 'coordinator'},
            'context_unbound': {'context': {'reference': 'fixture-context-1', 'binding_sha256': bindings[1]}},
            'excluded_action_attempted': step(permitted_action='create an account'),
            'credential_entry_attempted': step(kind='type', field={'type': 'password'}, description='typed a password'),
            'action_out_of_scope': step(permitted_action='message the support team'),
            'timestamps_conflated': {'started_at': fixtures.CAPTURED_AT},
            'capture_presented_as_live': {'goals': [dict(base['goals'][0], evidence=[
                {'kind': 'screenshot', 'path': str(self.task_dir(view, 'jr-01') / 'copied.png'),
                 'sha256': pack_image['sha256']}])]},
            'drift_unrecorded': {'environment_drift': {'state': 'unavailable', 'detail': ''}},
            'target_mismatch': {'target': {'url': 'https://staging.pantry-planner.example/welcome',
                                           'environment': 'fixture'}},
            'journey_coverage': {'goals': []},
        }
        (self.task_dir(view, 'jr-01') / 'copied.png').write_bytes(Path(pack_image['path']).read_bytes())
        for n, (code_name, change) in enumerate(cases.items()):
            with self.subTest(case=code_name):
                ref = self.write_payload(view, 'jr-01', dict(copy.deepcopy(base), **change), name=f'case-{n}.json')
                code, out = self.check(view, 0, 'journey', 'jr-01', ref)
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertIn(code_name, {p['code'] for p in out['data']['problems']})
        # A goal recorded as a gap instead of attempted is valid.
        gap = dict(copy.deepcopy(base), goals=[], gaps=[{'journey_id': 'plan-three-dinners', 'reason': 'excluded-action',
                                                         'detail': 'saving a plan needs an account'}])
        self.assertEqual(self.check(view, 0, 'journey', 'jr-01', self.write_payload(view, 'jr-01', gap, 'gap.json'))[0], 0)
        out = self.lab.ev(*self.lab.study_args(view['study_id'], 'check-action', {
            'revision': view['revision'], 'journey_id': 'plan-three-dinners', 'step': base['goals'][0]['steps'][0]
            | {'permitted_action': 'place a grocery order'}}))[1]
        self.assertEqual((out['error']['code'], out['data']['gap']), ('action_refused', True))

    def test_secret_markers_quarantine_the_attempt_and_fail_acceptance_and_export(self):
        view, bindings, first, brief = self.ready()
        payload = self.journey_payload(view, 0, brief['document']['sha256'], bindings[0], 'jr-01')
        payload['goals'][0]['observed_events'].append(f'the page printed Authorization: Bearer {SYNTHETIC_MARKER}')
        ref = self.write_payload(view, 'jr-01', payload)
        code, out = self.check(view, 0, 'journey', 'jr-01', ref)
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        context = {'class': 'fresh-anonymous', 'reference': 'fixture-context-0', 'binding_sha256': bindings[0]}
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, context=context,
                                predecessors=[sha(Path(first['ref']['path']).read_bytes())])
        self.assertEqual((code, out['error']['code']), (1, 'result_quarantined'))
        # Credential material by field name is quarantined too, even without a recognisable value.
        cookies = dict(self.journey_payload(view, 0, brief['document']['sha256'], bindings[0], 'jr-01'))
        cookies['goals'][0]['steps'][0]['field'] = {'type': 'text', 'cookies': 'a=b'}
        code, out = self.check(view, 0, 'journey', 'jr-01', self.write_payload(view, 'jr-01', cookies, 'cookie.json'))
        self.assertEqual(out['error']['code'], 'payload_quarantined')
        self.assertIn('credential-field', {h['class'] for h in out['data']['findings']})
        # A text evidence file is scanned as well.
        note = self.task_dir(view, 'jr-01') / 'page.txt'
        note.write_text(f'session_id={SYNTHETIC_MARKER}\n')
        leaky = self.journey_payload(view, 0, brief['document']['sha256'], bindings[0], 'jr-01')
        leaky['goals'][0]['evidence'].append({'kind': 'text', 'path': str(note), 'sha256': sha(note.read_bytes())})
        code, out = self.check(view, 0, 'journey', 'jr-01', self.write_payload(view, 'jr-01', leaky, 'leaky.json'))
        self.assertEqual(out['error']['code'], 'payload_quarantined')
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        code, out = self.lab.ev('disclosure', '--state-root', self.lab.root, '--study', view['study_id'],
                                '--consumer', 'export')
        self.assertEqual(code, 0, out)  # quarantined attempts were never accepted, so nothing disclosed is blocked
        self.assertEqual(out['data']['retained_quarantine'], 3)

    def test_no_browser_tools_unbound_context_and_credential_journeys_stay_visible_gaps(self):
        journeys = json.loads(TEMPLATE.read_text())['journeys'] + [
            {'id': 'save-plan', 'goal': 'Log in and save the plan to an account.',
             'permitted_actions': ['sign in with a test account'], 'excluded_actions': []}]
        view = self.fixture_study(journeys=journeys)
        probe = self.probe(view, (0, 1))
        ids = [view['cells'][n]['cell_id'] for n in (0, 1)]
        readings = self.run_probe(view, probe, {i: FakeContext(self.server) for i in ids})
        self.assertEqual(self.bind(view, 0, probe, readings)[0], 0)
        code, out = self.bind(view, 1, probe, readings, tools=child_tools('Read'))
        self.assertEqual(out['error']['code'], 'journey_unavailable')
        self.accepted_first(view, 0)
        self.accepted_first(view, 1)
        brief = self.brief(view, 0, 'journey')
        self.assertEqual([g['journey_id'] for g in brief['gaps']], ['save-plan'])
        self.assertNotIn('save the plan to an account', Path(brief['document']['path']).read_text())
        self.assertEqual(self.brief(view, 1, 'journey', expect=1)['error']['code'], 'context_unbound')
        self.assertEqual(self.brief(view, 2, 'journey', expect=1)['error']['code'], 'first_impression_missing')
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        rows = {r['cell_id']: r for r in coverage['cells']}
        self.assertEqual(rows[ids[1]]['journey'], {'state': 'gap', 'reasons': ['browser_tools_unavailable'],
                                                   'relay': 'prohibited'})
        self.assertEqual(rows[ids[1]]['first_impression'], 'frozen')  # capture results are kept
        self.assertIs(coverage['combined_scope_complete'], False)

    def context(self, bindings, n=0):
        return {'class': 'fresh-anonymous', 'reference': f'fixture-context-{n}', 'binding_sha256': bindings[n]}

    def test_fr3_an_attempted_goal_needs_its_route_and_what_was_observed(self):
        view, bindings, first, brief = self.ready()
        doc_sha = brief['document']['sha256']
        base = self.journey_payload(view, 0, doc_sha, bindings[0], 'jr-01')
        goal = base['goals'][0]
        empty = dict(goal, outcome='achieved', steps=[], reactions=[], observed_events=[], inferences=[], evidence=[])
        cases = {
            'achieved with nothing recorded': (empty, {'goal_unattempted', 'goal_unsupported'}),
            'achieved with a route but nothing observed': (dict(empty, steps=goal['steps']), {'goal_unsupported'}),
            'partial with nothing observed': (dict(goal, observed_events=[], evidence=[]), {'goal_unsupported'}),
            'not achieved and never attempted': (dict(empty, outcome='not-achieved'), {'goal_unattempted'}),
            'a step with no description': (dict(goal, steps=[dict(goal['steps'][0], description=' ')]), {'payload_shape'}),
        }
        for n, (name, (row, codes)) in enumerate(cases.items()):
            with self.subTest(case=name):
                ref = self.write_payload(view, 'jr-01', dict(copy.deepcopy(base), goals=[row]), name=f'goal-{n}.json')
                code, out = self.check(view, 0, 'journey', 'jr-01', ref)
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertEqual({p['code'] for p in out['data']['problems']}, codes)
        # The reviewer's case, through the acceptance boundary: an empty achieved goal never becomes coverage.
        ref = self.write_payload(view, 'jr-01', dict(copy.deepcopy(base), goals=[empty]), name='empty.json')
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']],
                                context=self.context(bindings))
        self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        self.assertEqual(coverage['cells'][0]['journey'], {'state': 'pending'})
        # Controls: a read-only route with one observation, no reactions, inferences or files, is valid and
        # becomes hands-on evidence; there is no quota of criticism.
        read = dict(goal['steps'][0], kind='read', description='read the recipe list')
        minimal = dict(empty, steps=[read], observed_events=['the recipe list loaded'])
        evidence_only = dict(minimal, observed_events=[], evidence=goal['evidence'])
        self.assertEqual(self.check(view, 0, 'journey', 'jr-01', self.write_payload(
            view, 'jr-01', dict(copy.deepcopy(base), goals=[evidence_only]), name='evidence-only.json'))[0], 0)
        ref = self.write_payload(view, 'jr-01', dict(copy.deepcopy(base), goals=[minimal]), name='minimal.json')
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']],
                                context=self.context(bindings), admit=False)
        self.assertEqual(code, 0, out)
        # A journey whose every goal is a gap is accepted as a gap, never as hands-on evidence.
        self.accepted_first(view, 1)
        gap_brief = self.brief(view, 1, 'journey')
        gap = dict(self.journey_payload(view, 1, gap_brief['document']['sha256'], bindings[1], 'jr-02'), goals=[],
                   gaps=[{'journey_id': 'plan-three-dinners', 'reason': 'excluded-action',
                          'detail': 'saving a plan needs an account'}])
        ref = self.write_payload(view, 'jr-02', gap)
        code, out = self.record(view, 1, 'journey', 'jr-02', ref, context=self.context(bindings, 1),
                                predecessors=[sha(Path(self.study_dir(view, 'artifacts/tasks/fi-02/payload.json')).read_bytes())])
        self.assertEqual(code, 0, out)
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        rows = coverage['cells']
        self.assertEqual((rows[0]['journey']['state'], rows[0]['journey']['trace_compliance']),
                         ('hands-on-evidence', 'unverified'))
        self.assertEqual(rows[1]['journey'], {'state': 'gap', 'reasons': ['excluded-action'], 'relay': 'prohibited'})
        self.assertEqual(coverage['journey_gaps'], 1)

    def test_fr5_steps_stay_inside_the_journey_interval_and_never_run_backwards(self):
        view, bindings, first, brief = self.ready()
        base = self.journey_payload(view, 0, brief['document']['sha256'], bindings[0], 'jr-01')
        one, two = base['goals'][0]['steps']

        def timed(*times):
            goal = dict(copy.deepcopy(base['goals'][0]), steps=[dict(s, at=t) for s, t in zip((one, two), times)])
            return dict(copy.deepcopy(base), goals=[goal])
        # The journey runs 00:05..00:09 on 1 June; the capture was at 23:00 on 31 May.
        cases = {
            'before the capture and descending': (timed('2029-05-31T22:00:00Z', '2029-05-30T22:00:00Z'),
                                                  {'step_outside_journey', 'steps_out_of_order'}),
            'after the capture, before the start': (timed('2029-06-01T00:04:00Z', '2029-06-01T00:07:00Z'),
                                                    {'step_outside_journey'}),
            'after the end': (timed('2029-06-01T00:06:00Z', '2029-06-01T00:09:30Z'), {'step_outside_journey'}),
            'reversed inside the interval': (timed('2029-06-01T00:08:00Z', '2029-06-01T00:06:00Z'),
                                             {'steps_out_of_order'}),
        }
        for n, (name, (payload, codes)) in enumerate(cases.items()):
            with self.subTest(case=name):
                ref = self.write_payload(view, 'jr-01', payload, name=f'time-{n}.json')
                code, out = self.check(view, 0, 'journey', 'jr-01', ref)
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertEqual({p['code'] for p in out['data']['problems']}, codes)
        # The reviewer's case is refused at the acceptance boundary as well.
        ref = self.write_payload(view, 'jr-01', cases['before the capture and descending'][0], name='reviewer.json')
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']],
                                context=self.context(bindings))
        self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
        # Controls: equal times (clock resolution) and steps on the interval's own bounds are valid.
        for n, times in enumerate((('2029-06-01T00:06:00Z', '2029-06-01T00:06:00Z'),
                                   ('2029-06-01T00:05:00Z', '2029-06-01T00:09:00Z'))):
            with self.subTest(control=times):
                ref = self.write_payload(view, 'jr-01', timed(*times), name=f'control-{n}.json')
                self.assertEqual(self.check(view, 0, 'journey', 'jr-01', ref)[0], 0)
        code, out = self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']],
                                context=self.context(bindings), admit=False)
        self.assertEqual(code, 0, out)
        record = json.loads(self.study_dir(view, 'focus-group', 'evidence', 'journeys',
                                           f'{out["data"]["record_sha256"]}.json').read_text())
        self.assertEqual((record['captured_at'], record['started_at']), (fixtures.CAPTURED_AT, LATER))


# ----------------------------------------------------------------------------- ingestion boundary


class IngestionTest(IsolationHarness):
    """FG2-C1, FG2-C2 and FG2-F2 through the real CLIs: record-acceptance screens and validates the exact
    accepted bytes itself, freezes or binds exactly those bytes, and the verify commands bind nothing else."""

    def attempts(self, view, kind):
        return len(list(self.study_dir(view, 'focus-group', 'evidence', 'attempts').glob(f'{kind}-*.json')))

    def accepted_names(self, view):
        folder = self.study_dir(view, 'focus-group', 'accepted')
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    @staticmethod
    def journey_context(binding_sha, reference='fixture-context-0'):
        return {'class': 'fresh-anonymous', 'reference': reference, 'binding_sha256': binding_sha}

    def material(self, view, task, name, data):
        path = self.task_dir(view, task) / name
        path.write_bytes(data)
        return {'path': str(path), 'sha256': sha(data)}

    def verify_journey(self, view, record_sha, ref):
        return self.lab.ev(*self.lab.study_args(view['study_id'], 'accept-journey',
                                                {'record_sha256': record_sha, 'payload': ref}))

    # FG2-C1 -----------------------------------------------------------------------------------

    def test_c1_a_later_response_is_never_frozen_or_bound_in_place_of_the_accepted_one(self):
        view = self.fixture_study()
        bindings = self.isolated(view)
        brief = self.brief(view, 0, 'first-impression')
        first = self.first_payload(view, 0, brief['document']['sha256'])
        ref = self.write_payload(view, 'fi-01', first)
        code, out = self.record(view, 0, 'first-impression', 'fi-01', ref)
        self.assertEqual(code, 0, out)
        record_sha = out['data']['record_sha256']
        later = dict(first, initial_viewport=dict(first['initial_viewport'],
                                                  reaction='Replacement response never accepted as the first response.'))
        alt = self.write_payload(view, 'fi-01', later, name='later-response.json')
        self.assertEqual(self.check(view, 0, 'first-impression', 'fi-01', alt)[0], 0)  # valid alone: binding decides
        before = self.attempts(view, 'freeze')
        code, out = self.freeze(view, record_sha, alt)
        self.assertEqual((code, out['error']['code']), (1, 'payload_not_accepted'))
        self.assertEqual(out['data']['accepted_result_sha256'], ref['sha256'])
        self.assertEqual(self.attempts(view, 'freeze'), before + 1)  # the refused attempt is retained
        code, out = self.record(view, 0, 'first-impression', 'fi-01', alt, admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'conflicting_acceptance'))
        self.assertEqual(sha(Path(ref['path']).read_bytes()), ref['sha256'])
        frozen = json.loads(self.study_dir(view, 'focus-group', 'evidence', 'first', f'{record_sha}.json').read_text())
        self.assertEqual((frozen['payload'], frozen['result_sha256']), (ref, ref['sha256']))
        doc = Path(self.brief(view, 0, 'journey')['document']['path']).read_text()
        self.assertIn(first['initial_viewport']['reaction'], doc)
        self.assertNotIn('Replacement response', doc)
        # Intact control: the exact accepted result verifies, idempotently.
        for _ in range(2):
            code, out = self.freeze(view, record_sha, ref)
            self.assertEqual((code, out['data']['payload_sha256'], out['data']['duplicate']), (0, ref['sha256'], True))
        # The same holds for a journey: accept-journey never blesses a later payload for the accepted record.
        jbrief = self.brief(view, 0, 'journey')['document']['sha256']
        journey = self.journey_payload(view, 0, jbrief, bindings[0], 'jr-01')
        jref = self.write_payload(view, 'jr-01', journey)
        code, out = self.record(view, 0, 'journey', 'jr-01', jref, predecessors=[ref['sha256']],
                                context=self.journey_context(bindings[0]))
        self.assertEqual(code, 0, out)
        jrecord = out['data']['record_sha256']
        other = dict(journey, goals=[dict(journey['goals'][0], reactions=['A different, later journey account.'])])
        jalt = self.write_payload(view, 'jr-01', other, name='later-journey.json')
        code, out = self.verify_journey(view, jrecord, jalt)
        self.assertEqual((code, out['error']['code']), (1, 'payload_not_accepted'))
        code, out = self.record(view, 0, 'journey', 'jr-01', jalt, predecessors=[ref['sha256']],
                                context=self.journey_context(bindings[0]), admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'conflicting_acceptance'))
        code, out = self.verify_journey(view, jrecord, jref)
        self.assertEqual((code, out['data']['payload_sha256']), (0, jref['sha256']), out)
        bound = json.loads(self.study_dir(view, 'focus-group', 'evidence', 'journeys', f'{jrecord}.json').read_text())
        self.assertEqual(bound['payload'], jref)

    def test_c1_an_envelope_or_a_changed_missing_or_escaped_accepted_result_is_never_consumed(self):
        view = self.fixture_study()
        self.isolated(view)
        # A worker-result envelope is not a payload: ingestion parses exactly the bytes it is given and
        # never follows a member reference to a second, caller-selected path.
        brief = self.brief(view, 1, 'first-impression')['document']['sha256']
        inner = self.write_payload(view, 'fi-02', self.first_payload(view, 1, brief))
        envelope = {'schema_version': 1, 'artifact': {'path': inner['path'], 'sha256': inner['sha256'],
                                                      'finding_count': 0, 'finding_ids': []}, 'correlation': {}}
        code, out = self.record(view, 1, 'first-impression', 'fi-02',
                                self.write_payload(view, 'fi-02', envelope, name='envelope.json'))
        self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'))
        self.assertIn('payload_shape', {p['code'] for p in out['data']['problems']})
        self.assertEqual(self.accepted_names(view), [])
        expected = {'changed': 'hash_mismatch', 'missing': 'missing_artifact', 'escaped': 'out_of_scope_artifact'}
        for how, code_name in expected.items():
            with self.subTest(how=how):
                study = self.fixture_study(study_id=f'c1-{how}')
                self.isolated(study)
                first = self.accepted_first(study, 0)
                path = Path(first['ref']['path'])
                if how == 'changed':
                    path.write_text('{"rewritten": true}')
                elif how == 'missing':
                    path.unlink()
                else:
                    outside = self.lab.base / f'outside-{how}.json'
                    outside.write_bytes(path.read_bytes())  # the original bytes, outside the task scope
                    path.unlink()
                    path.symlink_to(outside)
                code, out = self.freeze(study, first['record_sha256'], first['ref'])
                self.assertEqual((code, out['error']['code']), (1, 'material_unusable'))
                self.assertEqual(out['data']['problems'][0]['code'], code_name)
                self.assertEqual(self.brief(study, 0, 'journey', expect=1)['error']['code'], 'predecessor_unusable')
                code, out = self.lab.ev('disclosure', '--state-root', self.lab.root, '--study', study['study_id'],
                                        '--consumer', 'export')
                self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'))
                self.assertEqual(out['data']['material'][0]['code'], code_name)

    # FG2-C2 -----------------------------------------------------------------------------------

    def test_c2_every_material_kind_is_scanned_whole_before_acceptance_and_again_before_disclosure(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        first = self.accepted_first(view, 0)
        doc_sha = self.brief(view, 0, 'journey')['document']['sha256']
        marker = f'api_key={SYNTHETIC_MARKER}'

        def journey(*items, name):
            payload = self.journey_payload(view, 0, doc_sha, bindings[0], 'jr-01')
            payload['goals'][0]['evidence'] += [dict(kind=kind, **ref) for kind, ref in items]
            return self.write_payload(view, 'jr-01', payload, name=name)

        code, out = self.lab.admit(view, 'jr-01-r0', 'journey', view['cells'][0]['cell_id'])
        self.assertEqual(code, 0, out)

        def record(ref, **kw):
            return self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']],
                               context=self.journey_context(bindings[0]), admit=False, **kw)
        accepted = self.accepted_names(view)
        # An event log carrying an invented credential assignment: the advisory check refuses it, and so
        # does record-acceptance on its own, with only location, class and hash in the output.
        log = self.material(view, 'jr-01', 'events.jsonl', f'{{"event": "load"}}\n{{"debug": "{marker}"}}\n'.encode())
        code, out = self.check(view, 0, 'journey', 'jr-01', journey(('event-log', log), name='event-secret.json'))
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        log2 = self.material(view, 'jr-01', 'events-2.jsonl', f'{{"debug": "{marker}"}}\n'.encode())
        direct = journey(('event-log', log2), name='event-secret-direct.json')
        code, out = record(direct)
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        self.assertEqual(out['data']['sha256'], direct['sha256'])
        self.assertTrue(any('events-2.jsonl' in h['location'] and h['class'] == 'credential-assignment'
                            for h in out['data']['findings']))
        self.assertEqual(record(direct)[1]['error']['code'], 'result_quarantined')
        # A text file is scanned whole: a marker after 256 KiB of clean text still quarantines.
        long_text = self.material(view, 'jr-01', 'page-long.txt', ('Clean line. ' * 30000 + marker).encode())
        code, out = record(journey(('text', long_text), name='long-text.json'))
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        # Oversize, undecodable and non-PNG material is refused unscanned, never cleared.
        cases = ((('event-log', self.material(view, 'jr-01', 'huge.log', b'a' * (8 * 1024 * 1024 + 1))),
                  'oversize_artifact'),
                 (('event-log', self.material(view, 'jr-01', 'utf16.log', 'log line'.encode('utf-16'))),
                  'evidence_undecodable'),
                 (('screenshot', self.material(view, 'jr-01', 'shot.gif', b'GIF89a' + b'\0' * 32)), 'evidence_unreadable'))
        for item, code_name in cases:
            with self.subTest(code=code_name):
                code, out = record(journey(item, name=f'{code_name}.json'))
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertIn(code_name, {p['code'] for p in out['data']['problems']})
        # Screenshot pixels clear only through the coordinator's own inspection record.
        pixels = journey(name='pixels.json')
        code, out = record(pixels, inspection=None)
        self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'))
        self.assertIn('evidence_uninspected', {p['code'] for p in out['data']['problems']})
        code, out = record(pixels, inspection=self.inspection(pixels, secrets_visible=True))
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        self.assertIn('coordinator-flagged', {h['class'] for h in out['data']['findings']})
        self.assertEqual(self.accepted_names(view), accepted)  # nothing above entered accepted state
        # Valid control: clean text, a clean event log and an inspected screenshot are accepted and bound.
        text = self.material(view, 'jr-01', 'page.txt', b'Three dinners planned; the list opened.\n')
        events = self.material(view, 'jr-01', 'events-clean.jsonl', b'{"event": "tap", "target": "recipes"}\n')
        good = journey(('text', text), ('event-log', events), name='good.json')
        code, out = record(good)
        self.assertEqual(code, 0, out)
        record_sha = out['data']['record_sha256']
        code, out = self.verify_journey(view, record_sha, good)
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(m['kind'] for m in out['data']['material']), ['event-log', 'screenshot', 'text'])
        self.lab.ev_ok('disclosure', '--state-root', self.lab.root, '--study', view['study_id'], '--consumer', 'export')
        # Material changed after acceptance is caught by every consumer: verification and disclosure.
        Path(events['path']).write_text(f'{{"debug": "{marker}"}}\n')
        code, out = self.verify_journey(view, record_sha, good)
        self.assertEqual((code, out['error']['code']), (1, 'material_unusable'))
        self.assertEqual(out['data']['problems'][0]['code'], 'hash_mismatch')
        for consumer in ('participant', 'analysis', 'review', 'export'):
            code, out = self.lab.ev('disclosure', '--state-root', self.lab.root, '--study', view['study_id'],
                                    '--consumer', consumer)
            self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'))
            self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)

    # FG2-A3-1 ---------------------------------------------------------------------------------

    def test_a3_screenshot_metadata_is_decoded_or_refused_never_cleared_unread(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        first = self.accepted_first(view, 0)
        doc_sha = self.brief(view, 0, 'journey')['document']['sha256']
        self.assertEqual(self.lab.admit(view, 'jr-01-r0', 'journey', view['cells'][0]['cell_id'])[0], 0)
        base = fixtures.png(390, 844, ((255, 255, 255), (10, 120, 200), (0, 0, 0)))
        marker = f'api_key={SYNTHETIC_MARKER}'.encode()
        accepted = self.accepted_names(view)

        def record(data, name):
            payload = self.journey_payload(view, 0, doc_sha, bindings[0], 'jr-01')
            payload['goals'][0]['evidence'] = [dict(kind='screenshot', **self.material(view, 'jr-01', name, data))]
            ref = self.write_payload(view, 'jr-01', payload, name=f'{name}.json')
            return self.record(view, 0, 'journey', 'jr-01', ref, predecessors=[first['ref']['sha256']],
                               context=self.journey_context(bindings[0]), admit=False)
        # A compressed iTXt chunk is inflated before the scan, so its marker quarantines like tEXt does.
        code, out = record(fixtures.with_chunk(base, b'iTXt', b'Comment\0\1\0\0\0' + zlib.compress(marker)), 'itxt.png')
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'), out)
        self.assertTrue(any('itxt.png:text-chunks' in h['location'] for h in out['data']['findings']))
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        # A chunk v1 does not decode, or bytes after IEND, is refused by location and format only.
        for data, name in ((fixtures.with_chunk(base, b'prVt', marker), 'private.png'), (base + marker, 'trailing.png')):
            with self.subTest(name=name):
                code, out = record(data, name)
                self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
                self.assertIn('evidence_unsupported', {p['code'] for p in out['data']['problems']})
                self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        self.assertEqual(self.accepted_names(view), accepted)  # nothing above entered accepted state
        # Valid control: standard chunks and clean compressed iTXt metadata still clear.
        clean = fixtures.with_chunk(fixtures.with_chunk(base, b'pHYs', b'\0\0\x0b\x13\0\0\x0b\x13\1'), b'iTXt',
                                    b'Software\0\1\0en\0\0' + zlib.compress(b'invented capture tool'))
        code, out = record(clean, 'clean.png')
        self.assertEqual(code, 0, out)
        self.lab.ev_ok('disclosure', '--state-root', self.lab.root, '--study', view['study_id'], '--consumer', 'export')

    # FG2-F2 -----------------------------------------------------------------------------------

    def test_f2_record_acceptance_validates_the_exact_bytes_without_any_prior_check(self):
        view = self.fixture_study()
        bindings = self.isolated(view, (0, 1))
        cell = view['cells'][0]['cell_id']
        brief = self.brief(view, 0, 'first-impression')['document']['sha256']
        self.assertEqual(self.lab.admit(view, 'fi-01-r0', 'first-impression', cell)[0], 0)
        record = lambda ref, **kw: self.record(view, 0, 'first-impression', 'fi-01', ref, admit=False, **kw)
        hidden = {'state': 'not-delivered', 'source': 'fixture: attachments unsupported'}

        def problems(ref, **kw):
            code, out = record(ref, **kw)
            self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'), out)
            return {p['code'] for p in out['data']['problems']}
        # Direct record of an unchecked, invalid payload: the boundary validates it itself.
        visual = self.write_payload(view, 'fi-01', self.first_payload(view, 0, brief), name='visual.json')
        self.assertIn('image_basis_unverified', problems(visual, delivery=hidden))
        # A failed advisory check leaves no receipt; record-acceptance refuses again on the same bytes.
        self.assertEqual(self.check(view, 0, 'first-impression', 'fi-01', visual, hidden)[0], 1)
        self.assertIn('image_basis_unverified', problems(visual, delivery=hidden))
        # Mismatched bindings: another cell's payload, a brief built for another task, another task's folder.
        self.assertIn('wrong_cell_or_revision',
                      problems(self.write_payload(view, 'fi-01', self.first_payload(view, 1, brief), name='foreign.json')))
        other = self.lab.ev_ok(*self.lab.study_args(view['study_id'], 'brief', {
            'revision': view['revision'], 'cell_id': cell, 'stage': 'first-impression', 'task_id': 'fi-99'}))
        borrowed = self.write_payload(view, 'fi-01', self.first_payload(view, 0, other['document']['sha256']),
                                      name='borrowed.json')
        self.assertEqual(record(borrowed)[1]['error']['code'], 'brief_task_mismatch')
        self.assertEqual(record(self.write_payload(view, 'fi-02', self.first_payload(view, 0, brief)))[1]['error']['code'],
                         'out_of_scope_artifact')
        # A planted marker is quarantined at the boundary, without its value, and its bytes never return.
        leak = self.write_payload(view, 'fi-01', self.first_payload(view, 0, brief, claims=[
            {'id': 'c1', 'kind': 'textual', 'statement': f'The footer shows token={SYNTHETIC_MARKER}', 'files': ['welcome.txt']}]),
            name='leak.json')
        code, out = record(leak)
        self.assertEqual((code, out['error']['code']), (1, 'payload_quarantined'))
        self.assertNotIn(SYNTHETIC_MARKER, self.lab.last_output)
        self.assertEqual(record(leak)[1]['error']['code'], 'result_quarantined')
        self.assertEqual(self.accepted_names(view), [])
        self.assertEqual(self.attempts(view, 'record'), 6)  # an identical re-presentation shares its attempt record
        # Valid control: accepted and frozen in one step, bound to these bytes; a retry is idempotent.
        good = self.write_payload(view, 'fi-01', self.first_payload(view, 0, brief))
        code, out = record(good)
        self.assertEqual((code, out['data']['ingested']), (0, 'first-impression'), out)
        self.assertTrue(record(good)[1]['data']['duplicate'])
        coverage = self.lab.ev_ok('coverage', '--state-root', self.lab.root, '--study', view['study_id'])
        self.assertEqual(coverage['cells'][0]['first_impression'], 'frozen')
        # Changed dependencies: a journey that ran in a context rebound since stays out, and a first
        # impression whose bytes changed stops its journey from being ingested at all.
        stale = self.write_payload(view, 'jr-01', self.journey_payload(
            view, 0, self.brief(view, 0, 'journey')['document']['sha256'], bindings[0], 'jr-01'), name='stale.json')
        # The journey is admitted while its brief is current (FG-3); the context is rebound afterwards.
        self.assertEqual(self.lab.admit(view, 'jr-01-r0', 'journey', view['cells'][0]['cell_id'])[0], 0)
        self.lab.release(view, 'jr-01-r0')
        probe = self.probe(view, (0, 1))
        readings = self.run_probe(view, probe, {view['cells'][n]['cell_id']: FakeContext(self.server) for n in (0, 1)})
        code, rebound = self.bind(view, 0, probe, readings, reference='fixture-context-0-resumed')
        self.assertEqual(code, 0, rebound)
        code, out = self.record(view, 0, 'journey', 'jr-01', stale, predecessors=[good['sha256']],
                                context=self.journey_context(bindings[0]), admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'payload_invalid'))
        self.assertIn('context_unbound', {p['code'] for p in out['data']['problems']})
        fresh_sha = rebound['data']['binding_sha256']
        fresh = self.write_payload(view, 'jr-01', self.journey_payload(
            view, 0, self.brief(view, 0, 'journey')['document']['sha256'], fresh_sha, 'jr-01',
            reference='fixture-context-0-resumed'), name='fresh.json')
        Path(good['path']).write_text('{"rewritten": true}')
        code, out = self.record(view, 0, 'journey', 'jr-01', fresh, predecessors=[good['sha256']],
                                context=self.journey_context(fresh_sha, 'fixture-context-0-resumed'), admit=False)
        self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'))
        self.assertEqual(len(self.accepted_names(view)), 1)


# ----------------------------------------------------------------------------- job-spec integration


class JobSpecTest(IsolationHarness):
    """FG-1 job-spec takes FG-2 briefs: all sixteen slots once journeys are briefed, and stale briefs fail."""

    def test_job_spec_accepts_every_generated_brief_and_refuses_a_stale_journey_brief(self):
        view = self.fixture_study()
        probe = self.probe(view, (0, 1, 2, 3))
        contexts = {c['cell_id']: FakeContext(self.server) for c in view['cells']}
        readings = self.run_probe(view, probe, contexts)
        documents = {}
        for n in range(4):
            self.assertEqual(self.bind(view, n, probe, readings)[0], 0)
            documents[f'fi-{n + 1:02d}'] = self.accepted_first(view, n)['brief']['document']
            documents[f'jr-{n + 1:02d}'] = self.brief(view, n, 'journey')['document']
        docs = self.lab.write('all.json', documents)
        args = ('job-spec', '--state-root', self.lab.root, '--study', view['study_id'], '--installation-id', 'fixture',
                '--documents', docs)
        job = self.lab.ok(*args, '--capabilities', self.lab.catalog(), now=BEFORE)['job']
        participants = [t for t in job['tasks'] if t['worker_id'] == 'focus-group/participant']
        self.assertEqual(len(participants), 8)
        self.assertEqual({t['document']['sha256'] for t in participants}, {d['sha256'] for d in documents.values()})
        # Rebinding cell 0 after its brief was built makes that journey brief stale for dispatch.
        probe = self.probe(view, (0, 1))
        again = self.run_probe(view, probe, {view['cells'][n]['cell_id']: FakeContext(self.server) for n in (0, 1)})
        self.assertEqual(self.bind(view, 0, probe, again, reference='fixture-context-0b')[0], 0)
        self.lab.refused('participant_brief_stale', *args, '--capabilities', self.lab.catalog(), now=BEFORE)
        # A brief swapped between tasks is refused.
        swapped = dict(documents, **{'fi-01': documents['fi-02'], 'fi-02': documents['fi-01']})
        self.lab.refused('participant_brief_unrecorded', 'job-spec', '--state-root', self.lab.root, '--study',
                         view['study_id'], '--installation-id', 'fixture', '--defer-journeys', '--documents',
                         self.lab.write('swapped.json', swapped), '--capabilities', self.lab.catalog(), now=BEFORE)


if __name__ == '__main__':
    unittest.main()
