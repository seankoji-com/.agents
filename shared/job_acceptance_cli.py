"""Explicit validator CLI: python -m shared.job_acceptance_cli ACTION --state-root ..."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.jobs.store import Store,strict_load,JobError,_regular
from shared.job_acceptance import accept_stage,validate_stage,validate_final

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('action',choices=['accept-stage','validate','validate-final']);p.add_argument('--state-root',required=True);p.add_argument('--job',required=True);p.add_argument('--input',required=True)
 a=p.parse_args(argv)
 try:
  s=Store(a.state_root,a.job);d=strict_load(_regular(Path(a.input),max_bytes=16*1024*1024))
  from shared.job_coordinator import verify_all_pins
  job=verify_all_pins(s)
  if not any(Path(pin['package_dir']).absolute()==Path(__file__).resolve().parents[1] for pin in job['pins'].values()):raise JobError('wrong executing package; use the stored pinned package recovery argv')
  if a.action=='accept-stage':o=accept_stage(s,d['caller'],d['stage_id'],d['validator_argv'],d['input_file'],d.get('revision'))
  elif a.action=='validate':o=validate_stage(s,d['stage_id'])
  else:o=validate_final(s,d['caller'],d['validator_argv_by_stage'],d['input_file_by_stage'])
  print(json.dumps(o,sort_keys=True));return 0 if o.get('accepted') else 1
 except (ValueError,KeyError,OSError,TypeError,RecursionError) as e:print(json.dumps({'accepted':False,'error':str(e)}),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
