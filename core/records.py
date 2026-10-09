"""`record`: validate a completed action, host response or evidence receipt and
fold it into the run record. Every handler raises before mutating on bad input,
so a rejected record leaves the state untouched."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from . import acceptance, blockers, contract, engine, results, selection, snapshot, t3, transitions
from .errors import InvalidInput, Prohibited
from .fsutil import copy_artifact, write_artifact
from .store import now_iso

KINDS = ('capabilities', 'transition', 'dispatch', 'observation', 'result', 'cancel', 'check', 'acceptance',
         'waiver', 'repair', 'resource', 'assign', 'cleanup', 'integration', 'remote-receipt',
         'remote-observation', 'block', 'note', 'policy', 'fail')


def _require(payload: dict, *names):
    missing = [name for name in names if payload.get(name) in (None, '')]
    if missing:
        raise InvalidInput('record_fields', f'record is missing {missing}')


def _task(state, task_id) -> dict:
    task = engine.task_by_id(state, task_id)
    if task is None:
        raise InvalidInput('unknown_task', f'no task {task_id}', {'task_id': task_id})
    return task


def _round_for_host_id(state, host_task_id):
    for task in state.get('tasks', []):
        for item in task.get('rounds') or []:
            if item.get('task_id') == host_task_id:
                return task, item
    raise Prohibited('foreign_task', 'that host task ID does not belong to this run', {'task_id': host_task_id})


def _phase(state, *phases):
    if state['phase'] not in phases:
        raise Prohibited('wrong_phase', f'this record needs phase {"/".join(phases)}, run is {state["phase"]}',
                         {'phase': state['phase']})


def _roots(ctx, state):
    roots = [state['repo']['worktree'], str(ctx.run_dir)]
    roots += [item['path'] for item in state.get('resources', []) if item['kind'] == 'worktree' and item.get('path')]
    extra = (state.get('policy') or {}).get('evidence_roots') or []
    return roots + list(extra)


def _bind(ctx, state):
    return acceptance.binding(state, ctx.state_root)


def _permitted(ctx, state, wanted_kind, payload):
    """The recorded action must be one `next` currently permits."""
    action_id = payload.get('action_id') or (payload.get('action') or {}).get('id')
    if not action_id:
        raise InvalidInput('action_id', 'record the action_id returned by next')
    current = engine.next_actions(ctx, state)
    for item in current['actions']:
        if item['id'] == action_id and item['action'] == wanted_kind:
            return item
    raise Prohibited('action_not_permitted', 'that action is not currently permitted; call next again',
                     {'action_id': action_id, 'permitted': [a['id'] for a in current['actions']]})


# -- handlers ------------------------------------------------------------------

def rec_capabilities(ctx, state, payload):
    response = payload.get('response', payload)
    caps = t3.capabilities(response)
    caps['recorded_at'] = ctx.at
    caps['artifact'] = write_artifact(ctx.run_dir, 'host', 'capabilities.json',
                                      schema_json(response))
    host = state['host']
    if caps.get('parent_thread_id'):
        if host.get('parent_thread_id') and host['parent_thread_id'] != caps['parent_thread_id'] and engine.live_host_tasks(state):
            raise Prohibited('cross_parent', 'capabilities came from another parent thread while tasks are live; '
                                             'use next to get the cross-parent handoff')
        host['parent_thread_id'] = host.get('parent_thread_id') or caps['parent_thread_id']
    inherited = caps.get('inherited') or {}
    if inherited.get('providerInstanceId'):
        if host.get('provider_instance_id') and host['provider_instance_id'] != inherited['providerInstanceId']:
            transitions.event(state, 'provider_switch',
                              f'parent provider {host["provider_instance_id"]} -> {inherited["providerInstanceId"]}', ctx.at)
        host['provider_instance_id'] = inherited['providerInstanceId']
        host['model'] = inherited.get('model')
    state['capabilities'] = caps
    return {'available': caps['available'], 'missing': caps['missing'],
            'unavailable_providers': {p['id']: p['unavailable_reasons'] for p in caps['providers'] if not p['available']}}


def schema_json(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def rec_transition(ctx, state, payload):
    _require(payload, 'to')
    target = payload['to']
    if target in ('ready', 'completed'):
        bind = _bind(ctx, state)
        ev = acceptance.evaluate(state, ctx.state_root, ctx.run_dir, bind)
        if not ev['ready']:
            raise Prohibited('not_ready', 'readiness is not satisfied at the current revision',
                             {'missing': ev['missing'], 'failed': ev['failed'], 'stale': ev['stale']})
        if target == 'completed':
            ok, why = acceptance.remote_confirmed(state, bind)
            if not ok:
                raise Prohibited('remote_unconfirmed', why)
        state['readiness'] = {'status': 'ready', 'binding': bind, 'at': ctx.at}
    if target == 'executing' and state['phase'] == 'verifying':
        raise Prohibited('repair_via_record', 'use record --kind repair to return to executing')
    if target == 'executing' and engine.needs_delegation(state) and state['execution']['mode'] == 'delegated':
        caps = state.get('capabilities') or {}
        if not caps.get('available'):
            raise Prohibited('capability_unavailable', 'delegated execution needs discovered T3 capabilities')
    if target == 'cancelled' and engine.live_host_tasks(state):
        raise Prohibited('cancel_unconfirmed', 'tasks are not confirmed stopped',
                         {'task_ids': engine.live_host_tasks(state)})
    if target == 'cancelling':
        state['cancellation'] = {'requested_at': ctx.at, 'reason': payload.get('reason') or 'operator request',
                                 'outcomes': []}
    if target == 'verifying' and state['phase'] == 'executing':
        open_tasks = [t['id'] for t in state['tasks'] if t.get('kind') not in ('review', 'probe')
                      and t['status'] not in engine.DONE_TASK + ('cancelled',)]
        pending_integration = [t['id'] for t in engine.delegated_writers(state) if t['status'] == 'accepted']
        if open_tasks or pending_integration:
            raise Prohibited('tasks_open', 'tasks are not finished or integrated',
                             {'open': open_tasks, 'awaiting_integration': pending_integration})
    transitions.apply(state, target, payload.get('reason') or 'recorded transition', ctx.at)
    return {'phase': state['phase']}


def _new_task(spec: dict) -> dict:
    task = {key: value for key, value in spec.items() if key != 'ephemeral'}
    task.setdefault('rounds', [])
    task.setdefault('status', 'pending')
    return task


def rec_dispatch(ctx, state, payload):
    _phase(state, 'executing', 'verifying')
    permitted = _permitted(ctx, state, 'dispatch', payload)
    args = permitted['args']
    task = engine.task_by_id(state, permitted['task_id'])
    if task is None:
        if not args.get('create_task'):
            raise InvalidInput('unknown_task', 'dispatch names no known task')
        task = _new_task(args['create_task'])
        state['tasks'].append(task)
        if task.get('kind') == 'review':
            state.setdefault('counters', {})['review_rounds'] = task['review_round']
    elif args.get('create_task') and task.get('kind') == 'review':
        task['target'], task['target_why'] = args['target'], args['why']
    call = permitted['host_call']['arguments']
    entry = {'round': args['round'], 'purpose': args['purpose'], 'client_request_id': call['clientRequestId'],
             'target': args['target'], 'why': args['why'], 'dispatched_at': ctx.at,
             'parent_thread_id': state['host'].get('parent_thread_id'), 'task_id': None, 'terminal': False,
             'observations': []}
    if payload.get('error'):
        entry['dispatch_error'] = payload['error']
        entry['terminal'] = True
        kind = t3.classify_dispatch_error(payload['error'])
        task['rounds'].append(entry)
        if kind == 'unavailable' and args.get('target'):
            skipped = set(task.get('unavailable_targets') or [])
            skipped.add(selection.key(args['target']))
            task['unavailable_targets'] = sorted(skipped)
            if task.get('kind') == 'review':
                task['status'] = 'unavailable'
                state.setdefault('reviews', []).append({
                    'round': task['review_round'], 'task_id': task['id'], 'selection': args['target'],
                    'why': args['why'], 'verdict': 'unavailable', 'detail': payload['error'],
                    'recorded_at': ctx.at, 'invalidated': 'superseded by the next chain candidate'})
            elif task.get('kind') == 'probe':
                provider = task['probe']['provider']
                state.setdefault('probes', {})[provider] = {'sibling_write': False, 'observed_at': ctx.at,
                                                            'evidence': f'probe dispatch unavailable: {payload["error"]}'}
                task['status'] = 'accepted'
            else:
                task['status'] = 'pending'
                task['target'] = None if not task.get('pinned_target') else task['target']
            return {'task': task['id'], 'outcome': 'unavailable', 'unavailable_targets': task.get('unavailable_targets')}
        return _block_task(ctx, state, task, 'task_failed', f'dispatch failed: {payload["error"]}')
    obs = t3.observation(payload.get('response') or {})
    entry['task_id'] = obs['task_id']
    entry['child_thread_id'] = obs['child_thread_id']
    entry['wait_timed_out'] = obs['wait_timed_out']
    task['rounds'].append(entry)
    task['status'] = 'active'
    task['target'] = task.get('target') or args['target']
    if task.get('worktree') and task.get('writes'):
        task['base_sha'] = snapshot.git(task['worktree'], 'rev-parse', 'HEAD').strip()
    if task.get('next_round'):
        task['next_round'] = None
    if task.get('writes') and task.get('executor') == 'delegate':
        mode, _ = engine.isolation(state)
        state['execution']['isolation'] = state['execution'].get('isolation') or mode
    return _observe(ctx, state, task, entry, obs)


def _block_task(ctx, state, task, code, reason):
    task['status'] = 'blocked'
    item = blockers.make(ctx, state, code, reason, [task['id']], ctx.at)
    task['blocker_id'] = item['id']
    state.setdefault('blockers', []).append(item)
    transitions.event(state, 'task_blocked', f'{task["id"]}: {reason}', ctx.at)
    return {'task': task['id'], 'outcome': 'blocked', 'blocker': item}


def _observe(ctx, state, task, entry, obs):
    entry['observations'].append({'at': ctx.at, 'status': obs['status'], 'work_state': obs['work_state'],
                                  'has_pending_child_runs': obs['has_pending_child_runs']})
    entry['last_status'], entry['last_work_state'] = obs['status'], obs['work_state']
    outcome = t3.outcome(obs)
    if entry.get('cancel') is not None:
        entry['cancel']['confirm_attempted'] = True
        if t3.stop_confirmed(obs):
            entry['cancel']['confirmed'] = True
            entry['terminal'] = True
            task['status'] = 'cancelled'
            state['cancellation']['outcomes'].append({'task_id': entry['task_id'], 'confirmed': True,
                                                      'status': obs['status'], 'at': ctx.at})
        return {'task': task['id'], 'outcome': 'cancel_confirmed' if entry['terminal'] else 'cancel_unconfirmed'}
    if outcome == 'working':
        return {'task': task['id'], 'outcome': 'working', 'work_state': obs['work_state'],
                'note': 'waiting_for_children is not a result' if obs['work_state'] == 'waiting_for_children' else None}
    entry['terminal'] = True
    if outcome in ('stopped', 'failed'):
        raw = write_artifact(ctx.run_dir, 'results', f'{task["id"]}-r{entry["round"]}-raw.txt',
                             str(obs.get('summary') or '').encode())
        if task.get('kind') == 'probe':
            return _probe_check(ctx, state, task)
        return _block_task(ctx, state, task, 'task_failed', f'child ended {obs["status"]}; raw output {raw["path"]}')
    if task.get('kind') == 'probe':
        return _probe_check(ctx, state, task)
    text = obs.get('summary')
    if not text or '```' not in text:
        task['status'] = 'awaiting_text'
        return {'task': task['id'], 'outcome': 'awaiting_text'}
    return _take_result(ctx, state, task, text)


def _probe_check(ctx, state, task):
    probe = task['probe']
    marker = Path(probe['marker'])
    try:
        ok = marker.read_text().strip() == probe['nonce']
    except OSError:
        ok = False
    state.setdefault('probes', {})[probe['provider']] = {
        'sibling_write': ok, 'observed_at': ctx.at, 'marker': str(marker),
        'evidence': 'parent read the nonce from the marker file' if ok else 'marker file absent or wrong after the child finished'}
    task['status'] = 'accepted'
    return {'task': task['id'], 'outcome': 'probed', 'sibling_write': ok}


def _take_result(ctx, state, task, text):
    rounds = task.get('rounds') or []
    round_no = rounds[-1]['round'] if rounds else 1
    raw = write_artifact(ctx.run_dir, 'results', f'{task["id"]}-r{round_no}-raw.txt', text.encode())
    worktree = task.get('worktree') or (state['repo']['worktree'] if task.get('executor') == 'self' else None)
    try:
        result = results.extract(text)
        results.validate(state, task, result, worktree)
    except results.Malformed as exc:
        task.setdefault('malformed', []).append({'round': round_no, 'problem': str(exc), 'raw': raw})
        if task.get('correction_used'):
            return _block_task(ctx, state, task, 'malformed_result',
                               f'result still malformed after one correction ({exc}); raw output kept at {raw["path"]}')
        task['correction_used'] = True
        task['status'] = 'correction_needed'
        task['next_round'] = {'purpose': 'correction', 'context': {'problem': str(exc), 'raw': text[-6000:]}}
        return {'task': task['id'], 'outcome': 'correction_requested', 'problem': str(exc), 'raw': raw}
    except results.Rejected as exc:
        task.setdefault('rejections', []).append({'round': round_no, 'code': exc.code, 'details': exc.details, 'raw': raw})
        return _block_task(ctx, state, task, 'result_rejected', f'{exc}: {exc.details}')
    artifact = write_artifact(ctx.run_dir, 'results', f'{task["id"]}-r{round_no}.json', schema_json(result))
    task['result'] = {'artifact': artifact, 'raw': raw, 'status': result['status'], 'changed_files': result['changed_files'],
                      'commit': result.get('commit'), 'verdict': result.get('verdict'), 'findings': result['findings'],
                      'round': round_no}
    if result['status'] != 'done':
        reason = '; '.join(item['reason'] for item in result['blockers']) or f'child reported {result["status"]}'
        return _block_task(ctx, state, task, 'task_failed', reason)
    task['status'] = 'accepted'
    if task.get('kind') == 'review':
        bind = _bind(ctx, state)
        state.setdefault('reviews', []).append({
            'round': task['review_round'], 'task_id': task['id'], 'selection': task.get('target'),
            'why': task.get('target_why'), 'verdict': result['verdict'], 'findings': result['findings'],
            'artifact': artifact, 'snapshot': bind['snapshot'], 'contract_hash': bind['contract_hash'],
            'policy_hash': bind['policy_hash'], 'recorded_at': ctx.at,
            'host_task_id': (rounds[-1] if rounds else {}).get('task_id'),
            'client_request_id': (rounds[-1] if rounds else {}).get('client_request_id')})
    return {'task': task['id'], 'outcome': 'accepted', 'artifact': artifact,
            'verdict': result.get('verdict')}


def rec_observation(ctx, state, payload):
    response = payload.get('response') or {}
    obs = t3.observation(response)
    recorded_parent = state['host'].get('parent_thread_id')
    if ctx.parent_thread_id and recorded_parent and ctx.parent_thread_id != recorded_parent:
        raise Prohibited('cross_parent', 'task status is parent-scoped; this thread cannot use the old task IDs')
    task, entry = _round_for_host_id(state, obs['task_id'])
    if entry.get('terminal') and entry.get('cancel') is None:
        return {'task': task['id'], 'outcome': 'already_terminal'}
    return _observe(ctx, state, task, entry, obs)


def rec_result(ctx, state, payload):
    _require(payload, 'task_id')
    task = _task(state, payload['task_id'])
    text = payload.get('text')
    if text is None and payload.get('text_file'):
        text = Path(payload['text_file']).read_text()
    if text is None and isinstance(payload.get('result'), dict):
        text = '```json t3-result\n' + schema_json(payload['result']).decode() + '```'
    if text is None:
        raise InvalidInput('record_fields', 'result needs text, text_file or result')
    if task.get('executor') == 'self':
        _phase(state, 'executing')
        if task['status'] not in ('pending', 'correction_needed'):
            raise Prohibited('task_state', f'task {task["id"]} is {task["status"]}')
        task.setdefault('rounds', []).append({'round': len(task['rounds']) + 1, 'purpose': 'self', 'task_id': None,
                                              'terminal': True, 'observations': [], 'dispatched_at': ctx.at})
        task['next_round'] = None
        return _take_result(ctx, state, task, text)
    if task['status'] != 'awaiting_text':
        raise Prohibited('task_state', f'task {task["id"]} is {task["status"]}; results arrive through observation')
    return _take_result(ctx, state, task, text)


def rec_cancel(ctx, state, payload):
    _phase(state, 'cancelling')
    response = payload.get('response') or {}
    host_id = response.get('taskId') or payload.get('host_task_id')
    task, entry = _round_for_host_id(state, host_id)
    result = t3.cancel_response(response)
    entry['cancel'] = {'requested_at': ctx.at, 'response_status': result['status'], 'confirmed': result['confirmed'],
                       'confirm_attempted': False}
    if result['confirmed']:
        entry['terminal'] = True
        task['status'] = 'cancelled'
        state['cancellation']['outcomes'].append({'task_id': host_id, 'confirmed': True, 'status': result['status'],
                                                  'at': ctx.at})
    return {'task': task['id'], 'confirmed': result['confirmed'], 'status': result['status'],
            'note': None if result['confirmed'] else 'not yet confirmed; next will ask for task_status'}


def rec_check(ctx, state, payload):
    _phase(state, 'verifying')
    _require(payload, 'name', 'log')
    check = next((c for c in state['policy'].get('checks', []) if c['name'] == payload['name']), None)
    if check is None:
        raise InvalidInput('unknown_check', f'no check named {payload["name"]} in the run policy')
    if payload.get('argv') != check['argv']:
        raise InvalidInput('argv_mismatch', 'recorded argv must equal the planned argv exactly',
                           {'planned': check['argv'], 'recorded': payload.get('argv')})
    code = payload.get('exit_code')
    reason = payload.get('unavailable_reason')
    if code is None and not reason:
        raise InvalidInput('record_fields', 'check needs exit_code or unavailable_reason')
    if code == 0 and reason:
        raise InvalidInput('check_contradiction', 'a zero exit cannot be recorded as unavailable')
    artifact = copy_artifact(Path(payload['log']), ctx.run_dir, 'checks', _roots(ctx, state) + [payload.get('log_root')])
    bind = _bind(ctx, state)
    status = 'passed' if code == 0 else 'unavailable' if reason or code in (124, 126, 127) else 'failed'
    entry = {'name': check['name'], 'argv': check['argv'], 'cwd': payload.get('cwd') or check.get('cwd'),
             'exit_code': code, 'status': status, 'unavailable_reason': reason, 'artifact': artifact,
             'snapshot': bind['snapshot'], 'contract_hash': bind['contract_hash'], 'policy_hash': bind['policy_hash'],
             'recorded_at': ctx.at, 'started_at': payload.get('started_at'), 'finished_at': payload.get('finished_at'),
             'invocation': payload.get('invocation'), 'attestation': 'model-mediated native tool observation'}
    state.setdefault('checks', []).append(entry)
    return {'name': check['name'], 'status': status, 'artifact': artifact}


def rec_acceptance(ctx, state, payload):
    _phase(state, 'verifying', 'executing')
    _require(payload, 'requirement_id', 'status', 'kind', 'explanation')
    reqs = {item['id']: item for item in contract.current_contract(state)['requirements']}
    req = reqs.get(payload['requirement_id'])
    if req is None:
        raise InvalidInput('unknown_requirement', f'no requirement {payload["requirement_id"]}')
    if payload['status'] not in ('passed', 'failed', 'unverified', 'unavailable'):
        raise InvalidInput('acceptance_status', 'status must be passed, failed, unverified or unavailable; waivers use record --kind waiver')
    if payload['kind'] != req['kind']:
        raise Prohibited('evidence_kind', f'{req["id"]} needs {req["kind"]} evidence, got {payload["kind"]}')
    paths = payload.get('artifacts') or []
    if payload['status'] == 'passed' and not paths:
        raise Prohibited('evidence_missing', 'a passed requirement needs at least one evidence artifact')
    if payload['kind'] == 'manual' and payload['status'] == 'passed' and not payload.get('verifier'):
        raise InvalidInput('manual_verifier', 'manual evidence names its verifier')
    stored = [copy_artifact(Path(path), ctx.run_dir, 'evidence', _roots(ctx, state)) for path in paths]
    bind = _bind(ctx, state)
    entry = {'requirement_id': req['id'], 'status': payload['status'], 'kind': payload['kind'],
             'explanation': payload['explanation'], 'artifacts': stored, 'verifier': payload.get('verifier'),
             'snapshot': bind['snapshot'], 'contract_hash': bind['contract_hash'], 'policy_hash': bind['policy_hash'],
             'recorded_at': ctx.at}
    state.setdefault('acceptance', []).append(entry)
    return {'requirement_id': req['id'], 'status': payload['status'], 'artifacts': stored}


def rec_waiver(ctx, state, payload):
    _require(payload, 'target', 'reason', 'decided_by', 'operator_quote')
    target = payload['target']
    if target.startswith('check:'):
        name = target[6:]
        check = next((c for c in state['policy'].get('checks', []) if c['name'] == name), None)
        if check is None:
            raise InvalidInput('unknown_check', f'no check {name}')
        if check.get('repository_required'):
            raise Prohibited('waiver_forbidden', 'repository-required checks cannot be waived')
    elif target == 'review':
        if not (state['policy'].get('review') or {}).get('waivable', True):
            raise Prohibited('waiver_forbidden', 'repository policy forbids waiving review')
    elif not target.startswith('requirement:'):
        raise InvalidInput('waiver_target', 'target is requirement:<ID>, check:<name> or review')
    bind = _bind(ctx, state)
    entry = {'target': target, 'reason': payload['reason'], 'decided_by': payload['decided_by'],
             'operator_quote': payload['operator_quote'], 'snapshot': bind['snapshot'],
             'contract_hash': bind['contract_hash'], 'policy_hash': bind['policy_hash'], 'recorded_at': ctx.at}
    state.setdefault('waivers', []).append(entry)
    return {'target': target, 'status': 'waived', 'note': 'a waiver is reported as waived, never as passed'}


def rec_repair(ctx, state, payload):
    _phase(state, 'verifying')
    _require(payload, 'stage')
    stage = payload['stage']
    counters = state.setdefault('counters', {}).setdefault('repairs', {})
    used = counters.get(stage, 0)
    if used >= state['policy']['repair_limit']:
        raise Prohibited('repair_limit', f'{stage} has used {used} of {state["policy"]["repair_limit"]} repair rounds')
    counters[stage] = used + 1
    label = f'repair {stage} #{used + 1}'
    for collection in ('acceptance', 'checks', 'reviews'):
        for entry in state.get(collection, []):
            entry.setdefault('invalidated', label)
    writers = [t for t in state['tasks'] if t.get('writes') and t.get('kind') not in ('review', 'probe')]
    template = writers[-1] if writers else {'executor': 'self', 'role': next(iter(state.get('roles') or {'self': 0})),
                                            'files': []}
    number = sum(1 for t in state['tasks'] if t['id'].startswith('repair-')) + 1
    task = {'id': f'repair-{number}', 'kind': 'code', 'purpose': f'repair after {stage}: {payload.get("reason", "")}'.strip(),
            'role': template.get('role'), 'executor': template.get('executor', 'self'), 'writes': True,
            'depends_on': [], 'requirement_ids': [], 'acceptance': [], 'constraints': [],
            'files': template.get('files') or [], 'status': 'pending', 'rounds': [],
            'next_round': {'purpose': 'repair', 'context': {'findings': payload.get('findings') or []}},
            'target': template.get('target') if template.get('pinned_target') else None}
    state['tasks'].append(task)
    transitions.apply(state, 'executing', label, ctx.at)
    return {'repair_task': task['id'], 'stage': stage, 'used': used + 1, 'limit': state['policy']['repair_limit']}


def _ps(pid: int) -> str | None:
    out = subprocess.run(['ps', '-o', 'lstart=', '-o', 'command=', '-p', str(pid)], capture_output=True)
    text = out.stdout.decode(errors='replace').strip()
    return text or None


def rec_resource(ctx, state, payload):
    _require(payload, 'kind')
    kind = payload['kind']
    rid = f'R-{uuid.uuid4().hex[:8]}'
    repo = state['repo']['worktree']
    created = []
    if kind == 'worktree':
        _require(payload, 'path', 'name')
        path = Path(payload['path'])
        top = snapshot.toplevel(path)
        if top != path.resolve():
            raise InvalidInput('worktree_missing', f'{path} is not the top of a git worktree')
        entry = {'id': rid, 'kind': 'worktree', 'name': payload['name'], 'path': str(path.resolve()),
                 'branch': payload.get('branch'), 'task_id': payload.get('task_id'), 'status': 'live',
                 'created_at': ctx.at, 'cleanup_argv': ['git', '-C', repo, 'worktree', 'remove', '--force', str(path.resolve())]}
        created.append(entry)
        if payload.get('branch'):
            created.append({'id': f'R-{uuid.uuid4().hex[:8]}', 'kind': 'branch', 'name': payload['name'],
                            'branch': payload['branch'], 'status': 'live', 'created_at': ctx.at,
                            'cleanup_argv': ['git', '-C', repo, 'branch', '-D', payload['branch']]})
        name = payload['name']
        if name.startswith('probe-'):
            provider = name[len('probe-'):]
            target = None
            for writer in engine.delegated_writers(state):
                candidate = engine.writer_target(state, writer)
                if candidate and candidate['providerInstanceId'] == provider:
                    target = candidate
                    break
            target = target or {'providerInstanceId': provider, 'model': None, 'options': {}}
            nonce = uuid.uuid4().hex
            state['tasks'].append({
                'id': name, 'kind': 'probe', 'purpose': 'check whether a delegated child can write outside the parent checkout',
                'role': engine.delegated_writers(state)[0]['role'] if engine.delegated_writers(state) else None,
                'host_role': 'test', 'executor': 'delegate', 'writes': False, 'depends_on': [], 'requirement_ids': [],
                'acceptance': [], 'constraints': [], 'files': [], 'status': 'pending', 'rounds': [],
                'target': target, 'target_why': 'probe the writer target', 'pinned_target': True,
                'worktree': str(path.resolve()),
                'probe': {'provider': provider, 'nonce': nonce, 'marker': str(path.resolve() / '.t3-probe-marker')}})
        else:
            for task in state['tasks']:
                if task['id'] == payload.get('task_id') or (name == 'shared' and task['id'] == payload.get('task_id')):
                    task['worktree'], task['branch'] = str(path.resolve()), payload.get('branch')
    elif kind == 'process':
        _require(payload, 'pid')
        fingerprint = _ps(int(payload['pid']))
        if not fingerprint:
            raise InvalidInput('process_missing', f'no process {payload["pid"]}')
        created.append({'id': rid, 'kind': 'process', 'pid': int(payload['pid']), 'fingerprint': fingerprint,
                        'purpose': payload.get('purpose'), 'status': 'live', 'created_at': ctx.at,
                        'cleanup_argv': ['kill', str(int(payload['pid']))]})
    else:
        raise InvalidInput('resource_kind', 'resource kind is worktree or process')
    state.setdefault('resources', []).extend(created)
    return {'resources': created}


def rec_assign(ctx, state, payload):
    _require(payload, 'task_id', 'name')
    task = _task(state, payload['task_id'])
    tree = engine.resource(state, 'worktree', name=payload['name'])
    if not tree:
        raise Prohibited('no_worktree', f'no live worktree named {payload["name"]}')
    task['worktree'], task['branch'] = tree['path'], tree.get('branch')
    return {'task': task['id'], 'worktree': tree['path']}


def resource_live(item: dict) -> bool:
    if item['kind'] == 'worktree':
        return Path(item['path']).exists()
    if item['kind'] == 'branch':
        repo_check = subprocess.run(['git', '-C', item['cleanup_argv'][2], 'rev-parse', '--verify', '-q',
                                     'refs/heads/' + item['branch']], capture_output=True)
        return repo_check.returncode == 0
    if item['kind'] == 'process':
        return _ps(item['pid']) == item['fingerprint']
    return False


def rec_cleanup(ctx, state, payload):
    _require(payload, 'resource_id')
    item = next((r for r in state.get('resources', []) if r['id'] == payload['resource_id']), None)
    if item is None:
        raise InvalidInput('unknown_resource', f'no resource {payload["resource_id"]}')
    if item['kind'] == 'process' and _ps(item['pid']) not in (None, item['fingerprint']):
        item['status'] = 'gone'
        item['note'] = 'pid now belongs to an unrelated process; nothing was signalled'
        return {'resource': item['id'], 'status': 'gone'}
    still = resource_live(item)
    item['status'] = 'live' if still else 'removed'
    item['cleaned_at'] = ctx.at
    if still:
        item['cleanup_error'] = payload.get('error') or f'exit {payload.get("exit_code")}'
    return {'resource': item['id'], 'status': item['status']}


def rec_integration(ctx, state, payload):
    _phase(state, 'executing')
    permitted = _permitted(ctx, state, 'integrate', payload)
    ids = permitted['args']['task_ids']
    branch = permitted['args']['branch']
    log = None
    if payload.get('log'):
        log = copy_artifact(Path(payload['log']), ctx.run_dir, 'integration', _roots(ctx, state))
    if payload.get('exit_code') != 0:
        state.setdefault('integrations', []).append({'task_ids': ids, 'branch': branch, 'exit_code': payload.get('exit_code'),
                                                     'log': log, 'at': ctx.at, 'ok': False})
        task = _task(state, ids[0])
        out = _block_task(ctx, state, task, 'integration_failed',
                          f'merging {branch} failed (exit {payload.get("exit_code")}); worktrees and branches are preserved')
        transitions.apply(state, 'blocked', 'integration failed', ctx.at)
        return out
    repo = state['repo']['worktree']
    merged = subprocess.run(['git', '-C', repo, 'merge-base', '--is-ancestor', branch, 'HEAD'], capture_output=True)
    if merged.returncode != 0:
        raise Prohibited('not_integrated', f'{branch} is not an ancestor of {repo} HEAD; integration did not happen')
    for task_id in ids:
        _task(state, task_id)['status'] = 'integrated'
    state.setdefault('integrations', []).append({'task_ids': ids, 'branch': branch, 'exit_code': 0, 'log': log,
                                                 'at': ctx.at, 'ok': True})
    return {'integrated': ids}


def rec_remote_receipt(ctx, state, payload):
    _phase(state, 'publishing')
    _require(payload, 'kind', 'url')
    remote = state.setdefault('remote', {'receipts': [], 'observations': []})
    if remote.get('receipts'):
        raise Prohibited('receipt_exists', 'a receipt already exists; observe it instead of publishing again')
    receipt = {'kind': payload['kind'], 'url': payload['url'], 'number': payload.get('number'),
               'head_sha': payload.get('head_sha'), 'recorded_at': ctx.at}
    remote.setdefault('receipts', []).append(receipt)
    return receipt


def rec_remote_observation(ctx, state, payload):
    _phase(state, 'publishing')
    _require(payload, 'kind', 'url', 'state', 'head_sha')
    remote = state.setdefault('remote', {'receipts': [], 'observations': []})
    observation = {'kind': payload['kind'], 'url': payload['url'], 'state': str(payload['state']).lower(),
                   'head_sha': payload['head_sha'], 'observed_at': ctx.at, 'source_argv': payload.get('argv')}
    remote.setdefault('observations', []).append(observation)
    return observation


def rec_block(ctx, state, payload):
    blocker = payload.get('blocker')
    if blocker:
        current = engine.next_actions(ctx, state).get('blocked')
        if not current or current['id'] != blocker.get('id'):
            raise Prohibited('block_not_current', 'that blocker is not what next reports now')
        item = current
    else:
        _require(payload, 'reason')
        item = blockers.make(ctx, state, payload.get('code') or 'operator', payload['reason'],
                             payload.get('task_ids') or [], ctx.at)
    if any(existing['id'] == item['id'] for existing in state.get('blockers', [])):
        return {'blocker': item, 'note': 'already recorded'}
    state.setdefault('blockers', []).append(item)
    if state['phase'] != 'blocked':
        transitions.apply(state, 'blocked', item['reason'], ctx.at)
    return {'blocker': item}


def rec_note(ctx, state, payload):
    _require(payload, 'key', 'text')
    state.setdefault('notes', {})[str(payload['key'])[:64]] = str(payload['text'])[:4000]
    return {'note': payload['key']}


def rec_policy(ctx, state, payload):
    changes = payload.get('policy')
    if not isinstance(changes, dict):
        raise InvalidInput('record_fields', 'policy record carries a policy object')
    for forbidden in ('repair_limit', 'budget_seconds'):
        if forbidden in changes:
            raise Prohibited('operator_only', f'{forbidden} changes through unblock decisions only')
    state['policy'].update(changes)
    return {'policy_hash': acceptance.policy_hash(state)}


def rec_fail(ctx, state, payload):
    _require(payload, 'reason')
    transitions.apply(state, 'failed', payload['reason'], ctx.at)
    return {'phase': 'failed'}


HANDLERS = {
    'capabilities': rec_capabilities, 'transition': rec_transition, 'dispatch': rec_dispatch,
    'observation': rec_observation, 'result': rec_result, 'cancel': rec_cancel, 'check': rec_check,
    'acceptance': rec_acceptance, 'waiver': rec_waiver, 'repair': rec_repair, 'resource': rec_resource,
    'assign': rec_assign, 'cleanup': rec_cleanup, 'integration': rec_integration,
    'remote-receipt': rec_remote_receipt, 'remote-observation': rec_remote_observation, 'block': rec_block,
    'note': rec_note, 'policy': rec_policy, 'fail': rec_fail,
}


def apply(ctx, state: dict, kind: str, payload: dict):
    if kind not in HANDLERS:
        raise InvalidInput('record_kind', f'record kind must be one of {sorted(HANDLERS)}')
    if not isinstance(payload, dict):
        raise InvalidInput('record_payload', 'record input must be a JSON object')
    if state['phase'] in ('completed', 'cancelled', 'failed') and kind not in ('cleanup', 'note'):
        raise Prohibited('terminal', f'run is {state["phase"]}; only cleanup and notes may be recorded')
    if state['phase'] == 'blocked' and kind not in ('cleanup', 'note', 'block', 'transition', 'observation', 'cancel'):
        raise Prohibited('blocked', 'run is blocked; resolve it with the blocker resume command first')
    result = HANDLERS[kind](ctx, state, payload)
    transitions.event(state, f'record:{kind}', str(result)[:300], ctx.at)
    return result
