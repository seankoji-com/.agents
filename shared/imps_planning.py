"""IMPS admission and receipt consumption. No model calls or review decisions.

Core remains format-neutral. The public IMPS launcher and installed stage validator
use this adapter; planning_review alone validates separate planning assessments.
"""
from copy import deepcopy
import json
from pathlib import Path

from core.jobs.store import _regular, _atomic, _retain, canonical, strict_load, digest
from shared import model_selection as models, planning_review as planning
from shared.lineage import lineage

FINAL = {'audit', 'investigation', 'blast-radius'}
PLANS = {'run', 'issues', 'checklist', 'discussion'}
DIRECT = {'doctor', 'status', 'cancel', 'recipe-scaffold', 'recipe-check', 'lookup'}
NOTE = 'imps-planning-v1:'


def operation(value):
    value = value.removeprefix('imps/')
    return {'imp-agency': 'audit', 'issue-mode': 'issues'}.get(value, value)


def admit(data):
    op = operation(data['operation'])
    if op in DIRECT:
        return {'allowed': True, 'chooser': False, 'dispatch': False}
    planning.need(op in FINAL | PLANS | {'verification-init', 'prs'}, 'unsupported imps operation')
    scope = planning.logical_output_id(data['request_reference'], data['output_name'])
    planning.need(bool(data.get('selection_sha256')), 'producing selection digest required')
    selected = models.validate(data.get('selection'), data['selection_sha256'])
    from shared.execution_agreement import admit as agreement_admit
    agreement_admit(selected, operation='imps/' + op)
    models.gate(selected, invocation_id=data['invocation_id'], scope_id=scope,
                expected=data['selection_sha256'], action='investigate')
    planning.need('imps/' + op in selected.get('agreement', {}).get('operations', []) or
                  operation(selected['operation']) == op, 'selection operation differs')
    role = 'judgement' if op in FINAL else 'workhorse'
    models.dispatch(selected, role=role)
    if op in FINAL | {'verification-init'}:
        planning.need(any(s['required'] for s in selected['review_panel']), 'operation needs an applicable planning panel')
    return planning.seal({'schema_version': 1, 'operation': op,
        'request_reference': data['request_reference'], 'output_name': data['output_name'],
        'scope_id': scope, 'invocation_id': data['invocation_id'], 'selection': selected,
        'selection_sha256': selected['selection_sha256'], 'forwarded': False})


def continuation(record, *, invocation_id, event='wake', forward=False, retain=None):
    planning.unseal(record)
    planning.need(not forward or not record['forwarded'], 'alias selection was already forwarded')
    models.gate(record['selection'], invocation_id=invocation_id, scope_id=record['scope_id'],
        event='forward' if forward else event, expected=record['selection_sha256'],
        action='investigate', pinned=True, retain=retain)
    if forward:
        record = deepcopy(record); record.pop('sha256'); record['forwarded'] = True
        return planning.seal(record)
    return record


def _identity(selected, value):
    pid, mid = models.key(value)
    provider = next(p for p in selected['capabilities']['providers'] if p['providerInstanceId'] == pid)
    driver = provider.get('driverKind', pid)
    return {'providerInstanceId': pid, 'model': mid, 'driver_kind': driver, 'lineage': lineage(driver, mid)}


