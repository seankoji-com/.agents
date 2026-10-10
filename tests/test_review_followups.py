"""Follow-ups from the post-merge adversarial review of PR #1: findings that the
in-PR review rounds did not catch or did not fix."""
import hashlib
import json
import sys
from pathlib import Path

from support import ROOT, FakeT3, capabilities
import test_bugfix_delegated as delegated

sys.path.insert(0, str(ROOT))
from core import fsutil, recipe  # noqa: E402
from core.errors import InvalidInput  # noqa: E402


class FollowupTest(delegated.DelegatedBugFixTest):
    # Inherited tests run in their own module; only the helpers are wanted here.
    test_parallel_delegated_fix_with_review_repair = test_serial_mode_when_probe_fails = None

    def delegated_run(self):
        repo = self.make_repo()
        run = self.init(self.delegated_plan(repo, [
            {'id': 'fix', 'purpose': 'fix counting', 'files': ['wordstat.py'], 'requirement_ids': ['REQ-MULTILINE']}],
            review=False))
        run.claim()
        run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run, delegated.DelegatedFlow(self, run, FakeT3())

    def test_a_blocked_probe_never_lets_writers_run_unprobed(self):
        repo, run, flow = self.delegated_run()
        flow.create_worktree(run.only('create_worktree'))
        probe = run.only('dispatch')
        self.assertTrue(probe['task_id'].startswith('probe-'))
        run.record('dispatch', {'action_id': probe['id'], 'error': {'code': 'invalid_request', 'message': 'invalid'}})
        data = run.next()
        offered = [(a['action'], a['task_id']) for a in data['actions']]
        self.assertFalse([a for a in offered if a[1] == 'fix'], f'isolation is undecided, yet {offered}')
        self.assertIsNotNone(data['blocked'], 'the probe block surfaces instead of being masked')
        self.assertIn(probe['task_id'], data['blocked']['task_ids'])

    def test_waiver_names_a_real_requirement(self):
        repo, run, flow = self.delegated_run()
        code, env, _ = run.record_raw('waiver', {'target': 'requirement:REQ-NOPE', 'reason': 'x', 'decided_by': 'operator',
                                                 'operator_quote': 'waive it'})
        self.assertEqual((code, env['error']['code']), (2, 'unknown_requirement'))

    def test_policy_check_names_are_unique(self):
        repo, run, flow = self.delegated_run()
        check = {'name': 'lint', 'argv': [sys.executable, '-c', 'pass']}
        code, env, _ = run.record_raw('policy', {'policy': {'checks': [check, dict(check, required=False)]}})
        self.assertEqual((code, env['error']['code']), (2, 'duplicate_check'))

    def test_copy_artifact_replaces_a_stale_target(self):
        run_dir = self.tmp / 'run'
        run_dir.mkdir()
        source = self.write('log.txt', 'real output\n')
        first = fsutil.copy_artifact(source, run_dir, 'checks', [self.tmp])
        (run_dir / first['path']).write_text('tampered\n')
        again = fsutil.copy_artifact(source, run_dir, 'checks', [self.tmp])
        self.assertEqual((run_dir / again['path']).read_text(), 'real output\n')
        self.assertIsNone(fsutil.verify_artifact(run_dir, again))

    def test_recipe_stamp_refuses_colliding_evidence_names(self):
        recipe_path = self.tmp / 'r' / 'recipe.json'
        recipe_path.parent.mkdir()
        recipe_path.write_text(json.dumps({'features': [{'id': 'F-X'}]}))
        run_dir = self.tmp / 'run'
        artifacts = []
        # Case-insensitive / Unicode normalization collision ('out.log' vs 'OUT.LOG')
        for folder, filename, text in (('a', 'out.log', 'one'), ('b', 'OUT.LOG', 'two')):
            path = run_dir / folder / filename
            path.parent.mkdir(parents=True)
            path.write_text(text)
            artifacts.append({'path': f'{folder}/{filename}', 'sha256': hashlib.sha256(text.encode()).hexdigest()})
        state = {'phase': 'completed', 'run_id': 'r1', 'acceptance': [
            {'requirement_id': 'REQ-X', 'status': 'passed', 'kind': 'runtime', 'artifacts': artifacts,
             'recorded_at': '2026-10-10T00:00:00Z', 'snapshot': {'head': 'x'}}]}
        with self.assertRaises(InvalidInput) as caught:
            recipe.stamp(recipe_path, state, run_dir, 'F-X', 'REQ-X')
        self.assertEqual(caught.exception.code, 'evidence_name_collision')

    def test_plan_construction_refuses_duplicate_check_names(self):
        repo = self.make_repo()
        check = {'name': 'lint', 'argv': [sys.executable, '-c', 'pass']}
        plan = self.delegated_plan(repo, [
            {'id': 'fix', 'purpose': 'fix counting', 'files': ['wordstat.py'], 'requirement_ids': ['REQ-MULTILINE']}],
            review=False)
        plan['policy'] = {'checks': [check, dict(check, required=False)]}
        env = self.init(plan, expect=2)
        self.assertEqual(env['error']['code'], 'duplicate_check')


if __name__ == '__main__':
    import unittest
    unittest.main()
