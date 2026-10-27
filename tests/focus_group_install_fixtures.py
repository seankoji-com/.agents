"""Installed focus-group fixtures shared by independently collected test modules.

Each module owns a fresh relocated package. No TestCase in this helper defines tests.
"""
import copy
import json
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import tarfile
import time
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
PLUGIN_MODULES = {'study', 'evidence', 'lifecycle', 'report', 'validate_study', 'plan_review', 'authority', 'core', 'shared'}
SHARED_CONTRACTS = ('boundaries.md', 'manifest.schema.json', 'workers-config.schema.json', 'job.schema.json',
                    'stage.schema.json', 'worker-brief.schema.json', 'worker-result.schema.json',
                    'result-envelope.schema.json', 'acceptance.schema.json', 'jobs-contract.md',
                    'reviewer-standard.md', 'model-selection.schema.json', 'model-authority.schema.json',
                    'planning-policy.schema.json', 'planning-job.schema.json', 'planning-subject.schema.json',
                    'planning-assessment.schema.json', 'planning-direct.schema.json')
# Loaded by every audited helper process through PYTHONPATH. It never changes behaviour: it records each path the
# process opens, lists or imports from inside the forbidden root, and appends one JSON line per process at exit.
AUDIT_HOOK = r'''
import atexit, errno, fcntl, json, os, sys
_root, _log = os.environ.get('FG_FORBIDDEN_ROOT'), os.environ.get('FG_AUDIT_LOG')
if _root and _log:
    _root, _hits, _busy = os.path.realpath(_root), [], [False]

    def _physical(value):
        path = value if os.path.isabs(value) else os.path.join(os.getcwd(), value)
        if hasattr(os, 'O_PATH'):
            fd = None
            try:
                fd = os.open(path, os.O_PATH | getattr(os, 'O_CLOEXEC', 0))
                return os.readlink('/proc/self/fd/' + str(fd))
            except OSError as exc:
                # Missing bare names have no link below physical cwd. Every
                # existing path/link is resolved afresh, never cached.
                if fd is None and exc.errno == errno.ENOENT and not os.path.isabs(value) and os.sep not in value:
                    return path
            finally:
                if fd is not None:
                    os.close(fd)
        elif sys.platform == 'darwin' and hasattr(os, 'O_EVTONLY') and hasattr(fcntl, 'F_GETPATH'):
            # The event-only descriptor resolves the current vnode without
            # opening its data. F_GETPATH is available in Python 3.9+ on macOS.
            # Reopen on every audit event so a retargeted alias is never cached.
            fd = None
            try:
                fd = os.open(path, os.O_EVTONLY | getattr(os, 'O_CLOEXEC', 0))
                resolved = fcntl.fcntl(fd, fcntl.F_GETPATH, b'\0' * 1024).split(b'\0', 1)[0]
                if resolved:
                    return os.fsdecode(resolved)
            except OSError:
                pass
            finally:
                if fd is not None:
                    os.close(fd)
        return os.path.realpath(path)

    def _check(value):
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        if isinstance(value, str) and value:
            path = _physical(value)
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


def module_deadline():
    """Each installed test module keeps the repository's 600-second hard bound."""
    old=signal.getsignal(signal.SIGALRM)
    def expired(signum,frame):raise TimeoutError('installed test module exceeded 600 seconds')
    signal.signal(signal.SIGALRM,expired);signal.alarm(600)
    def cleanup():signal.alarm(0);signal.signal(signal.SIGALRM,old)
    unittest.addModuleCleanup(cleanup)


def clean_env(base):
    """A process environment with its own HOME and XDG roots and no inherited plugin, XDG or Python settings."""
    (base / 'home').mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENTS_', 'XDG_', 'PYTHON', 'FG_'))}
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


def audit_fidelity_probe(base):
    """Real source reads through a retargeted alias must remain observable."""
    probe=Path(base)/'audit-control';probe.mkdir()
    env=audited(clean_env(probe),probe)
    target=ROOT/'tests/focus_group_install_fixtures.py'
    script=('from pathlib import Path\nimport os,sys,sitecustomize\n'
            'target=Path(sys.argv[1]);allowed=Path("allowed");allowed.write_text("Invented audit control.")\n'
            'alias=Path("alias");alias.symlink_to(allowed);assert alias.read_text()==allowed.read_text()\n'
            'original=os.path.realpath\n'
            'def no_component_walk(*args,**kwargs):raise AssertionError("descriptor path fell back to component traversal")\n'
            'if hasattr(os,"O_PATH") or sys.platform=="darwin":os.path.realpath=no_component_walk\n'
            'try:\n'
            ' alias.unlink();alias.symlink_to(target);assert alias.read_bytes()\n'
            ' alias.unlink();alias.symlink_to(target.parent);list(alias.iterdir())\n'
            ' alias.unlink();alias.symlink_to(allowed);assert alias.read_text()==allowed.read_text()\n'
            'finally:os.path.realpath=original\n')
    p=subprocess.run([sys.executable,'-c',script,str(target)],cwd=probe,env=env,
                     capture_output=True,text=True,timeout=60)
    assert p.returncode==0,p.stdout+p.stderr
    rows=audit_rows(probe);hits={v for row in rows for v in row['hits']}
    assert str(target.resolve()) in hits and str(target.parent.resolve()) in hits,rows
    return {'exit':p.returncode,'symlink_retarget_source_detected':True,'directory_source_detected':True,
            'no_path_cache':True,'rows':rows}


class PristineFixture:
    """Restore real setup bytes at the same path; never rewrite signed absolute bindings."""

    def __init__(self, base, *values):
        self.base = base
        self.saved = base.with_name(base.name + '-pristine')
        self.values = copy.deepcopy(values)
        self.files = self.manifest(base)
        shutil.copytree(base, self.saved, symlinks=True)

    @staticmethod
    def manifest(base):
        rows = {}
        for path in (base, *base.rglob('*')):
            mode = path.lstat().st_mode & 0o777
            if path.is_symlink():
                value = ('link', mode, os.readlink(path))
            elif path.is_dir():
                value = ('directory', mode)
            else:
                value = ('file', mode, sha(path.read_bytes()))
            rows[str(path.relative_to(base))] = value
        return rows

    def restore(self):
        shutil.rmtree(self.base)
        shutil.copytree(self.saved, self.base, symlinks=True)
        if self.manifest(self.base) != self.files:
            raise AssertionError('pristine fixture bytes, permissions or links changed')
        return copy.deepcopy(self.values)


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
                                                   'events': events + list(extra),
                                                   **({'harness': self.trace_harness}
                                                      if hasattr(self, 'trace_harness') else {})}}))

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
        for key in [k for k in os.environ if k.startswith(('PYTHON', 'FG_', 'AGENTS_', 'XDG_'))]:
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


def fixture_phase(config, name):
    with (Path(config['base'])/'phase-timing.jsonl').open('a') as stream:
        stream.write(json.dumps({'phase':name,'at':time.perf_counter()})+'\n')


def observe_fixture_calls(base, diagnostic_limit=None, profile_prepare=None):
    """Observe real public subprocess calls; an explicit diagnostic may stop early.

    Required scenarios always pass None and execute every operation/assertion.
    The optional stop produces a failed diagnostic, never a successful fixture.
    """
    original = subprocess.run
    log = Path(base)/'call-timing.jsonl'
    sequence = 0
    prepares = 0
    def record(value):
        with log.open('a') as stream:stream.write(json.dumps(value)+'\n')
    def timed(argv, *args, **kwargs):
        nonlocal sequence, prepares
        sequence += 1
        if diagnostic_limit is not None and sequence > diagnostic_limit:
            record({'event':'diagnostic-stop','after_calls':diagnostic_limit})
            raise RuntimeError('intentional timing diagnostic stop; no fixture completion')
        call = sequence;started = time.perf_counter()
        effective = argv
        if len(argv)>2 and Path(argv[1]).name=='job_cli.py' and argv[2]=='prepare':
            prepares += 1
            if prepares==profile_prepare:
                effective=[argv[0],'-m','cProfile','-o',str(Path(base)/'prepare.pstats'),*argv[1:]]
        record({'event':'start','call':call,'argv':list(map(str,argv)),
                'effective_argv':list(map(str,effective)),
                'timeout':kwargs.get('timeout'),'pid':os.getpid(),'mode':'fresh-process'})
        try:
            result = original(effective,*args,**kwargs)
            record({'event':'finish','call':call,'elapsed':time.perf_counter()-started,
                    'exit':result.returncode})
            return result
        except BaseException as exc:
            record({'event':'error','call':call,'elapsed':time.perf_counter()-started,
                    'error':type(exc).__name__+': '+str(exc)})
            raise
    subprocess.run = timed


class RecoveryInstallation:
    """Two real private builds and a moved prefix; audited children import only installed runtime.

    The older build is an offline synthetic identity: committed HEAD runtime
    with only the manifest version set to 0.1.0. It does not prove cross-code
    compatibility with the retained finance pin. Test support is copied separately
    so audits detect checkout imports and reads. No live state is used.
    """

    SUPPORT = ('support.py', 'focus_group_install_fixtures.py', 'focus_group_fixtures.py',
               'test_focus_group_plan.py', 'test_focus_group_lifecycle.py', 'test_focus_group_report.py',
               'test_model_ids.py', 'model_selection_fixtures.py', 'upfront_fixtures.py',
               'test_rebuild_installed.py', 'test_focus_group_install_authority.py',
               'test_focus_group_install_recovery.py')

    def __init__(self, base):
        setup_started = time.perf_counter()
        self.base = Path(base).resolve()
        self.env = clean_env(self.base)
        self.audit_probe = audit_fidelity_probe(self.base)
        self.prefix, self.agents = self.base/'prefix', self.base/'agents'
        original = self.base/'committed-source'
        original.mkdir()
        archive_paths = ['core','shared','plugins/focus-group']
        if subprocess.run(['git','cat-file','-e','HEAD:skills/focus-group/SKILL.md'],
                          cwd=ROOT,capture_output=True).returncode == 0:
            archive_paths.append('skills/focus-group')
        archive = subprocess.run(['git', 'archive', 'HEAD', *archive_paths],
                                 cwd=ROOT, capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            for member in bundle.getmembers():
                assert not member.issym() and not member.islnk()
                assert (original/member.name).resolve().is_relative_to(original)
            bundle.extractall(original)
        older_manifest=original/'plugins/focus-group/plugin.json'
        older_meta=json.loads(older_manifest.read_text())
        candidate_meta=json.loads((ROOT/'plugins/focus-group/plugin.json').read_text())
        assert tuple(map(int,'0.1.0'.split('.'))) < tuple(map(int,candidate_meta['version'].split('.')))
        older_meta['version']='0.1.0'
        older_manifest.write_text(json.dumps(older_meta,indent=2)+'\n')
        def install_source(source):
            argv = [sys.executable, str(ROOT/'scripts/install.py'), '--plugin', 'focus-group',
                    '--source', str(source), '--prefix', str(self.prefix), '--agents-root', str(self.agents)]
            p = subprocess.run(argv, env=self.env, cwd=self.base, capture_output=True, text=True, timeout=120)
            assert p.returncode == 0, p.stdout+p.stderr
            return json.loads(p.stdout)['data']
        old = install_source(original)
        new = install_source(ROOT)
        old_manifest=json.loads((Path(old['version_dir'])/'install-manifest.json').read_text())
        new_manifest=json.loads((Path(new['version_dir'])/'install-manifest.json').read_text())
        assert old_manifest['package_digest'] != new_manifest['package_digest'], 'synthetic older identity must have a distinct package digest'
        self.synthetic_older_identity={'manifest_version':'0.1.0','source':'committed HEAD with manifest-only synthetic delta',
            'old_package_digest':old_manifest['package_digest'],'new_package_digest':new_manifest['package_digest'],
            'retained_finance_pin_cross_code_compatibility':False}
        future_source=self.base/'future-source'
        for rel in ('core','shared','plugins/focus-group','skills/focus-group'):
            shutil.copytree(ROOT/rel,future_source/rel,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        future_manifest=future_source/'plugins/focus-group/plugin.json'
        future_meta=json.loads(future_manifest.read_text());future_meta['version']='0.1.99'
        future_manifest.write_text(json.dumps(future_meta))
        future=install_source(future_source)  # Source build, never an installed-file patch.
        self.original_prefix = self.prefix
        moved = self.base/'moved'/'relocated prefix';moved.parent.mkdir()
        self.prefix.rename(moved);self.prefix=moved
        proc = catalog(self.env, moved, self.agents, 'adopt', '--from-prefix', self.original_prefix)
        assert proc.returncode == 0, proc.stdout+proc.stderr
        self.old = moved/'focus-group'/Path(old['version_dir']).name
        self.package = moved/'focus-group'/Path(new['version_dir']).name
        self.future = moved/'focus-group'/Path(future['version_dir']).name
        # adopt may retain its registry lock at the former prefix; no runtime
        # package or importable helper may remain there.
        assert self.old != self.package and not (self.original_prefix/'focus-group').exists()
        self.manifest = json.loads((self.package/'install-manifest.json').read_text())
        self.driver = self.base/'fixture-support';(self.driver/'tests').mkdir(parents=True)
        (self.driver/'tests/__init__.py').write_text('')
        for name in self.SUPPORT:
            shutil.copyfile(ROOT/'tests'/name,self.driver/'tests'/name)
        self.control_env=dict(self.env)
        self.env = audited(self.env,self.base)
        self.proofs = []
        self.setup_seconds = time.perf_counter()-setup_started

    def run(self, module, function, package=None, *, diagnostic_limit=None, profile_prepare=None):
        # unittest discovery supplies a bare name; the isolated support copy is
        # always a tests package. Only these two copied scenario modules enter.
        module = module if module.startswith('tests.') else 'tests.' + module
        assert module in ('tests.test_focus_group_install_authority',
                          'tests.test_focus_group_install_recovery'), module
        phase_started=time.perf_counter()
        package=package or self.package
        # Planning fixture creation pins the selected installed version. Activate
        # that private version before the child; source catalog setup is outside
        # the audited execution boundary, just like initial install/adoption.
        activated=catalog(self.control_env,self.prefix,self.agents,'activate','focus-group',package.name)
        assert activated.returncode==0,activated.stdout+activated.stderr
        config={'base':str(self.base), 'package':str(package), 'old_package':str(self.old),
                'synthetic_older_identity':self.synthetic_older_identity,
                'new_package':str(self.package),'future_package':str(self.future),
                'prefix':str(self.prefix),'agents':str(self.agents),'diagnostic_limit':diagnostic_limit,
                'profile_prepare':profile_prepare}
        source = (
            'import sys,json,importlib\n'
            'from pathlib import Path\n'
            'config=json.loads(sys.argv[1])\n'
            'sys.path[:0]=[sys.argv[2],str(Path(config["package"])/"scripts"),config["package"]]\n'
            'from tests import test_focus_group_plan as plan,test_focus_group_lifecycle as life\n'
            'plan.TEMPLATE=Path(config["package"])/"templates/study-draft.example.json"\n'
            'manifest=json.loads((Path(config["package"])/"install-manifest.json").read_text())\n'
            'import os\n'
            'life.INSTALL.update(package=Path(config["package"]),prefix=Path(config["prefix"]),'
            'agents=Path(config["agents"]),installation=manifest["installation_id"],env=dict(os.environ))\n'
            'module=importlib.import_module(sys.argv[3])\n'
            'copied=Path(sys.argv[2])/"tests"/(sys.argv[3].split(".")[-1]+".py")\n'
            'assert Path(module.__file__).resolve()==copied.resolve(),module.__file__\n'
            'fixture_module={"name":module.__name__,"path":str(copied.resolve())}\n'
            'from tests.focus_group_install_fixtures import observe_fixture_calls\n'
            'observe_fixture_calls(config["base"],config["diagnostic_limit"],config["profile_prepare"])\n'
            'result=getattr(module,sys.argv[4])(config)\n'
            'imports={n:str(Path(m.__file__).resolve()) for n,m in list(sys.modules.items()) '
            'if getattr(m,"__file__",None) and (n in ("study","authority","evidence","lifecycle","report") '
            'or n=="core" or n.startswith("core.") or n=="shared" or n.startswith("shared."))}\n'
            'assert all(Path(p).is_relative_to(Path(config["package"])) for p in imports.values()),imports\n'
            'print(json.dumps({"scenario":result,"imports":imports,"package":config["package"],'
            '"fixture_module":fixture_module}))\n')
        p=subprocess.Popen([sys.executable,'-c',source,json.dumps(config),str(self.driver),module,function],
                           cwd=self.base,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                           start_new_session=True)
        try:stdout,stderr=p.communicate(timeout=540)
        except BaseException as exc:
            # This process group was created here and its leader PID captured
            # before any scenario code. Never find or stop processes by name.
            os.killpg(p.pid,signal.SIGKILL);stdout,stderr=p.communicate()
            self.proofs.append({'function':function,'pid':p.pid,'exit':p.returncode,'stdout':stdout,
                                'stderr':stderr,'interruption':type(exc).__name__+': '+str(exc),
                                'elapsed':time.perf_counter()-phase_started,'diagnostic_limit':diagnostic_limit,
                                'profile_prepare':profile_prepare})
            self.retain();raise
        self.proofs.append({'function':function,'pid':p.pid,'exit':p.returncode,'stdout':stdout,'stderr':stderr,
                            'elapsed':time.perf_counter()-phase_started,'diagnostic_limit':diagnostic_limit,
                            'profile_prepare':profile_prepare})
        self.retain()
        assert p.returncode==0,stdout+stderr
        result=json.loads(stdout.splitlines()[-1]);rows=audit_rows(self.base)
        assert rows and all(not r['hits'] for r in rows),rows
        self.retain()
        return result

    def retain(self):
        out=os.environ.get('FG_RECOVERY_EVIDENCE_DIR')
        if out:
            path=Path(out);path.mkdir(exist_ok=True)
            (path/(self.base.name+'.json')).write_text(json.dumps({'processes':self.proofs,
                'audit_fidelity_probe':self.audit_probe,
                'setup_seconds':self.setup_seconds,
                'synthetic_older_identity':self.synthetic_older_identity,
                'phases':[json.loads(line) for line in (self.base/'phase-timing.jsonl').read_text().splitlines()]
                    if (self.base/'phase-timing.jsonl').exists() else [],
                'call_timings':[json.loads(line) for line in (self.base/'call-timing.jsonl').read_text().splitlines()]
                    if (self.base/'call-timing.jsonl').exists() else [],
                'audits':audit_rows(self.base),'old_package':str(self.old),'new_package':str(self.package),
                'new_package_digest':self.manifest['package_digest'],'installation_id':self.manifest['installation_id'],
                'original_runtime_absent':not (self.original_prefix/'focus-group').exists()},indent=2))
            (path/(self.base.name+'.install-manifest.json')).write_text(json.dumps(self.manifest,indent=2))
            for profile in self.base.glob('*.pstats'):
                shutil.copyfile(profile,path/(self.base.name+'-'+profile.name))
            if (self.base/'host.json').exists():
                shutil.copyfile(self.base/'host.json',path/(self.base.name+'-diagnostic-host.json'))


def save_recovery_host(host, path):
    def encode(value):
        if isinstance(value,Path):return {'fixture_path':str(value)}
        if isinstance(value,dict):
            if any(not isinstance(k,str) for k in value):
                return {'fixture_mapping':[[encode(k),encode(v)] for k,v in value.items()]}
            return {k:encode(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [encode(v) for v in value]
        return value
    Path(path).write_text(json.dumps(encode(host.__dict__)))


def load_recovery_host(path, package):
    def decode(value):
        if isinstance(value,dict):
            if set(value)=={'fixture_path'}:return Path(value['fixture_path'])
            if set(value)=={'fixture_mapping'}:
                return {(tuple(decode(k)) if isinstance(k,list) else decode(k)):decode(v)
                        for k,v in value['fixture_mapping']}
            return {k:decode(v) for k,v in value.items()}
        if isinstance(value,list):return [decode(v) for v in value]
        return value
    host=RecoveryHost.__new__(RecoveryHost);host.__dict__.update(decode(json.loads(Path(path).read_text())))
    host.package=Path(package);host.helper=host.package/'scripts/study.py'
    return host


def recovery_parent_selection(data, draft, reuse_panel_roles=False):
    """Construct one truthful synthetic parent choice before normal selection admission."""
    from shared import model_selection as models
    data=copy.deepcopy(data);data['capabilities']['runtimeMode']='full-access'
    for n,target in enumerate(draft['participant_models'],1):
        data['work'][f'participant-{n:02d}']=copy.deepcopy(target)
        for profile in data['profiles']['models']:
            if models.key(profile['target'])==models.key(target):
                profile['target']=copy.deepcopy(target)
    if reuse_panel_roles:
        # The base fixture normalizes targets while its parent is still auto.
        # Restore the explicitly selected full-access review/options before
        # validation, exactly as participant choices above are restored.
        data['review_panel'][0]['target']=copy.deepcopy(draft['review'])
        planner=copy.deepcopy(data['work']['analysis'])
        family=next(p['lineage'] for p in data['profiles']['models'] if models.key(p['target'])==models.key(planner))
        data['work']['workhorse']=planner
        data['coordinator']=dict(planner,lineage=family,observed_options=copy.deepcopy(planner['options']))
        data['capabilities'].update(parentThreadId='fixture-actual-parent',
            inheritedProviderInstanceId=planner['providerInstanceId'],inheritedModel=planner['model'])
        assert not data['work_replacements'] and not data['review_replacements']
        used={models.key(t) for t in data['work'].values()} | {models.key(s['target']) for s in data['review_panel']}
        data['profiles']['models']=[r for r in data['profiles']['models'] if models.key(r['target']) in used]
        for provider in data['capabilities']['providers']:
            provider['models']=[m for m in provider['models'] if (provider['providerInstanceId'],m['id']) in used]
        data['capabilities']['providers']=[p for p in data['capabilities']['providers'] if p['models']]
    return data


def recovery_role_contract(plan, selected):
    """Freeze panel, role/options, sharing and actual synthetic parent identity."""
    from shared import model_selection as models
    values={k:copy.deepcopy(plan[k]) for k in ('participant_models','analysis','review','sharing')}
    values.update(workhorse=copy.deepcopy(selected['work']['workhorse']),
        coordinator=copy.deepcopy(selected['coordinator']),
        capability_parent={k:selected['capabilities'][k] for k in
            ('parentThreadId','inheritedProviderInstanceId','inheritedModel')})
    assert selected['work']['analysis']==plan['analysis']==values['workhorse']
    assert selected['review_panel'][0]['target']==plan['review'] and selected['review_panel'][0]['independent']
    for n,target in enumerate(plan['participant_models'],1):
        assert selected['work'][f'participant-{n:02d}']==target
    families={models.key(p['target']):p['lineage'] for p in selected['profiles']['models']}
    assert families[models.key(plan['analysis'])]!=families[models.key(plan['review'])]
    assert models.key(values['coordinator'])==models.key(plan['analysis'])
    assert values['coordinator']['observed_options']==plan['analysis']['options']
    assert (values['capability_parent']['inheritedProviderInstanceId'],values['capability_parent']['inheritedModel'])==models.key(plan['analysis'])
    return values


class RecoveryHost(HandoffHost):
    """Retain complete target options and use the scenario's real synthetic catalog."""

    def catalog(self, now=fg3.BEFORE, caps=None, observations=None, observed_at=None):
        return fg3.Host.catalog(self, now, caps or json.loads(self.caps.read_text()), observations, observed_at)

    def plan(self,*args,**kwargs):
        # The original fixture models an auto-mode parent. This explicit
        # synthetic parent is full-access for the OpenCode-shaped target;
        # only discovery input changes, never a validator/result/receipt.
        from unittest.mock import patch
        from tests import focus_group_fixtures as fixtures
        original=fixtures.approved_selection
        def parent_choice(data):
            return original(recovery_parent_selection(data,args[0],getattr(self,'reuse_panel_roles',False)))
        with patch.object(fixtures,'approved_selection',side_effect=parent_choice):
            return super().plan(*args,**kwargs)

    def target_of(self, n):
        return {k:self.view['cells'][n][k] for k in ('providerInstanceId','model','options','runtimeMode')
                if k in self.view['cells'][n]}

    def job(self,command,payload,package=None):
        self.counter+=1;path=self.write(f'job-{command}-{self.counter}.json',payload)
        p=subprocess.run([sys.executable,str((package or self.package)/'shared/job_cli.py'),command,
            '--state-root',str(self.root),'--job',self.view['study_id'],'--input',str(path),
            '--prefix',str(fg3.INSTALL['prefix']),'--agents-root',str(fg3.INSTALL['agents'])],
            cwd=self.base,env={**fg3.INSTALL['env'],**self.policy_env},capture_output=True,text=True,timeout=120)
        return p.returncode,json.loads(p.stdout) if p.returncode==0 else p.stderr

    def create_job(self):
        if not getattr(self,'shared_cap',None):return super().create_job()
        # Initial synthetic run-choice construction, before public job creation.
        # This is not a rewrite of runtime state, budget, receipt or performed work.
        from shared import execution_agreement as agreements, model_selection as models, adopter_planning as adopter
        path=self.root/self.view['study_id']/'focus-group/planning'/self.view['revision']/'run.json'
        record=json.loads(path.read_text());selected=copy.deepcopy(record['selection'])
        selected['agreement']['limits']['max_repair_cycles']=self.shared_cap
        selected['agreement']=agreements.freeze(selected['agreement'],selected)
        selected=models.freeze(selected)
        record=adopter.admit('focus-group',{'operation':'run','request_reference':record['request_reference'],
            'output_name':record['output_name'],'invocation_id':selected['invocation_id'],
            'selection':selected,'selection_sha256':selected['selection_sha256']})
        path.write_text(json.dumps(record))
        documents={f'fi-{n+1:02d}':self.document(n,'first-impression',f'fi-{n+1:02d}') for n in range(len(self.view['cells']))}
        spec=self.ok('job-spec','--state-root',self.root,'--study',self.view['study_id'],
            '--installation-id',fg3.INSTALL['installation'],'--documents',self.write('fi-docs.json',documents),
            '--defer-journeys','--capabilities',self.catalog(),now=fg3.BEFORE)['job']
        spec['policy']['max_repair_cycles']=self.shared_cap
        p=subprocess.run([sys.executable,str(self.package/'shared/job_cli.py'),'create','--state-root',str(self.root),
            '--job',self.view['study_id'],'--input',str(self.write('job.json',spec)),
            '--prefix',str(fg3.INSTALL['prefix']),'--agents-root',str(fg3.INSTALL['agents'])],
            cwd=self.base,env={**fg3.INSTALL['env'],**self.policy_env},capture_output=True,text=True,timeout=120)
        assert p.returncode==0,p.stdout+p.stderr
        self.documents=documents