def _authors(admission, documents, job_file=None, producers=None):
    selected = admission['selection']
    result = [_identity(selected, selected['coordinator'])]
    # Include prospective selected work authors as well as observed executions.
    result.extend(_identity(selected, t) for t in selected['work'].values())
    if job_file:
        from shared.job_coordinator import pinned_store, verify_all_pins
        from core.jobs.store import tasks
        path = Path(job_file)
        job = verify_all_pins(pinned_store(path.parent.parent, path.parent.name))
        planning.need(job['workflow'] == 'imps/' + admission['operation'] and
                      job.get('imps_admission', {}).get('scope_id') == admission['scope_id'],
                      'another producing job/admission')
        producer = (job.get('model_selection_history') or {}).get(admission['selection_sha256'], job.get('model_selection'))
        planning.need(models.validate(producer, admission['selection_sha256']) == selected, 'producing choice differs')
        for task in tasks(job):
            if task.get('role') == 'review':
                continue
            handles = task.get('handles', []) + task.get('followups', [])
            if task in job['tasks']:
                planning.need(handles, 'actual producer execution identity missing')
            for h in handles:
                identity = h.get('observed_identity', {})
                planning.need(identity.get('status') == 'verified', 'actual producer identity unverified')
                planning.need(h.get('status') in ('completed', 'cancelled', 'interrupted', 'failed') and
                    not h.get('has_pending_child_runs') and h.get('work_state') == 'result_available',
                    'producer execution pending')
                request = h['request_id']
                brief_path = (Path(task['brief']['path']) if request == task['request_id'] else
                    path.parent / 'briefs' / ('followup' if h in task.get('followups', []) else '') /
                    (task['task_id'] + '-' + digest(request.encode()) + '.json'))
                brief = strict_load(_regular(brief_path))
                planning.need(brief['request_id'] == request and brief['worker_id'] == task['worker_id'],
                              'actual producer brief correlation differs')
                frozen = brief.get('model_selection') or {}
                sha = frozen.get('selection_sha256')
                producer = (job.get('model_selection_history') or {}).get(sha, job.get('model_selection'))
                models.validate(producer, sha)
                binding = frozen['binding']
                dispatch = models.dispatch(producer, role=binding['role'], slot_id=binding.get('slot_id'),
                    target=binding.get('target'), unavailable=binding.get('unavailable'),
                    data_classes=binding.get('data_classes', ['repository']), expected=sha)
                for key in ('providerInstanceId', 'model', 'options', 'runtimeMode'):
                    planning.need(brief['target'].get(key) == dispatch['target'].get(key) and
                                  h['target'].get(key) == brief['target'].get(key), 'producer target/options differ')
                observations = [e[k] for e in task.get('dispatch_history', []) if e.get('request_id') == request
                    for k in ('status_identity', 'receipt_identity', 'configuration_identity') if isinstance(e.get(k), dict)]
                for observed in observations:
                    models.correlate(dispatch, {**identity, **observed})
                if producers is not None:
                    producers.append({'request_id': request, 'task_id': task['task_id'], 'selection': producer,
                        'selection_sha256': sha, 'brief': planning.file_descriptor(brief_path),
                        'target': dispatch['target'], 'identity': identity, 'observations': observations,
                        'result_ref': task.get('result_ref')})
                result.append(_identity(producer, identity))
        for stage in job['stages'] + [s for h in job.get('history', []) for s in h.get('stages', [])]:
            if stage.get('execution_mode') == 'direct':
                if 'final_plan' in stage.get('validator_contract', {}):
                    continue  # deterministic integration adds no authored conclusion
                observations = stage.get('direct_execution_history')
                planning.need(observations, 'actual direct producer identity missing')
                for row in observations:
                    sha = (row.get('model_selection') or {}).get('selection_sha256')
                    producer = (job.get('model_selection_history') or {}).get(sha, job.get('model_selection'))
                    models.validate(producer, sha)
                    binding = stage.get('selection_binding') or {}
                    dispatch = models.dispatch(producer, role=binding['role'], target=binding.get('target'),
                        unavailable=binding.get('unavailable'), data_classes=binding.get('data_classes', ['repository']), expected=sha)
                    planning.need(dispatch['target'] == row['model_selection']['dispatch']['target'],
                                  'direct producer target/options differ')
                    models.correlate(dispatch, row['identity'])
                    if producers is not None:
                        producers.append({'stage_id': stage['id'], 'selection': producer,
                            'selection_sha256': sha, 'identity': row['identity'], 'dispatch': row['model_selection']})
                    result.append(_identity(producer, row['identity']))
    from shared.document_authors import import_subject_authors
    for doc in documents:
        row = planning.file_descriptor(doc) if isinstance(doc, str) else doc
        if (Path(row['path']).parent / 'document-authors.json').exists():
            for author in import_subject_authors(row):
                result.append({'unknown': True, 'lineage': 'unknown'} if author.get('unknown') else _identity(selected, author))
    return sorted({canonical(a): a for a in result}.values(), key=canonical)


