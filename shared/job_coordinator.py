"""Stage 2 pin adapter for the generic core job store."""
from pathlib import Path
from shared.worker_registry import snapshot_pins,read_regular,digest,package_digest,verify_package_files,verify_bundle,compose_worker
from core.jobs import create_job,JobError
from core.jobs.store import Store, _directory_fd, _retain, requests, trusted_link
import json
import os
import shlex


def selection_for_task(job, task):
    """New CLI jobs require choices; old immutable jobs retain their old contract.

    Low-level core fixture/import APIs remain format-neutral. Adoption adapters
    must use the CLI admission boundary or explicitly supply this policy marker.
    """
    from shared.model_selection import validate, dispatch, SelectionError
    if not job.get('policy', {}).get('model_selection_required') and not job.get('model_selection'):
        return None
    try:
        binding = task.get('selection_binding') or {}
        producing = binding.get('selection_sha256')
        record = validate((job.get('model_selection_history') or {}).get(producing, job.get('model_selection')), producing)
        if binding.get('selection_sha256') != record['selection_sha256']:
            raise SelectionError('task producing selection binding missing/mismatched')
        from core.jobs import _unsettled
        plan = dispatch(record, role=binding['role'], slot_id=binding.get('slot_id'),
                        target=binding.get('target'), data_classes=binding.get('data_classes', ['repository']),
                        unavailable=binding.get('unavailable'), expected=producing,
                        live_tasks=[t['task_id'] for t in job['tasks'] if _unsettled(job, t)])
        actual = task.get('target') or {}
        if any(actual.get(k, {} if k == 'options' else None) != plan['target'].get(k, {} if k == 'options' else None)
               for k in ('providerInstanceId', 'model', 'options', 'runtimeMode')):
            raise SelectionError('task target/options differ from frozen selection')
        if plan['execution'] != 'child':
            raise SelectionError('current-context choice cannot dispatch a child')
        return {'record': record, 'binding': binding, 'dispatch': plan}
    except (SelectionError, KeyError, TypeError) as exc:
        raise JobError('model_selection: ' + str(exc)) from exc


def selection_plan_revision(current, proposed):
    """Validate prospective choices before the ordinary owner-bound plan revision.

    The core persists these generic contract fields in the same transaction as the
    task revision. Existing findings, rounds and history are never replaced here.
    """
    from shared.job_coordination import provider_limits
    provider_limits({**current.get('policy', {}), **proposed.get('policy', {})}.get('max_live_workers_by_provider', {}))
    if not current.get('policy', {}).get('model_selection_required'):
        return
    from shared.model_selection import validate, prospective
    from core.jobs import _unsettled
    from copy import deepcopy
    if 'model_selection' in proposed:
        if not proposed.get('model_selection_sha256'):
            raise JobError('new choice needs its separately retained model_selection_sha256')
        chosen = validate(proposed['model_selection'], proposed.get('model_selection_sha256'))
        live = [t['task_id'] for t in current['tasks'] if _unsettled(current, t)]
        prospective(current['model_selection'], chosen, {'live_tasks': live})
        archive = deepcopy(current.get('model_selection_history', {}))
        archive[current['model_selection_sha256']] = current['model_selection']
        proposed['model_selection_history'] = archive
    merged = {**current, **proposed}
    if current.get('workflow') in ('focus-group/run', 'focus-group/resume'):
        from shared.adopter_planning import validate_job as validate_adopter_job
        merged['policy'] = {**current['policy'], **proposed.get('policy', {})}
        validate_adopter_job(merged, previous=current)
    for task in proposed.get('tasks', []):
        selection_for_task(merged, task)
    if current.get('policy', {}).get('imps_planning_required'):
        from shared.imps_planning import validate_job, job_contract
        changed = job_contract(current) != job_contract(merged)
        if changed:
            if 'imps_initial_plan' not in proposed:
                raise JobError('changed authored stages require a new initial planning receipt')
            from copy import deepcopy
            merged['stages'] = deepcopy(merged['stages'])
            for stage in merged['stages']:
                stage.get('resources', {}).pop('imps_initial_review', None)
        if merged.get('policy', {}).get('imps_planning_required') is not True:
            raise JobError('imps planning policy is immutable once enabled')
        validate_job(merged, before_execution=changed)
        if changed:
            merged['stages'][0].setdefault('resources', {})['imps_initial_review'] = {
                'descriptor': proposed['imps_initial_plan'], 'check': merged.get('imps_initial_check')}
            proposed['stages'] = merged['stages']


