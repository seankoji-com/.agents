#!/usr/bin/env python3
"""Map a coordinator-captured T3 snapshot to the frozen bench-v2 grader contexts.

The snapshot is host_observations.read_snapshot output: T3's own record of the parent's
delegate_task and task_status calls, exported from the coordinator-only store. From it
this module builds

- the workflow/negative `--context` record, in the shape of
  bench/v2/fixtures/workflows/coordinator-contexts/*.json plus the fresh run identity, and
  the matching captured-transport ledger (tools/captured_ledger.py), and
- the five-stage `--review-context` transport record for C13.

Dispatch existence, host task IDs, inputs and child threads come from the T3 store.
Worker identity and follow-up links come from the rebuilt job state (`tasks[].worker_id`,
`request_id`, `followup_of`), joined on the `clientRequestId` T3 recorded. That job state is
written by the parent, which shares the worker UID, so it names workers but proves nothing
by itself: an event without a matching host dispatch is never emitted. Routes this module
cannot trace (source reads, stage transitions, sidecar calls, settings parse/load) are
absent from trace_coverage unless a coordinator-owned `extra` record supplies them, so the
graders fail closed instead of reading absence as evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / 'bench' / 'v2'
sys.path.insert(0, str(V2 / 'tools'))
sys.path.insert(0, str(V2 / 'checks'))
import captured_ledger  # noqa: E402
import negative_start  # noqa: E402
import workflow_contract  # noqa: E402

CONTRACTS = V2 / 'fixtures' / 'workflows' / 'contracts.json'
DELEGATE, STATUS = 't3-code.delegate_task', 't3-code.task_status'
# Operation labels the frozen graders and coordinator-context seeds use per specialised worker.
WORKER_OPERATIONS = {
    'ape/source-researcher': 'source_research', 'ape/synthesizer': 'synthesis',
    'elephant-goldfish/factual-checker': 'factual_check', 'elephant-goldfish/cold-reader': 'cold_read',
    'babysitter/pr-maintainer': 'pr_maintenance', 'babysitter/pr-reviewer': 'pr_review',
    'agent-tuneup/config-researcher': 'config_research', 'agent-tuneup/config-verifier': 'config_verification',
    'imps/investigator': 'investigation', 'imps/stage-executor': 'stage_execution',
    'imps/auditor': 'audit', 'imps/reviewer': 'review'}
FOLLOWUP_OPERATIONS = {'ape/source-researcher': 'research_followup'}
# The cold-reader contamination check reads the dispatched brief; nothing else keeps input text.
RETAINED_INPUT = {'cold_read'}
TRACED = ['dispatch_calls', 'task_handles']


def contract(scenario: str) -> dict:
    document = json.loads(CONTRACTS.read_text(encoding='utf-8'))
    group = 'negative_scenarios' if scenario.startswith('negative-') else 'scenarios'
    if scenario not in document[group]:
        raise ValueError(f'unknown frozen scenario: {scenario}')
    return document[group][scenario]


def _delegations(captured: dict) -> list:
    return [row for row in captured.get('tool_records', [])
            if isinstance(row, dict) and row.get('toolName') == DELEGATE
            and isinstance(row.get('input'), dict) and isinstance(row.get('output'), dict)
            and isinstance(row['output'].get('taskId'), str) and row['output']['taskId']]


def _job_tasks(job_states) -> dict:
    by_request = {}
    for job in job_states or ():
        rows = list(job.get('tasks', [])) + [t for h in job.get('history', []) for t in h.get('tasks', [])]
        for task in rows:
            if isinstance(task, dict) and isinstance(task.get('request_id'), str):
                by_request.setdefault(task['request_id'], task)
    return by_request


def dispatch_calls(captured: dict, job_states=()) -> list:
    """One event per host-recorded delegate_task, in host order."""
    tasks = _job_tasks(job_states)
    records = _delegations(captured)
    host_task = {row['input'].get('clientRequestId'): row['output']['taskId'] for row in records
                 if isinstance(row['input'].get('clientRequestId'), str)}
    child_thread = {row['output']['taskId']: row['output'].get('childThreadId') for row in records}
    for row in captured.get('subagents', []):
        if isinstance(row, dict) and isinstance(row.get('id'), str) and isinstance(row.get('childThreadId'), str):
            child_thread.setdefault(row['id'], row['childThreadId'])
            child_thread[row['id']] = child_thread[row['id']] or row['childThreadId']
    events = []
    for row in records:
        given, task_id = row['input'], row['output']['taskId']
        job_task = tasks.get(given.get('clientRequestId'), {})
        worker = job_task.get('worker_id') if isinstance(job_task.get('worker_id'), str) else None
        prior_request = job_task.get('followup_of')
        continued = given.get('childThreadId')
        if prior_request is not None or continued:
            prior = host_task.get(prior_request) if isinstance(prior_request, str) else None
            if prior is None and isinstance(continued, str):
                prior = next((task for task, thread in child_thread.items()
                              if thread == continued and task != task_id), None)
            event = {'operation': FOLLOWUP_OPERATIONS.get(worker, 'followup'), 'task_id': task_id,
                     'prior_task_id': prior,
                     'conversation_id': continued if isinstance(continued, str) else child_thread.get(prior)}
        else:
            operation = job_task.get('operation') if isinstance(job_task.get('operation'), str) else None
            event = {'operation': operation or WORKER_OPERATIONS.get(worker, 'dispatch'), 'task_id': task_id}
            if worker:
                event['worker'] = worker
        if event['operation'] in RETAINED_INPUT and isinstance(given.get('task'), str):
            event['input'] = {'task': given['task']}
        events.append(event)
    return events


def host_observations(captured: dict, job_states=(), extra: dict | None = None) -> dict:
    records = _delegations(captured)
    host = {'trace_coverage': list(TRACED), 'dispatch_calls': dispatch_calls(captured, job_states),
            'observed_handles': [row['output']['taskId'] for row in records],
            'reviewer_handles': [row['output']['taskId'] for row in records if row['input'].get('role') == 'review']}
    jobs = [job for job in job_states or () if isinstance(job, dict)]
    if len(jobs) == 1 and isinstance(jobs[0].get('job_id'), str):
        host['job_id'] = jobs[0]['job_id']
        codes = {row.get('code') for row in jobs[0].get('blockers', []) if isinstance(row, dict)}
        if 'required_review_unavailable' in codes:
            host['required_review_status'] = 'unavailable'
    for key, value in (extra or {}).items():
        if key == 'trace_coverage':
            host['trace_coverage'] = sorted(set(host['trace_coverage']) | set(value))
        elif key in ('dispatch_calls', 'observed_handles', 'reviewer_handles'):
            raise ValueError(f'extra host observations may not replace the captured {key}')
        else:
            host[key] = value
    return host


def observed_ids(scenario: str, host: dict) -> tuple[dict, list]:
    spec = contract(scenario)
    reader = negative_start._host_observed_id if scenario.startswith('negative-') else workflow_contract._host_observed_id
    ids, missing = {}, []
    for key in spec['required_observed_ids']:
        value = reader(scenario, host, key)
        if isinstance(value, str) and value:
            ids[key] = value
        else:
            missing.append(key)
    return ids, missing


def build_context(scenario: str, outcome: Path, captured: dict, prelaunch: dict,
                  job_states=(), extra: dict | None = None) -> tuple[dict, list]:
    """Return (context, gaps). Gaps name missing outputs or identities; the grader fails them."""
    spec = contract(scenario)
    if prelaunch.get('scenario') != scenario or prelaunch.get('kind') != 'prelaunch':
        raise ValueError('prelaunch ledger does not belong to this scenario')
    run_id, nonce = prelaunch['run_id'], prelaunch['prelaunch_nonce']
    host = host_observations(captured, job_states, extra)
    ids, missing = observed_ids(scenario, host)
    outcome = Path(outcome)
    artifacts, gaps = {}, [f'observed id unavailable: {key}' for key in missing]
    for name in spec['required_outputs']:
        path = outcome / name
        if path.is_file() and not path.is_symlink():
            artifacts[name] = {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                               'run_id': run_id}
        else:
            gaps.append(f'required output missing: {name}')
    context = {'schema_version': 1, 'scenario': scenario, 'run_id': run_id, 'prelaunch_nonce': nonce,
               'launch': {'scenario': scenario, 'run_id': run_id, 'prelaunch_nonce': nonce,
                          'input_sha256': prelaunch.get('input_sha256')},
               'observed_ids': ids, 'artifacts': artifacts, 'host_observations': host}
    return context, gaps


def write_context_and_capture(context: dict, prelaunch_path: Path, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    context_path = directory / 'context.json'
    context_path.write_text(json.dumps(context, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    capture_path = directory / 'capture.json'
    captured_ledger.create_capture(prelaunch_path, context_path, capture_path)
    for path in (context_path, capture_path):
        path.chmod(0o600)
    return context_path, capture_path


def review_context(captured: dict, catalog: dict, parent_target: dict) -> dict | None:
    """The host transport of the last review dispatch, as five_stage.independent_review_matches reads it."""
    reviews = [row for row in _delegations(captured) if row['input'].get('role') == 'review']
    if not reviews:
        return None
    task_id = reviews[-1]['output']['taskId']
    records = [row for row in captured.get('tool_records', []) if isinstance(row, dict) and (
        (row.get('toolName') == DELEGATE and isinstance(row.get('output'), dict) and row['output'].get('taskId') == task_id)
        or (row.get('toolName') == STATUS and isinstance(row.get('input'), dict) and row['input'].get('taskId') == task_id))]
    return {'parent_thread_id': captured.get('parent_thread_id'), 'task_id': task_id,
            'target': reviews[-1]['input'].get('target'), 'parent_target': parent_target,
            'catalog': catalog, 'tool_records': records}


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    ctx = sub.add_parser('context', help='workflow/negative --context plus capture ledger')
    ctx.add_argument('scenario')
    ctx.add_argument('--snapshot', type=Path, required=True)
    ctx.add_argument('--outcome', type=Path, required=True)
    ctx.add_argument('--prelaunch', type=Path, required=True)
    ctx.add_argument('--out', type=Path, required=True)
    ctx.add_argument('--job-state', type=Path, action='append', default=[])
    ctx.add_argument('--extra', type=Path)
    review = sub.add_parser('review', help='five-stage --review-context')
    review.add_argument('--snapshot', type=Path, required=True)
    review.add_argument('--catalog', type=Path, required=True)
    review.add_argument('--parent-target', type=Path, required=True)
    review.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'context':
            context, gaps = build_context(args.scenario, args.outcome, _load(args.snapshot), _load(args.prelaunch),
                                          [_load(p) for p in args.job_state], _load(args.extra) if args.extra else None)
            context_path, capture_path = write_context_and_capture(context, args.prelaunch, args.out)
            print(json.dumps({'context': context_path.name, 'capture': capture_path.name, 'gaps': gaps}))
            return 0
        value = review_context(_load(args.snapshot), _load(args.catalog), _load(args.parent_target))
        if value is None:
            print(json.dumps({'review_context': None, 'gap': 'no host-recorded review dispatch'}))
            return 1
        args.out.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
        args.out.chmod(0o600)
        print(json.dumps({'review_context': args.out.name, 'task_id': value['task_id']}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'observations_to_context.py: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
