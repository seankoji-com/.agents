"""Real ape report/job acceptance; only host executions are synthetic."""
from copy import deepcopy
import json
from pathlib import Path
import sys

from core.jobs.store import canonical, digest
from shared import model_selection as models, planning_review as planning
from tests.upfront_fixtures import approved_selection
from tests.model_selection_fixtures import selection_input, replacement
from tests.test_rebuild_installed import Sandbox, ROOT, worker_result
from tests.test_ape_validate_report import (CRITERIA, pin_source, fingerprint, descriptor,
    research_markdown, research_findings, synthesis_markdown, synthesis_findings, write_pin, receipts_for)


class ApePlanFixture:
    serial = 0

    def __init__(self, box, package, manifest, *, op='study', installed=False, direct=False,
                 adopt=True, synth_author=False, panel=False, coordinator_spare=False, direct_work=False):
        type(self).serial += 1
        self.box, self.package, self.manifest = box, package, manifest
        self.id = 'ape-' + str(self.serial)
        self.base = box.private / self.id
        self.base.mkdir()
        self.scripts = (package if installed else ROOT / 'plugins/ape') / 'scripts'
        self.op, self.direct_mode, self.direct_work = op, direct, direct_work
        self.job_id = self.id + '-research'
        self.review_id = self.id + '-review'
        self.job_file = box.jobs / self.job_id / 'job.json'
        self.request = self.base / 'request.txt'
        self.request.write_text('Compare pinned sources and recommend the smallest safe experiment or no adoption.')
        self.reference = 'fixture:request:' + self.id
        self.output_name = self.id + '/final-report.md'
        self.scope = planning.logical_output_id(self.reference, self.output_name)
        self.selection_data = json.loads(json.dumps(selection_input()).replace('alpha-work','gpt-fixture').replace(
            'beta-review','claude-fixture').replace('gamma-spare','gemini-fixture').replace(
            '"alpha"','"openai"').replace('"beta"','"anthropic"').replace('"gamma"','"google"'))
        d = self.selection_data
        d.update(scope_id=self.scope, operation='ape/' + op, invocation_id=self.id)
        d['coordinator']['lineage'] = 'openai'
        if coordinator_spare:
            target=deepcopy(d['profiles']['models'][2]['target'])
            d['coordinator']={**target,'lineage':'google','observed_options':target['options']}
        self.final_rid = 'R-SRC' if op == 'study' else 'R-SYNTH'
        d['review_panel'][0].update(independent=False, coverage=[self.final_rid, 'D1'])
        if op == 'forage':
            d['work']['judgement'] = deepcopy(d['work']['workhorse'])
            if synth_author:
                d['work']['judgement'] = deepcopy(d['review_panel'][0]['target'])
        if direct:
            row = replacement(d, d['coordinator'], review=True)
            row.pop('target'); row['execution'] = 'self-review'
            d['review_replacements'].append(row)
        if panel:
            extra = deepcopy(d['review_panel'][0]);extra['slot_id'] = 'second'
            extra['target'] = deepcopy(d['profiles']['models'][2]['target'])
            d['review_panel'].append(extra)
        if direct_work:
            assert op=='study'
            d['work']['workhorse']['execution']='current-context'
        self.selection = approved_selection(d)
        self.admission_input = {'operation': op, 'request_reference': self.reference,
            'output_name': self.output_name, 'invocation_id': self.id,
            'selection': self.selection, 'selection_sha256': self.selection['selection_sha256']}
        self.admission = self.ape('admit', self.admission_input)
        self.source = pin_source(self.base, 'src-1')
        self.finger = fingerprint(self.base)
        self.project = self.base / 'project'
        self.project.mkdir()
        box.run(['git', 'init', '-q', self.project])
        box.run(['git','-C',self.project,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'commit','-qm','fixture','--allow-empty'])
        self.local = self.project / 'source.py';self.local.write_text('VALUE = 1\n')
        self.stages, self.tasks = [], []
        self.add_stage('research','R-SRC','ape/source-researcher')
        if op == 'forage':
            self.add_stage('synthesis','R-SYNTH','ape/synthesizer',['research'])
        if direct_work:
            self.tasks=[]
            self.stages[0].update(execution_mode='direct',selection_binding={
                'role':'workhorse','selection_sha256':self.selection['selection_sha256']})
        self.final_stage = self.stages[-1]['id']
        self.caller = box.caller(manifest,'ape/' + op)
        self.job = {'schema_version':1,'job_id':self.job_id,'installation_id':manifest['installation_id'],
            'workflow':'ape/' + op,'owner':'fixture-owner','objective':'Pinned research with final review',
            'requirements': {'R-SRC':'Compare pinned source', **({'R-SYNTH':'Compare accepted reports'} if op=='forage' else {})},
            'authorization':{'actions':['read']},'constraints':['No source execution, experiment or target writes.'],
            'dependencies':[{'key':'ape','plugin':'ape'}], 'stages':self.stages,'tasks':self.tasks,
            'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'decisions':[],
            'history':[],'metrics':{},'result_contract':{'schema_version':1},
            'ape_admission':self.admission,'model_selection':self.selection,
            'model_selection_sha256':self.selection['selection_sha256'],'invocation_id':self.id,'scope_id':self.scope}
        self.adopt = adopt
        self.metadata = self.base / 'report-metadata.json'
        self.snapshot = None

    def add_stage(self, sid, rid, worker, dependencies=()):
        path = self.box.jobs / self.job_id / 'artifacts/tasks' / sid / 'report.md'
        self.stages.append({'id':sid,'depends_on':list(dependencies),'requirements':[rid],'status':'pending',
            'validator_dependency':'ape','revision':self.source['revision'],'criteria':deepcopy(CRITERIA),
            'validator_contract':{'sources':[self.source]},'outputs':[str(path)]})
        role = 'judgement' if worker=='ape/synthesizer' else 'workhorse'
        self.tasks.append({'task_id':sid,'stage_id':sid,'logical_slot_id':'primary','request_id':self.id+'-'+sid,
            'worker_id':worker,'dependency_key':'ape','status':'pending','role':'worker',
            'write_scope':{'mode':'worker-evidence','path':'artifacts/tasks/'+sid},
            'target':self.selection['work'][role], 'selection_binding':{
                'selection_sha256':self.selection['selection_sha256'],'role':role}})

    def ape(self, command, data, ok=True):
        proc = self.box.run([sys.executable,self.scripts/'plan_review.py',command,'--input',self.box.payload(data)],check=False)
        if proc.returncode != (0 if ok else 2):
            raise AssertionError(proc.stdout+proc.stderr)
        return json.loads(proc.stdout) if ok else proc.stderr

    def create_work(self, ok=True, job=None):
        runtime=ROOT if self.scripts==ROOT/'plugins/ape/scripts' else self.package
        proc=self.box.job(runtime,'create',self.job_id,job or self.job,check=False,
            extra=('--prefix',self.box.prefix,'--agents-root',self.box.agents))
        if proc.returncode != (0 if ok else 2):raise AssertionError(proc.stdout+proc.stderr)
        return json.loads(proc.stdout) if ok else proc.stderr

    def work(self):
        if self.direct_work:
            return self.work_direct()
        self.create_work()
        consumed=[]
        for stage in self.stages:
            sid=stage['id']
            brief=self.box.dispatch(self.package,self.job_id,self.caller,sid,'host-'+self.id+sid)
            path=Path(stage['outputs'][0]);path.parent.mkdir(parents=True,exist_ok=True)
            if sid=='research':
                path.write_text(research_markdown(self.source,self.adopt))
                findings=research_findings(self.source,self.adopt)
                op='study' if self.op=='study' else 'forage-research'
            else:
                path.write_text(synthesis_markdown([self.source],consumed))
                findings=synthesis_findings([self.source],consumed)
                op='forage-synthesis'
                if not self.adopt:
                    text=path.read_text()
                    import re
                    text=re.sub(r'(## Conflicts\n).*?(## Rejected)',r'\1\nNone.\n\n## Recommended experiment\n\nNone.\n\n\2',text,flags=re.S)
                    path.write_text(text); findings=[r for r in findings if r['section']=='Overlap']
            target=brief['target']
            self.box.job(self.package,'task-observation',self.job_id,{'caller':self.caller,'task_id':sid,'event':{
                'kind':'completion','completion_id':'host-'+self.id+sid+'-done','request_id':brief['request_id'],'host_task_id':'host-'+self.id+sid,
                'status_identity':{k:target[k] for k in ('providerInstanceId','model','options')},
                'status':'completed','work_state':'result_available','has_pending_child_runs':False}})
            result=json.loads(worker_result(brief));result['artifacts']=[{
                'path':'artifacts/tasks/'+sid+'/report.md','sha256':digest(path.read_bytes()),'bytes':len(path.read_bytes())}]
            self.box.complete(self.package,self.job_id,self.caller,sid,brief,'host-'+self.id+sid,json.dumps(result))
            report={'path':str(path),'sha256':digest(path.read_bytes())}
            self.descriptor=descriptor(op,[self.source],[{'id':stage['requirements'][0],'source_ids':['src-1']}],
                self.finger,report,findings,consumed if sid=='synthesis' else None)
            if self.op=='forage' and sid=='research':
                self.accept()
                consumed=[{'id':'accepted-research','source_id':'src-1',**report}]
        self.inputs={'requests':[{'path':str(self.request),'reference':self.reference,'clauses':[
            {'start':0,'end':len(self.request.read_text()),'requirement':self.final_rid}]}],
            'decisions':[], 'requirements':{self.final_rid:self.job['requirements'][self.final_rid]},
            'load_bearing_decisions':['D1'],'repository_root':str(self.project),'evidence_paths':[str(self.local)]}

    def work_direct(self):
        self.create_work()
        capabilities=deepcopy(self.selection['capabilities'])
        capabilities.update(parentThreadId='fixture-direct-coordinator',
            inheritedProviderInstanceId=self.selection['coordinator']['providerInstanceId'],
            inheritedModel=self.selection['coordinator']['model'], inheritedOptions=self.selection['coordinator'].get('observed_options', {}))
        self.box.job(self.package,'direct-execution',self.job_id,{'caller':self.caller,'stage_id':'research'},
                     extra=('--capabilities',self.box.payload(capabilities)))
        path=Path(self.stages[0]['outputs'][0]);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(research_markdown(self.source,self.adopt))
        self.descriptor=descriptor('study',[self.source],[{'id':'R-SRC','source_ids':['src-1']}],self.finger,
            {'path':str(path),'sha256':digest(path.read_bytes())},research_findings(self.source,self.adopt))
        self.inputs={'requests':[{'path':str(self.request),'reference':self.reference,'clauses':[
            {'start':0,'end':len(self.request.read_text()),'requirement':self.final_rid}]}],
            'decisions':[],'requirements':{self.final_rid:self.job['requirements'][self.final_rid]},
            'load_bearing_decisions':['D1'],'repository_root':str(self.project),'evidence_paths':[str(self.local)]}

    def prepare(self):
        out=self.ape('prepare',{'descriptor':self.descriptor,'inputs':self.inputs,
            'job_file':str(self.job_file),'stage_id':self.final_stage,'metadata_file':str(self.metadata)})
        self.snapshot=out['snapshot'];return out

    def review(self, command, data=None, ok=True):
        payload=dict(data or {})
        if command not in ('create','validate'):payload.setdefault('caller',self.review_caller)
        runtime=ROOT if self.scripts==ROOT/'plugins/ape/scripts' else self.package
        args=[sys.executable,runtime/'shared/planning_review_cli.py',command,'--input',self.box.payload(payload),
            '--state-root',self.box.jobs,'--job',self.review_id]
        if command=='create':args+=['--prefix',self.box.prefix,'--agents-root',self.box.agents]
        proc=self.box.run(args,check=False)
        if proc.returncode != (0 if ok else 2):raise AssertionError(proc.stdout+proc.stderr)
        return json.loads(proc.stdout) if ok else proc.stderr

    def begin_review(self):
        if self.snapshot is None:self.prepare()
        made=self.review('create',{'job_id':self.review_id,'installation_id':self.manifest['installation_id'],
            'plugin':'ape','project_id':self.selection['project_id'],'owner':'fixture-owner','invocation_id':self.id,
            'scope_id':self.scope,'selection':self.selection,'snapshot':self.snapshot})
        self.review_caller=made['caller'];self.review('begin')
        return made

    def assessment(self):
        return {'coverage':[{'id':r,'outcome':'supported','evidence':'fixture:source-counterexample-recovery'}
            for r in [self.final_rid,'D1']],'inspected_paths':self.snapshot['declared_paths'],'responses':[]}

    def review_pass(self, slot='review', adverse=False, malformed=False, direct=None):
        direct=self.direct_mode if direct is None else direct
        a=self.review('launch',{'slot_id':slot,'request_id':self.review_id+'-'+slot})
        if direct:
            self.review('unavailable',{'task_id':a['task_id'],'failure':{'kind':'technical','tool':'fixture-delegate',
                'call_id':'fixture-call','request_id':a['request_id'],'receipt':{'error':'fixture prelaunch failure'},'prelaunch':True}})
            return self.review('direct',{'observation':{'schema_version':1,'kind':'planning-direct','pass_id':self.review_id+'-self',
                'identity':{k:self.selection['coordinator'][k] for k in ('providerInstanceId','model','observed_options')},
                'identity_reference':'fixture:actual-session','snapshot_sha256':self.snapshot['sha256'],
                'selection_sha256':self.selection['selection_sha256'],'review_verdict':'approve','findings':[],
                'requirements':[{'id':self.final_rid,'status':'passed','evidence':'fixture:self-check'}],
                'assessment':self.assessment()}})
        self.review('host-event',{'task_id':a['task_id'],'event':{'kind':'accepted','request_id':a['request_id'],
            'host_task_id':'host-'+a['request_id'],'child_thread_id':'child-'+a['request_id'],'status':'completed',
            'work_state':'result_available','has_pending_child_runs':False,
            'status_identity':{k:a['target'][k] for k in ('providerInstanceId','model','options')}}})
        brief=json.loads(Path(a['path']).read_text());r=json.loads(worker_result(brief))
        r['review_verdict']='adverse' if adverse else 'approve';r['planning_review']=self.assessment()
        if adverse:r['findings']=[{'id':'F1','severity':'major','scenario':'No abandon condition.',
            'source_evidence':'fixture:report','smallest_correction':'State an abandon condition.'}]
        if malformed:r['planning_review']['coverage']=[]
        return self.review('result',{'task_id':a['task_id'],'result_file':str(self.box.payload(r)),
            'completion_id':'done-'+a['request_id']})

    def finish(self, attach=True):
        out=self.review('finish');self.receipt=out['reference']
        if attach:
            out=self.ape('attach',{'descriptor':self.descriptor,'metadata_file':str(self.metadata),'receipt':self.receipt['path']})
            self.descriptor['planning_review']=out['metadata']
        return out

    def approve(self):
        self.begin_review();self.review_pass();self.finish()

    def accept(self, ok=True):
        sid='research' if self.descriptor['operation']=='forage-research' else self.final_stage
        obs=self.box.publish(self.package,self.job_id,self.caller,sid,self.descriptor)
        proc=self.box.accept(self.package,'accept-stage',self.job_id,{'caller':self.caller,'stage_id':sid,
            'validator_argv':[str(self.package/'scripts/validate_report.py'),'--input',obs],'input_file':obs,
            'revision':self.source['revision']})
        if ok and (proc.returncode or not json.loads(proc.stdout).get('accepted')):raise AssertionError(proc.stdout+proc.stderr)
        if not ok and proc.returncode==0 and json.loads(proc.stdout).get('accepted'):raise AssertionError('unexpected acceptance')
        return proc

    def validate_final(self):
        job=self.box.state_of(self.job_id)
        observations={s['id']:s['observation_ref']['path'] for s in job['stages']}
        proc=self.box.accept(self.package,'validate-final',self.job_id,{'caller':self.caller,
            'validator_argv_by_stage':{s:[str(self.package/'scripts/validate_report.py'),'--input',p]
                                      for s,p in observations.items()},'input_file_by_stage':observations})
        if proc.returncode or not json.loads(proc.stdout).get('accepted'):raise AssertionError(proc.stdout+proc.stderr)

    def validate_report(self, ok=True):
        proc=self.box.run([sys.executable,self.scripts/'validate_report.py','--input',self.box.payload(self.descriptor)],check=False)
        if proc.returncode!=(0 if ok else 1):raise AssertionError(proc.stdout+proc.stderr)
        return json.loads(proc.stdout)


