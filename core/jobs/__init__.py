"""Generic job planning, storage, immutable brief preparation and lifecycle records."""
from __future__ import annotations
import copy, json, os, shlex
from pathlib import Path
from .store import Store, JobError, canonical, digest, validate, requests, tasks as _tasks, _atomic, _authorize, _regular, _retain, strict_load
def _completion_taken(j,cid,request):return any(n.get('completion_id')==cid and n.get('request_id')!=request for n in j.get('notifications',[])+[x for t in _tasks(j) for x in t.get('execution_history',[])])  # completion IDs bind one request across current and superseded tasks
def _slot_followups(j,t):return {f['request_id'] for x in _tasks(j) if (x['stage_id'],x['logical_slot_id'])==(t['stage_id'],t['logical_slot_id']) for f in x.get('followups',[])}  # follow-up budget is per logical slot, like attempts
def _open_findings(t):return any(d.get('finding',{}).get('severity') in ('blocker','major') and (d.get('disposition') not in ('fixed','rejected') or not d.get('evidence')) for d in t.get('finding_dispositions',[]))
def _owner_current(d,limit):  # Re-read owner decision bytes at each use; changed source/hash/quote fails closed.
    try:raw=_regular(Path(d['source']),max_bytes=limit);return __import__('re').fullmatch(r'[0-9a-f]{64}',str(d.get('source_sha256',''))) is not None and digest(raw)==d['source_sha256'] and bool(d.get('quote')) and d['quote'] in raw.decode('utf-8')
    except (OSError,ValueError,KeyError,TypeError):return False
_RESULT_STATUS={'ready-for-acceptance':'awaiting-acceptance','needs-followup':'awaiting-followup','blocked':'blocked','failed':'failed','malformed-result':'failed'}
def _result_status(t):return ('stale' if t.get('inputs_stale') else _RESULT_STATUS.get(t.get('last_execution_status'),'failed')) if any(x.get('request_id')==t['request_id'] for x in t.get('execution_history',[])) else None  # only the ingested current result sets acceptance status
def _spent(s):return s.get('validated_cycle')==s.get('cycle',0)  # this pass was already validated; new executions need a charged pass
def _live_handles(task):
    return any(h.get('status') not in ('completed','failed','cancelled','interrupted') or h.get('has_pending_child_runs') or h.get('work_state')!='result_available' for h in task.get('handles',[])+task.get('followups',[]))
def _uningested(task): return any(h.get('status') in ('completed','failed','cancelled','interrupted') and not h.get('has_pending_child_runs') and h.get('work_state')=='result_available' and not any(x.get('request_id')==h.get('request_id') for x in task.get('execution_history',[])) for h in task.get('handles',[])+task.get('followups',[]))  # terminal work whose result was never ingested is still an obligation
def _record_identity(j,t,h,e):
    previous=h.get('observed_identity',{});s=copy.deepcopy(previous.get('sources',{}));observed=e.get('observed_identity',e.get('observed'));names={'status':'status','receipt':'receipt','configuration':'configuration','thread-configuration':'configuration'};inputs={k:e.get(k+'_identity',(observed or {}).get(k) if isinstance(observed,dict) else None) for k in ('status','receipt','configuration')}
    if isinstance(observed,dict) and observed.get('source'):inputs[names[observed['source']]]=observed
    for source,value in inputs.items():
        if isinstance(value,dict):row=s.setdefault(source,{});provider=value.get('providerInstanceId',value.get('provider_instance_id'));model=value.get('model',value.get('model_id',value.get('modelId')));row.update({'providerInstanceId':provider} if isinstance(provider,str) and provider else {});row.update({'model':model} if isinstance(model,str) and model else {})
    target=h.get('target') or t.get('target') or {};tp=target.get('providerInstanceId');tm=target.get('model');bad=previous.get('status')=='mismatched' or any(v.get('providerInstanceId') is not None and v.get('providerInstanceId')!=tp or v.get('model') is not None and v.get('model')!=tm for v in s.values());p=s.get('status',{}).get('providerInstanceId');m=s.get('status',{}).get('model') or next((s[k].get('model') for k in ('receipt','configuration') if k in s and s[k].get('model')),None);verified=bool(tp and tm and p==tp and any(v.get('model')==tm for v in s.values()))
    h['observed_identity']={'status':'mismatched' if bad else 'verified' if verified else 'unreported','sources':s,'providerInstanceId':p,'model':m}
    if bad and not any(b.get('kind')=='identity-mismatch' and b.get('request_id')==h.get('request_id') and b.get('host_task_id')==h.get('task_id') for b in j.get('blockers',[])):j.setdefault('blockers',[]).append({'kind':'identity-mismatch','task_id':t['task_id'],'request_id':h.get('request_id'),'host_task_id':h.get('task_id'),'providerInstanceId':p,'expectedProviderInstanceId':tp,'model':m,'cycle':h.get('cycle',t.get('cycle',0)),'reconciled':None})
    if h['observed_identity']['status']!='mismatched':
        for b in j.get('blockers',[]):b.get('kind')=='identity-mismatch' and b.get('task_id')==t['task_id'] and b.get('request_id')!=h.get('request_id') and b.get('cycle',-1)<h.get('cycle',t.get('cycle',0)) and b.update(superseded_by=h.get('request_id'))
def _quarantine_result(store,t,r):
    request=r['request_id'];h=next((x for x in t.get('followups',[]) if x.get('request_id')==request and x.get('forbidden_followup')),None)
    if not h:return False
    if not r.get('completion_id'):raise JobError('result completion_id is required for idempotent ingestion')
    if any(x.get('completion_id')==r['completion_id'] for x in t.get('execution_history',[])):return True
    raw=bytes(r['result']);path=store.path/'results'/'quarantine'/(request+'.json');_retain(path,raw,'quarantined result bytes differ');t['attempt']+=1;t.setdefault('execution_history',[]).append({'request_id':request,'completion_id':r['completion_id'],'accepted_execution':False,'quarantined':True,'reason':'forbidden continued review or document-only follow-up','result_sha256':digest(raw),'transport_ref':{'transport_path':str(path),'transport_sha256':digest(raw)}});return True
