"""JSON-file CLI: python -m shared.job_cli COMMAND --state-root ROOT --job ID ..."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.jobs import prepare,record_result,decision,cancel,discard,record_dispatch,retry_task,revise_plan
from shared.job_coordinator import create_pinned_job,verify_pinned_dependency,verify_all_pins,adopt_pins,pinned_store,prepare_task,prepare_followup,publish_observation,dispose_finding,record_observation,revise_document,record_direct_execution
from shared.job_acceptance import validate_stage
from shared.worker_registry import job_agents_roots,record_job_root
from core.jobs.store import Store,JobError,strict_load

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('command',choices=['create','overview','status','admission','prepare','result','task-observation','followup-prepare','observation','direct-execution','finding-disposition','decision','plan-revision','upgrade-package','document-revision','retry','cancel','discard']);p.add_argument('--state-root',required=True);p.add_argument('--job',required=True);p.add_argument('--input');p.add_argument('--prefix');p.add_argument('--agents-root');p.add_argument('--config');p.add_argument('--capabilities')
 p.add_argument('--compact',action='store_true');p.add_argument('--since');p.add_argument('--cursor');p.add_argument('--limit',type=int,help='compact page records (default: 20; maximum: 100)')
 a=p.parse_args(argv)
 try:
  if (a.compact or a.since is not None or a.cursor is not None or a.limit is not None) and a.command not in ('overview','status'):raise JobError('compact options require overview or status')
  if (a.since is not None or a.cursor is not None or a.limit is not None) and not a.compact:raise JobError('--since, --cursor and --limit require --compact')
  store=pinned_store(a.state_root,a.job)  # unsafe job IDs are invalid input, refused before any state access
  if a.command=='create' and (not a.prefix or not a.agents_root):raise JobError('create requires --prefix and --agents-root')
  if a.command!='create':
   job=verify_all_pins(store)
   if a.command!='upgrade-package' and not any(os.path.realpath(pin['package_dir'])==os.path.realpath(Path(__file__).resolve().parents[1]) for pin in job['pins'].values()):raise JobError('pin_mismatch: wrong executing package; use the stored pinned package recovery argv')
  if a.input:
   from core.jobs.store import _regular
   data=strict_load(_regular(Path(a.input),max_bytes=16*1024*1024))
  else:data={}
  if a.command=='create':
   if data.get('job_id')!=a.job:raise JobError('--job differs from create input job_id')
   from shared.model_selection import validate, gate
   from shared.job_coordinator import selection_for_task
   selected=validate(data.get('model_selection'),data.get('model_selection_sha256'))
   if not data.get('model_selection_sha256'):raise JobError('producing model_selection_sha256 required')
   gate(selected,invocation_id=data.get('invocation_id'),scope_id=data.get('scope_id'))
   data.setdefault('policy',{})['model_selection_required']=True
   for task in data.get('tasks',[]):selection_for_task(data,task)
   out=create_pinned_job(data,a.state_root,a.prefix,a.agents_root,a.config)
  elif a.command in ('overview','status','admission'):
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
   if a.command=='admission':
    from shared.job_coordination import admission
    out=admission(job)
   else:
    from shared.job_coordination import overview
    out=overview(store,job,compact=a.compact,since=a.since,cursor=a.cursor,limit=20 if a.limit is None else a.limit)
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
  elif a.command=='upgrade-package':
   from shared.job_upgrade import upgrade_package
   out=upgrade_package(store,data['caller'],data['revision'],data['dependency_key'],data['expected_state_sha256'],data['expected_package_digest'],Path(__file__).resolve().parents[1],a.prefix,a.agents_root,a.config)
  elif a.command=='plan-revision':
   def adopt(job,deps):
    pins=adopt_pins(job,deps,a.state_root,a.prefix or '',a.agents_root or '',a.config,data['revision'].get('adopt_keys',[]))
    record_job_root(job_agents_roots(pins),a.state_root,a.job);return pins  # index new owning roots before the revision is written
   from shared.document_authors import refresh_new_task_authors
   from shared.job_coordinator import selection_plan_revision
   selection_plan_revision(store.load(), data['new_plan'], data['revision'])
   current_policy=store.load().get('policy', {})
   proposed_policy=data['new_plan'].get('policy', current_policy)
   if current_policy.get('model_selection_required') is True and proposed_policy.get('model_selection_required',True) is not True:
    raise JobError('model selection policy is immutable once enabled')
   if current_policy.get('author_independence') is True and proposed_policy.get('author_independence', True) is not True:
    raise JobError('author independence policy is immutable once enabled')
   refresh_new_task_authors(store.load(),data['new_plan'])
   from shared.adopter_planning import transaction_guard
   guard=transaction_guard(store.load(),'plan-revision',proposed={**store.load(),**data['new_plan']},caller=data['caller'],job_file=store.file)
   out=revise_plan(store,data['caller'],data['revision'],data['new_plan'],adopt,commit_guard=guard)
  elif a.command=='document-revision':
   capabilities=None
   if a.capabilities:
    from core.jobs.store import _regular
    capabilities=strict_load(_regular(Path(a.capabilities),max_bytes=1024*1024))
   out=revise_document(store,data['caller'],data['task_id'],data['document'],data['reason'],capabilities)
  elif a.command=='direct-execution':
   if not a.capabilities:raise JobError('direct-execution requires --capabilities')
   from core.jobs.store import _regular
   capabilities=strict_load(_regular(Path(a.capabilities),max_bytes=1024*1024))
   out=record_direct_execution(store,data['caller'],data['stage_id'],capabilities)
  elif a.command=='decision':out=decision(store,data['caller'],data['decision'])
  elif a.command=='cancel':out=cancel(store,data['caller'],data['reason']);record_job_root(job_agents_roots(out['pins']),a.state_root,a.job,'cancelled')
  else:out=discard(store,data['caller'],data['reason']);record_job_root(job_agents_roots(out['pins']),a.state_root,a.job,'discarded')
  print(json.dumps(out,ensure_ascii=False,sort_keys=True,**({'separators':(',',':')} if a.compact else {})));return 0
 except (JobError,KeyError,TypeError,ValueError,OSError,RecursionError) as e:print(f'job_error: {e}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