def select_legacy_ape_fixture(job, base, state_root):
    """Give older follow-up/scope fixtures the same real upfront admission contract."""
    d=json.loads(json.dumps(selection_input()).replace('alpha-work','gpt-fixture').replace(
        'beta-review','claude-fixture').replace('gamma-spare','gemini-fixture').replace(
        '"alpha"','"openai"').replace('"beta"','"anthropic"').replace('"gamma"','"google"'))
    request=Path(base)/'source-request.txt';request.write_text('Compare pinned sources and report supported recommendations.')
    reference='fixture:request:'+job['job_id'];output=job['job_id']+'/report.md'
    op = 'ape/forage' if job['workflow'] == 'ape/forage' else 'ape/study'
    d.update(invocation_id=job['job_id'],operation=op,
             scope_id=planning.logical_output_id(reference,output))
    d['coordinator']['lineage']='openai';d['review_panel'][0].update(independent=False,coverage=list(job['requirements']))
    if op=='ape/forage':
        d['work']['judgement'] = deepcopy(d['work']['workhorse'])
    if any(s.get('execution_mode')=='direct' and
           not any(t['stage_id']==s['id'] for t in job['tasks']) for s in job['stages']):
        d['work']['judgement']={**deepcopy(d['work']['workhorse']), 'execution':'current-context',
                              'accept_actual_settings':True}
    selected=approved_selection(d)
    from shared.ape_planning import admit
    job.update(ape_admission=admit({'operation':op,'request_reference':reference,'output_name':output,
        'invocation_id':job['job_id'],'selection':selected,'selection_sha256':selected['selection_sha256']}),
        model_selection=selected,model_selection_sha256=selected['selection_sha256'],
        invocation_id=job['job_id'],scope_id=d['scope_id'])
    for task in job['tasks']:
        role='judgement' if task['worker_id']=='ape/synthesizer' else 'workhorse'
        task['target']=deepcopy(selected['work'][role]);task['selection_binding']={
            'role':role,'selection_sha256':selected['selection_sha256']}
        stage=next(s for s in job['stages'] if s['id']==task['stage_id'])
        stage.setdefault('outputs',[str(Path(state_root)/job['job_id']/'artifacts/tasks'/task['task_id']/'report.md')])
    for stage in job['stages']:
        if stage.get('execution_mode') == 'direct' and not any(t['stage_id']==stage['id'] for t in job['tasks']):
            stage['selection_binding']={'role':'judgement','selection_sha256':selected['selection_sha256']}
    return job