def _retain_forbidden(j,t,e,parent):
    h={'task_id':e['host_task_id'],'host_task_id':e['host_task_id'],'request_id':e['request_id'],'parent_task_id':parent.get('task_id'),'child_thread_id':e.get('child_thread_id'),'status':e.get('status','running'),'work_state':e.get('work_state','working'),'has_pending_child_runs':e.get('has_pending_child_runs',False),'target':e.get('target'),'scope':e.get('scope'),'forbidden_followup':True,'cycle':t.get('cycle',0)};t.setdefault('followups',[]).append(h);t.setdefault('forbidden_followups',[]).append({'request_id':e['request_id'],'host_task_id':e['host_task_id'],'reconciled':None});j.setdefault('blockers',[]).append({'kind':'forbidden-followup','task_id':t['task_id'],'request_id':e['request_id'],'host_task_id':e['host_task_id'],'reconciled':None});_record_identity(j,t,h,e);t.setdefault('dispatch_history',[]).append(e)
def _open_dispatch(t):  # Unreconciled conflicting host IDs or forbidden work blocks replacement and acceptance.
    f=t.get('followup_dispatch') or {};return 'a conflicting host handle remains unreconciled' if any(not c.get('reconciled') for c in t.get('host_conflicts',[])) else 'a forbidden follow-up remains unreconciled' if any(not c.get('reconciled') for c in t.get('forbidden_followups',[])) else 'uncertain follow-up dispatch lacks an authoritative host observation' if f.get('uncertain_calls') and not any(h.get('request_id')==f.get('request_id') for h in t.get('handles',[])+t.get('followups',[])) else ''
def _unsettled(j,t):return _open_dispatch(t) or ('uncertain or blocked dispatch lacks an authoritative host observation' if t.get('blocked_reason') or t.get('uncertain_calls') and not any(h.get('request_id')==t['request_id'] for h in t.get('handles',[])+t.get('followups',[])) else 'a conflicting host handle remains unreconciled in job blockers' if any(b.get('kind')=='conflicting-host-handle' and b.get('task_id')==t['task_id'] and not b.get('reconciled') for b in j.get('blockers',[])) else 'owned host work is not terminal with result_available' if _live_handles(t) else 'owned terminal work has no ingested result' if _uningested(t) else '')  # A plan decision never proves termination, absence or that a claimed result was read.
def create_job(payload,state_root,pins):
    """Persist a fully formed plan and externally verified immutable pin snapshot.""";j=copy.deepcopy(payload);j.setdefault('schema_version',1);j['pins']=copy.deepcopy(pins)
    for key in ('max_repair_cycles','max_live_workers'):
        if key not in j.get('policy',{}) and len({canonical(pin.get('limits',{}).get(key)) for pin in pins.values()})>1:raise JobError('conflicting pin limits require explicit job policy')
    limits=next(iter(pins.values()),{}).get('limits',{})
    for key,value in (('max_repair_cycles',limits.get('max_repair_cycles',20)),('max_artifact_bytes',16*1024*1024),('max_live_workers',limits.get('max_live_workers'))):
        j.setdefault('policy',{}).setdefault(key,value)
    for s in j['stages']:
        s.setdefault('attempts',{'primary':0,'support':0,'review':0,'final':0});s.setdefault('acceptance',None)
    for t in j['tasks']:
        t.setdefault('status','pending');t.setdefault('attempt',0);t.setdefault('handles',[]);t.setdefault('followups',[]);t.setdefault('dispatch_retries',0)
    store=Store(state_root,j['job_id']);store.create(j);return {'job':str(store.file),'overview':str(store.path/'overview.json')}