def trigger(plan, stages):
    planning.need(isinstance(stages, list) and stages and all(isinstance(s, dict) for s in stages),
                  'declare every gate-plan stage')
    planning.need(all(set(s) == {'id', 'actions', 'output_type'} and isinstance(s['id'], str) and s['id'] and
        isinstance(s['actions'], list) and s['actions'] and set(s['actions']) <= {'read', 'write'} and
        s['output_type'] in ('inspection', 'command', 'runtime', 'implementation', 'synthesis', 'recommendation', 'strategy')
        for s in stages), 'each stage needs explicit identity/actions/output type')
    planning.need(len({s['id'] for s in stages}) == len(stages), 'stage identities must be distinct')
    auth = plan.get('authorization', {})
    writes = any(a not in ('read', 'inspect', 'inspection', 'local-checks', 'test') for a in auth.get('local', []))
    return bool(writes or auth.get('remote') or auth.get('endstate', 'local') != 'local' or len(stages) > 1 or
                any(s.get('output_type') in ('synthesis', 'recommendation', 'strategy') or
                    any(a != 'read' for a in s.get('actions', [])) for s in stages))


def _effective(plan, package):
    from core import planning as core_plan, fsutil, store
    return core_plan.build(plan, fsutil.read_json(Path(package) / 'config.json'),
        state_root=store.env_state_root('imps'), plugin={'name': 'imps'}, clock_iso='frozen')


def descriptor(admission, kind, **values):
    continuation(admission, invocation_id=admission['invocation_id'])
    planning.need(kind in ('initial-plan', 'synthesis', 'verification-recipe'), 'unsupported output kind')
    op = admission['operation']
    planning.need((kind == 'synthesis' and op in FINAL) or (kind == 'initial-plan' and op in PLANS) or
                  (kind == 'verification-recipe' and op == 'verification-init'), 'output kind differs from operation')
    return {'kind': kind, 'admission': admission, **values}


