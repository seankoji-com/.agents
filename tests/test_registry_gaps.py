"""Issue #28 REQ-REGISTRY gaps: custom job roots protect pins, legacy refusals name usable
versions, and every detected contract condition carries its stable error code.

Isolated HOME/XDG roots, prefix and agents root; no model, no network, no GitHub.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tests.test_jobs_stage3 as stage3  # noqa: E402  (module import: its classes are not re-collected)
from tests.support import CoreTestCase  # noqa: E402
from tests.test_rebuild_installed import Sandbox  # noqa: E402
from tests.test_rebuild_migration import strip_workers  # noqa: E402
from shared.error_codes import STABLE_CODES, code_of  # noqa: E402


def plan(manifest, job_id):
    return {'schema_version': 1, 'job_id': job_id, 'installation_id': manifest['installation_id'],
            'workflow': 'imps/run', 'owner': {'id': 'owner'}, 'objective': 'synthetic registry job',
            'requirements': {'R1': 'the fixture requirement holds'}, 'authorization': {'actions': ['read']},
            'constraints': ['Offline fixture only.'], 'dependencies': [{'key': 'imps', 'plugin': 'imps'}],
            'pins': {}, 'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
            'result_contract': {'schema_version': 1},
            'stages': [{'id': 'impl', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                        'execution_mode': 'direct', 'validator_dependency': 'imps', 'revision': 'impl-r1'}],
            'tasks': [], 'decisions': [], 'history': [], 'metrics': {}}


class RegistryGapTest(unittest.TestCase):
    """Job roots are indexed at creation; removal checks every recorded root."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='t3p-gaps-')
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))
        self.index = self.box.agents / 'job-index.json'

    def job(self, pkg, command, root, job_id, data=None, extra=()):
        argv = [sys.executable, Path(pkg) / 'shared' / 'job_cli.py', command, '--state-root', root, '--job', job_id,
                *extra]
        if data is not None:
            argv += ['--input', self.box.payload(data)]
        return self.box.run(argv, check=False)

    def create(self, pkg, root, job):
        from tests.model_selection_fixtures import attach_selection
        from tests.imps_plan_review_fixtures import select_legacy_imps_job
        manifest = json.loads((Path(pkg) / 'install-manifest.json').read_text())
        select_legacy_imps_job(job, self.box.private, Path(pkg), manifest, self.box.env)
        return self.job(pkg, 'create', root, job['job_id'], job,
                        extra=('--prefix', self.box.prefix, '--agents-root', self.box.agents,
                               '--config', self.box.config / 'agents' / 'workers.json'))

    def uninstall(self, version):
        return self.box.t3('uninstall', 'imps', '--version', version, check=False)

    def test_custom_root_job_blocks_removal_until_discarded(self):
        pkg, manifest = self.box.install('imps')
        root = self.box.base / 'elsewhere' / 'jobs'
        created = self.create(pkg, root, plan(manifest, 'custom-job'))
        self.assertEqual(created.returncode, 0, created.stderr)
        job_file = root / 'custom-job' / 'job.json'
        self.assertTrue(job_file.is_file())
        self.assertEqual(self.index.stat().st_mode & 0o777, 0o600)
        entry = json.loads(self.index.read_text())['jobs'][str(root / 'custom-job')]
        self.assertEqual(entry, {'state_root': str(root), 'job_id': 'custom-job', 'status': 'live'})

        refused = self.uninstall(pkg.name)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('version_referenced', refused.stdout)
        self.assertIn(str(root / 'custom-job'), refused.stdout)
        self.assertTrue((pkg / 'install-manifest.json').is_file())
        self.assertTrue(Path(manifest['bundle_dir']).is_dir())

        discarded = self.job(pkg, 'discard', root, 'custom-job',
                             {'caller': self.box.caller(manifest, 'imps/run'), 'reason': 'owner discarded it'})
        self.assertEqual(discarded.returncode, 0, discarded.stderr)
        self.assertEqual(json.loads(self.index.read_text())['jobs'][str(root / 'custom-job')]['status'], 'discarded')
        before = job_file.read_bytes()
        removed = self.uninstall(pkg.name)
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertFalse(pkg.exists())
        self.assertFalse(Path(manifest['bundle_dir']).exists())
        self.assertEqual(job_file.read_bytes(), before, 'removal never erases discarded job state')

    def test_missing_recorded_root_fails_closed_unless_cancelled(self):
        pkg, manifest = self.box.install('imps')
        cancelled_root, lost_root = self.box.base / 'cancelled-jobs', self.box.base / 'lost-jobs'
        for root, job_id in ((cancelled_root, 'cancelled-job'), (lost_root, 'lost-job')):
            created = self.create(pkg, root, plan(manifest, job_id))
            self.assertEqual(created.returncode, 0, created.stderr)
        cancelled = self.job(pkg, 'cancel', cancelled_root, 'cancelled-job',
                             {'caller': self.box.caller(manifest, 'imps/run'), 'reason': 'owner cancelled it'})
        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        shutil.rmtree(cancelled_root)
        shutil.rmtree(lost_root)

        refused = self.uninstall(pkg.name)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('recorded job state is missing or unreadable', refused.stdout)
        self.assertIn(str(lost_root / 'lost-job'), refused.stdout)
        self.assertNotIn(str(cancelled_root), refused.stdout)
        self.assertTrue((pkg / 'install-manifest.json').is_file())

    def test_corrupt_index_fails_closed_for_removal_and_creation(self):
        pkg, manifest = self.box.install('imps')
        self.index.write_text('{"schema_version": 1, "jobs": ')
        refused = self.uninstall(pkg.name)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('job root index is corrupt', refused.stdout)
        self.assertTrue((pkg / 'install-manifest.json').is_file())
        self.assertTrue(Path(manifest['bundle_dir']).is_dir())

        root = self.box.base / 'jobs'
        created = self.create(pkg, root, plan(manifest, 'blocked-job'))
        self.assertEqual(created.returncode, 2)
        self.assertIn('job root index is corrupt', created.stderr)
        self.assertFalse((root / 'blocked-job' / 'job.json').exists())

    def test_legacy_package_refusal_names_bundled_versions_with_stable_code(self):
        legacy, _ = self.box.install('imps', source=self.box.source_copy('imps', strip_workers, name='legacy'))
        current, manifest = self.box.install('imps')
        self.box.t3('activate', 'imps', legacy.name)
        root = self.box.base / 'jobs'
        refused = self.create(current, root, plan(manifest, 'new-job'))
        self.assertEqual(refused.returncode, 2)
        self.assertIn(f'job_error: pin_mismatch: legacy package has no worker bundle: imps (imps {legacy.name})',
                      refused.stderr)
        self.assertIn(f'installed versions with bundles: {current.name}', refused.stderr)
        self.assertNotIn('package digest missing', refused.stderr)
        self.assertFalse((root / 'new-job' / 'job.json').exists())
        self.assertNotIn(str(root / 'new-job'), self.index.read_text() if self.index.exists() else '')


