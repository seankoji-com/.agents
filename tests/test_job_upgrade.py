"""Same-job upgrades through installed packages; no live state or providers."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.jobs.store import MAX_STATE_BYTES, JobError, Store, _regular
from tests.test_rebuild_installed import Sandbox, tree_digest


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def with_state_limit(mebibytes):
    def mutate(plugin):
        path = plugin.parents[1] / 'core/jobs/store.py'
        setting = f'MAX_STATE_BYTES={MAX_STATE_BYTES // (1024*1024)}*1024*1024'
        source = path.read_text()
        if source.count(setting) != 1:
            raise AssertionError('fixture must replace exactly one state bound')
        path.write_text(source.replace(setting, f'MAX_STATE_BYTES={mebibytes}*1024*1024', 1))
    return mutate


class InstalledUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='job-upgrade-')
        self.addCleanup(self.tmp.cleanup)
        self.box = Sandbox(Path(self.tmp.name))

        source = self.box.source_copy('imps', with_state_limit(16), name='old-source')
        self.old, self.old_manifest = self.box.install('imps', source=source)
        self.caller = self.box.caller(self.old_manifest, 'imps/run')
        self.job_id = 'upgrade-fixture'
        self.box.create(self.old, self.plan())
        self.file = self.box.jobs / self.job_id / 'job.json'
        self.new, self.new_manifest = self.box.install('imps')

    def plan(self):
        return {'schema_version': 1, 'job_id': self.job_id,
                'installation_id': self.old_manifest['installation_id'],
                'workflow': 'imps/run', 'owner': {'id': 'fixture-owner'},
                'objective': 'preserve exact evidence', 'requirements': {'R1': 'retain evidence'},
                'authorization': {'actions': ['read', 'edit']}, 'constraints': ['No live services.'],
                'dependencies': [{'key': 'imps', 'plugin': 'imps'}], 'pins': {},
                'policy': {'max_repair_cycles': 20, 'max_artifact_bytes': 16777216},
                'result_contract': {'schema_version': 1},
                'stages': [{'id': 'stage', 'depends_on': [], 'requirements': ['R1'],
                            'status': 'accepted-at-snapshot', 'acceptance': {'fixture': 'prior'},
                            'execution_mode': 'workers', 'validator_dependency': 'imps',
                            'attempts': {'primary': 4, 'review': 3}, 'cycle': 4}],
                'tasks': [{'task_id': 'slot', 'stage_id': 'stage', 'logical_slot_id': 'implement',
                           'request_id': 'fixture-request', 'worker_id': 'imps/stage-executor',
                           'dependency_key': 'imps', 'status': 'pending', 'attempt': 5, 'cycle': 4,
                           'handles': [], 'followups': [], 'dispatch_retries': 0}],
                'decisions': [], 'history': [], 'metrics': {}}

    def decision(self):
        self.box.job(self.old, 'decision', self.job_id, {
            'caller': self.caller,
            'decision': self.box.owner_decision('upgrade-owner', 'Upgrade this fixture package.',
                                                'plan:upgrade-1')})

    def payload(self):
        return {'caller': self.caller,
                'revision': {'id': 'upgrade-1', 'owner_decision_id': 'upgrade-owner',
                             'reason': 'Preserve this same job with a newer installed package.'},
                'dependency_key': 'imps', 'expected_state_sha256': sha(self.file.read_bytes()),
                'expected_package_digest': self.new_manifest['package_digest']}

    def upgrade(self, payload=None):
        return self.box.job(self.new, 'upgrade-package', self.job_id, payload or self.payload(),
                            check=False, extra=('--prefix', self.box.prefix,
                                                '--agents-root', self.box.agents))

    def mutate_fixture(self, function):
        # Synthetic fixture setup uses the store transaction, never a live job.
        from shared.job_coordinator import pinned_store
        pinned_store(self.box.jobs, self.job_id).mutate(self.caller, function)

    def test_upgrade_crosses_old_limit_without_losing_provenance_or_resetting_budgets(self):
        self.assert_upgrade_preserves_history(16, 14)

    def test_upgrade_crosses_64_mib_limit_without_losing_history(self):
        source = self.box.source_copy('imps', with_state_limit(64), name='64-mib-source')
        self.old, self.old_manifest = self.box.install('imps', source=source)
        self.caller = self.box.caller(self.old_manifest, 'imps/run')
        self.job_id = 'upgrade-64-mib-fixture'
        self.box.create(self.old, self.plan())
        self.file = self.box.jobs / self.job_id / 'job.json'
        self.new, self.new_manifest = self.box.install('imps')
        self.assert_upgrade_preserves_history(64, 62)

    def assert_upgrade_preserves_history(self, old_limit_mib, history_mib):
        self.mutate_fixture(lambda job: (job['history'].append({'fixture': 'h' * (history_mib*1024*1024)}),
                                        job['tasks'][0].update(fixture_evidence='e' * (900*1024))) and None)
        self.decision()
        before = self.file.read_bytes()
        original = json.loads(before)
        self.assertLess(len(before), old_limit_mib*1024*1024)
        packages_before = tree_digest(self.old, self.new)
        # The original package cannot archive another complete plan within its ceiling.
        old_route = {'caller': self.caller,
                     'revision': {**self.payload()['revision'], 'adopt_keys': ['imps']},
                     'new_plan': {}}
        refused = self.box.job(self.old, 'plan-revision', self.job_id, old_route, check=False,
                               extra=('--prefix', self.box.prefix, '--agents-root', self.box.agents))
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('byte limit', refused.stderr)
        self.assertEqual(self.file.read_bytes(), before)

        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(Path(receipt['previous_state']['path']).read_bytes(), before)
        self.assertEqual(receipt['previous_state']['sha256'], sha(before))
        self.assertEqual(Path(receipt['previous_state']['path']).stat().st_mode & 0o777, 0o600)
        after = json.loads(self.file.read_bytes())
        self.assertGreater(len(self.file.read_bytes()), old_limit_mib*1024*1024)
        self.assertEqual(after['history'][:len(original['history'])], original['history'])
        for key in ('job_id', 'owner', 'requirements', 'authorization', 'constraints', 'policy', 'decisions'):
            self.assertEqual(after[key], original[key], key)
        for key in ('attempt', 'cycle', 'request_id', 'handles', 'fixture_evidence'):
            self.assertEqual(after['tasks'][0][key], original['tasks'][0][key], key)
        self.assertEqual(after['stages'][0]['attempts'], original['stages'][0]['attempts'])
        self.assertEqual(after['stages'][0]['status'], 'stale')
        self.assertIsNone(after['stages'][0]['acceptance'])
        self.assertEqual(after['pins']['imps']['package_digest'], self.new_manifest['package_digest'])
        self.assertEqual(tree_digest(self.old, self.new), packages_before)
        # Normal commands still enforce the executing package pin.
        self.assertNotEqual(self.box.job(self.old, 'status', self.job_id, check=False).returncode, 0)
        self.assertEqual(self.box.job(self.new, 'status', self.job_id, check=False).returncode, 0)
        self.assertEqual(self.box.pinned_package(self.job_id, 'imps'), self.new)

    def test_refuses_missing_owner_decision_without_writing_state(self):
        before = self.file.read_bytes()
        result = self.upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('owner decision required', result.stderr)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse((self.file.parent/'migrations').exists())

    def test_refuses_wrong_hash_digest_owner_and_unreconciled_work(self):
        self.decision()
        before = self.file.read_bytes()
        for field, value, error in [('expected_state_sha256', '0'*64, 'state hash'),
                                     ('expected_package_digest', '0'*64, 'target differs'),
                                     ('caller', {**self.caller, 'actor': 'worker'}, 'coordinator-only')]:
            with self.subTest(field=field):
                payload = self.payload();payload[field] = value
                result = self.upgrade(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertEqual(self.file.read_bytes(), before)
        self.mutate_fixture(lambda job: job['tasks'][0].update(uncertain_calls=1))
        before = self.file.read_bytes()
        result = self.upgrade()
        self.assertIn('reconciled owned work', result.stderr)
        self.assertEqual(self.file.read_bytes(), before)

    def test_normal_commands_refuse_unpinned_package_and_tampered_pins(self):
        result = self.box.job(self.new, 'status', self.job_id, check=False)
        self.assertIn('wrong executing package', result.stderr)
        self.decision()
        before = self.file.read_bytes()
        (self.old/'entry.md').write_text('tampered fixture')
        result = self.upgrade()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.file.read_bytes(), before)


class BoundsTests(unittest.TestCase):
    def test_state_bound_does_not_raise_input_or_artifact_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'large'
            with path.open('wb') as f:f.truncate(16*1024*1024+1)
            with self.assertRaisesRegex(JobError, 'oversized'):_regular(path)
            store = Store(d, 'fixture')
            store.path.mkdir()
            with store.file.open('wb') as f:f.truncate(MAX_STATE_BYTES+1)
            with self.assertRaisesRegex(JobError, 'oversized'):store.load()


if __name__ == '__main__':
    unittest.main()