def source_snapshot(desc, inputs, package):
    desc = deepcopy(desc)
    if desc['kind'] == 'initial-plan' and not desc.get('document') and desc.get('planning_review'):
        planning.current_file(desc['planning_review'])
        meta = strict_load(_regular(Path(desc['planning_review']['path'])))
        desc['document'] = meta['snapshot']['imps_descriptor']['document']
    admission = desc['admission']; continuation(admission, invocation_id=admission['invocation_id'])
    kind = desc['kind']; descriptor(admission, kind)
    planning.current_file(desc['document'])
    planning.need(set(inputs) <= {'requests', 'decisions', 'requirements', 'load_bearing_decisions',
        'repository_root', 'evidence_paths', 'declared_paths', 'attachments'}, 'unsupported review input')
    planning.need(inputs['requests'][0]['reference'] == admission['request_reference'], 'source request differs')
    documents = list(inputs.get('attachments', []))
    domain = {k: deepcopy(v) for k, v in desc.items() if k != 'planning_review'}
    if kind == 'initial-plan':
        raw = strict_load(_regular(Path(desc['document']['path'])))
        planning.need(raw == {k: v for k, v in desc.items() if k not in ('document', 'planning_review')},
                      'initial plan body differs from bound document')
        documents.insert(0, desc['document'])
        effective = _effective(desc['plan'], package)
        expected = {r['id']: r['text'] for r in effective['brief']['requirements']}
        planning.need(inputs['requirements'] == expected, 'requirements differ from effective gate plan')
        trigger(desc['plan'], desc['stages'])
        domain['effective_contract'] = {k: effective[k] for k in ('brief', 'authorization', 'policy', 'repo', 'roles', 'host')}
    else:
        planning.need(desc['requirements'] == inputs['requirements'], 'output criteria differ from source contract')
        documents.insert(0, desc['document'])
    root = str(Path(inputs['repository_root']).resolve())
    if kind == 'initial-plan':
        planning.need(root == effective['repo']['worktree'], 'plan repository differs from evidence root')
    if kind == 'verification-recipe':
        from core import schema
        facts = strict_load(_regular(Path(desc['document']['path'])))
        schema.validate(facts, 'recipe-facts', 'facts_invalid')
    # Confidential duplicate labels cannot be erased by an ordinary optional read.
    from shared.ape_planning import evidence_unique
    evidence = evidence_unique(inputs['evidence_paths'])
    templates = [str(Path(package) / 'templates' / f) for f in ('feature.md', 'verify-project.md')] if kind == 'verification-recipe' else []
    producers = []
    authors = _authors(admission, documents, desc.get('job_file') if kind == 'synthesis' else None, producers)
    if any(not (Path(row['path'] if isinstance(row, dict) else row).parent / 'document-authors.json').exists()
           for row in inputs.get('attachments', [])):
        authors.append({'unknown': True, 'lineage': 'unknown'})
    snap = planning.capture({'output_name': admission['output_name'],
        'output_type': {'initial-plan': 'implementation-plan', 'synthesis': 'synthesis',
                        'verification-recipe': 'verification-recipe'}[kind],
        'requirements': inputs['requirements'], 'load_bearing_decisions': inputs.get('load_bearing_decisions', []),
        'requests': inputs['requests'], 'decisions': inputs['decisions'], 'documents': documents,
        'rubrics': [str(Path(package) / 'references/plan-review-rubric.md')], 'templates': templates,
        'repository_root': root, 'evidence_paths': evidence,
        'declared_paths': list(dict.fromkeys([*(r['path'] if isinstance(r, dict) else r for r in evidence),
                                             *inputs.get('declared_paths', [])])),
        'authors': authors, 'imps_producer_bindings': sorted({canonical(p): p for p in producers}.values(), key=canonical),
        'imps_descriptor': domain, 'imps_selection_sha256': admission['selection_sha256']})
    planning.need(snap['logical_output_id'] == admission['scope_id'], 'logical subject differs')
    return snap


def _same(current, frozen):
    current = deepcopy(current); current.pop('sha256'); current['repository_head'] = frozen.get('repository_head')
    for field in ('rubrics', 'templates'):
        planning.need([{k: v for k, v in r.items() if k != 'path'} for r in current[field]] ==
                      [{k: v for k, v in r.items() if k != 'path'} for r in frozen[field]], 'imps ' + field + ' changed')
        current[field] = frozen[field]
    planning.need(planning.seal(current) == frozen, 'reviewed request/output/criteria/source/authors changed')


def _validate_job_contract(contract):
    """Reject impossible authored task/stage fields before a review is prepared."""
    from core import schema
    planning.need(isinstance(contract, dict), 'initial job contract must be an object')
    published = schema.load_schema_file(Path(__file__).resolve().parent / 'agents/job.schema.json')
    for collection in ('stages', 'tasks'):
        item = deepcopy(published['properties'][collection]['items'])
        # The authored projection omits runtime IDs and lifecycle fields. Its
        # supplied fields still obey the same published types/enums as creation.
        item['required'] = [k for k in item.get('required', [])
                            if k in ('id', 'task_id', 'stage_id', 'worker_id')]
        problems = schema.errors(contract.get(collection), {'type': 'array', 'items': item},
                                 root=published, path='$.job_contract.' + collection)
        planning.need(not problems, 'invalid initial job contract: ' + '; '.join(problems[:10]))


