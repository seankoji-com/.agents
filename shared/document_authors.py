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


def append_author(records, data, capabilities, source_hashes=()):
    """Record one author and propagate source authors; unknown sources stay unknown."""
    sha256 = digest(data)
    current = author_from_capabilities(capabilities)
    authors, unknown = [current], False
    previous = authors_for_hash(records, sha256) if isinstance(records, dict) and sha256 in records else []
    if any(item.get('unknown') for item in previous):
        # A hash already marked unknown stays unknown even if a later coordinator
        # records the same bytes; provenance cannot be reconstructed after the fact.
        unknown = True
    else:
        authors.extend(previous)
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


def waiver_binding(task):
    from core.jobs.store import canonical, digest
    contract_keys = ('task_id', 'stage_id', 'logical_slot_id', 'worker_id', 'target',
                     'independent_of_author', 'document', 'reviewed_documents', 'reviewed_task_ids',
                     'requirements', 'role', 'context_policy', 'write_scope', 'max_followups')
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