def prepare(store, caller, task_id, verify_pin, verify_acceptance, target_reason='configured worker'):
    if not callable(verify_pin):raise JobError('pinned dependency verifier is required')
    def check(job):
        for dep in job['dependencies']:
            if verify_pin(dep,job['pins'][dep['key']]) is not True:raise JobError('pin_mismatch: pinned dependency verification failed')
    store.verify_pins=check
    def apply(j):
        task=next((t for t in j['tasks'] if t['task_id']==task_id),None)
        if task is None or task.get('status') not in ('pending','stale','blocked'):raise JobError('task is undeclared or already launched')
        if _live_handles(task) or _uningested(task):raise JobError('owned terminal work has no ingested result; read it before fresh preparation' if _uningested(task) else 'owned handles must be reconciled before fresh preparation')  # re-preparing would clear a launched request's stale inputs
        if task.get('uncertain_calls') and not any(h.get('request_id')==task['request_id'] for h in task.get('handles',[])+task.get('followups',[])) or task.get('blocked_reason')=='uncertain_dispatch' or _open_dispatch(task):raise JobError(_open_dispatch(task) or 'uncertain original must be reconciled before fresh preparation')
        stage=next(s for s in j['stages'] if s['id']==task['stage_id'])
        if _spent(stage) or task.get('attempt',0) and (task.get('status')=='stale' or task.get('inputs_stale')):raise JobError('stale reexecution or a new execution in a validated pass requires a charged repair pass')
        if task.get('attempt',0)>=1+j['policy']['max_repair_cycles']:raise JobError('attempt_budget_exhausted: task execution budget exhausted')
        for dep in stage.get('depends_on',[]):
            if not callable(verify_acceptance) or verify_acceptance(dep) is not True:raise JobError('predecessor acceptance is not current')
        pin=j['pins'][task['dependency_key']];effective=pin['effective_workers'].get(task['worker_id'])
        if not effective:raise JobError('worker missing from pinned dependency')
        consumed=[output for prior in j['stages'] if prior['id'] in stage.get('depends_on',[]) for output in prior.get('outputs',[])]
        req=task.get('requirements',stage['requirements']);brief={'schema_version':1,'job_id':j['job_id'],'stage_id':task['stage_id'],'logical_slot_id':task['logical_slot_id'],'task_id':task_id,'request_id':task['request_id'],'worker_id':task['worker_id'],'objective':j.get('objective',''),'requirements':[{'id':r,'statement':j['requirements'][r]} for r in req],'authorization':j['authorization'],'constraints':j['constraints'],'snapshot':j.get('snapshot'),'dependency_pins':j['pins'],'consumed_outputs':consumed,'effective_definition':effective,'target_reason':target_reason,'attempt':task.get('attempt',0),'max_attempts':1+j['policy']['max_repair_cycles'],'stop_conditions':stage.get('stop_conditions',[]),'result_contract':j['result_contract'],'write_scope':task.get('write_scope',{'mode':'coordinator-only'}),'revision':stage.get('revision'),'target':task.get('target'),'resources':stage.get('resources',{}),'role':task.get('role','worker'),'review_inputs':task.get('review_inputs',{}),'owner_decisions':[d for d in j['decisions'] if d.get('scope')=='waiver:'+task_id]}
        if task.get('context_policy')=='document-only':
            document=task.get('document',{})
            if not document.get('path') or digest(_regular(Path(document['path']),max_bytes=j['policy']['max_artifact_bytes']))!=document.get('sha256'):raise JobError('document bytes differ from the declared read scope')
            if pin.get('task_contract'):raise JobError('document-only definition cannot include a job task contract')
            for key in ('objective','consumed_outputs','resources','target_reason','target','revision','owner_decisions'):brief.pop(key,None)
            brief.update(result_contract={'schema_version':1,'transport':'worker-result-v1'},stop_conditions=['Stop if the supplied document is unreadable or its hash differs.'],revision=None);brief.update(document=document,requirements=[{'id':r} for r in req],authorization={'read':[document['path']],'write':task.get('write_scope',{})},constraints=['Read only the supplied document and procedural definition; no other job context or child work.'],snapshot={'sha256':digest(canonical(j.get('snapshot')))},dependency_pins={task['dependency_key']:{k:pin[k] for k in ('package_digest','bundle_digest')}},target_reason='declared document-only scope')
        brief['effective_brief_sha256']=digest(canonical(brief));raw=canonical(brief);path=store.path/'briefs'/(task_id+'-'+digest(task['request_id'].encode())+'.json')
        _retain(path,raw,'immutable brief changed; an explicit new attempt is required');task['brief']={key:brief[key] for key in ('job_id','stage_id','logical_slot_id','task_id','request_id','worker_id','effective_brief_sha256','revision','snapshot')}
        task['brief'].update(path=str(path),sha256=digest(raw));task['cycle']=stage.get('cycle',0);task.pop('inputs_stale',None)  # the execution belongs to this pass under the current contract
        return {'path':str(path),'sha256':digest(raw),'bytes':len(raw),'provenance':{key:brief[key] for key in ('job_id','stage_id','task_id','request_id')}}
    return store.transact(caller,apply,'prepare')
def record_result(store,caller,task_id,result,result_parser=None):
    from .results import parse_result
    parser=result_parser or parse_result
    def apply(j):
        task=next((t for t in j['tasks'] if t['task_id']==task_id),None)
        if task is None:raise JobError('unknown task slot')
        if not isinstance(result,dict) or not isinstance(result.get('result'),(bytes,bytearray)):raise JobError('result ingestion requires raw result bytes')
        request=result.get('request_id')
        if not isinstance(request,str) or not request:raise JobError('authoritative ingestion request_id is required')
        handles=task.get('handles',[])+task.get('followups',[])
        if (handles or request!=task['request_id'] or task.get('uncertain_calls') or task.get('blocked_reason')) and not any(h.get('request_id')==request for h in handles):raise JobError('result is not for an owned request')
        if _completion_taken(j,result.get('completion_id'),request):raise JobError('completion notification belongs to another request')
        if _quarantine_result(store, task, result): return task
        brief=task.get('brief') if request==task['request_id'] else {'path':str(store.path/'briefs'/('followup' if any(h.get('request_id')==request for h in task.get('followups',[])) else '')/(task_id+'-'+digest(request.encode())+'.json'))}
        if not isinstance(brief,dict):raise JobError('task has no prepared immutable brief correlation')
        brief_raw=_regular(Path(brief['path']))
        if 'sha256' in brief and digest(brief_raw)!=brief['sha256']:raise JobError('prepared brief bytes changed')
        assigned=strict_load(brief_raw)
        if request!=task['request_id']:brief=assigned
        if assigned.get('request_id')!=request or assigned.get('effective_brief_sha256')!=brief['effective_brief_sha256']:raise JobError('prepared brief correlation changed')
        expected={key:brief[key] for key in ('job_id','stage_id','logical_slot_id','request_id','worker_id','effective_brief_sha256')}
        expected.update(role=assigned.get('role','worker'),revision=brief.get('revision'),binding=brief.get('snapshot'),requirements=[r['id'] for r in assigned['requirements']],task_id=task_id,owner_waivers=[d for d in j['decisions'] if d.get('scope')=='waiver:'+task_id and _owner_current(d,j['policy']['max_artifact_bytes'])],waivable_requirements=j['policy'].get('waivable_requirements',[]));completion_id=result.get('completion_id')
        if not isinstance(completion_id,str) or not completion_id:raise JobError('result completion_id is required for idempotent ingestion')
        if any(x.get('completion_id')==completion_id for x in task.get('execution_history',[])):return task
        if any(x.get('request_id')==request for x in task.get('execution_history',[])):raise JobError('request execution result already ingested')
        if task['attempt']>=1+j['policy']['max_repair_cycles'] and not any(h.get('request_id')==request for h in handles):raise JobError('attempt_budget_exhausted: attempt budget exhausted')
        transport=store.path/'results'/(request+'.json');_retain(transport,bytes(result['result']),'result transport for this request is already retained for another execution')
        task['attempt']+=1
        try:parsed=parser(bytes(result['result']),expected,store.path if task.get('write_scope',{}).get('mode')=='worker-evidence' else None,j['policy']['max_artifact_bytes'])
        except Exception as exc:
            if request==task['request_id']:task.update(status='stale' if task.get('inputs_stale') else 'failed',last_execution_status='malformed-result',last_completion_id=completion_id)
            task.setdefault('execution_history',[]).append({'request_id':request,'completion_id':completion_id,'accepted_execution':True,'malformed':True,'reason':str(exc),'result_sha256':digest(bytes(result['result'])),'transport_ref':{'transport_path':str(transport),'transport_sha256':digest(bytes(result['result']))}});return task
        task.setdefault('finding_dispositions',[])
        for finding in parsed['result']['findings']:
            if not any(d.get('finding_id')==finding['id'] and d.get('finding')==finding for d in task['finding_dispositions']):  # changed content under a reused ID is a distinct obligation
                task['finding_dispositions'].append({'finding_id':finding['id'],'finding':finding,'finding_sha256':digest(canonical(finding)),'request_id':request,'disposition':None})
        if request!=task['request_id']:
            task.setdefault('execution_history',[]).append({'request_id':request,'result':parsed['result'],'completion_id':completion_id,'sha256':parsed['sha256'],'accepted_execution':True,'transport_ref':{'kind':parsed['kind'],'transport_path':str(transport),'transport_sha256':digest(bytes(result['result']))}});return task
        task['status']='stale' if task.get('inputs_stale') else _RESULT_STATUS[parsed['result']['status']]
        task['result_ref']={'sha256':parsed['sha256'],'kind':parsed['kind'],'bytes':parsed['bytes'],'transport_path':str(transport),'transport_sha256':digest(bytes(result['result']))};task.update(last_execution_status=parsed['result']['status'],last_completion_id=completion_id)
        task.setdefault('execution_history',[]).append({'request_id':request,'result':parsed['result'],'completion_id':completion_id,'sha256':parsed['sha256'],'accepted_execution':True,'transport_ref':task['result_ref']});return task
    return store.transact(caller,apply,'result')