def prepare(desc, inputs, metadata_file, package):
    if 'job_contract' in desc:
        _validate_job_contract(desc['job_contract'])
    path = Path(metadata_file)
    planning.need(path.is_absolute() and not path.resolve().is_relative_to(Path(inputs['repository_root']).resolve()),
                  'persistent review metadata must be absolute and outside target repository')
    desc = deepcopy(desc)
    if desc['kind'] == 'initial-plan' and not desc.get('document'):
        body = canonical({k: v for k, v in desc.items() if k not in ('document', 'planning_review')})
        document = path.parent / 'plan-sources' / (digest(body) + '.json')
        _retain(document, body, 'immutable initial plan body changed')
        desc['document'] = planning.file_descriptor(document)
    snapshot = source_snapshot(desc, inputs, package)
    if path.exists():
        old = strict_load(_regular(path))
        planning.need(old['scope_id'] == snapshot['logical_output_id'], 'metadata cannot change logical subject')
        if old.get('reference'):
            try:
                _same(snapshot, old['snapshot']); validate({**desc, 'planning_review': planning.file_descriptor(path)}, package)
                return {'snapshot': old['snapshot'], 'subject_file': old['subject_file'], 'metadata': planning.file_descriptor(path), 'descriptor': desc}
            except ValueError:
                pass  # A repair keeps the same persistent subject and its budget/history.
    subject = planning.subject_root(desc['admission']['selection']['project_id']) / snapshot['logical_output_id'] / 'review.json'
    meta = {'schema_version': 1, 'scope_id': snapshot['logical_output_id'], 'subject_file': str(subject),
            'inputs': deepcopy(inputs), 'snapshot': snapshot, 'reference': None}
    _atomic(path, canonical(meta))
    return {'snapshot': snapshot, 'subject_file': str(subject), 'metadata': planning.file_descriptor(path), 'descriptor': desc}


def _receipt(desc, meta, package):
    planning.need(meta.get('schema_version') == 1 and meta.get('reference'), 'missing final planning receipt')
    snapshot = meta['snapshot']; planning.unseal(snapshot)
    _same(source_snapshot(desc, meta['inputs'], package), snapshot)
    receipt = planning.validate_receipt(meta['reference'], expected_snapshot=snapshot['sha256'])
    planning.need(receipt['snapshot'] == snapshot and receipt['subject_file'] == meta['subject_file'] and
        receipt['logical_output_id'] == meta['scope_id'] and
        receipt['selection_sha256'] == desc['admission']['selection_sha256'], 'receipt/subject/producing selection differs')
    job = strict_load(_regular(Path(receipt['job_file'])))
    planning.need(job['workflow'] == 'imps/planning-review', 'separate imps planning job required')
    return {'modes': [p['mode'] for p in receipt['passes']], 'rounds_used': receipt['rounds_used'],
        'round_limit': receipt['round_limit'], 'findings': receipt['findings'],
        'requested_panel': receipt['requested_panel'], 'degraded_panel': receipt['degraded_panel'],
        'subject_file': meta['subject_file'], 'reference': meta['reference'],
        'head_observation': planning.head_observation(snapshot), 'execution_authorized': False}


def validate(desc, package):
    ref = desc.get('planning_review')
    planning.need(isinstance(ref, dict), 'imps planning review metadata required')
    planning.current_file(ref)
    return _receipt(desc, strict_load(_regular(Path(ref['path']))), package)


def attach(desc, metadata_file, receipt_file, package):
    path = Path(metadata_file); meta = strict_load(_regular(path))
    meta['reference'] = planning.file_descriptor(receipt_file)
    _receipt(desc, meta, package)
    _atomic(path, canonical(meta))
    return {'metadata': planning.file_descriptor(path), 'subject_file': meta['subject_file']}


