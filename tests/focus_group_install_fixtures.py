"""Installed focus-group fixtures shared by independently collected test modules.

Each module owns a fresh relocated package. No TestCase in this helper defines tests.
"""
import copy
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
from tests import test_focus_group_lifecycle as fg3  # noqa: E402
from tests import test_focus_group_report as fg4  # noqa: E402
from tests.test_focus_group_plan import BEFORE, OPERATIONS, WORKERS, sha  # noqa: E402
from tests.test_model_ids import MODEL_ID  # noqa: E402

CATALOG = ROOT / 'scripts' / 'catalog.py'
SOURCE_PLUGIN = ROOT / 'plugins' / 'focus-group'
PLUGIN_MODULES = {'study', 'evidence', 'lifecycle', 'report', 'validate_study', 'plan_review', 'core', 'shared'}
SHARED_CONTRACTS = ('boundaries.md', 'manifest.schema.json', 'workers-config.schema.json', 'job.schema.json',
                    'stage.schema.json', 'worker-brief.schema.json', 'worker-result.schema.json',
                    'result-envelope.schema.json', 'acceptance.schema.json', 'jobs-contract.md',
                    'reviewer-standard.md', 'model-selection.schema.json', 'model-authority.schema.json',
                    'planning-policy.schema.json', 'planning-job.schema.json', 'planning-subject.schema.json',
                    'planning-assessment.schema.json', 'planning-direct.schema.json')
# Loaded by every audited helper process through PYTHONPATH. It never changes behaviour: it records each path the
# process opens, lists or imports from inside the forbidden root, and appends one JSON line per process at exit.
AUDIT_HOOK = r'''
import atexit, json, os, sys
_root, _log = os.environ.get('FG_FORBIDDEN_ROOT'), os.environ.get('FG_AUDIT_LOG')
if _root and _log:
    _root, _hits, _busy = os.path.realpath(_root), [], [False]

    def _check(value):
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        if isinstance(value, str) and value:
            path = os.path.realpath(value if os.path.isabs(value) else os.path.join(os.getcwd(), value))
            if path == _root or path.startswith(_root + os.sep):
                _hits.append(path)

    def _hook(event, args):
        if _busy[0] or event not in ('open', 'os.listdir', 'os.scandir', 'os.chdir', 'import'):
            return
        _busy[0] = True
        try:
            _check(args[1] if event == 'import' else (args[0] if args else None))
        finally:
            _busy[0] = False

    for _entry in list(sys.path):
        _check(_entry)
    sys.addaudithook(_hook)

    def _report():
        _busy[0] = True
        line = json.dumps({'pid': os.getpid(), 'script': os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else '',
                           'cwd': os.getcwd(), 'hits': sorted(set(_hits))[:20]}) + '\n'
        fd = os.open(_log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    atexit.register(_report)
'''
STATE = {}


def clean_env(base):
    """A process environment with its own HOME and XDG roots and no inherited plugin, XDG or Python settings."""
    (base / 'home').mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('T3_PLUGINS_', 'XDG_', 'PYTHON', 'FG_'))}
    env.update(HOME=str(base / 'home'), XDG_CONFIG_HOME=str(base / 'config'), XDG_STATE_HOME=str(base / 'xdg-state'),
               PYTHONDONTWRITEBYTECODE='1')
    return env


def catalog(env, prefix, agents, *args):
    return subprocess.run([sys.executable, str(CATALOG), '--prefix', str(prefix), '--agents-root', str(agents),
                           *map(str, args)], capture_output=True, text=True, env=env, timeout=120)


def install(base, name='prefix'):
    """Install focus-group with the catalog's install route into `base/name`; return its locations."""
    env = clean_env(base)
    prefix, agents = base / name, base / 'agents'
    proc = catalog(env, prefix, agents, 'install', 'focus-group')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    receipt = json.loads(proc.stdout.splitlines()[-1])['data']
    package = Path(receipt['version_dir'])
    manifest = json.loads((package / 'install-manifest.json').read_text())
    return {'base': base, 'env': env, 'prefix': prefix, 'agents': agents, 'package': package, 'manifest': manifest,
            'installation': manifest['installation_id'], 'receipt': receipt}


def audited(env, base):
    """`env` plus the audit hook: helper processes report what they touched under the source checkout."""
    hook = base / 'audit-hook'
    hook.mkdir(exist_ok=True)
    (hook / 'sitecustomize.py').write_text(AUDIT_HOOK)
    return {**env, 'PYTHONPATH': str(hook), 'FG_FORBIDDEN_ROOT': str(ROOT), 'FG_AUDIT_LOG': str(base / 'audit.jsonl')}


def audit_rows(base):
    log = base / 'audit.jsonl'
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def run_installed(package, script, *args, env, cwd, python=sys.executable):
    proc = subprocess.run([python, str(package / script), *map(str, args)], capture_output=True, text=True, env=env,
                          cwd=cwd, timeout=120)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, (json.loads(lines[-1]) if lines else None), proc.stderr


