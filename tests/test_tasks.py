"""Source-spec cases 8, 10 and 11; REQ-TASKS: delegated task identity, timeouts,
nested work, cross-parent resume, capabilities and cancellation."""
import json
import subprocess
import sys
import time

from support import CoreTestCase, FakeT3, PARENT, capabilities, cli, done, result_block


class TaskBase(CoreTestCase):
    def read_run(self, caps=None, tasks=None, name='repo'):
        repo = self.make_repo(name=name)
        plan = self.plan(repo, execution={'mode': 'delegated'},
                         tasks=tasks or [{'id': 'survey', 'purpose': 'find callers', 'kind': 'read'}],
                         policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': [],
                                 'worktree_root': str(self.tmp / 'wt')})
        run = self.init(plan)
        run.claim()
        run.record('capabilities', {'response': caps or capabilities()})
        return repo, run


class DelegatedTaskTest(TaskBase):
    def test_wait_timeout_keeps_task_id_and_never_redispatches(self):
        repo, run = self.read_run()
        run.record('transition', {'to': 'executing'})
        t3 = FakeT3()
        dispatch = run.only('dispatch')
        request = dispatch['host_call']['arguments']['clientRequestId']
        timed_out = dict(t3.call(dispatch['host_call']), waitTimedOut=True)
        run.record('dispatch', {'action_id': dispatch['id'], 'response': timed_out})
        data = run.next()
        self.assertEqual([a['action'] for a in data['actions']], ['query_task'])
        self.assertEqual(data['actions'][0]['host_call']['arguments']['taskId'], timed_out['taskId'])
        code, env, _ = run.record_raw('dispatch', {'action_id': dispatch['id'], 'response': timed_out})
        self.assertEqual((code, env['error']['code']), (4, 'action_not_permitted'), 'a duplicate dispatch is refused')
        self.assertTrue(run.state['tasks'][0]['rounds'][0]['wait_timed_out'])
        self.assertEqual(run.state['tasks'][0]['rounds'][0]['client_request_id'], request)

    def test_retry_reuses_client_request_id_until_recorded(self):
        repo, run = self.read_run()
        run.record('transition', {'to': 'executing'})
        first = run.only('dispatch')
        # The MCP call failed in transit; nothing was recorded, so the retry is identical.
        again = run.only('dispatch')
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(first['host_call']['arguments']['clientRequestId'], again['host_call']['arguments']['clientRequestId'])
        t3 = FakeT3()
        self.assertEqual(t3.call(first['host_call'])['taskId'], t3.call(again['host_call'])['taskId'])

    def test_correction_round_gets_a_new_client_request_id(self):
        repo, run = self.read_run()
        run.record('transition', {'to': 'executing'})
        t3 = FakeT3()
        first = run.only('dispatch')
        t3.script(first['host_call']['arguments']['clientRequestId'], done('done! no JSON here'))
        run.record('dispatch', {'action_id': first['id'], 'response': t3.call(first['host_call'])})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'awaiting_text', 'no fenced block: read the full final message')
        collect = run.only('collect_result')
        self.assertTrue(collect['args']['child_thread_id'])
        out = run.record('result', {'task_id': 'survey', 'text': 'done! no JSON here, full message'})
        self.assertEqual(out['result']['outcome'], 'correction_requested')
        second = run.only('dispatch')
        self.assertNotEqual(first['host_call']['arguments']['clientRequestId'], second['host_call']['arguments']['clientRequestId'])
        self.assertTrue(second['host_call']['arguments']['clientRequestId'].endswith(':r2'))
        self.assertIn('Correction requested', second['host_call']['arguments']['task'])

    def test_waiting_for_children_is_not_a_result(self):
        repo, run = self.read_run()
        run.record('transition', {'to': 'executing'})
        t3 = FakeT3()
        dispatch = run.only('dispatch')
        t3.script(dispatch['host_call']['arguments']['clientRequestId'],
                  {'status': 'completed', 'workState': 'waiting_for_children',
                   'summary': result_block('survey'), 'hasPendingChildRuns': True},
                  done(result_block('survey')))
        run.record('dispatch', {'action_id': dispatch['id'], 'response': t3.call(dispatch['host_call'])})
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'working')
        self.assertEqual(run.state['tasks'][0]['status'], 'active')
        self.assertEqual(run.only('query_task')['task_id'], 'survey')
        out = run.record('observation', {'response': t3.call(run.only('query_task')['host_call'])})
        self.assertEqual(out['result']['outcome'], 'accepted')

    def test_cross_parent_resume_refuses_old_task_ids(self):
        repo, run = self.read_run()
        run.record('transition', {'to': 'executing'})
        t3 = FakeT3()
        dispatch = run.only('dispatch')
        response = t3.call(dispatch['host_call'])
        run.record('dispatch', {'action_id': dispatch['id'], 'response': response})
        run.release()
        data = run.next(parent='thread-other-0002')
        self.assertEqual(data['actions'][0]['action'], 'block')
        self.assertFalse([a for a in data['actions'] if a['host_call'] and a['host_call']['tool'] == 'task_status'])
        blocker = data['blocked']
        self.assertEqual(blocker['code'], 'cross_parent_resume')
        self.assertEqual(blocker['task_ids'], [response['taskId']])
        self.assertIn('thread-other-0002', blocker['resume']['argv'])
        run.claim()
        code, env, _ = run.record_raw('observation', {'response': response}, parent='thread-other-0002')
        self.assertEqual((code, env['error']['code']), (4, 'cross_parent'))
        self.assertEqual(run.next()['actions'][0]['action'], 'query_task', 'the original parent can still continue')


