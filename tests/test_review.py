"""Review submissions stay bound to the reviewed revision and policy."""
from support import CoreTestCase


class ReviewTest(CoreTestCase):
    def setup_review(self, perspectives=None):
        run = self.init(self.plan(self.make_repo(), policy={'checks': [], 'review': {
            'required': True, 'role': 'reviewer', 'perspectives': perspectives or {}}}))
        log = run.scratch('review.txt', 'review findings')
        run.evidence('REQ-MULTILINE', log)
        return run, log

    def review_payload(self, run, log, verdict='approve', findings=None, perspective='default', task='review-1'):
        return {'binding': run.binding(), 'task_id': task, 'perspective_id': perspective,
                'verdict': verdict, 'findings': findings or [], 'artifacts': [str(log)]}

    def test_pending_review_cannot_certify_the_tree(self):
        run, log = self.setup_review()
        run.child(task_id='review-1', status='running')
        self.assertEqual(run.submit_raw('review', self.review_payload(run, log))[0], 4)
        run.child(task_id='review-1')
        run.submit('review', self.review_payload(run, log))
        self.assertTrue(run.validate()['ready'])

    def test_review_sent_before_edit_is_rejected_and_never_relabelled(self):
        run, log = self.setup_review()
        payload = self.review_payload(run, log)
        run.child(task_id='review-1')
        from pathlib import Path
        Path(run.state['repo']['worktree'], 'wordstat.py').write_text('edited')
        self.assertEqual(run.submit_raw('review', payload)[0], 4)
        self.assertEqual(run.state['reviews'], [])
        self.assertFalse(run.validate()['ready'])

    def test_approve_with_major_findings_is_adverse_and_final_for_revision(self):
        run, log = self.setup_review()
        run.child(task_id='review-1')
        payload = self.review_payload(run, log, findings=[{'severity': 'major', 'summary': 'missing caller'}])
        run.submit('review', payload)
        self.assertEqual(run.validate()['review']['status'], 'failed')
        self.assertEqual(run.state['reviews'][0]['verdict'], 'adverse')
        before = (run.run_dir / 'run.json').read_bytes()
        self.assertEqual(run.submit_raw('review', self.review_payload(run, log))[0], 4)
        self.assertEqual((run.run_dir / 'run.json').read_bytes(), before)

    def test_artifact_changes_stale_review(self):
        run, log = self.setup_review()
        run.child(task_id='review-1')
        run.submit('review', self.review_payload(run, log))
        artifact = run.state['reviews'][0]['artifacts'][0]
        (run.run_dir / artifact['path']).write_text('tampered')
        self.assertEqual(run.validate()['status'], 'stale')

    def test_unsuccessful_child_cannot_approve(self):
        run, log = self.setup_review()
        run.child(task_id='review-1', status='failed')
        code, env, _ = run.submit_raw('review', self.review_payload(run, log))
        self.assertEqual((code, env['error']['code']), (4, 'review_unavailable'))
        self.assertFalse(run.validate()['ready'])
