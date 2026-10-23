"""Thinking's source-plan adapter to the shared planning acceptance contract.

No chooser, dispatch or acceptance authority. Topic metadata holds references;
readiness always reopens the actual planning receipt and its producing records.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys


def helpers():
    root = next((p for p in Path(__file__).resolve().parents
                 if (p / 'shared/planning_review.py').is_file()), None)
    if root is None:
        raise ValueError('shared planning review helpers are unavailable')
    sys.path.insert(0, str(root))
    from shared import planning_review
    return planning_review


def admission(slug, selection, request_reference):
    """Seal the chosen invocation before creating a topic or recording authors."""
    p = helpers()
    from shared import model_selection as models
    output = 'thinking/' + slug + '/handoff.md'
    scope = p.logical_output_id(request_reference, output)
    selected = models.validate(selection)
    from shared.execution_agreement import admit as agreement_admit
    agreement_admit(selected, operation='elephant-goldfish/thinking')
    p.need(selected['operation'] in ('thinking', 'elephant-goldfish/thinking') or
           'elephant-goldfish/thinking' in selected.get('agreement', {}).get('operations', []), 'selection is not for thinking')
    models.gate(selected, invocation_id=selected['invocation_id'], scope_id=scope, action='draft')
    models.dispatch(selected, role='workhorse')
    return p.seal({'schema_version': 1, 'scope_id': scope, 'request_reference': request_reference,
                   'output_name': output, 'selection': selected, 'selection_sha256': selected['selection_sha256']})


def check_admission(meta, slug):
    p = helpers()
    record = p.unseal(meta.get('model_admission'))
    p.need(record == admission(slug, record['selection'], record['request_reference']),
           'thinking predraft admission changed')
    return record


def template_file(meta, template_dir=None):
    if template_dir is None:
        root = os.environ.get('T3_PLUGIN_ROOT')
        candidate = Path(root) / 'templates' if root else None
        template_dir = candidate if candidate and candidate.is_dir() else Path(__file__).resolve().parents[1] / 'templates'
    return Path(os.path.abspath(template_dir)) / ('handoff.' + meta['output_type'] + '.md')


def _authors(documents):
    from shared.document_authors import import_subject_authors
    from core.jobs.store import canonical
    authors = []
    for document in documents:
        authors.extend(import_subject_authors(document))
    return sorted({canonical(dict(a, lineage='unknown') if a.get('unknown') else a):
                   dict(a, lineage='unknown') if a.get('unknown') else a
                   for a in authors}.values(), key=canonical)


def _source_author_records(documents):
    """Bind exact source-hash authors, excluding later renderer-sidecar entries."""
    from core.jobs.store import strict_load, _regular
    from shared.document_authors import authors_for_hash, records_shape_problem
    result = []
    for document in documents:
        path = Path(document['path']).parent / 'document-authors.json'
        if path.exists():
            records = strict_load(_regular(path))
            helpers().need(not records_shape_problem(records), 'malformed source author records')
        else:
            records = {}
        result.append({'path': document['path'], 'sha256': document['sha256'],
                       'authors': authors_for_hash(records, document['sha256'])})
    return result


def source_snapshot(tdir, meta, inputs, template_dir=None):
    """Bind the request and decisions separately from the source plan and receipt."""
    p = helpers()
    tdir = Path(os.path.abspath(tdir))
    admitted = check_admission(meta, tdir.name)
    p.need(isinstance(inputs, dict) and set(inputs) <= {
        'requests', 'decisions', 'attachments', 'evidence_paths', 'declared_paths',
        'repository_root', 'requirements', 'load_bearing_decisions', 'template_dir'}, 'unsupported thinking review inputs')
    requirements = inputs['requirements']
    p.need(inputs['requests'][0]['reference'] == admitted['request_reference'], 'request differs from predraft admission')
    ids = list(dict.fromkeys(re.findall(r'\[(REQ-[A-Z0-9_-]+)\]', (tdir / 'spec.md').read_text(encoding='utf-8'))))
    p.need(ids and isinstance(requirements, dict) and set(ids) == set(requirements),
           'review requirements must match every spec requirement ID')
    attachments = inputs.get('attachments', [])
    p.need(isinstance(attachments, list), 'attachments must be a path list')
    documents = [str(tdir / 'discovery.md'), str(tdir / 'spec.md'), *attachments]
    descriptors = [p.file_descriptor(row['path'] if isinstance(row, dict) else row) for row in documents]
    snapshot = p.capture({
        'output_name': 'thinking/' + tdir.name + '/handoff.md', 'output_type': 'source-plan',
        'requirements': requirements, 'load_bearing_decisions': inputs.get('load_bearing_decisions', []),
        'requests': deepcopy(inputs['requests']), 'decisions': deepcopy(inputs['decisions']),
        'documents': documents,
        'rubrics': [str(tdir / 'spec.md'), str(Path(__file__).resolve().parents[1] / 'references/plan-review-rubric.md')],
        'templates': [str(template_file(meta, template_dir or inputs.get('template_dir')))],
        'evidence_paths': inputs['evidence_paths'],
        'declared_paths': inputs.get('declared_paths', [r['path'] if isinstance(r, dict) else r for r in inputs['evidence_paths']]),
        'repository_root': inputs['repository_root'],
        'authors': _authors(descriptors), 'source_author_records': _source_author_records(descriptors),
        'owner_review': deepcopy(meta['review']), 'thinking_inputs': deepcopy(inputs),
        'thinking_admission': admitted,
    })
    # The output and acceptance references must never be inputs to their own review.
    record = meta.get('plan_review')
    forbidden = {row['path'] for row in record.values() if isinstance(row, dict) and isinstance(row.get('path'), str)} \
        if isinstance(record, dict) else set()
    for field in ('requests', 'decisions', 'documents', 'rubrics', 'templates', 'evidence_paths'):
        for row in snapshot[field]:
            path = Path(row['path'])
            p.need(str(path) not in forbidden, 'circular snapshot/receipt input is forbidden')
            if path.parent == tdir:
                p.need(path.name not in ('meta.json', 'plan-review.snapshot.json') and
                       not path.name.startswith(('handoff', 'plan-review.receipt')),
                       'circular handoff/receipt input is forbidden')
    return snapshot


def check_source(tdir, meta, snapshot, template_dir=None):
    p = helpers()
    p.unseal(snapshot)
    p.need(snapshot.get('owner_review') == meta.get('review'), 'owner discovery decision changed since plan review')
    p.need(snapshot.get('thinking_inputs') == meta.get('plan_review_inputs'), 'declared planning inputs changed')
    current = source_snapshot(tdir, meta, meta['plan_review_inputs'], template_dir)
    # HEAD is an observation. Relevant file hashes, including dirty/untracked bytes,
    # remain dependencies; an unrelated commit cannot manufacture source drift.
    current.pop('sha256')
    current['repository_head'] = snapshot.get('repository_head')
    # A source CLI and its installed copy may consume the same receipt. Their
    # bundled asset paths differ; require the reviewed bytes at both paths.
    # check_snapshot below still dereferences the original reviewed paths.
    for field, index in (('rubrics', 1), ('templates', 0)):
        observed, reviewed = current[field][index], snapshot[field][index]
        p.need({k: v for k, v in observed.items() if k != 'path'} ==
               {k: v for k, v in reviewed.items() if k != 'path'}, 'reviewed ' + field + ' changed')
        current[field][index] = reviewed
    # Rendering adds its author to handoff's sidecar history. It does not rewrite
    # the source hashes' actual authors. Those records are compared separately.
    current['authors'] = snapshot['authors']
    p.need(p.seal(current) == snapshot, 'thinking source plan, attachment, rubric, template or evidence changed')
    p.check_snapshot(snapshot)


def state(tdir, meta, template_dir=None):
    try:
        p = helpers()
        record = meta.get('plan_review')
        p.need(isinstance(record, dict) and set(record) == {'schema_version', 'snapshot', 'reference'} and
               type(record['schema_version']) is int and record['schema_version'] == 1,
               'missing or malformed planning receipt reference')
        p.current_file(record['snapshot'])
        from core.jobs.store import strict_load, _regular
        snapshot = strict_load(_regular(Path(record['snapshot']['path'])))
        check_source(tdir, meta, snapshot, template_dir)
        receipt = p.validate_receipt(record['reference'], expected_snapshot=snapshot['sha256'])
        p.need(receipt['snapshot'] == snapshot, 'planning receipt source snapshot differs')
        job = strict_load(_regular(Path(receipt['job_file'])))
        p.need(job['workflow'] == 'elephant-goldfish/planning-review' and
               p.manifest_policy(job)['worker_id'] == 'elephant-goldfish/plan-reviewer',
               'receipt is not from the thinking planning workflow')
        return {'ready': True, 'status': 'accepted', 'reason': None,
                'snapshot_sha256': snapshot['sha256'], 'reference': record['reference'],
                'subject_file': receipt['subject_file'], 'logical_output_id': receipt['logical_output_id'],
                'modes': [row['mode'] for row in receipt['passes']],
                'rounds_used': receipt['rounds_used'], 'round_limit': receipt['round_limit'],
                'degraded_panel': receipt['degraded_panel'], 'requested_panel': receipt['requested_panel'],
                'slot_modes': receipt['slot_modes'],
                'findings': receipt['findings'], 'head_observation': p.head_observation(snapshot),
                'execution_authorized': False}
    except Exception as exc:
        # This is a fail-closed readiness view. Malformed references or a missing
        # pinned validator must be reported as a hold by list/resolve as well.
        return {'ready': False, 'status': 'review_needed', 'reason': 'plan review: ' + str(exc),
                'execution_authorized': False}


def prepare(tdir, meta, inputs, template_dir=None):
    p = helpers()
    inputs = deepcopy(inputs)
    if template_dir is not None:
        inputs['template_dir'] = os.path.abspath(template_dir)
    snapshot = source_snapshot(tdir, meta, inputs, template_dir)
    from core.jobs.store import _atomic, canonical
    target = Path(os.path.abspath(tdir)) / 'plan-review.snapshot.json'
    _atomic(target, canonical(snapshot))
    meta['plan_review_policy'] = 1
    meta['plan_review_inputs'] = deepcopy(inputs)
    meta['plan_review'] = {'schema_version': 1, 'snapshot': p.file_descriptor(target), 'reference': None}
    return snapshot


def attach(tdir, meta, receipt_path, template_dir=None):
    p = helpers()
    candidate = deepcopy(meta)
    p.need(isinstance(candidate.get('plan_review'), dict), 'prepare source snapshot before attaching a receipt')
    candidate['plan_review']['reference'] = p.file_descriptor(Path(receipt_path).absolute())
    result = state(tdir, candidate, template_dir)
    p.need(result['ready'], result['reason'])
    meta['plan_review'] = candidate['plan_review']
    return result
