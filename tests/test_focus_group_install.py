"""focus-group REQ-INSTALL and REQ-ARCHITECTURE: the installed, relocated artifact.

The existing installer (`scripts/catalog.py install`, which runs `scripts/install.py`) writes the plugin package and
its external worker bundle into a temporary prefix. That prefix is then moved and adopted through the catalog's own
`adopt` route, and every focus-group helper runs from the moved package: `doctor`, planning, pack validation, the
invented fixture study's ingestion, the pinned stage validator, synthesis, the fidelity review and the portable
export. Those processes start in a temporary working directory with no source path on `PYTHONPATH`, and a
`sitecustomize` audit hook records any file they open or list under the source checkout; the tests require none.
Damaged packages (a missing template, a changed helper, an incomplete worker bundle, an unadopted move) are refused by
the installed doctor, the catalog doctor and job creation alike. Nothing calls a model, a browser, T3 or GitHub.
Handoff and lifecycle cases run in their own modules under the same 600-second deadline.
"""
import ast
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.focus_group_install_fixtures import (  # noqa: E402
    BEFORE, MODEL_ID, OPERATIONS, PLUGIN_MODULES, SHARED_CONTRACTS, STATE, WORKERS,
    InstalledHost, PristineFixture, RelocatedInstallCase, Swap, audit_rows, audited, catalog, fg3, fg4,
    install, run_installed, setUpModule, sha, tearDownModule,
)


