"""Write reports from the same validation result used by the gate."""
from . import schema
from .fsutil import atomic_json, atomic_write_bytes, safe_dir


def build(state, validation):
    built = {'schema_version': 2, 'run_id': state['run_id'], 'phase': state['phase'],
            'brief': state['brief']['text'], 'readiness': validation, 'children': state['children'],
            'notes': state['notes'], 'remote': state['remote']}
    schema.validate(built, 'report', 'report_invalid')
    return built


def markdown(report):
    ev = report['readiness']
    lines = [f'# Run {report["run_id"]}', '', report['brief'].strip() or '(no brief)', '',
             f'Outcome: {ev["outcome"]}', '', '## Evidence', '',
             '| Requirement | Status | Explanation |', '| --- | --- | --- |']
    for row in ev['requirements']:
        explanation = (row.get('explanation') or row.get('stale_reason') or '').replace('\n', ' ').replace('|', '\\|')
        lines.append(f'| {row["id"]} | {row["status"]} | {explanation} |')
    lines += ['', 'Waived is never counted as passed.', '', '## Checks', '']
    lines += [f'- {r["name"]}: {r["status"]}' for r in ev['checks']]
    lines += ['', f'Review: {ev["review"]["status"]}', '', '## Blocked', '']
    problems = ev['missing'] + ev['failed'] + ev['stale']
    lines += [f'- {r["obligation"]}: {r.get("reason") or r.get("status")}' for r in problems]
    if not ev['remote_confirmed']:
        lines.append('- Remote: ' + ev['remote_reason'])
    lines += ['', '## Child tasks', '']
    lines += [f'- {c["task_id"]}: {c["status"]}, pending children: {c.get("has_pending_child_runs", False)}'
              for c in report['children']]
    lines += ['', '## Notes', '']
    lines += ['- ' + n['text'] for n in report['notes']]
    return '\n'.join(lines) + '\n'


def write(run_dir, built):
    directory = safe_dir(run_dir, 'reports')
    atomic_json(directory / 'report.json', built)
    atomic_write_bytes(directory / 'report.md', markdown(built).encode())
    return {'json': str(directory / 'report.json'), 'markdown': str(directory / 'report.md')}
