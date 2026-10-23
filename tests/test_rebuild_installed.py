"""Issue #28 Stage 5: the installed artifact, not the source tree (REQ-COMPAT, REQ-REGISTRY, REQ-DELIVERY).

`bin/t3-plugins setup` installs every plugin into an isolated HOME, XDG roots, prefix,
agents root and two provider skill roots. The tests then read only what was installed:
adapters route every operation to the installed coordinator entry, packages carry their
worker bundles, shared coordination contract and pinned digests, `agents list/show`
inspect the bundles read-only, and uninstall keeps overrides and user files.

`Sandbox` is shared with test_rebuild_integration.py and test_rebuild_migration.py.
No model, no network, no GitHub and never the owner's home.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.store import canonical  # noqa: E402
from shared.job_acceptance import ADAPTERS  # noqa: E402
from shared.worker_registry import SHARED_REQUIRED, package_digest, verify_bundle, verify_package_files  # noqa: E402

BIN = ROOT / 'bin' / 't3-plugins'
INSTALL = ROOT / 'scripts' / 'install.py'
FIVE = ('imps', 'ape', 'plan', 'babysitter', 'agent-tuneup')
# Plugins whose Stage 4 coordinator entry is merged. ape joins when its rebuild names the
# contract; until then its entry is checked for routing only.
COORDINATED = set(FIVE)
TIMEOUT = 120


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def meta(plugin: str) -> dict:
    return json.loads((ROOT / 'plugins' / plugin / 'plugin.json').read_text())


def tree_digest(*roots: Path) -> dict:
    """Path -> (mode, sha256) for every file under the roots; detects any write."""
    found = {}
    for root in roots:
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
                found[str(path)] = (path.stat().st_mode & 0o777, sha(path.read_bytes()))
            elif path.is_symlink():
                found[str(path)] = ('link', os.readlink(path))
    return found


def json_lines(text: str) -> list:
    return [json.loads(line) for line in text.splitlines() if line.strip().startswith('{')]


class Sandbox:
    """One isolated installation: own HOME, XDG roots, prefix, agents root and job state."""

    def __init__(self, base: Path):
        self.base = Path(base).resolve()
        self.home = self.base / 'home'
        self.prefix, self.agents = self.base / 'prefix', self.base / 'agents'
        self.config, self.state = self.base / 'config', self.base / 'state'
        self.jobs = self.state / 't3-plugins' / 'jobs'  # the default job root under XDG_STATE_HOME
        self.private = self.base / 'coordinator'  # coordinator-owned inputs, outside job state
        for path in (self.home, self.private):
            path.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('T3_', 'XDG_'))}
        self.env = {**env, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config),
                    'XDG_STATE_HOME': str(self.state), 'XDG_DATA_HOME': str(self.base / 'data'),
                    'PYTHONDONTWRITEBYTECODE': '1'}
        self._counter = itertools.count()

    # Processes ---------------------------------------------------------------
    def run(self, argv, check=True, cwd=None):
        proc = subprocess.run([str(a) for a in argv], capture_output=True, text=True, env=self.env,
                              cwd=str(cwd or self.base), timeout=TIMEOUT)
        if check and proc.returncode:
            raise AssertionError(f'{argv[:3]} exited {proc.returncode}: {proc.stdout[-2000:]}{proc.stderr[-2000:]}')
        return proc

    def t3(self, *args, check=True):
        """The user CLI, always with this sandbox's explicit prefix and agents root."""
        return self.run([sys.executable, BIN, '--prefix', self.prefix, '--agents-root', self.agents, *args],
                        check=check)

    def install(self, plugin, source=None, check=True):
        argv = [sys.executable, INSTALL, '--plugin', plugin, '--prefix', self.prefix, '--agents-root', self.agents]
        if source is not None:
            argv += ['--source', source]
        proc = self.run(argv, check=check)
        if proc.returncode:
            return proc
        version = Path(json.loads(proc.stdout)['data']['version_dir'])
        return version, json.loads((version / 'install-manifest.json').read_text())

    def source_copy(self, plugin, mutate=None, name=None):
        """A source tree outside Git (content-addressed version) holding one plugin plus core/shared."""
        source = self.base / (name or f'source-{next(self._counter)}')
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc')
        shutil.copytree(ROOT / 'plugins' / plugin, source / 'plugins' / plugin, ignore=ignore)
        for part in ('core', 'shared'):
            shutil.copytree(ROOT / part, source / part, ignore=ignore)
        if mutate:
            mutate(source / 'plugins' / plugin)
        return source

    # Jobs --------------------------------------------------------------------
    def payload(self, data) -> Path:
        path = self.private / f'input-{next(self._counter)}.json'
        path.write_text(json.dumps(data))
        return path

    def job(self, pkg, command, job_id, data=None, check=True, extra=()):
        if command == 'plan-revision' and data is not None:
            from tests.model_selection_fixtures import attach_revision
            attach_revision(data, self.state_of(job_id))
        argv = [sys.executable, Path(pkg) / 'shared' / 'job_cli.py', command, '--state-root', self.jobs,
                '--job', job_id, *extra]
        if data is not None:
            argv += ['--input', self.payload(data)]
        proc = self.run(argv, check=check)
        return json.loads(proc.stdout) if check else proc

    def create(self, pkg, job):
        from tests.model_selection_fixtures import attach_selection
        if job.get('workflow') in ('ape/study', 'ape/forage') and not job.get('ape_admission'):
            from tests.ape_plan_review_fixtures import select_legacy_ape_fixture
            select_legacy_ape_fixture(job, self.private, self.jobs)
        if job.get('workflow') in ('imps/run', 'imps/issues', 'imps/checklist', 'imps/discussion') and not job.get('imps_admission'):
            from tests.imps_plan_review_fixtures import select_legacy_imps_job
            package = Path(pkg) if (Path(pkg) / 'plugin.json').is_file() and json.loads((Path(pkg) / 'plugin.json').read_text())['name'] == 'imps' else (self.prefix / 'imps/current').resolve()
            manifest = json.loads((package / 'install-manifest.json').read_text())
            select_legacy_imps_job(job, self.private, package, manifest, self.env)
        attach_selection(job)
        return self.job(pkg, 'create', job['job_id'], job,
                        extra=('--prefix', self.prefix, '--agents-root', self.agents,
                               '--config', self.config / 't3-plugins' / 'workers.json'))

    def accept(self, pkg, action, job_id, data):
        return self.run([sys.executable, Path(pkg) / 'shared' / 'job_acceptance_cli.py', action, '--state-root',
                         self.jobs, '--job', job_id, '--input', self.payload(data)], check=False)

    def state_of(self, job_id) -> dict:
        return json.loads((self.jobs / job_id / 'job.json').read_text())

    def pinned_package(self, job_id, plugin) -> Path:
        """Resume step one: recover the pinned package from the job, never from `current`."""
        entry = self.t3('--job', self.jobs / job_id / 'job.json', 'path', plugin).stdout.strip()
        return Path(entry).parent

    @staticmethod
    def caller(manifest, workflow):
        return {'actor': 'coordinator', 'installation_id': manifest['installation_id'], 'workflow': workflow,
                'package_digest': manifest['package_digest']}

    def owner_decision(self, decision_id, quote, scope):
        source = self.private / f'owner-{decision_id}.txt'
        source.write_text(f'Owner answer recorded verbatim: {quote}\n')
        return {'id': decision_id, 'quote': quote, 'source': str(source),
                'source_sha256': sha(source.read_bytes()), 'scope': scope}

    def publish(self, pkg, job_id, caller, stage_id, data):
        source = self.private / f'{stage_id}-{sha(canonical(data))[:16]}.json'
        source.write_text(json.dumps(data))
        return self.job(pkg, 'observation', job_id, {'caller': caller, 'stage_id': stage_id,
                                                      'input_file': str(source)})['path']

    def dispatch(self, pkg, job_id, caller, task_id, host):
        """Prepare one slot and record the host's accepted handle; returns the brief."""
        prepared = self.job(pkg, 'prepare', job_id, {'caller': caller, 'task_id': task_id,
                                                     'target_reason': 'lowest suitable configured tier'})
        raw = Path(prepared['path']).read_bytes()
        assert (sha(raw), len(raw)) == (prepared['sha256'], prepared['bytes']), 'brief locator differs from bytes'
        brief = json.loads(raw)
        self.job(pkg, 'task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': {
            'kind': 'accepted', 'request_id': brief['request_id'], 'host_task_id': host,
            'child_thread_id': 'child-' + host, 'status': 'running', 'work_state': 'working',
            'status_identity': brief.get('target'),
            'has_pending_child_runs': False}})
        return brief

    def complete(self, pkg, job_id, caller, task_id, brief, host, result_text):
        done = host + '-done'
        self.job(pkg, 'task-observation', job_id, {'caller': caller, 'task_id': task_id, 'event': {
            'kind': 'completion', 'request_id': brief['request_id'], 'host_task_id': host,
            'child_thread_id': 'child-' + host, 'completion_id': done, 'status': 'completed',
            'status_identity': brief.get('target'),
            'work_state': 'result_available', 'has_pending_child_runs': False}})
        return self.job(pkg, 'result', job_id, {'caller': caller, 'task_id': task_id,
                                                'request_id': brief['request_id'], 'completion_id': done,
                                                'result': {'json': result_text}})


