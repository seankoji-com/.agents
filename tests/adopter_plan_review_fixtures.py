"""Public adopter fixtures; real installed planning jobs, synthetic host observations."""
from copy import deepcopy
import json
from pathlib import Path
import sys

from core.jobs.store import digest
from shared import model_selection as models, planning_review as planning
from tests.ape_plan_review_fixtures import ApePlanFixture
from tests.model_selection_fixtures import selection_input, replacement, answer
from tests.test_rebuild_installed import ROOT


class AdopterFixture(ApePlanFixture):
    serial = 0

    def __init__(self, box, package, manifest, *, plugin='agent-tuneup', op='align', kind=None,
                 installed=True, direct=False, private=True):
        type(self).serial += 1
        self.box,self.package,self.manifest = box,package,manifest
        self.id='adopters-'+str(self.serial);self.plugin_name=plugin;self.op=op;self.direct_mode=direct
        self.runtime=package if installed else ROOT
        self.plugin=package if installed else ROOT/'plugins'/plugin
        self.base=box.private/self.id;self.base.mkdir()
        self.project=self.base/'project';self.project.mkdir()
        box.run(['git','init','-q',self.project]);box.run(['git','-C',self.project,'-c','user.name=Fixture',
            '-c','user.email=fixture@example.invalid','commit','-qm','initial','--allow-empty'])
        self.local=self.project/'source.py';self.local.write_text('VALUE = 1\n')
        self.request=self.base/'request.txt';self.request.write_text('Assess the requested outcome with evidence and safe recovery.')
        self.reference='fixture:request:'+self.id;self.output_name=self.id+'/output'
        self.scope=planning.logical_output_id(self.reference,self.output_name)
        d=json.loads(json.dumps(selection_input()).replace('alpha-work','gpt-fixture').replace('beta-review','claude-fixture')
            .replace('gamma-spare','gemini-fixture').replace('"alpha"','"openai"').replace('"beta"','"anthropic"').replace('"gamma"','"google"'))
        d.update(scope_id=self.scope,invocation_id=self.id,operation=plugin+'/'+op)
        d['coordinator']['lineage']='openai';d['review_panel'][0].update(independent=False,coverage=['REQ-ONE','D1'])
        if private:
            d['sharing']=[{'target':d['review_panel'][0]['target'],'data_classes':['private-settings'],
                           'source':answer('Permit the selected reviewer to read this private-settings proposal.')}]
        if direct:
            row=replacement(d,d['coordinator'],review=True);row.pop('target');row['execution']='self-review'
            row['authority']['data_classes'].append('private-settings');d['review_replacements'].append(row)
        self.selection_data=d;self.selection=models.freeze(d)
        self.admission_input={'operation':op,'request_reference':self.reference,'output_name':self.output_name,
            'invocation_id':self.id,'selection':self.selection,'selection_sha256':self.selection['selection_sha256']}
        self.admission=self.ape('admit',self.admission_input)
        self.answer=self.base/'output.md';self.answer.write_text('No changes recommended. Evidence covers the requested outcome and recovery.\n')
        self.record_author(self.answer)
        self.metadata=self.base/'review-metadata.json';self.snapshot=None;self.review_id=self.id+'-planning';self.final_rid='REQ-ONE'
        self.requirements={'REQ-ONE':'Assess the requested outcome'}
        self.inputs={'requests':[{'path':str(self.request),'reference':self.reference,'clauses':[
            {'start':0,'end':len(self.request.read_text()),'requirement':'REQ-ONE'}]}],'decisions':[],
            'requirements':self.requirements,'load_bearing_decisions':['D1'],
            'repository_root':str(self.project),'evidence_paths':[str(self.local)]}
        self.descriptor={'kind':kind or ('conclusions' if plugin=='agent-tuneup' else 'design' if plugin=='elephant-goldfish' else 'strategy'),
            'admission':self.admission,'document':planning.file_descriptor(self.answer),'requirements':self.requirements}

        if plugin == 'agent-tuneup':
            self.descriptor['observation_conclusions'] = {'findings': [], 'changes': []}

    def record_author(self, document):
        caps=deepcopy(self.selection['capabilities']);caps.update(parentThreadId='fixture-parent',
            inheritedProviderInstanceId=self.selection['coordinator']['providerInstanceId'],inheritedModel=self.selection['coordinator']['model'])
        script=self.runtime/'shared/document_authors.py'
        from shared.document_authors import append_author, locked_author_records
        with locked_author_records(document.parent) as (records, save):
            save(append_author(records,document.read_bytes(),caps,document_path=document))

    def ape(self, command, data, ok=True):
        p=self.box.run([sys.executable,self.plugin/'scripts/plan_review.py',command,'--input',self.box.payload(data)],check=False)
        if p.returncode!=(0 if ok else 2):raise AssertionError(p.stdout+p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def review(self,command,data=None,ok=True):
        payload=dict(data or {})
        if command not in ('create','validate'):payload.setdefault('caller',self.review_caller)
        argv=[sys.executable,self.runtime/'shared/planning_review_cli.py',command,'--input',self.box.payload(payload),
              '--state-root',self.box.jobs,'--job',self.review_id]
        if command=='create':argv+=['--prefix',self.box.prefix,'--agents-root',self.box.agents]
        p=self.box.run(argv,check=False)
        if p.returncode!=(0 if ok else 2):raise AssertionError(p.stdout+p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def prepare(self):
        out=self.ape('prepare',{'descriptor':self.descriptor,'inputs':self.inputs,'metadata_file':str(self.metadata)})
        self.snapshot=out['snapshot'];return out

    def begin_review(self):
        if self.snapshot is None:self.prepare()
        made=self.review('create',{'job_id':self.review_id,'installation_id':self.manifest['installation_id'],
            'plugin':self.plugin_name,'project_id':self.selection['project_id'],'owner':'fixture-owner',
            'invocation_id':self.id,'scope_id':self.scope,'selection':self.selection,'snapshot':self.snapshot})
        self.review_caller=made['caller'];self.review('begin');return made

    def proposal(self):
        self.target=self.base/'settings.json';self.target.write_text('{"mcpServers":{"unused":{"disabled":false}}}')
        self.target.chmod(0o600)
        self.candidate=self.base/'candidate.json';self.candidate.write_text('{"mcpServers":{"unused":{"disabled":true}}}')
        self.candidate.chmod(0o600)
        self.before=self.base/'before.json';self.before.write_bytes(self.target.read_bytes());self.before.chmod(0o600)
        self.plan_file=self.base/'private-plan.json'
        p=self.box.run([sys.executable,self.plugin/'scripts/align.py','plan','--adapter','claude','--target',self.target,
            '--candidate',self.candidate,'--allow-key','/mcpServers/unused/disabled','--out',self.plan_file])
        self.plan=json.loads(self.plan_file.read_text())
        self.descriptor.update(kind='proposal',plan_file=str(self.plan_file),before_file=str(self.before),plan_digest=self.plan['approval_digest'])
        return json.loads(p.stdout)

    def owner_approve(self,ok=True):
        owner_file=self.base/'approval.txt';owner_file.write_text('Apply the exact displayed candidate and digest.')
        self.owner={'path':str(owner_file),'source':answer(owner_file.read_text()),'plan_digest':self.plan['approval_digest']}
        return self.ape('approve',{'descriptor':self.descriptor,'owner':self.owner},ok=ok)

    def apply_context(self,approval):
        d=deepcopy(self.selection_data);d['operation']='agent-tuneup/apply';d['invocation_id']=self.id+'-apply'
        s=models.freeze(d)
        a=self.ape('admit',{**self.admission_input,'operation':'apply','invocation_id':d['invocation_id'],
            'selection':s,'selection_sha256':s['selection_sha256']})
        return {'admission':a,'approval':approval}

    def elephant_job(self):
        from tests.test_rebuild_installed import worker_result
        # Both specialised reviewers remain different from the actual document author.
        d=deepcopy(self.selection_data);d['work']['factual']=deepcopy(d['review_panel'][0]['target'])
        d['profiles']['roles']['factual']={'minimum':2,'judgement':True}
        self.selection=models.freeze(d);self.admission_input.update(selection=self.selection,
            selection_sha256=self.selection['selection_sha256']);self.admission=self.ape('admit',self.admission_input)
        self.descriptor['admission']=self.admission
        self.job_id=self.id+'-documents';self.job_file=self.box.jobs/self.job_id/'job.json'
        doc=planning.file_descriptor(self.answer)
        stages=[];slots=[]
        for sid,mode,rid in [('facts','factual','R-FACT'),('cold','cold-read','R-COLD')]:
            contract={'root':str(self.base),'slug':self.project.name,'mode':mode,
                      'document_path':str(self.answer),'document_sha256':doc['sha256']}
            # Put the document in the declared scope before building the contract.
            contract['root']=str(self.base.parent);contract['slug']=self.base.name
            stages.append({'id':sid,'depends_on':[] if sid=='facts' else ['facts'],
                'requirements':[rid],'status':'pending','validator_dependency':'domain','validator_contract':contract,
                **({'resources':{'adopter_design_file':str(self.base/'published-design.json')}} if sid=='cold' else {})})
            task={'task_id':sid,'stage_id':sid,'logical_slot_id':'primary','request_id':self.id+'-'+sid,
                'worker_id':'elephant-goldfish/'+('factual-checker' if sid=='facts' else 'cold-reader'),
                'dependency_key':'domain','status':'pending','role':'worker' if sid=='facts' else 'review',
                'target':deepcopy(self.selection['work']['factual'] if sid=='facts' else self.selection['review_panel'][0]['target']),
                'write_scope':{'mode':'coordinator-only'},'document':{k:doc[k] for k in ('path','sha256')},
                'independent_of_author':True,'selection_binding':{'selection_sha256':self.selection['selection_sha256'],
                    'role':'factual' if sid=='facts' else 'reviewer'}}
            if sid=='cold':
                task.update(context_policy='document-only',reviewed_documents=[task['document']])
                task['selection_binding']['slot_id']='review'
            slots.append(task)
        self.job={'schema_version':1,'job_id':self.job_id,'installation_id':self.manifest['installation_id'],
            'workflow':'elephant-goldfish/elephant','owner':'fixture-owner','objective':'A repaired feasible readable design',
            'requirements':{'R-FACT':'Facts match code','R-COLD':'Reader can act'},'authorization':{'actions':['read']},
            'constraints':['Offline only.'],'dependencies':[{'key':'domain','plugin':'elephant-goldfish'}],
            'stages':stages,'tasks':slots,'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},
            'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1},
            'adopter_admission':self.admission,'model_selection':self.selection,
            'model_selection_sha256':self.selection['selection_sha256'],'invocation_id':self.id,'scope_id':self.scope}
        self.box.create(self.package,self.job)
        self.caller=self.box.caller(self.manifest,self.job['workflow'])
        self.descriptor.update(job_file=str(self.job_file),factual_stage='facts')

    def complete_document_slot(self,sid):
        from tests.test_rebuild_installed import worker_result
        brief=self.box.dispatch(self.package,self.job_id,self.caller,sid,'host-'+self.id+'-'+sid)
        chosen=self.selection['work']['factual'] if sid=='facts' else self.selection['review_panel'][0]['target']
        self.box.job(self.package,'task-observation',self.job_id,{'caller':self.caller,'task_id':sid,'event':{
            'kind':'completion','completion_id':self.id+'-'+sid+'-done','request_id':brief['request_id'],
            'host_task_id':'host-'+self.id+'-'+sid,'status_identity':chosen,'status':'completed',
            'work_state':'result_available','has_pending_child_runs':False}})
        r=json.loads(worker_result(brief))
        if sid=='cold':r.update(review_verdict='approve',conclusion='VERDICT: READY')
        self.box.complete(self.package,self.job_id,self.caller,sid,brief,'host-'+self.id+'-'+sid,json.dumps(r))
        return brief

    def accept_document(self,sid,*,outcome='confirmed',ok=True):
        from core.jobs.store import canonical
        mode='factual' if sid=='facts' else 'cold-read'
        content={'document_sha256':planning.file_descriptor(self.answer)['sha256']}
        if sid=='facts':content.update(claim_id='C1',outcome=outcome)
        else:content['verdict']='ready'
        evidence={'observer':'coordinator','kind':'factual-claim' if sid=='facts' else 'cold-read',
            'source':'fixture:actual-host-result','content':content,'sha256':digest(canonical(content))}
        data={'kind':'factual-observation' if sid=='facts' else 'cold-read-observation',
              'document_path':str(self.answer),'document_sha256':content['document_sha256']}
        if sid=='facts':data['claims']=[{'claim_id':'C1','outcome':outcome,'evidence':[evidence]}]
        else:data.update(verdict='ready',evidence=[evidence])
        obs=self.box.publish(self.package,self.job_id,self.caller,sid,data)
        self.document_observations=getattr(self,'document_observations',{});self.document_observations[sid]=obs
        argv=[str(self.package/'scripts/validate_document.py'),'--root',str(self.base.parent),
            '--slug',self.base.name,'--mode',mode,'--input',obs]
        out=self.box.accept(self.package,'accept-stage',self.job_id,{'caller':self.caller,'stage_id':sid,
            'validator_argv':argv,'input_file':obs})
        if ok and (out.returncode or not json.loads(out.stdout)['accepted']):raise AssertionError(out.stdout+out.stderr)
        if not ok and out.returncode==0 and json.loads(out.stdout).get('accepted'):raise AssertionError('unexpected acceptance')
        return out

    def install_design(self):
        job=self.box.state_of(self.job_id)
        cold=next(s for s in job['stages'] if s['id']=='cold')
        if cold.get('resources',{}).get('adopter_design_file'):
            return self.ape('publish',{'descriptor':self.descriptor,'output_file':cold['resources']['adopter_design_file']})
        cold.setdefault('resources',{})['adopter_design']=self.descriptor
        revision={'id':self.id+'-design','summary':'Attach accepted design before readability'}
        decision=self.box.owner_decision(self.id+'-design','Use the reviewed design as the cold-read prerequisite.',
            'plan:'+revision['id'])
        self.box.job(self.package,'decision',self.job_id,{'caller':self.caller,'decision':decision})
        revision['owner_decision_id']=decision['id']
        return self.box.job(self.package,'plan-revision',self.job_id,{'caller':self.caller,'revision':revision,
            'new_plan':{'stages':job['stages']}})

    def integrated_job(self):
        """Existing direct domain stage; no invented planning stage in its parent."""
        d=deepcopy(self.selection_data);d['work']['workhorse']['execution']='current-context'
        d['work']['workhorse']['accept_actual_settings']=True
        self.selection=models.freeze(d);self.admission_input.update(selection=self.selection,
            selection_sha256=self.selection['selection_sha256']);self.admission=self.ape('admit',self.admission_input)
        self.descriptor['admission']=self.admission
        self.job_id=self.id+'-parent';self.job_file=self.box.jobs/self.job_id/'job.json'
        if self.plugin_name=='agent-tuneup':
            contract={'criteria':{'operation':'audit','findings_allowed':True,'live_enforcement_required':False}}
            data={**contract,'audit_exit_code':0,'findings':[],'changes':[]}
        else:
            contract={'pr':'https://github.com/fixture/repository/pull/1','head_sha':'a'*40,
                'required_contexts':['build'],'allow_empty_required_contexts':False,'optional_contexts':[],
                'authorized_endstate':{'requested':'mergeable','observed':'mergeable','authorization_ref':'fixture:request'}}
            data={**contract,'required_checks':[{'context':'build','conclusion':'success','head_sha':'a'*40}],
                'review_threads':[],'review_thread_count':0}
            content=deepcopy(data)
            from core.jobs.store import canonical
            data['host_observations']=[{'observer':'coordinator','kind':'pr-state','source':'fixture:host',
                'content':content,'sha256':digest(canonical(content))}]
        self.domain_data=data
        if self.plugin_name == "agent-tuneup":
            self.descriptor["observation_conclusions"] = {k: deepcopy(data[k]) for k in ("findings", "changes")}
        self.job={'schema_version':1,'job_id':self.job_id,'installation_id':self.manifest['installation_id'],
            'workflow':self.plugin_name+'/'+self.op,'owner':'fixture-owner','objective':'Integrated requested outcome',
            'requirements':self.requirements,'authorization':{'actions':['read']},'constraints':['Offline only.'],
            'dependencies':[{'key':'domain','plugin':self.plugin_name}], 'pins':{},
            'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'decisions':[],'history':[],
            'metrics':{},'result_contract':{'schema_version':1},'tasks':[],
            'stages':[{'id':'integrated','depends_on':[],'requirements':['REQ-ONE'],'status':'pending',
                'execution_mode':'direct','validator_dependency':'domain','validator_contract':contract,
                'selection_binding':{'role':'workhorse','selection_sha256':self.selection['selection_sha256']}}],
            'adopter_admission':self.admission,'model_selection':self.selection,
            'model_selection_sha256':self.selection['selection_sha256'],'invocation_id':self.id,'scope_id':self.scope}
        self.box.create(self.package,self.job);self.caller=self.box.caller(self.manifest,self.job['workflow'])
        caps=deepcopy(self.selection['capabilities']);caps.update(parentThreadId='fixture-parent',
            inheritedProviderInstanceId=self.selection['coordinator']['providerInstanceId'],inheritedModel=self.selection['coordinator']['model'])
        self.box.job(self.package,'direct-execution',self.job_id,{'caller':self.caller,'stage_id':'integrated'},
            extra=('--capabilities',self.box.payload(caps)))
        if self.plugin_name=='agent-tuneup':self.descriptor['job_file']=str(self.job_file)

    def accept_integrated(self,ok=True):
        data=deepcopy(self.domain_data)
        if self.plugin_name=='agent-tuneup' and self.descriptor.get('planning_review'):
            data['adopter_output']=self.descriptor
        obs=self.box.publish(self.package,self.job_id,self.caller,'integrated',data)
        validator='validate_audit.py' if self.plugin_name=='agent-tuneup' else 'validate_pr.py'
        p=self.box.accept(self.package,'accept-stage',self.job_id,{'caller':self.caller,'stage_id':'integrated',
            'validator_argv':[str(self.package/'scripts'/validator),'--input',obs],'input_file':obs})
        if ok and (p.returncode or not json.loads(p.stdout)['accepted']):raise AssertionError(p.stdout+p.stderr)
        if not ok and p.returncode==0 and json.loads(p.stdout).get('accepted'):raise AssertionError('unexpected accepted integration')
        return p


def reviewed_apply_context(box,package,manifest,plan):
    """Migrate old native-write safety cases through actual review and owner gates."""
    f=AdopterFixture(box,package,manifest)
    f.plan=deepcopy(plan);f.plan_file=f.base/'plan.json';f.plan_file.write_text(json.dumps(plan))
    f.target=Path(plan['target']);f.candidate=Path(plan['candidate'])
    f.before=f.base/'before.json';f.before.write_bytes(f.target.read_bytes())
    f.descriptor.update(kind='proposal',plan_file=str(f.plan_file),before_file=str(f.before),plan_digest=plan['approval_digest'])
    f.approve();return f.apply_context(f.owner_approve())


def ralph_admission(data):
    """Transcribe the fixture owner's explicit pair and actual supported options."""
    d=selection_input();caps=deepcopy(data['capabilities'])
    d.update(invocation_id='fixture-ralph-invocation',operation='ralph/run',routing=None,
        scope_id=planning.logical_output_id('fixture:ralph-request','fixture-ralph-output'),capabilities=caps)
    work={k:deepcopy(data['implementer'][k]) for k in ('providerInstanceId','model','options','runtimeMode') if k in data['implementer']}
    review={k:deepcopy(data['evaluator'][k]) for k in ('providerInstanceId','model','options','runtimeMode') if k in data['evaluator']}
    work.setdefault('options',{});review.setdefault('options',{})
    # A missing cross-provider flag in these older capability fixtures means the
    # old runtime never asserted support. Add explicit synthetic host evidence.
    for provider in caps['providers']:provider.setdefault('canRunCrossProviderChildTask',True)
    from shared.lineage import lineage
    family=lambda t:lineage(next(p.get('driverKind','') for p in caps['providers'] if p['providerInstanceId']==t['providerInstanceId']),t['model'])
    d['coordinator']={**work,'lineage':family(work),'observed_options':work['options']}
    d['profiles']={'roles':{'workhorse':{'minimum':1},'reviewer':{'minimum':2,'judgement':True}},
        'models':[{'target':target,'quality':2,'judgement':True,'lineage':family(target),
            'lineage_source':'fixture:explicit-owner-confirmed-family','reason':'Synthetic lifecycle fixture suitability.',
            'fixed_effort_reason':'Synthetic fixed-effort evaluator is suitable for the fixture.'}
            for target,key in ((work,'implementer'),(review,'evaluator'))]}
    d['work']={'workhorse':work};d['review_panel']=[{'slot_id':'evaluation','role':'reviewer',
        'coverage':['fixture-goal'],'required':True,'independent':True,'target':review}]
    d['source']=answer('Use this exact fixture pair: '+json.dumps({'work':work,'review':review},sort_keys=True))
    s=models.freeze(d)
    from shared.adopter_planning import admit
    return admit('ralph',{'operation':'run','request_reference':'fixture:ralph-request','output_name':'fixture-ralph-output',
        'invocation_id':s['invocation_id'],'selection':s,'selection_sha256':s['selection_sha256']})


def review_existing_tuneup_report(package,manifest,env,state_root,job_id,data,base):
    """Old synthesis fixture now completes the real shared planning contract."""
    from tests.imps_plan_review_fixtures import legacy_box
    from core.jobs.store import canonical
    job_file=Path(state_root)/job_id/'job.json';job=json.loads(job_file.read_text())
    box=legacy_box(Path(base)/('planning-'+job_id),package,manifest,env);box.jobs=Path(state_root)
    f=AdopterFixture.__new__(AdopterFixture)
    f.box=box;f.package=Path(package);f.manifest=manifest;f.runtime=Path(package);f.plugin=Path(package);f.plugin_name='agent-tuneup'
    f.id=job['invocation_id'];f.op=job['workflow'].split('/')[1];f.admission=job['adopter_admission']
    f.selection=job['model_selection'];f.scope=job['scope_id'];f.reference=f.admission['request_reference']
    f.output_name=f.admission['output_name'];f.base=box.private;f.snapshot=None;f.direct_mode=False
    f.review_id=job_id+'-planning';f.final_rid=next(iter(job['requirements']));f.requirements=job['requirements']
    f.project=box.private/'project';f.project.mkdir();box.run(['git','init','-q',f.project])
    f.request=box.private/'request.txt';f.request.write_text(job['objective'])
    f.answer=box.private/'report.json';f.answer.write_bytes(canonical(data))
    f.metadata=box.private/'review.json'
    f.descriptor={'kind':'conclusions','admission':f.admission,'document':planning.file_descriptor(f.answer),
                  'requirements':f.requirements,'job_file':str(job_file),
                  'observation_conclusions':{k:deepcopy(data[k]) for k in ('findings','changes')}}
    f.inputs={'requests':[{'path':str(f.request),'reference':f.reference,'clauses':[
        {'start':0,'end':len(f.request.read_text()),'requirement':f.final_rid}]}],'decisions':[],
        'requirements':f.requirements,'load_bearing_decisions':[],'repository_root':str(f.project),'evidence_paths':[]}
    f.assessment=lambda:{'coverage':[{'id':rid,'outcome':'supported','evidence':'fixture:scope-precedence-recovery'}
        for rid in f.requirements],'inspected_paths':f.snapshot['declared_paths'],'responses':[]}
    f.begin_review()
    for slot in f.selection['review_panel']:
        if slot['required']:f.review_pass(slot=slot['slot_id'])
    f.finish();return f.descriptor


def ensure_legacy_elephant_design(case,job_id):
    """Give specialised cold-reader fixtures real factual and planning predecessors."""
    from tests.imps_plan_review_fixtures import legacy_box
    from core.jobs.store import canonical
    parent=case.job_state(job_id)
    if parent['workflow']!='elephant-goldfish/elephant' or not parent.get('adopter_admission'):return
    cold=next((s for s in parent['stages'] if s.get('validator_contract',{}).get('mode')=='cold-read'),None)
    if cold is None:return
    locator=cold.get('resources',{}).get('adopter_design_file')
    old=(json.loads(Path(locator).read_text()) if locator and Path(locator).exists() else cold.get('resources',{}).get('adopter_design'))
    if old:
        # A previously attached exact document does not create another review.
        if old['document']['sha256']==digest(Path(cold['validator_contract']['document_path']).read_bytes()):return
    generation=str(case.counter);case.counter+=1
    base=case.base/('design-review-'+job_id+'-'+generation)
    box=legacy_box(base,case.version,case.install,case.env);box.jobs=case.state
    f=AdopterFixture.__new__(AdopterFixture);f.box=box;f.manifest=case.install;f.package=case.version;f.plugin=case.version;f.runtime=case.version
    f.plugin_name='elephant-goldfish';f.id=parent['invocation_id'];f.op='elephant';f.admission=parent['adopter_admission']
    f.selection=parent['model_selection'];f.scope=parent['scope_id'];f.reference=f.admission['request_reference'];f.output_name=f.admission['output_name']
    f.base=box.private;f.snapshot=None;f.direct_mode=False;f.review_id=job_id+'-planning-'+generation
    f.requirements=parent['requirements'];f.final_rid=next(iter(f.requirements))
    f.project=box.private/'project';f.project.mkdir();box.run(['git','init','-q',f.project])
    f.request=box.private/'request.txt';f.request.write_text(parent['objective'])
    f.answer=Path(cold['validator_contract']['document_path']);f.metadata=box.private/'review.json'
    facts=next((s for s in parent['stages'] if s.get('validator_contract',{}).get('mode')=='factual' and s.get('acceptance')),None)
    if facts:
        producing_file=case.state/job_id/'job.json';factual_id=facts['id']
    else:
        # A document-only legacy fixture did not include a factual slot. Exercise
        # that missing prerequisite in its own read-only job before adequacy.
        facts_id=job_id+'-facts-'+generation
        slot={'target':f.selection['work']['fixture-factual'], 'role':'fixture-factual'}
        fact_contract=dict(cold['validator_contract'],mode='factual')
        job={'schema_version':1,'job_id':facts_id,'installation_id':case.install['installation_id'],
            'workflow':parent['workflow'],'owner':'fixture-owner','objective':parent['objective'],
            'requirements':{'R-FACT':'Confirm cited claims before design assessment'},'authorization':{'actions':['read']},
            'constraints':parent['constraints'],'dependencies':[{'key':'eg','plugin':'elephant-goldfish'}],
            'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'decisions':[],'history':[],
            'metrics':{},'result_contract':{'schema_version':1},'adopter_admission':f.admission,
            'model_selection':f.selection,'model_selection_sha256':f.selection['selection_sha256'],
            'invocation_id':f.id,'scope_id':f.scope,
            'stages':[{'id':'factual','depends_on':[],'requirements':['R-FACT'],'status':'pending','validator_dependency':'eg',
                'validator_contract':fact_contract}],
            'tasks':[{'task_id':'factual','stage_id':'factual','logical_slot_id':'primary','request_id':facts_id+'-request',
                'worker_id':'elephant-goldfish/factual-checker','dependency_key':'eg','status':'pending',
                'write_scope':{'mode':'coordinator-only'},'independent_of_author':True,
                'target':slot['target'],'selection_binding':{'role':slot['role'],**({'slot_id':slot['slot_id']} if slot.get('slot_id') else {}),
                    'selection_sha256':f.selection['selection_sha256']}}]}
        case.create(job);caller=case.caller(parent['workflow'])
        case.dispatch(facts_id,caller,'factual')
        observation=case.publish(facts_id,caller,'factual',case.factual_observation(f.answer))
        case.ok(case.accept(facts_id,caller,'factual',case.doc_argv(f.answer.parent.parent,f.answer.parent.name,'factual',observation),observation))
        producing_file=case.state/facts_id/'job.json';factual_id='factual'
    f.descriptor={'kind':'design','admission':f.admission,'document':planning.file_descriptor(f.answer),
        'requirements':f.requirements,'job_file':str(producing_file),'factual_stage':factual_id}
    f.inputs={'requests':[{'path':str(f.request),'reference':f.reference,'clauses':[
        {'start':0,'end':len(f.request.read_text()),'requirement':f.final_rid}]}],'decisions':[],
        'requirements':f.requirements,'load_bearing_decisions':[],'repository_root':str(f.project),'evidence_paths':[]}
    f.assessment=lambda:{'coverage':[{'id':rid,'outcome':'supported','evidence':'fixture:feasibility-failure-recovery'}
        for rid in f.requirements],'inspected_paths':f.snapshot['declared_paths'],'responses':[]}
    f.begin_review()
    if job_id.startswith('rounds-') and generation:
        subject=json.loads(Path(json.loads((box.jobs/f.review_id/'job.json').read_text())['planning']['subject_file']).read_text())
        if subject['round_limit']==3:
            text='Permit 30 planning assessments for this isolated cold-read budget fixture.'
            source=box.private/'budget-answer.txt';source.write_text(text)
            f.review('owner-decision',{'decision':{'kind':'limit-increase','logical_output_id':f.scope,
                'source':answer(text),'source_file':str(source),'round_limit':30,'technical_limit':200}})
    for slot in f.selection['review_panel']:
        if slot['required']:f.review_pass(slot=slot['slot_id'])
    f.finish();f.review('release')
    if locator:
        f.ape('publish',{'descriptor':f.descriptor,'output_file':locator})
        return
    parent=case.job_state(job_id);cold=next(s for s in parent['stages'] if s['id']==cold['id'])
    cold.setdefault('resources',{})['adopter_design']=f.descriptor
    label='design-'+generation;source=box.private/'attach-answer.txt';text='Use this reviewed design as the cold-read prerequisite.';source.write_text(text)
    decision={'id':label,'scope':'plan:'+label,'quote':text,'source':str(source),'source_sha256':digest(source.read_bytes())}
    caller=case.caller(parent['workflow']);case.ok(case.run_helper('job_cli.py','decision',job_id,{'caller':caller,'decision':decision}))
    case.ok(case.run_helper('job_cli.py','plan-revision',job_id,{'caller':caller,'new_plan':{'stages':parent['stages']},
        'revision':{'id':label,'owner_decision_id':label}}))