class ErrorCodeParityTest(CoreTestCase):
    """Each stable code whose condition is detected is carried by a representative failure."""

    NOT_DETECTED = {'result_transport_unavailable', 'dispatch_unavailable', 'cancel_unconfirmed'}

    def raised(self, function, *args, **kwargs):
        try:
            function(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - the code, not the class, is under test
            return exc
        self.fail(f'{function.__name__} did not refuse')

    def store(self, mutate=None):
        from core.jobs.store import Store
        job = stage3.JobStateTests.base(None)
        if mutate:
            mutate(job)
        root = self.tmp / ('jobs-' + str(len(list(self.tmp.glob('jobs-*')))))
        store = Store(root, 'job-1')
        store.create(job)
        return store

    caller = {'actor': 'coordinator', 'installation_id': 'install-1', 'workflow': 'imps/run', 'package_digest': 'c' * 64}

    def test_each_detected_code_is_carried_by_a_representative_failure(self):
        from core import planning, schema
        from core.jobs import prepare, record_dispatch, retry_task, revise_plan
        from core.jobs.results import parse_result
        from shared.job_acceptance import review_handle, validate_stage
        sys.path.insert(0, str(ROOT / 'plugins' / 'elephant-goldfish' / 'scripts'))
        import thinking_state

        observed = {}

        def carried(code, error):
            self.assertEqual(code_of(error), code, str(error))
            observed[code] = str(error)

        carried('schema_invalid', self.raised(schema.validate, {}, 'plan'))
        carried('plan_invalid', self.raised(planning.build, {}, {}, state_root=self.tmp, plugin={'name': 'imps'}))

        repo = self.make_repo()
        run = self.init(self.plan(repo))
        binding = run.binding()
        (repo / 'drift.txt').write_text('changed after the binding was taken\n')
        _, env, _ = run.submit_raw('evidence', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                                'explanation': 'observed', 'binding': binding,
                                                'artifacts': [str(run.scratch('evidence.txt', 'observed\n'))]})
        self.assertEqual(env['error']['code'], 'stale_evidence', env)
        observed['stale_evidence'] = env['error']['message']

        store = self.store()
        carried('ownership_mismatch', self.raised(store.mutate, {**self.caller, 'workflow': 'ape/forage'}, lambda j: j))
        weakened = {**store.load(), 'requirements': {'R1': 'weakened'}}
        carried('undeclared_expansion', self.raised(revise_plan, store, self.caller, {'id': 'rev-1'}, weakened))
        for _ in range(3):
            record_dispatch(store, self.caller, 't0', {'kind': 'uncertain', 'request_id': 'req0'})
        carried('uncertain_dispatch', self.raised(record_dispatch, store, self.caller, 't0',
                                                  {'kind': 'uncertain', 'request_id': 'req0'}))

        deferred = self.store()
        record_dispatch(deferred, self.caller, 't0', {'kind': 'capacity-deferred', 'request_id': 'req0'})
        self.assertIs(deferred.load()['tasks'][0]['capacity_deferred'], True)
        observed['capacity_deferred'] = 'recorded task state'

        def exhausted(job):
            job['policy']['max_repair_cycles'] = 0
            job['tasks'][0]['status'] = 'failed'
        carried('attempt_budget_exhausted', self.raised(retry_task, self.store(exhausted), self.caller, 't0', 'retry'))

        pinned = self.store(lambda job: job['pins']['imps'].update(package_dir=str(self.tmp / 'gone')))
        carried('pin_mismatch', self.raised(prepare, pinned, self.caller, 't0', lambda dep, pin: False, lambda s: True))

        job_dir = self.tmp / 'artifact-job'
        (job_dir / 'artifacts' / 'tasks' / 't0').mkdir(parents=True)
        (job_dir / 'artifacts' / 'tasks' / 't0' / 'result.json').write_text('{"oversized": true}')
        envelope = json.dumps({'schema_version': 1, 'correlation': {},
                               'artifact': {'path': 'artifacts/tasks/t0/result.json', 'sha256': '0' * 64,
                                            'finding_count': 0, 'finding_ids': []}}).encode()
        carried('artifact_invalid', self.raised(parse_result, envelope, {'task_id': 't0'}, None))
        carried('artifact_oversize', self.raised(parse_result, envelope, {'task_id': 't0'}, job_dir, 4))

        carried('required_review_unavailable', self.raised(review_handle, {'handles': [], 'request_id': 'req0'}))

        def accepted_dependent(job):
            job['tasks'] = []
            for stage in job['stages']:
                stage['execution_mode'] = 'direct'
            job['stages'][1].update(status='accepted-at-snapshot',
                                    acceptance={'path': str(self.tmp / 'receipt.json'), 'sha256': '0' * 64})
        verdict = validate_stage(self.store(accepted_dependent), 's1', run_validator=False)
        self.assertFalse(verdict['accepted'])
        carried('dependency_stale', ValueError(verdict['reason']))

        budget = {'max_rounds': 5, 'rounds_performed': 1, 'limit_source': 'recorded'}
        previous = {'max_rounds': 4, 'rounds_performed': 1, 'limit_source': 'recorded'}
        error = self.raised(thinking_state.check_cold_read, {'cold_read': budget}, previous)
        self.assertIn('owner_decision_required', str(error))
        observed['owner_decision_required'] = str(error)

        self.assertEqual(set(observed) | self.NOT_DETECTED, STABLE_CODES)
        self.assertFalse(set(observed) & self.NOT_DETECTED)


if __name__ == '__main__':
    unittest.main()