class RelocatedInstallTest(RelocatedInstallCase):
    def test_1_an_unadopted_move_is_refused_then_adoption_verifies_and_routes_to_the_moved_package(self):
        inst, base = self.inst, STATE['base'] / 'route'
        base.mkdir(exist_ok=True)
        self.assertFalse(inst['original_prefix'].exists())
        if not STATE.get('adopted'):
            # Before adoption the moved prefix is not the owned locator: the installed doctor and job creation refuse.
            code, out, _ = run_installed(inst['package'], 'scripts/study.py', 'doctor', env=inst['env'], cwd=base)
            self.assertEqual(code, 1, out)
            self.assertEqual(out['data']['package_integrity']['state'], 'failed')
            self.assertIn('explicit adoption is required', ' '.join(out['data']['package_integrity']['problems']))
            listed = catalog(inst['env'], inst['prefix'], inst['agents'], 'agents', 'list', 'focus-group')
            self.assertNotEqual(listed.returncode, 0)
        self.adopt()
        env = inst['env']
        entry = Path(catalog(env, inst['prefix'], inst['agents'], 'path', 'focus-group').stdout.strip())
        self.assertEqual(entry, inst['prefix'] / 'focus-group' / 'current' / 'entry.md')
        self.assertEqual(entry.resolve().parent, inst['package'])
        picker = catalog(env, inst['prefix'], inst['agents'], 'prompt', 'focus-group').stdout
        self.assertIn(f'Read {entry}.', picker)
        self.assertIn('Options: plan, run, status, doctor.', picker)
        routed = catalog(env, inst['prefix'], inst['agents'], 'prompt', 'focus-group', 'status', 'pantry-planner-onboarding')
        self.assertEqual(routed.stdout.strip(), f'Read {entry} and run: status pantry-planner-onboarding')
        doctor = catalog(env, inst['prefix'], inst['agents'], 'doctor', 'focus-group')
        row = json.loads(doctor.stdout.splitlines()[-1])
        self.assertEqual((doctor.returncode, row['ok'], row['errors']), (0, True, []), doctor.stdout + doctor.stderr)
        # The installed manifest's own routes reach every operation and nothing else.
        meta = json.loads((inst['package'] / 'plugin.json').read_text())
        self.assertEqual(meta['operations'], OPERATIONS)

        def route(request):
            return next((r['operation'] for r in meta['routes'] if re.fullmatch(r['pattern'], request)), None)
        for request, expected in {'doctor': 'doctor', 'plan https://staging.example/welcome first screen': 'plan',
                                  'plan pantry-planner-onboarding': 'plan', 'run pantry-planner-onboarding': 'run',
                                  'resume pantry-planner-onboarding': 'resume', 'cancel pantry-planner-onboarding': 'cancel',
                                  'status pantry-planner-onboarding': 'status', 'run': None, 'publish the report': None}.items():
            with self.subTest(request=request):
                self.assertEqual(route(request), expected)
        # Worker ownership: the catalog lists the three workers from the moved prefix with verified integrity.
        rows = [json.loads(line) for line in catalog(env, inst['prefix'], inst['agents'], 'agents', 'list',
                                                      'focus-group').stdout.splitlines()]
        self.assertEqual({r['id'] for r in rows}, set(WORKERS), rows)


    def test_2_installed_doctor_verifies_digests_bundle_templates_and_schemas_without_the_source(self):
        self.adopt()
        inst = self.inst
        base = STATE['base'] / 'doctor'
        base.mkdir(exist_ok=True)
        env = audited(inst['env'], base)
        caps = base / 'caps.json'
        caps.write_text(json.dumps(fg4.CAPS))
        code, out, err = run_installed(inst['package'], 'scripts/study.py', 'doctor', '--capabilities', caps, env=env,
                                       cwd=base)
        self.assertEqual(code, 0, (out, err))
        data = out['data']
        integrity = data['package_integrity']
        self.assertEqual((integrity['state'], integrity['problems']), ('verified', []))
        self.assertEqual((integrity['package_digest'], integrity['bundle_digest']),
                         (inst['manifest']['package_digest'], inst['manifest']['bundle_digest']))
        for rel in ('templates/study-draft.example.json', 'templates/capture-manifest.example.json',
                    'references/report-contract.md', 'scripts/validate_study.py', 'shared/job_acceptance_cli.py',
                    *(f'shared/agents/{name}' for name in SHARED_CONTRACTS), *(f'agents/{w.split("/")[1]}.md' for w in WORKERS)):
            self.assertTrue(data['package_files'].get(rel), rel)
        self.assertTrue(all(data['package_files'].values()))
        self.assertTrue(data['catalog']['suggested_panel_possible'])
        self.assertEqual(data['writes'], 'none: doctor reads files and creates no study, job or task')
        self.assertFalse((base / 'xdg-state').exists())
        # The bundle carries each worker and every shared worker contract, byte for byte as packaged.
        bundle = Path(inst['manifest']['bundle_dir'])
        assets = {a['path']: a for a in json.loads((bundle / 'manifest.json').read_text())['assets']}
        for worker in WORKERS:
            name = worker.split('/')[1]
            self.assertEqual((bundle / f'workers/{name}.md').read_bytes(),
                             (inst['package'] / f'agents/{name}.md').read_bytes())
            self.assertEqual(assets[f'workers/{name}.md']['id'], worker)
        for name in SHARED_CONTRACTS:
            self.assertEqual((bundle / 'shared' / name).read_bytes(), (inst['package'] / 'shared/agents' / name).read_bytes())
        for rel in ('templates/study-draft.example.json', 'templates/capture-manifest.example.json'):
            listed = next(f for f in inst['manifest']['files'] if f['path'] == rel)
            self.assertEqual(listed['sha256'], sha((inst['package'] / rel).read_bytes()))
        rows = audit_rows(base)
        self.assertEqual([r['script'] for r in rows], [str(inst['package'] / 'scripts' / 'study.py')])
        self.assertEqual([r['hits'] for r in rows], [[]])


    def test_3_installed_helpers_plan_validate_run_and_export_an_invented_study_without_the_source(self):
        self.adopt()
        inst = self.inst
        base = STATE['base'] / 'study'
        base.mkdir()
        env = audited(inst['env'], base)
        with Swap(inst, env, base):
            h = InstalledHost(base, inst['package'])
            # Planning and pack validation (with a quarantined planted marker and its sanitised derivative), job
            # creation pinned to the moved package, pilots, ingestion, journeys and the pinned stage validator.
            fg4.build_study(h)
            job = h.job_state()
            self.assertEqual(Path(job['pins']['focus-group']['package_dir']), inst['package'])
            pinned = catalog(inst['env'], inst['prefix'], inst['agents'], '--job', h.root / h.view['study_id'] / 'job.json',
                             'path', 'focus-group')
            self.assertEqual((pinned.returncode, pinned.stdout.strip()), (0, str(inst['package'] / 'entry.md')),
                             pinned.stderr)
            # Delegated synthesis, a fresh reviewer of another lineage, acceptance and the portable export.
            _, record = h.bind_analysis()
            code, out = h.run_analysis(fg4.synthesis_for(h, record))
            self.assertEqual(code, 0, out)
            self.assertEqual(h.accept('analysis')[0], 0)
            code, out = h.render()
            self.assertEqual(code, 0, out)
            bundle = Path(out['data']['bundle'])
            h.bind_review(bundle)
            h.run_review()
            code, out = h.accept('review')
            self.assertEqual((code, out.get('accepted')), (0, True), out)
            exported = h.rp_ok(*h.study('export'), '--bundle', bundle, '--out', base / 'export')
            self.assertEqual((exported['review_status'], exported['external_actions']), ('reviewed', []))
            moved = base / 'carried elsewhere' / 'export'
            moved.parent.mkdir()
            os.rename(base / 'export', moved)
            checked = h.rp_ok('verify-export', '--bundle', moved)
            self.assertEqual(checked['review_status'], 'reviewed')
            status = h.rp_ok(*h.study('status'))
            self.assertEqual((status['review_status'], status['complete']), ('reviewed', False))  # one journey is a gap
            text = '\n'.join(p.read_text() for p in moved.rglob('*') if p.suffix in ('.md', '.json'))
            self.assertNotIn(str(base), text)
            self.assertNotIn(str(ROOT), text)
            STATE['export'] = moved
        rows = audit_rows(base)
        scripts = {Path(r['script']).name for r in rows}
        self.assertTrue({'study.py', 'evidence.py', 'lifecycle.py', 'report.py', 'job_cli.py',
                         'job_acceptance_cli.py'} <= scripts, scripts)
        outside = sorted({r['script'] for r in rows if not Path(r['script']).is_relative_to(inst['prefix'])})
        self.assertEqual(outside, [], 'every audited helper ran from the moved prefix')
        touched = {(Path(r['script']).name, r['cwd'], h) for r in rows for h in r['hits']}
        self.assertEqual(sorted(touched), [], 'no helper touched the source checkout')
        # Helpers start in the temporary directory; the acceptance helper runs the pinned validator inside its package.
        self.assertEqual({r['cwd'] for r in rows if r['cwd'] != str(base)}, {str(inst['package'])})
        self.assertIn('validate_study.py', scripts)
        self.assertGreater(len(rows), 50)


    def test_4_the_installed_helpers_run_on_python_3_10(self):
        python = shutil.which('python3.10')
        if not python:
            self.skipTest('python3.10 is not installed here; 3.10 support of the installed artifact is unverified')
        self.adopt()
        inst = self.inst
        base = STATE['base'] / 'py310'
        base.mkdir(exist_ok=True)
        env = audited(inst['env'], base)
        caps = base / 'caps.json'
        caps.write_text(json.dumps(fg4.CAPS))
        code, out, err = run_installed(inst['package'], 'scripts/study.py', 'doctor', '--capabilities', caps, env=env,
                                       cwd=base, python=python)
        self.assertEqual((code, out['data']['python'][:5], out['data']['package_integrity']['state']),
                         (0, '3.10.', 'verified'), err)
        if 'export' in STATE:
            code, out, err = run_installed(inst['package'], 'scripts/report.py', 'verify-export', '--bundle',
                                           STATE['export'], env=env, cwd=base, python=python)
            self.assertEqual((code, out['data']['review_status']), (0, 'reviewed'), err)
        pack = base / 'pack'
        files = fg4.fixtures.write_pack(pack)
        manifest = base / 'manifest.json'
        manifest.write_text(json.dumps(fg4.fixtures.manifest(files)))
        code, out, err = run_installed(inst['package'], 'scripts/evidence.py', 'pack', '--state-root', base / 'jobs',
                                       '--study', 'py310-study', '--input', manifest, env=env, cwd=base, python=python)
        self.assertEqual((code, out['data']['stimulus']['manifest_sha256'] is not None), (0, True), (out, err))
        self.assertEqual(sorted({h for r in audit_rows(base) for h in r['hits']}), [])



