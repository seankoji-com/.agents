"""A routing-config runtimeMode pinned on a target reaches the delegate_task call, so
an imps run can follow shared/delegation.md instead of silently inheriting the mode."""
import sys

from support import ROOT, CoreTestCase

sys.path.insert(0, str(ROOT))
from core import selection, t3  # noqa: E402
from core.errors import InvalidInput  # noqa: E402

REVIEWER = {'chain': [
    {'select': 'fixed', 'providerInstanceId': 'opencode', 'model': 'gateway/glm-9', 'runtimeMode': 'full-access'},
    {'select': 'fixed', 'providerInstanceId': 'codex', 'model': 'model-x1'},
]}


class RuntimeModeTest(CoreTestCase):
    def test_fixed_chain_entry_carries_runtime_mode_into_the_call(self):
        state = {'roles': {'reviewer': REVIEWER}, 'capabilities': {}, 'host': {}, 'policy': {}}
        (first, _), (second, _) = selection.candidates(state, 'reviewer')
        self.assertEqual(first['runtimeMode'], 'full-access')
        self.assertNotIn('runtimeMode', second)
        call = t3.delegate_call(brief='b', title='t', role='review', client_request_id='r1', target=first)
        self.assertEqual(call['arguments']['runtimeMode'], 'full-access')
        self.assertEqual(call['arguments']['target'], {'providerInstanceId': 'opencode', 'model': 'gateway/glm-9'})
        plain = t3.delegate_call(brief='b', title='t', role='review', client_request_id='r2', target=second)
        self.assertNotIn('runtimeMode', plain['arguments'])

    def test_plan_accepts_runtime_mode_on_roles_and_task_targets(self):
        repo = self.make_repo()
        plan = self.plan(repo, roles={'reviewer': REVIEWER},
                         tasks=[{'id': 'main', 'purpose': 'fix it', 'requirement_ids': ['REQ-MULTILINE'],
                                 'target': {'providerInstanceId': 'opencode', 'model': 'gateway/glm-9',
                                            'runtimeMode': 'full-access'}}])
        run = self.init(plan)
        self.assertEqual(run.state['roles']['reviewer']['chain'][0]['runtimeMode'], 'full-access')
        bad = self.plan(repo, roles={'reviewer': {'chain': [dict(REVIEWER['chain'][0], runtimeMode='root')]}})
        self.init(bad, expect=2)

    def test_role_must_still_be_valid(self):
        with self.assertRaises(InvalidInput):
            t3.delegate_call(brief='b', title='t', role='boss', client_request_id='r', target=None)


if __name__ == '__main__':
    import unittest
    unittest.main()
