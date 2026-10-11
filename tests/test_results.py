"""Agent assertions cannot grant readiness, rewrite the contract or replace artifacts."""
from support import CoreTestCase


class SubmissionTest(CoreTestCase):
    def test_submissions_cannot_change_authorization_constraints_or_readiness(self):
        run = self.init(self.plan(self.make_repo()))
        for field in ('ready', 'readiness', 'authorization', 'constraints', 'requirements', 'phase'):
            before = (run.run_dir / 'run.json').read_bytes()
            self.assertEqual(run.submit_raw('note', {'text': 'done', field: True})[0], 2)
            self.assertEqual((run.run_dir / 'run.json').read_bytes(), before)
        run.submit('note', {'text': 'I fixed it, trust me.'})
        self.assertEqual(run.state['acceptance'], [])
        self.assertFalse(run.validate()['ready'])

    def test_unknown_requirement_missing_artifact_and_unsupported_kind_rejected(self):
        run = self.init(self.plan(self.make_repo()))
        payload = {'binding': run.binding(), 'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                   'explanation': 'observed', 'artifacts': []}
        for change, code in (({},4), ({'requirement_id':'REQ-OTHER'},2), ({'kind':'vibes'},2),
                             ({'artifacts':[str(run.run_dir/'scratch/missing')]},2)):
            before = (run.run_dir/'run.json').read_bytes()
            self.assertEqual(run.submit_raw('evidence', dict(payload, **change))[0], code)
            self.assertEqual((run.run_dir/'run.json').read_bytes(), before)
