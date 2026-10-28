"""Public CLI regressions with genuine, distinct installed acceptance packages."""
import json
from pathlib import Path
import tempfile
import unittest

from tests import test_planning_review as panel
from tests.test_rebuild_installed import Sandbox
from tests.test_plan_review_installed_matrix import relocate


class ExecutingPackagePinTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.box = Sandbox(Path(temporary.name))
        source_a = self.box.source_copy('imps')
        worker = source_a / 'plugins/imps/agents/reviewer.md'
        worker.write_text(worker.read_text() + '\nSynthetic executing package A worker.\n')
        self.a, self.manifest = self.box.install('imps', source=source_a)
        source_b = self.box.source_copy('imps')
        acceptance = source_b / 'shared/model_selection.py'
        acceptance.write_text(acceptance.read_text() + '\n# Synthetic active B acceptance bytes.\n')
        self.b, _ = self.box.install('imps', source=source_b)
        self.assertNotEqual((self.a / 'shared/model_selection.py').read_bytes(),
                            (self.b / 'shared/model_selection.py').read_bytes())
        self.assertEqual((self.box.prefix / 'imps/current').resolve(), self.b)
        # Use the established public CLI harness without inheriting its tests.
        self.f = panel.PlanningReviewTests('test_delegated_public_acceptance_and_installed_parent_consumption')
        self.f.box, self.f.package, self.f.manifest = self.box, self.a, self.manifest
        panel.PlanningReviewTests.serial = getattr(panel.PlanningReviewTests, 'serial', 0)
        self.f.setUp()
        self.f.installed_only = True

    def exercise(self):
        f = self.f
        f.create()
        job = self.box.state_of(f.job_id)
        pin = job['pins']['workflow']
        self.assertEqual(Path(pin['package_dir']), f.package)
        self.assertEqual(job['dependencies'][0]['package_dir'], str(f.package))
        self.assertEqual(pin['package_digest'], f.manifest['package_digest'])
        self.assertIn('Synthetic executing package A worker.',
                      pin['effective_workers']['imps/reviewer']['bytes'])
        attempt = f.attempt()  # Public launch prepares the pinned worker brief.
        self.assertIn('Synthetic executing package A worker.', Path(attempt['path']).read_text())
        f.result(attempt)
        receipt = f.cli('validate', {'reference': f.finish()})
        self.assertEqual(receipt['rounds_used'], 1)
        self.assertEqual(Path(self.box.state_of(f.job_id)['pins']['workflow']['package_dir']), f.package)

    def test_active_b_executing_a(self):
        self.exercise()

    def test_relocated_active_b_executing_a(self):
        packages = relocate(self.box, {'imps': (self.a, self.manifest)})
        self.f.package, self.f.manifest = packages['imps']
        self.assertEqual((self.box.prefix / 'imps/current').resolve().name, self.b.name)
        self.assertFalse(self.a.exists())
        self.exercise()

    def test_current_equals_executing(self):
        current = self.box.prefix / 'imps/current'
        current.unlink()
        current.symlink_to(self.a.name)
        self.exercise()

    def refused(self, message):
        with self.assertRaises(AssertionError) as caught:
            self.f.create()
        self.assertIn(message, str(caught.exception))
        self.assertFalse((self.box.jobs / self.f.job_id / 'job.json').exists())

    def test_tampered_executing_package_refused(self):
        path = self.a / 'shared/model_selection.py'
        path.write_text(path.read_text() + '\n# tampered\n')
        self.refused('installed package integrity failure: shared/model_selection.py')

    def test_unbundled_executing_package_refused(self):
        path = self.a / 'install-manifest.json'
        meta = json.loads(path.read_text())
        meta.pop('bundle_dir')
        path.write_text(json.dumps(meta))
        self.refused('no worker bundle')

    def test_wrong_plugin_refused(self):
        self.f.create = lambda: panel.PlanningReviewTests.create(self.f, extra={'plugin': 'ape'})
        self.refused('wrong package pin')

    def test_wrong_installation_refused(self):
        path = self.a / 'install-manifest.json'
        meta = json.loads(path.read_text())
        meta['installation_id'] = '00000000-0000-4000-8000-000000000001'
        path.write_text(json.dumps(meta))
        self.refused('outside its owned registry')

    def test_missing_receipt_refused(self):
        (self.a / 'install-manifest.json').unlink()
        self.refused('unresolved package pin')

    def test_missing_package_manifests_do_not_fall_back_to_current(self):
        (self.a / 'install-manifest.json').unlink()
        (self.a / 'plugin.json').unlink()
        self.refused('unresolved package pin')

    def test_persistent_history_and_round_limits(self):
        self.f.test_persistent_budget_new_jobs_and_explicit_owner_limit()


if __name__ == '__main__':
    unittest.main()
