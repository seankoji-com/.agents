"""Pass 8 regressions: synthetic owned transport, no live models or GitHub."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.jobs import prepare, record_dispatch, record_result, retry_task, revise_plan, worker_write, JobError
from core.jobs.store import _atomic, canonical
from core.jobs.results import parse_result, ResultError
from shared.job_acceptance import _check_slots, _authoritative, validate_final, AcceptanceError
from tests import test_jobs_review_r3 as job_fixtures

class Pass8JobsTests(unittest.TestCase):
    def setUp(self):
        self.fx = job_fixtures.Stage3Repair5Tests(); self.fx.setUp()
    def test_shared_issue28_fixture_carries_observed_identity_policy(self):
        self.assertEqual(self.fx.fx.base_job()['policy']['identity'], 'observed')
    def prepared(self, store):
        ref = prepare(store, self.fx.caller(), 't0', lambda *_: True, lambda *_: True)
        brief = json.loads(Path(ref['path']).read_text())
        result = self.fx.fx.valid_result()
        for key in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256','revision'):
            result[key] = brief[key]
        result['binding'] = brief['snapshot']
        result['requirements'] = [{'id':r['id'],'status':'passed','evidence':['fixture']} for r in brief['requirements']]
        return result
    def ingest(self, store, result, outer=None):
        request = result['request_id']; task = next(t for t in store.load()['tasks'] if t['task_id'] == 't0')
        if task.get('review_required'):
            target = task.get('target') or {'providerInstanceId':'claudeAgent','model':'claude-haiku-0','lineage':'anthropic'}
            if not task.get('target'):
                state = store.load(); state['tasks'][0]['target'] = target; _atomic(store.file, canonical(state))
                task = next(t for t in store.load()['tasks'] if t['task_id'] == 't0')
            owned = task.get('handles', []) + task.get('followups', [])
            host = 'synthetic-' + request
            if not any(h.get('request_id') == request for h in owned):
                record_dispatch(store, self.fx.caller(), 't0', {'kind':'accepted','request_id':request,
                    'host_task_id':host,'status':'running','work_state':'working',
                    'has_pending_child_runs':False,'status_identity':{'providerInstanceId':target['providerInstanceId'],
                    'model':target['model']}})
            record = record_result(store, self.fx.caller(), 't0', {'request_id':outer or request,
                'completion_id':request+'-done','result':json.dumps(result).encode()})
            task = next(t for t in store.load()['tasks'] if t['task_id'] == 't0')
            handle = next((h for h in task.get('handles', []) if h.get('request_id') == request), None)
            if handle and handle.get('status') not in ('completed','failed','cancelled','interrupted'):
                record_dispatch(store, self.fx.caller(), 't0', {'kind':'completion','request_id':request,
                    'host_task_id':host,'completion_id':request+'-done','status':'completed',
                    'work_state':'result_available','has_pending_child_runs':False})
            return record
        return record_result(store, self.fx.caller(), 't0', {'request_id':outer or result['request_id'],
            'completion_id':result['request_id']+'-done','result':json.dumps(result).encode()})
    def test_omitted_policy_limit_is_retained_and_explicit_removal_needs_owner(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.store(td); state = store.load(); state['policy']['max_live_workers']=2
            _atomic(store.file, canonical(state)); plan=copy.deepcopy(state); plan['policy'].pop('max_live_workers')
            revise_plan(store,self.fx.caller(),{'id':'omit-limit'},plan)
            self.assertEqual(store.load()['policy']['max_live_workers'],2)
            plan=store.load(); plan['policy']['max_live_workers']=None
            with self.assertRaisesRegex(JobError,'owner decision'):
                revise_plan(store,self.fx.caller(),{'id':'remove-limit'},plan)
    def test_late_result_preserves_old_execution_and_does_not_poison_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            store=self.fx.store(td); old=self.prepared(store); self.fx.accepted_handle(store)
            record_dispatch(store,self.fx.caller(),'t0',{'kind':'reconciled','request_id':'req0','host_task_id':'host0','status':'completed','work_state':'result_available','has_pending_child_runs':False})
            # R16-ST-01: a terminal result is imported before a charged replacement supersedes its request.
            self.ingest(store,old); preserved=store.load()['tasks'][0]
            self.assertEqual((preserved['attempt'],preserved['execution_history'][0]['request_id']),(1,'req0'))
            retry_task(store,self.fx.caller(),'t0','fixture replacement'); new=self.prepared(store)
            record_dispatch(store,self.fx.caller(),'t0',{'kind':'accepted','request_id':new['request_id'],'host_task_id':'host1'})
            before=store.load()['tasks'][0]
            self.assertEqual(before['request_id'],new['request_id'])
            self.ingest(store,new); after=store.load()['tasks'][0]
            self.assertEqual(after['status'],'awaiting-acceptance')
            self.assertEqual(after['attempt'],2); self.assertEqual(after['execution_history'][0]['request_id'],'req0')
            self.ingest(store,new); self.assertEqual(store.load()['tasks'][0]['attempt'],2)
    def test_current_malformed_completion_is_charged_once_and_raw_bytes_retained(self):
        with tempfile.TemporaryDirectory() as td:
            store=self.fx.store(td); self.prepared(store)
            payload={'request_id':'req0','completion_id':'malformed','result':b'not JSON'}
            record_result(store,self.fx.caller(),'t0',payload); record_result(store,self.fx.caller(),'t0',payload)
            task=store.load()['tasks'][0]; self.assertEqual(task['attempt'],1); self.assertEqual(task['status'],'failed')
            self.assertEqual(Path(task['execution_history'][0]['transport_ref']['transport_path']).read_bytes(),b'not JSON')
    def test_ingestion_cannot_use_worker_claim_to_choose_a_different_owned_request(self):
        with tempfile.TemporaryDirectory() as td:
            store=self.fx.store(td); result=self.prepared(store); before=store.file.read_bytes()
            with self.assertRaises(JobError): self.ingest(store,result,'invented')
            self.assertEqual(store.file.read_bytes(),before)
            result['request_id']='worker-invented'; self.ingest(store,result,'req0')
            self.assertEqual(store.load()['tasks'][0]['attempt'],1)
    def test_adverse_unavailable_and_absent_required_reviews_block_ready_slots(self):
        for verdict, required in (('adverse',False),('unavailable',False),(None,True),('approve',True)):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as td:
                store=self.fx.store(td); state=store.load(); state['tasks'][0]['review_required']=required; _atomic(store.file,canonical(state))
                result=self.prepared(store); result['review_verdict']=verdict; self.ingest(store,result); state=store.load()
                with self.assertRaises((AcceptanceError,KeyError)):
                    _check_slots(store,state,state['stages'][0])
    def test_noncanonical_artifact_alias_is_refused_before_a_write(self):
        with tempfile.TemporaryDirectory() as td:
            store=self.fx.store(td); state=store.load(); state['tasks'][0]['write_scope']={'mode':'worker-evidence','path':'artifacts/tasks/t0'}; _atomic(store.file,canonical(state))
            worker_write(store,self.fx.caller(),'t0','artifacts/tasks/t0/full.json',b'original')
            with self.assertRaises(JobError): worker_write(store,self.fx.caller(),'t0','artifacts/tasks/t0//full.json',b'overwrite')
            self.assertEqual((store.path/'artifacts/tasks/t0/full.json').read_bytes(),b'original')
    def test_waiver_cannot_extend_to_another_requirement(self):
        result=self.fx.fx.valid_result(); owner={'id':'owner','scope':'waiver:t0','requirement_ids':['other']}
        result['requirements']=[{'id':'R1','status':'waived','evidence':['record'],'reason':'fixture','owner_evidence':owner}]
        expected=self.fx.fx.expected_result(result); expected.update(owner_waivers=[owner],waivable_requirements=['R1'])
        with self.assertRaises(ResultError): parse_result(json.dumps(result).encode(),expected)
    def test_validator_cannot_omit_an_expected_criterion(self):
        output={'accepted':True,'requirement_outcomes':{'C1':{'status':'passed','evidence':['fixture']}}}
        self.assertFalse(_authoritative(json.dumps(output).encode(),{},['C1','C2'])[0])
        self.assertTrue(_authoritative(json.dumps(output).encode(),{},['C1'])[0])
    def test_final_gate_rejects_orphan_requirement_and_retains_pass_charge(self):
        with tempfile.TemporaryDirectory() as td:
            store=self.fx.store(td); state=store.load(); state['requirements']['ORPHAN']='no stage assigned'; _atomic(store.file,canonical(state))
            with patch('shared.job_acceptance.verify_all_pins',return_value=store.load()):
                outcome=validate_final(store,self.fx.caller(),{}, {})
            self.assertFalse(outcome['accepted']); self.assertEqual(store.load()['final_passes'],1)


class Pass8BenchTests(unittest.TestCase):
    def test_review_requires_captured_transport_and_relevant_changed_executable_line(self):
        from tests.test_bench_v2 import five_stage, workspace, synthetic_review_context
        with tempfile.TemporaryDirectory() as td:
            target=workspace(Path(td)); review=(target/'notes/review.md').read_text()
            self.assertFalse(five_stage.independent_review_matches(target,None,review))
            context=synthetic_review_context(target,Path(td)/'coordinator.json')
            self.assertTrue(five_stage.independent_review_matches(target,context,review))
            self.assertFalse(five_stage.relevant_changed_line(target,1))
            self.assertTrue(five_stage.relevant_changed_line(target,22))
            (target/'ledger/model.py').write_text((target/'ledger/model.py').read_text()+'\n# after review change\n')
            self.assertFalse(five_stage.independent_review_matches(target,context,review))
    def test_numeric_reproducer_is_computed_and_prompt_does_not_disclose_answer(self):
        from tests.test_bench_v2 import five_stage, V2
        self.assertTrue(five_stage.numeric_reproducer('0.29','0.28','0.29'))
        self.assertFalse(five_stage.numeric_reproducer('0.29','0.29','0.29'))
        self.assertNotIn('Actual: 0.28',(V2/'fixtures/five_stage/prompt.md').read_text())
    def test_malformed_capture_ledgers_return_structured_failure(self):
        from tests.test_bench_v2 import captured_ledger
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); paths=[root/n for n in ('pre.json','context.json','cap.json')]
            for p in paths:p.write_text('[]')
            checks=captured_ledger.verify(*paths,'workflow-ape',{},[],[])
            self.assertFalse(checks['ledger-records-objects'])
    def test_boolean_model_options_reject_integer_zero(self):
        from tests.test_bench_v2 import attempt_record
        # Build the same sanitized fixture used by the existing schema controls.
        record={}
        record['provider_instance_id']='claudeAgent'; record['model_as_read_back']={'provider_instance_id':'claudeAgent','model_id':'claude-haiku-0'}
        record['model_options']={'thinking':0}
        self.assertTrue(any('thinking' in error for error in attempt_record.validate(record)))

class Pass8ContainerTests(unittest.TestCase):
    def test_beta_token_count_route_is_exact_and_remains_non_inference(self):
        from tests.test_bench_container import gateway, GatewayFixture, FakeUpstream, request
        fx=GatewayFixture(); fx.setUp()
        try:
            gateway.TARGETS={'claudeAgent':'claude-haiku-4-5'}; gateway.TARGET_OPTIONS={'claudeAgent':{'thinking':False}}
            with patch.object(gateway.http.client,'HTTPSConnection',FakeUpstream):
                code,_=request(None,'/v1/messages/count_tokens?beta=true',{'model':'claude-haiku-4-5'})
            self.assertEqual(code,200)
            self.assertNotIn('service_tier',json.loads(FakeUpstream.calls[-1]['body']))
            with patch.object(gateway.http.client,'HTTPSConnection',FakeUpstream):
                code,_=request(None,'/v1/messages/count_tokens?beta=true&beta=true',{'model':'claude-haiku-4-5'})
            self.assertEqual(code,400)
        finally:fx.tearDown()
    def test_gateway_replaces_client_authentication_with_its_synthetic_fixture_key(self):
        from tests.test_bench_container import gateway, GatewayFixture, FakeUpstream, request
        fx=GatewayFixture();fx.setUp()
        try:
            with patch.object(gateway.http.client,'HTTPSConnection',FakeUpstream):
                code,_=request(None,'/v1/responses',{'model':'gpt-6-luna','reasoning':{'effort':'low'}})
            self.assertEqual(code,200); headers=FakeUpstream.calls[-1]['headers']
            self.assertEqual(headers['Authorization'],'Bearer synthetic-gateway-openai')
            self.assertNotIn('not-a-real-key',str(headers))
        finally:fx.tearDown()
    def test_extended_thinking_is_rejected_even_with_low_effort(self):
        from tests.test_bench_container import gateway, GatewayFixture
        fx=GatewayFixture();fx.setUp()
        try:
            with self.assertRaises(ValueError):
                gateway.enforce_options('anthropic',{'output_config':{'effort':'low'},'thinking':{'type':'enabled','budget_tokens':90000}},'claude-haiku-5-5')
        finally:fx.tearDown()
    def test_stream_reports_upstream_failure_and_downstream_cancellation_separately(self):
        from tests.test_bench_container import gateway
        import io
        class Upstream:
            def read1(self,_):raise ConnectionResetError()
        class Downstream:
            def write(self,_):raise BrokenPipeError()
        with self.assertRaises(gateway.TransportFailure) as caught:gateway.relay_stream(Upstream(),io.BytesIO())
        self.assertEqual(caught.exception.failure_kind,'upstream-failure')
        response=type('Reply',(),{'read1':lambda self,_:b': heartbeat\n\n'})()
        with self.assertRaises(gateway.TransportFailure) as caught:gateway.relay_stream(response,Downstream())
        self.assertEqual(caught.exception.failure_kind,'downstream-cancellation')
    def test_cancelled_child_is_terminal_but_cannot_pass_quality(self):
        """R21-container-fresh-01: only the success guard separates a cancelled child from a verified one."""
        from tests.test_bench_container import host_observations
        target={'providerInstanceId':'codex','model':'gpt-0-luna','options':{'reasoningEffort':'low','serviceTier':'default'}}
        selection={'instanceId':'codex','model':'gpt-0-luna','options':[{'id':key,'value':value} for key,value in target['options'].items()]}
        def observed(status):
            # Every other required check is satisfied: exact target, projected child selection, a
            # completed projected run, no pending runs or approvals, no unexpected visible child.
            return {'parent_thread_id':'p','subagents':[{'id':'t','childThreadId':'child-t'}],
                    'threads':[{'id':'p'},{'id':'child-t','modelSelection':selection}],
                    'runs':[{'threadId':'child-t','status':'completed','modelSelection':selection}],
                    'runtime_requests':[],'tool_records':[
                {'toolName':'t3-code.delegate_task','input':{'target':target},'output':{'taskId':'t'}},
                {'toolName':'t3-code.task_status','input':{'taskId':'t'},'output':{'taskId':'t','status':status,'workState':'result_available','hasPendingChildRuns':False,'providerInstanceId':'codex','model':'gpt-0-luna','childThreadId':'child-t'}}]}
        completed=host_observations.verify_owned_tasks(observed('completed'),['t'],target)
        self.assertTrue(completed['verified'],completed['checks'])
        self.assertTrue(all(completed['checks'].values()),completed['checks'])
        for status in ('cancelled','failed','interrupted'):
            with self.subTest(status=status):
                result=host_observations.verify_owned_tasks(observed(status),['t'],target)
                self.assertTrue(result['checks']['terminal_no_pending'])
                self.assertEqual([name for name,ok in result['checks'].items() if not ok],['all_children_successful'])
                self.assertFalse(result['verified'])

    def test_cancellation_regression_detects_removed_success_guard(self):
        """Removing only the success guard from an in-memory copy makes the cancellation test fail."""
        import types
        from tests import test_bench_container
        original=test_bench_container.host_observations
        guard="checks['all_children_successful'] &= bool(status and status.get('status') == 'completed')"
        source=Path(original.__file__).read_text()
        self.assertEqual(source.count(guard),1)
        mutant=types.ModuleType('host_observations_without_success_guard')
        mutant.__file__=original.__file__
        exec(compile(source.replace(guard,"checks['all_children_successful'] &= True"),original.__file__,'exec'),mutant.__dict__)
        def outcome(module):
            result=unittest.TestResult()
            with patch.object(test_bench_container,'host_observations',module):
                Pass8ContainerTests('test_cancelled_child_is_terminal_but_cannot_pass_quality').run(result)
            return result.wasSuccessful()
        self.assertTrue(outcome(original))
        self.assertFalse(outcome(mutant))
        # The previous fixture (no projected selection or runs) could not tell the two apart.
        target={'providerInstanceId':'codex','model':'gpt-0-luna','options':{'reasoningEffort':'low','serviceTier':'default'}}
        old={'parent_thread_id':'p','subagents':[{'id':'t'}],'tool_records':[
            {'toolName':'t3-code.delegate_task','input':{'target':target},'output':{'taskId':'t'}},
            {'toolName':'t3-code.task_status','input':{'taskId':'t'},'output':{'taskId':'t','status':'cancelled','workState':'result_available','hasPendingChildRuns':False,'providerInstanceId':'codex','model':'gpt-0-luna'}}]}
        for module in (original,mutant):
            result=module.verify_owned_tasks(copy.deepcopy(old),['t'],target)
            self.assertEqual((result['checks']['terminal_no_pending'],result['verified']),(True,False))

    def test_wait_timeout_retains_wait_only_recovery_and_never_relaunches(self):
        from tests.test_bench_container import benchctl
        import subprocess
        with tempfile.TemporaryDirectory() as td, patch.object(benchctl.subprocess,'run',side_effect=subprocess.TimeoutExpired('fixture',1)) as runner:
            with self.assertRaisesRegex(RuntimeError,'wait/read only'):
                benchctl.driver({'containers':{'agent':'synthetic-owned'}},['--wait-thread','retained-id'],Path(td)/'log')
            self.assertEqual(runner.call_count,1);self.assertEqual(runner.call_args.kwargs['timeout'],2850)

if __name__=='__main__': unittest.main()
