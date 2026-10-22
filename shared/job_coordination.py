"""Derived coordination views and job-local admission. No host calls or scheduling."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re

from core.jobs.store import JobError, canonical, digest

DEFAULT_MAX_REPAIR_CYCLES = 20
COMPACT_MAX_BYTES = 16384
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


def observed_now():
    """Local observation receipt time, never host execution or human attention time."""
    return datetime.now(timezone.utc).isoformat()


def freeze_provider_limits(job, pins):
    values = {canonical(pin.get('limits', {}).get('max_live_workers_by_provider', {})) for pin in pins.values()}
    policy = job.setdefault('policy', {})
    if 'max_live_workers_by_provider' not in policy:
        if len(values) > 1:
            raise JobError('conflicting pin limits require explicit job policy')
        limits = next(iter(pins.values()), {}).get('limits', {}).get('max_live_workers_by_provider', {})
        if limits:
            policy['max_live_workers_by_provider'] = dict(limits)
    provider_limits(policy.get('max_live_workers_by_provider', {}))


def provider_limits(value):
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key.strip() or len(key) > 128
        or type(limit) is not int or limit < 1 for key, limit in value.items()
    ):
        raise JobError('max_live_workers_by_provider requires provider instance IDs and positive integers')
    return value


def _latest_tasks(job):
    seen = set()
    for task in job['tasks'] + [task for history in reversed(job.get('history', [])) for task in history.get('tasks', [])]:
        if task['task_id'] not in seen:
            seen.add(task['task_id'])
            yield task


def deferred(task):
    events = [event for event in task.get('dispatch_history', []) if event.get('kind') == 'capacity-deferred']
    return bool(events and not events[-1].get('completion_id'))


def overview(store, job=None, *, compact=False, since=None, cursor=None, limit=20):
    job = store.load() if job is None else job
    full = store.overview(job, persist=False)
    full.update(limits=job['policy'], coordination_metrics=coordination_metrics(job), state_sha256=digest(canonical(job)))
    return compact_overview(job, full, store.file, since=since, cursor=cursor, limit=limit) if compact else full


def occupancy(job):
    """Count retained live handles, uncertain launches and prepared reservations.

    Terminal handles with pending children or without authoritative result_available
    still own capacity. Removed tasks remain owned through retained history.
    """
    occupied, seen_hosts = {}, set()
    current_tasks = {id(task) for task in job['tasks']}
    for task in _latest_tasks(job):
        handles = task.get('handles', []) + task.get('followups', [])
        for handle in handles:
            host = handle.get('task_id', handle.get('host_task_id'))
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            if (handle.get('status') not in TERMINAL or handle.get('has_pending_child_runs')
                    or handle.get('work_state') != 'result_available'):
                occupied['host:' + str(host)] = {
                    'host_task_id': host,
                    'task_id': task['task_id'], 'request_id': handle.get('request_id'),
                    'provider': (handle.get('target') or task.get('target') or {}).get('providerInstanceId'),
                    'kind': 'live',
                }
        if id(task) not in current_tasks:
            continue
        known = {handle.get('request_id') for handle in handles} | {
            execution.get('request_id') for execution in task.get('execution_history', [])}
        candidates = [task.get('prepared_followup'), task.get('followup_dispatch')]
        if not deferred(task):
            candidates += [task.get('brief'), task if task.get('uncertain_calls') else None]
        for candidate in candidates:
            if not candidate or candidate.get('request_id') in known:
                continue
            request = candidate.get('request_id')
            if not request:
                continue
            # Superseded prepared briefs cannot launch under the current contract.
            if candidate is task.get('brief') and request != task['request_id']:
                continue
            occupied['request:' + request] = {
                'task_id': task['task_id'], 'request_id': request,
                'provider': (task.get('target') or {}).get('providerInstanceId'),
                'kind': 'uncertain' if candidate.get('uncertain_calls') else 'prepared',
            }
    for blocker in job.get('blockers', []):
        if blocker.get('kind') == 'conflicting-host-handle' and blocker.get('host_task_id') and not blocker.get('reconciled'):
            host = blocker.get('host_task_id')
            occupied.setdefault('host:' + str(host), {
                'host_task_id': host,
                'task_id': blocker.get('task_id'), 'request_id': blocker.get('request_id'),
                'provider': None, 'kind': 'unreconciled-conflict',
            })
    return list(occupied.values())


def task_admission(job, task, *, request_id=None, occupied=None):
    request_id = request_id or task['request_id']
    used = [row for row in (occupancy(job) if occupied is None else occupied) if not (
        row['task_id'] == task['task_id'] and row['request_id'] == request_id
        and row['kind'] in ('prepared', 'uncertain'))]
    provider = (task.get('target') or {}).get('providerInstanceId')
    limits = job['policy'].get('max_live_workers_by_provider', {})
    provider_limits(limits)
    global_limit = job['policy'].get('max_live_workers')
    reason = None
    if deferred(task):
        reason = 'owned_completion_required'
    elif limits and not provider:
        reason = 'provider_identity_required'
    elif global_limit is not None and len(used) >= global_limit:
        reason = 'global_worker_limit'
    elif provider in limits and sum(row['provider'] in (None, provider) for row in used) >= limits[provider]:
        reason = 'provider_worker_limit'
    return {'eligible': reason is None, 'reason': reason, 'providerInstanceId': provider,
            'global_used': len(used), 'global_limit': global_limit,
            'provider_used': sum(row['provider'] in (None, provider) for row in used),
            'provider_limit': limits.get(provider)}


def require_admission(job, task, *, request_id=None):
    result = task_admission(job, task, request_id=request_id)
    if not result['eligible']:
        raise JobError('admission_deferred: ' + result['reason'])


def task_readiness(job, task, *, occupied, stages):
    stage = stages[task['stage_id']]
    result = task_admission(job, task, occupied=occupied)
    reason = result['reason']
    if any(row['task_id'] == task['task_id'] and row['kind'] != 'prepared' for row in occupied):
        reason = 'reconcile_owned_work'
    elif task.get('status', 'pending') not in ('pending', 'stale', 'blocked'):
        reason = 'task_not_pending'
    elif task.get('attempt', 0) or task.get('inputs_stale') or stage.get('validated_cycle') == stage.get('cycle', 0):
        # This view never grants a charged retry or clears stale inputs.
        reason = 'execution_or_retry_checks_required'
    elif any(stages[dep].get('status') != 'accepted-at-snapshot' for dep in stage.get('depends_on', [])):
        reason = 'predecessor_acceptance_required'
    return {**result, 'eligible': reason is None, 'reason': reason}


def admission(job):
    stages = {stage['id']: stage for stage in job['stages']}
    occupied = occupancy(job)
    rows = [{'task_id': task['task_id'], 'request_id': task['request_id'],
             **task_readiness(job, task, occupied=occupied, stages=stages)} for task in job['tasks']]
    return {'scope': 'job-local; preparation rechecks under lock; host capacity still applies',
            'occupied': len(occupied), 'tasks': rows}


def coordination_metrics(job):
    """Count retained facts without changing state or manufacturing telemetry."""
    all_tasks = _latest_tasks(job)
    executions = {}
    observations = unchanged = deferrals = rate_limits = retry_grants = 0
    decision_events, waits, seconds = [], {}, 0.0
    decision_requests = 0
    missing_time = False
    for task in all_tasks:
        previous = {}
        for event in task.get('dispatch_history', []):
            kind = event.get('kind')
            if kind in ('completion', 'reconciled', 'identity'):
                observations += 1
                key = (event.get('request_id'), event.get('host_task_id'), kind)
                value = {k: v for k, v in event.items() if k != 'recorded_at'}
                if previous.get(key) == value:
                    unchanged += 1
                previous[key] = value
            if kind == 'capacity-deferred':
                if event.get('completion_id'):
                    retry_grants += 1
                else:
                    deferrals += 1
                    rate_limits += event.get('reason') == 'rate-limit'
            if kind in ('approval-wait', 'approval-resolved'):
                decision_events.append(event)
        for execution in task.get('execution_history', []):
            if execution.get('technical_failure'):
                continue  # A failed host call has no worker result transport.
            request = execution.get('request_id')
            if request:
                size = execution.get('result_bytes')
                if size is None and request == task.get('request_id') and (task.get('result_ref') or {}).get('kind') == 'inline':
                    size = (task.get('result_ref') or {}).get('bytes')
                if type(size) is not int or size < 0:
                    size = None
                if request not in executions or executions[request] is None:
                    executions[request] = size
    for event in sorted(decision_events, key=lambda event: event.get('recorded_at') or ''):
        wait = event.get('wait_id')
        if event['kind'] == 'approval-wait' and wait not in waits:
            waits[wait] = event.get('recorded_at')
            decision_requests += 1
        elif event['kind'] == 'approval-resolved' and wait in waits:
            stamp = waits.pop(wait)
            try:
                start = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                end = datetime.fromisoformat(event['recorded_at'].replace('Z', '+00:00'))
                if start.tzinfo is None or end.tzinfo is None or end < start:
                    raise ValueError('invalid receipt interval')
                seconds += (end - start).total_seconds()
            except (ValueError, TypeError, AttributeError, KeyError):
                missing_time = True
    unknown_sizes = sum(size is None for size in executions.values())
    stages = job['stages']
    cycles = {}
    for stage in stages + [stage for history in job.get('history', []) for stage in history.get('stages', [])]:
        cycles[stage['id']] = max(cycles.get(stage['id'], 0), stage.get('cycle', 0))
    unknown = lambda reason: {'value': None, 'reason': reason}
    return {
        'accepted_stages': sum(stage.get('status') == 'accepted-at-snapshot' for stage in stages),
        'repair_cycles': sum(cycles.values()),
        'executions_with_results': len(executions),
        'recorded_observations': observations, 'unchanged_observations': unchanged,
        'capacity_deferrals': deferrals, 'rate_limit_deferrals': rate_limits,
        'capacity_retry_grants': retry_grants, 'decision_requests': decision_requests,
        'pending_decisions': len(job.get('approval_waits', [])),
        'resolved_decision_wait_seconds': unknown('older receipt timestamps unavailable') if missing_time
            else round(seconds, 6),
        'result_bytes': unknown(f'{unknown_sizes} retained executions have no recorded transport byte size') if unknown_sizes
            else sum(executions.values()),
        'known_result_bytes': sum(size for size in executions.values() if size is not None),
        'duplicate_completion_deliveries': unknown('idempotently ignored deliveries are not retained'),
        'host_execution_seconds': unknown('host execution timing is not recorded by this store'),
        'tokens': unknown('host token accounting is not recorded by this store'),
    }


def _short(value):
    value = str(value)
    return value if len(value) <= 160 else value[:157] + '...'


def compact_overview(job, full, path, *, since=None, cursor=None, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise JobError('compact limit must be between 1 and 100')
    if since is not None and not re.fullmatch(r'[0-9a-f]{64}', since):
        raise JobError('--since requires a view SHA-256')
    if since is not None and cursor is not None:
        raise JobError('--since and --cursor cannot be combined')
    sha = digest(canonical(full))
    response = {'schema_version': 1, 'job_id': job['job_id'], 'view_sha256': sha, 'changed': sha != since}
    if sha == since:
        return response
    offset = 0
    if cursor is not None:
        match = re.fullmatch(r'([0-9a-f]{64}):([0-9]+)', cursor)
        if not match or match[1] != sha:
            raise JobError('stale or invalid compact cursor; restart from the current view')
        offset = int(match[2])
    records = []
    def add(kind, index, row):
        if 'kind' in row:
            row = {**row, 'detail_kind': row['kind']}
            del row['kind']
        records.append({'kind': kind, 'details': str(path) + '#/' + kind + '/' + str(index), **row})
    for kind in ('blockers', 'approval_waits', 'gaps', 'fallbacks'):
        for index, item in enumerate(job.get(kind, [])):
            row = {key: _short(item[key]) for key in ('kind', 'task_id', 'request_id', 'wait_id', 'reason', 'status') if key in item} if isinstance(item, dict) else {'summary': _short(item)}
            add(kind, index, row)
    occupied = occupancy(job)
    stages = {stage['id']: stage for stage in job['stages']}
    for holder in occupied:
        records.append({'kind': 'occupants', 'details': str(path), 'occupancy_kind': holder['kind'],
                        **{key: _short(value) if value is not None else None
                           for key, value in holder.items() if key != 'kind'}})
    for index, task in enumerate(job['tasks']):
        if stages[task['stage_id']]['status'] == 'accepted-at-snapshot' and not any(row['task_id'] == task['task_id'] for row in occupied):
            continue
        state = task.get('status', 'pending')
        readiness = task_readiness(job, task, occupied=occupied, stages=stages)
        action = ('wait_for_completion' if state == 'running' else 'ingest_result' if state == 'awaiting-acceptance' and not task.get('result_ref')
                  else 'validate_stage' if state == 'awaiting-acceptance' else 'diagnose_or_retry' if state in ('failed', 'blocked', 'stale')
                  else 'prepare_if_admitted' if state == 'pending' else 'inspect')
        if state == 'pending' and not readiness['eligible']:
            action = 'inspect_admission'
        add('tasks', index, {'task_id': _short(task['task_id']), 'stage_id': _short(task['stage_id']),
                            'status': _short(state), 'next_action': action,
                            'admission': readiness})
    for index, stage in enumerate(job['stages']):
        add('stages', index, {'stage_id': _short(stage['id']), 'status': _short(stage['status']),
                             'repair_cycles_used': stage.get('cycle', 0),
                             'repair_cycles_remaining': max(0, job['policy']['max_repair_cycles'] - stage.get('cycle', 0))})
    for index, item in enumerate(job.get('decisions', [])):
        add('decisions', index, {key: _short(item[key]) for key in ('id', 'scope') if key in item})
    for provider, cap in sorted(job['policy'].get('max_live_workers_by_provider', {}).items()):
        records.append({'kind': 'provider_limit', 'providerInstanceId': provider, 'limit': cap})
    if offset > len(records):
        raise JobError('compact cursor is outside the current view')
    response.update(status=_short(full['status']), current_stage=_short(full['current_stage']) if full['current_stage'] is not None else None,
                    full_state_path=str(path), metrics=full['coordination_metrics'],
                    counts=dict(Counter(row['kind'] for row in records)), total_records=len(records),
                    total_tasks=len(job['tasks']), total_stages=len(job['stages']),
                    limits={'max_repair_cycles': job['policy']['max_repair_cycles'],
                            'max_live_workers': job['policy'].get('max_live_workers')},
                    records=[], next_cursor=None)
    for record in records[offset:offset + limit]:
        response['records'].append(record)
        response['next_cursor'] = f'{sha}:{offset + len(response["records"])}' if offset + len(response['records']) < len(records) else None
        if len(canonical(response)) + 1 > COMPACT_MAX_BYTES:
            response['records'].pop()
            response['next_cursor'] = f'{sha}:{offset + len(response["records"])}'
            break
    if not response['records'] and offset < len(records):
        raise JobError('compact metadata exceeds byte limit; inspect full state')
    if len(canonical(response)) + 1 > COMPACT_MAX_BYTES:
        raise JobError('compact metadata exceeds byte limit; inspect full state')
    return response
