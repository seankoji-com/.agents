"""Bind a tests-omg job to the exact report and an independent reviewer subject."""
from pathlib import Path
import sys

from core.jobs.store import JobError, _regular, canonical, digest, strict_load


def report_binding(job, stage, descriptor, package):
    root = Path(descriptor['state_root'])
    run_id = descriptor['run_id']
    import re
    if not root.is_absolute() or not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise JobError('absolute audit state and safe run identity required')
    folder = root / 'runs' / run_id
    report = folder / 'audit.json'
    inputs = {str(folder / name): digest(_regular(folder / name))
              for name in ('audit.json', 'input.json', 'report.html', 'manifest.json')}
    index = strict_load(_regular(root / 'index.json'))
    rows = [r for r in index['runs'] if r['run_id'] == run_id]
    if len(rows) != 1 or rows[0].get('superseded_by'):
        raise JobError('audit index identity missing, duplicated or superseded')
    inputs['audit-index-entry'] = digest(canonical(rows[0]))
    if inputs[str(report)] != descriptor['audit_sha256'] or inputs[str(folder / 'input.json')] != descriptor['input_sha256']:
        raise JobError('audit report bytes differ from the declared subject')
    subject = {'path': str(report), 'sha256': descriptor['audit_sha256']}
    ancestors, pending = {stage['id']}, list(stage.get('depends_on', []))
    by_id = {s['id']: s for s in job['stages']}
    while pending:
        sid = pending.pop()
        if sid in ancestors:
            continue
        ancestors.add(sid)
        pending.extend(by_id[sid].get('depends_on', []))
    reviewers = [t for t in job['tasks'] if t['stage_id'] in ancestors and
                 t.get('role') == 'review' and t.get('independent_of_author') is True and
                 subject in t.get('reviewed_documents', [])]
    if not reviewers:
        raise JobError('audit requires an independent review of the exact saved audit.json')
    saved = strict_load(_regular(report))
    source = strict_load(_regular(folder / 'manifest.json')).get('source_locator')
    if not source:
        raise JobError('audit source locator missing')
    # Use the pinned audit's bounded, fsmonitor-disabled Git inventory, never the
    # target's commands/configuration or the core's different snapshot policy.
    # Reuse acceptance's bounded runner: both streams are capped, timeout cleanup
    # kills the owned process group, and failures are normalized before accept.
    from shared.job_acceptance import AcceptanceError, _bounded_run
    try:
        proc = _bounded_run([sys.executable, str(package / 'scripts/audit.py'),
                             'audit', source, '--snapshot'], package,
                            {'timeout_seconds': 30, 'max_output_bytes': 1024 * 1024})
    except (AcceptanceError, OSError) as exc:
        raise AcceptanceError('audit source binding unavailable') from exc
    if proc.returncode:
        raise JobError('audit source binding unavailable')
    current = strict_load(proc.stdout)
    if (current.get('limitations') or current.get('sha256') != descriptor['snapshot_sha256'] or
            current.get('head_sha') != descriptor['head_sha']):
        raise JobError('audit source is stale or incomplete')
    inputs['source-binding'] = digest(canonical(current))
    if saved['snapshot']['sha256'] != descriptor['snapshot_sha256'] or saved['snapshot']['head_sha'] != descriptor['head_sha']:
        raise JobError('audit source identity differs from descriptor')
    return inputs
