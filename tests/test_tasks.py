"""Observed child identities, descendants and confirmed cancellation gate readiness."""
from support import CoreTestCase


class ChildTest(CoreTestCase):
    def ready_run(self):
        repo = self.make_repo()
        run = self.init(self.plan(repo, policy={'checks': [], 'review': {'required': False}}))
        run.evidence('REQ-MULTILINE', run.scratch('proof.log', 'observed'))
        self.assertTrue(run.validate()['ready'])
        return run

    def test_nonterminal_children_block_even_with_all_evidence(self):
        for status in ('queued', 'running', 'waiting'):
            run = self.ready_run()
            run.child(status=status)
            self.assertFalse(run.validate()['ready'])
            self.assertIn('child:task-1', str(run.validate()['missing']))
            run.child(status='completed')
            self.assertTrue(run.validate()['ready'])

    def test_terminal_parent_with_pending_descendants_is_not_ready(self):
        run = self.ready_run()
        run.child(status='completed', pending=True)
        self.assertFalse(run.validate()['ready'])
        run.child(status='completed', pending=False, work_state='waiting_for_children')
        self.assertFalse(run.validate()['ready'])
        run.child(status='completed', pending=False, work_state='result_available')
        self.assertTrue(run.validate()['ready'])

    def test_terminal_status_without_work_state_is_terminal(self):
        run = self.ready_run()
        for status in ('completed', 'failed', 'cancelled', 'interrupted'):
            run.child(task_id='child-' + status, status=status)
        self.assertTrue(run.validate()['ready'])

    def test_confirmed_stop_required_before_cancel(self):
        run = self.ready_run()
        run.child(status='running')
        code, env, _ = run.submit_raw('cancel', {})
        self.assertEqual((code, env['error']['code']), (4, 'children_pending'))
        self.assertEqual(env['error']['details']['task_ids'], ['task-1'])
        run.child(status='interrupted', pending=True)
        self.assertEqual(run.submit_raw('cancel', {})[0], 4)
        run.child(status='interrupted', pending=False)
        run.submit('cancel', {})
        self.assertEqual(run.validate()['outcome'], 'cancelled')
        self.assertFalse(run.validate()['ready'])

    def test_cross_parent_and_request_identity_changes_are_rejected(self):
        run = self.ready_run()
        run.child(status='running')
        child = dict(run.state['children'][0])
        child['parent_thread_id'] = 'another-thread'
        self.assertEqual(run.submit_raw('child', child)[0], 4)
        child = dict(run.state['children'][0], client_request_id='different')
        self.assertEqual(run.submit_raw('child', child)[0], 4)
        child = dict(run.state['children'][0], task_id='different')
        self.assertEqual(run.submit_raw('child', child)[0], 4)
        self.assertEqual(len(run.state['children']), 1)

    def test_observations_survive_restart_and_timeout_never_invents_a_task(self):
        run = self.ready_run()
        run.child(status='running')
        self.assertEqual(run.status()['children'][0]['task_id'], 'task-1')
        run.child(status='running')
        self.assertEqual(len(run.status()['children']), 1)
        self.assertFalse(run.validate()['ready'])
