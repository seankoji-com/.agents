"""Every configured review perspective must approve the same current revision."""
from test_review import ReviewTest


class Perspectives(ReviewTest):
    def test_every_perspective_required_and_handles_retained(self):
        run, log = self.setup_review({'architecture': 'Trace boundaries.'})
        for perspective in ('default', 'architecture'):
            task = 'review-' + perspective
            run.child(task_id=task)
            run.submit('review', self.review_payload(run, log, perspective=perspective, task=task))
            self.assertEqual(run.validate()['ready'], perspective == 'architecture')
        self.assertEqual(len(run.state['children']), 2)
        self.assertEqual(len(run.validate()['review']['perspectives']), 2)

    def test_panel_obligations_cannot_be_removed_or_reworded(self):
        run, log = self.setup_review({'architecture': 'Trace boundaries.'})
        for policy in ({'required': False}, {'perspectives': {'architecture': 'Ignore boundaries.'}}, {'perspectives': {}}):
            # Deep merge retains omitted keys; an explicit wording change is refused.
            result = run.submit_raw('policy', {'policy': {'review': policy}})
            self.assertEqual(result[0], 0 if policy == {'perspectives': {}} else 4)
        self.assertEqual(run.state['policy']['review']['perspectives']['architecture'], 'Trace boundaries.')

    def test_adverse_panel_and_tree_change_need_fresh_evidence(self):
        run, log = self.setup_review({'architecture': 'Trace boundaries.'})
        for perspective in ('default', 'architecture'):
            task = 'review-' + perspective
            run.child(task_id=task)
            run.submit('review', self.review_payload(run, log, verdict='adverse' if perspective == 'architecture' else 'approve',
                                                    perspective=perspective, task=task))
        self.assertFalse(run.validate()['ready'])
        from pathlib import Path
        Path(run.state['repo']['worktree'], 'repair.txt').write_text('repair')
        self.assertEqual(run.validate()['status'], 'stale')
