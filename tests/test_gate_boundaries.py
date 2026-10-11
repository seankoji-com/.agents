"""Preserved evidence boundaries from mixed historical regression suites."""
import json
import os
from pathlib import Path
from support import CoreTestCase, cli, git
from core import fsutil


class GateBoundaries(CoreTestCase):
    def ready_run(self):
        run=self.init(self.plan(self.make_repo(),policy={'checks': [], 'review': {'required': False}}))
        log=run.scratch('proof','observed')
        run.evidence('REQ-MULTILINE',log)
        self.assertTrue(run.validate()['ready'])
        return run,log

    def test_constraint_change_invalidates_semantic_binding(self):
        repo=self.make_repo()
        goal=repo/'GOAL.md'
        goal.write_text('## Definition of done\n- [ ] [REQ-ONE] works [verify:inspection]\n\n## Global constraints\n- Keep usage.\n')
        git(repo,'add','GOAL.md');git(repo,'commit','-qm','goal')
        run=self.init(self.plan(repo,brief={'text':'inspect','requirements_source':str(goal)},
                                policy={'checks': [], 'review': {'required': False}}))
        run.evidence('REQ-ONE',run.scratch('proof','observed'),kind='inspection')
        self.assertTrue(run.validate()['ready'])
        goal.write_text(goal.read_text().replace('Keep usage.','Keep output.'))
        self.assertEqual(run.validate()['status'],'stale')
        self.assertIn('requirements or constraints changed',str(run.validate()['stale']))

    def test_new_failed_evidence_is_not_hidden_by_older_waiver(self):
        run,log=self.ready_run()
        run.submit('waive',{'target':'requirement:REQ-MULTILINE','reason':'known','decided_by':'owner','operator_quote':'skip it'})
        run.evidence('REQ-MULTILINE',log,status='failed')
        self.assertEqual(run.validate()['requirements'][0]['status'],'failed')
        self.assertFalse(run.validate()['ready'])

    def test_check_labels_and_optional_stale_check(self):
        repo=self.make_repo()
        checks=[{'name':'optional','argv':['true'],'required':False,'cwd':str(repo)}]
        run=self.init(self.plan(repo,policy={'checks':checks,'review':{'required':False}}))
        for code,reason,label in ((1,None,'failed'),(127,None,'unavailable'),(None,'missing tool','unavailable'),(0,None,'passed')):
            payload={'name':'optional','argv':['true'],'cwd':str(repo),'exit_code':code,
                     'log':str(run.scratch('check','output')),'binding':run.binding()}
            if reason:payload['unavailable_reason']=reason
            run.submit('check',payload)
            self.assertEqual(run.validate()['checks'][0]['status'],label)
        (repo/'new.txt').write_text('changed')
        run.evidence('REQ-MULTILINE',run.scratch('fresh','observed'))
        self.assertTrue(run.validate()['ready'],'a stale optional check is not required')

    def test_report_recomputes_current_outcome_after_an_edit(self):
        run,log=self.ready_run()
        self.assertEqual(cli('report',*run.args())[1]['data']['report']['readiness']['outcome'],'completed')
        Path(run.state['repo']['worktree'],'wordstat.py').write_text('changed')
        built=cli('report',*run.args())[1]['data']['report']
        self.assertNotEqual(built['readiness']['outcome'],'completed')
        self.assertEqual(built['readiness']['status'],'stale')

    def test_artifact_destination_symlink_never_writes_outside(self):
        run,log=self.ready_run()
        outside=self.write('outside','not yours')
        path=run.run_dir/'artifacts'/'evidence'/f'{fsutil.sha256_file(log)[:12]}-{log.name}'
        path.unlink();path.symlink_to(outside)
        self.assertEqual(run.submit_raw('evidence',{'requirement_id':'REQ-MULTILINE','kind':'command','status':'passed',
                       'explanation':'observed','artifacts':[str(log)],'binding':run.binding()})[0],2)
        self.assertEqual(outside.read_text(),'not yours')

    def test_recipe_scaffold_refuses_symlinked_destination(self):
        from test_verification_init import facts
        repo=self.make_repo('verify-product')
        outside=self.tmp/'outside-agents';outside.mkdir()
        (repo/'.agents').symlink_to(outside)
        code,env,_=cli('recipe-scaffold','--repo',repo,'--json',json.dumps(facts()))
        self.assertEqual((code,env['error']['code']),(2,'path_escape'))
        self.assertEqual(list(outside.iterdir()),[])

    def test_review_binding_includes_issue_time_policy(self):
        run,log=self.ready_run()
        binding=run.binding()
        run.submit('policy',{'policy':{'review':{'required':True}}})
        run.child(task_id='review-1')
        code,env,_=run.submit_raw('review',{'binding':binding,'task_id':'review-1','perspective_id':'default',
                                  'verdict':'approve','findings':[],'artifacts':[str(log)]})
        self.assertEqual((code,env['error']['code']),(4,'stale_evidence'))

    def test_recipe_stamp_refuses_tree_changed_after_completed_validation(self):
        from test_verification_init import facts
        repo=self.make_repo('verify-product')
        code,env,_=cli('recipe-scaffold','--repo',repo,'--json',json.dumps(facts()))
        self.assertEqual(code,0,env)
        recipe_path=Path(env['data']['recipe'])
        run=self.init(self.plan(repo,brief={'text':'prove feature','constraints':[],
                               'requirements':[{'id':'REQ-CREATE','kind':'runtime','text':'F-CREATE works'}]},
                               policy={'checks':[],'review':{'required':False}}))
        run.evidence('REQ-CREATE',run.scratch('trace','observed product behaviour'),kind='runtime')
        self.assertEqual(run.validate()['outcome'],'completed')
        (repo/'changed.txt').write_text('edit after verification')
        code,env,_=cli('recipe-stamp',*run.args('--recipe',recipe_path,'--feature','F-CREATE','--requirement','REQ-CREATE'))
        self.assertEqual((code,env['error']['code']),(4,'stale_evidence'))
        self.assertEqual(json.loads(recipe_path.read_text())['status'],'draft')
