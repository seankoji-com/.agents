"""Public admission and receipt consumption for configuration, design and strategies.

No assessment, dispatch, settings write or scheduler lives here. Separate pinned
planning jobs own review; existing domain validators own factual/code/apply gates.
"""
from copy import deepcopy
from pathlib import Path
import re

from core.jobs.store import _regular, _atomic, canonical, strict_load, tasks
from shared import model_selection as models, planning_review as planning
from shared.imps_planning import _identity
from shared.document_authors import import_subject_authors
from shared.lineage import lineage

OPS = {'agent-tuneup': {'align', 'audit', 'apply'},
       'elephant-goldfish': {'elephant', 'check'},
       'babysitter': {'pr', 'repo', 'org'}, 'ralph': {'run', 'resume'}, 'focus-group': {'plan', 'run', 'resume'}}
DIRECT = {'doctor', 'status', 'list', 'resolve', 'cancel', 'clean', 'scan',
          'raw-audit', 'bootstrap-template', 'thinking-list'}
KINDS = {'agent-tuneup': {'conclusions': 'synthesis', 'proposal': 'configuration-proposal',
                         'bootstrap': 'recommendation'},
         'elephant-goldfish': {'design': 'source-plan'},
         'babysitter': {'strategy': 'strategy'}, 'ralph': {'strategy': 'strategy'}, 'focus-group': {'study-plan': 'source-plan'}}


def operation(plugin, value):
    if plugin == 'babysitter' and re.fullmatch(r'https?://github\.com/[^/\s]+/[^/\s]+/pull/\d+(?:[?#].*)?', value, re.I):
        return 'pr'
    if value.startswith(plugin + '/'):
        value = value[len(plugin) + 1:]
    planning.need(value in OPS[plugin] or value in DIRECT, 'unsupported adopter operation')
    return value


def admit(plugin, data):
    op = operation(plugin, data['operation'])
    if op in DIRECT:
        return {'allowed': True, 'chooser': False, 'dispatch': False}
    scope = planning.logical_output_id(data['request_reference'], data['output_name'])
    planning.need(data.get('selection_sha256'), 'producing selection digest required')
    selected = models.validate(data.get('selection'), data['selection_sha256'])
    models.gate(selected, invocation_id=data['invocation_id'], scope_id=scope, event=data.get('event', 'new'),
                action='investigate', expected=data['selection_sha256'], pinned=plugin in ('ralph', 'focus-group'), retain=data.get('retain'))
    planning.need(selected['operation'] in (op, plugin + '/' + op), 'selection operation differs')
    models.dispatch(selected, role='workhorse')
    # Required panel obligation is checked at the actual planning transition. A
    # factual-only check/ordinary loop may honestly retain an unused preference.
    return planning.seal({'schema_version': 1, 'plugin': plugin, 'operation': op,
        'request_reference': data['request_reference'], 'output_name': data['output_name'],
        'scope_id': scope, 'invocation_id': data['invocation_id'], 'selection': selected,
        'selection_sha256': selected['selection_sha256'], 'forwarded': data['operation'] not in (op, plugin + '/' + op)})


def continuation(record, *, invocation_id, event='wake', forward=False, retain=None,
                 schedule_id=None, capabilities=None, policy_digests=None):
    planning.unseal(record)
    planning.need(not forward or not record['forwarded'], 'alias selection was already forwarded')
    models.gate(record['selection'], invocation_id=invocation_id, scope_id=record['scope_id'],
        event='forward' if forward else event, action='investigate', expected=record['selection_sha256'],
        pinned=record['plugin'] in ('ralph', 'focus-group'), retain=retain, schedule_id=schedule_id,
        capabilities=capabilities, policy_digests=policy_digests)
    if forward:
        record = deepcopy(record); record.pop('sha256'); record['forwarded'] = True
        return planning.seal(record)
    return record


def dispatch(record, **kw):
    continuation(record, invocation_id=record['invocation_id'])
    return models.dispatch(record['selection'], expected=record['selection_sha256'], **kw)


def _job(path, admission):
    from shared.job_coordinator import pinned_store, verify_all_pins
    p = Path(path)
    planning.need(p.is_absolute() and p.name == 'job.json', 'absolute producing job.json required')
    job = verify_all_pins(pinned_store(p.parent.parent, p.parent.name))
    planning.need(job['workflow'] == admission['plugin'] + '/' + admission['operation'] and
                  job.get('adopter_admission') == admission, 'producing job/admission differs')
    validate_job(job)
    return job


