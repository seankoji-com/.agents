"""Acceptance uses actual validators from a real isolated pinned installation."""
import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from shared.job_coordinator import create_pinned_job,publish_observation
from core.jobs.store import Store
from shared.job_acceptance import accept_stage,validate_stage,validate_final
from tests.support import Run
def ape_report(base, pin, **finding):
    """A complete valid study descriptor; `finding` overrides fields of its first finding."""
    from tests.test_ape_validate_report import study_descriptor
    data = study_descriptor(base, pin, ['R1'], [{'id':'C1','kind':'source-provenance'}])
    data['findings'][0].update(finding)
    return data

def source_fixture(base, job):
    from tests.test_ape_validate_report import pin_source
    pin = pin_source(base, 'src')
    job['stages'][0]['validator_contract'] = {'sources':[pin]}
    job['stages'][0]['criteria'] = [{'id':'C1','kind':'source-provenance'}]
    return pin

class PinnedAcceptanceTests(unittest.TestCase):
 def _install(self,base,plugin):
  home=base/'home';home.mkdir(exist_ok=True);prefix=base/'prefix';agents=base/'agents';state=base/'state'
  env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(base/'config'),'XDG_STATE_HOME':str(state)}
  proc=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--plugin',plugin,'--prefix',str(prefix),'--agents-root',str(agents)],capture_output=True,text=True,env=env)
  self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
  version=Path(json.loads(proc.stdout)['data']['version_dir']);manifest=json.loads((version/'install-manifest.json').read_text())
  return version,manifest,prefix,agents,state,env

 def test_actual_ape_validator_receipt_is_pin_and_input_bound(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);home=base/'home';home.mkdir();prefix=base/'prefix';agents=base/'agents';state=base/'state'
   env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(base/'config'),'XDG_STATE_HOME':str(state)}
   proc=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--plugin','ape','--prefix',str(prefix),'--agents-root',str(agents)],capture_output=True,text=True,env=env)
   self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
   version=Path(json.loads(proc.stdout)['data']['version_dir']);manifest=json.loads((version/'install-manifest.json').read_text())
   job={'schema_version':1,'job_id':'accept-1','installation_id':manifest['installation_id'],'workflow':'ape/study','owner':'coordinator','objective':'research','requirements':{'R1':'retain provenance'},'authorization':{'actions':['read']},'constraints':['no target writes'],'snapshot':{'sha256':'a'*64},'dependencies':[{'key':'ape','plugin':'ape'}],'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':'research','depends_on':[],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'ape','criteria':[{'id':'C1','kind':'source-provenance'}],'revision':'source-1'}],'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
   source_pin=source_fixture(base,job)
   created=create_pinned_job(job,state,prefix,agents,base/'config/workers.json');self.assertTrue(Path(created['job']).exists())
   self.assertEqual(Store(state,'accept-1').load()['policy']['identity'],'observed')
   inp=base/'report.json';inp.write_text(json.dumps(ape_report(base,source_pin)))
   caller={'installation_id':manifest['installation_id'],'workflow':'ape/study','package_digest':manifest['package_digest'],'actor':'coordinator'}
   validator=version/'scripts/validate_report.py'
   inp=Path(publish_observation(Store(state,'accept-1'),caller,'research',str(inp))['path'])
   receipt=accept_stage(Store(state,'accept-1'),caller,'research',[str(validator),'--input',str(inp)],str(inp),'source-1')
   self.assertTrue(receipt['accepted']);self.assertTrue(validate_stage(Store(state,'accept-1'),'research')['accepted'])
   (version/'scripts/validate_report.py').chmod(0o644)
   validator.write_text(validator.read_text()+'\n# mutation\n')
   self.assertFalse(validate_stage(Store(state,'accept-1'),'research')['accepted'])

 def test_installed_babysitter_rejects_missing_failed_and_stale_observations(self):
  from core.jobs.store import canonical
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);home=base/'home';home.mkdir();prefix=base/'prefix';agents=base/'agents';state=base/'state';env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(base/'config'),'XDG_STATE_HOME':str(state)}
   proc=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--plugin','babysitter','--prefix',str(prefix),'--agents-root',str(agents)],capture_output=True,text=True,env=env);self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
   version=Path(json.loads(proc.stdout)['data']['version_dir']);manifest=json.loads((version/'install-manifest.json').read_text());pin=manifest['package_digest']
   job={'schema_version':1,'job_id':'baby-1','installation_id':manifest['installation_id'],'workflow':'babysitter/pr','owner':{'id':'owner'},'objective':'review evidence','requirements':{'R1':'all required checks'},'authorization':{'actions':['read']},'constraints':['no writes'],'dependencies':[{'key':'babysitter','plugin':'babysitter'}],'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':'pr','depends_on':[],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'babysitter'}],'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
   create_pinned_job(job,state,prefix,agents,base/'config/workers.json');caller={'installation_id':manifest['installation_id'],'workflow':'babysitter/pr','package_digest':pin,'actor':'coordinator'};validator=version/'scripts/validate_pr.py';inp=base/'pr.json'
   valid={'pr':'https://example.invalid/pr/1','head_sha':'a'*40,'required_contexts':['ci','lint'],'allow_empty_required_contexts':False,'optional_contexts':[],'required_checks':[{'context':x,'conclusion':'success','head_sha':'a'*40} for x in ('ci','lint')],'review_threads':[],'authorized_endstate':{'requested':'mergeable','observed':'mergeable','authorization_ref':'coord-1'}}
   def bind_host(data):
    content={key:data[key] for key in ('pr','head_sha','required_contexts','required_checks','review_threads','authorized_endstate','allow_empty_required_contexts','optional_contexts')}
    data['host_observations']=[{'observer':'coordinator','kind':'pr-state','source':'fixture-host-snapshot','content':content,'sha256':hashlib.sha256(canonical(content)).hexdigest()}]
    return data
   bind_host(valid)
   inp.write_text(json.dumps(valid));args=[sys.executable,str(validator),'--input',str(inp)];self.assertEqual(subprocess.run(args,capture_output=True).returncode,0)
   explicit_empty=bind_host({**valid,'required_contexts':[],'required_checks':[],'allow_empty_required_contexts':True});explicit_empty['host_observations'][0]['content']['allow_empty_required_contexts']=True;explicit_empty['host_observations'][0]['sha256']=hashlib.sha256(canonical(explicit_empty['host_observations'][0]['content'])).hexdigest();inp.write_text(json.dumps(explicit_empty));self.assertEqual(subprocess.run(args,capture_output=True).returncode,0)
   unresolved=bind_host({**valid,'review_threads':[{'resolved':False,'head_sha':'a'*40}]})
   missing_context=bind_host({**valid,'required_contexts':['ci','release']})
   unauthorized=bind_host({**valid,'authorized_endstate':{'requested':'merged','observed':'open','authorization_ref':'coord-1'}})
   content_mismatch={**valid,'host_observations':[dict(valid['host_observations'][0],content={**valid['host_observations'][0]['content'],'head_sha':'c'*40})]}
   for bad in ({**valid,'required_checks':[]},{**valid,'required_checks':[{'context':'ci','conclusion':'failure','head_sha':'a'*40},{'context':'lint','conclusion':'success','head_sha':'a'*40}]},{**valid,'head_sha':'c'*40},unresolved,missing_context,unauthorized,content_mismatch):
    inp.write_text(json.dumps(bad));self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)


 def test_installed_imps_final_gate_rejects_changed_current_stage_input(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);repo=base/'repo';repo.mkdir();(repo/'file.txt').write_text('before\n');subprocess.run(['git','init','-q','-b','main',str(repo)],check=True);subprocess.run(['git','-C',str(repo),'config','user.email','fixture@example.invalid'],check=True);subprocess.run(['git','-C',str(repo),'config','user.name','Fixture'],check=True);subprocess.run(['git','-C',str(repo),'add','-A'],check=True);subprocess.run(['git','-C',str(repo),'commit','-qm','fixture'],check=True)
   home=base/'home';home.mkdir();prefix=base/'prefix';agents=base/'agents';state=base/'state';env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(base/'config'),'XDG_STATE_HOME':str(state)}
   proc=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--plugin','imps','--prefix',str(prefix),'--agents-root',str(agents)],capture_output=True,text=True,env=env);self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
   version=Path(json.loads(proc.stdout)['data']['version_dir']);manifest=json.loads((version/'install-manifest.json').read_text());pin=manifest['package_digest']
   job={'schema_version':1,'job_id':'imps-final-1','installation_id':manifest['installation_id'],'workflow':'imps/issue','owner':{'id':'owner'},'objective':'final check','requirements':{'R1':'five stage gates'},'authorization':{'actions':['read']},'constraints':['no network'],'dependencies':[{'key':'imps','plugin':'imps'}],'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':f's{i}','depends_on':[f's{i-1}'] if i else [],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'imps'} for i in range(5)],'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
   create_pinned_job(job,state,prefix,agents,base/'config/workers.json')
   final_plan_file=base/'external-final-plan.json';scripts=version/'scripts';stage_hash=hashlib.sha256((scripts/'validate_stage.py').read_bytes()).hexdigest()
   plan={'state_root':str(base/'stage-state'),'package_root':str(version),'required_stages':[f's{i}' for i in range(5)],'stages':[{'id':f's{i}','state_subdir':f's{i}','run_id':f'run-{i}','stage_sha256':stage_hash} for i in range(5)]};final_plan_file.write_text(json.dumps(plan))
   # The final validator is an actual installed script; absent current stage receipts fail closed.
   final=scripts/'validate_stage.py';result=subprocess.run([sys.executable,str(final),'--state-root',str(base/'stage-state'),'--final-plan',str(final_plan_file)],capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0);self.assertIn('accepted',json.loads(result.stdout))

 def test_installed_imps_final_gate_runs_five_real_stage_gates_and_detects_regression(self):
  from tests.support import CoreTestCase,Run
  # The installed adapter consumes existing imps run state; build each run through
  # the public gate API and retain state outside the immutable installed package.
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);version,manifest,prefix,agents,unused,env=self._install(base,'imps');state_root=base/'stage-state';state_root.mkdir()
   stage_hash=hashlib.sha256((version/'scripts/validate_stage.py').read_bytes()).hexdigest()
   rows=[]
   for i in range(5):
    case=CoreTestCase(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
    case.state_root=state_root/f's{i}'
    repo=case.make_repo();run=case.init(case.plan(repo,policy={'review':{'required':True,'role':'reviewer'},'checks':[{'name':'unit','argv':[sys.executable,'-m','unittest','discover','-s','tests'],'cwd':str(repo)}]}));self.assertIsInstance(run,Run)
    # Accepted gates are produced by the existing real evidence/review/check API.
    for req in run.state['brief']['requirements']:
     artifact=run.scratch(f's{i}-{req["id"]}.txt','verified fixture evidence\n')
     run.evidence(req['id'],artifact)
    check_result=case.run_check(run);self.assertEqual(check_result['result']['status'], 'passed', check_result)
    review_log=run.scratch(f's{i}-review.txt','reviewed current fixture binding; no findings\n')
    run.child(task_id=f'reviewer-{i}',status='completed')
    run.submit('review',{'binding':run.binding(),'task_id':f'reviewer-{i}','perspective_id':'default','verdict':'approve','findings':[],'artifacts':[str(review_log)]})
    accepted=run.validate();self.assertTrue(accepted.get('ready'),accepted)
    rows.append({'id':f's{i}','state_subdir':f's{i}','run_id':run.run_id,'stage_sha256':stage_hash})
   self.assertEqual(len(rows),5)
   plan=base/'private-final-plan.json'
   plan.write_text(json.dumps({'state_root':str(state_root),'package_root':str(version),'required_stages':[r['id'] for r in rows],'stages':rows}))
   final=version/'scripts/validate_stage.py'
   def gate():return subprocess.run([sys.executable,str(final),'--state-root',str(state_root),'--final-plan',str(plan)],capture_output=True,text=True)
   accepted=gate();self.assertEqual(accepted.returncode,0,accepted.stdout+accepted.stderr)
   self.assertTrue(json.loads(accepted.stdout)['accepted'])
   # Persist the integrated current gate through the generic coordinator using
   # an external invocation descriptor whose argv and final-plan bytes are bound.
   job_state=base/'job-state';job={'schema_version':1,'job_id':'imps-final-accept','installation_id':manifest['installation_id'],'workflow':'imps/issue','owner':{'id':'owner'},'objective':'integrate five accepted stage gates','requirements':{'R1':'all five current gates pass'},'authorization':{'actions':['read']},'constraints':['offline fixture only'],'dependencies':[{'key':'imps','plugin':'imps'}],'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':'integrated','depends_on':[],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'imps','revision':'integrated-r1'}],'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
   job['stages'][0]['validator_contract']={'final_plan':json.loads(plan.read_text())}
   create_pinned_job(job,job_state,prefix,agents,base/'config/workers.json');store=Store(job_state,'imps-final-accept');caller={'installation_id':manifest['installation_id'],'workflow':'imps/issue','package_digest':manifest['package_digest'],'actor':'coordinator'}
   descriptor=base/'final-invocation.json';descriptor.write_text(json.dumps({'state_root':str(state_root),'final_plan':str(plan)}));descriptor=Path(publish_observation(store,caller,'integrated',str(descriptor))['path']);argv=[str(final),'--state-root',str(state_root),'--final-plan',str(plan)]
   receipt=accept_stage(store,caller,'integrated',argv,str(descriptor),'integrated-r1');self.assertTrue(receipt['accepted'],receipt)
   self.assertTrue(validate_stage(store,'integrated')['accepted'])
   # Inject an actual source regression into an integrated repository, then update
   # that run's pre-existing binding. Its stage validator must reject current state.
   stage3=state_root/'s3';run_dir=stage3/'runs'/rows[3]['run_id'];run_state=json.loads((run_dir/'run.json').read_text())
   repo=Path(run_state['repo']['worktree']);(repo/'wordstat.py').write_text((repo/'wordstat.py').read_text()+'\n# injected current source regression\n')
   bad=gate();self.assertNotEqual(bad.returncode,0,bad.stdout);payload=json.loads(bad.stdout)
   self.assertFalse(payload['accepted']);self.assertEqual(payload['requirement_outcomes']['imps-stage-s3']['status'],'failed')
   reopened=validate_final(store,caller,{'integrated':argv},{'integrated':str(descriptor)})
   self.assertFalse(reopened['accepted'],reopened);self.assertEqual(reopened.get('stage_id'),'integrated',reopened)
   self.assertEqual(validate_stage(store,'integrated')['accepted'],False)

 def test_installed_tuneup_audit_accepts_reported_findings_and_rejects_unavailable_live_requirement(self):
  from core.jobs.store import canonical
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);version,*_=self._install(base,'agent-tuneup');validator=version/'scripts/validate_audit.py';inp=base/'audit.json'
   findings={'findings':[{'code':'broad_execution_allow','location':'permissions.allow[0]'}],'changes':[],'criteria':{'operation':'audit','findings_allowed':True,'live_enforcement_required':False},'audit_exit_code':1}
   inp.write_text(json.dumps(findings));good=subprocess.run([sys.executable,str(validator),'--input',str(inp)],capture_output=True,text=True)
   self.assertEqual(good.returncode,0,good.stdout);self.assertTrue(json.loads(good.stdout)['accepted']);self.assertEqual(json.loads(good.stdout)['findings_count'],1)
   before=base/'before.json'; backup=base/'backup.json'; before.write_text('synthetic settings before edit'); backup.write_bytes(before.read_bytes()); before_sha=hashlib.sha256(before.read_bytes()).hexdigest()
   findings['authorization_records']=[{'id':'owner-1','quote':'Authorize synthetic settings change','source':'synthetic-owner-record','source_sha256':'b'*64,'scope':'settings-change:edit-1'}]
   change_content={'authorization_ref':'owner-1','backup_sha256':before_sha,'backup_path':str(backup),'before_path':str(before),'before_sha256':before_sha,'parse_result':'passed','load_result':'passed','enforcement_result':'not-required'}
   findings['criteria']={'operation':'apply','findings_allowed':True,'live_enforcement_required':False};findings['audit_exit_code']=0
   findings['changes']=[{**change_content,'id':'edit-1','enforcement_required':False,'observation':{'observer':'coordinator','kind':'settings-change','source':'fixture-settings-receipt','content':change_content,'sha256':hashlib.sha256(canonical(change_content)).hexdigest()}}]
   inp.write_text(json.dumps(findings));changed=subprocess.run([sys.executable,str(validator),'--input',str(inp)],capture_output=True,text=True)
   self.assertEqual(changed.returncode,0,changed.stdout)
   findings['changes'][0]['observation']['content']['load_result']='failed'
   inp.write_text(json.dumps(findings));tampered=subprocess.run([sys.executable,str(validator),'--input',str(inp)],capture_output=True,text=True)
   self.assertNotEqual(tampered.returncode,0,tampered.stdout)
   findings['criteria']={'operation':'apply','findings_allowed':True,'live_enforcement_required':True}
   findings['changes']=[];findings['audit_exit_code']=1
   findings['live_observation']={'observer':'coordinator','kind':'live-enforcement','source':'fixture-settings-load','content':{'result':'unavailable'},'sha256':hashlib.sha256(canonical({'result':'unavailable'})).hexdigest()}
   inp.write_text(json.dumps(findings));bad=subprocess.run([sys.executable,str(validator),'--input',str(inp)],capture_output=True,text=True)
   self.assertNotEqual(bad.returncode,0,bad.stdout);self.assertFalse(json.loads(bad.stdout)['accepted'])

 def test_installed_acceptance_failures_consume_four_shared_cycles_and_refuse_fifth(self):
  from shared.job_acceptance import AcceptanceError
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);version,manifest,prefix,agents,state,env=self._install(base,'ape')
   job={'schema_version':1,'job_id':'budget-1','installation_id':manifest['installation_id'],'workflow':'ape/study','owner':{'id':'owner'},'objective':'bounded audit','requirements':{'R1':'source provenance'},'authorization':{'actions':['read']},'constraints':['read only'],'dependencies':[{'key':'ape','plugin':'ape'}],'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':'research','depends_on':[],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'ape','criteria':[],'attempts':{'primary':0,'support':0,'review':0,'final':0}}],'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
   source_pin=source_fixture(base,job)
   create_pinned_job(job,state,prefix,agents,base/'config/workers.json');store=Store(state,'budget-1');caller={'installation_id':manifest['installation_id'],'workflow':'ape/study','package_digest':manifest['package_digest'],'actor':'coordinator'};validator=version/'scripts/validate_report.py';inp=base/'empty-report.json';inp.write_text(json.dumps(ape_report(base,source_pin,quote='invented nonexistent quote')));inp=Path(publish_observation(store,caller,'research',str(inp))['path']);argv=[str(validator),'--input',str(inp)]
   for _ in range(4):self.assertFalse(accept_stage(store,caller,'research',argv,str(inp))['accepted'])
   self.assertEqual(store.load()['stages'][0]['acceptance_runs'],4)
   with self.assertRaisesRegex(AcceptanceError,'budget exhausted'):accept_stage(store,caller,'research',argv,str(inp))

 def test_installed_elephant_handoff_and_distinct_observation_gates(self):
  from core.jobs.store import canonical
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);version,manifest,prefix,agents,state,env=self._install(base,'elephant-goldfish');validator=version/'scripts/validate_document.py';root=base/'thinking';topic=root/'fixture-topic';topic.mkdir(parents=True)
   discovery='# Discovery\n\nA specific problem.\n';spec='# Spec\n\n[REQ-ONE] Confirm this criterion.\n'
   (topic/'discovery.md').write_text(discovery);(topic/'spec.md').write_text(spec)
   meta={'output_type':'research','title':'Fixture','published':{},'review':{'schema':1,'status':'accepted','scope':'finalise-brief','evidence_ref':'review-1','operator_statement':'Reviewed fixture discovery','recorded_at':'2026-10-12T00:00:00Z','discovery_sha256':hashlib.sha256(discovery.encode()).hexdigest()}}
   (topic/'meta.json').write_text(json.dumps(meta));render=subprocess.run([sys.executable,str(version/'scripts/render_handoff.py'),'fixture-topic','--root',str(root)],capture_output=True,text=True)
   self.assertEqual(render.returncode,0,render.stdout+render.stderr)
   state_gate=subprocess.run([sys.executable,str(version/'scripts/thinking_state.py'),'--root',str(root),'gate','fixture-topic','--require','discovery,spec,handoff'],capture_output=True,text=True)
   self.assertEqual(state_gate.returncode,0,state_gate.stdout+state_gate.stderr)
   job_state=base/'elephant-job-state';job={'schema_version':1,'job_id':'document-1','installation_id':json.loads((version/'install-manifest.json').read_text())['installation_id'],'workflow':'elephant-goldfish/thinking','owner':{'id':'owner'},'objective':'review handoff readiness','requirements':{'R1':'reviewed document is ready'},'authorization':{'actions':['read']},'constraints':['offline fixture'],'dependencies':[{'key':'elephant','plugin':'elephant-goldfish'}],'pins':{},'policy':{'max_repair_cycles':3,'max_artifact_bytes':16777216},'stages':[{'id':'handoff','depends_on':[],'requirements':['R1'],'status':'pending','execution_mode':'direct','validator_dependency':'elephant','revision':'document-r1'}],'tasks':[],'decisions':[],'history':[],'metrics':{},'result_contract':{'schema_version':1}}
   job['stages'][0]['validator_contract']={'root':str(root),'slug':'fixture-topic','mode':'handoff'}
   create_pinned_job(job,job_state,prefix,agents,base/'config/workers.json');store=Store(job_state,'document-1');caller={'installation_id':job['installation_id'],'workflow':job['workflow'],'package_digest':json.loads((version/'install-manifest.json').read_text())['package_digest'],'actor':'coordinator'}
   descriptor=base/'handoff-invocation.json';descriptor.write_text(json.dumps({'root':str(root),'slug':'fixture-topic','mode':'handoff'}));descriptor=Path(publish_observation(store,caller,'handoff',str(descriptor))['path']);argv=[str(validator),'--root',str(root),'--slug','fixture-topic','--mode','handoff']
   accepted=accept_stage(store,caller,'handoff',argv,str(descriptor),'document-r1')
   # Keep exercising the factual and cold-read installed modes even while the
   # parent's handoff adapter argument-order defect is present.
   handoff_error=None if accepted['accepted'] else accepted
   # Handoff bytes are content-bound through the existing handoff manifest/check.
   (topic/'discovery.md').write_text(discovery+'Changed after rendering.\n');bad=subprocess.run([str(validator),'--root',str(root),'--slug','fixture-topic','--mode','handoff'],capture_output=True,text=True);self.assertNotEqual(bad.returncode,0,bad.stdout)
   if accepted['accepted']:self.assertFalse(validate_stage(store,'handoff')['accepted'])
   factual=base/'factual.json';doc_path=topic/'discovery.md';doc_hash=hashlib.sha256(doc_path.read_bytes()).hexdigest();unknown_content={'document_sha256':doc_hash,'claim_id':'C1','outcome':'unknown'};unknown_row={'observer':'coordinator','kind':'factual-claim','source':'fixture claim inspection','content':unknown_content,'sha256':hashlib.sha256(canonical(unknown_content)).hexdigest()};factual.write_text(json.dumps({'kind':'factual-observation','document_path':str(doc_path),'document_sha256':doc_hash,'claims':[{'claim_id':'C1','outcome':'unknown','evidence':[unknown_row]}]}))
   factual_args=[sys.executable,str(validator),'--root',str(root),'--slug','fixture-topic','--mode','factual','--input',str(factual)]
   self.assertNotEqual(subprocess.run(factual_args,capture_output=True).returncode,0)
   confirmed_content={'document_sha256':doc_hash,'claim_id':'C1','outcome':'confirmed'};confirmed_row={'observer':'coordinator','kind':'factual-claim','source':'fixture claim inspection','content':confirmed_content,'sha256':hashlib.sha256(canonical(confirmed_content)).hexdigest()};factual.write_text(json.dumps({'kind':'factual-observation','document_path':str(doc_path),'document_sha256':doc_hash,'claims':[{'claim_id':'C1','outcome':'confirmed','evidence':[confirmed_row]}]}))
   self.assertEqual(subprocess.run(factual_args,capture_output=True).returncode,0)
   claim_tamper={'kind':'factual-observation','document_path':str(doc_path),'document_sha256':doc_hash,'claims':[{'claim_id':'C1','outcome':'confirmed','evidence':[dict(confirmed_row,content={'claim_id':'C1','outcome':'refuted'})]}]};factual.write_text(json.dumps(claim_tamper));self.assertNotEqual(subprocess.run(factual_args,capture_output=True).returncode,0)
   cold=base/'cold.json';document=topic/'cold-document.md';document.write_text('# Cold read fixture\nThe criterion is visible.\n');doc_sha=hashlib.sha256(document.read_bytes()).hexdigest();cold_content={'document_sha256':doc_sha,'verdict':'ready'};cold_row={'observer':'coordinator','kind':'cold-read','source':'fixture cold reader','content':cold_content,'sha256':hashlib.sha256(canonical(cold_content)).hexdigest()};cold.write_text(json.dumps({'kind':'cold-read-observation','document_path':str(document),'document_sha256':doc_sha,'verdict':'ready','evidence':[cold_row]}))
   cold_args=[sys.executable,str(validator),'--root',str(root),'--slug','fixture-topic','--mode','cold-read','--input',str(cold)]
   self.assertEqual(subprocess.run(cold_args,capture_output=True).returncode,0)
   notready_content={'document_sha256':doc_sha,'verdict':'not-ready'};notready_row={'observer':'coordinator','kind':'cold-read','source':'fixture cold reader','content':notready_content,'sha256':hashlib.sha256(canonical(notready_content)).hexdigest()};cold.write_text(json.dumps({'kind':'cold-read-observation','document_path':str(document),'document_sha256':doc_sha,'verdict':'not-ready','evidence':[notready_row]}))
   self.assertNotEqual(subprocess.run(cold_args,capture_output=True).returncode,0)
   cold.write_text(json.dumps({'kind':'cold-read-observation','document_path':str(document),'document_sha256':doc_sha,'verdict':'ready','evidence':[cold_row]}));document.write_text('# Changed after cold read\n');self.assertNotEqual(subprocess.run(cold_args,capture_output=True).returncode,0)
   tampered_content={'document_sha256':doc_sha,'verdict':'ready'};tampered_row={'observer':'coordinator','kind':'cold-read','source':'fixture cold reader','content':{'document_sha256':'d'*64,'verdict':'ready'},'sha256':hashlib.sha256(canonical(tampered_content)).hexdigest()};cold.write_text(json.dumps({'kind':'cold-read-observation','document_path':str(document),'document_sha256':doc_sha,'verdict':'ready','evidence':[tampered_row]}))
   self.assertNotEqual(subprocess.run(cold_args,capture_output=True).returncode,0)
   self.assertIsNone(handoff_error, f'installed handoff acceptance failed: {handoff_error}')

if __name__=='__main__':unittest.main()