def selection_for_direct_stage(job, stage, identity):
    """An identity observation is not permission for delegated-to-direct fallback."""
    if not job.get('policy', {}).get('model_selection_required') and not job.get('model_selection'):
        return None
    from shared.model_selection import validate, dispatch, correlate, SelectionError
    try:
        binding = stage.get('selection_binding') or {}
        producing = binding.get('selection_sha256')
        if not producing:
            raise SelectionError('direct stage needs an explicit current-context work binding')
        record = validate((job.get('model_selection_history') or {}).get(producing, job.get('model_selection')), producing)
        from core.jobs import _unsettled
        plan = dispatch(record, role=binding['role'], target=binding.get('target'),
                        unavailable=binding.get('unavailable'), data_classes=binding.get('data_classes', ['repository']),
                        live_tasks=[t['task_id'] for t in job['tasks'] if _unsettled(job, t)], expected=producing)
        if plan['execution'] != 'current-context':
            raise SelectionError('chosen work execution requires a child; direct fallback not authorised')
        observation = correlate(plan, identity)
        return {'selection_sha256': producing, 'dispatch': plan, 'observation': observation}
    except (SelectionError, KeyError, TypeError) as exc:
        raise JobError('model_selection: ' + str(exc)) from exc

def _recovery_invocations(pins,job,state_root):
    by_key={d['key']:d['plugin'] for d in job['dependencies']}
    for key,pin in pins.items():
        argv=['t3-plugins','--job',str(Path(state_root).absolute()/job['job_id']/'job.json'),'path',by_key[key]]
        pin['compatible_pinned_argv']=argv;pin['compatible_pinned_invocation']=shlex.join(argv)
    return pins

