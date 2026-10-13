"""JSON-file CLI: python -m shared.job_cli COMMAND --state-root ROOT --job ID ..."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.jobs import prepare,record_result,decision,cancel,discard,record_dispatch,retry_task,revise_plan
from shared.job_coordinator import create_pinned_job,verify_pinned_dependency,verify_all_pins,adopt_pins,pinned_store,prepare_task,prepare_followup,publish_observation,dispose_finding,record_observation
from shared.job_acceptance import validate_stage
from core.jobs.store import Store,JobError,strict_load

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('command',choices=['create','overview','status','prepare','result','task-observation','followup-prepare','observation','finding-disposition','decision','plan-revision','retry','cancel','discard']);p.add_argument('--state-root',required=True);p.add_argument('--job',required=True);p.add_argument('--input');p.add_argument('--prefix');p.add_argument('--agents-root');p.add_argument('--config')
 a=p.parse_args(argv)
 try:
  store=pinned_store(a.state_root,a.job)  # unsafe job IDs are invalid input, refused before any state access
  if a.command=='create' and (not a.prefix or not a.agents_root):raise JobError('create requires --prefix and --agents-root')
  if a.command!='create':
   job=verify_all_pins(store)
   if not any(Path(pin['package_dir']).absolute()==Path(__file__).resolve().parents[1] for pin in job['pins'].values()):raise JobError('wrong executing package; use the stored pinned package recovery argv')
  if a.input:
   from core.jobs.store import _regular
   data=strict_load(_regular(Path(a.input),max_bytes=16*1024*1024))
  else:data={}
  if a.command=='create':
   if data.get('job_id')!=a.job:raise JobError('--job differs from create input job_id')
   out=create_pinned_job(data,a.state_root,a.prefix,a.agents_root,a.config)
  elif a.command in ('overview','status'):
   job=store.load();invalid=[]
   for stage in job['stages']:
    if stage.get('status')=='accepted-at-snapshot' and not validate_stage(store,stage['id'],run_validator=False).get('accepted'):invalid.append(stage['id'])
   if invalid:
    def stale(state):
     pending=set(invalid);changed=True
     while changed:
      changed=False
      for stage in state['stages']:
       if stage['id'] not in pending and any(dep in pending for dep in stage.get('depends_on',[])):
        pending.add(stage['id']);changed=True
     for stage in state['stages']:
      if stage['id'] in pending:stage['status']='stale';stage['acceptance']=None
    stale(job)
   out=store.overview(job,persist=False)
  elif a.command=='prepare':out=prepare_task(store,data['caller'],data['task_id'],lambda dep,pin:verify_pinned_dependency(dep,pin),lambda stage_id:validate_stage(store,stage_id).get('accepted') is True,data.get('target_reason','configured worker'))
  elif a.command=='result':
   from core.jobs.store import _regular
   result=data.get('result')
   if isinstance(result,dict) and isinstance(result.get('path'),str):result={'result':_regular(Path(result['path']),max_bytes=32768),'completion_id':data.get('completion_id'),'request_id':data.get('request_id')}
   elif isinstance(result,dict) and isinstance(result.get('json'),str):result={'result':result['json'].encode(),'completion_id':data.get('completion_id'),'request_id':data.get('request_id')}
   out=record_result(store,data['caller'],data['task_id'],result)
  elif a.command=='followup-prepare':out=prepare_followup(store,data['caller'],data['task_id'],data['request_id'])
  elif a.command=='observation':out=publish_observation(store,data['caller'],data['stage_id'],data['input_file'])
  elif a.command=='finding-disposition':out=dispose_finding(store,data['caller'],data['task_id'],data['finding_id'],data['disposition'],data['evidence'],data.get('finding_sha256'))
  elif a.command=='task-observation':out=record_observation(store,data['caller'],data['task_id'],data['event'])
  elif a.command=='retry':out=retry_task(store,data['caller'],data['task_id'],data['reason'],data.get('category','primary'))
  elif a.command=='plan-revision':
   out=revise_plan(store,data['caller'],data['revision'],data['new_plan'],lambda job,deps: adopt_pins(job,deps,a.state_root,a.prefix or '',a.agents_root or '',a.config,data['revision'].get('adopt_keys',[])))
  elif a.command=='decision':out=decision(store,data['caller'],data['decision'])
  elif a.command=='cancel':out=cancel(store,data['caller'],data['reason'])
  else:out=discard(store,data['caller'],data['reason'])
  print(json.dumps(out,ensure_ascii=False,sort_keys=True));return 0
 except (JobError,KeyError,TypeError,ValueError,OSError,RecursionError) as e:print(f'job_error: {e}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
