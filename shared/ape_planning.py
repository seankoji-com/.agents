"""Ape admission and parent receipt adapter. Shared planning_review owns acceptance.

The report's local rubric, citations and source validators remain in the ape package.
This adapter neither dispatches nor accepts a planning assessment.
"""
from copy import deepcopy
from pathlib import Path
import re

from core.jobs.store import _regular, _atomic, canonical, strict_load, tasks as all_tasks
from shared import model_selection as models, planning_review as planning
from shared.lineage import lineage

FINAL = {'study', 'forage-synthesis'}


def operation(value):
    if value in ('study', 'ape/study') or isinstance(value, str) and re.fullmatch(
            r'https?://github\.com/[^/\s]+/[^/\s]+(?:/[^\s]*)?', value, re.I):
        return 'study'
    planning.need(value in ('forage', 'ape/forage'), 'unsupported ape operation')
    return 'forage'


def admit(data):
    """Run before project investigation, draft or dispatch; raw fetch stays direct."""
    op = operation(data['operation'])
    scope = planning.logical_output_id(data['request_reference'], data['output_name'])
    selected = models.validate(data.get('selection'), data.get('selection_sha256'))
    from shared.execution_agreement import admit as agreement_admit
    agreement_admit(selected, operation='ape/' + op)
    planning.need(bool(data.get('selection_sha256')), 'producing selection digest required')
    models.gate(selected, invocation_id=data['invocation_id'], scope_id=scope,
                event=data.get('event', 'new'), action='investigate', expected=data['selection_sha256'])
    planning.need(selected['operation'] in (op, 'ape/' + op) or
                  'ape/' + op in selected.get('agreement', {}).get('operations', []), 'selection belongs to another operation')
    for role in ('workhorse', 'judgement') if op == 'forage' else ('workhorse',):
        models.dispatch(selected, role=role)
    planning.need(any(s['required'] for s in selected['review_panel']), 'final report needs an applicable planning panel')
    return planning.seal({'schema_version': 1, 'operation': op,
        'request_reference': data['request_reference'], 'output_name': data['output_name'],
        'scope_id': scope, 'invocation_id': data['invocation_id'],
        'selection_sha256': selected['selection_sha256'], 'selection': selected,
        'forwarded': data['operation'] not in (op, 'ape/' + op)})


def continuation(record, *, invocation_id, event='wake', forward=False):
    planning.unseal(record)
    planning.need(not forward or not record['forwarded'], 'alias selection was already forwarded')
    models.gate(record['selection'], invocation_id=invocation_id, scope_id=record['scope_id'],
                event='forward' if forward else event, action='investigate', expected=record['selection_sha256'])
    if forward:
        record = deepcopy(record)
        record.pop('sha256')
        record['forwarded'] = True
        return planning.seal(record)
    return record


def validate_job(job):
    """Ape's public and direct job creation share the same upfront admission."""
    if job.get('workflow') not in ('ape/study', 'ape/forage'):
        return
    record = job.get('ape_admission')
    planning.need(isinstance(record, dict), 'ape admission missing; select work/review before research')
    continuation(record, invocation_id=job.get('invocation_id'))
    planning.need(job['workflow'] == 'ape/' + record['operation'] and job.get('scope_id') == record['scope_id'],
                  'ape job differs from admitted operation/scope')
    selected = models.validate(job.get('model_selection'), job.get('model_selection_sha256'))
    # New work may use a prospective choice, but cannot relabel produced evidence.
    producing = (job.get('model_selection_history') or {}).get(record['selection_sha256'], selected)
    models.validate(producing, record['selection_sha256'])
    planning.need(producing == record['selection'], 'ape admission producing choice differs')
    planning.need(job.get('authorization', {}).get('actions') == ['read'], 'ape research is read-only')
    stages = job.get('stages', [])
    tasks = job.get('tasks', [])
    for stage in stages:
        if stage.get('resources', {}).get('ape_output_type') == 'forage-synthesis':
            planning.need(stage.get('execution_mode') == 'direct' and
                          not any(t['stage_id'] == stage['id'] for t in tasks) and
                          (stage.get('selection_binding') or {}).get('role') == 'judgement',
                          'declared coordinator synthesis requires a direct judgement binding and no child slot')
    synthesis = [s for s in stages if s.get('resources', {}).get('ape_output_type') == 'forage-synthesis' or
                 any(t['stage_id'] == s['id'] and t['worker_id'] == 'ape/synthesizer' for t in tasks)]
    if job['workflow'] == 'ape/study':
        planning.need(len(stages) == 1 and not synthesis and not stages[0]['depends_on'],
                      'study requires one final research stage')
    else:
        research = [s for s in stages if s not in synthesis]
        planning.need(len(synthesis) == 1 and 1 <= len(research) <= 5 and
                      set(synthesis[0]['depends_on']) == {s['id'] for s in research},
                      'forage requires a final synthesis of every research stage (at most five)')
    from shared.job_coordinator import selection_for_task
    for task in job.get('tasks', []):
        role = 'judgement' if task['worker_id'] == 'ape/synthesizer' else 'workhorse'
        planning.need((task.get('selection_binding') or {}).get('role') == role, 'ape work role binding differs')
        selection_for_task(dict(job, policy=dict(job.get('policy', {}), model_selection_required=True)), task)


