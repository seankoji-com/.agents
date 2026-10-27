"""Issue #28 Stage 5 legacy migration (REQ-COMPAT, REQ-REGISTRY, G-IMPS-LEGACY, G-EG-HANDOFF).

Old state stays readable through the rebuilt installed packages: imps major-version-2
gate runs keep their status/validate/report/cancel paths, major-version-1 runs are
refused with the previous-package route, and a legacy elephant-goldfish topic resolves
without being promoted. An older package installed without worker bundles keeps its
legacy operations, but cannot create or resume a new-format job; the job supplies its
pinned package instead. No migration step creates acceptance.

Isolated HOME/XDG roots, prefix and agents root; no model, no network, no GitHub.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import CoreTestCase  # noqa: E402
from tests.test_rebuild_installed import Sandbox, sha  # noqa: E402


def strip_workers(plugin_dir: Path):
    """Shape an older manifest: same plugin and operations, no managed worker catalog."""
    path = plugin_dir / 'plugin.json'
    meta = json.loads(path.read_text())
    meta.pop('workers', None)
    meta.pop('worker_shared', None)
    meta.pop('planning_review', None)  # Older workerless manifests predate the planning purpose hook.
    path.write_text(json.dumps(meta, indent=2) + '\n')


class LegacyStateTest(CoreTestCase):
    """Existing gate runs and thinking topics through the rebuilt installed packages."""

    def setUp(self):
        super().setUp()
        self.box = Sandbox(self.tmp / 'sandbox')

    def gate(self, pkg, *args):
        proc = self.box.run([sys.executable, pkg / 'cli.py', *args], check=False)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, proc.stdout + proc.stderr)
        return proc.returncode, json.loads(lines[0])

    def test_imps_v2_runs_keep_legacy_paths_and_v1_runs_get_the_previous_package_route(self):
        # A ready major-version-2 run recorded before the rebuild (source-tree gate, as an old package would).
        repo = self.make_repo()
        run = self.init(self.plan(repo))
        run.evidence('REQ-MULTILINE', run.scratch('evidence.txt', 'verified fixture evidence\n'))
        self.assertEqual(self.run_check(run)['result']['status'], 'passed')
        self.assertTrue(run.validate()['ready'])
        record = run.run_dir / 'run.json'
        before = record.read_bytes()

        pkg, _ = self.box.install('imps')
        args = ('--state-root', self.state_root, '--run-id', run.run_id)
        code, status = self.gate(pkg, 'status', *args)
        self.assertEqual((code, status['data']['run_id']), (0, run.run_id))
        self.assertEqual(status['data']['planning_review_status'], 'legacy-unreviewed')
        code, validated = self.gate(pkg, 'validate', *args)
        self.assertNotEqual(code, 0)
        self.assertIn('legacy-unreviewed', validated['error']['message'])
        code, report = self.gate(pkg, 'report', *args)
        self.assertNotEqual(code, 0)
        self.assertIn('legacy-unreviewed', report['error']['message'])
        self.assertEqual(record.read_bytes(), before, 'reading a legacy run never rewrites it')
        # Job metadata stays external: the new package created no job for the old run.
        self.assertFalse(self.box.jobs.exists())
        code, cancelled = self.gate(pkg, 'cancel', *args)
        self.assertEqual(code, 0, cancelled)
        self.assertEqual(json.loads(record.read_text())['schema_version'], 2)

        # A major-version-1 record is refused for every path, with the previous-package route.
        v1 = '20250101-000000-0000a1'
        old = self.state_root / 'runs' / v1
        old.mkdir(parents=True)
        (old / 'run.json').write_text(json.dumps({'schema_version': 1, 'run_id': v1, 'phase': 'checks'}))
        v1_bytes = (old / 'run.json').read_bytes()
        for command in ('status', 'validate', 'cancel'):
            code, refused = self.gate(pkg, command, '--state-root', self.state_root, '--run-id', v1)
            self.assertNotEqual(code, 0, command)
            self.assertEqual(refused['error']['code'], 'unsupported_version')
            self.assertIn("run's original package (its core/cli.py)", refused['error']['message'])
        self.assertEqual((old / 'run.json').read_bytes(), v1_bytes)

    def test_legacy_thinking_topic_resolves_but_is_never_promoted(self):
        pkg, _ = self.box.install('elephant-goldfish')
        root = self.tmp / 'thinking'
        topic = root / 'legacy-topic'
        topic.mkdir(parents=True)
        (topic / 'discovery.md').write_text('# Discovery\n\nThe retry policy is undocumented.\n')
        (topic / 'spec.md').write_text('# Spec\n\n[REQ-DOC] The retry policy is written down.\n')
        (topic / 'handoff.md').write_text('Old handoff without provenance.\n')
        (topic / 'meta.json').write_text(json.dumps({'output_type': 'research', 'title': 'Legacy topic'}))
        snapshot = {p.name: p.read_bytes() for p in topic.iterdir()}
        state = [sys.executable, pkg / 'scripts' / 'thinking_state.py', '--root', root]
        listed = json.loads(self.box.run([*state, 'list'], cwd=self.tmp).stdout)
        self.assertEqual([t['slug'] for t in listed['topics']], ['legacy-topic'])
        resolved = json.loads(self.box.run([*state, 'resolve', 'legacy-topic'], cwd=self.tmp).stdout)
        self.assertNotEqual(resolved['next_phase'], 'complete')
        self.assertTrue(resolved['hold_reason'])
        gate = self.box.run([*state, 'gate', 'legacy-topic', '--require', 'discovery,spec,handoff'],
                            cwd=self.tmp, check=False)
        self.assertNotEqual(gate.returncode, 0)
        check = self.box.run([sys.executable, pkg / 'scripts' / 'render_handoff.py', 'legacy-topic', '--root', root,
                              '--check'], cwd=self.tmp, check=False)
        self.assertNotEqual(check.returncode, 0)
        self.assertEqual({p.name: p.read_bytes() for p in topic.iterdir()}, snapshot)


class LegacyPackageActivationTest(unittest.TestCase):
    """An older package without bundles keeps legacy operations but cannot own new-format jobs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='t3p-legacy-')
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))

    def plan(self, manifest, job_id):
        return {'schema_version': 1, 'job_id': job_id, 'installation_id': manifest['installation_id'],
                'workflow': 'imps/run', 'owner': {'id': 'owner'}, 'objective': 'synthetic migration job',
                'requirements': {'R1': 'the fixture requirement holds'}, 'authorization': {'actions': ['read']},
                'constraints': ['Offline fixture only.'], 'dependencies': [{'key': 'imps', 'plugin': 'imps'}],
                'pins': {}, 'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
                'result_contract': {'schema_version': 1},
                'stages': [{'id': 'impl', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                            'execution_mode': 'direct', 'validator_dependency': 'imps', 'revision': 'impl-r1'}],
                'tasks': [], 'decisions': [], 'history': [], 'metrics': {}}

    def test_activating_a_bundleless_package_refuses_new_jobs_and_supplies_the_pinned_path(self):
        box = self.box
        legacy, legacy_manifest = box.install('imps', source=box.source_copy('imps', strip_workers, name='legacy'))
        self.assertNotIn('bundle_dir', legacy_manifest)
        current, manifest = box.install('imps')
        self.assertTrue(manifest['bundle_dir'])
        from tests.imps_plan_review_fixtures import select_legacy_imps_job
        job = select_legacy_imps_job(self.plan(manifest, 'pinned-job'), box.private, current, manifest, box.env)
        created = box.create(current, job)
        job_file = Path(created['job'])
        before = job_file.read_bytes()
        pin = json.loads(before)['pins']['imps']
        self.assertEqual(pin['package_dir'], str(current))

        box.t3('activate', 'imps', legacy.name)
        self.assertEqual((box.prefix / 'imps' / 'current').resolve(), legacy)
        # Legacy operations still route to the active legacy entry and its gate CLI.
        self.assertEqual(box.t3('prompt', 'imps', 'status').stdout,
                         f"Read {box.prefix / 'imps' / 'current' / 'entry.md'} and run: status\n")
        legacy_status = box.run([sys.executable, legacy / 'cli.py', 'status', '--state-root', box.base / 'gate',
                                 '--run-id', '20250101-000000-0000ab'], check=False)
        self.assertEqual(json.loads(legacy_status.stdout)['error']['code'], 'run_not_found')
        diagnosed = json.loads(box.t3('doctor', 'imps', check=False).stdout)
        self.assertIn('worker_bundle_missing', diagnosed['errors'])

        # New-format job creation through the legacy package (or its active pointer) is refused.
        for pkg in (legacy, current):
            from tests.model_selection_fixtures import attach_selection
            fixture_plan = json.loads(json.dumps(job))
            fixture_plan['job_id'] = 'new-job'
            refused = box.job(pkg, 'create', 'new-job', fixture_plan, check=False,
                              extra=('--prefix', box.prefix, '--agents-root', box.agents))
            self.assertEqual(refused.returncode, 2, pkg.name)
            # A legacy receipt carries neither package digest nor bundle; either refusal names the plugin.
            self.assertRegex(refused.stderr, r'(package digest missing|legacy package has no worker bundle): imps')
        self.assertFalse((box.jobs / 'new-job' / 'job.json').exists())

        # Resuming the existing job through the legacy package refuses and names the pinned route.
        for command in ('overview', 'status'):
            wrong = box.job(legacy, command, 'pinned-job', check=False)
            self.assertEqual(wrong.returncode, 2)
            self.assertIn('wrong executing package', wrong.stderr)
        argv = pin['compatible_pinned_argv']
        self.assertEqual(argv[:2] + argv[3:], ['agents', '--job', 'path', 'imps'])
        recovered = Path(box.t3(*argv[1:]).stdout.strip())
        self.assertEqual(recovered, current / 'entry.md')
        self.assertEqual(box.job(recovered.parent, 'overview', 'pinned-job')['job_id'], 'pinned-job')
        # The pinned package cannot be removed while the job is resumable.
        removal = box.t3('uninstall', 'imps', '--version', current.name, check=False)
        self.assertIn('version_referenced', removal.stdout)
        self.assertEqual(job_file.read_bytes(), before)

    def test_install_upgrade_and_rollback_never_manufacture_acceptance(self):
        box = self.box
        current, manifest = box.install('imps')
        from tests.imps_plan_review_fixtures import select_legacy_imps_job
        box.create(current, select_legacy_imps_job(self.plan(manifest, 'no-accept'), box.private, current, manifest, box.env))
        job_file = box.jobs / 'no-accept' / 'job.json'
        before = job_file.read_bytes()
        caller = box.caller(manifest, 'imps/run')
        newer, _ = box.install('imps', source=box.source_copy('imps', lambda p: (p / 'playbooks' / 'audit.md').write_text(
            (p / 'playbooks' / 'audit.md').read_text() + '\n<!-- later release -->\n')))
        box.t3('activate', 'imps', current.name)
        box.t3('activate', 'imps', newer.name)
        self.assertEqual(job_file.read_bytes(), before)
        overview = box.job(current, 'overview', 'no-accept')
        self.assertEqual([s['status'] for s in overview['stages']], ['pending'])
        self.assertEqual(overview['requirement_coverage'], {'R1': [{'stage': 'impl', 'status': 'pending'}]})
        validate = box.accept(current, 'validate', 'no-accept', {'stage_id': 'impl'})
        self.assertEqual(validate.returncode, 1)
        self.assertFalse(json.loads(validate.stdout)['accepted'])
        observed = box.private / 'descriptor.json'
        observed.write_text(json.dumps({'state_root': str(box.base / 'gate'), 'run_id': '20250101-000000-0000ab'}))
        path = box.job(current, 'observation', 'no-accept', {'caller': caller, 'stage_id': 'impl',
                                                              'input_file': str(observed)})['path']
        final = box.accept(current, 'validate-final', 'no-accept', {
            'caller': caller, 'input_file_by_stage': {'impl': path},
            'validator_argv_by_stage': {'impl': [str(current / 'scripts/validate_stage.py'), '--state-root',
                                                 str(box.base / 'gate'), '--run-id', '20250101-000000-0000ab']}})
        self.assertEqual(final.returncode, 1, final.stdout + final.stderr)
        state = json.loads(job_file.read_text())
        self.assertIsNone(state['stages'][0]['acceptance'])
        self.assertNotEqual(state['stages'][0]['status'], 'accepted-at-snapshot')
        self.assertEqual(sha(json.dumps(state['pins'], sort_keys=True).encode()),
                         sha(json.dumps(json.loads(before)['pins'], sort_keys=True).encode()))


if __name__ == '__main__':
    unittest.main()