def decision(store,caller,decision):
    def apply(j):
        if not isinstance(decision,dict) or not decision.get('quote') or not decision.get('source') or not decision.get('source_sha256') or not decision.get('scope') or not __import__('re').fullmatch(r'[0-9a-f]{64}',str(decision.get('source_sha256',''))):raise JobError('owner decision needs quote, source, SHA-256 and scope')
        source=Path(decision['source'])
        if not source.is_absolute() or Path(os.path.realpath(source)).is_relative_to(Path(os.path.realpath(store.path))):raise JobError('owner decision source must be outside job state and worker write scopes')
        raw=_regular(source,max_bytes=j['policy']['max_artifact_bytes'])
        if not source.is_absolute() or digest(raw)!=decision['source_sha256'] or decision['quote'] not in raw.decode('utf-8'):raise JobError('owner decision source bytes/hash/quote differ')
        if any(d.get('id')==decision.get('id') for d in j['decisions']):raise JobError('owner decision ID already recorded')
        if decision['scope'].startswith('waiver:') and (not isinstance(decision.get('requirement_ids'),list) or not decision['requirement_ids'] or any(r not in j['requirements'] for r in decision['requirement_ids'])):raise JobError('waiver requires explicit job requirement IDs; execution also requires policy permission')
        j['decisions'].append(decision);j['history'].append({'kind':'owner-decision','decision_id':decision.get('id')})
    return store.transact(caller,apply,'decision')
def cancel(store,caller,reason):return store.transact(caller,lambda j:j.update(status='cancelled') or j.setdefault('blockers',[]).append({'kind':'cancelled','reason':reason}),'cancel')
def discard(store,caller,reason):
    # Explicitly records archival intent; state and artifacts remain immutable/history-preserving.
    return store.transact(caller,lambda j:j.update(discard_requested={'reason':reason,'artifacts_preserved':True}),'discard')