def initial(plan, context, package):
    admission = context['admission']; continuation(admission, invocation_id=admission['invocation_id'])
    op = admission['operation']
    if op in FINAL:
        auth = plan.get('authorization', {})
        planning.need(auth.get('endstate', 'local') == 'local' and not auth.get('remote') and
                      all(a in ('read', 'inspect', 'inspection', 'local-checks') for a in auth.get('local', [])),
                      'investigation/audit/blast-radius stays read-only')
        planning.need(Path(context['output_path']).is_absolute(), 'final integrated conclusion path required')
    check = None
    if op in PLANS:
        if trigger(plan, context['stages']):
            check = validate(descriptor(admission, 'initial-plan', plan=plan, stages=context['stages'],
                                planning_review=context.get('planning_review')), package)
    elif op == 'verification-init':
        recipe_ready(context['recipe'], package, context['recipe_file'])
    elif op not in FINAL:
        planning.need(False, 'prs forwards to babysitter; no duplicate imps gate')
    effective = _effective(plan, package)
    return {'plan': deepcopy(plan), 'context': deepcopy(context), 'initial_check': check,
            'effective_contract': {k: effective[k] for k in ('brief', 'authorization', 'policy', 'repo', 'roles', 'host')}}


def run_record(state):
    notes = [n['text'][len(NOTE):] for n in state['notes'] if n['text'].startswith(NOTE + '{')]
    planning.need(len(notes) == 1, 'run requires original imps admission note; legacy-unreviewed')
    record = strict_load(notes[0].encode()); planning.unseal(record)
    return record


def integrated_stage(job):
    """One authored integrated conclusion; composite final gate adds no review."""
    authored = {s['id'] for s in job['stages'] if 'run_id' in s.get('validator_contract', {})}
    planning.need(authored, 'synthesis job requires an authored conclusion gate')
    stages = {s['id']: s for s in job['stages']}
    def ancestors(sid):
        found = set()
        pending = list(stages[sid]['depends_on'])
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current); pending.extend(stages[current]['depends_on'])
        return found
    candidates = [sid for sid in authored if authored - {sid} <= ancestors(sid) and
                  set(stages[sid]['requirements']) == set(job['requirements'])]
    planning.need(len(candidates) == 1, 'synthesis job needs one final integrated gate covering all authored stages/requirements')
    return candidates[0]


def intermediate(state, record):
    context = record['context']
    if not context.get('job_file'):
        return False
    from core.jobs.store import Store
    from shared.job_coordinator import verify_job_pins
    path = Path(context['job_file'])
    planning.need(path.is_absolute() and path.name == 'job.json', 'absolute producing job.json required')
    job = Store(path.parent.parent, path.parent.name, verify_pins=verify_job_pins).verified_load()
    planning.need(job['workflow'] == 'imps/' + context['admission']['operation'] and
                  job.get('authorization', {}).get('actions') == ['read'], 'source job differs or is writable')
    stage = next(s for s in job['stages'] if s['id'] == context['stage_id'])
    contract = stage['validator_contract']
    planning.need(contract.get('run_id') == state['run_id'] and
                  Path(contract['state_root']).resolve() == Path(record['state_root']).resolve() and
                  context['output_path'] in stage.get('outputs', []), 'gate does not belong to producing stage/output')
    return stage['id'] != integrated_stage(job)


