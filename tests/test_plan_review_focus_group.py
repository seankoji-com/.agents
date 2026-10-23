"""Focus-group public chooser, real planning receipt, and unchanged stronger domain gates."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shared import adopter_planning as adopter, model_selection as models
from tests.upfront_fixtures import approved_selection
from tests import focus_group_fixtures as fixtures
from tests import test_focus_group_report as fg


def setUpModule():
    fg.setUpModule()


def tearDownModule():
    fg.tearDownModule()


class FocusPlanningContract:
    def policy(self, command, data, ok=True):
        path=self.h.write('policy-'+command+'.json',data)
        p=subprocess.run([sys.executable,str(self.h.helper.with_name('plan_review.py')),command,'--input',str(path)],
            cwd=self.h.base,env={**os.environ,**self.h.policy_env,'PYTHONDONTWRITEBYTECODE':'1'},
            capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,0 if ok else 2,p.stdout+p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def raw_plan(self, draft=None, admission=None):
        draft=draft or self.h.draft()
        admission=admission or fixtures.policy_selection(self.h,draft)
        self.h.plan_admission=admission
        self.h.view=self.h.ok('plan','--state-root',self.h.root,'--study',draft['study_id'],
            '--input',self.h.write('raw-draft.json',draft),'--capabilities',self.h.write('raw-host.json',admission['selection']['capabilities']),
            '--admission',self.h.write('raw-admission.json',admission))
        return draft,self.h.view

    def desc_path(self):
        return self.h.root/self.h.view['study_id']/'focus-group'/'planning'/self.h.view['revision']/'descriptor.json'

    def public_run_choice(self, *, operation='run', retain=None, invocation=None):
        d=deepcopy(self.h.plan_admission);s=deepcopy(d['selection'])
        s['operation']='focus-group/'+operation;s['invocation_id']=invocation or s['invocation_id']+'-'+operation
        s=approved_selection(s)
        payload={'operation':operation,'request_reference':d['request_reference'],'output_name':d['output_name'],
            'invocation_id':s['invocation_id'],'selection':s,'selection_sha256':s['selection_sha256']}
        if operation=='resume':payload.update(event='resume',retain=retain)
        record=self.policy('admit',payload)
        self.policy('run',{'state_root':str(self.h.root),'study':self.h.view['study_id'],
                           'admission':record,'retain':retain})
        return record

    def test_selected_provider_runtime_mode_survives_the_study_target_contract(self):
        draft=deepcopy(self.h.draft());record=fixtures.policy_selection(self.h,draft)
        selected=deepcopy(record['selection']);pid=draft['participant_models'][0]['providerInstanceId']
        provider=next(p for p in selected['capabilities']['providers'] if p['providerInstanceId']==pid)
        provider.update(driverKind='opencode',runtimeModes=['full-access'])
        selected['capabilities']['runtimeMode']='full-access'
        selected['work']['participant-01']['runtimeMode']='full-access'
        draft['participant_models'][0]['runtimeMode']='full-access'
        selected=approved_selection(selected)
        admitted=adopter.admit('focus-group',{'operation':'plan',
            **{k:record[k] for k in ('request_reference','output_name','invocation_id')},
            'selection':selected,'selection_sha256':selected['selection_sha256']})
        _,view=self.raw_plan(draft,admitted)
        self.assertEqual(view['cells'][0]['runtimeMode'],'full-access')
        dispatched=models.dispatch(selected,role='participant-01')
        self.assertEqual(dispatched['target']['runtimeMode'],'full-access')
        bad=deepcopy(selected);bad['work']['participant-01'].pop('runtimeMode')
        with self.assertRaisesRegex(ValueError,'explicit full-access'):approved_selection(bad)

    def test_explicit_runtime_mode_binds_cell_job_brief_recovery_report_and_revision(self):
        draft=deepcopy(self.h.draft());draft['personas']=draft['personas'][:1]
        draft['participant_models'][0]['runtimeMode']='auto'
        _,view=self.raw_plan(draft)
        # Compare real source/relocated helpers in their own process, without loading source for the latter.
        def project():
            script="""import json,sys