def record_dispatch(store,caller,task_id,event):
    """Record host observations; no event dispatches, replaces or cancels work."""
    def apply(j):
        t=next((x for x in j['tasks'] if x['task_id']==task_id),None)
        if t is None or not isinstance(event,dict):raise JobError('unknown task or malformed host observation')
        kind=event.get('kind');request=event.get('request_id')
        recovery=kind=='accepted' and t.get('uncertain_calls') and request==t['request_id'] and not any(h.get('request_id')==request for h in t.get('handles',[])+t.get('followups',[])) or kind=='followup' and (t.get('followup_dispatch') or {}).get('uncertain_calls') and request==(t.get('followup_dispatch') or {}).get('request_id')  # a strictly correlated rediscovery of an already-launched, lost-response original or follow-up; never a fresh launch
        terminal=('completed','failed','cancelled','interrupted');forbidden_role=t.get('role')=='review' or t.get('context_policy')=='document-only';parent=next((h for h in t.get('handles',[])+t.get('followups',[]) if h.get('task_id',h.get('host_task_id'))==event.get('parent_host_task_id')),None);retained_forbidden=kind=='followup' and forbidden_role and parent and parent.get('status') in terminal and not parent.get('has_pending_child_runs') and parent.get('work_state')=='result_available'
        if (j.get('status')=='cancelled' or j.get('discard_requested')) and not recovery and not retained_forbidden and (kind not in ('completion','reconciled','approval-resolved') or kind!='approval-resolved' and (event.get('status') not in terminal or event.get('has_pending_child_runs'))):raise JobError('cancelled job permits only terminal reconciliation')
        t.setdefault('handles',[]);t.setdefault('followups',[]);t.setdefault('dispatch_retries',0)
        handles=t['handles']+t['followups'];host_id=event.get('host_task_id');handle=next((h for h in handles if h.get('task_id',h.get('host_task_id'))==host_id),None)
        if kind not in ('followup','completion','reconciled','identity') and request!=t['request_id']:raise JobError('request differs from declared slot')
        if kind in ('accepted','followup') and any(h.get('task_id',h.get('host_task_id'))==host_id and h.get('request_id')!=request for slot in _tasks(j) for h in slot.get('handles',[])+slot.get('followups',[])):raise JobError('host handle already belongs to another request')
        if kind=='accepted':
            previous=next((h for h in handles if h['request_id']==request),None)
            if previous:
                if previous.get('task_id',previous.get('host_task_id'))==host_id:return
                raise JobError('request already has an accepted host handle')
            if not host_id or _live_handles(t):raise JobError('accepted observation requires an unlaunched slot and host ID')
            t.pop('blocked_reason',None);accepted_handle={'task_id':host_id,'request_id':request,'child_thread_id':event.get('child_thread_id'),'status':event.get('status','running'),'work_state':event.get('work_state','working'),'has_pending_child_runs':event.get('has_pending_child_runs',False),'target':t.get('target'),'scope':t.get('write_scope'),'cycle':t.get('cycle',0)};t['handles'].append(accepted_handle);_record_identity(j,t,accepted_handle,event);t['status']='running'
        elif kind=='uncertain':
            if any(h.get('request_id')==request for h in handles):raise JobError('accepted request cannot become uncertain')
            calls=t.get('uncertain_calls',0)
            if calls>=3:raise JobError('uncertain_dispatch: uncertain dispatch original plus two retries exhausted')
            t['uncertain_calls']=calls+1;t['dispatch_retries']=calls;t['status']='awaiting-followup'
            if calls==2:t['blocked_reason']='uncertain_dispatch';t['status']='blocked'
        elif kind=='capacity-deferred':
            if any(h.get('request_id')==request for h in handles+t.get('execution_history',[])):raise JobError('an accepted or executed request cannot become a capacity deferral')
            notification=event.get('completion_id')
            if t.get('capacity_deferred') and not notification or notification in {e for x in _tasks(j) for e in x.get('capacity_retry_events',[])}:raise JobError('capacity retry requires a new owned completion notification')
            if notification:
                if not any(n.get('completion_id')==notification for n in j.get('notifications',[])):raise JobError('capacity notification was not observed')
                t.setdefault('capacity_retry_events',[]).append(notification)
            t['capacity_deferred']=True;t['status']='stale' if t.get('status')=='stale' else 'pending'  # a deferral never clears staleness
        elif kind in ('reconciled','completion','identity'):
            if not handle or request!=handle['request_id']:raise JobError('observation is not for an owned original handle')
            if kind == 'identity':
                _record_identity(j,t,handle,event);t.setdefault('dispatch_history', []).append(event);return
            terminal=event.get('status') in ('completed','failed','cancelled','interrupted')
            if kind=='completion' and (not event.get('completion_id') or _completion_taken(j,event['completion_id'],request)):raise JobError('completion identity is required and cannot belong to another request')
            key=(host_id,event.get('completion_id'));seen={(n.get('host_task_id'),n.get('completion_id')) for n in j.setdefault('notifications',[])}
            if kind=='completion' and key in seen:return
            for field in ('status','work_state','has_pending_child_runs'):
                if field not in event:raise JobError('authoritative observation missing '+field)
                handle[field]=event[field]
            if kind == 'completion':
                _record_identity(j,t,handle,event)
            if kind == 'reconciled':
                _record_identity(j,t,handle,event)
                if terminal and not event.get('has_pending_child_runs') and event.get('work_state') not in ('working','waiting_for_children'):
                    for b in j.get('blockers',[]):
                        if b.get('task_id')==task_id and b.get('request_id')==request and b.get('host_task_id')==host_id and b.get('kind') in ('identity-mismatch','forbidden-followup'):b['reconciled']={key:event[key] for key in ('status','work_state','has_pending_child_runs')};[x.update(reconciled=b['reconciled']) for x in t.get('forbidden_followups',[]) if x.get('request_id')==request and x.get('host_task_id')==host_id]
            if request==t['request_id']:
                t['status']=(_result_status(t) or ('stale' if t.get('inputs_stale') else 'awaiting-acceptance')) if terminal and event['work_state']=='result_available' and not event['has_pending_child_runs'] else 'running'
            if kind=='completion':j['notifications'].append(event)
            t.setdefault('reconciliation',[]).append(event)
        elif kind=='followup':
            parent=next((h for h in handles if h.get('task_id',h.get('host_task_id'))==event.get('parent_host_task_id')),None)
            if not parent or parent.get('status') not in ('completed','failed','cancelled','interrupted') or parent.get('has_pending_child_runs') or parent.get('work_state')!='result_available':raise JobError('followup parent is not confirmed terminal without pending runs')
            if not host_id or not request or request==parent['request_id'] or event.get('target')!=parent.get('target') or event.get('scope')!=parent.get('scope') or event.get('target')!=t.get('target') or event.get('scope')!=t.get('write_scope'):raise JobError('followup changed identity, model or authority')
            if any(h['request_id']==request and h.get('task_id')!=host_id for h in handles):raise JobError('request already has an accepted host handle')
            if any(h['request_id']==request for h in handles):return
            staged=t.get('prepared_followup',{})
            if t.get('role') == 'review' or t.get('context_policy') == 'document-only':
                _retain_forbidden(j,t,event,parent);return
            if not ((t.get('followup_dispatch') or {}).get('uncertain_calls') and (t.get('followup_dispatch') or {}).get('request_id')==request) and (t.get('attempt',0)>=1+j['policy']['max_repair_cycles'] or t.get('inputs_stale') or t.get('status')=='stale' or _spent(next(s for s in j['stages'] if s['id']==t['stage_id']))):raise JobError('stale, validated-pass or exhausted task requires a charged fresh preparation, not a follow-up')
            if len(_slot_followups(j,t))>=t.get('max_followups',1):raise JobError('attempt_budget_exhausted: declared followup budget exhausted')
            staged=t.get('prepared_followup',{})
            if staged.get('request_id')!=request:raise JobError('followup requires a prepared immutable brief')
            if digest(raw:=_regular(Path(staged['path'])))!=staged['sha256'] or t['request_id']!=strict_load(raw).get('followup_of') or t['request_id']!=parent['request_id']:raise JobError('prepared followup brief changed or follows a superseded request')
            t['brief']=t.pop('prepared_followup');t['request_id']=request
            followup={'task_id':host_id,'host_task_id':host_id,'request_id':request,'parent_task_id':parent.get('task_id'),'child_thread_id':event.get('child_thread_id'),'status':event.get('status','running'),'work_state':event.get('work_state','working'),'has_pending_child_runs':event.get('has_pending_child_runs',False),'target':strict_load(_regular(Path(staged['path']))).get('target',t.get('target')),'scope':t.get('write_scope'),'cycle':t.get('cycle',0)};t['followups'].append(followup);_record_identity(j,t,followup,event);t['status']='stale' if t.get('inputs_stale') else 'running'
        elif kind=='approval-wait':
            if not event.get('wait_id'):raise JobError('approval wait identity required')
            if not any(w.get('wait_id')==event['wait_id'] for w in j.setdefault('approval_waits',[])):j['approval_waits'].append(event)
        elif kind=='approval-resolved':
            j['approval_waits']=[w for w in j.get('approval_waits',[]) if w.get('wait_id')!=event.get('wait_id')]
        else:raise JobError('unknown host observation')
        t.setdefault('dispatch_history',[]).append(event)
    return store.transact(caller,apply,'task-observation')