def authors(admission, documents, job_file=None):
    selected = admission['selection']
    result = [_identity(selected, selected['coordinator'])]
    producers = []
    if job_file:
        job = _job(job_file, admission)
        for task in tasks(job):
            if task.get('role') == 'review' or task['worker_id'].endswith(('/factual-checker', '/cold-reader', '/config-verifier')):
                continue  # critique alone is not authorship
            handles = task.get('handles', []) + task.get('followups', [])
            if task in job['tasks']:
                planning.need(handles, 'actual author/synthesizer execution missing')
            for h in handles:
                identity = h.get('observed_identity') or {}
                planning.need(identity.get('status') == 'verified' and
                    h.get('status') in ('completed', 'failed', 'interrupted', 'cancelled') and
                    h.get('has_pending_child_runs') is False and h.get('work_state') == 'result_available',
                    'actual author/synthesizer identity unverified or pending')
                from core.jobs.store import digest
                request = h['request_id']
                bp = (Path(task['brief']['path']) if request == task['request_id'] else
                    Path(job_file).parent / 'briefs' / ('followup' if h in task.get('followups', []) else '') /
                    (task['task_id'] + '-' + digest(request.encode()) + '.json'))
                brief = strict_load(_regular(bp)); frozen = brief['model_selection']; sha = frozen['selection_sha256']
                producing = (job.get('model_selection_history') or {}).get(sha, job['model_selection'])
                models.validate(producing, sha)
                binding = frozen['binding']
                plan = models.dispatch(producing, role=binding['role'], slot_id=binding.get('slot_id'),
                    target=binding.get('target'), unavailable=binding.get('unavailable'),
                    data_classes=binding.get('data_classes', ['repository']), expected=sha)
                planning.need(brief['request_id'] == request and brief['target'] == h['target'] and
                    all(brief['target'].get(k, {} if k=='options' else None) == plan['target'].get(k, {} if k=='options' else None) for k in ('providerInstanceId', 'model', 'options', 'runtimeMode')),
                    'actual author brief/target/options differ')
                observations = [e[k] for e in task.get('dispatch_history', []) if e.get('request_id') == request
                    for k in ('status_identity', 'receipt_identity', 'configuration_identity') if isinstance(e.get(k), dict)]
                for observed in observations:
                    models.correlate(plan, {**identity, **observed})
                result.append(_identity(producing, identity))
                producers.append({'brief': planning.file_descriptor(bp), 'target': plan['target'],
                    'identity': identity, 'observations': observations, 'selection_sha256': sha})
        for stage in job['stages'] + [s for h in job.get('history',[]) for s in h.get('stages',[])]:
            if stage.get('execution_mode') != 'direct' or stage.get('validator_contract',{}).get('mode') in ('factual','cold-read','handoff'):
                continue
            rows = stage.get('direct_execution_history') or []
            planning.need(rows, 'actual direct author execution missing')
            for row in rows:
                frozen = row.get('model_selection') or {}
                producing = (job.get('model_selection_history') or {}).get(frozen.get('selection_sha256'),job['model_selection'])
                models.validate(producing,frozen.get('selection_sha256'))
                plan = frozen['dispatch']
                models.correlate(plan,row['identity'])
                result.append(_identity(producing,row['identity']))
                producers.append({'stage_id':stage['id'],'identity':row['identity'],'selection':producing,
                                  'dispatch':plan})
    # Recorded substantial contributors, including external text, remain authors.
    for doc in documents:
        row = planning.file_descriptor(doc['path'] if isinstance(doc, dict) else doc)
        imported = import_subject_authors(row)
        for author in imported:
            if author.get('unknown'):
                result.append({'unknown':True,'lineage':'unknown'})
                continue
            pid,mid=models.key(author)
            provider=next((p for p in selected['capabilities']['providers'] if p['providerInstanceId']==pid),None)
            driver=provider.get('driverKind',pid) if provider else author.get('driver_kind',pid)
            family=lineage(driver,mid)
            planning.need(author.get('lineage') in (None,family), 'recorded author lineage disagrees with identity')
            result.append({'providerInstanceId':pid,'model':mid,'driver_kind':driver,'lineage':family})
    return sorted({canonical(a): a for a in result}.values(), key=canonical), producers


