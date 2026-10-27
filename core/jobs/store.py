"""Private, versioned generic job state. Stores evidence, not readiness."""
from __future__ import annotations
import contextlib, copy, fcntl, graphlib, hashlib, itertools, json, math, os, re, stat, tempfile
from pathlib import Path
VERSION=1
MAX_STATE_BYTES=256*1024*1024;MAX_JSON_DEPTH=512  # finite state bound; input/artifact limits remain separate
class JobError(ValueError): pass
def _pairs(pairs):
 if len(out:=dict(pairs))!=len(pairs):raise JobError('duplicate JSON key: '+next(k for i,(k,_) in enumerate(pairs) if any(k==x for x,_ in pairs[:i])))
 return out
def strict_load(data):
 def bad(x,why='non-finite number'): raise JobError(f'{why}: {x}')
 try:v=json.loads(t:=data.decode('utf-8') if isinstance(data,(bytes,bytearray)) else data,object_pairs_hook=_pairs,parse_constant=bad,parse_float=lambda x:float(x) if math.isfinite(float(x)) else bad(x))
 except (UnicodeError,json.JSONDecodeError,RecursionError) as e:raise JobError(f'invalid JSON: {e}') from e
 return v if _within_json_depth(v) else bad(MAX_JSON_DEPTH,'invalid JSON: nesting exceeds maximum depth')
def _within_json_depth(value):
 """Count only containers, retaining at most one iterator per nesting level."""
 stack=[iter((value,))]
 while stack:
  for child in stack[-1]:
   if isinstance(child,(dict,list)):
    if len(stack)>MAX_JSON_DEPTH:return False
    stack.append(iter(child.values() if isinstance(child,dict) else child));break
  else:stack.pop()
 return True
