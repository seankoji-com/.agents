"""Hash-bound document author records transcribed from host capabilities."""
from core.jobs.store import canonical, digest, JobError


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
    from scripts.routing import lineage
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


def append_author(records, data, capabilities, source_hashes=()):
    """Record one author and propagate source authors; unknown sources stay unknown."""
    sha256 = digest(data)
    current = author_from_capabilities(capabilities)
    authors, unknown = [current], False
    for source_hash in source_hashes:
        inherited = authors_for_hash(records, source_hash)
        if any(item.get('unknown') for item in inherited):
            unknown = True
        else:
            authors.extend(inherited)
    records = dict(records or {})
    if unknown:
        records[sha256] = {'authors': [], 'unknown': True}
    else:
        records[sha256] = {'authors': sorted({canonical(item): item for item in authors}.values(), key=canonical)}
    return records


def waiver_binding(task):
    from core.jobs.store import canonical, digest
    contract_keys = ('task_id', 'stage_id', 'logical_slot_id', 'worker_id', 'target',
                     'independent_of_author', 'document', 'reviewed_documents', 'reviewed_task_ids')
    subjects = [task.get('document')] + task.get('reviewed_documents', [])
    document_sha = next((row.get('sha256') for row in subjects if isinstance(row, dict)), None)
    return {'target': task.get('target'),
            'document_authors_sha256': digest(canonical(task.get('document_authors'))),
            'contract_sha256': digest(canonical({k: task.get(k) for k in contract_keys if k in task})),
            'document_sha256': document_sha}


def has_current_task_waiver(job, task):
    from core.jobs import _owner_current
    from core.jobs.store import canonical
    expected = waiver_binding(task)
    return any(d.get('scope') == 'lineage-waiver:task:' + task['task_id'] and
               d.get('requirement_ids') == [] and d.get('binding') == expected and
               _owner_current(d, job['policy']['max_artifact_bytes']) for d in job.get('decisions', []))
