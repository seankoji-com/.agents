"""Synthetic reporting fixtures. No live model, GitHub, T3 or configuration writes."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/bug-report/scripts/session.py'
spec = importlib.util.spec_from_file_location('bug_report_session', SCRIPT)
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)
URL = 'https://github.com/pingdotgg/t3code/issues/123'
IDEA = 'https://github.com/pingdotgg/t3code/discussions/456'


def private_fixture():
    # A host can itself check out a repository in the normal temp directory.
    for base in [Path(tempfile.gettempdir()), Path('/var/tmp')]:
        # macOS exposes its temporary root through /var -> /private/var.
        # Canonicalize the fixture, preserving the ledger's no-symlink rule.
        base = base.resolve()
        if base.is_dir() and not any((p/'.git').exists() for p in (base,*base.parents)):
            return tempfile.TemporaryDirectory(dir=base)
    raise unittest.SkipTest('no temporary directory outside repositories')


def problem(pid='p1', outcome='t3-defect'):
    return {'id': pid, 'outcome': outcome,
            'evidence': {'symptom': 'Disposable filename too long', 'expected': 'Task setup completes',
                         'actual': 'Setup refused', 'impact': 'Cannot start task', 'version': 'fixture-1',
                         'channel': None, 'provider': 'synthetic', 'platform': 'POSIX fixture',
                         'procedure': 'Create 144 byte component in a disposable 143 byte fixture',
                         'results': '143 bytes accepted, 144 refused', 'references': ['fixture:observed-1']},
            'observation': 'fixture:observed-1', 'ownership_evidence': 'fixture:source-callsite',
            'expectation_evidence': 'fixture:documented-workflow', 'documentation': 'fixture:current-doc',
            'claims': [{'text': '143 byte component limit', 'evidence': 'fixture:observed-1',
                        'limits': 'A separate patch for 255 bytes has not been tested here.'}]}


class Reporting(unittest.TestCase):
    def test_default_root_keeps_a_pre_198_ledger_until_moved(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_STATE_HOME': temp}):
            state = Path(temp)
            self.assertEqual(ledger.default_state_root(), state / 'agents/jobs/bug-report')
            (state / 't3-plugins/bug-report').mkdir(parents=True)
            self.assertEqual(ledger.default_state_root(), state / 't3-plugins/bug-report')
            (state / 'agents/jobs/bug-report').mkdir(parents=True)
            self.assertEqual(ledger.default_state_root(), state / 'agents/jobs/bug-report')

    def setUp(self):
        self.tmp = private_fixture()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'private-state'
        self.now = 1000
        self.store = ledger.Store(self.root, clock=lambda: self.now)
        self.calls = []
        self.call('init', {'incident_key': 'synthetic-context:1', 'owner_thread': 'invoker',
                           'private_values': ['PRIVATE_TRANSCRIPT_SENTINEL', 'PRIVATE_SOURCE_SENTINEL', 'hidden.corp.invalid']})

    def call(self, action, data=None, sid='case'):
        return self.store.apply(sid, action, data or {})

    def test_private_fixture_canonicalizes_system_temp_alias(self):
        base = Path(self.tmp.name).resolve()
        alias = base / 'system-temp-alias'
        alias.symlink_to(base, target_is_directory=True)
        with patch.object(tempfile, 'gettempdir', return_value=str(alias)):
            with private_fixture() as name:
                fixture = Path(name)
                self.assertEqual(fixture, fixture.resolve())
                store = ledger.Store(fixture / 'private-state')
                store.apply('alias-case', 'init', {'incident_key': 'fixture:temp-alias',
                                                 'owner_thread': 'invoker'})
                self.assertEqual(store.status('alias-case')['owner_thread'], 'invoker')

    def ready(self, pid='p1', outcome='t3-defect', selected=None):
        self.call('problem', problem(pid, outcome))
        self.search(pid, selected)

    def search(self, pid='p1', selected=None, **extra):
        return self.call('search', {'problem': pid, 'queries': ['filename alias', 'closed filename variant'],
                            'issues_complete': True, 'discussions_complete': True,
                            'candidates': [], 'selected': selected, 'reason': 'Observed scope comparison', **extra})

    def prepared(self, kind, pid='p1', **extra):
        payload = {'body': 'Expected, actual, observed evidence and limits'}
        if kind in {'issue', 'idea'}:
            payload['title'] = 'Observed fixture problem'
        return self.call('prepare', {'kind': kind, 'problem': pid, 'actor_thread': 'reporter',
                                    'privacy_reviewed': True, 'thread_search_complete': True,
                                    'destination_refreshed': True,
                                    'destination_observation': {'write_access': True, 'templates_read': True,
                                        'repository_url': 'https://github.com/pingdotgg/t3code',
                                        'repository_id': 'fixture-repository', 'ideas_category_id': 'fixture-ideas'},
                                    'transport': 'github-graphql' if kind == 'idea' else 'github-rest',
                                    'payload': payload, **extra})

    def finish(self, op, **obs):
        return self.call('finish', {'operation': op['operation'],
                                   'observation': {'fetched': True, 'operation_hash': op['hash'], 'request_terminal': True, **obs}})

    def dispatch(self, op):
        payload = self.call('send', {'operation': op['operation']})['payload']
        self.calls.append(payload)

    def launch(self):
        op = self.prepared('launch', payload={'message': 'Sanitized summary with case reference',
                                            'title': 'Reporting case', 'scratch': True})
        self.dispatch(op)
        self.finish(op, thread_id='reporter', state='preparing')
        return op

    def publish(self, kind='issue', **extra):
        op = self.prepared(kind, **extra)
        self.dispatch(op)
        url = IDEA if kind == 'idea' else URL
        if kind in {'comment', 'reply'}:
            url += '#issuecomment-' + str(len(self.calls))
        self.finish(op, url=url, created_at=self.now,
                    payload_sha256=ledger.digest(op['payload']))
        return op

    def monitoring(self):
        self.ready()
        self.launch()
        self.publish()
        op = self.prepared('schedule', payload={'schedule': {'type': 'interval', 'everyMs': 120000},
                                               'bindToCurrentThread': True, 'prompt': 'Resume case; fixed deadline 2800'})
        self.dispatch(op)
        self.finish(op, task_id='owned-schedule', next_run=1120, bound_thread='reporter')

    def test_duplicate_invocation_keeps_single_owner_and_budget(self):
        result = self.call('init', {'incident_key': 'synthetic-context:1', 'owner_thread': 'other'}, sid='another')
        self.assertEqual(result['existing_session'], 'case')
        self.assertEqual(result['owner_thread'], 'invoker')
        self.assertFalse((self.root/'another.json').exists())

    def test_resume_merges_private_literals_for_prepared_and_sent_payloads(self):
        before = json.loads((self.root/'case.json').read_text())
        resumed = self.call('init', {'incident_key': 'synthetic-context:1', 'owner_thread': 'other',
            'private_values': ['PRIVATE_RESUME_SENTINEL', 'PRIVATE_TRANSCRIPT_SENTINEL', 'PRIVATE_RESUME_SENTINEL']}, sid='another')
        after = json.loads((self.root/'case.json').read_text())
        self.assertEqual(after['private_values'], before['private_values'] + ['PRIVATE_RESUME_SENTINEL'])
        for field in ('owner_thread', 'budget', 'deadline', 'created_at'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(resumed['existing_session'], 'case')
        self.assertFalse((self.root/'another.json').exists())
        self.ready()
        op = self.prepared('launch', payload={'title':'Resume privacy', 'scratch':True,
            'message':'PRIVATE_TRANSCRIPT_SENTINEL PRIVATE_RESUME_SENTINEL'})
        self.assertEqual(op['payload']['message'], '[redacted] [redacted]')
        self.dispatch(op)
        self.assertEqual(self.calls[0]['message'], '[redacted] [redacted]')
        self.finish(op, thread_id='reporter', state='preparing')
        public = self.prepared('issue', payload={'title':'Resume privacy',
            'body':'PRIVATE_TRANSCRIPT_SENTINEL PRIVATE_RESUME_SENTINEL'})
        self.assertEqual(public['request']['input']['body'], '[redacted] [redacted]')
        self.dispatch(public)
        self.assertEqual(self.calls[-1]['body'], '[redacted] [redacted]')

    def test_new_privacy_literals_hold_unsent_intents_until_reprepared(self):
        self.ready()
        op = self.prepared('launch', payload={'title':'Resume privacy', 'scratch':True,
            'message':'PRIVATE_RESUME_SENTINEL'})
        self.call('init', {'incident_key':'synthetic-context:1', 'owner_thread':'invoker',
            'private_values':['PRIVATE_RESUME_SENTINEL']})
        before = (self.root/'case.json').read_bytes()
        with self.assertRaisesRegex(ledger.Held, 'privacy declarations changed; reconcile stale intent'):
            self.dispatch(op)
        self.assertEqual((self.root/'case.json').read_bytes(), before)
        self.assertEqual(self.calls, [])
        self.call('reconcile', {'operation':op['operation'], 'absent':True,
            'complete_search':True, 'evidence':'Intent never dispatched'})
        replacement = self.prepared('launch', payload={'title':'Resume privacy', 'scratch':True,
            'message':'PRIVATE_RESUME_SENTINEL'})
        self.dispatch(replacement)
        self.assertEqual(self.calls, [{'title':'Resume privacy', 'scratch':True, 'message':'[redacted]'}])

    def test_private_literals_require_a_list_of_nonempty_strings(self):
        before = (self.root/'case.json').read_bytes()
        for values in ('PRIVATE_RESUME_SENTINEL', [None], ['']):
            with self.subTest(values=values), self.assertRaisesRegex(ledger.Held, 'private values must be nonempty strings'):
                self.call('init', {'incident_key':'synthetic-context:1', 'owner_thread':'invoker',
                    'private_values':values})
            self.assertEqual((self.root/'case.json').read_bytes(), before)

    def test_unconfirmed_missing_intermittent_conflicting_and_unavailable_hold(self):
        for missing in ['logs', 'intermittent reproduction', 'conflicting ownership', 'safe environment']:
            p = problem(outcome='unconfirmed')
            p['missing'] = missing
            self.call('problem', p)
            self.search()
            for kind in ['launch', 'issue', 'idea', 'schedule']:
                with self.assertRaises(ledger.Held):
                    self.prepared(kind)
        self.assertEqual(self.calls, [])

    def test_intentional_restriction_external_and_configuration_are_distinct(self):
        for pid, outcome in [('restriction','t3-improvement'), ('gateway','external'), ('config','explained')]:
            p = problem(pid, outcome)
            p['destination'] = 'https://github.com/example/provider/issues'
            result = self.call('problem', p)
            self.assertEqual(result['outcome'], outcome)
        self.search('restriction')
        with self.assertRaises(ledger.Held):
            self.prepared('issue', pid='restriction')
        for pid in ['gateway', 'config']:
            with self.assertRaises(ledger.Held):
                self.prepared('launch', pid=pid)
        self.assertEqual(self.calls, [])

    def test_evidence_draft_retains_limit_and_candid_fix_boundary(self):
        draft = self.call('problem', problem())['draft']
        self.assertIn('143', draft)
        self.assertIn('255 bytes has not been tested', draft)
        self.assertIn('Unknown', draft)
        self.ready()
        p = problem(); p.pop('observation')
        self.call('problem', p); self.search()
        with self.assertRaises(ledger.Held):
            self.launch()

    def test_active_investigation_pauses_for_human_input(self):
        self.call('budget', {'active': True})
        self.now += 200
        self.assertEqual(self.call('budget', {'active': False})['spent'], 200)
        self.now += 5000
        self.call('budget', {'active': True})
        self.now += 400
        with self.assertRaises(ledger.Held):
            self.prepared('read', read_key='q')
        with self.assertRaises(ledger.Held):
            self.call('budget', {'seconds': 700})
        self.assertEqual(self.calls, [])

    def test_transient_reads_two_retries_and_repeated_failure_stop(self):
        self.call('budget', {'active': True})
        for failure in ['timeout','rate-limit','transport']:
            op = self.prepared('read', read_key='same-logical-read', payload={'query':'fixture'})
            self.dispatch(op)
            self.call('finish', {'operation': op['operation'], 'failed': True,
                                 'confirmed_no_effect': True, 'request_terminal': True, 'failure_class': failure})
        with self.assertRaises(ledger.Held):
            self.prepared('read', read_key='same-logical-read')
        for _ in range(2):
            op = self.prepared('read', read_key='repeat', payload={'query':'fixture'})
            self.dispatch(op)
            self.call('finish', {'operation': op['operation'], 'failed': True,
                                 'confirmed_no_effect': True, 'request_terminal': True, 'failure_class': 'identical'})
        with self.assertRaises(ledger.Held):
            self.prepared('read', read_key='repeat')

    def test_incomplete_search_and_candidate_title_only_hold(self):
        self.ready()
        self.search(discussions_complete=False)
        with self.assertRaises(ledger.Held): self.launch()
        self.search(candidates=[{'url':URL,'content':'same title'}])
        with self.assertRaises(ledger.Held): self.launch()
        self.assertEqual(self.calls, [])

    def test_closed_duplicate_uses_inspected_canonical_and_no_new_issue(self):
        self.ready(selected=URL)
        self.search(selected=URL, candidates=[{'url':URL,'content':'matching mechanism',
                    'comments':'closed alias redirects here','versions':'fixture-1',
                    'resolution':'partially fixed variant remains','reason':'observed scope matches'}])
        self.launch()
        with self.assertRaises(ledger.Held): self.prepared('issue')
        with self.assertRaises(ledger.Held): self.prepared('comment', target=IDEA)
        self.publish('comment', target=URL)

    def test_reporting_thread_requires_workspace_and_accepted_handle(self):
        self.ready()
        with self.assertRaises(ledger.Held): self.prepared('launch', payload={'message':'summary'})
        op = self.prepared('launch', payload={'title':'Case','message':'summary','scratch':True})
        self.dispatch(op)
        with self.assertRaises(ledger.Held): self.finish(op, thread_id='failed', state='failed')
        self.finish(op, thread_id='reporter', state='preparing')
        with self.assertRaises(ledger.Held): self.launch()

    def test_unknown_launch_reconciles_before_any_retry(self):
        self.ready()
        op = self.prepared('launch', payload={'title':'Case','message':'summary','scratch':True})
        self.dispatch(op)
        self.call('finish', {'operation':op['operation'],'uncertain':True})
        with self.assertRaises(ledger.Held): self.launch()
        self.call('reconcile', {'operation':op['operation'],'observation':{
            'fetched':True,'operation_hash':op['hash'],'thread_id':'reporter','state':'idle'}})
        self.assertEqual(self.store.status('case')['reporting_thread'],'reporter')

    def test_lost_public_response_replay_dedup_and_new_evidence(self):
        self.ready(selected=URL); self.launch()
        op = self.prepared('comment', target=URL); self.dispatch(op)
        self.call('finish', {'operation':op['operation'],'uncertain':True})
        with self.assertRaises(ledger.Held): self.prepared('comment',target=URL)
        self.call('reconcile', {'operation':op['operation'],'observation':{
            'fetched':True,'operation_hash':op['hash'],'url':URL+'#issuecomment-1','created_at':1000,
            'payload_sha256':ledger.digest(op['payload'])}})
        before = (self.root/'case.json').read_bytes()
        status = self.store.status('case')
        for action in ('finish', 'reconcile', 'send'):
            message = 'operation cannot be dispatched again' if action == 'send' else 'operation already final'
            with self.subTest(action=action), self.assertRaisesRegex(ledger.Held, message):
                self.call(action, {'operation':op['operation'], 'observation':{
                    'fetched':True, 'operation_hash':op['hash'], 'url':URL, 'created_at':1000,
                    'payload_sha256':ledger.digest(op['payload'])}})
            self.assertEqual((self.root/'case.json').read_bytes(), before)
            self.assertEqual(self.store.status('case'), status)
            self.assertEqual(len(self.calls), 2)  # launch and the original comment
        duplicate = self.prepared('comment',target=URL)
        self.assertTrue(duplicate['duplicate'])
        p=problem();p['evidence']['results'] += '; new isolated observation'
        self.call('problem',p);self.search(selected=URL)
        self.publish('comment',target=URL,payload={'body':'One new observed datum'})
        self.assertEqual(len(self.calls),3)  # launch and two comments

    def test_publication_checks_thread_access_category_and_actual_content(self):
        self.ready(outcome='t3-improvement'); self.launch()
        with self.assertRaises(ledger.Held): self.prepared('idea', actor_thread='invoker')
        with self.assertRaises(ledger.Held): self.prepared('idea',destination_observation={'write_access':True,'templates_read':True})
        op=self.prepared('idea'); self.dispatch(op)
        with self.assertRaises(ledger.Held): self.finish(op,url=URL,created_at=1000,payload_sha256=ledger.digest(op['payload']))
        with self.assertRaises(ledger.Held): self.finish(op,url=IDEA,created_at=1000,payload_sha256='wrong')
        self.finish(op,url=IDEA,created_at=1000,payload_sha256=ledger.digest(op['payload']))

    def test_fixed_deadline_survives_redirect_reclassification_and_resume(self):
        self.monitoring(); self.now += 500
        self.ready(outcome='t3-improvement')
        self.publish('idea',payload={'title':'Established improvement','body':'Established improvement, related issue 123'})
        self.assertEqual(self.store.status('case')['deadline'],2800)
        moved=ledger.Store(self.root,clock=lambda:self.now)
        self.assertEqual(moved.status('case')['monitor_started_at'],1000)
        raw=json.loads((self.root/'case.json').read_text())
        self.assertEqual(raw['problems']['p1']['history'][0]['outcome'],'t3-defect')

    def test_overlap_and_expiry_at_exact_boundary(self):
        self.monitoring(); self.now=2799
        self.call('budget',{'active':True})
        op=self.prepared('diagnostic',scope='read-only',safe_procedure_reviewed=True)
        with self.assertRaises(ledger.Held): self.prepared('read',read_key='overlap')
        self.now=2800
        with self.assertRaises(ledger.Held): self.dispatch(op)
        self.assertEqual(len(self.calls),3)

    def test_inflight_completion_after_expiry_and_cleanup_with_pending_request(self):
        self.monitoring(); self.search(selected=URL); self.now=2799
        p=problem();p['evidence']['results']+='; additional observed evidence'
        self.call('problem',p);self.search(selected=URL)
        version=self.call('comments',{'target':URL,'actor':'owner','pages_complete':True,
                'items':[{'id':'triage','author':'maintainer','body':'Please provide evidence'}]})['comments'][0]['version']
        op=self.prepared('reply',target=URL,comment_version=version,payload={'body':'Observed supporting evidence'});self.dispatch(op)
        self.now=2801
        cleanup=self.prepared('cleanup',payload={'task_id':'owned-schedule'});self.dispatch(cleanup)
        self.finish(cleanup,task_id='owned-schedule',disabled_or_absent=True)
        self.finish(op,url=URL+'#issuecomment-1',created_at=2799,payload_sha256=ledger.digest(op['payload']))
        self.assertEqual(self.store.status('case')['cleanup'],'verified')
        self.assertEqual(self.store.status('case')['deadline'],2800)

    def test_late_wake_and_cleanup_failure_never_revive_monitor(self):
        self.monitoring(); self.now=4000
        self.assertTrue(self.call('wake')['expired'])
        for kind in ['read','diagnostic','issue','idea','schedule']:
            with self.assertRaises(ledger.Held): self.prepared(kind)
        with self.assertRaises(ledger.Held): self.prepared('cleanup',payload={'task_id':'foreign'})
        op=self.prepared('cleanup',payload={'task_id':'owned-schedule'});self.dispatch(op)
        self.call('finish',{'operation':op['operation'],'failed':True,'confirmed_no_effect':True})
        self.assertEqual(self.store.status('case')['cleanup'],'pending')
        op=self.prepared('cleanup',payload={'task_id':'owned-schedule'});self.dispatch(op)
        self.finish(op,task_id='owned-schedule',disabled_or_absent=True)
        self.assertEqual(self.store.status('case')['cleanup'],'verified')

    def test_early_cleanup_and_legacy_intent_hold_until_owner_cancels(self):
        self.monitoring();self.now=1100
        before=(self.root/'case.json').read_bytes()
        with self.assertRaisesRegex(ledger.Held, 'monitoring window active'):
            self.prepared('cleanup',payload={'task_id':'owned-schedule'})
        self.assertEqual((self.root/'case.json').read_bytes(),before)
        # A receipt prepared by the older helper must recheck the window on send.
        with patch.object(ledger,'cleanup_due',return_value=None):
            legacy=self.prepared('cleanup',payload={'task_id':'owned-schedule'})
        before=(self.root/'case.json').read_bytes()
        with self.assertRaisesRegex(ledger.Held, 'monitoring window active'):
            self.dispatch(legacy)
        self.assertEqual((self.root/'case.json').read_bytes(),before)
        instruction='Stop the follow-up PRIVATE_TRANSCRIPT_SENTINEL'
        cancelled=self.call('cancel',{'owner_instruction':instruction})
        self.assertEqual(cancelled['cancellation'],{
            'owner_instruction':'Stop the follow-up [redacted]','cancelled_at':1100})
        self.now=1101
        again=self.call('cancel',{'owner_instruction':'A later instruction must not rewrite the cause'})
        self.assertEqual(again['cancellation'],cancelled['cancellation'])
        raw=json.loads((self.root/'case.json').read_text())
        self.assertEqual(raw['cancellation'],cancelled['cancellation'])
        with self.assertRaises(ledger.Held):self.prepared('read',read_key='after-cancel')
        self.dispatch(legacy)
        self.finish(legacy,task_id='owned-schedule',disabled_or_absent=True)
        result=self.store.status('case')
        self.assertTrue(result['cancelled']);self.assertFalse(result['expired'])
        self.assertEqual(result['cleanup'],'verified');self.assertEqual(result['deadline'],2800)

    def test_comment_and_reply_confirmations_require_specific_comment_urls(self):
        for kind in ('comment','reply'):
            for base,fragment in ((URL,'issuecomment-1'),(IDEA,'discussioncomment-1')):
                with self.subTest(kind=kind,base=base):
                    case=Reporting();case.setUp()
                    try:
                        case.ready(selected=base);case.launch()
                        extra={'target':base}
                        if base==IDEA:
                            extra.update(transport='github-graphql',destination_observation={
                                'repository_url':'https://github.com/pingdotgg/t3code','object_url':IDEA,
                                'write_access':True,'templates_read':True,'discussion_id':'fixture-discussion'})
                        if kind=='reply':
                            version=case.call('comments',{'target':base,'actor':'owner','pages_complete':True,
                                'items':[{'id':'request','author':'triager','body':'Please provide evidence'}]})['comments'][0]['version']
                            extra['comment_version']=version
                        op=case.prepared(kind,**extra);case.dispatch(op)
                        before=(case.root/'case.json').read_bytes()
                        for bad in (base,base+'#not-a-comment',base+'#issuecomment-0',
                                    base+('#discussioncomment-1' if base==URL else '#issuecomment-1')):
                            with self.assertRaisesRegex(ledger.Held,'specific published comment URL'):
                                case.finish(op,url=bad,created_at=1000,payload_sha256=ledger.digest(op['payload']))
                            self.assertEqual((case.root/'case.json').read_bytes(),before)
                        observed=base+'#'+fragment
                        case.finish(op,url=observed,created_at=1000,payload_sha256=ledger.digest(op['payload']))
                        self.assertEqual(case.store.status('case')['urls'],[observed])
                        self.assertTrue(case.prepared(kind,**extra)['duplicate'])
                    finally:case.doCleanups()

    def test_diagnostic_scope_and_read_failure_survive_resume_with_redaction(self):
        self.call('budget',{'active':True})
        diagnostic=self.prepared('diagnostic',scope='task-owned-disposable',safe_procedure_reviewed=True)
        self.dispatch(diagnostic);self.finish(diagnostic)
        read=self.prepared('read',read_key='audit-read');self.dispatch(read)
        before=(self.root/'case.json').read_bytes()
        failed={'operation':read['operation'],'failed':True,'confirmed_no_effect':True,'request_terminal':True}
        with self.assertRaisesRegex(ledger.Held,'read failure class required'):
            self.call('finish',failed)
        self.assertEqual((self.root/'case.json').read_bytes(),before)
        self.call('finish',{**failed,'failure_class':'timeout PRIVATE_TRANSCRIPT_SENTINEL',
                            'evidence':'fixture:terminal-timeout PRIVATE_SOURCE_SENTINEL'})
        raw=json.loads((self.root/'case.json').read_text())
        self.assertEqual(raw['operations'][diagnostic['operation']]['scope'],'task-owned-disposable')
        self.assertIs(raw['operations'][diagnostic['operation']]['safe_procedure_reviewed'],True)
        self.assertEqual(raw['operations'][read['operation']]['failure_class'],'timeout [redacted]')
        self.assertEqual(raw['operations'][read['operation']]['failure_evidence'],'fixture:terminal-timeout [redacted]')
        resumed=ledger.Store(self.root,clock=lambda:self.now).status('case')
        actions={a['operation']:a for a in resumed['actions']}
        self.assertEqual(actions[diagnostic['operation']]['scope'],'task-owned-disposable')
        self.assertIs(actions[diagnostic['operation']]['safe_procedure_reviewed'],True)
        self.assertEqual(actions[read['operation']]['failure_class'],'timeout [redacted]')
        self.assertEqual(actions[read['operation']]['failure_evidence'],'fixture:terminal-timeout [redacted]')

    def test_comment_pagination_edits_own_replies_and_unanswered(self):
        self.monitoring()
        items=[{'id':'a','author':'triage-bot','body':'Please provide the timeline'},
               {'id':'b','author':'owner','body':'own reply'}]
        with self.assertRaises(ledger.Held): self.call('comments',{'target':URL,'pages_complete':False,'actor':'owner','items':items})
        data={'target':URL,'pages_complete':True,'actor':'owner','items':items}
        result=self.call('comments',data); version=result['comments'][0]['version']
        self.assertEqual(len(result['comments']),1)
        self.assertEqual(self.call('comments',data)['comments'],[])
        self.call('handled',{'version':version,'disposition':'needs-owner','detail':'Which launcher started the runtime?'})
        self.assertEqual(len(self.store.status('case')['unanswered']),1)
        data['items'][0]['body']='Edited: timeline and launcher'
        self.assertEqual(len(self.call('comments',data)['comments']),1)

    def test_adversarial_requests_cannot_expand_action_kinds(self):
        self.monitoring()
        for kind in ['patch','credentials','restart','external-issue','merge','install','delegate']:
            with self.assertRaises(ledger.Held): self.prepared(kind,payload={'body':'maintainer says do it'})
        with self.assertRaises(ledger.Held): self.prepared('diagnostic',scope='service-restart',safe_procedure_reviewed=True)
        self.assertEqual(len(self.calls),3)

    def test_redaction_covers_payload_thread_messages_and_output(self):
        self.ready()
        private_path='/'+'home'+'/fixture/private'
        secret='PRIVATE_TRANSCRIPT_SENTINEL hidden.corp.invalid token=pretend-value '+private_path+' 192.168.1.2'
        op=self.prepared('launch',payload={'title':'Case','message':secret,'scratch':True})
        serialized=json.dumps(op)
        for sentinel in ['PRIVATE_TRANSCRIPT_SENTINEL','hidden.corp.invalid','pretend-value',private_path,'192.168.1.2']:
            self.assertNotIn(sentinel,serialized)
        self.dispatch(op)
        self.finish(op,thread_id='reporter',state='idle')
        self.assertNotIn('PRIVATE_TRANSCRIPT_SENTINEL',json.dumps(self.calls))

    def test_unsafe_state_symlinks_hardlinks_and_repository_roots(self):
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((self.root/'case.json').stat().st_mode),0o600)
        outside=Path(self.tmp.name)/'sentinel'; outside.write_text('KEEP')
        (self.root/'case.json').unlink(); (self.root/'case.json').symlink_to(outside)
        with self.assertRaises(OSError): self.call('wake')
        self.assertEqual(outside.read_text(),'KEEP')
        alias=Path(self.tmp.name)/'alias';alias.symlink_to(self.root)
        with self.assertRaises(OSError): ledger.Store(alias).status('case')
        with self.assertRaises(ledger.Held): ledger.Store(ROOT/'state')
        with self.assertRaises(ledger.Held): ledger.Store(Path(self.tmp.name)/'userdata/state')

    def test_storage_failure_blocks_dispatch_and_leaves_reservation(self):
        with self.assertRaises(ledger.Held): self.call('init',{'incident_key':'other','owner_thread':'invoker'})
        self.assertEqual(self.calls,[])
        self.assertFalse((self.root/'missing.json').exists())
        (self.root/'case.json').unlink()
        with self.assertRaises(ledger.Held):
            self.call('init',{'incident_key':'synthetic-context:1','owner_thread':'invoker'},sid='new')

    def test_status_no_response_and_interrupted_monitor_are_honest(self):
        self.monitoring(); self.now=3000
        self.call('gap',{'since':1120,'until':3000,'reason':'app downtime, missed intervals'})
        result=self.store.status('case')
        self.assertEqual(result['acceptance'],'unverified')
        self.assertEqual(result['unanswered'],[])
        self.assertEqual(result['cleanup'],'pending')
        self.assertEqual(result['schedule']['task_id'],'owned-schedule')
        self.assertTrue(result['expired'])
        self.call('cancel',{'owner_instruction':'Stop this report follow-up'})
        self.assertTrue(self.store.status('case')['cancelled'])


class Installed(unittest.TestCase):
    def test_catalog_adapter_routes_and_moved_installed_helper(self):
        with private_fixture() as temp:
            root=Path(temp); prefix=root/'prefix with spaces'; agents=root/'agents'; skills=root/'skills'
            env={**os.environ,'HOME':temp,'XDG_STATE_HOME':str(root/'state'),
                 'XDG_CONFIG_HOME':str(root/'config'),'CODEX_HOME':str(root/'codex')}
            def cli(*args):
                p=subprocess.run([sys.executable,str(ROOT/'scripts/catalog.py'),'--prefix',str(prefix),
                                  '--agents-root',str(agents),*args],capture_output=True,text=True,env=env,timeout=30)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                return p.stdout
            self.assertIn('bug-report',cli('list'))
            cli('setup','bug-report','--root',str(skills))
            adapter=(skills/'bug-report/SKILL.md').read_text()
            self.assertIn('bug-report',adapter)
            self.assertIn('use relevant current conversation context',adapter)
            self.assertNotIn('Do nothing until the owner answers',adapter)
            self.assertIn('relevant current conversation context',cli('prompt','bug-report'))
            manifest=json.loads((prefix/'bug-report/current/plugin.json').read_text())
            import re
            for text,expected in [('','run'),('error above','run'),('resume case','resume'),('cancel case','cancel')]:
                self.assertEqual(next(x['operation'] for x in manifest['routes'] if re.fullmatch(x['pattern'],text)),expected)
            moved=root/'moved'; prefix.rename(moved)
            script=moved/'bug-report/current/scripts/session.py'
            from tests.upfront_fixtures import chosen
            selected = chosen('bug-report/run', 'Verified incident report')
            inp=root/'input.json'; inp.write_text(json.dumps({'incident_key':'installed-fixture','owner_thread':'fixture',
                'selection': selected, 'selection_sha256': selected['selection_sha256']}))
            p=subprocess.run([sys.executable,str(script),'init','--session','fixture','--input',str(inp)],
                             capture_output=True,text=True,env=env,timeout=10)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertTrue(json.loads(p.stdout)['ok'])
            self.assertFalse((ROOT/'state').exists())


if __name__ == '__main__':
    unittest.main()