def _write_probe(job,state_root):
    import os,secrets
    from core.jobs.store import canonical,JobError
    root=Path(state_root).expanduser().absolute();os.close(_directory_fd(root,create=True))
    chain=[];part=root
    while True:
        chain.append(part)
        if part.parent==part:break
        part=part.parent
    for part in reversed(chain):
        if part.is_symlink() and not trusted_link(part):raise JobError('symlink in pin probe path')
    probe=root/('.pin-probe-'+secrets.token_hex(12)+'.json')
    fd=os.open(probe,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(canonical(job));f.flush();os.fsync(f.fileno())
    except BaseException:
        probe.unlink(missing_ok=True);raise
    return probe

def verified_pins(job,state_root,prefix,agents_root,config_path=None):
    deps={d['key']:d['plugin'] for d in job['dependencies']}
    probe=_write_probe(job,state_root)
    try:return _recovery_invocations(snapshot_pins(probe,deps,Path(prefix),Path(agents_root),Path(config_path) if config_path else None)['pins'],job,state_root)
    finally:probe.unlink(missing_ok=True)

def adopt_pins(job,new_dependencies,state_root,prefix,agents_root,config_path=None,adopt_keys=()):
    """Snapshot only added/replaced dependencies and retain every unchanged pin."""
    from core.jobs.store import JobError
    old={d['key']:d['plugin'] for d in job['dependencies']};new={d['key']:d['plugin'] for d in new_dependencies}
    if len(new)!=len(new_dependencies):raise JobError('duplicate dependency key')
    changed={key:plugin for key,plugin in new.items() if old.get(key)!=plugin or key in adopt_keys or next((d for d in job['dependencies'] if d['key']==key),None)!=next(d for d in new_dependencies if d['key']==key)}
    retained={key:pin for key,pin in job['pins'].items() if key in new and key not in changed}
    if not changed:return retained
    probe=_write_probe({**job,'dependencies':[{'key':k,'plugin':v} for k,v in changed.items()],'pins':{}} ,state_root)
    try:added=_recovery_invocations(snapshot_pins(probe,changed,Path(prefix),Path(agents_root),Path(config_path) if config_path else None)['pins'],{**job,'dependencies':new_dependencies},state_root)
    finally:probe.unlink(missing_ok=True)
    return {**retained,**added}

def create_pinned_job(job,state_root,prefix,agents_root,config_path=None):
    """Pin, index the state root in each owning agents root, then create the job.

    The registry lock spans pinning and indexing, so a concurrent uninstall either runs
    first (and the pin fails) or sees the index record (and refuses removal)."""
    from shared.worker_registry import locked,registry_root,job_agents_roots,record_job_root,forget_job_root
    job=__import__('copy').deepcopy(job)
    job.setdefault('policy', {})['identity']='observed'
    workflow = str(job.get('workflow', ''))
    if workflow.startswith('imps/') and workflow != 'imps/planning-review':
        from shared.imps_planning import validate_job
        validate_job(job, Path(state_root).absolute() / job['job_id'] / 'job.json', before_execution=True)
        job['policy']['model_selection_required'] = True
        job['policy']['imps_planning_required'] = True
    if workflow in ('ape/study', 'ape/forage'):
        from shared.ape_planning import validate_job
        validate_job(job)
        job['policy']['model_selection_required'] = True
    from shared.adopter_planning import validate_job as validate_adopter_job
    if workflow in ('focus-group/run', 'focus-group/resume'):
        job['policy']['model_selection_required'] = True
    validate_adopter_job(job, creating=True)
    if workflow.partition('/')[0] in ('agent-tuneup', 'babysitter') or workflow in ('elephant-goldfish/elephant','elephant-goldfish/check'):
        job['policy']['model_selection_required'] = True
    if workflow.startswith('elephant-goldfish/'):
        if workflow.endswith(('/thinking', '/elephant')):
            job.setdefault('policy', {})['author_independence'] = True
        if workflow.endswith('/check'):
            # Checks enforce author lineage only when matching-hash records exist.
            job.setdefault('policy', {})['author_independence'] = False
        from shared.document_authors import import_subject_authors, merge_author_records
        for task in job.get('tasks', []):
            stage = next((row for row in job.get('stages', []) if row['id'] == task.get('stage_id')), {})
            contract = stage.get('validator_contract') or {}
            inferred = ({'path': contract.get('document_path'), 'sha256': contract.get('document_sha256')}
                        if contract.get('document_path') and contract.get('document_sha256') else None)
            if inferred and not task.get('document'):
                task['document'] = inferred
            validated_path = contract.get('document_path')
            checking = workflow.endswith('/check')
            authoring = bool(job.get('policy', {}).get('author_independence'))
            if (task.get('independent_of_author') or authoring or checking) and task.get('document') and validated_path:
                if (not isinstance(task['document'], dict) or task['document'].get('path') != validated_path or
                        task['document'].get('sha256') != contract.get('document_sha256')):
                    raise JobError('author-independent slot document must match the stage validated document')
            if task.get('independent_of_author') or authoring or checking:
                subjects = [inferred, task.get('document'), *(task.get('reviewed_documents') or [])]
                imported = [import_subject_authors(subject) for subject in subjects if subject]
                merged = merge_author_records(*(
                    {'authors': authors, 'unknown': any(row.get('unknown') for row in authors)}
                    for authors in imported)) if imported else {'authors': [], 'unknown': True}
                task['document_authors'] = [{'unknown': True}] if merged.get('unknown') else merged['authors']
                validated_authors = import_subject_authors(inferred) if inferred else [{'unknown': True}]
                if checking:
                    if validated_authors and not any(row.get('unknown') for row in validated_authors):
                        task['independent_of_author'] = True
                    else:
                        task.pop('independent_of_author', None)
                elif task.get('role') in ('factual', 'cold-read') or authoring:
                    task['independent_of_author'] = True
        if job.get('policy', {}).get('author_independence') or workflow.endswith('/check'):
            for stage in job.get('stages', []):
                contract = stage.get('validator_contract') or {}
                path, sha256 = contract.get('document_path'), contract.get('document_sha256')
                if not path or not sha256:
                    continue
                stage['document_authors'] = import_subject_authors({'path': path, 'sha256': sha256})
    with locked(registry_root(agents_root)):
        pins=verified_pins(job,state_root,prefix,agents_root,config_path)
        from shared.job_coordination import freeze_provider_limits
        freeze_provider_limits(job,pins)
        added=record_job_root(job_agents_roots(pins),state_root,job['job_id'])
    try:return create_job(job,state_root,pins)
    except BaseException:
        forget_job_root(added,state_root,job['job_id']);raise

def verify_pinned_dependency(dep,pin):
    package=Path(pin['package_dir']);bundle=Path(pin['bundle_dir'])
    manifest=json.loads(read_regular(package/'install-manifest.json','pinned package receipt').decode())
    if package_digest(manifest)!=pin['package_digest'] or manifest.get('package_digest')!=pin['package_digest']:raise JobError('pin_mismatch: pinned package changed')
    verify_package_files(package,manifest)
    checked=verify_bundle(bundle,pin['installation_id'],dep['plugin'],manifest['version'],pin['package_digest'])
    if checked.get('bundle_digest')!=pin['bundle_digest']:raise JobError('pin_mismatch: pinned bundle changed')
    actual_workers={};actual_shared={}
    for asset in checked['manifest']['assets']:
        data=read_regular(bundle/asset['path'],'immutable worker asset')
        record={'bytes':data.decode('utf-8'),'sha256':digest(data)}
        if asset['path'].startswith('workers/'):actual_workers[asset['id']]=record
        elif asset['path'].startswith('shared/'):actual_shared[asset['path'][7:]]=record
    if pin['workers']!=actual_workers or pin['shared']!=actual_shared or set(pin['effective_workers'])!=set(actual_workers):raise JobError('pin_mismatch: stored worker/shared definitions differ from immutable bundle')
    for wid,record in pin['effective_workers'].items():
        base=pin['workers'].get(wid)
        if not base:raise JobError('pin_mismatch: pinned worker base is missing')
        custom=record.get('override_bytes') if record.get('override_status')=='enabled' else ''
        if record.get('base_sha256')!=base['sha256'] or custom and digest(custom.encode())!=record.get('override_sha256'):raise JobError('pin_mismatch: stored worker base or override hash changed')
        contract=pin.get('task_contract');contract_bytes=contract['bytes'].encode() if contract else None
        if contract and digest(contract_bytes)!=contract.get('sha256'):raise JobError('pin_mismatch: stored task contract hash changed')
        effective=compose_worker([(name,data['bytes'].encode()) for name,data in pin['shared'].items()],base['bytes'].encode(),custom or '',contract_bytes)
        if effective!=record['bytes'] or digest(effective.encode())!=record['sha256']:raise JobError('pin_mismatch: pinned effective worker composition changed')
    return True


def verify_all_pins(store,caller=None):
    """Resolve and verify stored absolute pins before validating a caller identity."""
    store.verify_pins=verify_job_pins
    job=store.verified_load()
    if job.get('policy', {}).get('imps_planning_required'):
        from shared.imps_planning import validate_job
        validate_job(job, store.file)
    if caller is not None:
        from core.jobs.store import _authorize
        _authorize(job,caller,'mutate')
    return job

def verify_job_pins(job):
    for dep in job['dependencies']:
        pin=job['pins'].get(dep['key'])
        if not pin:raise JobError(f"pin_mismatch: missing stored pin: {dep['key']}")
        verify_pinned_dependency(dep,pin)
    return True

def pinned_store(state_root,job_id):
    return Store(state_root,job_id,verify_pins=verify_job_pins)


def prepare_task(store, caller, task_id, verify_pin, verify_acceptance, target_reason='configured worker'):
    """Bind explicit review subjects before preparing their immutable brief."""
    from core.jobs import prepare, _live_handles
    from shared.job_acceptance import AcceptanceError, independent_lineage, independent_of_authors, review_inputs
    if not callable(verify_pin) or any(verify_pin(d, store.load()['pins'][d['key']]) is not True for d in store.load()['dependencies']):
        raise JobError('pinned dependency verifier is required before review preparation')
    def bind(job):
        if job.get('policy', {}).get('imps_planning_required'):
            from shared.imps_planning import validate_job
            validate_job(job, store.file)
        if job['workflow'] in ('ape/study', 'ape/forage'):
            from shared.ape_planning import validate_job
            validate_job(job)
        task = next(t for t in job['tasks'] if t['task_id'] == task_id)
        from shared.job_coordination import require_admission
        require_admission(job, task)
        from shared.document_authors import validate_cold_reader_scope
        validate_cold_reader_scope(task)
        from shared.adopter_planning import validate_job as validate_adopter_job
        validate_adopter_job(job)
        selected = selection_for_task(job, task)
        if selected:
            # Prepared choices are included in the immutable brief and its hash.
            # Cold readers receive only procedural choices, not prior findings.
            task['model_selection'] = {'selection_sha256': selected['record']['selection_sha256'],
                                       'binding': selected['binding'], 'dispatch': selected['dispatch']}
        if task.get('role') == 'review':
            if _live_handles(task) or task.get('status') not in ('pending', 'stale', 'blocked'):
                raise JobError('review inputs cannot be rebound after dispatch')
            task['review_inputs'] = review_inputs(store, job, task)
            # Lineage independence compares worker executions; a document subject has none.
            for subject in task.get('reviewed_task_ids', []):
                try:
                    independent_lineage(next(t for t in job['tasks'] if t['task_id'] == subject), task)
                except AcceptanceError as exc:
                    raise JobError(str(exc)) from exc
        if task.get('independent_of_author') or job.get('policy', {}).get('author_independence'):
            subjects = [next(t for t in job['tasks'] if t['task_id'] == sid) for sid in task.get('reviewed_task_ids', [])]
            if not subjects:
                subjects = [task]
            try:
                for subject in subjects:
                    try:
                        independent_of_authors(subject, task)
                    except AcceptanceError:
                        from shared.document_authors import has_current_task_waiver
                        if not has_current_task_waiver(job, subject, reviewer=task if subject is not task else None):
                            raise
            except AcceptanceError as exc:
                raise JobError(str(exc)) from exc
        validate_adopter_job(job, task.get('stage_id'))
    return prepare(store, caller, task_id, verify_pin, verify_acceptance, target_reason, bind_inputs=bind)


TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')

def _shared_observation(job, task_id, event):
    """Apply follow-up uncertainty or conflicting-host reconciliation; return False for core observations."""
    task = next((t for t in job['tasks'] if t['task_id'] == task_id), None)
    if task is None or not isinstance(event, dict):
        return False
    kind, request, host = event.get('kind'), event.get('request_id'), event.get('host_task_id')
    owned = task.get('handles', []) + task.get('followups', [])
    staged = task.get('prepared_followup') or {}
    if kind == 'uncertain' and request and request != task['request_id'] and request == staged.get('request_id'):
        # A missing follow-up task ID is same-ID uncertain dispatch (issue-28 follow-up rules).
        if job.get('status') == 'cancelled' or job.get('discard_requested'):
            raise JobError('cancelled job permits only terminal reconciliation')
        if any(h.get('request_id') == request for h in owned):
            raise JobError('accepted request cannot become uncertain')
        current = task.get('followup_dispatch') or {}
        if current.get('request_id') not in (None, request) and current.get('uncertain_calls') and not any(h.get('request_id') == current['request_id'] for h in owned):
            raise JobError('uncertain_dispatch: another uncertain follow-up dispatch remains unreconciled')
        calls = current.get('uncertain_calls', 0) if current.get('request_id') == request else 0
        if calls >= 3:
            raise JobError('uncertain_dispatch: uncertain dispatch original plus two retries exhausted')
        task['followup_dispatch'] = {'request_id': request, 'uncertain_calls': calls + 1, 'dispatch_retries': calls}
        if calls == 2:
            task['followup_dispatch']['blocked_reason'] = 'uncertain_dispatch'
        task.setdefault('dispatch_history', []).append(event)
        return True
    conflicts = [c for c in task.get('host_conflicts', []) if c.get('host_task_id') == host and not c.get('reconciled')]
    if kind != 'reconciled' or not host or not conflicts or any(h.get('task_id', h.get('host_task_id')) == host for h in owned):
        return False
    for field in ('status', 'work_state', 'has_pending_child_runs'):
        if field not in event:
            raise JobError('authoritative observation missing ' + field)
    if request not in {c.get('request_id') for c in conflicts}:
        raise JobError('conflict reconciliation request differs from the retained conflict')
    if event['status'] not in TERMINAL or event['has_pending_child_runs'] is not False or event['work_state'] in ('working', 'waiting_for_children'):
        raise JobError('conflicting host reconciliation requires authoritative terminal state without pending runs')
    record = {key: event[key] for key in ('status', 'work_state', 'has_pending_child_runs')}
    for conflict in conflicts:
        conflict['reconciled'] = record
    for blocker in job.get('blockers', []):
        if blocker.get('kind') == 'conflicting-host-handle' and blocker.get('task_id') == task_id and blocker.get('host_task_id') == host:
            blocker['reconciled'] = record
    task.setdefault('reconciliation', []).append(event)
    task.setdefault('dispatch_history', []).append(event)
    return True


def record_observation(store, caller, task_id, event):
    """Record a host observation; retain a conflicting host ID for an owned request, then refuse it.

    Uncertain dispatch for the prepared follow-up and terminal reconciliation of a
    retained conflicting host ID are recorded here; other kinds go to core.
    """
    from core.jobs import record_dispatch
    from shared.job_coordination import observed_now
    if isinstance(event, dict) and 'recorded_at' in event:
        raise JobError('recorded_at is local receipt time and cannot be supplied')
    if isinstance(event, dict): event = {**event, 'recorded_at': observed_now()}
    if isinstance(event, dict) and event.get('kind') == 'capacity-deferred' and event.get('reason', 'capacity') not in ('capacity', 'rate-limit'):
        raise JobError('capacity deferral reason must be capacity or rate-limit')
    if isinstance(event, dict) and event.get('kind') in ('uncertain', 'reconciled'):
        if store.transact(caller, lambda job: _shared_observation(job, task_id, event), 'task-observation') is True:
            return store.load()
    try:
        return record_dispatch(store, caller, task_id, event)
    except JobError as exc:
        if 'request already has an accepted host handle' not in str(exc) or not event.get('host_task_id'):
            raise
        conflict = {key: event.get(key) for key in ('request_id', 'host_task_id', 'parent_host_task_id', 'child_thread_id')}
        conflict.update(observation_kind=event.get('kind'), reason=str(exc))
        def retain(job):
            task = next(t for t in job['tasks'] if t['task_id'] == task_id)
            if not any({k: v for k, v in c.items() if k != 'reconciled'} == conflict for c in task.setdefault('host_conflicts', [])):
                task['host_conflicts'].append(conflict)
                job.setdefault('blockers', []).append({**conflict, 'kind': 'conflicting-host-handle', 'task_id': task_id})
        store.transact(caller, retain, 'task-observation')
        raise


def _current_authority(job, task, stage):
    """Brief fields a follow-up must take from the current task contract (mirrors core prepare)."""
    pin = job['pins'][task['dependency_key']]
    scope = task.get('write_scope', {'mode': 'coordinator-only'})
    requirements = task.get('requirements', stage['requirements'])
    current = {'stage_id': task['stage_id'], 'logical_slot_id': task['logical_slot_id'], 'task_id': task['task_id'],
               'worker_id': task['worker_id'], 'role': task.get('role', 'worker'), 'write_scope': scope,
               'effective_definition': pin['effective_workers'].get(task['worker_id']),
               'max_attempts': 1 + job['policy']['max_repair_cycles']}
    if task.get('model_selection'):
        current['model_selection'] = task['model_selection']
    if task.get('context_policy') == 'document-only':
        current.update(document=task.get('document', {}), requirements=[{'id': r} for r in requirements],
                       authorization={'read': [task.get('document', {}).get('path')] + [f.get('path') for f in task.get('context_files') or []],
                                      'write': task.get('write_scope', {})},
                       revision=None)
    else:
        current.update(target=task.get('target'), authorization=job['authorization'], constraints=job['constraints'],
                       revision=stage.get('revision'), stop_conditions=stage.get('stop_conditions', []),
                       resources=stage.get('resources', {}), result_contract=job['result_contract'],
                       requirements=[{'id': r, 'statement': job['requirements'][r]} for r in requirements])
    return current


def prepare_followup(store, caller, task_id, request_id):
    """Prepare one correlated follow-up before the host launch; retain original bytes."""
    import re
    from core.jobs.store import canonical, strict_load, _regular, digest
    from core.jobs import _open_dispatch, _slot_followups, _spent, _uningested
    def apply(job):
        task = next(t for t in job['tasks'] if t['task_id'] == task_id)
        from shared.job_coordination import require_admission
        require_admission(job, task, request_id=request_id)
        stage = next(s for s in job['stages'] if s['id'] == task['stage_id'])
        selection_for_task(job, task)
        if task.get('role') == 'review':
            raise JobError('review rounds require a fresh declared execution, not a same-child follow-up')
        if task.get('context_policy') == 'document-only':
            raise JobError('document-only slots require a fresh declared execution, not a same-child follow-up')
        if task.get('inputs_stale') or task.get('status') == 'stale':
            raise JobError('stale task contract requires a charged fresh preparation, not a follow-up')
        if _spent(stage) or task.get('attempt', 0) >= 1 + job['policy']['max_repair_cycles']:
            raise JobError('follow-up in a validated pass or after the execution budget requires a charged repair pass')
        if _open_dispatch(task):
            raise JobError(_open_dispatch(task))
        if _uningested(task):
            raise JobError('owned terminal work has no ingested result blocks follow-up preparation')
        handles = task.get('handles', []) + task.get('followups', [])
        if task.get('status') not in ('awaiting-followup', 'awaiting-acceptance') or not handles or any(h.get('status') not in ('completed', 'failed', 'cancelled', 'interrupted') or h.get('work_state') != 'result_available' or h.get('has_pending_child_runs') for h in handles):
            raise JobError('follow-up requires reconciled terminal parent work')
        staged = (task.get('prepared_followup') or {}).get('request_id')
        # Every request ID retained anywhere in job history is reserved; only the currently staged one may be re-presented.
        if len(_slot_followups(job, task)) >= task.get('max_followups', 1) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', request_id) or (request_id != staged and request_id in requests(job)):
            raise JobError('follow-up exceeds its declared slot or request identity')
        original = task['brief']
        raw = _regular(Path(original['path']))
        if digest(raw) != original['sha256']:
            raise JobError('original brief bytes changed')
        brief = strict_load(raw)
        brief.pop('effective_brief_sha256')
        # Authority, definition and target come from the current task contract, never from the
        # original brief; a contract the original execution did not run under needs a fresh execution.
        current = _current_authority(job, task, stage)
        if any(brief.get(key) != value for key, value in current.items()):
            raise JobError('follow-up authority differs from the current task contract; a charged fresh preparation is required')
        brief.update(current, request_id=request_id, attempt=task['attempt'], followup_of=task['request_id'])
        brief['effective_brief_sha256'] = digest(canonical(brief))
        raw = canonical(brief)
        # Follow-up briefs live in their own directory under the same fixed-width
        # <task_id>-<sha256(request_id)> encoding as normal briefs, so no task/request pair aliases another.
        path = store.path / 'briefs' / 'followup' / (task_id + '-' + digest(request_id.encode()) + '.json')
        _retain(path, raw, 'follow-up brief is immutable')
        if staged and staged != request_id:  # A replaced staged follow-up may already be known to the host.
            task.setdefault('retired_request_ids', []).append(staged)
        reference = {key: brief[key] for key in ('job_id', 'stage_id', 'logical_slot_id', 'task_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision', 'snapshot')}
        reference.update(path=str(path), sha256=digest(raw))
        task['prepared_followup'] = reference
        return reference
    return store.transact(caller, apply, 'prepare')


def _coordinator_input(store, job, path):
    """Check the logical write boundary; the host enforces process permissions."""
    path = Path(path)
    if '..' in path.parts:
        raise JobError('coordinator input must not contain parent-directory traversal')
    location = Path(os.path.realpath(path))
    if not path.is_absolute() or location.is_relative_to(Path(os.path.realpath(store.path / 'artifacts'))):
        raise JobError('coordinator input must be absolute and outside worker artifacts')
    for task in job['tasks']:
        scope = task.get('write_scope', {})
        if scope.get('mode') == 'worker-evidence' and location.is_relative_to(Path(os.path.realpath(store.path / scope['path']))):
            raise JobError('worker-owned content cannot be an authoritative observation')
    return path


def publish_observation(store, caller, stage_id, input_file):
    """Freeze explicit coordinator observation bytes before invoking a validator."""
    from core.jobs.store import canonical, digest, strict_load, _regular
    if store.verify_pins is None:
        store.verify_pins = verify_job_pins
    def apply(job):
        stage = next((s for s in job['stages'] if s['id'] == stage_id), None)
        if stage is None:
            raise JobError('unknown observation stage')
        source = _coordinator_input(store, job, input_file)
        raw = _regular(source, max_bytes=job['policy']['max_artifact_bytes'])
        if not isinstance(strict_load(raw), dict):
            raise JobError('coordinator observation must be a complete JSON object')
        path = store.path / 'observations' / (stage_id + '-' + digest(raw) + '.json')
        _retain(path, raw, 'coordinator observation bytes changed')
        reference = {'path': str(path), 'root': str(store.path / 'observations'),
                     'sha256': digest(raw), 'bytes': len(raw)}
        if stage.get('observation_ref') != reference:
            from shared.job_acceptance import _descendants
            for affected in [stage, *_descendants(job['stages'], stage_id)]:
                if affected.get('acceptance'):
                    affected.setdefault('acceptance_history', []).append(affected['acceptance'])
                affected['acceptance'] = None
                affected['status'] = 'pending' if affected is stage else 'stale'
                if affected is not stage:
                    for task in job['tasks']:
                        if task['stage_id'] == affected['id']:
                            # Live work keeps its status but its inputs are stale: completion cannot make it acceptable.
                            task['inputs_stale'] = True
                            if task.get('status') != 'running' and not task.get('uncertain_calls'):
                                task['status'] = 'stale'
            stage['observation_ref'] = reference
            job['history'].append({'kind': 'coordinator-observation', 'stage_id': stage_id, 'reference': reference})
        return reference
    return store.transact(caller, apply, 'observation')


def record_direct_execution(store, caller, stage_id, capabilities):
    """Record the identity reported for a direct factual-stage execution."""
    from shared.document_authors import author_from_capabilities
    try:
        author = author_from_capabilities(capabilities)
    except (JobError, TypeError, ValueError) as exc:
        raise JobError('direct execution requires a fresh, catalog-correlated capabilities response') from exc
    def apply(job):
        if job.get('policy', {}).get('imps_planning_required'):
            from shared.imps_planning import validate_job
            validate_job(job, store.file)
        stage = next((row for row in job['stages'] if row['id'] == stage_id), None)
        if stage is None or stage.get('execution_mode') != 'direct' or any(t['stage_id'] == stage_id for t in job['tasks']):
            raise JobError('direct execution observation requires a zero-slot direct stage')
        from shared.adopter_planning import validate_job as validate_adopter_job
        validate_adopter_job(job, stage_id)
        selected = selection_for_direct_stage(job, stage, author)
        observation = {'identity': author, 'recorded_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
        if selected:
            observation['model_selection'] = selected
        stage.setdefault('direct_execution_history', []).append(observation)
        stage['status'] = 'pending'
        stage['acceptance'] = None
        job['history'].append({'kind': 'direct-execution', 'stage_id': stage_id, 'identity': author})
        return observation
    return store.transact(caller, apply, 'task-observation')


def _document_subjects(task):
    return [d for d in [task.get('document'), *task.get('reviewed_documents', [])] if isinstance(d, dict)]


def revise_document(store, caller, task_id, document, reason, capabilities=None):
    """Rebind a coordinator-repaired document to its new hash as a declared repair round.

    Within the persisted repair budget no owner decision is needed: every stage contract and
    slot naming the same path takes the new hash, and those stages and their successors go
    stale, so each executed slot needs a charged `retry` before it runs again. A spent budget
    refuses with attempt_budget_exhausted; raising it is an owner decision (plan-revision).
    """
    import re
    from core.jobs import _unsettled
    from core.jobs.store import digest, canonical
    import contextlib
    from shared.document_authors import append_author, locked_author_records, merge_author_records
    from shared.job_acceptance import AcceptanceError, _descendants, reviewed_document_bytes
    if not isinstance(document, dict) or set(document) != {'path', 'sha256'} or not isinstance(reason, str) or not reason.strip():
        raise JobError('document revision needs document {path, sha256} and a reason')
    if store.verify_pins is None:
        store.verify_pins = verify_job_pins
    # The sidecar lock is held from the read below until after the job commits, and
    # the sidecar is written only once job.json is persisted: a crash in between
    # leaves the new hash unrecorded, which reads as unknown authorship.
    sidecar_lock = contextlib.ExitStack()
    sidecar_update = []
    def apply(job):
        task = next((t for t in job['tasks'] if t['task_id'] == task_id), None)
        if task is None:
            raise JobError('unknown task slot')
        path, new = document['path'], document['sha256']
        old = next((d['sha256'] for d in _document_subjects(task) if d.get('path') == path), None)
        if old is None:
            raise JobError('task does not declare this document subject')
        revised_authors = None
        if not re.fullmatch(r'[0-9a-f]{64}', str(new)) or new == old:
            raise JobError('document revision needs a new SHA-256')
        try:
            if digest(reviewed_document_bytes(store, job, path)) != new:
                raise JobError('document bytes differ from the revised SHA-256')
        except AcceptanceError as exc:
            raise JobError(str(exc)) from exc
        if not task.get('execution_history') or task.get('status') not in ('failed', 'blocked', 'stale', 'awaiting-acceptance'):
            raise JobError('a document revision follows an executed, ingested round; use plan-revision otherwise')
        stages = {s['id'] for s in job['stages'] if (s.get('validator_contract') or {}).get('document_path') == path}
        stages |= {t['stage_id'] for t in job['tasks'] if any(d.get('path') == path for d in _document_subjects(t))}
        stages |= {d['id'] for sid in list(stages) for d in _descendants(job['stages'], sid)}
        limit = job['policy']['max_repair_cycles']
        for slot in (t for t in job['tasks'] if t['stage_id'] in stages):
            if _unsettled(job, slot):
                raise JobError('cannot revise a document under unreconciled work: ' + _unsettled(job, slot))
            stage = next(s for s in job['stages'] if s['id'] == slot['stage_id'])
            if slot.get('attempt', 0) and (stage.get('cycle', 0) >= limit or slot['attempt'] >= 1 + limit):
                raise JobError(f'attempt_budget_exhausted: {slot["task_id"]} used {slot["attempt"]} of {1 + limit} rounds; '
                               'owner_decision_required to raise the limit')
        if job.get('policy', {}).get('author_independence'):
            if capabilities is None:
                raise JobError('document-revision requires a fresh --capabilities response')
            try:
                records, save = sidecar_lock.enter_context(locked_author_records(Path(path).parent))
                inherited = records.get(old, {'authors': [], 'unknown': True})
                updated = append_author(records, reviewed_document_bytes(store, job, path), capabilities,
                                        document_path=Path(path))
                union = merge_author_records(inherited,
                    {'authors': task.get('document_authors', []), 'unknown': any(a.get('unknown') for a in task.get('document_authors', []))},
                    updated.get(new, {'authors': [], 'unknown': True}))
                # Never replace a record with a smaller author set.
                union = merge_author_records(updated.get(new, {'authors': []}), union)
                # Preserve append_author's order, path and pointer metadata so a
                # later in-place recording inherits this revision's authors.
                updated[new] = {**updated.get(new, {}), **union}
                revised_authors = [{'unknown': True}] if union.get('unknown') else union['authors']
                task['document_authors'] = revised_authors
                sidecar_update.append((save, updated))
            except JobError:
                raise
            except (OSError, TypeError, KeyError, ValueError) as exc:
                raise JobError('document-revision capabilities or inherited author record is invalid') from exc
        for stage in job['stages']:
            contract = stage.get('validator_contract') or {}
            if contract.get('document_path') == path:
                contract['document_sha256'] = new
                if revised_authors is not None and job.get('policy', {}).get('author_independence'):
                    stage['document_authors'] = revised_authors
            if stage['id'] in stages:
                if stage.get('acceptance'):
                    stage.setdefault('acceptance_history', []).append(stage['acceptance'])
                stage.update(acceptance=None, status='stale')
        for slot in job['tasks']:
            for subject in _document_subjects(slot):
                if subject.get('path') == path:
                    subject['sha256'] = new
                    if revised_authors is not None and (slot.get('independent_of_author') or job.get('policy', {}).get('author_independence')):
                        slot['document_authors'] = revised_authors
            if slot['stage_id'] in stages:
                slot['inputs_stale'] = True  # a charged retry, or fresh preparation of an unexecuted slot, clears it
                slot['status'] = 'stale'
        record = {'kind': 'document-revision', 'task_id': task_id, 'path': path, 'previous_sha256': old,
                  'sha256': new, 'reason': reason, 'stale_stages': sorted(stages),
                  'rounds_performed': task.get('attempt', 0), 'max_rounds': 1 + limit}
        job['history'].append(record)
        return record
    with sidecar_lock:
        record = store.transact(caller, apply, 'document-revision')
        try:
            for save, updated in sidecar_update:
                save(updated)
        except OSError as exc:
            raise JobError('document revision was committed but its author record was not written; '
                           'the new hash reads as unknown authorship: ' + str(exc)) from exc
    return record


def dispose_finding(store, caller, task_id, finding_id, disposition, evidence, finding_sha256=None):
    """Record an explicit, byte-bound coordinator finding disposition.

    A finding ID reused with changed content is a separate retained row; select it
    with ``finding_sha256`` (SHA-256 of the canonical finding) when the ID is ambiguous.
    """
    from core.jobs.store import canonical, digest, _regular
    if disposition not in ('fixed', 'rejected', 'deferred') or not isinstance(evidence, dict):
        raise JobError('invalid finding disposition or evidence reference')
    if store.verify_pins is None:
        store.verify_pins = verify_job_pins
    def apply(job):
        task = next((t for t in job['tasks'] if t['task_id'] == task_id), None)
        if task is None:
            raise JobError('unknown disposition task')
        rows = [d for d in task.get('finding_dispositions', []) if d['finding_id'] == finding_id and
                (finding_sha256 is None or digest(canonical(d.get('finding'))) == finding_sha256)]
        if not rows:
            raise JobError('unknown retained finding')
        if len(rows) > 1:
            raise JobError('finding ID has distinct retained content; select one with finding_sha256')
        row = rows[0]
        source = _coordinator_input(store, job, evidence.get('path', ''))
        raw = _regular(source, max_bytes=job['policy']['max_artifact_bytes'])
        if not raw or digest(raw) != evidence.get('sha256') or len(raw) != evidence.get('bytes'):
            raise JobError('disposition evidence bytes/hash differ')
        # One digest over the finding ID and the evidence digest keeps the name unique per pair
        # and short enough for ecryptfs, whose 143-byte name limit must also fit the temp suffix.
        name_key = digest(finding_id.encode() + b'\0' + digest(raw).encode())
        path = store.path / 'dispositions' / (task_id + '-' + name_key + '.bin')
        _retain(path, raw, 'disposition evidence is immutable')
        before = dict(row)
        row.update(disposition=disposition, evidence={'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)})
        job['history'].append({'kind': 'finding-disposition', 'task_id': task_id, 'finding_id': finding_id,
                               'finding_sha256': digest(canonical(row.get('finding'))), 'before': before, 'after': dict(row)})
        return row
    return store.transact(caller, apply, 'finding-disposition')