def validate_run(state, package, *, final=True):
    record = run_record(state)
    context = record['context']; admission = context['admission']
    continuation(admission, invocation_id=admission['invocation_id'])
    if admission['selection'].get('agreement'):
        planning.need(state['policy'].get('model_preferences', {}).get('agreement_sha256') ==
                      admission['selection']['agreement']['agreement_sha256'], 'run producing agreement binding changed')
    # Initial review proves the plan before execution. Planned source edits do not
    # erase that historical gate; the original receipt bytes and contract stay pinned.
    if admission['operation'] in PLANS and trigger(record['plan'], context['stages']):
        planning.need(record.get('initial_check'), 'initial review observation missing')
        planning.current_file(context['planning_review'])
        planning.current_file(record['initial_check']['reference'])
    elif admission['operation'] == 'verification-init':
        recipe_ready(context['recipe'], package, context['recipe_file'])
    effective = record['effective_contract']
    planning.need(all(effective[k] == state[k] for k in ('brief', 'authorization', 'policy', 'repo', 'roles', 'host')),
                  'run contract changed since initial planning review')
    if final and admission['operation'] in FINAL:
        if intermediate(state, record):
            return {'required_final_review': False, 'intermediate': True}
        notes = [strict_load(n['text'][len(NOTE + 'final:'):].encode()) for n in state['notes']
                 if n['text'].startswith(NOTE + 'final:')]
        planning.need(notes, 'final integrated conclusions require planning review, including zero/no-change')
        desc = notes[-1]
        planning.need(desc['admission'] == admission and desc['document']['path'] == context['output_path'] and
                      desc.get('job_file') == context.get('job_file'),
                      'final conclusion differs from run output/admission')
        planning.need(desc['requirements'] == {r['id']: r['text'] for r in state['brief']['requirements']},
                      'final criteria differ from run')
        return validate(desc, package)
    return {'required_final_review': False}


def recipe_ready(desc, package, recipe_file):
    planning.need(desc['kind'] == 'verification-recipe', 'authored verification recipe required')
    result = validate(desc, package)
    facts = strict_load(_regular(Path(desc['document']['path'])))
    from core import recipe
    path = Path(recipe_file)
    planning.need(recipe.check(path)['valid'], 'recipe deterministic checks failed')
    actual = strict_load(_regular(path))
    expected = {'schema_version': 1, 'project': facts['project'], 'prerequisites': facts['prerequisites'],
        'variables': facts.get('variables', {}), 'launch': facts['launch'], 'doctor': facts['doctor'],
        'cleanup': facts['cleanup'], 'evidence': {'dir': 'evidence', 'expected': [f['observe'] for f in facts['features'][:5]]},
        'features': [{'id': f['id'], 'name': f['name'], 'doc': f'features/{f["id"].lower()}.md',
                      'steps': f['steps'], 'expect': f['expect']} for f in facts['features'][:5]]}
    planning.need({k: v for k, v in actual.items() if k not in ('status', 'verified_run')} == expected,
                  'recipe launch/drive/cleanup/features differ from reviewed facts')
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='imps-recipe-check-') as scratch:
        rendered = recipe.scaffold(facts, Path(package) / 'templates', Path(scratch))
        directory = Path(rendered['dir'])
        for rel in ['SKILL.md', 'features/index.md', *(f['doc'] for f in actual['features'])]:
            planning.need(_regular(path.parent / rel) == _regular(directory / rel),
                          'rendered recipe instructions differ from reviewed facts/templates')
    return {**result, 'facts': facts, 'recipe': str(path),
            'admitted_steps': ['launch', 'drive', 'observe', 'cleanup']}