def _package_file(package, name):
    return Path(package) / name


def source_snapshot(desc, inputs, package):
    admission = desc['admission']; continuation(admission, invocation_id=admission['invocation_id'])
    plugin = admission['plugin']; kind = desc['kind']
    manifest = strict_load(_regular(Path(package) / 'plugin.json'))
    planning.need(manifest['name'] == plugin, 'descriptor belongs to another plugin package')
    planning.need(not (plugin == 'agent-tuneup' and admission['operation'] == 'apply'),
                  'apply consumes an unchanged reviewed proposal; it cannot author a new one')
    planning.need(kind in KINDS[plugin], 'operation has no such planning output')
    planning.need(not (plugin == 'elephant-goldfish' and admission['operation'] != 'elephant'),
                  'check is factual-only and cannot author a design')
    if plugin == 'focus-group':
        evidence_root = Path(inputs['repository_root'])
        planning.need(evidence_root.is_absolute() and '..' not in evidence_root.parts and evidence_root.is_dir(),
                      'absolute existing focus-group evidence root required')
        focus_group_adapter(package).validate_descriptor(desc)
    selected = admission['selection']
    planning.need(any(s['required'] for s in selected['review_panel']), 'planning output needs applicable review panel')
    planning.need(set(inputs) <= {'requests', 'decisions', 'requirements', 'load_bearing_decisions',
        'repository_root', 'evidence_paths', 'declared_paths', 'attachments'}, 'unsupported planning inputs')
    planning.need(inputs['requests'][0]['reference'] == admission['request_reference'], 'source request differs')
    planning.need(inputs['requirements'] == desc['requirements'], 'domain requirements differ')
    planning.current_file(desc['document'])
    documents = [desc['document'], *inputs.get('attachments', [])]
    evidence = deepcopy(inputs['evidence_paths'])
    if plugin == 'agent-tuneup':
        conclusions = desc.get('observation_conclusions')
        planning.need(isinstance(conclusions, dict) and set(conclusions) == {'findings', 'changes'} and
                      all(isinstance(conclusions[k], list) for k in conclusions),
                      'reviewed observation findings/changes required')
        # Raw private settings and proposal documents always retain their class.
        documents = [dict(planning.file_descriptor(d['path'] if isinstance(d, dict) else d), data_class='private-settings') for d in documents]
        evidence = [dict(path=r['path'] if isinstance(r,dict) else r,data_class='private-settings') for r in evidence]
        for row in desc.get('settings_inputs', []):
            planning.current_file(row)
            evidence.append(dict(row, data_class='private-settings'))
        if kind == 'proposal':
            from core.jobs.store import digest
            plan = strict_load(_regular(Path(desc['plan_file'])))
            approved = {k:v for k,v in plan.items() if k != 'approval_digest'}
            import json
            planning.need(digest(json.dumps(approved, sort_keys=True).encode()) == plan['approval_digest'], 'proposal digest invalid')
            planning.need(digest(_regular(Path(desc['before_file']))) == plan['before_sha256'] and
                          digest(_regular(Path(plan['candidate']))) == plan['after_sha256'], 'proposal before/candidate changed')
            evidence.extend({'path':p, 'data_class':'private-settings'} for p in
                            (desc['plan_file'], desc['before_file'], plan['candidate']))
            planning.need(desc.get('plan_digest') == plan['approval_digest'], 'proposal digest differs')
    factual = None
    if plugin == 'elephant-goldfish':
        # Assessment sees only the repaired current document after accepted facts.
        from shared.job_acceptance import validate_stage
        from shared.job_coordinator import pinned_store
        job = _job(desc['job_file'], admission)
        stage = next(s for s in job['stages'] if s['id'] == desc['factual_stage'])
        planning.need(stage.get('validator_contract', {}).get('mode') == 'factual', 'not a factual stage')
        planning.need(stage['validator_contract']['document_sha256'] == desc['document']['sha256'], 'facts concern another document')
        jp = Path(desc['job_file'])
        planning.need(validate_stage(pinned_store(jp.parent.parent, jp.parent.name), stage['id'], run_validator=False)['accepted'],
                      'current factual acceptance required before design review')
        observation = strict_load(_regular(Path(stage['observation_ref']['path'])))
        planning.need(all(r['outcome'] == 'confirmed' for r in observation['claims']), 'repair refuted facts before plan review')
        factual = {'stage_id':stage['id'], 'observation':stage['observation_ref'], 'acceptance':stage['acceptance']}
    contract = None
    if desc.get('job_file'):
        producing_job = _job(desc['job_file'], admission)
        if plugin == 'agent-tuneup':
            planning.need(inputs['requirements'] == producing_job['requirements'], 'integrated requirements differ from producing job')
        contract = {'workflow':producing_job['workflow'], 'requirements':producing_job['requirements'],
            'authorization':producing_job['authorization'], 'constraints':producing_job['constraints'],
            'stages':[{k:s[k] for k in ('id','depends_on','requirements','criteria','validator_contract') if k in s}
                      for s in producing_job['stages']]}
    author_list, producers = authors(admission, documents, desc.get('job_file'))
    from shared.ape_planning import evidence_unique
    evidence = evidence_unique(evidence)
    domain = {k:deepcopy(v) for k,v in desc.items() if k != 'planning_review'}
    out = planning.capture({'output_name':admission['output_name'], 'output_type':KINDS[plugin][kind],
        'requirements':inputs['requirements'], 'load_bearing_decisions':inputs.get('load_bearing_decisions', []),
        'requests':deepcopy(inputs['requests']), 'decisions':deepcopy(inputs['decisions']),
        'documents':documents, 'rubrics':[str(_package_file(package, 'references/adopter-review-rubric.md'))],
        'templates':[], 'repository_root':None if plugin == 'focus-group' else inputs['repository_root'],
        **({'focus_group_evidence_root':inputs['repository_root'], 'repository_head':None} if plugin == 'focus-group' else {}),
        'evidence_paths':evidence,
        'declared_paths':list(dict.fromkeys([r['path'] if isinstance(r,dict) else r for r in evidence] + inputs.get('declared_paths', []))),
        'authors':author_list, 'adopter_descriptor':domain, 'adopter_producers':producers,
        'adopter_factual':factual, 'adopter_contract':contract, 'adopter_selection_sha256':admission['selection_sha256']})
    planning.need(out['logical_output_id'] == admission['scope_id'], 'stable subject scope differs')
    return out


