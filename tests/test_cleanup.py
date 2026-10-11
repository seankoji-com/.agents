"""External cleanup cannot remove evidence copied into the run."""
from support import CoreTestCase


class CleanupTest(CoreTestCase):
    def test_evidence_survives_removal_of_its_source(self):
        run = self.init(self.plan(self.make_repo(), policy={'checks': [], 'review': {'required': False}}))
        source = run.scratch('proof.log', 'observed output')
        run.evidence('REQ-MULTILINE', source)
        source.unlink()
        self.assertTrue(run.validate()['ready'])
        artifact = run.state['acceptance'][0]['artifacts'][0]
        self.assertEqual((run.run_dir/artifact['path']).read_text(), 'observed output')
