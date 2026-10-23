"""IMPS public gates with real planning jobs; only host executions are synthetic."""
from copy import deepcopy
import json
from pathlib import Path
import sys

from shared import model_selection as models, planning_review as planning
from tests.upfront_fixtures import approved_selection
from tests.ape_plan_review_fixtures import ApePlanFixture
from tests.model_selection_fixtures import selection_input, replacement
from tests.test_rebuild_installed import ROOT


class ImpsPlanFixture(ApePlanFixture):
    serial = 0

    def __init__(self, box, package, manifest, *, op='audit', installed=True, direct=False,
                 stages=1, write=False, synthesis=False, code_review=False, work_backup=False):
        type(self).serial += 1
        self.box, self.package, self.manifest = box, package, manifest
        self.id = 'imps-' + str(self.serial); self.op = op; self.direct_mode = direct
        self.base = box.private / self.id; self.base.mkdir()
        self.runtime = package if installed else ROOT
        self.plugin = package if installed else ROOT / 'plugins/imps'
        self.review_id = self.id + '-planning'; self.final_rid = 'REQ-ONE'
        self.project = self.base / 'project'; self.project.mkdir()
        box.run(['git', 'init', '-q', self.project])
        box.run(['git', '-C', self.project, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'fixture', '--allow-empty'])
        self.local = self.project / 'source.py'; self.local.write_text('VALUE = 1\n')
        self.request = self.base / 'request.txt'; self.request.write_text('Assess the requested outcome with evidence and safe recovery.')
        self.reference = 'fixture:request:' + self.id; self.output_name = self.id + '/output'
        self.scope = planning.logical_output_id(self.reference, self.output_name)
        d = json.loads(json.dumps(selection_input()).replace('alpha-work','gpt-fixture').replace(
            'beta-review','claude-fixture').replace('gamma-spare','gemini-fixture').replace(
            '"alpha"','"openai"').replace('"beta"','"anthropic"').replace('"gamma"','"google"'))
        self.selection_data = d
        d.update(scope_id=self.scope, invocation_id=self.id, operation='imps/' + op)
        d['coordinator']['lineage'] = 'openai'; d['work']['judgement'] = deepcopy(d['work']['workhorse'])
        d['review_panel'][0].update(independent=code_review, coverage=['REQ-ONE', 'D1'])
        if work_backup:
            d['work_replacements'].append(replacement(d, deepcopy(d['review_panel'][0]['target'])))
        if direct:
            row = replacement(d, d['coordinator'], review=True); row.pop('target'); row['execution'] = 'self-review'
            d['review_replacements'].append(row)
        self.selection = approved_selection(d)
        self.admission_input = {'operation':op, 'request_reference':self.reference, 'output_name':self.output_name,
            'invocation_id':self.id, 'selection':self.selection, 'selection_sha256':self.selection['selection_sha256']}
        self.admission = self.ape('admit', self.admission_input)
        self.metadata = self.base / 'review-metadata.json'; self.snapshot = None
        self.requirements = {'REQ-ONE':'Assess the requested outcome'}
        self.inputs = {'requests':[{'path':str(self.request), 'reference':self.reference, 'clauses':[
            {'start':0,'end':len(self.request.read_text()),'requirement':'REQ-ONE'}]}], 'decisions':[],
            'requirements':self.requirements, 'load_bearing_decisions':['D1'],
            'repository_root':str(self.project), 'evidence_paths':[str(self.local)]}
        self.plan = {'schema_version':2,'repo':{'worktree':str(self.project),'base_ref':'HEAD'},
            'brief':{'text':'Bounded fixture', 'requirements':[{'id':'REQ-ONE','text':self.requirements['REQ-ONE'],
                'kind':'inspection'}], 'constraints':['Local only.']},
            'host':{'kind':'t3','parent_thread_id':'fixture-parent'},
            'authorization':{'endstate':'local','local':['edit'] if write else ['read'],'remote':[]},
            'policy':{'checks':[], 'review':{'required':code_review}}}
        self.stages = [{'id':'stage-' + str(i), 'actions':['write'] if write else ['read'],
                        'output_type':'synthesis' if synthesis else 'inspection'} for i in range(stages)]
        self.answer = self.base / 'answer.md'
        if op in ('audit','investigation','blast-radius'):
            self.context = {'admission':self.admission, 'output_path':str(self.answer)}
            self.answer.write_text('No confirmed findings. No change recommended. Coverage: requested source and recovery paths.\n')
            self.descriptor = {'kind':'synthesis','admission':self.admission,
                'document':planning.file_descriptor(self.answer),'requirements':self.requirements}
        elif op=='verification-init':
            self.facts = json.loads((ROOT / 'tests/fixtures/schemas/valid/recipe-facts--basic.json').read_text())
            self.facts_file = self.base / 'facts.json'; self.facts_file.write_text(json.dumps(self.facts))
            self.descriptor = {'kind':'verification-recipe','admission':self.admission,
                'document':planning.file_descriptor(self.facts_file),'requirements':self.requirements}
            made = self.gate('recipe-scaffold', self.facts, extra=('--repo', self.project))['data']
            self.recipe_file = made['recipe']
            self.context = {'admission':self.admission,'recipe':self.descriptor,'recipe_file':self.recipe_file}
        else:
            self.descriptor = {'kind':'initial-plan','admission':self.admission,'plan':self.plan,'stages':self.stages}
            self.context = {'admission':self.admission,'stages':self.stages}
        self.gates = self.base / 'gates'; self.run_id = None

    def ape(self, command, data, ok=True):
        p = self.box.run([sys.executable,self.plugin/'cli.py','plan-review',command,'--input',self.box.payload(data)],check=False)
        if p.returncode != (0 if ok else 2): raise AssertionError(p.stdout+p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def gate(self, command, data=None, ok=True, extra=()):
        argv=[sys.executable,self.plugin/'cli.py',command,'--state-root',getattr(self,'gates',self.base/'gates'),*extra]
        if getattr(self,'run_id',None):argv+=['--run-id',self.run_id]
        if data is not None:argv+=['--input',self.box.payload(data)]
        p=self.box.run(argv,check=False)
        if ok and p.returncode:raise AssertionError(p.stdout+p.stderr)
        if not ok and not p.returncode:raise AssertionError('unexpected successful gate: '+p.stdout)
        return json.loads(p.stdout)

    def init(self, ok=True, context=None):
        out=self.gate('init',{**self.plan,'imps':context or self.context},ok=ok)
        if ok:self.run_id=out['run_id']
        return out

    def prepare(self):
        out=self.ape('prepare',{'descriptor':self.descriptor,'inputs':self.inputs,'metadata_file':str(self.metadata)})
        self.snapshot=out['snapshot'];self.descriptor=out['descriptor'];return out

    def review(self, command, data=None, ok=True):
        payload=dict(data or {})
        if command=='launch':payload['request_id']+=getattr(self,'round_request_suffix','')
        if command not in ('create','validate'):payload.setdefault('caller',self.review_caller)
        argv=[sys.executable,self.runtime/'shared/planning_review_cli.py',command,'--input',self.box.payload(payload),
            '--state-root',self.box.jobs,'--job',self.review_id]
        if command=='create':argv+=['--prefix',self.box.prefix,'--agents-root',self.box.agents]
        p=self.box.run(argv,check=False)
        if p.returncode!=(0 if ok else 2):raise AssertionError(p.stdout+p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def begin_review(self):
        if self.snapshot is None:self.prepare()
        made=self.review('create',{'job_id':self.review_id,'installation_id':self.manifest['installation_id'],
            'plugin':'imps','project_id':self.selection['project_id'],'owner':'fixture-owner',
            'invocation_id':self.id,'scope_id':self.scope,'selection':self.selection,'snapshot':self.snapshot})
        self.review_caller=made['caller'];self.review('begin');return made

    def finish(self, attach=True):
        out=super().finish(attach)
        if attach:
            if self.op=='verification-init':self.context['recipe']=self.descriptor
            elif self.op not in ('audit','investigation','blast-radius'):
                self.context['planning_review']=self.descriptor['planning_review']
        return out

    def evidence(self):
        binding=self.gate('snapshot')['data']
        return self.gate('evidence',{'binding':binding,'requirement_id':'REQ-ONE','kind':'inspection','status':'passed',
            'explanation':'Inspected actual fixture source.', 'artifacts':[str(self.local)]})

    def finalize(self, ok=True):return self.gate('finalize',self.descriptor,ok=ok)

    def stage_validate(self, ok=True):
        p=self.box.run([sys.executable,self.package/'scripts/validate_stage.py','--state-root',self.gates,
                        '--run-id',self.run_id],check=False)
        if p.returncode!=(0 if ok else 1):raise AssertionError(p.stdout+p.stderr)
        return json.loads(p.stdout)


def legacy_box(base, package, manifest, env):
    """Separate scratch state using an existing scratch installation."""
    from tests.test_rebuild_installed import Sandbox
    box=Sandbox(Path(base))
    box.prefix=Path(package).parents[1]
    box.agents=Path(manifest['bundle_dir']).parents[3]
    box.env=dict(env)
    return box


def configure_plan_fixture(f, plan, stages):
    f.plan=deepcopy(plan);f.project=Path(plan['repo']['worktree'])
    f.requirements={r['id']:r['text'] for r in plan['brief']['requirements']}
    f.final_rid=next(iter(f.requirements))
    f.stages=deepcopy(stages)
    f.inputs.update(requirements=f.requirements,repository_root=str(f.project),evidence_paths=[])
    f.inputs['requests'][0]['clauses'][0]['requirement']=f.final_rid
    f.descriptor={'kind':'initial-plan','admission':f.admission,'plan':f.plan,'stages':f.stages}
    f.context={'admission':f.admission,'stages':f.stages}
    f.assessment=lambda: {'coverage':[{'id':rid,'outcome':'supported','evidence':'fixture:exact-plan-failure-recovery'}
        for rid in [*f.requirements,'D1']], 'inspected_paths':f.snapshot['declared_paths'],'responses':[]}
    return f


def admitted_gate(case, package, manifest, env, plan, stages=None):
    """Initialize through public admission before the old fixture performs any work."""
    box=legacy_box(case.tmp/('gate-review-'+str(ImpsPlanFixture.serial)),package,manifest,env)
    f=ImpsPlanFixture(box,package,manifest,op='run')
    stages=stages or [{'id':'execution','actions':['write'],'output_type':'implementation'}]
    configure_plan_fixture(f,plan,stages);f.gates=case.state_root
    f.approve();f.init()
    from tests.support import Run
    return Run(case,case.state_root,f.run_id)


def select_legacy_imps_job(job, base, package, manifest, env, return_fixture=False):
    """Review the actual authored whole-job plan before generic lifecycle fixtures."""
    from shared.imps_planning import job_contract
    box=legacy_box(Path(base)/('job-review-'+job['job_id']),package,manifest,env)
    f=ImpsPlanFixture(box,package,manifest,op='run')
    d=deepcopy(f.selection_data)
    d['work']['judgement']['execution']='current-context'
    d['work']['judgement']['accept_actual_settings']=True
    d['review_panel'][0]['coverage']=[*job['requirements'],'D1']
    f.selection=approved_selection(d)
    f.admission_input.update(selection=f.selection,selection_sha256=f.selection['selection_sha256'])
    f.admission=f.ape('admit',f.admission_input)
    job['policy'].update(model_selection_required=True,imps_planning_required=True)
    job.update(imps_admission=f.admission,model_selection=f.selection,
        model_selection_sha256=f.selection['selection_sha256'],invocation_id=f.id,scope_id=f.scope)
    for t in job['tasks']:
        t['target']=deepcopy(f.selection['work']['workhorse'])
        t['selection_binding']={'role':'workhorse','selection_sha256':f.selection['selection_sha256']}
    for s in job['stages']:
        if s.get('execution_mode')=='direct' and not any(t['stage_id']==s['id'] for t in job['tasks']):
            s['selection_binding']={'role':'judgement','selection_sha256':f.selection['selection_sha256']}
    writable=any(a!='read' for a in job['authorization'].get('actions',[]))
    plan=deepcopy(f.plan);plan['authorization']['local']=['edit'] if writable else ['read']
    plan['brief']['requirements']=[{'id':rid,'text':text,'kind':'inspection'} for rid,text in job['requirements'].items()]
    plan['brief']['constraints']=job['constraints']
    stages=[{'id':s['id'],'actions':['write'] if writable else ['read'],'output_type':'implementation' if writable else 'inspection'}
            for s in job['stages']]
    configure_plan_fixture(f,plan,stages)
    f.descriptor['job_contract']=job_contract(job)
    if writable or len(stages)>1:f.approve()
    job['imps_initial_plan']=f.descriptor
    return (job, f) if return_fixture else job