def _same(current, frozen):
    current = deepcopy(current); current.pop('sha256'); current['repository_head'] = frozen.get('repository_head')
    planning.need([{k:v for k,v in r.items() if k != 'path'} for r in current['rubrics']] ==
                  [{k:v for k,v in r.items() if k != 'path'} for r in frozen['rubrics']], 'domain rubric changed')
    current['rubrics'] = frozen['rubrics']
    planning.need(planning.seal(current) == frozen, 'reviewed source/request/criteria/author changed')


def prepare(desc, inputs, metadata_file, package):
    snap = source_snapshot(desc, inputs, package)
    path = Path(metadata_file)
    planning.need(path.is_absolute() and not path.resolve().is_relative_to(Path(inputs['repository_root']).resolve()),
                  'metadata must be private outside target checkout')
    if path.exists():
        prior = strict_load(_regular(path))
        planning.need(prior['scope_id'] == snap['logical_output_id'], 'metadata cannot change logical output')
        try:
            _same(snap, prior['snapshot'])
            if prior.get('reference'):
                planning.validate_receipt(prior['reference'], expected_snapshot=prior['snapshot']['sha256'])
                return {'snapshot':prior['snapshot'], 'subject_file':prior['subject_file'], 'metadata':planning.file_descriptor(path)}
        except ValueError:
            pass  # changed revision retains the shared subject's history/budget
    subject = planning.subject_root(desc['admission']['selection']['project_id']) / snap['logical_output_id'] / 'review.json'
    meta = {'schema_version':1, 'scope_id':snap['logical_output_id'], 'subject_file':str(subject),
            'inputs':deepcopy(inputs), 'snapshot':snap, 'reference':None}
    _atomic(path, canonical(meta))
    return {'snapshot':snap, 'subject_file':str(subject), 'metadata':planning.file_descriptor(path)}


