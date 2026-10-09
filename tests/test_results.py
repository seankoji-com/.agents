"""Source-spec case 9 and REQ-RESULT: structured child results are extracted,
stored, validated and checked against the actual worktree."""
import json
import sys
from pathlib import Path

from support import ROOT, CoreTestCase, FakeT3, capabilities, done, result_block

sys.path.insert(0, str(ROOT))
from core import results  # noqa: E402


class ExtractTest(CoreTestCase):
    def test_single_fenced_block_is_extracted(self):
        text = 'Summary prose.\n\n```json t3-result\n{"schema_version": 1, "task_id": "x"}\n```\n'
        self.assertEqual(results.extract(text)['task_id'], 'x')
        plain = 'prose\n```json\n{"a": 1}\n```'
        self.assertEqual(results.extract(plain), {'a': 1})

    def test_ambiguous_or_broken_blocks_are_malformed(self):
        for text in ('no block at all', '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```',
                     '```json t3-result\n{not json}\n```', '```json t3-result\n[1, 2]\n```'):
            with self.subTest(text=text[:30]):
                with self.assertRaises(results.Malformed):
                    results.extract(text)


class ResultFlowTest(CoreTestCase):
    def executing(self, delegated=False):
        repo = self.make_repo()
        overrides = {'policy': {'review': {'required': False, 'role': 'reviewer'}, 'checks': [],
                                'worktree_root': str(self.tmp / 'wt')}}
        if delegated:
            overrides.update(execution={'mode': 'delegated'}, tasks=[{'id': 'survey', 'purpose': 'read', 'kind': 'read'}])
        run = self.init(self.plan(repo, **overrides))
        run.claim()
        if delegated:
            run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run

    def test_valid_result_is_stored_as_artifact(self):
        repo, run = self.executing(delegated=True)
        t3 = FakeT3()
        dispatch = run.only('dispatch')
        t3.script(dispatch['host_call']['arguments']['clientRequestId'],
                  done(result_block('survey', findings=[{'severity': 'note', 'summary': 'one caller'}])))
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        stored = run.state['tasks'][0]['result']
        artifact = json.loads((run.run_dir / stored['artifact']['path']).read_text())
        self.assertEqual(artifact['findings'][0]['summary'], 'one caller')
        self.assertTrue((run.run_dir / stored['raw']['path']).is_file())

    def test_malformed_twice_blocks_with_raw_output_preserved(self):
        repo, run = self.executing(delegated=True)
        t3 = FakeT3()
        first = run.only('dispatch')
        t3.script(first['host_call']['arguments']['clientRequestId'], done('```json t3-result\n{"oops": \n```'))
        run.record('dispatch', {'action_id': first['id'], 'response': t3.call(first['host_call'])})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'correction_requested')
        second = run.only('dispatch')
        self.assertIn('{"oops":', second['host_call']['arguments']['task'], 'correction brief carries the raw output')
        t3.script(second['host_call']['arguments']['clientRequestId'], done('```json t3-result\n{"still": "wrong"}\n```'))
        run.record('dispatch', {'action_id': second['id'], 'response': t3.call(second['host_call'])})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'blocked')
        self.assertEqual(out['result']['blocker']['code'], 'malformed_result')
        task = run.state['tasks'][0]
        self.assertEqual(task['status'], 'blocked')
        self.assertEqual(len(task['malformed']), 2, 'exactly one correction was requested')
        raws = [(run.run_dir / item['raw']['path']).read_text() for item in task['malformed']]
        self.assertIn('{"oops":', raws[0])
        self.assertIn('"still": "wrong"', raws[1])
        self.assertFalse([a for a in run.next()['actions'] if a['action'] == 'dispatch'])

    def test_claimed_files_or_commit_that_do_not_exist_are_rejected(self):
        repo, run = self.executing()
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        out = run.record('result', {'task_id': 'main', 'text': result_block(
            'main', changed_files=['wordstat.py', 'imaginary.py'])})
        self.assertEqual(out['result']['blocker']['code'], 'result_rejected')
        self.assertIn('imaginary.py', out['result']['blocker']['reason'])

        repo, run = self.executing()
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        out = run.record('result', {'task_id': 'main', 'text': result_block(
            'main', changed_files=['wordstat.py'], commit='deadbeefcafe')})
        self.assertIn('claimed commit is not in the task worktree', out['result']['blocker']['reason'])

    def test_completion_claim_without_artifacts_is_rejected(self):
        repo, run = self.executing()
        (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text().replace("split(' ')", 'split()'))
        out = run.record('result', {'task_id': 'main', 'text': result_block(
            'main', changed_files=['wordstat.py'], requirements=[
                {'id': 'REQ-MULTILINE', 'status': 'passed', 'explanation': 'tested',
                 'evidence': [{'path': str(self.tmp / 'logs' / 'never-written.txt')}]}])})
        self.assertIn('evidence that does not exist', out['result']['blocker']['reason'])
        repo, run = self.executing()
        out = run.record('result', {'task_id': 'main', 'text': result_block('main')})
        self.assertIn('no changes', out['result']['blocker']['reason'])

    def test_result_cannot_change_constraints_authorization_or_completion(self):
        for field, value in (('constraints', []), ('authorized_actions', ['merge']), ('phase', 'completed'),
                             ('completion', True), ('endstate', 'merge')):
            with self.subTest(field=field):
                repo, run = self.executing()
                (repo / 'wordstat.py').write_text('changed\n')
                out = run.record('result', {'task_id': 'main', 'text': result_block(
                    'main', changed_files=['wordstat.py'], **{field: value})})
                self.assertEqual(out['result']['blocker']['code'], 'result_rejected')
                self.assertIn('operator-owned fields', out['result']['blocker']['reason'])
                state = run.state
                self.assertEqual(state['brief']['constraints'], ['Do not change the CLI usage text.'])
                self.assertEqual(state['authorization']['endstate'], 'local')
                self.assertEqual(state['phase'], 'executing')

    def test_result_cannot_reword_requirements(self):
        repo, run = self.executing()
        (repo / 'wordstat.py').write_text('changed\n')
        out = run.record('result', {'task_id': 'main', 'text': result_block(
            'main', changed_files=['wordstat.py'], requirements=[
                {'id': 'REQ-MULTILINE', 'text': 'count roughly works', 'status': 'passed', 'explanation': 'x'}])})
        self.assertIn('rewrites a requirement', out['result']['blocker']['reason'])
