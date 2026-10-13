#!/usr/bin/env python3
"""Run the pinned imps core validate gate with a fresh pre-check binding."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.jobs.store import _regular,strict_load

def validate_final(path, state_root):
 try:
  plan=strict_load(_regular(path))
  stages=plan['stages'];required=plan['required_stages'];base=Path(plan['state_root']).absolute();package=Path(__file__).resolve().parents[1]
  if base!=Path(state_root).absolute():raise ValueError('final invocation state root differs from the bound plan')
  if os.path.realpath(plan['package_root'])!=os.path.realpath(package):raise ValueError('final plan must use this pinned package')
  # Every declared row is a distinct valid gate and the required list names each exactly once, checked before any gate runs.
  if not isinstance(stages,list) or not all(isinstance(s,dict) for s in stages):raise ValueError('final plan stages must be declared gate objects')
  ids=[s.get('id') for s in stages]
  if not isinstance(required,list) or not required or any(not isinstance(sid,str) or not sid for sid in ids+required) or len(set(ids))!=len(ids) or len(set(required))!=len(required) or set(required)!=set(ids):raise ValueError('final gate must cover every declared current stage gate exactly once')
  if any(not isinstance(s.get('stage_sha256'),str) or len(s['stage_sha256'])!=64 for s in stages):raise ValueError('final plan must bind all five stage gate inputs')
  for s in stages:
   if os.path.realpath(s.get('plugin_root',str(package)))!=os.path.realpath(package):raise ValueError('a result cannot select an executable package')
   if not isinstance(s.get('state_subdir'),str) or Path(s['state_subdir']).is_absolute() or '..' in Path(s['state_subdir']).parts:raise ValueError('stage state escapes final state root')
   if not isinstance(s.get('run_id'),str) or not s['run_id']:raise ValueError('final plan stage needs a run id')
  # Reserve every declared stage binding before any gate runs; each gate must run at its
  # reserved binding, and the whole set is rechecked after the last gate. This covers the
  # window from the first reservation to the final observation, not later changes.
  rows={s['id']:s for s in stages};targets={sid:(base/rows[sid]['state_subdir'],rows[sid]['run_id']) for sid in required}
  def snap(sid,phase):
   proc=subprocess.run([sys.executable,str(package/'core'/'cli.py'),'snapshot','--plugin-dir',str(package),'--state-root',str(targets[sid][0]),'--run-id',targets[sid][1]],capture_output=True,text=True)
   if proc.returncode:raise ValueError(f'{phase} binding unavailable for {sid}: {proc.stderr[-1000:]}')
   try:data=json.loads(proc.stdout)['data']
   except (ValueError,KeyError,TypeError):data=None
   if not isinstance(data,dict) or not data:raise ValueError(f'{phase} binding malformed for {sid}')
   return data
  reserved={sid:snap(sid,'reserved') for sid in required}
  outcomes={};reports=[];ok=True
  for sid in required:
   stage=rows[sid]
   plugin=package
   state_root,run_id=targets[sid];command=[sys.executable,str(plugin/'scripts'/'validate_stage.py'),'--state-root',str(state_root),'--run-id',run_id]
   pre=snap(sid,'pre-check')
   if pre!=reserved[sid]:raise ValueError(f'stage binding changed after reservation, before its gate for {sid}')
   current_hash=hashlib.sha256((plugin/'scripts'/'validate_stage.py').read_bytes()).hexdigest()
   if current_hash!=stage['stage_sha256']:raise ValueError(f'current stage validator bytes changed for {sid}')
   run=subprocess.run(command,capture_output=True,text=True)
   try:result=json.loads(run.stdout)
   except ValueError:result={'accepted':False,'requirement_outcomes':{'stage-gate':{'status':'failed','evidence':run.stderr[-1500:]}}}
   if not isinstance(result,dict):result={}
   reports.append({'stage_id':sid,'argv':command,'exit_code':run.returncode,'stdout_sha256':hashlib.sha256(run.stdout.encode()).hexdigest(),'precheck_sha256':hashlib.sha256(json.dumps(pre,sort_keys=True).encode()).hexdigest(),'stage_validator_sha256':current_hash})
   if snap(sid,'post-check')!=pre:raise ValueError(f'stage binding changed during final gate for {sid}')
   good=run.returncode==0 and result.get('accepted') is True
   outcomes['imps-stage-'+sid]={'status':'passed' if good else 'failed','evidence':reports[-1]};ok=ok and good
  # An earlier stage can change while a later one runs: refuse any stage not still at its reservation.
  final={}
  for sid in required:
   try:final[sid]='current' if snap(sid,'final')==reserved[sid] else 'changed after its gate'
   except ValueError as exc:final[sid]=str(exc)
   if hashlib.sha256((package/'scripts'/'validate_stage.py').read_bytes()).hexdigest()!=rows[sid]['stage_sha256']:final[sid]='stage validator bytes changed after its gate'
   if final[sid]!='current':
    outcomes['imps-stage-'+sid]={'status':'failed','evidence':{**outcomes['imps-stage-'+sid]['evidence'],'final_binding':final[sid]}};ok=False
  print(json.dumps({'accepted':ok,'requirement_outcomes':outcomes,'current_gate':reports,'final_binding':final},sort_keys=True));return 0 if ok else 1
 except Exception as exc:
  print(json.dumps({'accepted':False,'requirement_outcomes':{'imps-final-gate':{'status':'failed','evidence':str(exc)}}},sort_keys=True));return 1

def main():
 p=argparse.ArgumentParser();p.add_argument('--state-root',required=True);p.add_argument('--run-id');p.add_argument('--final-plan');a=p.parse_args()
 if a.final_plan:return validate_final(Path(a.final_plan), a.state_root)
 if not a.run_id:p.error('--run-id is required outside final-plan mode')
 package=Path(__file__).resolve().parents[1];core=package/'core/cli.py'
 common=[sys.executable,str(core)]
 before=subprocess.run([*common,'snapshot','--plugin-dir',str(package),'--state-root',a.state_root,'--run-id',a.run_id],capture_output=True,text=True)
 if before.returncode:print(json.dumps({'accepted':False,'requirement_outcomes':{'imps-stage-gate':{'status':'unavailable','reason':'pre-check binding unavailable','evidence':before.stderr[-2000:]}}}));return 1
 try:pre=json.loads(before.stdout)['data']
 except (ValueError,KeyError,TypeError):print(json.dumps({'accepted':False,'requirement_outcomes':{'imps-stage-gate':{'status':'unavailable','reason':'invalid pre-check binding response','evidence':before.stdout[-2000:]}}}));return 1
 checked=subprocess.run([*common,'validate','--plugin-dir',str(package),'--state-root',a.state_root,'--run-id',a.run_id],capture_output=True,text=True)
 try:result=json.loads(checked.stdout)['data']
 except (ValueError,KeyError,TypeError):print(json.dumps({'accepted':False,'requirement_outcomes':{'imps-stage-gate':{'status':'failed','reason':'invalid gate validation response','evidence':checked.stdout[-2000:]}}}));return 1
 fresh=result.get('binding');ok=checked.returncode==0 and result.get('ready') is True and fresh==pre
 outcomes={}
 for row in result.get('requirements',[]):
  outcomes[row.get('id','unknown')]={'status':'passed' if row.get('status')=='passed' else 'failed','evidence':row}
 outcomes['pre-check-binding']={'status':'passed' if fresh==pre else 'failed','evidence':{'sha256':hashlib.sha256(json.dumps(pre,sort_keys=True).encode()).hexdigest()}}
 print(json.dumps({'accepted':ok,'binding':fresh,'requirement_outcomes':outcomes,'validator_identity':'core.cli validate','precheck_sha256':hashlib.sha256(before.stdout.encode()).hexdigest()},sort_keys=True));return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
