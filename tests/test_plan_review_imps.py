"""Source/installed IMPS acceptance, not prompt-presence assertions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from core.jobs.store import digest
from shared import planning_review as planning
from tests.upfront_fixtures import approved_selection
from tests.imps_plan_review_fixtures import ImpsPlanFixture
from tests.test_rebuild_installed import Sandbox


class ImpsReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.box=Sandbox(Path(cls.temp.name))
        cls.package,cls.manifest=cls.box.install('imps')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def fixture(self, **kw):return ImpsPlanFixture(self.box,self.package,self.manifest,**kw)

    def test_integrated_zero_findings_source_installed_and_direct_review(self):
        for installed in (False,True):
            for op in ('audit','investigation','blast-radius'):
                for direct in (False,True):
                    with self.subTest(installed=installed,op=op,direct=direct):
                        f=self.fixture(op=op,installed=installed,direct=direct);f.init();f.evidence()
                        f.gate('validate',ok=False);f.stage_validate(ok=False)
                        f.finalize(ok=False);f.approve();f.finalize()
                        result=f.gate('validate')['data'];self.assertTrue(result['ready'])
                        self.assertTrue(f.stage_validate()['accepted'])
                        checked=f.ape('validate',{'descriptor':f.descriptor})
                        self.assertEqual(checked['modes'],['self-review' if direct else 'cross-lineage'])
                        self.assertFalse(checked['execution_authorized']);self.assertEqual(checked['rounds_used'],1)
                        self.assertEqual(json.loads(f.metadata.read_text())['subject_file'],checked['subject_file'])

    def test_initial_write_multistage_synthesis_trigger_before_init(self):
        for op in ('run','issues','checklist','discussion'):
            for reason in ('write','stages','synthesis'):
                with self.subTest(op=op,reason=reason):
                    f=self.fixture(op=op,**{'write':reason=='write','stages':2 if reason=='stages' else 1,
                                            'synthesis':reason=='synthesis'})
                    f.init(ok=False);self.assertFalse(f.gates.exists())
                    f.approve();f.init();f.evidence();result=f.gate('validate')['data']
                    self.assertTrue(result['source_ready']);self.assertFalse(result['ready'])
                    self.assertFalse(result['endpoint_complete'])
                    self.assertTrue(f.stage_validate()['accepted'])  # Source-stage gate; selected endpoint remains incomplete.

    def test_invalid_authored_job_role_refuses_before_review_preparation(self):
        for installed in (False, True):
            with self.subTest(installed=installed):
                f=self.fixture(op='run',installed=installed,write=True)
                f.descriptor['job_contract']={'stages':[{'id':'stage-0'}], 'tasks':[
                    {'task_id':'execute','stage_id':'stage-0','worker_id':'imps/stage-executor',
                     'role':'implementation'}]}
                payload={'descriptor':f.descriptor,'inputs':f.inputs,'metadata_file':str(f.metadata)}
                refusal=f.ape('prepare',payload,ok=False)
                self.assertIn('job_contract.tasks[0].role',refusal)
                self.assertFalse(f.metadata.exists())
                self.assertFalse((f.box.jobs/f.review_id).exists())
                for role in ('worker','review'):
                    f.descriptor['job_contract']['tasks'][0]['role']=role
                    f.descriptor.pop('document',None)
                    f.metadata=f.base/('role-'+role+'.json')
                    f.prepare()
                    self.assertTrue(f.metadata.exists())

    def test_single_read_only_initial_plan_and_deterministic_helpers_do_not_review(self):
        f=self.fixture(op='checklist');f.init();f.evidence()
        result=f.gate('validate')['data']
        self.assertTrue(result['source_ready']);self.assertFalse(result['endpoint_complete']);self.assertFalse(f.metadata.exists())
        for op in ('doctor','status','cancel','recipe-scaffold','recipe-check'):
            self.assertEqual(f.ape('admit',{'operation':op}),{'allowed':True,'chooser':False,'dispatch':False})
        f.gate('status');self.assertFalse(f.metadata.exists())

    def test_whole_job_initial_plan_reconstructs_its_reviewed_contract(self):
        from shared.imps_planning import job_contract
        for installed in (False, True):
            with self.subTest(installed=installed):
                f=self.fixture(op='run',write=True,installed=installed)
                f.descriptor['job_contract']=job_contract({
                    'workflow':'imps/run','requirements':f.requirements,
                    'authorization':{'actions':['edit']},'constraints':['Local only.'],
                    'repo':{'worktree':str(f.project),'base_sha':'fixture-base'},
                    'stages':[{'id':'execution','depends_on':[],
                        'requirements':['REQ-ONE'],'execution_mode':'direct'}],
                    'tasks':[],
                })
                f.approve()
                metadata_before=f.metadata.read_bytes()
                receipt_before=Path(f.receipt['path']).read_bytes()
                f.init()
                self.assertEqual(f.metadata.read_bytes(),metadata_before)
                self.assertEqual(Path(f.receipt['path']).read_bytes(),receipt_before)
                self.assertIn('job_contract',f.snapshot['imps_descriptor'])

                changed_plan=deepcopy(f.plan)
                changed_plan['brief']['text']='Different implementation'
                rejected=f.gate('init',{**changed_plan,'imps':f.context},ok=False)
                self.assertIn('initial plan body differs',rejected['error']['message'])

                changed_context=deepcopy(f.context)
                changed_context['stages'][0]['actions']=['read']
                rejected=f.init(ok=False,context=changed_context)
                self.assertIn('initial plan body differs',rejected['error']['message'])

                changed_contract=deepcopy(f.descriptor)
                changed_contract.pop('document')
                changed_contract['job_contract']['constraints'].append('Changed contract')
                rejected=f.ape('validate',{'descriptor':changed_contract},ok=False)
                self.assertIn('initial plan body differs',rejected)

                for path in (f.metadata,Path(f.receipt['path'])):
                    before=path.read_bytes()
                    path.write_bytes(before+b'\n')
                    try:
                        f.init(ok=False)
                    finally:
                        path.write_bytes(before)

    def test_unanswered_choices_and_missing_context_prevent_initialization(self):
        f=self.fixture(op='run',write=True)
        for key in ('selection','selection_sha256'):
            d=deepcopy(f.admission_input);d.pop(key)
            self.assertIn('imps_planning_error',f.ape('admit',d,ok=False))
        self.assertIn('context required',f.gate('init',f.plan,ok=False)['error']['message'])
        self.assertFalse(f.gates.exists())
        d=deepcopy(f.admission_input);d['selection']['source']['answer']='tampered'
        self.assertIn('imps_planning_error',f.ape('admit',d,ok=False))

    def test_recipe_review_precedes_execution_but_scaffold_check_remain_direct(self):
        for installed in (False,True):
            f=self.fixture(op='verification-init',installed=installed)
            f.gate('recipe-check',extra=('--recipe',f.recipe_file))
            f.ape('recipe-ready',{'descriptor':f.descriptor,'recipe_file':f.recipe_file},ok=False)
            f.init(ok=False);f.approve()
            result=f.ape('recipe-ready',{'descriptor':f.descriptor,'recipe_file':f.recipe_file})
            self.assertEqual(result['admitted_steps'],['launch','drive','observe','cleanup'])
            self.assertFalse(result['execution_authorized']);f.init()
            wrong=f.gate('recipe-stamp',ok=False,extra=('--recipe',str(f.base/'other-recipe.json'),
                '--feature','F-CREATE','--requirement','REQ-ONE'))
            self.assertIn('stamp target',wrong['error']['message'])
            path=Path(f.recipe_file);before=path.read_bytes();recipe=json.loads(before)
            recipe['cleanup'][0]['argv']=['false'];path.write_text(json.dumps(recipe))
            self.assertIn('differ from reviewed facts',f.ape('recipe-ready',{
                'descriptor':f.descriptor,'recipe_file':f.recipe_file},ok=False))
            path.write_bytes(before)
            feature=path.parent/recipe['features'][0]['doc'];before_doc=feature.read_bytes()
            feature.write_text('Run different commands.\n')
            self.assertIn('rendered recipe instructions differ',f.ape('recipe-ready',{
                'descriptor':f.descriptor,'recipe_file':f.recipe_file},ok=False))
            feature.write_bytes(before_doc)
            f.facts_file.write_text(f.facts_file.read_text()+'\n')
            f.ape('recipe-ready',{'descriptor':f.descriptor,'recipe_file':f.recipe_file},ok=False)

    def test_missing_tampered_stale_and_borrowed_receipts_fail_actual_gates(self):
        f=self.fixture();f.init();f.evidence();f.approve();f.finalize()
        original=deepcopy(f.descriptor)
        for ref in (None,{}, {'path':str(f.base/'absent'),'sha256':'0'*64,'bytes':1}):
            f.descriptor['planning_review']=ref;f.finalize(ok=False)
        f.descriptor=original
        for path in (f.metadata,Path(f.receipt['path']),f.request,f.local,f.answer):
            before=path.read_bytes();path.write_bytes(before+b'\n')
            f.gate('validate',ok=False);f.stage_validate(ok=False)
            path.write_bytes(before)
        result=f.gate('validate')['data']
        self.assertTrue(result.get('source_ready',result['ready']))
        other=self.fixture();other.init();other.evidence()
        other.descriptor['planning_review']=f.descriptor['planning_review'];other.finalize(ok=False)
        f.descriptor['requirements']['REQ-ONE']='weakened';f.finalize(ok=False)

    def test_adverse_and_partial_are_final_in_that_round_not_unavailability(self):
        for partial in (False,True):
            f=self.fixture();f.init();f.evidence();f.begin_review()
            result=f.review_pass(adverse=not partial,malformed=partial)
            self.assertEqual(result['outcome'],'incomplete' if partial else 'adverse')
            out=f.finish(attach=False);self.assertFalse(out['accepted'])
            f.ape('attach',{'descriptor':f.descriptor,'metadata_file':str(f.metadata),'receipt':f.receipt['path']},ok=False)
            f.gate('validate',ok=False);f.finalize(ok=False)

    def test_alias_once_pinned_resume_and_persistent_subject(self):
        f=self.fixture();f.init();f.approve();f.finalize()
        for event in ('wake','repair','compaction'):
            self.assertEqual(f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':event}),f.admission)
        for retain in (None,False):
            self.assertEqual(f.ape('continue',{'admission':f.admission,'invocation_id':f.id,
                'event':'resume','retain':retain}),f.admission)
        self.assertEqual(f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'event':'resume','retain':True}),f.admission)
        forwarded=f.ape('continue',{'admission':f.admission,'invocation_id':f.id,'forward':True})
        self.assertIn('already forwarded',f.ape('continue',{'admission':forwarded,'invocation_id':f.id,'forward':True},ok=False))
        f.ape('continue',{'admission':f.admission,'invocation_id':'new-command'},ok=False)
        old=json.loads(f.metadata.read_text());self.assertEqual(f.prepare()['snapshot'],old['snapshot'])
        self.assertEqual(json.loads(Path(old['subject_file']).read_text())['rounds_used'],1)
        f.review('begin',ok=False)
        f.local.with_name('unrelated.txt').write_text('Unrelated.\n')
        self.box.run(['git','-C',f.project,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                      'commit','-qm','unrelated','--allow-empty'])
        self.assertTrue(f.ape('validate',{'descriptor':f.descriptor})['head_observation']['changed'])

    def test_planning_does_not_satisfy_code_or_persona_gates(self):
        f=self.fixture(op='run',write=True,code_review=True);f.approve();f.init();f.evidence()
        self.assertFalse(f.gate('validate')['data']['ready']);f.stage_validate(ok=False)
        binding=f.gate('snapshot')['data'];review_log=f.gates/'runs'/f.run_id/'scratch/code-review.txt';review_log.write_text('Code review fixture.\n')
        child={'task_id':'code-review','client_request_id':'code-review-request','parent_thread_id':'fixture-parent',
               'status':'completed','has_pending_child_runs':False}
        f.gate('child',child)
        f.gate('review',{'binding':binding,'task_id':'code-review','perspective_id':'default','verdict':'adverse',
            'findings':[{'severity':'major','summary':'Concrete code defect'}],'artifacts':[str(review_log)]})
        f.gate('review',{'binding':binding,'task_id':'code-review','perspective_id':'default','verdict':'approve',
            'findings':[],'artifacts':[str(review_log)]},ok=False)
        self.assertFalse(f.gate('validate')['data']['ready'])

    def test_read_only_authority_and_reserved_run_notes(self):
        f=self.fixture(write=True);f.init(ok=False)
        f.plan['authorization']['local']=['read'];f.init()
        f.gate('note',{'text':'imps-planning-v1:{}'},ok=False)
        f.gate('note',{'text':'ordinary retained note'})

    def test_stale_declared_output_pin_and_unknown_attachment_authorship(self):
        f=self.fixture();f.answer.write_text('Changed before source capture.\n')
        f.ape('prepare',{'descriptor':f.descriptor,'inputs':f.inputs,'metadata_file':str(f.metadata)},ok=False)
        f.descriptor['document']=planning.file_descriptor(f.answer)
        attachment=f.base/'external-plan.md';attachment.write_text('An externally authored alternative.\n')
        f.inputs['attachments']=[str(attachment)];f.approve()
        self.assertIn({'unknown':True,'lineage':'unknown'},f.snapshot['authors'])
        self.assertEqual(f.ape('validate',{'descriptor':f.descriptor})['modes'],['non-independent'])

    def test_initial_review_is_preexecution_evidence_and_plan_changes_reopen_it(self):
        f=self.fixture(op='run',write=True);f.approve()
        f.local.write_text('VALUE = 2\n')
        f.init(ok=False)  # intended edits cannot precede the initial pass
        f.local.write_text('VALUE = 1\n');f.init()
        f.local.write_text('VALUE = 2\n');f.evidence()
        result=f.gate('validate')['data']
        self.assertTrue(result['source_ready']);self.assertFalse(result['endpoint_complete'])
        changed=deepcopy(f.context);f.plan['brief']['requirements'][0]['text']='Different acceptance'
        f.init(ok=False,context=changed)

    def test_whole_job_creation_and_dispatch_require_actual_initial_plan(self):
        from tests.imps_plan_review_fixtures import select_legacy_imps_job
        job={'schema_version':1,'job_id':'imps-admission-public','installation_id':self.manifest['installation_id'],
            'workflow':'imps/run','owner':'fixture-owner','objective':'Two bounded stages',
            'requirements':{'REQ-ONE':'Assess the requested outcome'},'authorization':{'actions':['read']},
            'constraints':['Offline only.'],'dependencies':[{'key':'imps','plugin':'imps'}],
            'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'decisions':[],
            'history':[],'metrics':{},'result_contract':{'schema_version':1},
            'stages':[{'id':sid,'depends_on':[] if sid=='first' else ['first'],'requirements':['REQ-ONE'],
                'status':'pending','validator_dependency':'imps'} for sid in ('first','second')],
            'tasks':[{'task_id':'work','stage_id':'first','logical_slot_id':'primary','request_id':'imps-public-work',
                'worker_id':'imps/stage-executor','dependency_key':'imps','status':'pending',
                'write_scope':{'mode':'worker-evidence','path':'artifacts/tasks/work'}}]}
        kwargs={'check':False,'extra':('--prefix',self.box.prefix,'--agents-root',self.box.agents)}
        refused=self.box.job(self.package,'create',job['job_id'],job,**kwargs)
        self.assertNotEqual(refused.returncode,0)

        job,f=select_legacy_imps_job(job,self.box.private,self.package,self.manifest,self.box.env,return_fixture=True)
        missing=deepcopy(job);missing['imps_initial_plan'].pop('planning_review')
        self.assertNotEqual(self.box.job(self.package,'create',job['job_id'],missing,**kwargs).returncode,0)
        self.box.job(self.package,'create',job['job_id'],job,
                     extra=('--prefix',self.box.prefix,'--agents-root',self.box.agents))
        caller=self.box.caller(self.manifest,'imps/run')
        # A changed initial stage contract needs a new counted planning pass and
        # the ordinary owner-bound revision. Its reference survives core storage.
        from shared.imps_planning import job_contract
        new=deepcopy(self.box.state_of(job['job_id']))
        new['stages'][1]['criteria']=[{'id':'C-RECOVERY','kind':'inspection'}]
        revision={'id':'stage-contract-r2','owner_decision_id':'owner-r2'}
        refused=self.box.job(self.package,'plan-revision',job['job_id'],{'caller':caller,
            'revision':revision,'new_plan':new},check=False)
        self.assertNotEqual(refused.returncode,0)
        f.descriptor.pop('document');f.descriptor.pop('planning_review')
        f.descriptor['job_contract']=job_contract(new)
        f.metadata=f.base/'review-metadata-r2.json';f.prepare()
        f.review('begin',{'snapshot':f.snapshot});f.round_request_suffix='-repair'
        f.review_pass();f.finish()
        new['imps_initial_plan']=f.descriptor
        source=f.base/'owner-r2.txt';source.write_text('Approve the changed recovery criterion for this fixture.')
        self.box.job(self.package,'decision',job['job_id'],{'caller':caller,'decision':{
            'id':'owner-r2','scope':'plan:stage-contract-r2','quote':source.read_text(),
            'source':str(source),'source_sha256':digest(source.read_bytes())}})
        self.box.job(self.package,'plan-revision',job['job_id'],{'caller':caller,'revision':revision,'new_plan':new})
        stored=self.box.state_of(job['job_id'])
        self.assertEqual(stored['stages'][0]['resources']['imps_initial_review']['descriptor'],f.descriptor)
        self.assertEqual(json.loads(Path(f.receipt['path']).read_text())['rounds_used'],2)
        prepared=self.box.job(self.package,'prepare',job['job_id'],{'caller':caller,'task_id':'work'})
        brief=json.loads(Path(prepared['path']).read_text())
        self.assertEqual(brief['target']['options'],job['model_selection']['work']['workhorse']['options'])
        path=self.box.jobs/job['job_id']/'job.json';state=json.loads(path.read_text())
        state['requirements']['REQ-ONE']='Changed stage contract';path.write_text(json.dumps(state))
        refused=self.box.job(self.package,'prepare',job['job_id'],{'caller':caller,'task_id':'work'},check=False)
        self.assertNotEqual(refused.returncode,0)
    def test_relocated_helpers_consume_real_receipts_and_bound_templates(self):
        import shutil
        for op in ('audit','run','verification-init'):
            f=self.fixture(op=op,write=op=='run')
            moved=f.base/'relocated';shutil.copytree(self.package,moved)
            f.plugin=moved;f.runtime=moved
            f.approve();f.init();f.evidence()
            if op=='audit':f.finalize()
            if op=='run':
                self.assertTrue(f.gate('validate')['data']['source_ready'])
                self.assertTrue(f.stage_validate()['accepted'])
                self.assertFalse(f.gate('validate')['data']['endpoint_complete'])
            else:
                self.assertTrue(f.stage_validate()['accepted'])

    def test_multistage_audit_reviews_only_integrated_conclusions_and_binds_producers(self):
        from shared import model_selection as models
        f=self.fixture()
        d=deepcopy(f.selection_data);d['work']['judgement'].update(execution='current-context',accept_actual_settings=True)
        f.selection=approved_selection(d)
        f.admission_input.update(selection=f.selection,selection_sha256=f.selection['selection_sha256'])
        f.admission=f.ape('admit',f.admission_input);f.descriptor['admission']=f.admission
        jid=f.id+'-audit';job_file=self.box.jobs/jid/'job.json'
        raw=f.base/'observations.md';raw.write_text('Source observations, before integrated conclusions.\n')
        source_root=f.base/'source-gates';f.gates=source_root
        f.init(context={'admission':f.admission,'output_path':str(raw),'job_file':str(job_file),'stage_id':'source'})
        source_id=f.run_id;f.evidence()
        f.gates=f.base/'final-gates';f.run_id=None
        f.context={'admission':f.admission,'output_path':str(f.answer),'job_file':str(job_file),'stage_id':'conclusion'}
        f.init();f.evidence();f.descriptor['job_file']=str(job_file)
        stages=[]
        for sid,root,rid,path,deps in [('source',source_root,source_id,raw,[]),
                ('conclusion',f.gates,f.run_id,f.answer,['source'])]:
            stages.append({'id':sid,'depends_on':deps,'requirements':['REQ-ONE'],'status':'pending',
                'execution_mode':'direct','validator_dependency':'imps','outputs':[str(path)],
                'validator_contract':{'state_root':str(root),'run_id':rid},
                'selection_binding':{'role':'judgement','selection_sha256':f.selection['selection_sha256']}})
        job={'schema_version':1,'job_id':jid,'installation_id':self.manifest['installation_id'],'workflow':'imps/audit',
            'owner':'fixture-owner','requirements':f.requirements,'authorization':{'actions':['read']},
            'constraints':['No edits.'],'dependencies':[{'key':'imps','plugin':'imps'}],'pins':{},
            'policy':{'max_repair_cycles':3},'stages':stages,'tasks':[],'decisions':[],'history':[],
            'metrics':{},'result_contract':{'schema_version':1},'imps_admission':f.admission,
            'model_selection':f.selection,'model_selection_sha256':f.selection['selection_sha256'],
            'invocation_id':f.id,'scope_id':f.scope}
        self.box.job(self.package,'create',jid,job,extra=('--prefix',self.box.prefix,'--agents-root',self.box.agents))
        caps=deepcopy(f.selection['capabilities']);caps['parentThreadId']='fixture-coordinator'
        caps['inheritedOptions']=f.selection['coordinator'].get('observed_options', {})
        caller=self.box.caller(self.manifest,'imps/audit')
        for sid in ('source','conclusion'):
            self.box.job(self.package,'direct-execution',jid,{'caller':caller,'stage_id':sid},
                extra=('--capabilities',self.box.payload(caps)))
        p=self.box.run([__import__('sys').executable,self.package/'cli.py','validate','--state-root',source_root,
                        '--run-id',source_id])
        self.assertTrue(json.loads(p.stdout)['data']['ready']);self.assertFalse(f.metadata.exists())
        f.gate('validate',ok=False);f.approve();f.finalize();self.assertTrue(f.stage_validate()['accepted'])
        self.assertEqual(len(f.snapshot['imps_producer_bindings']),2)
        state=json.loads(job_file.read_text());state['stages'][0]['direct_execution_history'][0]['model_selection']['selection_sha256']='0'*64
        job_file.write_text(json.dumps(state));f.gate('validate',ok=False)



if __name__=='__main__':unittest.main()
