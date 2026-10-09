"""JSON result and Markdown handoff, produced only from validated state."""
from __future__ import annotations

import shlex
from pathlib import Path

from . import acceptance, engine, schema
from .fsutil import atomic_json, atomic_write_bytes
from .resources import live as resource_live

OUTCOME = {'completed': 'completed', 'blocked': 'blocked', 'cancelled': 'cancelled', 'failed': 'failed'}


def build(ctx, state: dict) -> dict:
    ev = acceptance.evaluate(state, ctx.state_root, ctx.run_dir)
    upcoming = engine.next_actions(ctx, state)
    resources = []
    for item in state.get('resources', []):
        live = item.get('status') == 'live' and resource_live(item)
        argv = list(item['cleanup_argv'])
        note = None
        if live and item['kind'] == 'branch' and state['phase'] != 'completed':
            # A preserved branch may hold unmerged work; removing it is a deliberate discard.
            argv = [('-D' if arg == '-d' else arg) for arg in argv]
            note = 'discards any unmerged commits on this branch'
        resources.append({'id': item['id'], 'kind': item['kind'], 'status': 'live' if live else item.get('status'),
                          'path': item.get('path'), 'branch': item.get('branch'), 'pid': item.get('pid'),
                          'cleanup_command': shlex.join(argv) if live else None, 'note': note})
    tasks = []
    for task in state.get('tasks', []):
        tasks.append({'id': task['id'], 'kind': task.get('kind'), 'status': task['status'],
                      'executor': task.get('executor'), 'target': task.get('target'),
                      'worktree': task.get('worktree'),
                      'result_artifact': (task.get('result') or {}).get('artifact'),
                      'rounds': [{'round': r.get('round'), 'purpose': r.get('purpose'),
                                  'client_request_id': r.get('client_request_id'), 'host_task_id': r.get('task_id'),
                                  'last_status': r.get('last_status'), 'last_work_state': r.get('last_work_state'),
                                  'cancel': r.get('cancel'), 'dispatch_error': r.get('dispatch_error')}
                                 for r in task.get('rounds') or []]})
    reviews = [{'round': r['round'], 'verdict': r['verdict'], 'selection': r.get('selection'), 'why': r.get('why'),
                'host_task_id': r.get('host_task_id'), 'client_request_id': r.get('client_request_id'),
                'findings': r.get('findings', []), 'invalidated': r.get('invalidated'),
                'artifact': r.get('artifact')} for r in state.get('reviews', [])]
    active = upcoming.get('blocked')
    outcome = OUTCOME.get(state['phase'], 'blocked' if active else 'in_progress')
    if outcome == 'completed' and not ev['ready']:
        # Completed at an earlier revision; the current tree is not what was verified.
        outcome = 'stale'
    report = {
        'schema_version': 1, 'run_id': state['run_id'], 'generation': state['generation'],
        'generated_at': ctx.at, 'phase': state['phase'], 'outcome': outcome,
        'plugin': state['plugin'], 'labels': state.get('labels', {}),
        'repo': dict(state['repo'], head=ev['binding']['snapshot']['head'],
                     content_hash=ev['binding']['snapshot']['content_hash']),
        'brief': state['brief']['text'],
        'readiness': {'status': ev['status'], 'ready': ev['ready'], 'counts': ev['counts'],
                      'missing': ev['missing'], 'failed': ev['failed'], 'stale': ev['stale']},
        'requirements': ev['requirements'], 'checks': ev['checks'], 'review': ev['review'], 'reviews': reviews,
        'tasks': tasks, 'execution': state['execution'], 'probes': state.get('probes', {}),
        'blocker': active, 'resources': resources,
        'remote': state.get('remote'), 'budget': state['budget'], 'counters': state.get('counters'),
        'cancellation': state.get('cancellation'), 'notes': state.get('notes', {}),
        'completed_binding': (state.get('readiness') or {}).get('binding') if state['phase'] == 'completed' else None,
        'next_actions': [a['action'] for a in upcoming['actions']],
        'evidence_dir': str(ctx.run_dir / 'artifacts'),
    }
    schema.validate(report, 'report', 'report_invalid')
    return report