def _receipt(desc, meta, package):
    planning.unseal(meta['snapshot'])
    _same(source_snapshot(desc, meta['inputs'], package), meta['snapshot'])
    r = planning.validate_receipt(meta['reference'], expected_snapshot=meta['snapshot']['sha256'])
    planning.need(r['subject_file'] == meta['subject_file'] and r['logical_output_id'] == meta['scope_id'] and
                  r['selection_sha256'] == desc['admission']['selection_sha256'], 'receipt subject/selection differs')
    from shared.job_coordinator import pinned_store, verify_all_pins
    p = Path(r['job_file']); job = verify_all_pins(pinned_store(p.parent.parent,p.parent.name))
    planning.need(job['workflow'] == desc['admission']['plugin'] + '/planning-review', 'wrong planning workflow purpose')
    pin = next(job['pins'][d['key']] for d in job['dependencies'] if d['plugin'] == desc['admission']['plugin'])
    planning.need(_regular(Path(__file__)) == _regular(Path(pin['package_dir']) / 'shared/adopter_planning.py'),
                  'adopter adapter differs from pinned review; use its producing package')
    return r


def validate_observation(data, desc, package):
    """The accepted integrated report must publish the reviewed conclusions."""
    validate(desc, package)
    planning.need(desc['admission']['plugin'] == 'agent-tuneup' and
                  desc['observation_conclusions'] == {k: data.get(k) for k in ('findings', 'changes')},
                  'published observation findings/changes differ from reviewed conclusions')


def validate(desc, package):
    planning.need(isinstance(desc.get('planning_review'), dict), 'planning metadata required')
    planning.current_file(desc['planning_review'])
    meta = strict_load(_regular(Path(desc['planning_review']['path'])))
    planning.need(meta.get('schema_version') == 1 and meta.get('reference'), 'actual planning receipt missing')
    r = _receipt(desc, meta, package)
    return {k:deepcopy(r[k]) for k in ('passes','rounds_used','round_limit','degraded_panel','findings','subject_file','selection_sha256')} | {
        'snapshot_sha256':meta['snapshot']['sha256'], 'execution_authorized':False,
        'head_observation':planning.head_observation(meta['snapshot'])}


def attach(desc, metadata_file, receipt, package):
    path = Path(metadata_file); meta = strict_load(_regular(path))
    meta['reference'] = planning.file_descriptor(receipt)
    _receipt(desc, meta, package)
    _atomic(path, canonical(meta))
    return {'metadata':planning.file_descriptor(path), 'subject_file':meta['subject_file']}


def approve(desc, owner, package):
    """Only after review, record the concrete owner answer and reviewed digest."""
    r = validate(desc, package)
    planning.need(desc['admission']['plugin'] == 'agent-tuneup' and desc['kind'] == 'proposal', 'concrete proposal required')
    models.source(owner['source'])
    planning.need(_regular(Path(owner['path'])).decode('utf-8') == owner['source']['answer'], 'owner source bytes differ')
    planning.need(owner['plan_digest'] == desc['plan_digest'], 'approval is for another concrete plan')
    return planning.seal({'schema_version':1, 'proposal':deepcopy(desc), 'owner':deepcopy(owner),
                          'owner_file':planning.file_descriptor(owner['path']), 'snapshot_sha256':r['snapshot_sha256']})


def apply_ready(context, document, package):
    """Revalidate the reviewed proposal AND concrete owner approval before writes."""
    admission = context['admission']; continuation(admission, invocation_id=admission['invocation_id'])
    planning.need(admission['plugin'] == 'agent-tuneup' and admission['operation'] == 'apply', 'apply choices required')
    approval = context['approval']; planning.unseal(approval)
    planning.need(document == strict_load(_regular(Path(approval['proposal']['plan_file']))),
                  'applied plan differs from the concrete reviewed proposal')
    planning.current_file(approval['owner_file'])
    reviewed = validate(approval['proposal'], package)
    planning.need(reviewed['snapshot_sha256'] == approval['snapshot_sha256'] and
        document['approval_digest'] == approval['owner']['plan_digest'] == approval['proposal']['plan_digest'],
        'candidate change reopens review and concrete owner approval')
    models.source(approval['owner']['source'])
    planning.need(_regular(Path(approval['owner']['path'])).decode('utf-8') == approval['owner']['source']['answer'], 'owner answer changed')
    return {'ready':True, 'review':reviewed, 'execution_authorized':False}