def worker_write(store,caller,task_id,relative_path,data):
    """Write only declared task evidence using non-following directory handles."""
    def apply(j):
        task=next((t for t in j['tasks'] if t['task_id']==task_id),None)
        if task is None:raise JobError('unknown task slot')
        if any(h.get('request_id')==task['request_id'] for h in task.get('execution_history',[])):raise JobError('ingested task evidence is immutable')
        scope=task.get('write_scope',{});prefix=scope.get('path')
        if caller.get('actor')=='worker' and (caller.get('task_id')!=task_id or caller.get('stage_id')!=task['stage_id'] or caller.get('scope')!=scope or caller.get('package_digest')!=j['pins'][task['dependency_key']]['package_digest']):raise JobError('worker actor does not own assigned evidence')
        rel=Path(relative_path)
        if scope.get('mode')!='worker-evidence' or not isinstance(prefix,str) or not relative_path.startswith(prefix.rstrip('/')+'/') or rel.as_posix()!=relative_path or rel.is_absolute() or '..' in rel.parts:raise JobError('artifact_invalid: write outside assigned artifact subtree')
        if any(not __import__('re').fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',p) for p in rel.parts):raise JobError('artifact_invalid: unsafe artifact path')
        if any(a.get('path')==relative_path for h in task.get('execution_history',[]) for a in h.get('result',{}).get('artifacts',[])):raise JobError('prior execution evidence is immutable')
        if any(h.get('transport_ref',{}).get('kind')=='artifact' and strict_load(_regular(Path(h['transport_ref']['transport_path'])))['artifact']['path']==relative_path for h in task.get('execution_history',[])):raise JobError('prior full-result artifact is immutable')
        _atomic(store.path/rel,data);return {'path':str(store.path/rel),'sha256':digest(data),'bytes':len(data),'task_id':task_id}
    return store.transact(caller,apply,'worker-evidence')
def retry_task(store,caller,task_id,reason,category='primary'):
    """Reopen a failed task only within the persisted stage repair budget."""
    if category not in ('primary','support','review'):raise JobError('invalid retry category')
    def apply(j):
        t=next((x for x in j['tasks'] if x['task_id']==task_id),None)
        if t is None:raise JobError('unknown task slot')
        if _live_handles(t) or t.get('uncertain_calls') and not any(h.get('request_id')==t['request_id'] for h in t.get('handles',[])+t.get('followups',[])) or t.get('blocked_reason')=='uncertain_dispatch' or _open_dispatch(t) or _uningested(t):raise JobError(_open_dispatch(t) or (_uningested(t) and 'owned terminal work has no ingested result') or 'owned or uncertain original handles must be reconciled before retry')
        if t.get('status') not in ('failed','blocked','stale','awaiting-acceptance'):raise JobError('task is not eligible for retry')
        stage=next(s for s in j['stages'] if s['id']==t['stage_id']);counter=stage.setdefault('attempts',{}).setdefault(category,0)
        cur=stage.get('cycle',0);advance=t.get('cycle',cur if t.get('attempt') or t.get('handles') or t.get('followups') or t.get('execution_history') else 0)>=cur or _spent(stage)  # executed in this pass, executed but unbound, or a validated pass: charge
        if advance and stage.get('cycle',0)>=j['policy']['max_repair_cycles']:raise JobError('attempt_budget_exhausted: shared stage repair cycle budget exhausted')
        if t.get('attempt',0)>=1+j['policy']['max_repair_cycles']:raise JobError('attempt_budget_exhausted: task execution budget exhausted')
        if advance:stage['cycle']=stage.get('cycle',0)+1;stage['attempts'][category]=counter+1
        t['cycle']=stage['cycle'];t.pop('blocked_reason',None);t.pop('inputs_stale',None);t['uncertain_calls']=0;t['status']='pending';t.setdefault('retry_reasons',[]).append(reason);t.setdefault('original_request_id',t['request_id']);new=t['original_request_id'][:96]+'-'+digest(t['original_request_id'].encode())[:8]+'-a'+str(stage['cycle'])
        if new in requests(j):raise JobError('retry request ID is retained by job history')
        t.setdefault('retired_request_ids',[]).append(t['request_id']);t['request_id']=new;t.pop('brief',None)
    return store.transact(caller,apply,'retry')
def revise_plan(store,caller,revision,new_plan,adopt_dependencies=None):
    """Apply declared plan edits, requiring recorded owner evidence for expansion/weakening."""
    if not isinstance(revision,dict) or not revision.get('id'):raise JobError('revision needs a stable ID')
    required_decision=False;why=[];j=store.verified_load();_authorize(j,caller,'plan-revision')
    if any(r['revision']['id']==revision['id'] for r in j.get('plan_revisions',[])):raise JobError('plan revision ID already applied; use a new owner-bound revision')
    new_plan=copy.deepcopy(new_plan)
    for key in ('requirements','dependencies','stages','tasks','constraints','authorization','policy'):
        if key not in new_plan:new_plan[key]=j.get(key)
    new_plan['policy']={**j['policy'],**new_plan['policy']}
    task_contract={'task_id','stage_id','logical_slot_id','worker_id','dependency_key','target','write_scope','requirements','context_policy','document','max_followups','review_required','role','review_task_ids','reviewed_task_ids','reviewed_documents','independent_of_author','document_authors'};stage_contract={'id','depends_on','requirements','criteria','resources','validator_dependency','validator_contract','revision','outputs','stop_conditions','execution_mode','validator_limits','independent_of_author','lineage_waiver','document_authors'}
    for kind,contract in (('tasks',task_contract),('stages',stage_contract)):
        identity='task_id' if kind=='tasks' else 'id'
        for candidate in new_plan[kind]:
            old=next((x for x in j[kind] if x[identity]==candidate[identity]),None);runtime=(set(old)|set(candidate))-contract if old else set(candidate)-contract-{'request_id'}
            if old and any(k in candidate and candidate[k]!=old.get(k) for k in runtime):raise JobError('plan cannot supply runtime '+kind+' state')
            if not old and any(candidate[k] not in (None,0,False,'pending',[],{}) for k in runtime):raise JobError('new slots cannot supply performed runtime state')
            if old:candidate.update({k:copy.deepcopy(old[k]) for k in runtime if k in old})
    old_deps={x['key']:x['plugin'] for x in j['dependencies']};new_deps={x['key']:x['plugin'] for x in new_plan['dependencies']}
    added=set(new_deps)-set(old_deps);removed=set(old_deps)-set(new_deps);replaced={k for k in old_deps.keys()&new_deps.keys() if next(d for d in j['dependencies'] if d['key']==k)!=next(d for d in new_plan['dependencies'] if d['key']==k)};adoption=set(revision.get('adopt_keys',[]))
    if not adoption<=set(new_deps):raise JobError('adoption references undeclared dependencies')
    replaced|=adoption
    if added or removed or replaced:
        required_decision=True;why.append('dependency set or plugin changed')
    old_req=set(j['requirements']);new_req=set(new_plan['requirements'])
    if not old_req.issubset(new_req):required_decision=True;why.append('requirements removed')
    if any(key in new_req and new_plan['requirements'][key]!=j['requirements'][key] for key in old_req):required_decision=True;why.append('requirement changed')
    old_stage_ids={s['id'] for s in j['stages']};new_stage_ids={s['id'] for s in new_plan['stages']}
    if not old_stage_ids.issubset(new_stage_ids):required_decision=True;why.append('stages removed')
    if new_stage_ids-old_stage_ids:required_decision=True;why.append('stages added')
    old_task_ids={t['task_id'] for t in j['tasks']};new_task_ids={t['task_id'] for t in new_plan['tasks']}
    if old_task_ids-new_task_ids:
        required_decision=True;why.append('task slots removed');reason=next((_unsettled(j,t) or ('task retains an unresolved blocker or major finding' if _open_findings(t) else 'task is '+t['status']) for t in j['tasks'] if t['task_id'] in old_task_ids-new_task_ids and (_unsettled(j,t) or _open_findings(t) or t.get('status') in ('running','awaiting-followup','pending'))),None)
        if reason:raise JobError('cannot remove unreconciled task slots: '+reason)
    if new_task_ids-old_task_ids:required_decision=True;why.append('task slots added')
    if any(t.get('request_id') in requests(j) or t['task_id'] in {x['task_id'] for x in _tasks(j)} for t in new_plan['tasks'] if t['task_id'] not in old_task_ids) or (new_stage_ids-old_stage_ids)&{x['id'] for h in j['history'] for x in h.get('stages',[])}:raise JobError('new slots or stages cannot reuse a stage, task or request ID retained by job history')
    for old in j['stages']:
        new=next((s for s in new_plan['stages'] if s['id']==old['id']),None)
        if new and (set(old['requirements'])!=set(new['requirements']) or set(old.get('depends_on',[]))!=set(new.get('depends_on',[])) or sorted(old.get('criteria',[]),key=canonical)!=sorted(new.get('criteria',[]),key=canonical) or any(old.get(k)!=new.get(k) for k in ('validator_contract','validator_dependency','execution_mode','outputs','validator_limits','stop_conditions','resources','independent_of_author','lineage_waiver'))):required_decision=True;why.append('stage coverage, authority, criteria or dependency changed')
    for old in j['tasks']:
        new=next((t for t in new_plan['tasks'] if t['task_id']==old['task_id']),None)
        if new and any(new.get(k)!=old.get(k) for k in task_contract-{'task_id'}):
            if _unsettled(j,old):raise JobError('cannot change a live task contract before reconciliation: '+_unsettled(j,old))
            required_decision=True;why.append('task contract changed')
    old_constraints=set(j.get('constraints',[]));new_constraints=set(new_plan['constraints'])
    if not old_constraints.issubset(new_constraints):required_decision=True;why.append('constraints weakened or removed')
    old_auth=j.get('authorization',{});new_auth=new_plan.get('authorization',old_auth)
    if not _subset(new_auth,old_auth):required_decision=True;why.append('authority broadened')
    old_policy=j.get('policy',{});new_policy=new_plan.get('policy',old_policy)
    for key,value in old_policy.items():
        if (key=='identity' and value=='observed' and new_policy.get(key,value)!='observed') or (key=='author_independence' and value is True and new_policy.get(key,value) is not True):raise JobError('observed identity policy is immutable' if key=='identity' else 'author independence policy is immutable once enabled')
        if (isinstance(value,(int,float)) and not isinstance(value,bool) and isinstance(new_policy.get(key,value),(int,float)) and not isinstance(new_policy.get(key,value),bool) and new_policy.get(key,value)>value) or key=='max_live_workers' and value is not None and new_policy.get(key,value) is None:
            required_decision=True;why.append(f'limit raised: {key}')
        elif new_policy.get(key,value)!=value and key not in ('max_repair_cycles','max_live_workers','max_artifact_bytes'):
            required_decision=True;why.append(f'policy changed: {key}')
    decision_id=revision.get('owner_decision_id');decision=next((d for d in j['decisions'] if d.get('id')==decision_id and d.get('scope')==f"plan:{revision['id']}" and _owner_current(d,j['policy']['max_artifact_bytes'])),None)
    if required_decision and decision is None:raise JobError('undeclared_expansion: owner decision required for '+', '.join(why))
    generation=digest(canonical(j));pins=None
    if added or replaced:
        if not callable(adopt_dependencies):raise JobError('new dependency pins require the Stage 2 adoption adapter')
        pins=adopt_dependencies(j,new_plan['dependencies'])
    def apply(state):
        if digest(canonical(state))!=generation:raise JobError('job changed during plan validation; retry against current revision')
        for field in ('requirements','dependencies','stages','tasks','constraints','authorization','policy'):
            state[field]=new_plan[field]
        if pins is not None:state['pins']=pins
        else:state['pins']={key:pin for key,pin in j['pins'].items() if key in new_deps}
        if decision:state['history'].append({'kind':'superseded-plan','revision_id':revision['id'],'requirements':j['requirements'],'stages':j['stages'],'tasks':j['tasks'],'dependencies':j['dependencies'],'authorization':j['authorization'],'constraints':j.get('constraints',[])})
        else:state['history'].append({'kind':'plan-revision','revision':revision,'decision_required':False})
        affected=set(new_stage_ids-old_stage_ids)|{t['stage_id'] for t in j['tasks']+new_plan['tasks'] if t['task_id'] in old_task_ids^new_task_ids or any(t['task_id']==o['task_id'] and any(t.get(k)!=o.get(k) for k in task_contract) for o in j['tasks'])}
        if any(j[k]!=new_plan[k] for k in ('requirements','constraints','authorization','policy')):affected|=new_stage_ids
        for old in j['stages']:
            new=next((s for s in new_plan['stages'] if s['id']==old['id']),None)
            if new and (any(new.get(k)!=old.get(k) for k in stage_contract-{'id','criteria'}) or sorted(new.get('criteria',[]),key=canonical)!=sorted(old.get('criteria',[]),key=canonical)):affected.add(old['id'])
        affected|={s['id'] for s in state['stages'] if s.get('validator_dependency') in added|replaced}|{t['stage_id'] for t in state['tasks'] if t.get('dependency_key') in added|replaced}  # a replaced worker definition invalidates its slots
        for stage in state['stages']:
            if stage['id'] in affected:stage['status']='stale';stage['acceptance']=None
        stale_ids=set(affected)
        while grow:=[s for s in state['stages'] if s['id'] not in stale_ids and set(s.get('depends_on',[]))&stale_ids]:
            for stage in grow:stale_ids.add(stage['id']);stage['status']='stale';stage['acceptance']=None
        for task in state['tasks']:
            slot=(task['stage_id'],task['logical_slot_id']);prior=[x for h in j['history'] for x in h.get('tasks',[])]+j['tasks'];same_slot=[x for x in prior if (x['stage_id'],x['logical_slot_id'])==slot];old_task=next((x for x in j['tasks'] if x['task_id']==task['task_id']),None)
            if old_task is None:task.setdefault('attempt',0);task.setdefault('status','pending');task.setdefault('handles',[]);task.setdefault('followups',[]);task.setdefault('dispatch_retries',0)
            if same_slot:task['attempt']=max(x.get('attempt',0) for x in same_slot);task['cycle']=max(x.get('cycle',0) for x in same_slot)
            if task['stage_id'] in stale_ids:
                task['inputs_stale']=True
                if not _live_handles(task) and not task.get('uncertain_calls'):task['status']='stale'
        state.setdefault('plan_revisions',[]).append({'revision':revision,'plan_sha256':digest(canonical(new_plan)),'decision_id':decision_id if decision else None,'expanded':required_decision,'adopted_dependencies':sorted(added|replaced),'invalidated_acceptance':bool(affected)})
    return store.transact(caller,apply,'plan-revision')
def _subset(candidate, ceiling):
    if isinstance(candidate,dict):return isinstance(ceiling,dict) and set(candidate)<=set(ceiling) and all(_subset(v,ceiling[k]) for k,v in candidate.items())
    if isinstance(candidate,list):return isinstance(ceiling,list) and all(v in ceiling for v in candidate)
    if type(candidate) is bool:return type(ceiling) is bool and (not candidate or ceiling)
    if isinstance(candidate,(int,float)) and not isinstance(candidate,bool):return isinstance(ceiling,(int,float)) and candidate<=ceiling
    return candidate==ceiling