sys.path.insert(0,sys.argv[1])
import report as r
s=r.Study(sys.argv[2],sys.argv[3]);rev=s.require()['revision'];p=s.plan(rev)['plan']
t=p['participant_models'][0];plain=dict(t);plain.pop('runtimeMode',None)
other=dict(t,runtimeMode='approval-required');old=[plain['providerInstanceId'],plain['model'],plain['options']]
c=r.fg.cells(p)[0]
single=dict(p,participant_models=[t,other])
try:r.fg.normalise(single);diversity=None
except r.StudyError as e:diversity=e.code
print(json.dumps({'key':r.fg.target_key(t),'plain_key':r.fg.target_key(plain),'old_key':r.fg.sha(old)[:10],
 'other_key':r.fg.target_key(other),'diversity_refusal':diversity,'binding':r.fg.bindings(p,c,'first-impression'),
 'other_binding':r.fg.bindings(p,dict(c,target=other),'first-impression'),
 'evidence':r.evidence_view(s,p,rev,r.lifecycle.load_job(s)),
 'identity':r.fg.identity_verdict(t,{'providerInstanceId':t['providerInstanceId'],'model':t['model'],'source':'fixture'})}))
"""
            p=subprocess.run([sys.executable,'-c',script,str(self.h.helper.parent),str(self.h.root),view['study_id']],
                cwd=self.h.base,env={**os.environ,**self.h.policy_env,'PYTHONDONTWRITEBYTECODE':'1'},
                capture_output=True,text=True,timeout=60)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            return json.loads(p.stdout)
        before=project()
        self.assertEqual(before['plain_key'],before['old_key'],'absent mode must retain historic cell IDs')
        self.assertEqual(len({before['key'],before['plain_key'],before['other_key']}),3)
        self.assertNotEqual(before['binding'],before['other_binding'])
        self.assertEqual(before['diversity_refusal'],'not_multi_model')
        self.assertEqual(before['evidence']['cells'][0]['requested']['runtimeMode'],'auto')
        self.assertEqual(before['identity']['requested']['runtimeMode'],'auto')
        self.assertNotIn('runtimeMode',before['identity']['observed'],'request must never fill an unreported observation')
        fixtures.policy_review(self.h,view);self.public_run_choice();self.h.approve(view);self.h.create_job()
        original=self.h.job_state();old_choice=original['model_selection_sha256']
        self.assertEqual(original['tasks'][0]['target']['runtimeMode'],'auto')
        pilots=self.h.lc_ok(*self.h.study('pilots'))
        self.assertEqual(pilots['pilots'][0]['model']['runtimeMode'],'auto')
        slots=self.h.resume()['slots']
        self.assertEqual(next(s for s in slots if s['slot']==self.h.cell(0)+':first-impression')['state'],'dispatchable')
        dropped=deepcopy(draft['participant_models'][0]);dropped.pop('runtimeMode')
        code,out=self.h.admit_slot(0,'first-impression','fi-01-r0',target_override=dropped)
        self.assertEqual((code,out['error']['code']),(1,'outside_matrix'))
        self.assertEqual(self.h.admit_slot(0,'first-impression','fi-01-r0')[0],0)
        brief=self.h.prepare('fi-01')
        self.assertEqual(brief['model_selection']['dispatch']['target']['runtimeMode'],'auto')
        self.assertEqual(project()['evidence']['cells'][0]['requested']['runtimeMode'],'auto')
        # Finish and ingest the actual owned execution before changing choices.
        completed=self.h.first(0,admit=False,payload=self.h.fi_payload(0,'Clear enough to start.'))
        self.assertEqual(completed['code'],0,completed['out'])
        self.assertTrue(self.h.reconcile()['quiescent'])
        self.assertNotIn('runtimeMode',self.h.job_state()['tasks'][0]['handles'][0]['observed_identity'])
        changed=deepcopy(draft);changed['participant_models'][0]['runtimeMode']='approval-required'
        old_revision=view['revision'];old_cell=view['cells'][0]['cell_id']
        _,view=self.raw_plan(changed)
        self.assertNotEqual(view['revision'],old_revision)
        self.assertNotEqual(view['cells'][0]['cell_id'],old_cell)
        self.h.refused('planning_review_required','approve','--state-root',self.h.root,'--study',view['study_id'],
                      '--input',self.h.approval(view))
        fixtures.policy_review(self.h,view)
        self.public_run_choice(invocation='runtime-mode-revision-run');self.h.approve(view)
        carried=self.h.ok('carry','--state-root',self.h.root,'--study',view['study_id'],'--write')
        self.assertTrue(any(e['cell_id']==old_cell and e['status']=='stale' for e in carried['entries']))
        self.h.revise_job()
        revised=self.h.job_state()
        self.assertEqual(revised['authorization']['study_revision'],view['revision'])
        self.assertIn(old_choice,revised['model_selection_history'])
        current=[t for t in revised['tasks'] if t.get('focus_group',{}).get('cell_id')==view['cells'][0]['cell_id']
                 or t['target']==changed['participant_models'][0]]
        self.assertTrue(current)
        self.assertTrue(all(t['target'].get('runtimeMode')=='approval-required' for t in current))
        # The old immutable plan and producing brief still retain their original requested mode.
        old=json.loads((self.h.root/view['study_id']/'focus-group'/'plans'/(old_revision+'.json')).read_text())
        self.assertEqual(old['plan']['participant_models'][0]['runtimeMode'],'auto')
        self.assertEqual(brief['model_selection']['dispatch']['target']['runtimeMode'],'auto')
        self.assertEqual(project()['evidence']['cells'][0]['requested']['runtimeMode'],'approval-required')

    def test_relocated_worker_bundle_and_all_six_operation_contracts(self):
        package,manifest,prefix,agents=fixtures.policy_install(self.h.helper)
        meta=json.loads((package/'plugin.json').read_text())
        matrix=json.loads((package/'shared/operation-matrix.json').read_text())['plugins']['focus-group']
        self.assertEqual(set(matrix),{'plan','run','resume','status','cancel','doctor'})
        self.assertEqual(matrix,meta['operation_review'])
        self.assertIn('stricter fidelity',matrix['run']['reason'])
        for op in ('doctor','status','cancel'):
            self.assertEqual((matrix[op]['selection'],matrix[op]['planning']),('direct','none'))
            self.assertEqual(self.policy('admit',{'operation':op}),{'allowed':True,'chooser':False,'dispatch':False})
        required={'reviewer-standard.md','model-selection.schema.json','model-authority.schema.json',
            'planning-policy.schema.json','planning-job.schema.json','planning-subject.schema.json',
            'planning-assessment.schema.json','planning-direct.schema.json'}
        self.assertTrue(required<=set(meta['worker_shared']))
        bundle=Path(manifest['bundle_dir'])
        for name in required:
            self.assertEqual((bundle/'shared'/name).read_bytes(),(package/'shared/agents'/name).read_bytes())
        for worker in meta['workers']:
            self.assertEqual((worker['allowed_scope'],worker['output_contract']),('read-only','worker-result.schema.json'))
            self.assertEqual((bundle/'workers'/Path(worker['path']).name).read_bytes(),(package/worker['path']).read_bytes())
        self.assertEqual(meta['planning_review']['worker_id'],'focus-group/plan-reviewer')

    def test_raw_participant_lineage_is_not_a_synthesis_author_but_actual_authors_and_other_operations_are(self):
        from tests.model_selection_fixtures import replacement
        draft=self.h.draft(review=fg.CLAUDE)
        admission=fixtures.policy_selection(self.h,draft)
        chosen=admission['selection']
        # The raw participant model may review a synthesis authored by GPT plus the coordinator.
        models.validate(chosen)
        for role in ('analysis','workhorse'):
            bad=deepcopy(chosen);bad['review_panel'][0]['target']=deepcopy(bad['work'][role])
            with self.assertRaisesRegex(ValueError,'every actual/prospective author'):approved_selection(bad)
        bad=deepcopy(chosen);bad['author_lineages']=['anthropic']
        with self.assertRaisesRegex(ValueError,'every actual/prospective author'):approved_selection(bad)
        for op in ('imps/run','plan','focus-group/other'):
            bad=deepcopy(chosen);bad['operation']=op
            with self.assertRaisesRegex(ValueError,'every actual/prospective author'):approved_selection(bad)
        # Replacement independence uses the same classification, with explicit finite authority.
        base=fixtures.policy_selection(self.h,self.h.draft())['selection']
        d=deepcopy(base);target=deepcopy(d['work']['participant-01'])
        spare=replacement(d,target,review=True);spare['slot_id']='fidelity'
        d['review_replacements']=[spare]
        raw_replacement=replacement(d,d['review_panel'][0]['target']);raw_replacement['role']='participant-01'
        d['work_replacements']=[raw_replacement]
        d=approved_selection(d)
        selected=models.dispatch(d,role='reviewer',slot_id='fidelity',target=target,
            unavailable={'kind':'technical','reference':'fixture:bounded-prelaunch-failure','reconciled':[{'target':next(s['target'] for s in d['review_panel'] if s['slot_id']=='fidelity'), 'request_id':'fixture-original', 'reference':'fixture:host-absent','owned':True,'has_pending_child_runs':False,'status':'absent','reason':'technical'}]})
        self.assertTrue(selected['substituted'])
        self.assertEqual(selected['target'],target)
        # Unrelated operations keep their existing independent replacement behavior.
        from tests.model_selection_fixtures import selection_input
        other=selection_input();alternate=deepcopy(other['profiles']['models'][2]['target'])
        other['work_replacements']=[replacement(other,alternate)]
        other['review_replacements']=[replacement(other,alternate,review=True)]
        other=approved_selection(other)
        self.assertEqual(models.dispatch(other,role='reviewer',slot_id='review',target=alternate,
            unavailable={'kind':'technical','reference':'fixture:unrelated-control','reconciled':[{'target':next(s['target'] for s in other['review_panel'] if s['slot_id']=='review'), 'request_id':'fixture-original', 'reference':'fixture:host-absent','owned':True,'has_pending_child_runs':False,'status':'absent','reason':'technical'}]})['target'],alternate)
        bad=deepcopy(d);bad['author_lineages']=['anthropic'];bad=approved_selection(bad)
        with self.assertRaisesRegex(ValueError,'independent slot'):
            models.dispatch(bad,role='reviewer',slot_id='fidelity',target=target,
                unavailable={'kind':'technical','reference':'fixture:bounded-prelaunch-failure','reconciled':[{'target':next(s['target'] for s in d['review_panel'] if s['slot_id']=='fidelity'), 'request_id':'fixture-original', 'reference':'fixture:host-absent','owned':True,'has_pending_child_runs':False,'status':'absent','reason':'technical'}]})

    def test_missing_upfront_choices_and_missing_actual_host_author_stop_before_plan(self):
        draft=self.h.draft();before=self.h.files()
        self.h.refused('model_selection_required','plan','--state-root',self.h.root,'--study',draft['study_id'],
            '--input',self.h.write('unselected.json',draft),'--capabilities',self.h.caps)
        self.assertFalse((self.h.root/draft['study_id']/'focus-group'/'current.json').exists())
        self.h.refused('model_selection_required','suggest','--input',self.h.write('unselected-suggest.json',draft),
                      '--capabilities',self.h.caps)
        # Missing actual host identity is a visible failure, never a made-up parent thread.
        a=fixtures.policy_selection(self.h,draft);s=deepcopy(a['selection']);s['capabilities'].pop('parentThreadId')
        s=approved_selection(s);a=adopter.admit('focus-group',{**{k:a[k] for k in ('request_reference','output_name','invocation_id')},
            'operation':'plan','selection':s,'selection_sha256':s['selection_sha256']})
        code,out=self.h.call('plan','--state-root',self.h.root,'--study',draft['study_id'],
            '--input',self.h.write('no-host-draft.json',draft),'--capabilities',self.h.write('no-host.json',s['capabilities']),
            '--admission',self.h.write('no-host-admission.json',a))
        self.assertNotEqual(code,0,out)
        directory=self.h.root/draft['study_id']/'focus-group'
        self.assertFalse((directory/'current.json').exists())
        self.assertFalse((directory/'plans').exists())
        self.assertEqual(list(directory.rglob('document-authors.json')),[])
        # A supplied fresh host identity that differs from the retained chooser is also refused.
        good=fixtures.policy_selection(self.h,draft);caps=deepcopy(good['selection']['capabilities'])
        caps['parentThreadId']='another-actual-host-parent'
        code,out=self.h.call('plan','--state-root',self.h.root,'--study',draft['study_id'],
            '--input',self.h.write('changed-host-draft.json',draft),'--capabilities',self.h.write('changed-host.json',caps),
            '--admission',self.h.write('changed-host-admission.json',good))
        self.assertNotEqual(code,0,out)
        self.assertFalse((directory/'plans').exists())

    def test_missing_adverse_and_stale_receipts_refuse_owner_approval_and_panel_work(self):
        draft,view=self.raw_plan()
        self.h.refused('planning_review_required','approve','--state-root',self.h.root,'--study',view['study_id'],
                      '--input',self.h.approval(view))
        # An actual adverse execution and receipt remain adverse and cannot attach.
        finished=fixtures.policy_review(self.h,view,adverse=True,attach=False)
        self.assertFalse(finished['accepted'])
        self.policy('attach',{'state_root':str(self.h.root),'study':view['study_id'],
            'metadata_file':str(self.h.planning_metadata),'receipt':self.h.planning_receipt['path']},ok=False)
        self.assertEqual(json.loads(Path(self.h.planning_receipt['path']).read_text())['passes'][0]['outcome'],'adverse')
        self.h.refused('planning_review_required','approve','--state-root',self.h.root,'--study',view['study_id'],
                      '--input',self.h.approval(view))

    def test_accepted_receipt_stales_on_input_drift_and_run_requires_its_own_choice(self):
        draft,view=self.raw_plan()
        evidence=self.h.inputs/'declared-review-evidence.txt';evidence.write_text('Bound study evidence.\n')
        self.h.policy_evidence=[str(evidence)]
        fixtures.policy_review(self.h,view)
        self.policy('validate',{'state_root':str(self.h.root),'study':view['study_id']})
        self.h.approve(view)
        self.h.check_run(view,expect='planning_review_required')
        selected=self.public_run_choice()
        self.h.check_run(view)
        desc=json.loads(self.desc_path().read_text())
        plan=Path(desc['document']['path']);authors=json.loads((plan.parent/'document-authors.json').read_text())
        self.assertIn('fixture-actual-parent',json.dumps(authors))
        raw=plan.read_bytes();plan.write_bytes(raw+b'\n')
        self.policy('validate',{'state_root':str(self.h.root),'study':view['study_id']},ok=False)
        self.h.check_run(view,expect='planning_review_required');plan.write_bytes(raw)
        self.policy('validate',{'state_root':str(self.h.root),'study':view['study_id']})
        # Product-study capture avoids Git but still binds declared bytes, paths and the evidence root.
        from shared import planning_review as planning
        content=evidence.read_bytes();evidence.write_bytes(content+b'changed')
        self.policy('validate',{'state_root':str(self.h.root),'study':view['study_id']},ok=False)
        evidence.write_bytes(content)
        descriptor_bytes=self.desc_path().read_bytes();metadata_bytes=self.h.planning_metadata.read_bytes()
        alternate=self.h.inputs/'same-evidence-other-path.txt';alternate.write_bytes(content)
        other_root=self.h.base/'other-evidence-root';other_root.mkdir()
        for field,value in (('repository_root',str(other_root)),('evidence_paths',[str(alternate)])):
            meta=json.loads(metadata_bytes);meta['inputs'][field]=value
            self.h.planning_metadata.write_text(json.dumps(meta))
            descriptor=json.loads(descriptor_bytes);descriptor['planning_review']=planning.file_descriptor(self.h.planning_metadata)
            self.desc_path().write_text(json.dumps(descriptor))
            self.policy('validate',{'state_root':str(self.h.root),'study':view['study_id']},ok=False)
        self.h.planning_metadata.write_bytes(metadata_bytes);self.desc_path().write_bytes(descriptor_bytes)
        self.policy('validate',{'state_root':str(self.h.root),'study':view['study_id']})
        self.public_run_choice(operation='resume',retain=False)
        self.public_run_choice(operation='resume',retain=True,invocation=selected['invocation_id'])

    def test_proposed_pin_cannot_execute_an_unverified_policy_adapter(self):
        self.h.start(personas=1)
        bad=deepcopy(self.h.job_state())
        fake=self.h.inputs/'unverified-package';(fake/'scripts').mkdir(parents=True)
        marker=self.h.inputs/'unverified-code-executed'
        (fake/'scripts/plan_review.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("unverified")\n')
        bad['pins']['focus-group']['package_dir']=str(fake)
        with self.assertRaises((ValueError,OSError)):
            adopter.validate_job(bad)
        self.assertFalse(marker.exists(),'proposed job pins must not select executable policy code')
        runtime=Path(self.h.job_state()['pins']['focus-group']['package_dir'])
        installed=json.loads((runtime/'install-manifest.json').read_text())
        fresh=self.h.base/'forged-creation-root'
        payload=self.h.write('forged-create.json',bad)
        p=subprocess.run([sys.executable,str(runtime/'shared/job_cli.py'),'create','--state-root',str(fresh),
            '--job',bad['job_id'],'--input',str(payload),'--prefix',str(runtime.parents[1]),
            '--agents-root',installed['agents_root']],cwd=self.h.base,
            env={**os.environ,**self.h.policy_env,'PYTHONDONTWRITEBYTECODE':'1'},
            capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertFalse(marker.exists(),'public creation executed unverified adapter')
        self.assertEqual(list(fresh.rglob('*')),[],'refused creation must create no study/job artifacts')

    def test_public_creation_persists_required_selection_policy(self):
        self.h.start(personas=1)
        original=self.h.job_state();original['policy']['model_selection_required']=False
        runtime=Path(original['pins']['focus-group']['package_dir'])
        installed=json.loads((runtime/'install-manifest.json').read_text())
        fresh=self.h.base/'required-policy-root'
        p=subprocess.run([sys.executable,str(runtime/'shared/job_cli.py'),'create','--state-root',str(fresh),
            '--job',original['job_id'],'--input',str(self.h.write('required-policy-create.json',original)),
            '--prefix',str(runtime.parents[1]),'--agents-root',installed['agents_root']],cwd=self.h.base,
            env={**os.environ,**self.h.policy_env,'PYTHONDONTWRITEBYTECODE':'1'},
            capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        stored=json.loads((fresh/original['job_id']/'job.json').read_text())
        self.assertIs(stored['policy']['model_selection_required'],True)

    def test_new_slots_require_current_selection_and_existing_producing_choices_are_retained(self):
        self.h.start(personas=1)
        original=self.h.job_state()
        historic=deepcopy(original['model_selection']);historic['invocation_id']+='-previous'
        historic=approved_selection(historic)
        current=deepcopy(original);current['model_selection_history']={historic['selection_sha256']:historic}
        current['tasks'][0]['selection_binding']['selection_sha256']=historic['selection_sha256']
        script="""import json,sys