def publish(desc, output_file, package):
    result = validate(desc, package)
    path = Path(output_file)
    meta = strict_load(_regular(Path(desc['planning_review']['path'])))
    planning.need(path.is_absolute() and not path.resolve().is_relative_to(Path(meta['inputs']['repository_root']).resolve()),
                  'review descriptor must stay private outside target checkout')
    _atomic(path, canonical(desc))
    return {'descriptor':planning.file_descriptor(path),'review':result}


def _resource(stage, name):
    resources = stage.get('resources',{})
    desc, locator = resources.get(name), resources.get(name+'_file')
    planning.need(not (desc and locator), 'declare one review descriptor or locator, not both')
    if locator:
        planning.need(Path(locator).is_absolute(), 'absolute private review descriptor locator required')
        desc = strict_load(_regular(Path(locator)))
    return desc


def focus_group_adapter(package):
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('focus_group_planning_adapter', Path(package) / 'scripts/plan_review.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_job(job, stage_id=None, *, previous=None, creating=False):
    workflow = job.get('workflow',''); plugin, _, op = workflow.partition('/')
    if plugin == 'focus-group' and op in ('run', 'resume'):
        dependency = next((d for d in job.get('dependencies', []) if d['plugin'] == plugin), None)
        pin = job.get('pins', {}).get(dependency['key']) if dependency else None
        if pin:
            # Public create has not replaced proposed pins yet. Never import
            # executable policy selected by a caller before independent checks.
            from shared.job_coordinator import verify_pinned_dependency
            verify_pinned_dependency(dependency, pin)
            package = Path(pin['package_dir'])
        else:
            runtime = Path(__file__).resolve().parents[1]
            package = runtime if (runtime / 'plugin.json').is_file() else runtime / 'plugins/focus-group'
            meta = strict_load(_regular(package / 'plugin.json'))
            planning.need(meta.get('name') == 'focus-group', 'use the focus-group packaged coordinator helper')
        focus_group_adapter(package).validate_job(job, previous=previous, creating=creating)
        return
    if plugin not in OPS or op not in OPS[plugin]:
        return
    # Imported historical jobs retain their old contract. Public creation always
    # supplies model_selection and cannot enter this compatibility branch.
    if not job.get('model_selection') and not job.get('policy',{}).get('model_selection_required'):
        return
    record = job.get('adopter_admission')
    planning.need(isinstance(record,dict), 'adopter admission missing before substantive work')
    continuation(record, invocation_id=job.get('invocation_id'))
    planning.need(record['plugin'] == plugin and record['operation'] == op and job.get('scope_id') == record['scope_id'], 'job operation/scope differs')
    selected = models.validate(job.get('model_selection'),job.get('model_selection_sha256'))
    producing = (job.get('model_selection_history') or {}).get(record['selection_sha256'], selected)
    planning.need(models.validate(producing,record['selection_sha256']) == record['selection'], 'job producing selection differs')
    from shared.job_coordinator import selection_for_task
    for t in job['tasks']:
        selection_for_task(dict(job,policy=dict(job.get('policy',{}),model_selection_required=True)),t)
    strategy = job.get('adopter_strategy') or next((_resource(s,'adopter_strategy') for s in job['stages']
        if s.get('resources',{}).get('adopter_strategy') or s.get('resources',{}).get('adopter_strategy_file')),None)
    if strategy:
        planning.need(strategy['admission'] == record, 'strategy belongs to another invocation')
        pin = next((job['pins'][d['key']] for d in job['dependencies'] if d['plugin'] == plugin), None)
        planning.need(pin, 'strategy package must be pinned before execution')
        validate(strategy,Path(pin['package_dir']))
    if plugin == 'elephant-goldfish' and op == 'elephant' and stage_id:
        stage = next(s for s in job['stages'] if s['id']==stage_id)
        if stage.get('validator_contract',{}).get('mode') == 'cold-read':
            desc = _resource(stage,'adopter_design') or job.get('adopter_design')
            planning.need(desc and desc['admission'] == record, 'design review required before cold read')
            contract=stage['validator_contract']
            planning.need(desc['document']['path']==contract['document_path'] and
                          desc['document']['sha256']==contract['document_sha256'], 'design review concerns another cold-read document')
            pin = next(job['pins'][d['key']] for d in job['dependencies'] if d['plugin']==plugin)
            validate(desc,Path(pin['package_dir']))