def _job(path):
    from shared.job_coordinator import pinned_store, verify_all_pins
    path = Path(path)
    planning.need(path.is_absolute() and path.name == 'job.json', 'absolute producing job.json required')
    store = pinned_store(path.parent.parent, path.parent.name)
    job = verify_all_pins(store)
    validate_job(job)
    pin = next((job['pins'][d['key']] for d in job['dependencies'] if d['plugin'] == 'ape'), None)
    planning.need(pin is not None, 'ape producing package pin missing')
    planning.need(_regular(Path(__file__)) == _regular(Path(pin['package_dir']) / 'shared/ape_planning.py'),
                  'ape adapter differs from producing package; use its pinned helper')
    return job


def _identity(selected, author):
    pid, mid = models.key(author)
    providers = [p for p in selected['capabilities']['providers'] if p['providerInstanceId'] == pid]
    planning.need(len(providers) == 1, 'actual author missing from producing catalog')
    driver = providers[0].get('driverKind', pid)
    return {'providerInstanceId': pid, 'model': mid, 'driver_kind': driver, 'lineage': lineage(driver, mid)}


def authors(job, documents):
    """Include actual researcher, synthesizer and coordinator executions, plus contributors."""
    selected = job['ape_admission']['selection']
    result = [_identity(selected, selected['coordinator'])]
    stages = job['stages'] + [s for h in job.get('history', []) for s in h.get('stages', [])]
    for task in all_tasks(job):
        if task.get('role') == 'review':
            continue
        handles = task.get('handles', []) + task.get('followups', [])
        if not handles and task not in job['tasks']:
            continue  # a superseded slot that never executed contributed no report
        planning.need(handles, 'actual research/synthesizer execution identity is missing')
        for handle in handles:
            observed = handle.get('observed_identity', {})
            planning.need(observed.get('status') == 'verified', 'actual research/synthesizer identity unverified')
            planning.need(handle.get('status') in ('completed', 'failed', 'cancelled', 'interrupted') and
                          not handle.get('has_pending_child_runs') and handle.get('work_state') == 'result_available',
                          'research/synthesizer execution still pending')
            result.append(_identity(selected, observed))
    for stage in stages:
        if stage.get('execution_mode') == 'direct':
            observations = stage.get('direct_execution_history')
            planning.need(observations, 'actual direct research identity is missing')
            result.extend(_identity(selected, row['identity']) for row in observations)
    from shared.document_authors import import_subject_authors
    for row in documents:
        if (Path(row['path']).parent / 'document-authors.json').exists():
            for a in import_subject_authors(row):
                result.append({'unknown': True, 'lineage': 'unknown'} if a.get('unknown') else _identity(selected, a))
    return sorted({canonical(a): a for a in result}.values(), key=canonical)


