"""Strict full-object worker result parser; no extraction, execution, or truncation."""
from __future__ import annotations
import json,os,stat
from pathlib import Path
from .store import JobError,strict_load,digest,_directory_fd
INLINE_LIMIT=32768
class ResultError(ValueError):pass
SEVERITIES={'blocker','major','minor','note'}
def _check_full(v,expected):
 from core import schema as published_schema
 try:
  contract=published_schema.load_schema_file(Path(__file__).resolve().parents[2]/'shared'/'agents'/'worker-result.schema.json')
  errors=published_schema.errors(v,contract)
  if errors:raise ResultError('; '.join(errors))
 except Exception as exc:raise ResultError(f'full result does not match published schema: {exc}') from exc
 for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256'):
  if expected.get(k)!=v[k]:raise ResultError(f'result correlation mismatch: {k}')
 if len(v['conclusion'].split())>250:raise ResultError('conclusion exceeds 250 words')
 seen_requirements=set()
 for outcome in v['requirements']:
  if not isinstance(outcome,dict) or not isinstance(outcome.get('id'),str) or not outcome['id'] or outcome.get('status') not in {'passed','failed','unverified','unavailable','waived'} or not outcome.get('evidence'):raise ResultError('requirement outcome lacks valid status/evidence')
  if outcome['id'] in seen_requirements:raise ResultError('duplicate requirement outcome')
  seen_requirements.add(outcome['id'])
  if outcome['status']=='waived' and (not isinstance(outcome.get('owner_evidence'),dict) or outcome['owner_evidence'] not in expected.get('owner_waivers',[]) or outcome['id'] not in outcome['owner_evidence'].get('requirement_ids',[]) or outcome['id'] not in expected.get('waivable_requirements',[])):raise ResultError('waiver is not a recorded, policy-permitted owner decision')
 if 'requirements' in expected and seen_requirements!=set(expected['requirements']):raise ResultError('assigned requirement coverage differs')
 if 'revision' in expected and v['revision']!=expected['revision']:raise ResultError('result revision differs from immutable brief')
 if 'binding' in expected and v['binding']!=expected['binding']:raise ResultError('result binding differs from pre-check brief')
 seen_findings=set()
 for f in v['findings']:
  if not isinstance(f,dict) or f.get('severity') not in SEVERITIES or not f.get('scenario') or not f.get('source_evidence') or not f.get('id'):raise ResultError('finding lacks ID, severity, scenario, or source evidence')
  if f['id'] in seen_findings:raise ResultError('duplicate finding ID')
  seen_findings.add(f['id'])
 if any(not isinstance(c,dict) or not isinstance(c.get('argv'),list) or any(not isinstance(a,str) for a in c['argv']) for c in v['commands']):raise ResultError('command evidence must contain argv arrays')
 if any(not isinstance(a,dict) or not isinstance(a.get('path'),str) or not isinstance(a.get('sha256'),str) or not isinstance(a.get('bytes'),int) or isinstance(a.get('bytes'),bool) for a in v['artifacts']):raise ResultError('artifact_invalid: artifact evidence has invalid fields')
 if v['status']=='ready-for-acceptance' and any(x['status'] in ('failed','unavailable','unverified') for x in v['requirements']):raise ResultError('ready result contradicts failed or unverified requirement')
 if 'role' in expected and v['review_verdict']=='approve' and expected['role']!='review':raise ResultError('approval requires a declared independent review slot')
 if any(f['severity'] in ('blocker','major') for f in v['findings']) and v['review_verdict']!='adverse':raise ResultError('blocker/major findings require an adverse verdict')
 return v
def parse_result(data:bytes,expected:dict,job_dir:Path|None=None,max_artifact_bytes=16*1024*1024):
 if not isinstance(data,bytes):raise ResultError('transport must be bytes')
 if len(data)>INLINE_LIMIT:raise ResultError('result transport exceeds 32768-byte limit')
 try:v=strict_load(data)
 except JobError as e:raise ResultError(str(e)) from e
 if isinstance(v,dict) and v.get('schema_version')==1 and 'artifact' in v:
  if set(v)!={'schema_version','artifact','correlation'}:raise ResultError('invalid result envelope fields')
  env=v['artifact']
  if not isinstance(env,dict) or not isinstance(env.get('path'),str) or type(env.get('finding_count')) is not int or not isinstance(env.get('finding_ids'),list):raise ResultError('artifact_invalid: invalid artifact descriptor')
  rel=Path(env['path'])
  corr=v.get('correlation')
  if not isinstance(corr,dict) or any(corr.get(k)!=expected.get(k) for k in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')):raise ResultError('artifact_invalid: artifact envelope correlation mismatch')
  if rel.as_posix()!=env['path'] or rel.is_absolute() or '..' in rel.parts or not env.get('path','').startswith('artifacts/tasks/'):raise ResultError('artifact_invalid: artifact path outside declared task subtree')
  if job_dir is None:raise ResultError('artifact_invalid: artifact writes were not authorized')
  if not expected.get('task_id') or rel.parts[:3]!=('artifacts','tasks',expected['task_id']):raise ResultError('artifact_invalid: artifact is not in the declared task subtree')
  root=Path(job_dir).resolve(strict=True);path=Path(job_dir)/rel;current=Path(job_dir)
  for part in rel.parts:
   current=current/part
   if current.is_symlink():raise ResultError('artifact_invalid: artifact path crosses symlink')
  try:
   parent=_directory_fd(path.parent)
   try:fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
   finally:os.close(parent)
  except OSError as e:raise ResultError('artifact_invalid: artifact missing or unsafe') from e
  try:
   st=os.fstat(fd)
   if not stat.S_ISREG(st.st_mode):raise ResultError('artifact_invalid: artifact must be regular file')
   if st.st_size>max_artifact_bytes:raise ResultError('artifact_oversize: artifact exceeds pinned byte limit')
   if not path.resolve(strict=True).is_relative_to(root):raise ResultError('artifact_invalid: artifact escapes job directory')
   with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(max_artifact_bytes+1)
  finally:os.close(fd)
  if len(raw)!=st.st_size or len(raw)>max_artifact_bytes or digest(raw)!=env.get('sha256'):raise ResultError('artifact_invalid: artifact size/hash mismatch')
  full=strict_load(raw);_check_full(full,expected)
  if env.get('finding_count')!=len(full['findings']) or env.get('finding_ids')!=[f.get('id') for f in full['findings']]:raise ResultError('artifact_invalid: artifact finding index/count mismatch')
  return {'kind':'artifact','envelope':v,'result':full,'sha256':digest(raw),'bytes':len(raw)}
 if not isinstance(v,dict):raise ResultError('result must be one full JSON object')
 return {'kind':'inline','result':_check_full(v,expected),'sha256':digest(data),'bytes':len(data)}
