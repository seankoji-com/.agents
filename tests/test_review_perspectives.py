import json

from support import FakeT3, capabilities, cli, done, result_block
from test_readiness import Base


class Perspectives(Base):
    def panel_run(self):
        repo = self.make_repo()
        plan = self.plan(repo, policy={'review': {'required': True, 'role': 'reviewer',
                                                'perspectives': {'architecture': 'Trace contracts.',
                                                                 'operations': 'Trace retries.'}},
                                       'checks': [], 'repair_limit': 1})
        run = self.init(plan)
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        source = repo / 'wordstat.py'
        source.write_text(source.read_text().replace("split(' ')", 'split()'))
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        return repo, run

    def accept(self, run):
        log = run.scratch('accept.log', 'prints 3')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'prints 3', 'artifacts': [str(log)]})

    def review(self, run, verdict='approve', findings=None, edit=None):
        action = run.only('dispatch')
        t3 = FakeT3()
        t3.script(action['host_call']['arguments']['clientRequestId'], done(result_block(
            action['task_id'], verdict=verdict, findings=findings or [])))
        run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
        if edit:
            edit()
        query = next(a for a in run.next()['actions'] if a['action'] == 'query_task')
        run.record('observation', {'response': t3.call(query['host_call'])})
        return action

    def test_every_perspective_required_and_handles_retained(self):
        repo, run = self.panel_run()
        requests = []
        for name in ('default', 'architecture', 'operations'):
            self.assertFalse(cli('validate', *run.args())[1]['data']['ready'])
            action = self.review(run)
            requests.append(action['host_call']['arguments']['clientRequestId'])
            self.assertEqual(run.state['reviews'][-1]['perspective_id'], name)
            if name != 'default':
                self.assertIn('perspective ' + name, action['host_call']['arguments']['task'])
        self.assertEqual(len(set(requests)), 3)
        self.assertTrue(cli('validate', *run.args())[1]['data']['ready'])
        self.assertEqual(run.only('transition')['args']['to'], 'ready')
        self.assertEqual(len([t for t in run.state['tasks'] if t['kind'] == 'review']), 3)

    def test_adverse_panel_requires_repair_and_invalidates_all(self):
        repo, run = self.panel_run()
        self.review(run)
        self.review(run, findings=[{'severity': 'major', 'summary': 'missing retry check'}])
        self.assertEqual(run.state['reviews'][-1]['verdict'], 'adverse')
        self.assertEqual(cli('validate', *run.args())[1]['data']['review']['status'], 'failed')
        repair = run.only('repair')
        self.assertEqual(repair['args']['stage'], 'review')
        run.record('repair', {'stage': 'review', 'findings': repair['args']['findings']})
        self.assertTrue(all(r.get('invalidated') for r in run.state['reviews']))
        self.assertEqual(run.state['counters']['repairs']['review'], 1)

    def test_tree_change_during_panel_does_not_certify_new_tree(self):
        repo, run = self.panel_run()
        self.review(run)
        source = repo / 'wordstat.py'
        self.review(run, edit=lambda: source.write_text(source.read_text() + '\n# changed during review\n'))
        value = cli('validate', *run.args())[1]['data']
        self.assertFalse(value['ready'])
        self.assertTrue(value['stale'])
        self.accept(run)
        action = run.only('dispatch')
        self.assertNotIn('perspective operations', action['host_call']['arguments']['task'])

    def test_panel_obligations_cannot_be_removed_or_reworded(self):
        repo, run = self.panel_run()
        for perspectives in ({}, {'architecture': 'different', 'operations': 'Trace retries.'}):
            code, env, _ = run.record_raw('policy', {'policy': {'review': {'perspectives': perspectives}}})
            self.assertEqual(code, 4, env)
            self.assertEqual(env['error']['code'], 'policy_weakening')
        code, env, _ = run.record_raw('policy', {'policy': {'review': {'perspectives': {'default': 'invalid'}}}})
        self.assertEqual(code, 2, env)


if __name__ == '__main__':
    import unittest
    unittest.main()
