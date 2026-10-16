"""Hash-bound document author records transcribed from host capabilities."""
import contextlib
from core.jobs.store import canonical, digest, JobError, trusted_link


@contextlib.contextmanager
def locked_author_records(directory):
    """Yield (records, save) for one directory's sidecar under an exclusive lock.

    The lock is a flock on the directory itself, so concurrent recorders never
    lose each other's records and no lock file is left beside the documents.
    ``save`` writes a uniquely named, fsynced temporary file and replaces the sidecar.
    """
    import fcntl
    import json
    import os
    import tempfile
    from pathlib import Path
    directory = Path(directory)
    sidecar = directory / 'document-authors.json'
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if sidecar.is_symlink():
            raise JobError('document author records may not be a symlink')
        try:
            records = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.exists() else {}
        except ValueError as exc:
            raise JobError('document author records are not valid JSON') from exc
        problem = records_shape_problem(records)
        if problem:
            raise JobError('document author records ' + problem)

        def save(updated):
            handle, temporary = tempfile.mkstemp(prefix='.' + sidecar.name + '.', dir=directory)
            try:
                with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                    stream.write(json.dumps(updated, indent=2, sort_keys=True) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, sidecar)
                os.fsync(fd)  # make the rename itself durable
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

        yield records, save
    finally:
        os.close(fd)


def records_shape_problem(records):
    """Describe why a parsed sidecar has the wrong shape, or return None."""
    if not isinstance(records, dict):
        return 'must be an object'
    paths = records.get('_document_paths', {})
    if not isinstance(paths, dict) or not all(isinstance(v, (dict, str)) for v in paths.values()):
        return 'have an invalid path index'
    def is_order(value):  # bool is an int subclass; true/false are not record orders
        return isinstance(value, int) and not isinstance(value, bool)
    if not is_order(records.get('_record_order', 0)):
        return 'have an invalid record order'
    entries = [v for k, v in records.items() if k not in ('_document_paths', '_record_order')]
    if not all(isinstance(v, dict) for v in entries):
        return 'have a non-object hash record'
    if not all(is_order(v['order']) for v in entries if 'order' in v):
        return 'have an invalid record order'
    return None


def import_subject_authors(subject):
    """Import authors only when the current bytes match the declared document hash."""
    import json
    from pathlib import Path
    if not isinstance(subject, dict) or not isinstance(subject.get('path'), str):
        return [{'unknown': True}]
    path = Path(subject['path'])
    try:
        if (not path.is_absolute() or '..' in path.parts or
                any(part.is_symlink() and not trusted_link(part) for part in (path, *path.parents))):
            return [{'unknown': True}]
        if digest(path.read_bytes()) != subject.get('sha256'):
            return [{'unknown': True}]
        sidecar = path.parent / 'document-authors.json'
        if sidecar.is_symlink() or not sidecar.is_file():
            return [{'unknown': True}]
        records = json.loads(sidecar.read_text(encoding='utf-8'))
        if records_shape_problem(records):
            return [{'unknown': True}]
        authors = authors_for_hash(records, subject['sha256'])
        # A document can be edited at a temporary path and then moved into place.
        # Keep authors of the last hash recorded for the validated destination too.
        paths = records.get('_document_paths', {}) if isinstance(records, dict) else {}
        pointer = paths.get(str(path.resolve()))
        previous_hash = pointer.get('sha256') if isinstance(pointer, dict) else pointer
        last_order = pointer.get('order', 0) if isinstance(pointer, dict) else 0
        # Records written anywhere in this sidecar after the destination was
        # last recorded may describe a copied or moved version of its content.
        # Include them regardless of whether their original path still exists.
        later = [entry for key, entry in records.items()
                 if key not in ('_document_paths', '_record_order') and isinstance(entry, dict)
                 and isinstance(entry.get('order'), int) and entry['order'] > last_order]
        if later:
            inherited = merge_author_records(*({'authors': entry.get('authors', []),
                                                'unknown': entry.get('unknown') is True}
                                               for entry in later))
            if inherited.get('unknown'):
                return [{'unknown': True}]
            authors = merge_author_records({'authors': authors}, inherited)['authors']
        if previous_hash and previous_hash != subject['sha256']:
            previous = authors_for_hash(records, previous_hash)
            if any(row.get('unknown') for row in previous):
                return [{'unknown': True}]
            if not any(row.get('unknown') for row in authors):
                authors = merge_author_records({'authors': authors}, {'authors': previous})['authors']
        return authors
    except (OSError, TypeError, ValueError):
        return [{'unknown': True}]