sys.path.insert(0,sys.argv[1])
from shared.job_coordinator import selection_plan_revision
data=json.load(open(sys.argv[2]))
try:selection_plan_revision(data['current'],data['proposed'])
except ValueError as e:print(str(e));sys.exit(2)
"""
        runtime=Path(original['pins']['focus-group']['package_dir'])
        def revise(previous,proposed,expected):
            payload=self.h.write('producing-revision.json',{'current':previous,'proposed':proposed})
            p=subprocess.run([sys.executable,'-c',script,str(runtime),str(payload)],cwd=self.h.base,
                env={**os.environ,**self.h.policy_env,'PYTHONDONTWRITEBYTECODE':'1'},
                capture_output=True,text=True,timeout=60)
            self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
            return p.stdout
        # An existing slot keeps exactly the producing contract already owned by this job.
        revise(current,{'tasks':deepcopy(current['tasks'])},0)
        added=deepcopy(current['tasks'][0]);added['task_id']+='-new';added['request_id']+='-new'
        proposed={'tasks':deepcopy(current['tasks'])+[added]}
        self.assertIn('new or changed panel slot requires current choices',revise(current,proposed,2))
        changed=deepcopy(current['tasks']);changed[0]['role']='review'
        self.assertIn('new or changed panel slot requires current choices',revise(current,{'tasks':changed},2))
        # Fresh creation has no owned producing history to retain.
        installed=json.loads((runtime/'install-manifest.json').read_text())
        fresh=self.h.base/'new-producing-history-root'
        p=subprocess.run([sys.executable,str(runtime/'shared/job_cli.py'),'create','--state-root',str(fresh),
            '--job',current['job_id'],'--input',str(self.h.write('new-producing-history.json',current)),
            '--prefix',str(runtime.parents[1]),'--agents-root',installed['agents_root']],cwd=self.h.base,
            env={**os.environ,**self.h.policy_env,'PYTHONDONTWRITEBYTECODE':'1'},
            capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn('new or changed panel slot requires current choices',p.stdout+p.stderr)
        self.assertEqual(list(fresh.rglob('*')),[])

    def test_exact_roles_generic_bypass_refusal_and_fresh_revision_keep_history(self):
        self.h.start(personas=1)
        original=self.h.job_state();old_selection=original['model_selection_sha256']
        for task in original['tasks']:
            bound=task['selection_binding'];s=original['model_selection']
            picked=models.dispatch(s,role=bound['role'],slot_id=bound.get('slot_id'))
            for key in ('providerInstanceId','model','options','runtimeMode'):
                self.assertEqual(picked['target'].get(key,{}),task['target'].get(key,{}))
        # Public create/prepare/accept callback has no legacy/policy=False escape.
        for key in ('model_selection','adopter_admission'):
            bad=deepcopy(original);bad.pop(key,None)
            for stage in bad['stages']:stage['resources'].pop('focus_group_admission',None)
            bad['policy']['model_selection_required']=False
            with self.assertRaises(ValueError):adopter.validate_job(bad)
        for field in ('invocation_id','scope_id','job_id'):
            bad=deepcopy(original);bad[field]+='-transplant'
            with self.assertRaises(ValueError):adopter.validate_job(bad)
        # Fresh run selection for a changed exact study revision travels through the generic route.
        draft=self.h.draft();draft['personas']=draft['personas'][:1];draft['decision']+=' Check recovery too.'
        self.h.view=self.h.plan(draft);self.h.approve(self.h.view)
        new=self.public_run_choice(invocation='fresh-run-for-revised-study')
        self.h.ok('carry','--state-root',self.h.root,'--study',self.h.view['study_id'],'--write')
        self.h.revise_job()
        current=self.h.job_state()
        self.assertEqual((current['invocation_id'],current['scope_id']),(new['invocation_id'],new['scope_id']))
        self.assertIn(old_selection,current['model_selection_history'])
        self.assertEqual(current['model_selection'],new['selection'])
        self.assertEqual(current['policy']['max_live_workers'],original['policy']['max_live_workers'])
        self.assertEqual(current['tasks'][0]['target'],original['tasks'][0]['target'])
        # A same-lineage fidelity choice and replacing a selected cell with a generic target both fail.
        desc=json.loads(self.desc_path().read_text());plan=json.loads(Path(desc['document']['path']).read_text())['plan']
        adapter=adopter.focus_group_adapter(self.h.helper.parent.parent)
        bad=deepcopy(new);s=deepcopy(new['selection']);s['work']['participant-01']=s['work']['workhorse'];s=approved_selection(s)
        bad['selection']=s;bad['selection_sha256']=s['selection_sha256'];bad.pop('sha256');bad=__import__('shared.planning_review',fromlist=['seal']).seal(bad)
        with self.assertRaisesRegex(ValueError,'approved matrix'):adapter.choices(plan,bad)
        s=deepcopy(new['selection']);s['review_panel'][0]['target']=deepcopy(s['work']['analysis'])
        s['review_panel'][0]['independent']=False
        s=approved_selection(s)
        bad=deepcopy(new);bad['selection']=s;bad['selection_sha256']=s['selection_sha256'];bad.pop('sha256')
        bad=__import__('shared.planning_review',fromlist=['seal']).seal(bad)
        with self.assertRaisesRegex(ValueError,'independent fidelity'):adapter.choices(plan,bad)


class FocusPlanningTest(FocusPlanningContract, unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.h=fg.ReportHost(Path(self.tmp.name))
