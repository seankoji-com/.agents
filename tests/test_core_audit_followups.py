"""Core audit follow-ups: adverse reviews cannot be reset by out-of-band edits,
policy records cannot retarget a role, evidence stores the snapshot it attested,
engine bugs are not reported as bad input, the review binding on a permitted
dispatch comes from `next`, and delegated tasks resolve a role at init."""
import contextlib
import io
import json
import sys
from unittest import mock

from support import ROOT, CoreTestCase, FakeT3, capabilities, cli, done, result_block

sys.path.insert(0, str(ROOT))
from core import cli as core_cli, engine, records, schema, snapshot  # noqa: E402
from core.errors import InvalidInput  # noqa: E402


def edit(repo, text='\n# changed\n'):
    (repo / 'wordstat.py').write_text((repo / 'wordstat.py').read_text() + text)


def in_process(argv):
    """Run core/cli.py main() in this process; return (exit, envelope, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = core_cli.main([str(a) for a in argv])
    return code, json.loads(out.getvalue().strip()), err.getvalue()


class Flow(CoreTestCase):
    def run_with(self, tasks=None, mode='direct', review=False, **policy):
        repo = self.make_repo()
        settings = {'review': {'required': review, 'role': 'reviewer'}, 'checks': [],
                    'worktree_root': str(self.tmp / 'wt')}
        settings.update(policy)
        overrides = {'execution': {'mode': mode}, 'policy': settings}
        if tasks:
            overrides['tasks'] = tasks
        run = self.init(self.plan(repo, **overrides))
        run.claim()
        if mode == 'delegated' or review:
            run.record('capabilities', {'response': capabilities()})
        run.record('transition', {'to': 'executing'})
        return repo, run, FakeT3()

    def accept(self, run):
        log = run.scratch(f'ok-{run.generation}.log', 'ok')
        run.record('acceptance', {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command',
                                  'explanation': 'ok', 'artifacts': [str(log)]})

    def to_review(self, **policy):
        repo, run, t3 = self.run_with(review=True, **policy)
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        self.accept(run)
        return repo, run, t3, run.only('dispatch')

    def adverse_review(self, **policy):
        repo, run, t3, review = self.to_review(**policy)
        t3.script(review['host_call']['arguments']['clientRequestId'], done(result_block(
            review['task_id'], verdict='adverse', findings=[{'severity': 'blocker', 'summary': 'wrong split'}])))
        run.record('dispatch', {'action_id': review['id'], 'response': t3.call(review['host_call'])})
        run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(run.state['reviews'][-1]['verdict'], 'adverse')
        return repo, run, t3


class AdverseReviewIsFinalTest(Flow):
    def test_out_of_band_edit_does_not_buy_a_fresh_review_round(self):
        repo, run, _ = self.adverse_review()
        self.assertEqual(run.only('repair')['args']['round'], 1)
        edit(repo, '\n# edited outside record --kind repair\n')
        self.accept(run)  # the edit staled acceptance; re-gather it at the new revision
        actions = run.next()['actions']
        self.assertEqual([a['action'] for a in actions], ['repair'], 'no new review round without a repair')
        self.assertEqual(actions[0]['args'], dict(actions[0]['args'], stage='review', round=1))
        self.assertEqual(run.state['counters']['review_rounds'], 1)

    def test_out_of_band_edit_cannot_reset_an_exhausted_repair_budget(self):
        repo, run, _ = self.adverse_review(repair_limit=0)
        self.assertEqual(run.next()['blocked']['code'], 'repair_limit')
        edit(repo, '\n# edited outside record --kind repair\n')
        data = run.next()
        if not data.get('blocked'):
            self.accept(run)
            data = run.next()
        self.assertEqual((data.get('blocked') or {}).get('code'), 'repair_limit', data)
        self.assertFalse([a for a in data['actions'] if a['action'] == 'dispatch'])


class PolicyRecordCannotRetargetTest(Flow):
    def test_role_overrides_in_a_policy_record_are_refused(self):
        _, run, _ = self.run_with(review=True)
        before = run.state['policy']
        code, env, _ = run.record_raw('policy', {'policy': {'role_overrides': {
            'reviewer': {'providerInstanceId': 'claudeAgent', 'model': 'claude-opus-5-5'}}}})
        self.assertEqual((code, env['error']['code']), (4, 'policy_fixed'))
        self.assertIn('role_overrides', env['error']['message'])
        self.assertEqual(run.state['policy'], before)


class EvidenceStoresAttestedSnapshotTest(Flow):
    def test_check_and_acceptance_store_the_snapshot_they_compared(self):
        repo, run, _ = self.run_with(checks=[{'name': 'unit', 'argv': [sys.executable, '-c', 'pass'],
                                              'cwd': str(self.tmp)}])
        edit(repo)
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=['wordstat.py'])})
        run.record('transition', {'to': 'verifying'})
        check = run.only('run_check')
        log = run.scratch('unit.log', 'ok')
        real = records._bind
        calls = []

        def bind_then_drift(ctx, state):
            bound = real(ctx, state)
            calls.append(bound)
            (repo / 'drift.txt').write_text(f'changed after binding {len(calls)}\n')  # a watcher touching the tree
            return bound

        payload = {'name': 'unit', 'argv': check['args']['argv'], 'cwd': check['args']['cwd'], 'exit_code': 0,
                   'log': str(log), 'snapshot': check['args']['snapshot']}
        with mock.patch.object(records, '_bind', bind_then_drift):
            code, env, _ = in_process(['record', *run.args('--kind', 'check', '--token', run.token,
                                                           '--expect-generation', run.generation,
                                                           '--parent-thread-id', run.parent,
                                                           '--json', json.dumps(payload))])
        self.assertEqual(code, 0, env)
        stored = run.state['checks'][-1]['snapshot']
        self.assertEqual(snapshot.token(stored), check['args']['snapshot'])
        self.assertEqual(len(calls), 1, 'one snapshot per record')

        self.run_check(run, run.only('run_check'))  # the drift staled the check; run it again honestly
        accept = run.only('accept')
        evidence = run.scratch('accept.log', 'ok')
        calls.clear()
        payload = {'requirement_id': 'REQ-MULTILINE', 'status': 'passed', 'kind': 'command', 'explanation': 'ok',
                   'artifacts': [str(evidence)], 'snapshot': accept['args']['snapshot']}
        with mock.patch.object(records, '_bind', bind_then_drift):
            code, env, _ = in_process(['record', *run.args('--kind', 'acceptance', '--token', run.token,
                                                           '--expect-generation', run.generation,
                                                           '--parent-thread-id', run.parent,
                                                           '--json', json.dumps(payload))])
        self.assertEqual(code, 0, env)
        self.assertEqual(snapshot.token(run.state['acceptance'][-1]['snapshot']), accept['args']['snapshot'])
        self.assertEqual(len(calls), 1)


class ExitCodeTruthTest(Flow):
    def record_note(self, run, error):
        def broken(ctx, state, payload):
            raise error
        with mock.patch.dict(records.HANDLERS, {'note': broken}):
            return in_process(['record', *run.args('--kind', 'note', '--token', run.token,
                                                   '--expect-generation', run.generation,
                                                   '--parent-thread-id', run.parent,
                                                   '--json', json.dumps({'key': 'k', 'text': 't'}))])

    def test_handler_key_and_type_errors_are_internal_errors(self):
        _, run, _ = self.run_with()
        for error in (KeyError('round'), TypeError('bad shape')):
            code, env, stderr = self.record_note(run, error)
            self.assertEqual((code, env['error']['code']), (5, 'internal_error'), env)
            self.assertIn('Traceback', stderr)

    def test_value_errors_stay_invalid_input(self):
        _, run, _ = self.run_with()
        code, env, _ = self.record_note(run, ValueError('not a number'))
        self.assertEqual((code, env['error']['code']), (2, 'invalid_input'))

    def test_malformed_echoed_dispatch_args_are_invalid_input_with_a_message(self):
        _, run, t3 = self.run_with([{'id': 'survey', 'purpose': 'read', 'kind': 'read'}], mode='delegated')
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        for drop in ('round', 'purpose', 'target', 'why'):
            args = {k: v for k, v in dispatch['args'].items() if k != drop}
            echoed = engine.action('dispatch', 'dispatch', task_id=dispatch['task_id'], args=args,
                                   host_call=dispatch['host_call'], note=dispatch['note'])
            code, env, _ = run.record_raw('dispatch', {'action': echoed, 'response': response})
            self.assertEqual((code, env['error']['code']), (2, 'action_args'), drop)
            self.assertIn(drop, env['error']['message'])
        self.assertEqual(run.state['tasks'][0]['rounds'], [])


class PermittedDispatchBindingTest(Flow):
    def test_permitted_review_dispatch_binds_next_not_the_payload(self):
        _, run, t3, review = self.to_review()
        forged = dict(review['args']['binding'], contract_hash='0' * 64)
        run.record('dispatch', {'action_id': review['id'], 'response': t3.call(review['host_call']),
                                'binding': forged})
        task = next(t for t in run.state['tasks'] if t['id'] == review['task_id'])
        self.assertEqual(task['review_binding'], review['args']['binding'])


class DelegatedRoleAtInitTest(Flow):
    def test_delegated_task_with_unknown_role_is_refused_at_init(self):
        repo = self.make_repo()
        env = self.init(self.plan(repo, execution={'mode': 'delegated'},
                                  tasks=[{'id': 'fix', 'purpose': 'fix', 'role': 'ghost'}]), expect=2)
        self.assertEqual(env['error']['code'], 'unknown_role')
        self.assertIn('fix', env['error']['message'])
        self.assertEqual(env['error']['details'], {'task': 'fix', 'role': 'ghost'})


class ResultTextFileContainmentTest(Flow):
    def test_text_file_inside_the_roots_is_read(self):
        repo, run, _ = self.run_with()
        edit(repo)
        text = run.scratch('main-result.txt', result_block('main', changed_files=['wordstat.py']))
        out = run.record('result', {'task_id': 'main', 'text_file': str(text)})
        self.assertEqual(out['result']['outcome'], 'accepted')

    def test_text_file_outside_the_roots_is_refused(self):
        repo, run, _ = self.run_with()
        edit(repo)
        outside = self.write('outside.txt', result_block('main', changed_files=['wordstat.py']))
        code, env, _ = run.record_raw('result', {'task_id': 'main', 'text_file': str(outside)})
        self.assertEqual((code, env['error']['code']), (2, 'path_escape'))
        self.assertEqual(run.state['tasks'][0]['status'], 'pending')
        self.assertEqual(list(run.run_dir.glob('artifacts/results/*')), [])


class SchemaItemsTest(CoreTestCase):
    def test_tuple_form_items_is_refused(self):
        with self.assertRaises(InvalidInput) as caught:
            schema.check_keywords({'type': 'array', 'items': [{'type': 'string'}]})
        self.assertEqual(caught.exception.code, 'schema_keyword')
        schema.check_keywords({'type': 'array', 'items': {'type': 'string'}})


if __name__ == '__main__':
    import unittest
    unittest.main()