def markdown(report: dict) -> str:
    lines = [f'# Run {report["run_id"]}: {report["outcome"]}', '']
    if report['outcome'] == 'stale':
        done = (report.get('completed_binding') or {}).get('snapshot') or {}
        lines += [f'Completed at `{(done.get("head") or "")[:12]}`, but the working tree has changed since; '
                  'that completion does not cover the current tree. Start a new run to verify it.', '']
    lines += [
             f'Phase `{report["phase"]}` at generation {report["generation"]}. Readiness: '
             f'`{report["readiness"]["status"]}`. Repository `{report["repo"]["worktree"]}` '
             f'on `{report["repo"].get("branch")}` at `{(report["repo"].get("head") or "")[:12]}`.', '']
    if report['brief']:
        lines += ['**Brief:** ' + report['brief'].strip().splitlines()[0][:300], '']
    blocker = report.get('blocker')
    if blocker:
        lines += ['## Blocked', '', f'- Reason: {blocker["reason"]}',
                  f'- Code: `{blocker["code"]}`; tasks: {", ".join(blocker["task_ids"]) or "none"}',
                  f'- Resume: `{shlex.join(blocker["resume"]["argv"])}`']
        if blocker['resume'].get('then'):
            lines.append(f'- Then paste into the same T3 thread: `{blocker["resume"]["then"]}`')
        lines.append('')
    notes = report.get('notes') or {}
    if notes:
        lines += ['## Notes', ''] + [f'- **{key}:** {value}' for key, value in notes.items()] + ['']
    lines += ['## Requirements', '', '| ID | Kind | Status | Explanation |', '| --- | --- | --- | --- |']
    for row in report['requirements']:
        explanation = (row.get('explanation') or row.get('stale_reason') or '').replace('|', '/').replace('\n', ' ')
        lines.append(f'| {row["id"]} | {row["kind"]} | {row["status"]} | {explanation[:160]} |')
    counts = report['readiness']['counts']
    lines += ['', 'Counts: ' + ', '.join(f'{k} {v}' for k, v in counts.items()) + '. Waived is never counted as passed.', '']
    if report['checks']:
        lines += ['## Checks', ''] + [f'- `{shlex.join(row["argv"])}`: {row["status"]}' for row in report['checks']] + ['']
    review = report['review']
    lines += ['## Review', '', f'- Required: {review["required"]}; status: {review["status"]}']
    for row in report['reviews']:
        target = row.get('selection') or {}
        lines.append(f'- Round {row["round"]}: {row["verdict"]} by {target.get("providerInstanceId")}/'
                     f'{target.get("model")} (task {row.get("host_task_id")}, request {row.get("client_request_id")}). '
                     f'Why: {row.get("why")}' + (f' [invalidated: {row["invalidated"]}]' if row.get('invalidated') else ''))
    lines.append('')
    delegated = [t for t in report['tasks'] if t['rounds'] and any(r['host_task_id'] for r in t['rounds'])]
    if delegated:
        lines += ['## Delegated tasks', '']
        for task in delegated:
            for item in task['rounds']:
                if item['host_task_id']:
                    lines.append(f'- {task["id"]} round {item["round"]} ({item["purpose"]}): T3 task `{item["host_task_id"]}`, '
                                 f'request `{item["client_request_id"]}`, last status {item["last_status"]}')
        lines.append('')
    live = [row for row in report['resources'] if row['status'] == 'live']
    if live:
        lines += ['## Preserved resources', '', 'Each line is the exact cleanup command for one run-owned resource.', '']
        lines += [f'- {row["kind"]} {row.get("path") or row.get("branch") or row.get("pid")}: `{row["cleanup_command"]}`'
                  + (f' ({row["note"]})' if row.get('note') else '') for row in live]
        lines.append('')
    elif report['resources']:
        lines += ['## Resources', '', 'All run-owned worktrees, branches and processes were removed.', '']
    lines += ['## Evidence', '', f'Artifacts: `{report["evidence_dir"]}` (never removed by cleanup).', '']
    return '\n'.join(lines)


def write(ctx, report: dict) -> dict:
    directory = Path(ctx.run_dir) / 'reports'
    text = markdown(report)
    atomic_json(directory / 'report.json', report)
    atomic_write_bytes(directory / 'report.md', text.encode())
    return {'json': str(directory / 'report.json'), 'markdown': str(directory / 'report.md')}
