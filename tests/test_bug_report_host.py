"""Finite fake-host exercises of actual emitted requests and retained observations."""
import copy
import json
import math
import os
import subprocess
import sys
from pathlib import Path
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import test_bug_report as fixtures
ledger, problem, URL, IDEA = fixtures.ledger, fixtures.problem, fixtures.URL, fixtures.IDEA


class FakeHost:
    """Accept only supported destination-bearing shapes. No external I/O."""
    def __init__(self):
        self.requests=[]
        self.objects={}
        self.threads={}
        self.schedules={}
        self.pages=[]

    def invoke(self, request, now):
        self.requests.append(copy.deepcopy(request))
        transport=request['transport']
        if transport == 'github-create-issue':
            args=request['arguments']
            assert args['repository_full_name']=='pingdotgg/t3code'
            payload={k:args[k] for k in ('title','body')};url=URL
        elif transport == 'github-rest':
            assert request['method']=='POST'
            endpoint=request['endpoint']
            assert endpoint.startswith('repos/pingdotgg/t3code/issues')
            payload=request['input']
            url=URL if endpoint.endswith('issues') else (
                'https://github.com/pingdotgg/t3code/issues/'+endpoint.split('/')[-2]
                +'#issuecomment-'+str(len(self.requests)))
        else:
            assert transport=='github-graphql'
            variables=request['variables']
            if 'createDiscussion' in request['query']:
                assert variables['r']=='fixture-repository' and variables['c']=='fixture-ideas'
                payload={'title':variables['t'],'body':variables['b']};url=IDEA
            else:
                assert variables['d']=='fixture-discussion'
                payload={'body':variables['b']};url=IDEA+'#discussioncomment-'+str(len(self.requests))
        created=datetime.fromtimestamp(math.floor(now),timezone.utc).isoformat().replace('+00:00','Z')
        if transport=='github-graphql':
            obj={'id':'fixture-discussion','url':url,'createdAt':created,**payload}
            result={'data':{'createDiscussion' if 'title' in payload else 'addDiscussionComment':{
                'discussion' if 'title' in payload else 'comment':obj}}}
        elif transport=='github-create-issue':
            obj={'id':123,'url':url,'created_at':created,**payload}
            result={'issue':obj}
        else:
            obj={'id':len(self.requests),'html_url':url,'created_at':created,**payload}
            result=obj
        self.objects[url]=obj
        return copy.deepcopy(result)

    def fetch(self,url):
        return copy.deepcopy(self.objects[url])

    def observed(self,url):
        obj=self.fetch(url)
        return {'url':obj.get('url',obj.get('html_url')),
                'created_at':datetime.fromisoformat(obj.get('created_at',obj.get('createdAt')).replace('Z','+00:00')).timestamp(),
                'payload':{k:obj[k] for k in ('title','body') if k in obj}}

    def launch(self,payload):
        assert payload['scratch'] is True and 'workspaceStrategy' not in payload
        self.threads['reporter']={'threadId':'reporter','status':'preparing','message':payload['message']}
        return copy.deepcopy(self.threads['reporter'])

    def schedule(self,payload):
        assert payload['schedule']=={'type':'interval','everyMs':120000}
        assert payload['bindToCurrentThread'] is True
        result={'scheduledTaskId':'owned-schedule','nextRunAt':'1970-01-01T00:18:40Z','boundThreadId':'reporter','enabled':True}
        self.schedules['owned-schedule']=result
        return copy.deepcopy(result)