def refresh_new_task_authors(job, plan):
    """Re-import hash-matched authors for every slot and validated stage document."""
    plan.setdefault('stages', job.get('stages', []))
    plan.setdefault('tasks', job.get('tasks', []))
    workflow = str(job.get('workflow', ''))
    existing_tasks = {row.get('task_id'): row for row in job.get('tasks', [])}
    for task in plan.get('tasks', []):
        stage = next((row for row in plan['stages'] if row['id'] == task.get('stage_id')), {})
        contract = stage.get('validator_contract') or {}
        authoring = workflow.endswith(('/thinking', '/elephant'))
        checking = workflow.endswith('/check')
        should_import = bool(task.get('independent_of_author') or authoring or checking)
        if not should_import:
            continue
        validated_path = contract.get('document_path')
        validated = ({'path': validated_path, 'sha256': contract.get('document_sha256')}
                     if validated_path and contract.get('document_sha256') else None)
        if validated and not task.get('document'):
            task['document'] = dict(validated)
        if (task.get('document') and validated_path and
                (not isinstance(task['document'], dict) or task['document'].get('path') != validated_path or
                 task['document'].get('sha256') != contract.get('document_sha256'))):
            raise JobError('author-independent slot document must match the stage validated document')
        retained_authors = existing_tasks.get(task.get('task_id'), {}).get('document_authors')
        subjects = [validated]
        subjects.extend(subject for subject in [task.get('document'), *(task.get('reviewed_documents') or [])]
                        if subject and subject != validated)
        imported = [import_subject_authors(row) for row in subjects if row]
        if imported:
            merged = merge_author_records(*({'authors': rows, 'unknown': any(a.get('unknown') for a in rows)}
                                            for rows in imported))
            authors = [{'unknown': True}] if merged.get('unknown') else merged['authors']
        else:
            authors = [{'unknown': True}]
        retained = merge_author_records({'authors': retained_authors or [],
                                         'unknown': retained_authors is not None and
                                         (not isinstance(retained_authors, list) or
                                          any(not isinstance(row, dict) or row.get('unknown') for row in retained_authors))})
        imported_record = {'authors': authors,
                           'unknown': not isinstance(authors, list) or
                           any(not isinstance(row, dict) or row.get('unknown') for row in authors)}
        merged_authors = merge_author_records(retained, imported_record)
        task['document_authors'] = [{'unknown': True}] if merged_authors.get('unknown') else merged_authors['authors']
        if checking:
            validated_authors = import_subject_authors(validated) if validated else [{'unknown': True}]
            if validated_authors and not any(row.get('unknown') for row in validated_authors):
                task['independent_of_author'] = True
            else:
                task.pop('independent_of_author', None)
        elif authoring and task.get('role') in ('factual', 'cold-read'):
            task['independent_of_author'] = True

    if workflow.startswith('elephant-goldfish/'):
        for stage in plan.get('stages', []):
            contract = stage.get('validator_contract') or {}
            subject = ({'path': contract['document_path'], 'sha256': contract['document_sha256']}
                       if contract.get('document_path') and contract.get('document_sha256') else None)
            if subject and (workflow.endswith(('/thinking', '/elephant')) or workflow.endswith('/check')):
                stage['document_authors'] = import_subject_authors(subject)


