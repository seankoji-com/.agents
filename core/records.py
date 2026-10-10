"""`record`: validate a completed action, host response or evidence receipt and
fold it into the run record. Every handler raises before mutating on bad input,
so a rejected record leaves the state untouched."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from . import acceptance, blockers, contract, engine, resources, results, selection, snapshot, t3, transitions
from .errors import InvalidInput, Prohibited
from .fsutil import contained, copy_artifact, write_artifact
from .store import now_iso

KINDS = ('capabilities', 'transition', 'dispatch', 'observation', 'result', 'cancel', 'check', 'acceptance',
         'waiver', 'repair', 'resource', 'cleanup', 'integration', 'remote-receipt',
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
    if not host_task_id:
        raise InvalidInput('host_task_id', 'record the host task ID (the response taskId)')
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


def _supersede_waivers(state, target, at):
    """A waiver covers the evidence recorded before it. Newer evidence for the same
    obligation (a repeat failure, say) is judged on its own until the operator waives again."""
    for waiver in state.get('waivers', []):
        if waiver['target'] == target and not waiver.get('invalidated'):
            waiver['invalidated'] = f'superseded by evidence recorded at {at}'


def _bind(ctx, state):
    return acceptance.binding(state, ctx.state_root)


def _require_current(ctx, state, payload):
    """Evidence names the snapshot it was gathered at (the `snapshot` from its
    next action). If the tree changed since, the evidence describes another
    revision and is refused. Returns the binding it compared, so the record
    stores exactly the snapshot the evidence was attested against."""
    expected = payload.get('snapshot')
    if not expected:
        raise InvalidInput('snapshot_missing', 'record the snapshot token from the next action that asked for this evidence')
    bind = _bind(ctx, state)
    current = snapshot.token(bind['snapshot'])
    if expected != current:
        raise Prohibited('stale_evidence', 'the working tree changed after this evidence was requested; call next again',
                         {'expected': expected, 'current': current})
    return bind


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


def _head(state) -> str:
    return snapshot.git(state['repo']['worktree'], 'rev-parse', 'HEAD').strip()


def rec_transition(ctx, state, payload):
    _require(payload, 'to')
    target = payload['to']
    if target == 'failed':
        return _fail(ctx, state, payload.get('reason') or 'recorded transition')
    if target in ('ready', 'completed', 'publishing'):
        still = engine.live_host_tasks(state) + engine.uncertain_requests(state)
        if still:
            raise Prohibited('children_running', 'delegated work may still be running; observe it first',
                             {'task_ids': still})
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
    uncertain = [a['client_request_id'] for t in state['tasks'] for a in t.get('uncertain_dispatches') or []
                 if not a.get('operator_cleared')
                 and a['client_request_id'] not in {r.get('client_request_id') for r in t.get('rounds') or []}]
    if target == 'cancelled' and uncertain:
        raise Prohibited('cancel_unconfirmed', 'uncertain dispatches may have started children',
                         {'client_request_ids': uncertain})
    if target == 'executing':
        state['execution']['serial_base'] = _head(state)
        state['execution']['self_base'] = snapshot.baseline(state['repo']['worktree'])
    if target == 'cancelled' and engine.live_host_tasks(state):
        raise Prohibited('cancel_unconfirmed', 'tasks are not confirmed stopped',
                         {'task_ids': engine.live_host_tasks(state)})
    if target == 'cancelling':
        state['cancellation'] = {'requested_at': ctx.at, 'reason': payload.get('reason') or 'operator request',
                                 'outcomes': []}
    if target == 'verifying' and state['phase'] == 'executing':
        open_tasks = [t['id'] for t in state['tasks'] if t.get('kind') not in ('review', 'probe')
                      and t['status'] not in engine.DONE_TASK + ('cancelled',)]
        pending_integration = [t['id'] for t in engine.needs_integration(state)]
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


def _sent_dispatch(ctx, state, payload):
    """A dispatch that was already sent must be tracked even if the run moved on
    since `next` issued it (otherwise its child would be orphaned). The record may
    carry the full action; it is accepted when its id matches its contents and its
    clientRequestId is exactly the next round of that task."""
    try:
        if not payload.get('action_id') and payload.get('action'):
            raise Prohibited('action_not_permitted', 'falling back to the echoed action')
        return _permitted(ctx, state, 'dispatch', payload)
    except (Prohibited, InvalidInput):
        echoed = payload.get('action')
        if not isinstance(echoed, dict) or echoed.get('action') != 'dispatch' or not echoed.get('host_call'):
            raise
        call, args = echoed['host_call'], echoed.get('args') or {}
        if (not isinstance(call, dict) or not isinstance(call.get('arguments'), dict) or not isinstance(args, dict)
                or not echoed.get('task_id')):
            raise Prohibited('action_tampered', 'echoed action is not a well-formed dispatch action')
        rebuilt = engine.action('dispatch', 'dispatch', task_id=echoed['task_id'], args=args,
                                host_call=call, note=echoed.get('note'))
        if rebuilt['id'] != echoed.get('id'):
            raise Prohibited('action_tampered', 'echoed action does not match its id')
        _dispatch_args_shape(args)
        task = engine.task_by_id(state, echoed['task_id']) or args.get('create_task')
        if task is not None and not isinstance(task, dict):
            raise Prohibited('action_tampered', 'echoed action names a malformed task')
        if not task:
            raise
        expected = engine.client_request_id(state, task, len(task.get('rounds') or []) + 1)
        if echoed['host_call']['arguments'].get('clientRequestId') != expected:
            raise Prohibited('action_not_permitted', 'echoed dispatch is not the next round of its task',
                             {'expected_client_request_id': expected})
        return rebuilt


def _dispatch_args_shape(args):
    """An echoed dispatch's args come from the agent, so their shape is checked
    here rather than surfacing later as a KeyError."""
    problems = []
    if not isinstance(args.get('round'), int) or isinstance(args.get('round'), bool) or args['round'] < 1:
        problems.append('round must be a positive integer')
    if not isinstance(args.get('purpose'), str):
        problems.append('purpose must be a string')
    if 'target' not in args or not isinstance(args['target'], (dict, type(None))):
        problems.append('target must be an object or null')
    if 'why' not in args or not isinstance(args['why'], (str, type(None))):
        problems.append('why must be a string or null')
    created = args.get('create_task')
    if created is not None and (not isinstance(created, dict) or not isinstance(created.get('id'), str) or (
            created.get('kind') == 'review' and not isinstance(created.get('review_round'), int))):
        problems.append('create_task must be a task object with an id (and review_round for a review)')
    if problems:
        raise InvalidInput('action_args', 'echoed dispatch args are malformed: ' + '; '.join(problems))


def rec_dispatch(ctx, state, payload):
    if state['phase'] in ('cancelling', 'blocked'):
        if not payload.get('action'):
            raise Prohibited('wrong_phase', 'only an already-sent dispatch (with its full action) can be recorded now')
        payload = dict(payload, action_id=None)
    else:
        _phase(state, 'executing', 'verifying')
    permitted = _sent_dispatch(ctx, state, payload)
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
        kind = t3.classify_dispatch_error(payload['error'])
        if kind == 'uncertain':
            # T3 may have accepted the request. Keep the round open-ended: the next
            # dispatch reuses this clientRequestId, which T3 deduplicates.
            attempts = task.setdefault('uncertain_dispatches', [])
            attempts.append({'client_request_id': call['clientRequestId'], 'error': payload['error'], 'at': ctx.at})
            if len([a for a in attempts if a['client_request_id'] == call['clientRequestId']]) >= 3:
                return _block_task(ctx, state, task, 'task_failed',
                                   f'dispatch outcome unknown after 3 attempts with clientRequestId {call["clientRequestId"]}; '
                                   'check T3 for a task with that request ID before retrying (a retry reuses it)')
            return {'task': task['id'], 'outcome': 'uncertain', 'client_request_id': call['clientRequestId'],
                    'note': 'retry the identical delegate_task call; T3 returns the existing task for this clientRequestId'}
        entry['dispatch_error'] = payload['error']
        entry['terminal'] = True
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
    if task.get('writes') and not task.get('base_sha'):
        task['base_sha'] = args.get('base_sha')
    if task.get('kind') == 'review':
        # Bind the verdict to the revision the review was asked to read: the binding
        # the dispatch was sent with, echoed by this record. An action's id ignores
        # its binding, so `next` may re-offer the same dispatch with a newer one after
        # the tree moved; that newer binding would certify content the reviewer never
        # saw. An echoed binding can only be the current one or older (and so stale).
        echoed = payload.get('binding') or args.get('binding')
        if not isinstance(echoed, dict) or not {'snapshot', 'contract_hash', 'policy_hash'} <= set(echoed):
            raise InvalidInput('binding_missing', 'record the binding from the review dispatch action')
        task['review_binding'] = {key: echoed[key] for key in ('snapshot', 'contract_hash', 'policy_hash')}
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
            if task['status'] not in engine.DONE_TASK:
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
    worktree = task.get('worktree') or state['repo']['worktree']
    try:
        result = results.extract(text)
        results.validate(state, task, result, worktree, _roots(ctx, state))
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
    if not engine.still_running(task):
        _advance_base(state, task)
    if task.get('kind') == 'review':
        bind = task.get('review_binding') or _bind(ctx, state)
        verdict = result['verdict']
        serious = [f for f in result['findings'] if f['severity'] in ('blocker', 'major')]
        if verdict == 'approve' and serious:
            verdict = 'adverse'  # the brief's rule: any blocker or major finding makes the verdict adverse
        state.setdefault('reviews', []).append({
            'round': task['review_round'], 'task_id': task['id'], 'selection': task.get('target'),
            'why': task.get('target_why'), 'verdict': verdict, 'reported_verdict': result['verdict'],
            'findings': result['findings'],
            'artifact': artifact, 'snapshot': bind['snapshot'], 'contract_hash': bind['contract_hash'],
            'policy_hash': bind['policy_hash'], 'recorded_at': ctx.at,
            'host_task_id': (rounds[-1] if rounds else {}).get('task_id'),
            'client_request_id': (rounds[-1] if rounds else {}).get('client_request_id')})
        _supersede_waivers(state, 'review', ctx.at)
    return {'task': task['id'], 'outcome': 'accepted', 'artifact': artifact,
            'verdict': result.get('verdict')}


def _advance_base(state, task):
    """The next writer in the parent's checkout is judged only on what it adds
    after this one, once this one (and any nested run it started) has stopped."""
    if not task.get('writes') or task.get('kind') in ('review', 'probe'):
        return
    if task.get('executor') == 'self' or state['execution'].get('isolation') == 'serial':
        state['execution']['serial_base'] = _head(state)
        state['execution']['self_base'] = snapshot.baseline(state['repo']['worktree'])


def rec_observation(ctx, state, payload):
    response = payload.get('response') or {}
    obs = t3.observation(response)
    recorded_parent = state['host'].get('parent_thread_id')
    if ctx.parent_thread_id and recorded_parent and ctx.parent_thread_id != recorded_parent:
        raise Prohibited('cross_parent', 'task status is parent-scoped; this thread cannot use the old task IDs')
    task, entry = _round_for_host_id(state, obs['task_id'])
    if entry.get('terminal') and entry.get('cancel') is None:
        was_pending = engine.needs_stop(entry)
        entry['observations'].append({'at': ctx.at, 'status': obs['status'], 'work_state': obs['work_state'],
                                      'has_pending_child_runs': obs['has_pending_child_runs']})
        if was_pending and not engine.needs_stop(entry):
            _advance_base(state, task)
        return {'task': task['id'], 'outcome': 'already_terminal',
                'has_pending_child_runs': obs['has_pending_child_runs']}
    return _observe(ctx, state, task, entry, obs)


def rec_result(ctx, state, payload):
    _require(payload, 'task_id')
    task = _task(state, payload['task_id'])
    text = payload.get('text')
    if text is None and payload.get('text_file'):
        text = contained(Path(payload['text_file']), _roots(ctx, state)).read_text()  # same containment as other evidence
    if text is None and isinstance(payload.get('result'), dict):
        text = '```json t3-result\n' + schema_json(payload['result']).decode() + '```'
    if text is None:
        raise InvalidInput('record_fields', 'result needs text, text_file or result')
    if task.get('executor') == 'self':
        _phase(state, 'executing')
        if task['status'] not in ('pending', 'correction_needed'):
            raise Prohibited('task_state', f'task {task["id"]} is {task["status"]}')
        if task.get('writes') and not task.get('self_base') and state['execution'].get('self_base'):
            task['self_base'] = state['execution']['self_base']
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
        if task['status'] not in engine.DONE_TASK:
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
    planned_cwd = Path(check.get('cwd') or state['repo']['worktree'])
    if not planned_cwd.is_absolute():
        planned_cwd = Path(state['repo']['worktree']) / planned_cwd
    if payload.get('cwd') and Path(payload['cwd']).resolve() != planned_cwd.resolve():
        raise InvalidInput('cwd_mismatch', 'recorded cwd must be the planned cwd',
                           {'planned': str(planned_cwd), 'recorded': payload['cwd']})
    bind = _require_current(ctx, state, payload)
    code = payload.get('exit_code')
    if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
        raise InvalidInput('exit_code', 'exit_code is an integer or null', {'exit_code': code})
    reason = payload.get('unavailable_reason')
    if code is None and not reason:
        raise InvalidInput('record_fields', 'check needs exit_code or unavailable_reason')
    if code == 0 and reason:
        raise InvalidInput('check_contradiction', 'a zero exit cannot be recorded as unavailable')
    artifact = copy_artifact(Path(payload['log']), ctx.run_dir, 'checks', _roots(ctx, state))
    status = 'passed' if code == 0 else 'unavailable' if reason or code in (124, 126, 127) else 'failed'
    entry = {'name': check['name'], 'argv': check['argv'], 'cwd': payload.get('cwd') or check.get('cwd'),
             'exit_code': code, 'status': status, 'unavailable_reason': reason, 'artifact': artifact,
             'snapshot': bind['snapshot'], 'contract_hash': bind['contract_hash'], 'policy_hash': bind['policy_hash'],
             'recorded_at': ctx.at, 'started_at': payload.get('started_at'), 'finished_at': payload.get('finished_at'),
             'invocation': payload.get('invocation'), 'attestation': 'model-mediated native tool observation'}
    state.setdefault('checks', []).append(entry)
    _supersede_waivers(state, f'check:{check["name"]}', ctx.at)
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
    bind = _require_current(ctx, state, payload)
    paths = payload.get('artifacts') or []
    if payload['status'] == 'passed' and not paths:
        raise Prohibited('evidence_missing', 'a passed requirement needs at least one evidence artifact')
    if payload['kind'] == 'manual' and payload['status'] == 'passed' and not payload.get('verifier'):
        raise InvalidInput('manual_verifier', 'manual evidence names its verifier')
    stored = [copy_artifact(Path(path), ctx.run_dir, 'evidence', _roots(ctx, state)) for path in paths]
    entry = {'requirement_id': req['id'], 'status': payload['status'], 'kind': payload['kind'],
             'explanation': payload['explanation'], 'artifacts': stored, 'verifier': payload.get('verifier'),
             'snapshot': bind['snapshot'], 'contract_hash': bind['contract_hash'], 'policy_hash': bind['policy_hash'],
             'recorded_at': ctx.at}
    state.setdefault('acceptance', []).append(entry)
    _supersede_waivers(state, f'requirement:{req["id"]}', ctx.at)
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
    elif target.startswith('requirement:'):
        known = {item['id'] for item in contract.current_contract(state)['requirements']}
        if target[len('requirement:'):] not in known:
            raise InvalidInput('unknown_requirement', f'no requirement {target[len("requirement:"):]}')
    else:
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
    findings = [f for f in payload.get('findings') or [] if isinstance(f, dict)]
    named = {str(f['file']) for f in findings if f.get('file')}
    work = [t for t in state['tasks'] if t.get('kind') not in ('review', 'probe')]
    writers = [t for t in work if t.get('writes')]
    # The repair owns the files its findings name, plus the scope of every writer
    # that owns one of them; findings that name no file reach every writer's scope.
    scope = [w for w in writers if any(results.owns(w.get('files'), path) for path in named)]
    if not scope or len(named) < len(findings):
        scope = writers
    if scope:
        template = scope[-1]
        files = [] if any(not w.get('files') for w in scope) else sorted({p for w in scope for p in w['files']} | named)
    else:
        # No writer to copy: use the run's work role and the union of the planned tasks' files.
        template = {'executor': 'self',
                    'role': state['policy'].get('work_role') or next(iter(state.get('roles') or {}), None)}
        files = [] if any(not t.get('files') for t in work) else sorted({f for t in work for f in t['files']} | named)
    number = sum(1 for t in state['tasks'] if t['id'].startswith('repair-')) + 1
    task = {'id': f'repair-{number}', 'kind': 'code', 'purpose': f'repair after {stage}: {payload.get("reason", "")}'.strip(),
            'role': template.get('role'), 'executor': template.get('executor', 'self'), 'writes': True,
            'depends_on': [], 'requirement_ids': [], 'acceptance': [], 'constraints': [],
            'files': files, 'status': 'pending', 'rounds': [],
            'next_round': {'purpose': 'repair', 'context': {'findings': payload.get('findings') or []}},
            'target': template.get('target') if template.get('pinned_target') else None,
            'pinned_target': bool(template.get('pinned_target'))}
    state['tasks'].append(task)
    state['execution']['serial_base'] = _head(state)
    state['execution']['self_base'] = snapshot.baseline(state['repo']['worktree'])
    transitions.apply(state, 'executing', label, ctx.at)
    return {'repair_task': task['id'], 'stage': stage, 'used': used + 1, 'limit': state['policy']['repair_limit']}


def _common_dir(path) -> Path:
    return (Path(path) / snapshot.git(path, 'rev-parse', '--git-common-dir').strip()).resolve()


def _created_worktree(ctx, state, payload):
    """A worktree is run-owned only when it is the fresh result of a create_worktree
    action that `next` offered: same path, branch and name, a worktree of this
    repository, and nothing in it beyond what `git worktree add` checks out."""
    try:
        permitted = _permitted(ctx, state, 'create_worktree', payload)
    except InvalidInput as exc:
        raise InvalidInput('action_id', 'record a worktree with the action_id of the create_worktree action '
                                        'that made it') from exc
    args = permitted['args']
    for key in ('path', 'name', 'branch'):
        if payload.get(key) not in (None, args.get(key)):
            raise InvalidInput('resource_mismatch', f'recorded {key} differs from the create_worktree action',
                               {'planned': args.get(key), 'recorded': payload.get(key)})
    path = Path(args['path'])
    try:
        top = snapshot.toplevel(path)
    except InvalidInput as exc:
        raise InvalidInput('worktree_missing', f'{path} is not a git worktree; run the action argv first') from exc
    path = path.resolve()
    if top != path:
        raise InvalidInput('worktree_missing', f'{path} is not the top of a git worktree')
    repo = state['repo']['worktree']
    if _common_dir(path) != _common_dir(repo) or path == Path(repo).resolve():
        raise Prohibited('foreign_worktree', f'{path} is not a new worktree of {repo}')
    if any(item.get('path') == str(path) for item in state.get('resources', []) if item['kind'] == 'worktree'):
        raise Prohibited('resource_exists', f'{path} is already recorded')
    if snapshot.git(path, 'status', '--porcelain', '--untracked-files=all').strip():
        raise Prohibited('worktree_not_fresh', f'{path} already holds changes or files; a pre-existing worktree '
                                               'is never adopted as run-owned')
    if args.get('branch'):
        reflog = snapshot.git(repo, 'reflog', 'show', '--format=%H', 'refs/heads/' + args['branch'], check=False)
        if len([line for line in reflog.splitlines() if line]) > 1:
            raise Prohibited('worktree_not_fresh', f'branch {args["branch"]} has history from before this action')
    probe = permitted['task_id'] if str(permitted['task_id']).startswith('probe-') and not engine.task_by_id(
        state, permitted['task_id']) else None
    return path, args['name'], args.get('branch'), permitted['task_id'], probe, permitted['id']


def rec_resource(ctx, state, payload):
    _require(payload, 'kind')
    kind = payload['kind']
    rid = f'R-{uuid.uuid4().hex[:8]}'
    repo = state['repo']['worktree']
    created = []
    if kind == 'worktree':
        path, name, branch, task_id, probe, action_id = _created_worktree(ctx, state, payload)
        entry = {'id': rid, 'kind': 'worktree', 'name': name, 'path': str(path), 'branch': branch,
                 'task_id': task_id, 'status': 'live', 'created_at': ctx.at, 'created_by': action_id,
                 'identity': resources.worktree_identity(path),
                 # Only a probe worktree, which holds nothing but the probe marker, is force-removed.
                 'cleanup_argv': ['git', '-C', repo, 'worktree', 'remove', *(['--force'] if probe else []), str(path)]}
        created.append(entry)
        if branch:
            created.append({'id': f'R-{uuid.uuid4().hex[:8]}', 'kind': 'branch', 'name': name,
                            'branch': branch, 'repo': repo, 'status': 'live', 'created_at': ctx.at,
                            'identity': resources.branch_identity(repo, branch),
                            'cleanup_argv': ['git', '-C', repo, 'branch', '-d', branch]})
        if probe:
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
                'worktree': str(path),
                'probe': {'provider': provider, 'nonce': nonce, 'marker': str(path / '.t3-probe-marker')}})
        else:
            for task in state['tasks']:
                if task['id'] == task_id:
                    task['worktree'], task['branch'] = str(path), branch
                    task['base_sha'] = snapshot.git(path, 'rev-parse', 'HEAD').strip()
    elif kind == 'process':
        _require(payload, 'pid')
        if not isinstance(payload['pid'], int) or isinstance(payload['pid'], bool) or payload['pid'] <= 1:
            raise InvalidInput('pid', 'pid must be a positive integer', {'pid': payload['pid']})
        fingerprint = resources.fingerprint(payload['pid'])
        if not fingerprint:
            raise InvalidInput('process_missing', f'no process {payload["pid"]}')
        created.append({'id': rid, 'kind': 'process', 'pid': int(payload['pid']), 'fingerprint': fingerprint,
                        'purpose': payload.get('purpose'), 'status': 'live', 'created_at': ctx.at,
                        'cleanup_argv': ['kill', str(int(payload['pid']))]})
    else:
        raise InvalidInput('resource_kind', 'resource kind is worktree or process')
    state.setdefault('resources', []).extend(created)
    return {'resources': created}


def rec_cleanup(ctx, state, payload):
    _require(payload, 'resource_id')
    item = next((r for r in state.get('resources', []) if r['id'] == payload['resource_id']), None)
    if item is None:
        raise InvalidInput('unknown_resource', f'no resource {payload["resource_id"]}')
    if resources.identity(item) == 'replaced':
        item['status'] = 'gone'
        item['note'] = ('pid now belongs to an unrelated process; nothing was signalled' if item['kind'] == 'process'
                        else f'{item["kind"]} was removed and replaced by an unrelated one; nothing was touched')
        return {'resource': item['id'], 'status': 'gone'}
    still = resources.live(item)
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
    for task_id in ids:
        base = _task(state, task_id).get('base_sha')
        tip = snapshot.git(repo, 'rev-parse', '--verify', branch, check=False).strip()
        if base and tip == base:
            raise Prohibited('nothing_integrated', f'{branch} has no commits beyond its baseline; the child did not commit')
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
    observation = {'kind': payload['kind'], 'url': payload['url'], 'number': payload.get('number'),
                   'state': str(payload['state']).lower(),
                   'head_sha': payload['head_sha'], 'observed_at': ctx.at, 'source_argv': payload.get('argv')}
    receipt = (remote.get('receipts') or [None])[-1]
    if receipt is None:
        raise Prohibited('receipt_missing', 'record the publish receipt before observing it')
    if not acceptance.same_remote(observation, receipt):
        raise InvalidInput('remote_mismatch', 'the observation names a different PR from the recorded receipt',
                           {'receipt': receipt.get('url'), 'observed': payload['url']})
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
    if any(existing['id'] == item['id'] and existing['status'] == 'active' for existing in state.get('blockers', [])):
        return {'blocker': item, 'note': 'already recorded'}
    state.setdefault('blockers', []).append(item)
    if state['phase'] != 'blocked':
        transitions.apply(state, 'blocked', item['reason'], ctx.at)
    return {'blocker': item}


def rec_note(ctx, state, payload):
    _require(payload, 'key', 'text')
    state.setdefault('notes', {})[str(payload['key'])[:64]] = str(payload['text'])[:4000]
    return {'note': payload['key']}


POLICY_EDITABLE = ('checks', 'review', 'model_preferences', 'brief_notes', 'work_role')


def _check_policy(state, changes):
    """A policy record may add obligations or adjust preferences; it may never
    weaken an obligation the run already carries. Fixed targets (role_overrides)
    come only from the plan or repository policy at init: selection reports them as
    repository policy, so a mid-run record could otherwise retarget an independent role."""
    for forbidden in ('repair_limit', 'budget_seconds'):
        if forbidden in changes:
            raise Prohibited('operator_only', f'{forbidden} changes through unblock decisions only')
    fixed = sorted(set(changes) - set(POLICY_EDITABLE))
    if fixed:
        raise Prohibited('policy_fixed', f'{fixed} are fixed when the run is created', {'keys': fixed})
    if 'checks' in changes:
        checks = changes['checks']
        if not isinstance(checks, list) or not all(isinstance(c, dict) and c.get('name') for c in checks):
            raise InvalidInput('record_fields', 'checks is a list of named checks')
        for check in checks:
            if not isinstance(check.get('argv'), list) or not check['argv'] or not all(isinstance(a, str) and a for a in check['argv']):
                raise InvalidInput('check_argv', f'check {check.get("name")} needs a literal argv array')
        names = [c['name'] for c in checks]
        if len(names) != len(set(names)):
            raise InvalidInput('duplicate_check', 'check names must be unique',
                               {'names': sorted({n for n in names if names.count(n) > 1})})
        new = {c['name']: dict(c, required=c.get('required', True) is not False) for c in checks}
        for old in state['policy'].get('checks', []):
            kept = new.get(old['name'])
            if old.get('required', True) and (
                    kept is None or not kept['required']
                    or any(kept.get(key) != old.get(key) for key in ('argv', 'cwd', 'repository_required'))):
                raise Prohibited('policy_weakening', f'required check {old["name"]} cannot be removed, relaxed or changed')
        for check in new.values():
            if check.get('repository_required') and not any(
                    old['name'] == check['name'] and old.get('repository_required') for old in state['policy'].get('checks', [])):
                raise Prohibited('policy_fixed', 'repository-required checks come only from repository policy')
        changes = dict(changes, checks=list(new.values()))
    if 'review' in changes:
        old = state['policy'].get('review') or {}
        review = dict(old, **(changes['review'] or {}))
        if old.get('required') and not review.get('required'):
            raise Prohibited('policy_weakening', 'a required review cannot be made optional')
        if not old.get('waivable', True) and review.get('waivable', True):
            raise Prohibited('policy_weakening', 'an unwaivable review cannot be made waivable')
        if review.get('required') and review.get('role') not in (state.get('roles') or {}):
            raise InvalidInput('unknown_role', f'review role {review.get("role")!r} is not configured')
        changes = dict(changes, review=review)
    if changes.get('work_role') is not None and changes['work_role'] not in (state.get('roles') or {}):
        raise InvalidInput('unknown_role', f'work_role {changes["work_role"]} is not a configured role')
    return changes


def rec_policy(ctx, state, payload):
    changes = payload.get('policy')
    if not isinstance(changes, dict):
        raise InvalidInput('record_fields', 'policy record carries a policy object')
    state['policy'].update(_check_policy(state, changes))
    return {'policy_hash': acceptance.policy_hash(state)}


def _fail(ctx, state, reason):
    """Failure is terminal, so owned children are stopped first: with any still
    live, the run goes through cancelling and fails once every stop is confirmed."""
    still = engine.live_host_tasks(state) + engine.uncertain_requests(state)
    if not still:
        transitions.apply(state, 'failed', reason, ctx.at)
        return {'phase': 'failed'}
    if state['phase'] != 'cancelling':
        transitions.apply(state, 'cancelling', f'stopping owned work before failing: {reason}', ctx.at)
        state['cancellation'] = {'requested_at': ctx.at, 'reason': reason, 'outcomes': []}
    state['cancellation'].update(then='failed', fail_reason=reason)
    return {'phase': 'cancelling', 'then': 'failed', 'task_ids': still,
            'note': 'delegated work may still be running; stop it (next offers the steps), then the run fails'}


def rec_fail(ctx, state, payload):
    _require(payload, 'reason')
    return _fail(ctx, state, payload['reason'])


HANDLERS = {
    'capabilities': rec_capabilities, 'transition': rec_transition, 'dispatch': rec_dispatch,
    'observation': rec_observation, 'result': rec_result, 'cancel': rec_cancel, 'check': rec_check,
    'acceptance': rec_acceptance, 'waiver': rec_waiver, 'repair': rec_repair, 'resource': rec_resource,
    'cleanup': rec_cleanup, 'integration': rec_integration,
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
    if state['phase'] == 'blocked' and kind not in ('cleanup', 'note', 'block', 'transition', 'observation', 'cancel',
                                                    'dispatch'):
        raise Prohibited('blocked', 'run is blocked; resolve it with the blocker resume command first')
    result = HANDLERS[kind](ctx, state, payload)
    transitions.event(state, f'record:{kind}', str(result)[:300], ctx.at)
    return result