class HostWorkflow(unittest.TestCase):
    def setUp(self):
        self.c=fixtures.Reporting();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.host=FakeHost()

    def launch(self):
        op=self.c.prepared('launch',payload={'title':'Report case','message':'Reviewed case summary','scratch':True})
        payload=self.c.call('send',{'operation':op['operation']})['payload']
        obs=self.host.launch(payload)
        self.c.finish(op,thread_id=obs['threadId'],state=obs['status'])

    def post(self,kind='issue',**kwargs):
        op=self.c.prepared(kind,**kwargs)
        request=self.c.call('send',{'operation':op['operation']})['request']
        result=self.host.invoke(request,self.c.now)
        # Read the actual object after dispatch; retain real REST/GraphQL field shapes.
        obj=result.get('issue',result)
        if 'data' in result:
            obj=next(iter(next(iter(result['data'].values())).values()))
        fetched=self.host.observed(obj.get('url',obj.get('html_url')))
        self.c.finish(op,url=fetched['url'],created_at=fetched['created_at'],timestamp_precision=1,
                      payload_sha256=ledger.digest(fetched['payload']))
        return op

    def test_real_synthetic_limit_observation_and_unsupported_fix_refused(self):
        # A disposable filesystem model enforces the observed component limit.
        def write_component(name,limit):
            if len(name.encode())>limit:raise OSError('fixture component too long')
            return len(name.encode())
        self.assertEqual(write_component('a'*143,143),143)
        with self.assertRaises(OSError):write_component('a'*144,143)
        p=problem();p['environment']={'component_limit':143}
        p['claims'].append({'text':'A different-limit patch fixes this environment',
            'evidence':'fixture:255-limit-patch','limits':'Only a 255-byte limit was tested',
            'fixes_affected_environment':True,'tested_environment':{'component_limit':255},
            'fix_observation':'fixture:255-result'})
        self.c.call('problem',p);self.c.search()
        with self.assertRaises(ledger.Held):self.launch()
        self.assertEqual(self.host.requests,[])
        p['claims'].pop();self.c.call('problem',p);self.c.search();self.launch()
        draft=ledger.redact(ledger.render(p),[])
        self.post(payload={'title':p['evidence']['symptom'],'body':draft})
        body=self.host.observed(URL)['payload']['body']
        for expected in ['143','144','255 bytes has not been tested','Expected','Actual','Impact','Procedure','Results','Platform','Provider','Version','Claims and limits']:
            self.assertIn(expected,body)

    def test_mixed_gateway_failure_and_deliberate_restriction_route_individually(self):
        # Observed transport ownership and documented trust boundary are distinct.
        gateway={'status':502,'owner':'provider','body':'Gateway unavailable'}
        policy={'external_server_credentials':'deliberately withheld','opt_in_exists':False}
        p=problem('gateway','external')
        p['evidence'].update(symptom='Provider gateway returns 502',actual=gateway['body'],
                             procedure='Call disposable gateway fixture',results=gateway)
        p.update(ownership_evidence='fixture:provider returned 502',destination='https://github.com/example/provider/issues')
        suggested=self.c.call('problem',p)['draft']
        self.assertIn('502',suggested)
        with self.assertRaises(ledger.Held):self.c.prepared('issue',pid='gateway')
        p=problem('opt-in','t3-improvement')
        p['evidence'].update(symptom='Request explicit opt-in for external credentials',
            expected='Owner-controlled opt-in',actual=policy['external_server_credentials'],
            procedure=None,results=None)
        p.update(documentation='fixture:current trust policy',ownership_evidence='fixture:T3 deliberate boundary',
                 expectation_evidence='fixture:new requested capability')
        self.c.call('problem',p);self.c.search('opt-in');
        op=self.c.prepared('launch',pid='opt-in',payload={'title':'Ideas case','message':'Known deliberate restriction; request opt-in','scratch':True})
        self.c.call('send',{'operation':op['operation']});obs=self.host.launch(op['payload'])
        self.c.finish(op,thread_id=obs['threadId'],state=obs['status'])
        self.post('idea',pid='opt-in',payload={'title':p['evidence']['symptom'],'body':ledger.render(p)})
        self.assertIn('deliberately withheld',self.host.observed(IDEA)['payload']['body'])
        self.assertEqual(len(self.host.requests),1)
        self.assertIn('createDiscussion',self.host.requests[0]['query'])

    def test_actual_external_arguments_cannot_escape_destination_contract(self):
        self.c.ready();self.launch()
        for payload in [{'body':'data','title':'title','owner':'example','repo':'external'},
                        {'body':'data','title':'title','repository_full_name':'example/external'},
                        {'body':'data','title':'title','endpoint':'repos/example/external/issues'}]:
            with self.assertRaises(ledger.Held):self.c.prepared('issue',payload=payload)
        self.post('issue',transport='github-create-issue')
        self.assertEqual(self.host.requests[0]['arguments']['repository_full_name'],'pingdotgg/t3code')

    def test_lost_write_response_subsecond_timestamp_and_reconciliation(self):
        self.c.ready();self.launch();self.c.now=1000.75
        op=self.c.prepared('issue');r=self.c.call('send',{'operation':op['operation']})
        self.host.invoke(r['request'],self.c.now)  # effect happens, response lost
        self.c.call('finish',{'operation':op['operation'],'uncertain':True})
        with self.assertRaises(ledger.Held):self.c.prepared('issue')
        actual=self.host.observed(URL)
        self.c.call('reconcile',{'operation':op['operation'],'observation':{
            'fetched':True,'operation_hash':op['hash'],'url':actual['url'],'created_at':actual['created_at'],
            'timestamp_precision':1,'payload_sha256':ledger.digest(actual['payload'])}})
        self.assertEqual(self.c.store.status('case')['deadline'],2800)
        self.assertEqual(len(self.host.requests),1)

    def test_same_evidence_rephrased_does_not_post_twice(self):
        self.c.ready(selected=URL);self.launch();self.post('comment',target=URL)
        duplicate=self.c.prepared('comment',target=URL,payload={'body':'Rephrased unchanged evidence'})
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.host.requests),1)

    def test_prepared_classification_and_routing_generations_are_rechecked(self):
        self.c.ready();self.launch();op=self.c.prepared('issue')
        p=problem(outcome='unconfirmed');p['missing']='conflicting owner observation'
        self.c.call('problem',p)
        with self.assertRaises(ledger.Held):self.c.call('send',{'operation':op['operation']})
        self.assertEqual(self.host.requests,[])

    def test_repeat_reads_observe_later_pages_and_edited_comments(self):
        self.c.monitoring()
        first=[{'id':'a','author':'bot','body':'timeline?'}]
        self.host.pages=[first]
        for wake,expected in [(1120,1),(1240,2)]:
            self.c.now=wake
            op=self.c.prepared('read',read_key='comments',payload={'target':URL})
            self.c.call('send',{'operation':op['operation']})
            items=[item for page in self.host.pages for item in page]
            self.c.finish(op)
            result=self.c.call('comments',{'target':URL,'pages_complete':True,'actor':'owner','items':items})
            self.assertEqual(len(result['comments']),expected)
            self.host.pages=[[{'id':'a','author':'bot','body':'edited timeline and launcher?'}],
                             [{'id':'b','author':'maintainer','body':'Which release?'}]]

    def test_reply_is_bound_to_request_version_and_real_public_response(self):
        self.c.ready();self.launch();initial=self.post()
        self.c.search(selected=URL)
        request={'target':URL,'pages_complete':True,'actor':'owner',
                 'items':[{'id':'ask','author':'triage','body':'Which version?'}]}
        version=self.c.call('comments',request)['comments'][0]['version']
        with self.assertRaises(ledger.Held):
            self.c.call('handled',{'version':version,'disposition':'answered','operation':initial['operation']})
        self.assertEqual(len(self.c.store.status('case')['unanswered']),1)
        response=self.post('reply',target=URL,comment_version=version,reference_operation=initial['operation'],
                           payload={'body':'Evidence is already recorded here: '+URL+'.'})
        self.c.call('handled',{'version':version,'disposition':'answered','operation':response['operation']})
        self.assertEqual(self.c.store.status('case')['unanswered'],[])
        self.assertIn(URL,self.host.requests[-1]['input']['body'])

    def test_diagnostic_budget_stays_active_and_bounded_after_publication(self):
        self.c.monitoring();self.c.call('budget',{'active':True})
        op=self.c.prepared('diagnostic',scope='read-only',safe_procedure_reviewed=True)
        self.c.call('budget',{'active':False})
        with self.assertRaises(ledger.Held):self.c.call('send',{'operation':op['operation']})
        self.c.call('reconcile',{'operation':op['operation'],'absent':True,'complete_search':True,'evidence':'No send occurred'})
        self.c.call('budget',{'active':True});self.c.now+=601
        with self.assertRaises(ledger.Held):self.c.prepared('diagnostic',scope='read-only',safe_procedure_reviewed=True)
        # Periodic monitoring reads have the independent fixed deadline.
        self.c.prepared('read',read_key='monitor-comments')

    def test_inflight_diagnostic_time_cannot_be_paused_out_of_budget(self):
        self.c.call('budget',{'active':True})
        op=self.c.prepared('diagnostic',scope='read-only',safe_procedure_reviewed=True)
        self.c.call('send',{'operation':op['operation']});self.c.now+=100
        with self.assertRaises(ledger.Held):self.c.call('budget',{'active':False})
        self.c.finish(op)
        self.assertEqual(self.c.call('budget',{'active':False})['spent'],100)

    def test_uncertain_diagnostic_and_investigative_read_remain_charged(self):
        for kind in ('diagnostic','read'):
            c=fixtures.Reporting();c.setUp()
            try:
                c.call('budget',{'active':True})
                op=c.prepared(kind,read_key='investigation',scope='read-only',safe_procedure_reviewed=True)
                c.call('send',{'operation':op['operation']})
                c.call('finish',{'operation':op['operation'],'uncertain':True})
                with self.assertRaises(ledger.Held):c.call('budget',{'active':False})
                with self.assertRaises(ledger.Held):c.call('reconcile',{'operation':op['operation'],'absent':True,
                    'complete_search':True,'evidence':'No public effect, but request still running'})
                c.now+=1000
                # A terminal observation now proves actual completion; elapsed work stays charged.
                c.call('reconcile',{'operation':op['operation'],'observation':{'fetched':True,
                    'operation_hash':op['hash'],'request_terminal':True}})
                self.assertEqual(c.call('budget',{'active':False})['spent'],1000)
                with self.assertRaises(ledger.Held):c.prepared('diagnostic',scope='read-only',safe_procedure_reviewed=True)
            finally:c.doCleanups()

    def test_true_lock_overlap_hardlink_and_storage_failure(self):
        with self.c.store.locked():
            with self.assertRaises(BlockingIOError):self.c.call('wake')
        original=self.c.store.write
        def fail_session(fd,name,value):
            if name=='case.json':raise OSError('fixture disk full')
            return original(fd,name,value)
        self.c.ready();self.launch()
        with patch.object(self.c.store,'write',side_effect=fail_session):
            with self.assertRaises(OSError):self.c.prepared('issue')
        self.assertEqual(self.host.requests,[])
        self.assertEqual(len(self.c.store.status('case')['actions']),1)  # launch only
        os.link(self.c.root/'case.json',self.c.root/'hardlink')
        with self.assertRaises(ledger.Held):self.c.call('wake')

    def test_native_schedule_mapping_late_wake_cleanup_and_discussion_reply(self):
        self.c.ready(outcome='t3-improvement');self.launch();initial=self.post('idea')
        op=self.c.prepared('schedule',payload={'schedule':{'type':'interval','everyMs':120000},
            'bindToCurrentThread':True,'prompt':'Resume case; retain deadline 2800'})
        request=self.c.call('send',{'operation':op['operation']})['request']
        self.assertEqual(request['transport'],'t3-schedule-task')
        actual=self.host.schedule(request['arguments'])
        self.c.finish(op,task_id=actual['scheduledTaskId'],next_run=actual['nextRunAt'],bound_thread=actual['boundThreadId'])
        self.c.search(selected=IDEA)
        version=self.c.call('comments',{'target':IDEA,'pages_complete':True,'actor':'owner',
            'items':[{'id':'idea-question','author':'maintainer','body':'What is the intended opt-in?'}]})['comments'][0]['version']
        obs={'write_access':True,'templates_read':True,'repository_url':'https://github.com/pingdotgg/t3code',
             'object_url':IDEA,'discussion_id':'fixture-discussion'}
        reply=self.post('reply',transport='github-graphql',target=IDEA,comment_version=version,
                        destination_observation=obs,reference_operation=initial['operation'],
                        payload={'body':'Evidence is already recorded here: '+IDEA+'.'})
        self.c.call('handled',{'version':version,'disposition':'answered','operation':reply['operation']})
        self.c.now=2900;self.assertTrue(self.c.call('wake')['expired'])
        cleanup=self.c.prepared('cleanup',payload={'task_id':'owned-schedule'})
        request=self.c.call('send',{'operation':cleanup['operation']})['request']
        self.assertEqual(request,{'transport':'t3-delete-scheduled-task','arguments':{'scheduledTaskId':'owned-schedule'}})
        del self.host.schedules[request['arguments']['scheduledTaskId']]
        self.c.finish(cleanup,task_id='owned-schedule',disabled_or_absent='owned-schedule' not in self.host.schedules)
        self.assertEqual(self.c.store.status('case')['cleanup'],'verified')
        self.assertEqual(self.c.store.status('case')['deadline'],2800)

    def test_distinct_candidate_mechanisms_two_targets_and_partial_fix(self):
        # Two distinct observations in one incident, with different expected behavior.
        def filename_model(name):
            if len(name.encode())>143:raise OSError('fixture component exceeds 143 bytes')
        with self.assertRaises(OSError) as failure:filename_model('a'*144)
        fs=problem('fs');fs['evidence']['results']=str(failure.exception)
        dialog={'open':True}
        def press_escape():return dialog['open']  # disposable defective key-handler model
        observed_open=press_escape();self.assertTrue(observed_open)
        ui=problem('dialog');ui['evidence'].update(symptom='Escape leaves disposable dialog open',
            expected='Escape closes dialog',actual='Dialog remains open',impact='Cannot dismiss dialog',
            procedure='Open disposable dialog and press Escape',results={'open':observed_open},
            references=['fixture:escape-key-observation'])
        ui.update(observation='fixture:escape-key-observation',ownership_evidence='fixture:T3 key-handler model',
            expectation_evidence='fixture:documented Escape behavior',documentation='fixture:dialog contract',
            claims=[{'text':'Escape did not dismiss the dialog','evidence':'fixture:escape-key-observation',
                     'limits':'Disposable model, no live UI claim'}])
        self.c.call('problem',fs);self.c.call('problem',ui)
        second='https://github.com/pingdotgg/t3code/issues/124'
        candidates=[{'url':URL,'content':'Task failed: filename mechanism','comments':'closed alias points here',
                     'versions':'fixture-1','resolution':'255-byte fix leaves 143-byte variant','reason':'matches only filesystem'},
                    {'url':second,'content':'Task failed: dialog key handler','comments':'Escape event observed',
                     'versions':'fixture-1','resolution':'open','reason':'matches only dialog'}]
        fs_draft=self.c.search('fs',URL,candidates=candidates)['draft']
        ui_draft=self.c.search('dialog',second,candidates=candidates)['draft']
        op=self.c.prepared('launch',pid='fs',payload={'title':'Two distinct reports','message':'Two evidence summaries and target reasons','scratch':True})
        self.c.call('send',{'operation':op['operation']});obs=self.host.launch(op['payload'])
        self.c.finish(op,thread_id=obs['threadId'],state=obs['status'])
        with self.assertRaises(ledger.Held):self.c.prepared('comment',pid='fs',target=candidates[1]['url'])
        self.post('comment',pid='fs',target=URL,payload={'body':fs_draft})
        self.post('comment',pid='dialog',target=second,payload={'body':ui_draft})
        self.assertEqual([r['endpoint'] for r in self.host.requests],
                         ['repos/pingdotgg/t3code/issues/123/comments','repos/pingdotgg/t3code/issues/124/comments'])
        bodies={obj['html_url'].split('#')[0]:obj['body'] for obj in self.host.objects.values()}
        self.assertIn('143',bodies[URL]);self.assertNotIn('dialog',bodies[URL])
        self.assertIn('Escape',bodies[second]);self.assertNotIn('143',bodies[second])
        for url, reason in ((URL,'matches only filesystem'), (second,'matches only dialog')):
            self.assertIn('Canonical report: '+url,bodies[url])
            self.assertIn('Search assessment: Observed scope comparison',bodies[url])
            self.assertIn('Match reasoning: '+reason,bodies[url])
        self.assertEqual(len(self.c.store.status('case')['urls']),2)

    def test_existing_matching_ideas_uses_comment_not_new_discussion(self):
        self.c.ready(outcome='t3-improvement',selected=IDEA)
        self.c.search(selected=IDEA,candidates=[{'url':IDEA,'content':'matching capability',
            'comments':'closed duplicate redirects here','versions':'fixture-1','resolution':'canonical open',
            'reason':'same requested behavior'}])
        self.launch()
        with self.assertRaises(ledger.Held):self.c.prepared('idea')
        obs={'write_access':True,'templates_read':True,'repository_url':'https://github.com/pingdotgg/t3code',
             'object_url':IDEA,'discussion_id':'fixture-discussion'}
        self.post('comment',target=IDEA,transport='github-graphql',destination_observation=obs,payload={'body':ledger.render(problem(outcome='t3-improvement'))})
        self.assertEqual(len(self.host.requests),1)
        self.assertIn('addDiscussionComment',self.host.requests[0]['query'])

    def test_cross_kind_evidence_dedup_keeps_request_and_allows_reference_or_new_data(self):
        self.c.ready();self.launch();initial=self.post(payload={'title':'Fixture','body':ledger.render(problem())})
        self.c.search(selected=URL)
        duplicate=self.c.prepared('comment',target=URL,payload={'body':ledger.render(problem())})
        self.assertTrue(duplicate['duplicate'])
        version=self.c.call('comments',{'target':URL,'pages_complete':True,'actor':'owner',
            'items':[{'id':'same-data','author':'triage','body':'Please send the same evidence again'}]})['comments'][0]['version']
        duplicate=self.c.prepared('reply',target=URL,comment_version=version,payload={'body':ledger.render(problem())})
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.c.store.status('case')['unanswered']),1)
        self.assertEqual(len(self.host.requests),1)
        reference=self.post('reply',target=URL,comment_version=version,reference_operation=initial['operation'],
                            payload={'body':'Evidence is already recorded here: '+URL+'.'})
        self.c.call('handled',{'version':version,'disposition':'answered','operation':reference['operation']})
        p=problem();p['evidence']['results']+='; new independent observation'
        self.c.call('problem',p);self.c.search(selected=URL)
        self.post('comment',target=URL,payload={'body':ledger.render(p)})
        self.assertEqual(len(self.host.requests),3)

    def test_pending_write_admits_only_tracked_read_only_reconciliation(self):
        self.c.ready();self.launch();self.c.call('budget',{'active':True})
        op=self.c.prepared('issue');r=self.c.call('send',{'operation':op['operation']})
        self.host.invoke(r['request'],self.c.now)
        self.c.call('finish',{'operation':op['operation'],'uncertain':True})
        with self.assertRaises(ledger.Held):self.c.prepared('read',read_key='unrelated')
        read=self.c.prepared('read',read_key='reconcile',reconciliation_for=op['operation'],payload={'target':URL})
        self.c.call('send',{'operation':read['operation']})
        with self.assertRaises(ledger.Held):self.c.prepared('read',read_key='overlap',reconciliation_for=op['operation'])
        actual=self.host.observed(URL);self.c.finish(read)
        self.c.call('reconcile',{'operation':op['operation'],'observation':{
            'fetched':True,'operation_hash':op['hash'],'url':actual['url'],'created_at':actual['created_at'],
            'payload_sha256':ledger.digest(actual['payload'])}})
        self.assertEqual(len(self.host.requests),1)

    def test_claim_correction_with_same_raw_results_is_new_publishable_evidence(self):
        self.c.ready(selected=URL);self.launch();self.post('comment',target=URL)
        p=problem();p['claims'][0]['text']='Correction: the related patch remains unverified for this limit'
        self.c.call('problem',p);self.c.search(selected=URL)
        self.post('comment',target=URL,payload={'body':ledger.render(p)})
        self.assertEqual(len(self.host.requests),2)
        self.assertIn('Correction:',self.host.requests[-1]['input']['body'])

    def test_observed_misconfiguration_is_explained_without_reporting(self):
        config={'selected_route':'/wrong-route','documented_route':'/api'}
        def request(route):return 200 if route==config['documented_route'] else 404
        before=request(config['selected_route']);documented=request(config['documented_route'])
        self.assertEqual((before,documented),(404,200))
        p=problem('configuration','explained')
        p['evidence'].update(symptom='Configured route returns 404',expected='Use documented /api route',
            actual='Selected /wrong-route returns 404',procedure='Query disposable route fixture',
            results={'configured':before,'documented':documented},references=['fixture:route-observation'])
        p.update(ownership_evidence='fixture:selected route differs from current documented route',
                 expectation_evidence='fixture:/api returns 200',documentation='fixture:documented /api contract')
        result=self.c.call('problem',p)
        self.assertIn('/wrong-route',result['draft'])
        for kind in ('launch','issue','idea','schedule'):
            with self.assertRaises(ledger.Held):self.c.prepared(kind,pid='configuration')
        self.assertEqual(self.host.requests,[])
        self.assertEqual(self.c.store.status('case')['problems']['configuration']['outcome'],'explained')

    def test_gateway_defect_and_requested_t3_automatic_retries_are_separate(self):
        attempts=[]
        def gateway():attempts.append(502);return {'status':502,'owner':'provider-fixture'}
        observed=gateway();self.assertEqual(len(attempts),1)
        external=problem('upstream','external')
        external['evidence'].update(symptom='Provider gateway unavailable',actual='Gateway returns 502',
            procedure='One disposable gateway request',results=observed,references=['fixture:gateway-response'])
        external.update(destination='https://github.com/example/gateway/issues',ownership_evidence='fixture:provider response source')
        suggestion=self.c.call('problem',external)['draft']
        self.assertIn('502',suggestion)
        idea=problem('automatic-retry','t3-improvement')
        idea['evidence'].update(symptom='Request bounded automatic retries for upstream gateway errors',
            expected='Offer bounded automatic retries for retryable gateway errors',actual='T3 reports upstream error after one attempt',
            procedure=None,results={'observed_attempts':len(attempts)},references=['fixture:client-attempt-count'])
        idea.update(documentation='fixture:current T3 contract promises no automatic gateway retry',
            expectation_evidence='fixture:established new capability request',ownership_evidence='fixture:T3 retry-policy improvement')
        self.c.call('problem',idea);self.c.search('automatic-retry')
        op=self.c.prepared('launch',pid='automatic-retry',payload={'title':'Retry idea','message':'Upstream defect draft plus separate retry proposal','scratch':True})
        self.c.call('send',{'operation':op['operation']});obs=self.host.launch(op['payload'])
        self.c.finish(op,thread_id=obs['threadId'],state=obs['status'])
        self.post('idea',pid='automatic-retry',payload={'title':idea['evidence']['symptom'],'body':ledger.render(idea)})
        self.assertIn('bounded automatic retries',self.host.observed(IDEA)['payload']['body'])
        self.assertEqual(len(self.host.requests),1)
        self.assertIn('createDiscussion',self.host.requests[0]['query'])

    def test_sensitive_sentinels_absent_from_all_public_requests_logs_and_exports(self):
        original=self.c
        try:
            for kind in ('issue','comment','idea'):
                with self.subTest(kind=kind):
                    self.c=fixtures.Reporting();self.c.setUp();self.host=FakeHost()
                    try:
                        private_path='/'+'home'+'/synthetic/private-source'
                        self.c.call('init', {'incident_key':'synthetic-context:1', 'owner_thread':'invoker',
                            'private_values':['PRIVATE_RESUME_SENTINEL']})
                        secret='PRIVATE_TRANSCRIPT_SENTINEL PRIVATE_SOURCE_SENTINEL PRIVATE_RESUME_SENTINEL hidden.corp.invalid token=synthetic-secret '+private_path
                        p=problem(outcome='t3-improvement' if kind=='idea' else 't3-defect')
                        p['evidence']['actual']+=' '+secret
                        self.c.call('problem',p)
                        draft=self.c.search(selected=URL if kind=='comment' else None,
                            reason='Compared candidate scope '+secret)['draft']
                        self.launch()
                        self.post(kind,**({'target':URL} if kind=='comment' else {}),
                            payload={'body':draft,**({'title':'Report '+secret} if kind in {'issue','idea'} else {})})
                        url=IDEA if kind=='idea' else next(iter(self.host.objects))
                        self.assertIn('Search assessment: Compared candidate scope',
                                      self.host.observed(url)['payload']['body'])
                        exported={'requests':self.host.requests,'fetched':self.host.observed(url),
                                  'summary':self.c.store.status('case')}
                        artifact=Path(self.c.tmp.name)/'public-artifact.json'
                        artifact.write_text(json.dumps(exported))
                        inp=Path(self.c.tmp.name)/'private-input.json'
                        inp.write_text(json.dumps({'kind':'credentials','payload':{'body':secret}}))
                        result=subprocess.run([sys.executable,str(fixtures.SCRIPT),'prepare','--session','case',
                            '--state-root',str(self.c.root),'--input',str(inp)],capture_output=True,text=True,timeout=10)
                        self.assertEqual(result.returncode,2)
                        logs=result.stdout+result.stderr
                        malformed=Path(self.c.tmp.name)/'malformed-input.json'
                        malformed.write_text(json.dumps({'kind':'issue','payload':[secret]}))
                        bad=subprocess.run([sys.executable,str(fixtures.SCRIPT),'prepare','--session','case',
                            '--state-root',str(self.c.root),'--input',str(malformed)],capture_output=True,text=True,timeout=10)
                        self.assertEqual(bad.returncode,2)
                        logs+=bad.stdout+bad.stderr
                        self.assertNotIn('Traceback',logs)
                        for sentinel in ('PRIVATE_TRANSCRIPT_SENTINEL','PRIVATE_SOURCE_SENTINEL','PRIVATE_RESUME_SENTINEL','hidden.corp.invalid','synthetic-secret',private_path):
                            self.assertNotIn(sentinel,artifact.read_text())
                            self.assertNotIn(sentinel,logs)
                    finally:self.c.doCleanups()
        finally:self.c=original


if __name__=='__main__':unittest.main()
