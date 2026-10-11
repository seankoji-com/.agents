"""Local verification never proves publication or a different remote head."""
from support import CoreTestCase, git


class RemoteTest(CoreTestCase):
    def local_pass(self, endstate='pr'):
        repo = self.make_repo()
        run = self.init(self.plan(repo, authorization={'endstate': endstate},
                                  policy={'checks': [], 'review': {'required': False}}))
        run.evidence('REQ-MULTILINE', run.scratch('proof', 'observed'))
        return repo, run

    def receipt(self, run, **changes):
        data = {'type': 'receipt', 'kind': 'pr', 'url': 'https://example.invalid/pull/1', 'state': 'open',
                'head_sha': run.binding()['snapshot']['head']}
        data.update(changes)
        run.submit('remote', data)
        return data

    def test_local_pass_cannot_complete_a_pr_endstate(self):
        _, run = self.local_pass()
        self.assertTrue(run.validate()['ready'])
        self.assertNotEqual(run.validate()['outcome'], 'completed')
        self.assertFalse(run.validate()['remote_confirmed'])

    def test_receipt_needs_independent_observation_at_verified_head(self):
        _, run = self.local_pass()
        receipt = self.receipt(run)
        self.assertFalse(run.validate()['remote_confirmed'])
        run.submit('remote', dict(receipt, type='observation', head_sha='0'*40))
        self.assertFalse(run.validate()['remote_confirmed'])
        run.submit('remote', dict(receipt, type='observation', url='https://example.invalid/pull/2'))
        self.assertFalse(run.validate()['remote_confirmed'])
        run.submit('remote', dict(receipt, type='observation'))
        self.assertEqual(run.validate()['outcome'], 'completed')

    def test_pr_requires_committed_changes_and_release_is_never_faked(self):
        repo, run = self.local_pass()
        (repo/'wordstat.py').write_text('changed')
        run.evidence('REQ-MULTILINE', run.scratch('fresh', 'observed changed output'))
        receipt = self.receipt(run)
        run.submit('remote', dict(receipt, type='observation'))
        self.assertFalse(run.validate()['remote_confirmed'])
        _, release = self.local_pass('release')
        receipt = self.receipt(release, state='merged')
        release.submit('remote', dict(receipt, type='observation'))
        self.assertFalse(release.validate()['remote_confirmed'])