def setUpModule():
    STATE.clear()
    tmp = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(tmp.cleanup)
    base = Path(tmp.name).resolve()
    STATE.update(tmp=tmp, base=base)
    original = install(base, 'original-prefix')
    moved = base / 'moved' / 'relocated prefix'
    moved.parent.mkdir()
    os.rename(original['prefix'], moved)  # relocation: the original prefix no longer exists
    package = moved / 'focus-group' / original['package'].name
    STATE['relocated'] = dict(original, prefix=moved, package=package, original_prefix=original['prefix'])


def tearDownModule():
    STATE['tmp'].cleanup()
    STATE.clear()


class InstalledHost(fg4.ReportHost):
    """The FG-4 fixture host, with every focus-group helper and the generic job helpers taken from the installed
    package. The draft starts from the installed template."""

    def __init__(self, base, package):
        super().__init__(base)
        self.package = package
        self.policy_env = {'XDG_STATE_HOME': os.environ['XDG_STATE_HOME']}
        self.helper = package / 'scripts' / 'study.py'

    def draft(self, **changes):
        draft = super().draft(**changes)
        template = json.loads((self.package / 'templates' / 'study-draft.example.json').read_text())
        for key in ('study_id', 'audience', 'decision', 'mode', 'journeys', 'exclusions', 'journey_context', 'personas',
                    'capture_profile', 'prompts', 'limits', 'coverage_policy'):
            if key not in changes:
                draft[key] = copy.deepcopy(template[key])
        return draft

    def _json(self, script, args, now=None, env=None):
        argv = [sys.executable, str(self.package / 'scripts' / script), *map(str, args)]
        if now:
            argv += ['--now', now]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, cwd=self.base,
                              env=env or {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (proc.stdout, proc.stderr)
        return proc.returncode, json.loads(lines[0])

    def lc(self, *args, now=None):
        return self._json('lifecycle.py', args, now)

    def rp(self, *args, env=None):
        return self._json('report.py', args, env=env)


class HandoffHost(InstalledHost):
    """Issue 85: use the actual generated example and record both required brief reads."""

    def __init__(self, base, package):
        super().__init__(base, package)
        self.first_hosts = {}

    def begin(self, n=0, request=None, stage='first-impression'):
        task = f'{"fi" if stage == "first-impression" else "jr"}-{n + 1:02d}'
        request = request or f'{task}-r0'
        code, out = self.admit_slot(n, stage, request,
                                     purpose='initial' if request.endswith('-r0') else 'repair')
        assert code == 0, out
        brief = self.prepare(task)
        outer = next(t['brief'] for t in self.job_state()['tasks'] if t['task_id'] == task)
        host = self.launch(task, request, n=n)
        document = (self.documents if stage == 'first-impression' else self.journey_documents)[task]
        text = Path(document['path']).read_text()
        example = re.search(r'```json\n(.*?)\n```', text.split('## Expected output\n')[1], re.S)
        payload = json.loads(example[1])
        # Instantiate the document's example before the fixture worker writes/returns anything.
        payload['brief_sha256'] = document['sha256']
        if stage == 'journey':
            payload['environment_drift']['detail'] = f'Fixture {task}: drift could not be observed.'
            for gap in payload['gaps']:
                gap['detail'] = f'Fixture {task}: stopped before attempting {gap["journey_id"]}.'
        if stage == 'first-impression':
            self.first_hosts[n] = host
        return {'task': task, 'request': request, 'host': host, 'brief': brief, 'document': document,
                'stage': stage, 'n': n, 'outer': outer,
                'text': text, 'payload': payload}

    def trace(self, run, extra=()):
        # Resolve this execution, including retired requests and unprepared forbidden follow-ups.
        # Do not assert file validity here: negative cases must reach installed inspect-trace.
        outer = self.root / self.view['study_id'] / 'briefs' / f'{run["task"]}-{sha(run["request"].encode())}.json'
        events = [{'tool': 'read', 'path': str(outer)},
                  {'tool': 'read', 'path': run['document']['path']}]
        events += [{'tool': 'read', 'path': f['path'], 'result': 'Image read successfully'
                    if f['path'].endswith('.png') else 'Text read successfully'}
                   for f in run['brief']['context_files']]
        self.counter += 1
        return self.call_evidence(*self.study('inspect-trace'), '--input', self.write(
            f'trace-{self.counter}.json', {'revision': self.view['revision'], 'cell_id': run['payload']['cell_id'],
                                         'stage': run['stage'], 'task_id': run['task'],
                                         'request_id': run['request'], 'host_task_id': run['host'],
                                         'brief': run['document'], 'first_host_task_id':
                                             self.first_hosts[run['n']] if run['stage'] == 'journey' else None,
                                         'trace': {'source': 'invented OpenCode host read receipts',
                                                   'events': events + list(extra)}}))

    def finish(self, run, change=None, delivery=None):
        item = self.payload_file(run['task'], run['payload'])
        run['item'] = item
        result = self.worker_result(run['brief'], [item])
        if change:
            change(result)
        path = self.transport(result)
        run.update(transport=path, completion=f'done-{run["request"]}')
        assert self.complete(run['task'], run['request'], run['host'], run['completion'])[0] == 0
        delivered = self.deliver(run['task'], run['request'], run['completion'], path)
        if run['stage'] == 'journey':
            evidence = {'context': {'class': 'fresh-anonymous',
                                    **self.bound_context(self.view, self.cell(run['n']))}}
        else:
            evidence = {'image_delivery': delivery or {'state': 'delivered',
                'source': 'invented OpenCode host read events: Image read successfully for each PNG'}}
        outcome = self.ingest(run['task'], run['request'], run['completion'], path, **evidence)
        self.reconcile()
        return delivered, outcome


class Swap:
    """Point the FG-3/FG-4 harness (job helper, prefix, agents root, validator) and the helper processes' environment
    and working directory at one installed package and a temporary directory for a test, then restore all three.
    (Helpers open some files relative to a directory descriptor; the audit event carries only the relative name, so
    every audited process starts outside the source checkout.)"""

    def __init__(self, inst, env, cwd):
        self.inst, self.env, self.cwd = inst, env, cwd

    def __enter__(self):
        self.saved_install = dict(fg3.INSTALL)
        self.saved_environ = dict(os.environ)
        self.saved_cwd = os.getcwd()
        os.chdir(self.cwd)
        fg3.INSTALL.update(env=self.env, prefix=self.inst['prefix'], agents=self.inst['agents'],
                           package=self.inst['package'], installation=self.inst['installation'])
        for key in [k for k in os.environ if k.startswith(('PYTHON', 'FG_', 'T3_PLUGINS_', 'XDG_'))]:
            del os.environ[key]
        os.environ.update({k: v for k, v in self.env.items() if k.startswith(('PYTHON', 'FG_', 'XDG_')) or k == 'HOME'})
        return self

    def __exit__(self, *exc):
        os.chdir(self.saved_cwd)
        fg3.INSTALL.clear()
        fg3.INSTALL.update(self.saved_install)
        os.environ.clear()
        os.environ.update(self.saved_environ)


# ----------------------------------------------------------------------------- REQ-INSTALL: relocation


class RelocatedInstallCase(unittest.TestCase):
    """One package installed by the catalog, moved to a new prefix and adopted, then used without the source."""

    def assert_prepared_binding(self, h, run):
        """Check persisted current or retired evidence before constructing a valid trace."""
        study = h.root / h.view['study_id']
        task = next(t for t in h.job_state()['tasks'] if t['task_id'] == run['task'])
        handles = [r for r in task['handles'] if r['request_id'] == run['request']]
        self.assertEqual([r['task_id'] for r in handles], [run['host']])
        if task['brief']['request_id'] == run['request']:
            bound = {k: task['brief'][k] for k in ('path', 'sha256')}
        else:
            self.assertIn(run['request'], [r['request_id'] for r in task['execution_history']])
            rows = [json.loads(p.read_text()) for p in (study / 'focus-group/evidence/traces').glob('*.json')]
            refs = [r['prepared_brief'] for r in rows if (r['task_id'], r['request_id'], r['host_task_id']) ==
                    (run['task'], run['request'], run['host'])]
            self.assertTrue(refs, 'retired execution must retain its earlier trace binding')
            self.assertTrue(all(ref == refs[0] for ref in refs))
            bound = refs[0]
        path = study / 'briefs' / f'{run["task"]}-{sha(run["request"].encode())}.json'
        self.assertEqual(bound, {'path': str(path), 'sha256': run['outer']['sha256']})
        self.assertEqual(run['outer']['path'], str(path))
        raw = path.read_bytes()
        self.assertEqual(sha(raw), bound['sha256'])
        outer = json.loads(raw)
        self.assertEqual((outer['task_id'], outer['request_id'], outer['stage_id']),
                         (run['task'], run['request'], run['stage']))
        self.assertEqual(outer, run['brief'])
        correlation = {k: v for k, v in outer.items() if k != 'effective_brief_sha256'}
        self.assertEqual(outer['effective_brief_sha256'], sha((json.dumps(
            correlation, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode()))
        self.assertEqual(len({bound['sha256'], outer['effective_brief_sha256'], run['document']['sha256']}), 3)
        return bound

    def assert_artifact_example(self, run):
        expected_output = run['text'].split('## Expected output\n', 1)[1]
        fragment = expected_output.split('artifacts must include ', 1)[1].split('. Replace 123', 1)[0]
        artifact = json.loads(fragment)
        self.assertEqual(set(artifact), {'path', 'sha256', 'bytes'})
        self.assertEqual(artifact['path'], f'artifacts/tasks/{run["task"]}/payload.json')
        self.assertEqual(artifact['sha256'], 'SHA-256 of the payload file')
        self.assertIs(type(artifact['bytes']), int)

    @property
    def inst(self):
        return STATE['relocated']

    def adopt(self):
        inst = self.inst
        if not STATE.get('adopted'):
            proc = catalog(inst['env'], inst['prefix'], inst['agents'], 'adopt', '--from-prefix', inst['original_prefix'])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(json.loads(proc.stdout)['verified'])
            STATE['adopted'] = True