def author_from_capabilities(capabilities):
    if not isinstance(capabilities, dict):
        raise JobError('fresh orchestrator_capabilities response is required')
    provider = capabilities.get('inheritedProviderInstanceId')
    model = capabilities.get('inheritedModel')
    parent = capabilities.get('parentThreadId')
    if not all(isinstance(value, str) and value for value in (provider, model, parent)):
        raise JobError('capabilities are missing inherited provider, model or parentThreadId')
    row = next((p for p in capabilities.get('providers', [])
                if isinstance(p, dict) and p.get('providerInstanceId') == provider), None)
    models = row.get('models', []) if row else []
    if not any(isinstance(item, dict) and item.get('id') == model for item in models):
        raise JobError('inherited model is absent from its provider catalog')
    from shared.lineage import lineage
    label = lineage(row.get('driverKind', ''), model)
    from shared.job_acceptance import canonical_lineage
    canonical_lineage(label)
    return {'providerInstanceId': provider, 'model': model, 'parentThreadId': parent,
            'lineage': label}


def authors_for_hash(records, sha256):
    """Return a canonical author union, or an unknown sentinel for missing provenance."""
    if not isinstance(records, dict) or sha256 not in records:
        return [{'unknown': True}]
    entry = records[sha256]
    authors = entry.get('authors') if isinstance(entry, dict) else None
    if not isinstance(authors, list) or entry.get('unknown'):
        return [{'unknown': True}]
    return sorted({canonical(author): author for author in authors}.values(), key=canonical)


def append_author(records, data, capabilities, source_hashes=(), document_path=None):
    """Record one author and propagate source authors; unknown sources stay unknown."""
    problem = records_shape_problem(records)
    if problem:
        raise JobError('document author records ' + problem)
    sha256 = digest(data)
    current = author_from_capabilities(capabilities)
    authors, unknown = [current], False
    paths = records.get('_document_paths', {}) if isinstance(records, dict) else {}
    path_key = str(document_path.resolve()) if document_path is not None else None
    pointer = paths.get(path_key) if path_key else None
    previous_hash = pointer.get('sha256') if isinstance(pointer, dict) else pointer
    last_order = pointer.get('order', 0) if isinstance(pointer, dict) else 0
    if path_key and previous_hash is None:
        matching = [key for key, value in records.items()
                    if key != '_document_paths' and isinstance(value, dict) and value.get('document_path') == path_key]
        legacy = [key for key, value in records.items()
                  if key != '_document_paths' and isinstance(value, dict) and not value.get('document_path')]
        if matching:
            previous_hash = matching[-1]
        elif len(legacy) == 1:
            previous_hash = legacy[0]
        elif len(legacy) > 1:
            raise JobError('cannot establish the previous author record for this document path')
    # A moved recorded copy may be the bytes now at this path while the path
    # pointer still names its older hash. Preserve both provenance records.
    prior_hashes = [key for key in (previous_hash, sha256)
                    if key and isinstance(records, dict) and key in records]
    if path_key:
        # Sidecar order records content history, not filesystem state. Any
        # record made since this path was last recorded may be a copied or
        # moved version and therefore contributes its authors.
        for key, entry in records.items():
            if (key not in ('_document_paths', '_record_order') and isinstance(entry, dict)
                    and isinstance(entry.get('order'), int) and entry['order'] > last_order):
                prior_hashes.append(key)
    previous_records = [authors_for_hash(records, key) for key in dict.fromkeys(prior_hashes)]
    if any(any(item.get('unknown') for item in rows) for rows in previous_records):
        # A hash already marked unknown stays unknown even if a later coordinator
        # records the same bytes; provenance cannot be reconstructed after the fact.
        unknown = True
    else:
        for rows in previous_records:
            authors.extend(rows)
    for source_hash in source_hashes:
        inherited = authors_for_hash(records, source_hash)
        if any(item.get('unknown') for item in inherited):
            unknown = True
        else:
            authors.extend(inherited)
    records = dict(records or {})
    order = max([records.get('_record_order', 0)] + [entry.get('order', 0) for key, entry in records.items()
                if key not in ('_document_paths', '_record_order') and isinstance(entry, dict)
                and isinstance(entry.get('order', 0), int)]) + 1 if path_key else None
    if unknown:
        records[sha256] = {'authors': [], 'unknown': True}
    else:
        records[sha256] = {'authors': sorted({canonical(item): item for item in authors}.values(), key=canonical)}
    if path_key:
        records[sha256]['order'] = order
        records[sha256]['document_path'] = path_key
    if path_key:
        paths = dict(paths)
        paths[path_key] = {'sha256': sha256, 'order': order}
        records['_document_paths'] = paths
        records['_record_order'] = order
    return records