def review_legacy_ape_fixture(ins, job_id, stage_id, data):
    """Drive a real separate planning job for the preexisting research-job fixture."""
    from types import SimpleNamespace
    import subprocess
    job=json.loads((ins.state/job_id/'job.json').read_text())
    f=ApePlanFixture.__new__(ApePlanFixture)
    f.id=job_id;f.package=ins.version;f.manifest=ins.manifest;f.op=job['workflow'].split('/')[1]
    f.review_id=job_id+'-planning-'+str(len(list(ins.state.glob(job_id+'-planning-*')))+1)
    f.job_id=job_id;f.job_file=ins.state/job_id/'job.json'
    f.scripts=ins.version/'scripts';f.selection=job['model_selection'];f.final_stage=stage_id
    f.final_rid=job['stages'][-1]['requirements'][0];f.scope=job['scope_id'];f.snapshot=None;f.direct_mode=False
    f.base=ins.base;f.metadata=ins.base/(job_id+'-report-metadata.json');f.descriptor=data
    f.project=ins.base/'local-project';f.project.mkdir(exist_ok=True)
    if not (f.project/'.git').exists():
        subprocess.run(['git','init','-q',str(f.project)],check=True)
    request=ins.base/'source-request.txt'
    f.inputs={'requests':[{'path':str(request),'reference':job['ape_admission']['request_reference'],'clauses':[
        {'start':0,'end':len(request.read_text()),'requirement':f.final_rid}]}], 'decisions':[],
        'requirements':{r:job['requirements'][r] for r in next(s for s in job['stages'] if s['id']==stage_id)['requirements']},
        'load_bearing_decisions':[],'repository_root':str(f.project),'evidence_paths':[]}
    def run(argv,check=True):
        proc=subprocess.run([str(a) for a in argv],capture_output=True,text=True,env=ins.env,timeout=120)
        if check and proc.returncode:raise AssertionError(proc.stdout+proc.stderr)
        return proc
    f.box=SimpleNamespace(jobs=ins.state,prefix=ins.prefix,agents=ins.agents,payload=lambda d:ins.write('planning',d),run=run)
    f.assessment=lambda: {'coverage':[{'id':r,'outcome':'supported','evidence':'fixture:source-counterexample-recovery'}
        for r in f.inputs['requirements']],'inspected_paths':f.snapshot['declared_paths'],'responses':[]}
    f.prepare()
    if json.loads(f.metadata.read_text()).get('reference'):
        f.descriptor['planning_review'] = planning.file_descriptor(f.metadata)
        f.ape('validate', {'descriptor':f.descriptor})
        return f.descriptor
    f.approve()
    f.review('release')
    return f.descriptor