class CapabilityTest(TaskBase):
    def test_missing_capability_blocks_delegated_mode_explicitly(self):
        caps = capabilities()
        caps['features']['cancellation'] = False
        repo, run = self.read_run(caps=caps)
        recorded = run.state['capabilities']
        self.assertFalse(recorded['available'])
        self.assertEqual(recorded['missing'], ['cancellation'])
        data = run.next()
        self.assertEqual(data['blocked']['code'], 'capability_unavailable')
        self.assertIn('cancellation', data['blocked']['reason'])
        code, env, _ = run.record_raw('transition', {'to': 'executing'})
        self.assertEqual((code, env['error']['code']), (4, 'capability_unavailable'))

    def test_tools_not_callable_and_provider_reasons_are_separate(self):
        repo, run = self.read_run(caps={'unavailable': True, 'reason': 'mcp__t3-code__ tools not exposed by this harness'})
        self.assertEqual(run.state['capabilities']['missing'], ['orchestration_tools'])
        self.assertEqual(run.next()['blocked']['code'], 'capability_unavailable')
        repo, run2 = self.read_run(name='repo2')
        out = run2.state['capabilities']
        reasons = {p['id']: p['unavailable_reasons'] for p in out['providers'] if not p['available']}
        self.assertEqual(reasons['grok'], ['unauthenticated'])
        self.assertIn('disabled', reasons['cursor'])
        self.assertIn('not_installed', reasons['cursor'])

    def test_named_target_is_never_rewritten(self):
        caps = capabilities()
        repo, run = self.read_run(caps=caps, tasks=[{'id': 'survey', 'purpose': 'x', 'kind': 'read',
                                                     'target': {'providerInstanceId': 'grok', 'model': 'grok-4.6'}}])
        run.record('transition', {'to': 'executing'})
        dispatch = run.only('dispatch')
        self.assertEqual(dispatch['args']['target']['providerInstanceId'], 'grok')
        run.record('dispatch', {'action_id': dispatch['id'], 'error': {'code': 'capability_denied', 'message': 'Provider is not authenticated'}})
        data = run.next()
        self.assertEqual(data['blocked']['code'], 'provider_unavailable')
        self.assertEqual(data['blocked']['task_ids'], ['survey'])


class CancellationTest(TaskBase):
    def cancelling_run(self):
        repo, run = self.read_run(tasks=[{'id': 'a', 'purpose': 'x', 'kind': 'read'},
                                         {'id': 'b', 'purpose': 'y', 'kind': 'read'}])
        run.record('transition', {'to': 'executing'})
        t3 = FakeT3()
        for action in run.next()['actions']:
            run.record('dispatch', {'action_id': action['id'], 'response': t3.call(action['host_call'])})
        run.record('transition', {'to': 'cancelling', 'reason': 'operator asked to cancel'})
        return run, t3

    def test_cancelled_only_after_confirmed_stop(self):
        run, t3 = self.cancelling_run()
        cancels = run.next()['actions']
        self.assertEqual([a['action'] for a in cancels], ['cancel_task', 'cancel_task'])
        code, env, _ = run.record_raw('transition', {'to': 'cancelled'})
        self.assertEqual(code, 4, 'cannot announce cancellation before stops are confirmed')
        for action in cancels:
            run.record('cancel', {'response': t3.call(action['host_call'])})
        confirms = run.next()['actions']
        self.assertEqual([a['action'] for a in confirms], ['confirm_stop', 'confirm_stop'])
        for task in t3.tasks.values():
            task['queue'] = [{'status': 'interrupted', 'workState': 'result_available', 'summary': 'stopped'}]
        for action in confirms:
            run.record('observation', {'response': t3.call(action['host_call'])})
        self.assertEqual(run.only('transition')['args']['to'], 'cancelled')
        run.record('transition', {'to': 'cancelled'})
        self.assertEqual(run.status()['phase'], 'cancelled')
        self.assertTrue(all(o['confirmed'] for o in run.state['cancellation']['outcomes']))

    def test_unconfirmed_stop_stays_blocked_with_exact_task_ids(self):
        run, t3 = self.cancelling_run()
        for action in run.next()['actions']:
            run.record('cancel', {'response': t3.call(action['host_call'])})
        confirms = run.next()['actions']
        first = confirms[0]
        t3.tasks[first['args']['host_task_id']]['queue'] = [{'status': 'interrupted', 'workState': 'result_available'}]
        for action in confirms:
            run.record('observation', {'response': t3.call(action['host_call'])})
        data = run.next()
        self.assertEqual(data['blocked']['code'], 'cancel_unconfirmed')
        self.assertEqual(data['blocked']['task_ids'], [confirms[1]['args']['host_task_id']])
        run.record('block', {'blocker': data['blocked']})
        self.assertEqual(run.status()['phase'], 'blocked')
        self.assertEqual(run.state['resume_phase'], 'cancelling')

    def test_cleanup_never_signals_an_unrelated_process(self):
        repo, run = self.read_run()
        sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(lambda: sleeper.wait(timeout=10))
        self.addCleanup(sleeper.kill)
        run.record('resource', {'kind': 'process', 'pid': sleeper.pid, 'purpose': 'dev server'})
        resource = run.state['resources'][0]
        # Simulate pid reuse: the recorded fingerprint no longer matches the live process.
        state_file = run.run_dir / 'run.json'
        data = json.loads(state_file.read_text())
        data['resources'][0]['fingerprint'] = 'Thu Jan  1 00:00:00 1970 /usr/bin/unrelated'
        state_file.write_text(json.dumps(data))
        out = run.record('cleanup', {'resource_id': resource['id']})
        self.assertEqual(out['result']['status'], 'gone')
        self.assertIsNone(sleeper.poll(), 'the unrelated process is still running')