def worker_result(brief, conclusion='synthetic fixture result', status='ready-for-acceptance'):
    """A complete worker-result v1 object for one immutable brief."""
    result = {'schema_version': 1, 'status': status, 'conclusion': conclusion,
              'requirements': [{'id': r['id'], 'status': 'passed', 'evidence': ['synthetic evidence']}
                               for r in brief['requirements']],
              'review_verdict': None, 'findings': [], 'gaps': [], 'uncertainties': [], 'changes': [],
              'commands': [], 'artifacts': [], 'binding': brief['snapshot'], 'extra_work_requests': [],
              'metrics': {'tokens': {'value': None, 'reason': 'synthetic fixture'}}}
    for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256',
                'revision'):
        result[key] = brief[key]
    return json.dumps(result)


class InstalledArtifactTest(unittest.TestCase):
    """One `t3-plugins setup` of the whole catalog; every test here only reads it."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='t3p-installed-')
        cls.box = Sandbox(Path(cls._tmp.name))
        cls.roots = (cls.box.home / 'provider-a' / 'skills', cls.box.home / 'provider-b' / 'skills')
        cls.setup = cls.box.t3('setup', '--root', cls.roots[0], '--root', cls.roots[1])
        cls.receipts = json_lines(cls.setup.stdout)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def package(self, plugin):
        current = self.box.prefix / plugin / 'current'
        self.assertTrue(current.is_symlink(), plugin)
        version = current.resolve()
        self.assertEqual(version.parent, (self.box.prefix / plugin).resolve())
        return version, json.loads((version / 'install-manifest.json').read_text())

    def test_setup_installs_every_plugin_with_bundles_shared_contract_and_pinned_digests(self):
        installed = {r['data']['plugin'] for r in self.receipts if r.get('ok') and 'plugin' in r.get('data', {})}
        self.assertLessEqual(set(FIVE), installed)
        identities = set()
        for plugin in FIVE:
            with self.subTest(plugin=plugin):
                version, manifest = self.package(plugin)
                self.assertEqual((manifest['plugin'], manifest['version']), (plugin, version.name))
                # The package digest pins the exact owned file list, and every file verifies.
                self.assertEqual(manifest['package_digest'], package_digest(manifest))
                verify_package_files(version, manifest)
                identities.add(manifest['installation_id'])
                # The worker bundle lives under the explicit agents root and pairs with this package.
                bundle = Path(manifest['bundle_dir'])
                self.assertEqual(bundle, self.box.agents / 'installations' / manifest['installation_id'] / plugin
                                 / manifest['version'])
                checked = verify_bundle(bundle, manifest['installation_id'], plugin, manifest['version'],
                                        manifest['package_digest'])
                self.assertEqual(checked['bundle_digest'], manifest['bundle_digest'])
                assets = {a['path']: a for a in checked['manifest']['assets']}
                declared = meta(plugin)
                for worker in declared['workers']:
                    rel = 'workers/' + worker['id'].split('/', 1)[1] + '.md'
                    self.assertEqual((bundle / rel).read_bytes(),
                                     (ROOT / 'plugins' / plugin / worker['path']).read_bytes(), rel)
                    self.assertEqual(assets[rel]['id'], worker['id'])
                for rel in declared.get('worker_shared', SHARED_REQUIRED):
                    self.assertEqual((bundle / 'shared' / rel).read_bytes(),
                                     (ROOT / 'shared' / 'agents' / rel).read_bytes(), rel)
                # The package carries the coordination contract, job helpers and its pinned validator.
                for rel in ('shared/job-coordination.md', 'shared/job_cli.py', 'shared/job_acceptance_cli.py',
                            'shared/t3-runtime.md'):
                    self.assertEqual((version / rel).read_bytes(), (ROOT / rel).read_bytes(), rel)
                validator = version / 'scripts' / ADAPTERS[plugin]
                self.assertTrue(validator.is_file() and os.access(validator, os.X_OK), validator)
        self.assertEqual(len(identities), 1, 'one prefix has one installation identity')
        # setup wrote nowhere in HOME except the two explicit provider skill roots.
        written = {p.relative_to(self.box.home).parts[0] for p in self.box.home.rglob('*') if p.is_file()}
        self.assertLessEqual(written, {'provider-a', 'provider-b'})

    def test_every_operation_routes_from_both_adapters_to_the_installed_coordinator_entry(self):
        for plugin in FIVE:
            declared = meta(plugin)
            version, _ = self.package(plugin)
            entry_path = self.box.prefix / plugin / 'current' / declared['entry']
            entry = entry_path.read_text()
            with self.subTest(plugin=plugin, check='entry bytes'):
                self.assertEqual(entry_path.read_bytes(), (ROOT / 'plugins' / plugin / declared['entry']).read_bytes())
            for root in self.roots:
                with self.subTest(plugin=plugin, root=root.parent.name):
                    skill = root / f't3-{plugin}' / 'SKILL.md'
                    receipt = json.loads((skill.parent / '.t3-plugins-skill.json').read_text())
                    self.assertEqual((receipt['entry'], receipt['sha256']), (str(entry_path), sha(skill.read_bytes())))
                    text = skill.read_text()
                    self.assertIn('Read the installed entry file at ' + json.dumps(str(entry_path)), text)
                    if declared.get('default_operation'):
                        self.assertIn('Default workflow: `' + declared['default_operation'] + '`.', text)
                        self.assertNotIn('Options:', text)
                    else:
                        listed = re.search(r'Operations: (.+)\.\n', text).group(1)
                        self.assertEqual(re.findall(r'`([^`]+)`', listed), declared['operations'])
                    self.assertIn('This adapter grants no additional authorization.', text)
            for op in declared['operations']:
                with self.subTest(plugin=plugin, op=op):
                    # The installed entry names the operation (table row, bullet or bold heading).
                    self.assertRegex(entry, r'[`*]' + re.escape(op) + r'\b')
                    prompt = self.box.t3('prompt', plugin, op).stdout
                    self.assertEqual(prompt, f'Read {entry_path} and run: {op}\n')
            with self.subTest(plugin=plugin, check='PKG references'):
                for rel in set(re.findall(r'`PKG/([\w./-]+)`', entry)):
                    self.assertTrue((version / rel).exists(), f'{plugin} entry names missing PKG/{rel}')
        coordinated = {p for p in FIVE if '`PKG/shared/job-coordination.md`' in
                       (self.box.prefix / p / 'current' / 'entry.md').read_text()}
        self.assertLessEqual(COORDINATED, coordinated)

    def test_agents_list_and_show_inspect_installed_bundles_read_only(self):
        before = tree_digest(self.box.prefix, self.box.agents, self.box.base / 'config')
        rows = json_lines(self.box.t3('agents', 'list').stdout)
        expected = {w['id']: (p, w['role']) for p in (*FIVE, 'ralph', 'focus-group') for w in meta(p)['workers']}
        self.assertEqual({r['id'] for r in rows}, set(expected))
        self.assertEqual(len(expected), 16)
        self.assertEqual(len([w for w in expected if w.split('/')[0] in FIVE]), 11)
        for row in rows:
            plugin, role = expected[row['id']]
            version, manifest = self.package(plugin)
            self.assertEqual((row['plugin'], row['version'], row['role'], row['integrity'], row['override_status'],
                              row['bundle_digest']),
                             (plugin, version.name, role, 'ok', 'disabled', manifest['bundle_digest']))
        only = json_lines(self.box.t3('agents', 'list', 'babysitter').stdout)
        self.assertEqual({r['id'] for r in only}, {'babysitter/pr-maintainer', 'babysitter/pr-reviewer'})
        shown = json.loads(self.box.t3('agents', 'show', 'imps', 'reviewer').stdout)
        source = (ROOT / 'plugins/imps/agents/reviewer.md').read_bytes()
        self.assertIn(source.decode(), shown['definition'])
        self.assertEqual((shown['provenance']['base_sha256'], shown['provenance']['override_status']),
                         (sha(source), 'disabled'))
        self.assertEqual(Path(shown['provenance']['bundle_dir']), Path(self.package('imps')[1]['bundle_dir']))
        self.assertTrue(shown['provenance']['shared_paths'])
        missing = self.box.t3('agents', 'show', 'imps', 'no-such-worker', check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(tree_digest(self.box.prefix, self.box.agents, self.box.base / 'config'), before)

    def test_doctor_checks_installed_integrity_without_claiming_provider_behavior(self):
        proc = self.box.t3('doctor')
        rows = {r['plugin']: r for r in json_lines(proc.stdout)}
        self.assertLessEqual(set(FIVE), set(rows))
        for plugin in FIVE:
            self.assertEqual((rows[plugin]['ok'], rows[plugin]['errors']), (True, []), plugin)
            self.assertIn('provider behavior not tested', rows[plugin]['scope'])
        # Re-running install is idempotent and keeps the active snapshot.
        version, _ = self.package('babysitter')
        again = json.loads(self.box.run([sys.executable, INSTALL, '--plugin', 'babysitter', '--prefix',
                                         self.box.prefix, '--agents-root', self.box.agents]).stdout)
        self.assertEqual((again['data']['action'], again['data']['version']), ('already_installed', version.name))


class InstalledUninstallTest(unittest.TestCase):
    """Owned uninstall removes package and bundle bytes only; user files and overrides survive."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='t3p-uninstall-')
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))
        self.root = self.box.home / 'skills'
        for plugin in ('imps', 'babysitter'):
            self.box.t3('setup', plugin, '--root', self.root)

    def test_uninstall_preserves_overrides_config_user_files_and_other_plugins(self):
        box = self.box
        version = (box.prefix / 'imps' / 'current').resolve()
        manifest = json.loads((version / 'install-manifest.json').read_text())
        bundle = Path(manifest['bundle_dir'])
        override = box.agents / 'overrides' / 'imps' / 'reviewer.md'
        override.parent.mkdir(parents=True)
        override.write_text('---\nworker_id: imps/reviewer\n---\nPrefer short findings.\n')
        box.t3('agents', 'enable-override', 'imps/reviewer', '--base-digest', manifest['bundle_digest'])
        listed = {r['id']: r for r in json_lines(box.t3('agents', 'list', 'imps').stdout)}
        self.assertEqual(listed['imps/reviewer']['override_status'], 'enabled')
        config = box.config / 't3-plugins' / 'workers.json'
        notes = version / 'operator-notes.txt'
        notes.write_text('mine\n')
        adapter_note = self.root / 't3-imps' / 'notes.md'
        adapter_note.write_text('operator file beside the adapter\n')
        kept = {p: p.read_bytes() for p in (override, config, notes, adapter_note)}
        baby_before = tree_digest(box.prefix / 'babysitter', box.agents / 'installations' /
                                  manifest['installation_id'] / 'babysitter')

        removed = json.loads(box.t3('uninstall', 'imps').stdout.splitlines()[-1])
        self.assertTrue(removed['ok'], removed)
        self.assertTrue(removed['data']['state_untouched'])
        adapter = json.loads(box.t3('skills', 'uninstall', 'imps', '--root', self.root).stdout)
        self.assertTrue(adapter['removed'])

        for path, data in kept.items():
            self.assertEqual(path.read_bytes(), data, path)
        self.assertFalse((version / 'entry.md').exists())
        self.assertFalse((version / 'install-manifest.json').exists())
        self.assertFalse(bundle.exists(), 'every owned, verified bundle file is removed')
        self.assertFalse((self.root / 't3-imps' / 'SKILL.md').exists())
        self.assertTrue((box.agents / 'claims.json').is_file())
        self.assertEqual(tree_digest(box.prefix / 'babysitter', box.agents / 'installations' /
                                     manifest['installation_id'] / 'babysitter'), baby_before)
        doctor = json.loads(box.t3('doctor', 'babysitter').stdout)
        self.assertEqual((doctor['ok'], doctor['errors']), (True, []))
        self.assertEqual({r['id'] for r in json_lines(box.t3('agents', 'list').stdout)},
                         {'babysitter/pr-maintainer', 'babysitter/pr-reviewer'})


if __name__ == '__main__':
    unittest.main()