def validate_job(job, job_file=None, *, before_execution=False):
    if job.get('workflow') not in {'imps/' + op for op in FINAL | PLANS}:
        return
    record = job.get('imps_admission')
    planning.need(isinstance(record, dict), 'imps admission missing; select before work')
    continuation(record, invocation_id=record['invocation_id'])
    planning.need(job['workflow'] == 'imps/' + record['operation'] and job.get('scope_id') == record['scope_id'],
                  'imps job scope/operation differs')
    selected = models.validate(job.get('model_selection'), job.get('model_selection_sha256'))
    planning.need(selected['scope_id'] == record['scope_id'], 'current selection belongs to another job scope')
    producing = job.get('model_selection_history', {}).get(record['selection_sha256'], selected)
    planning.need(models.validate(producing, record['selection_sha256']) == record['selection'], 'producing choice differs')
    if record['operation'] in FINAL:
        planning.need(job.get('authorization', {}).get('actions') == ['read'], 'synthesis job stays read-only')
        integrated_stage(job)
    else:
        carrier = job_review(job)
        desc = carrier['descriptor']
        planning.need(isinstance(desc, dict) and desc['admission']['scope_id'] == record['scope_id'] and
                      desc.get('job_contract') == job_contract(job), 'job needs its exact initial gate plan')
        planning.need({s['id'] for s in desc['stages']} == {s['id'] for s in job['stages']},
                      'initial plan must declare every job stage')
        package = next(Path(d['package_dir']) for d in job.get('dependencies', [])
                       if d['plugin'] == 'imps' and d.get('package_dir')) if any(
                       d.get('package_dir') for d in job.get('dependencies', []) if d['plugin'] == 'imps') else None
        if package is None:
            # Source creation runs before pinning. The selected source helper is
            # byte-checked by the pinned stage path when its receipt is consumed.
            package = Path(__file__).resolve().parents[1] / 'plugins/imps'
            if not package.exists():
                package = Path(__file__).resolve().parents[1]
        planning.need({r['id']: r['text'] for r in desc['plan']['brief']['requirements']} == job['requirements'],
                      'initial job requirements differ')
        actions = job['authorization'].get('actions', [])
        requires_review = len(job['stages']) > 1 or any(a != 'read' for a in actions) or any(
            s.get('output_type') in ('synthesis', 'recommendation', 'strategy') for s in desc['stages'])
        if requires_review:
            if before_execution:
                job['imps_initial_check'] = validate(desc, package)
            else:
                planning.need(carrier['check'], 'initial job review observation missing')
                planning.current_file(desc['planning_review'])
                meta = strict_load(_regular(Path(desc['planning_review']['path'])))
                frozen = deepcopy(meta['snapshot']['imps_descriptor']); frozen.pop('effective_contract', None)
                planning.need(frozen == {k: v for k, v in desc.items() if k != 'planning_review'} and
                              meta['reference'] == carrier['check']['reference'], 'historical job plan binding differs')
                planning.current_file(carrier['check']['reference'])
    from core.store import RunStore
    for stage in job['stages']:
        contract = stage.get('validator_contract', {})
        if 'run_id' not in contract:
            continue
        state = RunStore(Path(contract['state_root']), contract['run_id']).load()
        run = run_record(state)
        if record['operation'] in FINAL:
            planning.need(run['context']['admission'] == record and
                          run['context'].get('job_file') == str(job_file) and
                          run['context'].get('stage_id') == stage['id'] and
                          run['context']['output_path'] in stage.get('outputs', []),
                          'gate producing admission/job differs from synthesis job')
        validate_run(state, state['plugin']['package_dir'], final=False)


def job_contract(job):
    """Authored initial semantics, excluding lifecycle, gate IDs and observations."""
    return {k: deepcopy(job[k]) for k in ('workflow', 'requirements', 'authorization', 'constraints')} | {
        'repo': deepcopy(job.get('repo', {})),
        'repository_worktree': job.get('resources', {}).get('worktree'),
        'stages': [{k: deepcopy(v) for k, v in s.items() if k in
            ('id', 'depends_on', 'requirements', 'criteria', 'outputs', 'stop_conditions', 'execution_mode')}
                   for s in job['stages']],
        'tasks': [{k: deepcopy(v) for k, v in t.items() if k in
            ('task_id', 'stage_id', 'worker_id', 'role', 'review_required', 'requirements')}
                  for t in job['tasks']]}


def job_review(job):
    """Revisions persist through the existing generic stage resources contract."""
    rows = [s.get('resources', {})['imps_initial_review'] for s in job['stages']
            if 'imps_initial_review' in s.get('resources', {})]
    planning.need(len(rows) <= 1, 'ambiguous initial job review references')
    return rows[0] if rows else {'descriptor': job.get('imps_initial_plan'), 'check': job.get('imps_initial_check')}