def json_depth(text):return max(itertools.accumulate(1 if c in '[{' else -1 for c in re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"|[^\][{}"]+','',text)),default=0)  # valid JSON only: strings are stripped, so quoted brackets never count
def digest(data):return hashlib.sha256(data).hexdigest()
def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def _regular(path,max_bytes=16*1024*1024):
 parent=_directory_fd(Path(path).parent)
 try:fd=os.open(Path(path).name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
 finally:os.close(parent)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or max_bytes is not None and info.st_size>max_bytes:raise JobError(f'unsafe or oversized regular file: {path}')
  with os.fdopen(fd,'rb',closefd=False) as f:data=f.read() if max_bytes is None else f.read(max_bytes+1)
  if max_bytes is not None and len(data)>max_bytes:raise JobError('regular file grew beyond byte limit')
  return data
 finally:os.close(fd)
def _atomic(path,data,exclusive=False):  # exclusive: create-only; an existing name raises FileExistsError.
 path=Path(path);parent=_directory_fd(path.parent,create=True)
 name='.'+path.name+'.'+__import__('secrets').token_hex(12)
 try:
  try:
   if not stat.S_ISREG(os.stat(path.name,dir_fd=parent,follow_symlinks=False).st_mode):raise JobError('unsafe destination')
  except FileNotFoundError:pass
  fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  (os.link if exclusive else os.replace)(name,path.name,src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
 finally:
  try:os.unlink(name,dir_fd=parent)
  except FileNotFoundError:pass
  os.close(parent)
def _retain(path,data,why,max_bytes=16*1024*1024):  # Retained evidence is create-exclusive; only identical bytes may be re-presented.
 try:_atomic(path,data,exclusive=True)
 except FileExistsError:
  if _regular(path,max_bytes=max_bytes)!=data:raise JobError(why) from None
def tasks(j):return j['tasks']+[y for h in j.get('history',[]) for y in h.get('tasks',[])]  # current and superseded task records
def requests(j,skip=None):  # Every request ID retained by current or superseded task records (optionally excluding one task ID).
 out=set()
 for t in [x for x in tasks(j) if x['task_id']!=skip]:
  out|={x.get('request_id') for x in [t,t.get('prepared_followup') or {},t.get('followup_dispatch') or {}]+[y for k in ('handles','followups','execution_history','dispatch_history','host_conflicts') for y in t.get(k,[])]}|{t.get('original_request_id'),*t.get('retired_request_ids',[])}
 return out-{None}
def _directory_fd(path,create=False):
 path=Path(path).absolute()
 if '..' in path.parts:raise JobError('escaping directory path')
 fd=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  for i,part in enumerate(path.parts[1:],2):
   if create:
    try:os.mkdir(part,0o700,dir_fd=fd)
    except FileExistsError:pass
   nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|(0 if trusted_link(Path(*path.parts[:i])) else os.O_NOFOLLOW),dir_fd=fd);os.close(fd);fd=nxt
  return fd
 except BaseException:os.close(fd);raise
def validate(j):
 if not isinstance(j,dict) or type(j.get('schema_version')) is not int or j.get('schema_version')!=VERSION:raise JobError('unknown or malformed job schema; inspect with compatible package')
 if len(canonical(j))>MAX_STATE_BYTES:raise JobError('job state exceeds byte limit; retain existing history and inspect without truncation')
 from core import schema as published_schema
 try:
  contract=published_schema.load_schema_file(Path(__file__).resolve().parents[2]/'shared'/'agents'/'job.schema.json')
  problems=published_schema.errors(j,contract)
  if problems:raise JobError('published job schema violations: '+'; '.join(problems[:10]))
 except Exception as exc:raise JobError(f'schema_invalid: job does not match published job schema: {exc}') from exc
 if not j['owner'] or not j['requirements']:raise JobError('owner and requirements must be nonempty')
 if any(not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',k) or not isinstance(v,str) or not v for k,v in j['requirements'].items()):raise JobError('requirements need safe IDs and nonempty statements')
 stages=j['stages'];current=j['tasks'];ids={s['id'] for s in stages};deps={s['id']:s.get('depends_on',[]) for s in stages}
 if len(ids)!=len(stages):raise JobError('duplicate stage id')
 if any(r not in j['requirements'] for s in stages for r in s.get('requirements',[])):raise JobError('stage references undeclared requirement')
 if any(d not in ids for values in deps.values() for d in values):raise JobError('unknown stage dependency')
 try:tuple(graphlib.TopologicalSorter(deps).static_order())
 except graphlib.CycleError as exc:raise JobError('cyclic stage dependency') from exc
 if len({t['task_id'] for t in current})!=len(current) or len({t['request_id'] for t in current})!=len(current):raise JobError('duplicate task or request ID')
 if len({(t['stage_id'],t['logical_slot_id']) for t in current})!=len(current):raise JobError('duplicate logical task slot')
 for t in current:
  if t['stage_id'] not in ids:raise JobError('task references unknown stage')
  if j['pins'] and t.get('dependency_key') not in j['pins']:raise JobError('task references undeclared dependency pin')
  scope=t.get('write_scope',{'mode':'coordinator-only'})
  if scope['mode']=='worker-evidence' and scope.get('path')!='artifacts/tasks/'+t['task_id']:raise JobError('worker scope must be its exact assigned task subtree')
 if any(t['request_id'] in requests(j,t['task_id']) for t in j['tasks']):raise JobError('request ID is retained by another task execution')
 keys=[d['key'] for d in j['dependencies']]
 if len(set(keys))!=len(keys):raise JobError('duplicate dependency key')
 if set(j['pins'])!=set(keys):raise JobError('pin/dependency mismatch')
 for key,value in j['policy'].items():
  if key.endswith('_bytes') and key!='max_artifact_bytes' and (type(value) is not int or value<1):raise JobError(f'invalid integer policy limit: {key}')
 return j
def trusted_link(p):  # Root-owned symlink whose every ancestor is a root-owned directory no group/other can write (macOS /var, /tmp): only root can swap it.
 try:return '..' not in Path(p).parts and stat.S_ISLNK((s:=os.lstat(p)).st_mode) and s.st_uid==0 and all((a:=os.stat(d)).st_uid==0 and not a.st_mode&0o022 for d in Path(p).absolute().parents)
 except OSError:return False
def _reject_symlink_components(path):
 if bad:=next((c for c in (Path(*Path(path).absolute().parts[:i]) for i in range(2,len(Path(path).absolute().parts)+1)) if c.is_symlink() and not trusted_link(c)),None):raise JobError(f'symlink in job state path: {bad}')
def _authorize(job,caller,operation):
 if not isinstance(caller,dict):raise JobError('caller metadata is required')
 if caller.get('installation_id')!=job['installation_id'] or caller.get('workflow')!=job['workflow'] or caller.get('package_digest') not in {p['package_digest'] for p in job['pins'].values()}:raise JobError('ownership_mismatch: wrong-package/installation/workflow caller')
 if caller.get('actor') not in ('coordinator','worker'):raise JobError('explicit caller actor is required')
 if caller['actor']!='coordinator' and operation!='worker-evidence':raise JobError('coordinator-only operation')
GUARDED_OPERATIONS=frozenset(('create','plan-revision','prepare','acceptance'))
def guard_operations(job):
 value=(job or {}).get('policy',{}).get('transaction_guard_required',[])
 if not isinstance(value,list) or any(x not in GUARDED_OPERATIONS for x in value) or len(value)!=len(set(value)):raise JobError('invalid transaction_guard_required operations')
 return set(value)
def require_guard(before,proposed,operation,guard):
 old,new=guard_operations(before),guard_operations(proposed)
 if not old<=new:raise JobError('transaction guard policy cannot be removed')
 if new-old and not callable(guard):raise JobError('required transaction guard missing for policy introduction')
 if operation in old|new and not callable(guard):raise JobError('required transaction guard missing for '+operation)
 if guard is not None and not callable(guard):raise JobError('transaction guard must be callable')
@contextlib.contextmanager
def guarded(guard,before,operation,context):
 # Trusted Python callback from the pinned adapter, never executable job data.
 if guard is None:yield lambda proposed:None;return
 frozen=copy.deepcopy(context or {})
 with guard(copy.deepcopy(before),operation,copy.deepcopy(frozen)) as final:
  if not callable(final):raise JobError('transaction guard must yield a final check')
  yield lambda proposed:final(copy.deepcopy(before),copy.deepcopy(proposed),copy.deepcopy(frozen))
class Store:
 def __init__(self,state_root,job_id,verify_pins=None,verify_brief=None):
  if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',job_id):raise JobError('unsafe job id')
  self.root=Path(state_root).expanduser().absolute();self.path=self.root/job_id;self.file=self.path/'job.json';self.lock=self.path/'job.lock';self.verify_pins=verify_pins;self.verify_brief=verify_brief
 def locked(self):
  for path,label in ((self.root,'state root'),(self.path,'job directory')):
   _reject_symlink_components(path);os.close(_directory_fd(path,create=True))
   if stat.S_IMODE(path.stat().st_mode)&0o077:raise JobError(label+' permissions must be private (0700)')
  parent=_directory_fd(self.path)
  try:fd=os.open(self.lock.name,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
  finally:os.close(parent)
  if not stat.S_ISREG(os.fstat(fd).st_mode):os.close(fd);raise JobError('unsafe lock')
  fcntl.flock(fd,fcntl.LOCK_EX);return fd
 def load(self):return validate(strict_load(_regular(self.file,max_bytes=MAX_STATE_BYTES)))
 def create(self,j,*,commit_guard=None,commit_context=None):
  validate(j);fd=self.locked()
  try:
   if self.file.exists():raise JobError('job already exists')
   require_guard(None,j,'create',commit_guard)
   with guarded(commit_guard,None,'create',commit_context) as final:
    validate(j);final(j);_atomic(self.file,canonical(j));self.overview(j)
  finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
 def mutate(self,caller,fn):return self.transact(caller,fn,_replace=True)
 def transact(self,caller,fn,operation='mutate',*,commit_guard=None,commit_context=None,_replace=False):
  fd=self.locked()
  try:
   j=self.verified_load();_authorize(j,caller,operation);old=canonical(j);before=copy.deepcopy(j)
   require_guard(before,before,operation,commit_guard)
   if operation=='mutate' and guard_operations(before):raise JobError('guarded jobs require the explicit transaction operation')
   if (j.get('status')=='cancelled' or j.get('discard_requested')) and operation not in ('task-observation','cancel','discard'):raise JobError('job is cancelled or discarded')
   context={**copy.deepcopy(commit_context or {}),'caller':copy.deepcopy(caller)}
   with guarded(commit_guard,before,operation,context) as final:
    result=fn(j)
    # A mutate replacement must not overwrite the callback's original object.
    if _replace:j=result or j
    validate(j);require_guard(before,j,operation,commit_guard)
    if guard_operations(before) or guard_operations(j):
     authored=('requirements','authorization','constraints','dependencies','pins','policy','model_selection','model_selection_sha256','invocation_id','scope_id')
     if operation not in GUARDED_OPERATIONS and any(before.get(k)!=j.get(k) for k in authored):raise JobError('guarded plan changes require plan-revision')
    final(j)  # Also runs for a no-op, including final acceptance authorization.
    if canonical(j)!=old:_atomic(self.file,canonical(j));self.overview(j)
    return j if _replace or result is None else result
  finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
 def verified_load(self):
  job=self.load()
  if any('package_dir' in pin for pin in job['pins'].values()):
   if not callable(self.verify_pins):raise JobError('stored dependency verifier is required before mutation')
   self.verify_pins(job)
  return job
 def overview(self,j=None,persist=True):
  j=j or self.load();covered={r:[] for r in j['requirements']}
  for s in j['stages']:
   for r in s.get('requirements',[]):covered[r].append({'stage':s['id'],'status':s['status']})
  pending=[s for s in j['stages'] if s['status'] not in ('accepted-at-snapshot','cancelled')]
  view={'schema_version':1,'job_id':j['job_id'],'workflow':j['workflow'],'status':j.get('status','running'),'stages':j['stages'],'requirement_coverage':covered,'current_stage':pending[0]['id'] if pending else None,'decisions':j['decisions'],'blockers':j.get('blockers',[]),'handles':[{'task_id':t['task_id'],'status':t.get('status','pending'),'handles':t.get('handles',[]),'followups':t.get('followups',[]),'uncertain_calls':t.get('uncertain_calls',0),'blocked_reason':t.get('blocked_reason')} for t in j['tasks']],'evidence':j.get('evidence',[]),'gaps':j.get('gaps',[]),'fallbacks':j.get('fallbacks',[]),'approval_waits':j.get('approval_waits',[])}
  if persist:_atomic(self.path/'overview.json',canonical(view))
  return view