class DamagedPackageTest(unittest.TestCase):
    """A missing bundled asset, a changed helper and an incomplete worker bundle are each refused by the installed
    doctor, the catalog doctor and job creation; restoring the bytes makes the same package acceptable again."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        seed = cls()
        seed.base = Path(cls.tmp.name).resolve() / 'case'
        seed.base.mkdir()
        seed.prepare_fixture()
        cls.pristine = PristineFixture(seed.base, seed.inst, seed.h, seed.job_spec)

    def setUp(self):
        self.base = self.pristine.base
        self.inst, self.h, self.job_spec = self.pristine.restore()

    def prepare_fixture(self):
        self.inst = install(self.base)
        work = self.base / 'work'
        work.mkdir()
        # An approved study and its job specification, made by the installed helpers before any damage.
        with Swap(self.inst, self.inst["env"], work):
            self.h = InstalledHost(work, self.inst['package'])
            self.h.view = self.h.plan(self.h.draft())
            self.h.approve(self.h.view)
            documents = {f'fi-{n + 1:02d}': self.h.document(n, 'first-impression', f'fi-{n + 1:02d}')
                         for n in range(len(self.h.view['cells']))}
            spec = self.h.ok('job-spec', '--state-root', self.h.root, '--study', self.h.view['study_id'],
                             '--installation-id', self.inst['installation'], '--documents',
                             self.h.write('fi-docs.json', documents), '--defer-journeys', '--capabilities',
                             self.h.catalog(), now=BEFORE)
        self.job_spec = self.h.write('job.json', spec['job'])

    def doctor(self):
        code, out, err = run_installed(self.inst['package'], 'scripts/study.py', 'doctor', env=self.inst['env'],
                                       cwd=self.base)
        return code, out, err

    def catalog_doctor(self):
        proc = catalog(self.inst['env'], self.inst['prefix'], self.inst['agents'], 'doctor', 'focus-group')
        return proc.returncode, json.loads(proc.stdout.splitlines()[-1])

    def create(self, job_id):
        proc = subprocess.run([sys.executable, str(self.inst['package'] / 'shared' / 'job_cli.py'), 'create',
                               '--state-root', str(self.h.root), '--job', job_id, '--input', str(self.job_spec),
                               '--prefix', str(self.inst['prefix']), '--agents-root', str(self.inst['agents'])],
                              capture_output=True, text=True, env=self.inst['env'], timeout=120)
        return proc.returncode, proc.stdout + proc.stderr

    def refused_then_restored(self, path, damage, problem):
        original = path.read_bytes()
        damage(path)
        code, out, err = self.doctor()
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(out['data']['package_integrity']['state'], 'failed')
        self.assertIn(problem, ' '.join(out['data']['package_integrity']['problems']))
        code, row = self.catalog_doctor()
        self.assertEqual((code, row['ok']), (1, False), row)
        study = self.h.view['study_id']
        code, out = self.create(study)
        self.assertEqual(code, 2, out)
        self.assertFalse((self.h.root / study / 'job.json').exists())
        path.write_bytes(original)
        self.assertEqual(self.doctor()[0], 0)
        self.assertEqual(self.catalog_doctor()[0], 0)
        code, out = self.create(study)
        self.assertEqual(code, 0, out)
        return row

    def test_a_missing_install_receipt_is_refused_without_misidentifying_a_source_checkout(self):
        self.refused_then_restored(self.inst['package'] / 'install-manifest.json', lambda p: p.unlink(),
                                   'missing install receipt')

    def test_a_missing_template_is_reported_and_refused(self):
        template = self.inst['package'] / 'templates' / 'study-draft.example.json'
        row = self.refused_then_restored(template, lambda p: p.unlink(), 'missing or unlisted')
        self.assertIn('missing_or_modified:templates/study-draft.example.json', row['errors'])
        template.unlink()
        code, out, _ = self.doctor()
        self.assertEqual((code, out['data']['package_files']['templates/study-draft.example.json']), (1, False))

    def test_a_changed_helper_is_reported_and_refused(self):
        helper = self.inst['package'] / 'scripts' / 'report.py'
        row = self.refused_then_restored(helper, lambda p: p.write_bytes(p.read_bytes() + b'\n# changed\n'),
                                         'integrity failure: scripts/report.py')
        self.assertIn('missing_or_modified:scripts/report.py', row['errors'])

    def test_an_incomplete_worker_bundle_is_reported_and_refused(self):
        analyst = Path(self.inst['manifest']['bundle_dir']) / 'workers' / 'analyst.md'
        row = self.refused_then_restored(analyst, lambda p: p.unlink(), 'bundle asset integrity failure: workers/analyst.md')
        self.assertTrue(any('installation_invalid' in e for e in row['errors']), row)

    def test_an_incomplete_package_without_its_job_runtime_never_runs(self):
        store = self.inst['package'] / 'core' / 'jobs' / 'store.py'
        store.unlink()
        proc = subprocess.run([sys.executable, str(self.inst['package'] / 'scripts' / 'study.py'), 'doctor'],
                              capture_output=True, text=True, env=self.inst['env'], cwd=self.base, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('core.jobs.store', proc.stderr)
        code, row = self.catalog_doctor()
        self.assertEqual((code, row['ok']), (1, False))
        self.assertIn('missing_or_modified:core/jobs/store.py', row['errors'])


class ArchitectureTest(unittest.TestCase):
    """Inspect the installed package: standard-library Python 3.10+, no launcher, poller, scheduler, SDK, fixed model
    ID or private material, and no workflow vocabulary in the generic core."""

    @property
    def package(self):
        return STATE['relocated']['package']

    def test_pinned_validator_rejects_bad_input_without_serializing_exception_text(self):
        import contextlib
        import importlib.util
        import io
        import types
        from unittest import mock
        program = self.package / 'scripts/validate_study.py'
        expected = {'accepted': False, 'requirement_outcomes': {}, 'error': 'validator_failure'}
        marker = 'INVENTED-VALIDATOR-MARKER'
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            malformed = base / 'malformed.json'
            malformed.write_text('{"unfinished":')
            non_object = base / 'list.json'
            non_object.write_text(json.dumps([marker]))
            for path in (base / marker, malformed, non_object):
                with self.subTest(input=path.name):
                    proc = subprocess.run([sys.executable, str(program), '--input', str(path)],
                                          capture_output=True, text=True, timeout=60)
                    self.assertEqual((proc.returncode, json.loads(proc.stdout)), (1, expected))
                    self.assertNotIn(marker, proc.stdout + proc.stderr)
                    self.assertNotIn(str(base), proc.stdout + proc.stderr)
        spec = importlib.util.spec_from_file_location('fixture_study_validator', program)
        validator = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, 'path', list(sys.path)):
            spec.loader.exec_module(validator)
        for error in (ValueError(marker), OSError(marker), RuntimeError(marker)):
            fake_report = types.SimpleNamespace(validate_observation=mock.Mock(side_effect=error))
            output = io.StringIO()
            with mock.patch.dict(sys.modules, {'report': fake_report}), contextlib.redirect_stdout(output):
                if isinstance(error, RuntimeError):
                    with self.assertRaises(RuntimeError):
                        validator.main(['--input', 'unused-observation.json'])
                    self.assertEqual(output.getvalue(), '')
                else:
                    self.assertEqual(validator.main(['--input', 'unused-observation.json']), 1)
                    self.assertEqual(json.loads(output.getvalue()), expected)

    def test_helpers_are_standard_library_python_3_10_without_launchers_pollers_or_schedulers(self):
        banned = {'subprocess', 'socket', 'threading', 'multiprocessing', 'asyncio', 'sched', 'selectors', 'http',
                  'urllib.request', 'webbrowser', 'concurrent'}
        stdlib = set(sys.stdlib_module_names)
        for path in sorted((self.package / 'scripts').glob('*.py')):
            with self.subTest(script=path.name):
                tree = ast.parse(path.read_text(), feature_version=(3, 10))
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported |= {a.name for a in node.names}
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        imported.add(node.module)
                    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, ('sleep', 'system', 'popen', 'fork', 'spawnv', 'execv'))
                tops = {name.split('.')[0] for name in imported}
                self.assertEqual(tops - stdlib - PLUGIN_MODULES, set(), 'only the standard library and the package')
                self.assertEqual({n for n in imported if n in banned or n.split('.')[0] in banned}, set())
        for rel in ('core/jobs/__init__.py', 'core/jobs/store.py', 'core/jobs/results.py', 'shared/lineage.py',
                    'shared/worker_registry.py', 'shared/job_cli.py', 'shared/job_acceptance.py'):
            ast.parse((self.package / rel).read_text(), feature_version=(3, 10))

    def test_no_fixed_model_ids_private_material_or_core_vocabulary(self):
        private = re.compile('/' + 'Users/|/' + 'home/|/tmp/[A-Za-z0-9._-]+-[0-9]+/|/var/' + 'folders/|'
                             + '|'.join(re.escape(v) for v in {getpass.getuser(), socket.gethostname()} if len(v) > 3))
        credential = re.compile(r'(?i)\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b')
        plugin_files = [p for p in self.package.rglob('*') if p.is_file() and p.parts[len(self.package.parts)] not in
                        ('core', 'shared') and p.name != 'install-manifest.json']
        fixtures = [ROOT / 'tests' / 'focus_group_fixtures.py',
                    ROOT / 'tests' / 'focus_group_install_fixtures.py'] + sorted(
            (ROOT / 'tests').glob('test_focus_group*.py'))
        for path in plugin_files + [f for f in fixtures if f.exists()]:
            text = path.read_text(errors='replace')
            with self.subTest(path=path.name):
                self.assertIsNone(private.search(text), 'machine path, user or host name')
                self.assertIsNone(credential.search(text), 'credential-shaped string')
                if path.suffix in ('.py', '.md', '.json') and path.parent.name != 'tests':
                    self.assertIsNone(MODEL_ID.search(text), 'fixed model ID')
        for path in (self.package / 'core').rglob('*.py'):
            text = path.read_text()
            for term in ('focus-group', 'focus_group', 'first-impression', 'journey', 'participant'):
                self.assertNotIn(term, text, f'{path.name} names {term}')

    def test_the_package_ships_no_browser_runtime_or_provider_sdk(self):
        names = {p.name.lower() for p in self.package.rglob('*')}
        for forbidden in ('playwright', 'selenium', 'puppeteer', 'chromedriver', 'node_modules', 'anthropic', 'openai',
                          'requirements.txt', 'package.json'):
            self.assertFalse(any(forbidden in n for n in names), forbidden)
        self.assertEqual(sorted(p.name for p in (self.package / 'scripts').iterdir() if p.is_file()),
                         ['authority.py', 'evidence.py', 'lifecycle.py', 'plan_review.py',
                          'report.py', 'study.py', 'validate_study.py'])



if __name__ == '__main__':
    unittest.main()