def source_snapshot(descriptor, inputs, job_file, stage_id, rubric):
    job = _job(job_file)
    admission = job['ape_admission']
    stage = next(s for s in job['stages'] if s['id'] == stage_id)
    planning.need(descriptor['operation'] in FINAL, 'intermediate research has no final planning pass')
    planning.need(descriptor['operation'] == ('study' if admission['operation'] == 'study' else 'forage-synthesis'),
                  'final report operation differs from admission')
    planning.need(set(inputs) <= {'requests', 'decisions', 'requirements', 'load_bearing_decisions',
        'repository_root', 'evidence_paths', 'declared_paths', 'attachments'}, 'unsupported ape review input')
    planning.need(set(inputs['requirements']) == set(stage['requirements']) and
                  all(inputs['requirements'][r] == job['requirements'][r] for r in stage['requirements']),
                  'planning requirements differ from producing research contract')
    planning.need(inputs['requests'][0]['reference'] == admission['request_reference'], 'source request differs from admission')
    planning.need(descriptor['sources'] == stage['validator_contract']['sources'] and descriptor['criteria'] == stage['criteria'],
                  'report source pins/criteria differ from producing stage')
    planning.need(sorted(r['id'] for r in descriptor['requirements']) == sorted(stage['requirements']),
                  'report requirements differ from producing stage')
    if descriptor['operation'] == 'forage-synthesis':
        outputs = sorted(p for s in job['stages'] if s['id'] in stage['depends_on'] for p in s.get('outputs', []))
        planning.need(sorted(r['path'] for r in descriptor['consumed_reports']) == outputs,
                      'synthesis must consume exactly accepted dependency reports')
    planning.need(descriptor['report']['path'] in stage.get('outputs', []),
                  'final report must be a declared producing-stage output')
    documents = [descriptor['report'], *descriptor.get('consumed_reports', [])]
    evidence = [descriptor['fingerprint'], *descriptor['sources'], *inputs['evidence_paths']]
    paths = list(dict.fromkeys(r['path'] if isinstance(r, dict) else r for r in evidence))
    domain = {k: deepcopy(v) for k, v in descriptor.items() if k != 'planning_review'}
    snapshot = planning.capture({'output_name': admission['output_name'], 'output_type': 'synthesis',
        'requirements': inputs['requirements'], 'load_bearing_decisions': inputs.get('load_bearing_decisions', []),
        'requests': deepcopy(inputs['requests']), 'decisions': deepcopy(inputs['decisions']),
        'documents': [*documents, *inputs.get('attachments', [])], 'rubrics': [str(rubric)], 'templates': [],
        'repository_root': inputs['repository_root'], 'evidence_paths': evidence_unique(evidence),
        'declared_paths': list(dict.fromkeys([*paths, *inputs.get('declared_paths', [])])),
        'authors': authors(job, documents), 'ape_descriptor': domain,
        'ape_contract': {'workflow': job['workflow'], 'stage_id': stage_id,
                         'authorization': job['authorization'], 'constraints': job['constraints'],
                         'criteria': stage['criteria'], 'requirements': inputs['requirements']},
        'ape_selection_sha256': admission['selection_sha256']})
    planning.need(snapshot['logical_output_id'] == admission['scope_id'], 'report stable subject scope differs')
    return snapshot


def evidence_unique(rows):
    result = {}
    for row in rows:
        path = row['path'] if isinstance(row, dict) else row
        existing = result.get(path)
        # A repeated optional read must not erase an earlier confidential label.
        old_class = existing.get('data_class', 'repository') if isinstance(existing, dict) else 'repository'
        new_class = row.get('data_class', 'repository') if isinstance(row, dict) else 'repository'
        if existing is not None and old_class not in models.ORDINARY:
            planning.need(new_class in models.ORDINARY or new_class == old_class,
                          'conflicting confidential data classes for the same evidence path')
            continue
        if existing is None or new_class not in models.ORDINARY:
            result[path] = row
    return list(result.values())