def merge_author_records(*records):
    """Union author records without allowing a known hash to lose authors."""
    from core.jobs.store import canonical
    rows, unknown = [], False
    for record in records:
        if not isinstance(record, dict) or record.get('unknown'):
            unknown = True
        else:
            rows.extend(record.get('authors', []))
    if unknown:
        return {'authors': [], 'unknown': True}
    return {'authors': sorted({canonical(row): row for row in rows}.values(), key=canonical)}


def waiver_binding(task, reviewer=None):
    from core.jobs.store import canonical, digest
    contract_keys = ('task_id', 'stage_id', 'logical_slot_id', 'worker_id', 'dependency_key', 'target',
                     'independent_of_author', 'document', 'reviewed_documents', 'reviewed_task_ids',
                     'requirements', 'role', 'context_policy', 'write_scope', 'max_followups',
                     'review_required', 'review_task_ids')
    subjects = [task.get('document')] + task.get('reviewed_documents', [])
    document_sha = next((row.get('sha256') for row in subjects if isinstance(row, dict)), None)
    result = {'target': task.get('target'),
            'document_authors_sha256': digest(canonical(task.get('document_authors'))),
            'contract_sha256': digest(canonical({k: task.get(k) for k in contract_keys if k in task})),
            'document_sha256': document_sha}
    if reviewer is not None:
        result['reviewer_target'] = reviewer.get('target')
    return result


def has_current_task_waiver(job, task, reviewer=None):
    from core.jobs import _owner_current
    from core.jobs.store import canonical
    expected = waiver_binding(task, reviewer)
    return any(d.get('scope') == 'lineage-waiver:task:' + task['task_id'] and
               d.get('requirement_ids') == [] and d.get('binding') == expected and
               _owner_current(d, job['policy']['max_artifact_bytes']) for d in job.get('decisions', []))


def stage_waiver_binding(stage, authors, document_sha256, executor):
    contract = {key: value for key, value in stage.items() if key not in
                ('status', 'attempts', 'acceptance', 'acceptance_history', 'acceptance_runs', 'validated_cycle', 'cycle', 'direct_execution_history')}
    return {'target': executor, 'document_authors_sha256': digest(canonical(authors)),
            'contract_sha256': digest(canonical(contract)), 'document_sha256': document_sha256}


def has_current_stage_waiver(job, stage):
    executor = (stage.get('direct_execution_history') or [{}])[-1].get('identity')
    if not executor:
        return False
    authors = stage.get('document_authors', [{'unknown': True}])
    document_sha = (stage.get('validator_contract') or {}).get('document_sha256')
    expected = stage_waiver_binding(stage, authors, document_sha, executor)
    from core.jobs import _owner_current
    return any(d.get('scope') == 'lineage-waiver:stage:' + stage['id'] and
               d.get('requirement_ids') == [] and d.get('binding') == expected and
               _owner_current(d, job['policy']['max_artifact_bytes']) for d in job.get('decisions', []))
