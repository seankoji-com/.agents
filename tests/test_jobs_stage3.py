import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from core.jobs.store import Store,JobError,validate,canonical
def fixture_decision(store, caller, value):
    from core.jobs import decision as actual_decision
    from core.jobs.store import digest
    source = store.root / ('owner-source-' + digest(str(value.get('id')).encode()) + '.txt')
    source.write_text(value.get('quote', '') + '\n')
    value = {**value, 'source': str(source), 'source_sha256': digest(source.read_bytes())}
    return actual_decision(store, caller, value)

class JobStateTests(unittest.TestCase):
 def test_document_only_brief_omits_job_and_predecessor_context(self):
  import hashlib
  from core.jobs import create_job,prepare
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);document=root/'document.md';document.write_text('# Evaluate only this document\n')
   job=self.base();job.update(objective='private-objective-marker',snapshot={'private_context':'private-snapshot-marker'},result_contract={'schema_version':1})
   job['stages'][0]['outputs']=['private-output-marker'];job['requirements']['R1']='private-requirement-marker'
   job['tasks'][0].update(context_policy='document-only',document={'path':str(document),'sha256':hashlib.sha256(document.read_bytes()).hexdigest()})
   pin={'package_digest':'c'*64,'bundle_digest':'b'*64,'task_contract':None,'effective_workers':{'imps/stage-executor':{'bytes':'procedural definition only','sha256':'a'*64}},'limits':{}}
   create_job(job,root/'state',{'imps':pin});store=Store(root/'state','job-1');caller={'actor':'coordinator','installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64}
   prepared=prepare(store,caller,'t0',lambda dep,saved:saved==pin,lambda stage:False)
   text=Path(prepared['path']).read_text();brief=json.loads(text)
   for marker in ('private-objective-marker','private-snapshot-marker','private-output-marker','private-requirement-marker'):self.assertNotIn(marker,text)
   self.assertEqual(brief['document'],job['tasks'][0]['document']);self.assertEqual(brief['requirements'],[{'id':'R1'}])
 def test_document_only_context_files_are_exact_declared_read_only_inputs(self):
  import hashlib
  from core.jobs import create_job,prepare
  digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);document=root/'document.md';document.write_text('# Evaluate this document and its files\n')
   image=root/'capture.png';image.write_bytes(b'\x89PNG fixture');notes=root/'notes.txt';notes.write_text('notes\n')
   files=[{'path':str(image),'sha256':digest(image)},{'path':str(notes),'sha256':digest(notes)}]
   pin={'package_digest':'c'*64,'bundle_digest':'b'*64,'task_contract':None,'effective_workers':{'imps/stage-executor':{'bytes':'procedural definition only','sha256':'a'*64}},'limits':{}}
   caller={'actor':'coordinator','installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64}
   def job_with(name,**task):
    job=self.base();job['job_id']=name;job['tasks'][0].update(task);create_job(job,root/'state',{'imps':pin});return Store(root/'state',name)
   store=job_with('job-files',context_policy='document-only',document={'path':str(document),'sha256':digest(document)},context_files=files)
   brief=json.loads(Path(prepare(store,caller,'t0',lambda dep,saved:saved==pin,lambda stage:False)['path']).read_text())
   self.assertEqual((brief['context_files'],brief['authorization']['read']),(files,[str(document),str(image),str(notes)]))
   from core import schema
   brief_schema=schema.load_schema_file(ROOT/'shared/agents/worker-brief.schema.json')
   self.assertEqual(schema.errors(brief,brief_schema),[])
   duplicated={**brief,'context_files':files+[dict(files[0])]}
   self.assertTrue(any('unique' in error.lower() for error in schema.errors(duplicated,brief_schema)))
   self.assertIn('declared context files',brief['constraints'][0])
   # A changed file, an undeclared kind of task or a relative path never widens the read scope.
   notes.write_text('changed\n')
   store=job_with('job-changed',context_policy='document-only',document={'path':str(document),'sha256':digest(document)},context_files=files)
   with self.assertRaisesRegex(JobError,'context file bytes differ'):prepare(store,caller,'t0',lambda dep,saved:saved==pin,lambda stage:False)
   store=job_with('job-whole',context_files=[{'path':str(image),'sha256':digest(image)}])
   with self.assertRaisesRegex(JobError,'belong only to a document-only task'):prepare(store,caller,'t0',lambda dep,saved:saved==pin,lambda stage:False)
   store=job_with('job-relative',context_policy='document-only',document={'path':str(document),'sha256':digest(document)},context_files=[{'path':'capture.png','sha256':digest(image)}])
   with self.assertRaisesRegex(JobError,'context file bytes differ'):prepare(store,caller,'t0',lambda dep,saved:saved==pin,lambda stage:False)
 def test_an_added_slot_keeps_unchanged_executed_siblings_and_stales_stage_acceptance_and_successors(self):
  from core.jobs import revise_plan
  with tempfile.TemporaryDirectory() as d:
   s=Store(d,'job-1');j=self.base()
   executed={'status':'awaiting-acceptance','attempt':1,'cycle':0,'execution_history':[{'request_id':'req0','completion_id':'c0'}]}
   j['tasks'][0].update(executed,target={'providerInstanceId':'p','model':'m'})
   j['tasks'].append(dict(j['tasks'][0],task_id='t1',stage_id='s1',logical_slot_id='primary',request_id='req1',execution_history=[{'request_id':'req1','completion_id':'c1'}]))
   j['tasks'].append(dict(j['tasks'][0],task_id='live',logical_slot_id='live',request_id='req-live',status='running',attempt=0,execution_history=[],handles=[{'task_id':'host-live','request_id':'req-live','status':'running','work_state':'working','has_pending_child_runs':False}]))
   j['stages'][0].update(status='accepted-at-snapshot',acceptance={'sha256':'e'*64})
   s.create(j);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   def revise(rid,plan):
    fixture_decision(s,caller,{'id':'owner-'+rid,'quote':'approve '+rid,'source':'x','source_sha256':'d'*64,'scope':'plan:'+rid})
    revise_plan(s,caller,{'id':rid,'owner_decision_id':'owner-'+rid},plan)
    return s.load()
   before=s.load();tasks=before['tasks']+[{'task_id':'t2','stage_id':'s0','logical_slot_id':'second','request_id':'req2','worker_id':'imps/stage-executor','dependency_key':'imps'}]
   after=revise('add',{'tasks':tasks})
   by={t['task_id']:t for t in after['tasks']};stage={x['id']:x for x in after['stages']}
   self.assertEqual((stage['s0']['status'],stage['s0']['acceptance']),('stale',None))
   for kept in ('t0','live'):
    self.assertEqual({k:v for k,v in by[kept].items() if k!='cycle'},{k:v for k,v in next(t for t in before['tasks'] if t['task_id']==kept).items() if k!='cycle'})
    self.assertNotIn('inputs_stale',by[kept])
   self.assertEqual((by['t1']['inputs_stale'],by['t1']['status'],stage['s1']['status']),(True,'stale','stale'))  # successors stay stale
   self.assertEqual((by['t2']['inputs_stale'],by['t2']['attempt']),(True,0))  # a never-executed slot: fresh preparation clears it
   # A changed sibling contract, or an added slot beside a stage contract change, still stales the executed slot.
   changed=[dict(t) for t in after['tasks']];next(t for t in changed if t['task_id']=='t0')['target']={'providerInstanceId':'p','model':'other'}
   self.assertTrue(next(t for t in revise('retarget',{'tasks':changed})['tasks'] if t['task_id']=='t0')['inputs_stale'])
   s2=Store(Path(d)/'second','job-1');s2.create(j);s=s2
   stages=[dict(x) for x in j['stages']];stages[0]['resources']={'changed':True}
   both=revise('add-and-change',{'tasks':j['tasks']+[tasks[-1]],'stages':stages})
   self.assertTrue(next(t for t in both['tasks'] if t['task_id']=='t0')['inputs_stale'])
 def base(self):
  return {'schema_version':1,'job_id':'job-1','installation_id':'install-1','workflow':'imps/run','owner':'coordinator','objective':'x','requirements':{'R1':'keep evidence'},'authorization':{'actions':['edit']},'constraints':['no network'],'dependencies':[{'key':'imps','plugin':'imps'}],'pins':{'imps':{'package_digest':'c'*64}},'result_contract':{'schema_version':1},'policy':{'identity':'observed','max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':f's{i}','depends_on':[f's{i-1}'] if i else [],'requirements':['R1'],'status':'pending','attempts':{'primary':0,'support':0,'review':0,'final':0},'acceptance':None} for i in range(5)],'tasks':[{'task_id':'t0','stage_id':'s0','logical_slot_id':'primary','request_id':'req0','worker_id':'imps/stage-executor','dependency_key':'imps','status':'pending','attempt':0,'handles':[],'followups':[],'dispatch_retries':0,'dispatch_history':[]}],'decisions':[],'history':[],'metrics':{}}
 def test_five_stage_overview_and_restart(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d,'job-1');s.create(self.base());r=Store(d,'job-1');o=r.overview();self.assertEqual(len(o['stages']),5);self.assertEqual(o['requirement_coverage']['R1'][0]['stage'],'s0')
 def test_duplicate_cycle_unknown_slot_rejected(self):
  j=self.base();j['stages'][1]['id']='s0'
  with self.assertRaises(JobError):validate(j)
  j=self.base();j['stages'][0]['depends_on']=['s4']
  with self.assertRaises(JobError):validate(j)
  j=self.base();j['tasks'].append(dict(j['tasks'][0],task_id='t1',request_id='req1'))
  with self.assertRaises(JobError):validate(j)
 def test_plan_widening_requires_owner_evidence_and_preserves_old_plan(self):
  from core.jobs import revise_plan,decision
  with tempfile.TemporaryDirectory() as d:
   s=Store(d,'job-1');j=self.base();j['pins']={'imps':{'package_digest':'c'*64,'compatible_pinned_invocation':'agents --job /tmp/j path imps'}};s.create(j)
   caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'};new=dict(j);new['requirements']={'R1':'weakened'}
   with self.assertRaisesRegex(JobError,'undeclared_expansion'):
    revise_plan(s,caller,{'id':'rev-1'},new)
   fixture_decision(s,caller,{'id':'owner-1','quote':'approve revision','source':'operator decision','source_sha256':'d'*64,'scope':'plan:rev-1'})
   revise_plan(s,caller,{'id':'rev-1','owner_decision_id':'owner-1'},new)
   after=s.load();self.assertEqual(after['requirements']['R1'],'weakened');self.assertEqual(after['history'][-1]['requirements'],j['requirements'])
 def test_author_lineage_stage_contract_edits_require_owner_decisions(self):
  from core.jobs import revise_plan
  cases=(('add-independent',{}, {'independent_of_author':True}),
         ('remove-independent',{'independent_of_author':True},{}),
         ('change-independent',{'independent_of_author':True},{'independent_of_author':False}),
         ('add-waiver',{}, {'lineage_waiver':{'scope':'lineage-waiver:stage:s0'}}),
         ('remove-waiver',{'lineage_waiver':{'scope':'lineage-waiver:stage:s0'}},{}),
         ('change-waiver',{'lineage_waiver':{'scope':'lineage-waiver:stage:s0'}},
          {'lineage_waiver':{'scope':'lineage-waiver:stage:s0','binding':'changed'}}))
  for name,old_fields,new_fields in cases:
   with self.subTest(case=name), tempfile.TemporaryDirectory() as d:
    s=Store(d,'job-1');j=self.base();j['policy']['identity']='observed';j['stages'][0].update(old_fields)
    j['pins']={'imps':{'package_digest':'c'*64,'compatible_pinned_invocation':'agents --job /tmp/j path imps'}}
    s.create(j);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
    plan={k:json.loads(json.dumps(s.load()[k])) for k in ('requirements','dependencies','stages','tasks','constraints','authorization','policy')}
    stage=plan['stages'][0]
    for field in ('independent_of_author','lineage_waiver'):stage.pop(field,None)
    stage.update(new_fields)
    revision={'id':'lineage-'+name}
    with self.assertRaisesRegex(JobError,'undeclared_expansion'):
     revise_plan(s,caller,revision,plan)
    fixture_decision(s,caller,{'id':'owner-'+name,'quote':'owner approves '+name,
      'scope':'plan:'+revision['id'],'requirement_ids':[]})
    revise_plan(s,caller,{**revision,'owner_decision_id':'owner-'+name},plan)
    self.assertEqual(s.load()['stages'][0].get('independent_of_author'),new_fields.get('independent_of_author'))
    self.assertEqual(s.load()['stages'][0].get('lineage_waiver'),new_fields.get('lineage_waiver'))
 def test_strict_json_duplicate_and_nan(self):
  from core.jobs.store import strict_load
  for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
   with self.assertRaises(JobError):strict_load(raw)
 def test_mutation_lock_preserves_whole_job(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d,'job-1');s.create(self.base());c={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   j=s.load();j['pins']={'imps':{'package_digest':'c'*64,'compatible_pinned_invocation':'agents --job /tmp/job path imps'}};from core.jobs.store import _atomic;_atomic(s.file,canonical(j))
   s.mutate(c,lambda state:state['decisions'].append({'id':'d1'}));self.assertEqual(len(Store(d,'job-1').load()['decisions']),1)

 def test_caller_must_name_actor_explicitly(self):
  from core.jobs import decision
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};store=Store(d,'job-1');store.create(job)
   missing={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64}
   with self.assertRaisesRegex(JobError,'actor'):decision(store,missing,{'id':'d','quote':'approved','source':'owner','source_sha256':'d'*64,'scope':'test'})

 def test_concurrent_process_mutations_preserve_both_decisions(self):
  import subprocess,sys
  with tempfile.TemporaryDirectory() as d:
   store=Store(d,'job-1');job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};store.create(job)
   caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   code="import sys;from core.jobs.store import Store;from tests.test_jobs_stage3 import fixture_decision;s=Store(sys.argv[1],'job-1');fixture_decision(s,{'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'},{'id':sys.argv[2],'quote':'approved','source':'owner','source_sha256':'d'*64,'scope':'test'})"
   procs=[subprocess.Popen([sys.executable,'-c',code,d,f'd{i}']) for i in range(2)]
   self.assertEqual([p.wait() for p in procs],[0,0]);self.assertEqual({x['id'] for x in Store(d,'job-1').load()['decisions']},{'d0','d1'})
 def test_worker_cannot_use_coordinator_api_and_symlink_write_has_no_side_effect(self):
  from core.jobs import worker_write,decision
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};job['tasks'][0].update(dependency_key='imps',write_scope={'mode':'worker-evidence','path':'artifacts/tasks/t0'});store=Store(d,'job-1');store.create(job)
   worker={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'worker','task_id':'t0','stage_id':'s0','scope':job['tasks'][0]['write_scope']}
   with self.assertRaisesRegex(JobError,'coordinator-only'):decision(store,worker,{'id':'x','quote':'x','source':'x','source_sha256':'d'*64,'scope':'x'})
   foreign=Path(d)/'foreign';foreign.mkdir();(store.path/'artifacts').symlink_to(foreign,target_is_directory=True)
   with self.assertRaises((JobError,OSError)):worker_write(store,worker,'t0','artifacts/tasks/t0/new/file',b'x')
   self.assertFalse((foreign/'tasks').exists())
   (store.path/'artifacts').unlink();written=worker_write(store,worker,'t0','artifacts/tasks/t0/evidence.txt',b'owned evidence');self.assertEqual(Path(written['path']).read_bytes(),b'owned evidence')
 def test_followup_new_request_is_recorded_and_deduplicated(self):
  from core.jobs import record_dispatch, prepare
  from shared.job_coordinator import prepare_followup
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['pins']={'imps':{'package_digest':'c'*64,'effective_workers':{'imps/stage-executor':{'bytes':'fixture definition'}}}};store=Store(d,'job-1');store.create(job);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   prepare(store,caller,'t0',lambda dep,pin:True,lambda stage:True)
   accepted={'kind':'accepted','request_id':'req0','host_task_id':'host-0','status':'running','work_state':'working','has_pending_child_runs':False}
   with self.assertRaisesRegex(JobError,'host ID'):record_dispatch(store,caller,'t0',{**accepted,'host_task_id':''})
   record_dispatch(store,caller,'t0',accepted)
   with self.assertRaisesRegex(JobError,'terminal'):record_dispatch(store,caller,'t0',{'kind':'followup','request_id':'req-next','host_task_id':'child-1','parent_host_task_id':'host-0','target':None,'scope':None})
   with self.assertRaisesRegex(JobError,'missing status'):record_dispatch(store,caller,'t0',{'kind':'completion','request_id':'req0','host_task_id':'host-0','completion_id':'done-0'})
   with self.assertRaisesRegex(JobError,'owned original handle'):record_dispatch(store,caller,'t0',{'kind':'completion','request_id':'other-request','host_task_id':'host-0','completion_id':'wrong-request','status':'completed','work_state':'result_available','has_pending_child_runs':False})
   terminal={'kind':'completion','request_id':'req0','host_task_id':'host-0','completion_id':'done-0','status':'completed','work_state':'result_available','has_pending_child_runs':False}
   record_dispatch(store,caller,'t0',terminal);record_dispatch(store,caller,'t0',terminal)
   self.assertEqual(len(store.load()['notifications']),1)
   owned=store.load()['tasks'][0]['handles'][0];self.assertEqual((owned['status'],owned['work_state'],owned['has_pending_child_runs']),('completed','result_available',False))
   # R16-ST-01: the owned terminal result is read before a follow-up supersedes the current request.
   from core.jobs import record_result
   from tests.test_jobs_review import JobReviewTests
   brief=json.loads(Path(store.load()['tasks'][0]['brief']['path']).read_text());result=JobReviewTests().valid_result()
   for key in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256','revision'):result[key]=brief[key]
   result['binding']=brief['snapshot'];result['requirements']=[{'id':r['id'],'status':'passed','evidence':['fixture']} for r in brief['requirements']]
   record_result(store,caller,'t0',{'request_id':'req0','completion_id':'req0-done','result':json.dumps(result).encode()})
   with self.assertRaisesRegex(JobError,'identity, model or authority'):record_dispatch(store,caller,'t0',{'kind':'followup','request_id':'req-next','host_task_id':'child-bad','parent_host_task_id':'host-0','target':'other','scope':None})
   event={'kind':'followup','request_id':'req-next','host_task_id':'child-1','parent_host_task_id':'host-0','target':None,'scope':None}
   prepare_followup(store,caller,'t0','req-next')
   record_dispatch(store,caller,'t0',event);record_dispatch(store,caller,'t0',event)
   self.assertEqual(len(Store(d,'job-1').load()['tasks'][0]['followups']),1)

 def test_capacity_retry_requires_new_owned_notification_and_deduplicates_it(self):
  from core.jobs import record_dispatch
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['tasks'].append({'task_id':'t1','stage_id':'s0','logical_slot_id':'support','request_id':'req1','worker_id':'imps/stage-executor','dependency_key':'imps','status':'pending','attempt':0,'handles':[],'followups':[],'dispatch_retries':0,'dispatch_history':[]});job['pins']={'imps':{'package_digest':'c'*64}}
   store=Store(d,'job-1');store.create(job);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   record_dispatch(store,caller,'t0',{'kind':'accepted','request_id':'req0','host_task_id':'host-0','status':'running','work_state':'working','has_pending_child_runs':False})
   record_dispatch(store,caller,'t0',{'kind':'completion','request_id':'req0','host_task_id':'host-0','completion_id':'notice-0','status':'completed','work_state':'result_available','has_pending_child_runs':False})
   deferred={'kind':'capacity-deferred','request_id':'req1','completion_id':'notice-0'}
   record_dispatch(store,caller,'t1',deferred)
   with self.assertRaisesRegex(JobError,'new owned completion notification'):record_dispatch(store,caller,'t1',deferred)
   with self.assertRaisesRegex(JobError,'notification was not observed'):record_dispatch(store,caller,'t1',{**deferred,'completion_id':'invented'})
   self.assertEqual(store.load()['tasks'][1]['capacity_retry_events'],['notice-0'])

 def test_uncertain_dispatch_reuses_original_id_with_persistent_retry_ceiling(self):
  from core.jobs import record_dispatch
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};store=Store(d,'job-1');store.create(job);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   retry={'kind':'uncertain','request_id':'req0'}
   record_dispatch(store,caller,'t0',retry);record_dispatch(store,caller,'t0',retry);record_dispatch(store,caller,'t0',retry)
   with self.assertRaisesRegex(JobError,'original plus two retries exhausted'):record_dispatch(store,caller,'t0',retry)
   task=Store(d,'job-1').load()['tasks'][0];self.assertEqual(task['dispatch_retries'],2);self.assertEqual(task['dispatch_history'][0]['request_id'],'req0')
 def test_explicit_artifact_limit_above_default_is_preserved(self):
  from core.jobs import create_job
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['policy']['max_artifact_bytes']=32*1024*1024;job['pins']={}
   create_job(job,d,{'imps':{'package_digest':'c'*64}});self.assertEqual(Store(d,'job-1').load()['policy']['max_artifact_bytes'],32*1024*1024)

 def test_observed_identity_policy_cannot_be_removed_by_plan_revision(self):
  from core.jobs import revise_plan
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['policy']['identity']='observed';store=Store(d,'job-1');store.create(job)
   caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   changed=store.load();changed['policy']['identity']='legacy'
   with self.assertRaisesRegex(JobError,'identity policy is immutable'):
    revise_plan(store,caller,{'id':'remove-identity'},changed)

 def test_author_independence_policy_cannot_be_removed_in_core_plan_revision(self):
  from core.jobs import revise_plan
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['policy']['author_independence']=True;store=Store(d,'job-1');store.create(job)
   caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   changed=store.load();changed['policy']['author_independence']=False
   with self.assertRaisesRegex(JobError,'author independence policy is immutable'):
    revise_plan(store,caller,{'id':'remove-author-independence'},changed)

 def test_dependency_adoption_preserves_unchanged_pins_limits_and_owner_boundary(self):
  from core.jobs import revise_plan,decision
  from shared.job_coordinator import create_pinned_job,adopt_pins,verify_all_pins
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);home=base/'home';home.mkdir();prefix=base/'prefix';agents=base/'agents';state=base/'state';config=base/'config/workers.json';env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(base/'config'),'XDG_STATE_HOME':str(state)}
   manifests={}
   for plugin in ('imps','babysitter','agent-tuneup'):
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--plugin',plugin,'--prefix',str(prefix),'--agents-root',str(agents)],capture_output=True,text=True,env=env);self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr);manifests[plugin]=json.loads(proc.stdout)['data']
   override_rows=[]
   for plugin,worker_id in (('imps','imps/stage-executor'),('babysitter','babysitter/pr-maintainer')):
    manifest=json.loads((Path(manifests[plugin]['version_dir'])/'install-manifest.json').read_text())
    target=agents/'overrides'/(worker_id+'.md');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(f'---\nworker_id: {worker_id}\n---\nfixture owner enabled override\n')
    override_rows.append({'worker_id':worker_id,'base_bundle_digest':manifest['bundle_digest'],'path':worker_id+'.md','enabled':True})
   config.parent.mkdir(parents=True,exist_ok=True);config.write_text(json.dumps({'schema_version':1,'max_live_workers':2,'max_repair_cycles':3,'overrides':override_rows}))
   job=self.base();job['pins']={};job['dependencies']=[{'key':'imps','plugin':'imps'},{'key':'babysitter','plugin':'babysitter'}];job['policy']={'identity':'observed','max_repair_cycles':3,'max_artifact_bytes':32*1024*1024,'max_live_workers':2};job['stages'][0]['validator_dependency']='imps'
   from tests.imps_plan_review_fixtures import select_legacy_imps_job
   version=Path(manifests['imps']['version_dir']);manifest=json.loads((version/'install-manifest.json').read_text())
   select_legacy_imps_job(job,base,version,manifest,env)
   from unittest.mock import patch
   with patch.dict(os.environ,env):create_pinned_job(job,state,prefix,agents,config)
   store=Store(state,'job-1');original=store.load()['pins'];caller={'installation_id':store.load()['installation_id'],'workflow':'imps/run','package_digest':original['imps']['package_digest'],'actor':'coordinator'}
   self.assertEqual(original['imps']['effective_workers']['imps/stage-executor']['override_status'],'enabled')
   self.assertEqual(original['babysitter']['effective_workers']['babysitter/pr-maintainer']['override_status'],'enabled')
   import shutil
   for plugin in ('imps','babysitter'):
    plugin_root=prefix/plugin;current=plugin_root/'current';self.assertTrue(current.is_symlink())
    alternate=plugin_root/'alternate-current';shutil.copytree(current.resolve(),alternate)
    current.unlink();current.symlink_to(alternate.name,target_is_directory=True)
   verify_all_pins(store,caller)
   self.assertEqual(store.load()['pins'],original)
   verify_all_pins(store,caller)
   changed=store.load();changed['dependencies']=[*changed['dependencies'],{'key':'tuneup','plugin':'agent-tuneup'}]
   def adopter(current,deps):return adopt_pins(current,deps,state,prefix,agents,config)
   with self.assertRaisesRegex(JobError,'undeclared_expansion'):
    revise_plan(store,caller,{'id':'adopt-1'},changed,adopter)
   fixture_decision(store,caller,{'id':'owner-adopt','quote':'approve tuneup dependency','source':'fixture owner record','source_sha256':'9'*64,'scope':'plan:adopt-1'})
   revise_plan(store,caller,{'id':'adopt-1','owner_decision_id':'owner-adopt'},changed,adopter)
   after=Store(state,'job-1').load();self.assertEqual(after['pins']['imps'],original['imps']);self.assertEqual(after['pins']['babysitter'],original['babysitter']);self.assertEqual(after['policy'],job['policy'])
   # Resume verifies original exact pin bytes after both current pointers changed.
   verify_all_pins(Store(state,'job-1'),caller)
   self.assertEqual(Store(state,'job-1').load()['pins']['imps'],original['imps'])

 def test_limits_can_narrow_reorder_without_owner_approval_and_raise_requires_record(self):
  from core.jobs import revise_plan,decision
  with tempfile.TemporaryDirectory() as d:
   store=Store(d,'job-1');job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};job['policy']['max_artifact_bytes']=32*1024*1024;store.create(job);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   narrow=dict(job);narrow['stages']=list(reversed(job['stages']));narrow['policy']={**job['policy'],'max_artifact_bytes':1024};revise_plan(store,caller,{'id':'narrow'},narrow)
   raised=store.load();raised['policy']={**narrow['policy'],'max_artifact_bytes':64*1024*1024}
   with self.assertRaisesRegex(JobError,'undeclared_expansion'):revise_plan(store,caller,{'id':'raise'},raised)
   fixture_decision(store,caller,{'id':'raise-ok','quote':'raise artifact ceiling','source':'fixture owner record','source_sha256':'8'*64,'scope':'plan:raise'})
   revise_plan(store,caller,{'id':'raise','owner_decision_id':'raise-ok'},raised)
   self.assertEqual(Store(d,'job-1').load()['policy']['max_artifact_bytes'],64*1024*1024)

 def test_rehashed_receipt_and_edited_accepted_flag_still_require_current_validator(self):
  import hashlib
  from core.jobs.store import canonical,digest,_atomic
  from shared.job_acceptance import accept_stage,validate_stage
  from shared.job_coordinator import create_pinned_job,publish_observation
  from tests.test_rebuild_installed import Sandbox
  from tests.ape_plan_review_fixtures import ApePlanFixture
  with tempfile.TemporaryDirectory() as td:
   box=Sandbox(Path(td));version,manifest=box.install('ape')
   f=ApePlanFixture(box,version,manifest,installed=True);f.work();f.approve()
   receipt=json.loads(f.accept().stdout);state=box.jobs
   store=Store(state,f.job_id);job_now=store.load()
   job_now['stages'][0]['status']='accepted-at-snapshot';_atomic(store.file,canonical(job_now))
   from unittest.mock import patch
   with patch.dict(os.environ,box.env,clear=True):self.assertTrue(validate_stage(store,f.final_stage)['accepted'])
   path=Path(receipt['input_file']);path.write_text('{}')
   forged=dict(receipt);forged['accepted']=True;forged['receipt_sha256']=None;forged['receipt_sha256']=digest(canonical(forged))
   job_now=store.load();receipt_path=Path(job_now['stages'][0]['acceptance']['path']);_atomic(receipt_path,canonical(forged))
   job_now['stages'][0]['acceptance']['sha256']=forged['receipt_sha256'];_atomic(store.file,canonical(job_now))
   with patch.dict(os.environ,box.env,clear=True):verdict=validate_stage(store,f.final_stage)
   self.assertFalse(verdict['accepted'])
   self.assertTrue(any(word in verdict.get('reason','').lower() for word in ('input','validator','receipt')),verdict)

 def test_worker_result_denial_does_not_expand_scope_and_duplicate_completion_is_idempotent(self):
  from tests.support import CoreTestCase
  import json
  from core.jobs import record_result,worker_write
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};job['tasks'][0].update(dependency_key='imps',write_scope={'mode':'worker-evidence','path':'artifacts/tasks/t0'});store=Store(d,'job-1');store.create(job);coord={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'};worker={**coord,'actor':'worker','task_id':'t0','stage_id':'s0','scope':job['tasks'][0]['write_scope']}
   with self.assertRaises(JobError):worker_write(store,worker,'t0','artifacts/tasks/t1/out',b'bad')
   # The coordinator follows a denied worker write with public, freshly bound
   # check and requirement evidence; no worker authority or old binding is reused.
   case=CoreTestCase(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
   repo=case.make_repo();run=case.init(case.plan(repo));before=run.binding()
   (repo/'wordstat.py').write_text((repo/'wordstat.py').read_text()+'\n# coordinator fallback verification input\n')
   check=case.run_check(run);self.assertEqual(check['result']['status'],'passed',check)
   artifact=run.scratch('coordinator-fallback.log','fresh coordinator verification\n');run.evidence('REQ-MULTILINE',artifact)
   self.assertNotEqual(run.binding(),before);self.assertTrue(run.validate()['ready'])
   self.assertEqual(Store(d,'job-1').load()['tasks'][0]['write_scope'],job['tasks'][0]['write_scope'])

 def test_primary_support_and_review_retries_share_one_stage_budget(self):
  from core.jobs import retry_task
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['pins']={'imps':{'package_digest':'c'*64}};store=Store(d,'job-1');store.create(job);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   requests=[]
   for category in ('primary','support','review'):
    state=store.load();state['tasks'][0]['status']='failed';from core.jobs.store import _atomic;_atomic(store.file,canonical(state))
    retry_task(store,caller,'t0',category+' correction',category)
    requests.append(store.load()['tasks'][0]['request_id'])
   self.assertEqual(len(set(requests)),3)
   self.assertEqual(store.load()['stages'][0]['cycle'],3)
   state=store.load();state['tasks'][0]['status']='failed';_atomic(store.file,canonical(state))
   with self.assertRaisesRegex(JobError,'shared stage repair cycle budget exhausted'):
    retry_task(store,caller,'t0','fourth combined cycle','support')
   self.assertEqual(sum(store.load()['stages'][0]['attempts'].values()),3)

 def test_failed_slots_in_same_pass_share_one_stage_cycle_across_categories(self):
  from core.jobs import retry_task
  from core.jobs.store import _atomic
  with tempfile.TemporaryDirectory() as d:
   job=self.base();job['tasks'].append({'task_id':'t1','stage_id':'s0','logical_slot_id':'support','request_id':'req1','worker_id':'imps/stage-executor','dependency_key':'imps','status':'failed','attempt':0,'handles':[],'followups':[],'dispatch_retries':0,'dispatch_history':[]});job['tasks'][0]['status']='failed';job['pins']={'imps':{'package_digest':'c'*64}}
   store=Store(d,'job-1');store.create(job);caller={'installation_id':'install-1','workflow':'imps/run','package_digest':'c'*64,'actor':'coordinator'}
   retry_task(store,caller,'t0','primary pass','primary');retry_task(store,caller,'t1','support in same pass','support')
   state=store.load();self.assertEqual(state['stages'][0]['cycle'],1);self.assertEqual(state['stages'][0]['attempts']['primary'],1);self.assertEqual(state['stages'][0]['attempts']['support'],0)
   self.assertEqual(state['tasks'][0]['cycle'],state['tasks'][1]['cycle']);self.assertNotEqual(state['tasks'][0]['request_id'],state['tasks'][1]['request_id'])

 def test_installed_imps_malformed_result_charges_once_and_duplicate_is_idempotent(self):
  from core.jobs import prepare,record_result
  from shared.job_coordinator import create_pinned_job
  from core.jobs.results import parse_result
  import core.schema as schema_module
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);home=base/'home';home.mkdir();prefix=base/'prefix';agents=base/'agents';state=base/'state';env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(base/'config'),'XDG_STATE_HOME':str(state)}
   proc=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--plugin','imps','--prefix',str(prefix),'--agents-root',str(agents)],capture_output=True,text=True,env=env);self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
   version=Path(json.loads(proc.stdout)['data']['version_dir']);manifest=json.loads((version/'install-manifest.json').read_text())
   job={'schema_version':1,'job_id':'result-once','installation_id':manifest['installation_id'],'workflow':'imps/run','owner':{'id':'owner'},'objective':'bounded stage','requirements':{'R1':'preserve evidence'},'authorization':{'actions':['read']},'constraints':['no writes'],'dependencies':[{'key':'imps','plugin':'imps'}],'pins':{'imps':{'package_digest':'c'*64}},'result_contract':{'schema_version':1},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':'stage','depends_on':[],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'imps'}],'tasks':[{'task_id':'slot-1','stage_id':'stage','logical_slot_id':'primary','request_id':'request-1','worker_id':'imps/stage-executor','dependency_key':'imps','write_scope':{'mode':'coordinator-only'}}],'result_contract':{'schema_version':1},'decisions':[],'history':[],'metrics':{}}
   from tests.imps_plan_review_fixtures import select_legacy_imps_job
   select_legacy_imps_job(job,base,version,manifest,env)
   create_pinned_job(job,state,prefix,agents,base/'config/workers.json');store=Store(state,'result-once');caller={'installation_id':manifest['installation_id'],'workflow':'imps/run','package_digest':manifest['package_digest'],'actor':'coordinator'}
   before=store.load()
   with self.assertRaises(JobError):prepare(store,caller,'slot-1',lambda dep,pin:False,lambda stage_id:True)
   self.assertEqual(store.load(),before)
   prepare(store,caller,'slot-1',lambda dep,pin:True,lambda stage_id:True)
   malformed={'request_id':'request-1','completion_id':'host-completion-1','result':b'{"status":"ready-for-acceptance"}'}
   record_result(store,caller,'slot-1',malformed,result_parser=parse_result)
   record_result(store,caller,'slot-1',malformed,result_parser=parse_result)
   self.assertEqual(schema_module.SCHEMA_DIR,Path(ROOT/'core/schemas'))
   saved=store.load()['tasks'][0];self.assertEqual(saved['attempt'],1);self.assertEqual(len(saved['execution_history']),1);self.assertEqual(saved['last_execution_status'],'malformed-result')

if __name__=='__main__':unittest.main()