def prepare(descriptor, inputs, job_file, stage_id, metadata_file, rubric):
    snapshot = source_snapshot(descriptor, inputs, job_file, stage_id, rubric)
    metadata_file = Path(metadata_file)
    planning.need(metadata_file.is_absolute(), 'absolute report metadata path required')
    planning.need(not metadata_file.resolve().is_relative_to(Path(inputs['repository_root']).resolve()) and
                  not metadata_file.resolve().is_relative_to(Path(job_file).parent.resolve() / 'artifacts'),
                  'report metadata must stay outside the target project and worker artifacts')
    if metadata_file.exists():
        prior = strict_load(_regular(metadata_file))
        planning.need(prior['scope_id'] == snapshot['logical_output_id'], 'report metadata cannot change logical output')
        comparable = deepcopy(snapshot)
        comparable.pop('sha256')
        comparable['repository_head'] = prior['snapshot'].get('repository_head')
        if planning.seal(comparable) == prior['snapshot'] and prior.get('reference'):
            try:
                planning.validate_receipt(prior['reference'], expected_snapshot=prior['snapshot']['sha256'])
                return {'snapshot': prior['snapshot'], 'subject_file': prior['subject_file'],
                        'metadata': planning.file_descriptor(metadata_file)}
            except ValueError:
                pass  # Keep the subject's history/budget, but require a fresh receipt.
    job = _job(job_file)
    subject = planning.subject_root(job['model_selection']['project_id']) / snapshot['logical_output_id'] / 'review.json'
    record = {'schema_version': 1, 'scope_id': snapshot['logical_output_id'], 'subject_file': str(subject),
              'job_file': str(job_file), 'stage_id': stage_id, 'inputs': deepcopy(inputs),
              'snapshot': snapshot, 'reference': None}
    _atomic(metadata_file, canonical(record))
    return {'snapshot': snapshot, 'subject_file': str(subject), 'metadata': planning.file_descriptor(metadata_file)}


def validate(descriptor, rubric):
    reference = descriptor.get('planning_review')
    planning.need(isinstance(reference, dict), 'final ape report requires planning review metadata')
    planning.current_file(reference)
    meta = strict_load(_regular(Path(reference['path'])))
    planning.need(meta.get('schema_version') == 1 and meta.get('reference'), 'missing or malformed final planning receipt')
    snapshot = meta['snapshot']
    planning.unseal(snapshot)
    current = source_snapshot(descriptor, meta['inputs'], meta['job_file'], meta['stage_id'], rubric)
    current.pop('sha256')
    current['repository_head'] = snapshot.get('repository_head')
    # Source and relocated packages may use identical rubric bytes at different paths.
    planning.need({k: v for k, v in current['rubrics'][0].items() if k != 'path'} ==
                  {k: v for k, v in snapshot['rubrics'][0].items() if k != 'path'}, 'ape domain rubric changed')
    current['rubrics'] = snapshot['rubrics']
    planning.need(planning.seal(current) == snapshot, 'ape reviewed sources/request/criteria/authors changed')
    receipt = planning.validate_receipt(meta['reference'], expected_snapshot=snapshot['sha256'])
    planning.need(receipt['snapshot'] == snapshot and receipt['subject_file'] == meta['subject_file'] and
                  receipt['logical_output_id'] == meta['scope_id'], 'ape subject/receipt correlation differs')
    review_job = _job(receipt['job_file'])
    planning.need(review_job['workflow'] == 'ape/planning-review' and
                  receipt['selection_sha256'] == snapshot['ape_selection_sha256'], 'ape producing planning selection differs')
    return {'modes': [p['mode'] for p in receipt['passes']], 'rounds_used': receipt['rounds_used'],
            'round_limit': receipt['round_limit'], 'degraded_panel': receipt['degraded_panel'],
            'requested_panel': receipt['requested_panel'], 'findings': receipt['findings'],
            'subject_file': meta['subject_file'], 'reference': meta['reference'],
            'head_observation': planning.head_observation(snapshot), 'execution_authorized': False}


def attach(descriptor, metadata_file, receipt, rubric):
    path = Path(metadata_file)
    meta = strict_load(_regular(path))
    meta['reference'] = planning.file_descriptor(receipt)
    # Validate before replacing the report metadata; failed attachments leave it unchanged.
    snapshot = meta['snapshot']
    current = source_snapshot(descriptor, meta['inputs'], meta['job_file'], meta['stage_id'], rubric)
    current.pop('sha256'); current['repository_head'] = snapshot.get('repository_head')
    planning.need(planning.seal(current) == snapshot, 'ape source changed before receipt attachment')
    accepted = planning.validate_receipt(meta['reference'], expected_snapshot=snapshot['sha256'])
    planning.need(accepted['subject_file'] == meta['subject_file'] and
                  accepted['selection_sha256'] == snapshot['ape_selection_sha256'], 'ape receipt binding differs')
    review_job = _job(accepted['job_file'])
    planning.need(review_job['workflow'] == 'ape/planning-review', 'receipt is not ape planning review')
    _atomic(path, canonical(meta))
    return {'metadata': planning.file_descriptor(path), 'subject_file': meta['subject_file']}
