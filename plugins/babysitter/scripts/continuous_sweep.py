#!/usr/bin/env python3
"""Reference host adapter for one continuous babysitter sweep (issue #94).

The coordinator is an agent, so the live mapping from this contract to T3 tools is
the agent's job: ``schedule_task`` for ``create_schedule``, ``delete_scheduled_task``
for ``delete_schedule``, an arriving scheduled-task run for ``due``, ``list-prs.sh``
for ``discover`` and ``delegate_task`` for ``dispatch``. This module fixes the order
and the state transitions so a fake host can prove the causal path offline: a timer
advance delivers a wake, the wake is reconciled through ``continuous.py``, and any
resulting action is reserved and recorded before it is reported as started.

A host object supplies:

    create_schedule(request) -> {'schedule_id', 'next_run_at', 'stop'}
    delete_schedule(stop) -> {'verified': bool}
    due(now) -> [{'wake_id', 'kind', 'delivery_id'}]
    discover(scope, now) -> observation dict accepted by continuous.py observe
    dispatch(action, now) -> {'host_task_id': str}
        or {'helper_result': {'request_id': str, 'returncode': int, 'stdout': str}}
        for synchronous update-only execution

Nothing here calls a network, a model or a scheduler by itself.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path


def _continuous():
    path = Path(__file__).with_name('continuous.py')
    spec = importlib.util.spec_from_file_location('babysitter_continuous', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


continuous = _continuous()


def _namespace(**values):
    return argparse.Namespace(**values)


def _state(path):
    return continuous.read_state(path)


def arm(host, state_path, now):
    """Create the one host schedule this run is allowed to own, then record it."""
    plan = continuous.cmd_schedule_plan(_namespace(state=str(state_path)))
    if plan.get('status') != 'plan':
        return plan
    receipt = host.create_schedule(plan['request'])
    try:
        recorded = continuous.cmd_schedule_record(_namespace(
            state=str(state_path), now=now, schedule_id=receipt['schedule_id'],
            next_run_at=receipt['next_run_at']))
    except Exception:
        # Never leave a host schedule the run state does not know about.
        host.delete_schedule(receipt.get('stop') or {
            'tool': 'delete_scheduled_task',
            'arguments': {'scheduledTaskId': receipt['schedule_id']}})
        raise
    return {'status': 'armed', 'plan': plan, 'schedule': recorded}


def _close_dispatch(state_path, now, action, status, reason, host_task_id=None):
    """Close a reservation whose host launch failed or was refused."""
    try:
        return continuous.cmd_receipt(_namespace(
            state=str(state_path), now=now, pr=action['pr'],
            request_id=action.get('request_id'),
            kind='fixer' if action['kind'] == 'dispatch-fixer' else action['kind'],
            status=status, reason=reason, host_task_id=host_task_id,
            head=action.get('head'), result=None))
    except continuous.ContinuousError as exc:
        return {'status': 'reconcile-error', 'reason': str(exc)}


def handle_wake(host, state_path, now, wake):
    """Reconcile one delivered wake and reserve each resulting action.

    Order is reserve -> host side effect -> attach handle. The reservation is the
    transaction that stops a competing fixer or merge from racing the launch; the host
    is never called before it exists. A lost response keeps the reservation held until
    host reconciliation proves refusal or identifies the launched task.
    """
    with continuous.locked_state(state_path) as state:
        continuous.require_current_package(state)
    if (wake.get('kind') or 'schedule') == 'schedule' and (
            state.get('cancelled') or state['scheduler']['mode'] != 'scheduled'
            or state['scheduler'].get('stopped')):
        report = continuous.scheduler_report(state, continuous.parse_time(now))
        return {'wake': wake, 'result': {'status': 'scheduled-continuation-blocked',
                'actions': [], 'scheduler_stop': state['scheduler'].get('stop'),
                'scheduler': report, 'coverage': report['coverage'], 'next_wake_at': None},
                'dispatched': []}
    observation = host.discover(state['scope'], now)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as stream:
        json.dump(observation, stream)
        observation_path = stream.name
    try:
        result = continuous.cmd_observe(_namespace(
            state=str(state_path), now=now, observation=observation_path,
            wake_id=wake.get('wake_id'), wake_kind=wake.get('kind') or 'schedule'))
    finally:
        Path(observation_path).unlink(missing_ok=True)
    dispatched = []
    if result.get('status') == 'duplicate':
        return {'wake': wake, 'result': result, 'dispatched': []}
    for action in result.get('actions', []):
        if action.get('kind') not in ('dispatch-fixer', 'merge', 'update-branch'):
            continue
        kind = 'fixer' if action['kind'] == 'dispatch-fixer' else action['kind']
        try:
            reservation = continuous.cmd_dispatch(_namespace(
                state=str(state_path), now=now, pr=action['pr'],
                request_id=action.get('request_id'), kind=kind,
                host_task_id=None, head=action.get('head'),
                attempt=action.get('attempt'),
                review_triage=bool(action.get('review_triage')), reserve=True))
        except continuous.ContinuousError as exc:
            # Nothing was launched, so no writer raced this action.
            dispatched.append({'action': action, 'status': 'reserve-error',
                               'reason': str(exc)})
            continue
        if reservation.get('status') == 'already-reserved':
            # An outstanding reservation means a previous launch was never reconciled.
            # Replaying it would duplicate the writer; hold and report it instead.
            dispatched.append({'action': action, 'status': 'reservation-held',
                               'dispatch': reservation.get('dispatch')})
            continue
        if reservation.get('status') != 'recorded':
            dispatched.append({'action': action, 'status': reservation.get('status'),
                               'dispatch': reservation.get('dispatch')})
            continue
        try:
            receipt = host.dispatch(action, now)
        except Exception as exc:  # noqa: BLE001 - host adapters fail in many ways
            closed = _close_dispatch(
                state_path, now, action, 'uncertain',
                'host launch raised; the launch outcome is uncertain and no handle was '
                f'confirmed: {type(exc).__name__}: {exc}')
            dispatched.append({'action': action, 'status': 'launch-error',
                               'reason': f'{type(exc).__name__}: {exc}',
                               'reservation': reservation.get('status'),
                               'reconciled': closed.get('status')})
            continue
        if kind == 'update-branch' and isinstance(receipt, dict) and 'helper_result' in receipt:
            helper_result = receipt['helper_result']
            status, _ = continuous.update_helper_receipt(
                _state(state_path)['prs'][action['pr']], reservation['dispatch'], helper_result)
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as stream:
                json.dump(helper_result, stream)
                result_path = stream.name
            try:
                recorded = continuous.cmd_receipt(_namespace(
                    state=str(state_path), now=now, pr=action['pr'],
                    request_id=action['request_id'], kind=kind, status=status,
                    head=action['head'], host_task_id=None, result=result_path, reason=None))
            finally:
                Path(result_path).unlink(missing_ok=True)
            dispatched.append({'action': action, 'status': status,
                               'recorded': recorded['status']})
            continue
        if not isinstance(receipt, dict) or receipt.get('status', 'accepted') != 'accepted':
            refusal = receipt if isinstance(receipt, dict) else {}
            # Only an explicit rejection confirms that no work was launched.
            status = 'rejected' if refusal.get('status') == 'rejected' else 'uncertain'
            closed = _close_dispatch(state_path, now, action, status,
                                     refusal.get('reason') or 'host refused the dispatch')
            dispatched.append({'action': action, 'status': refusal.get('status'),
                               'reason': refusal.get('reason'),
                               'reservation': reservation.get('status'),
                               'reconciled': closed.get('status')})
            continue
        if not receipt.get('host_task_id'):
            _close_dispatch(state_path, now, action, 'uncertain',
                            'host returned acceptance without a task handle')
            dispatched.append({'action': action, 'status': 'launch-uncertain'})
            continue
        try:
            recorded = continuous.cmd_dispatch(_namespace(
                state=str(state_path), now=now, pr=action['pr'],
                request_id=action.get('request_id'), kind=kind,
                host_task_id=receipt.get('host_task_id'), head=action.get('head'),
                attempt=action.get('attempt'),
                review_triage=bool(action.get('review_triage')), reserve=False))
        except continuous.ContinuousError as exc:
            # The reservation still excludes competing writers; only the handle is
            # missing, and it can be attached by a later retry.
            dispatched.append({'action': action, 'status': 'record-error',
                               'host_task_id': receipt.get('host_task_id'),
                               'reason': str(exc)})
            continue
        dispatched.append({'action': action, 'status': 'dispatched',
                           'host_task_id': receipt.get('host_task_id'),
                           'recorded': recorded.get('status')})
    return {'wake': wake, 'result': result, 'dispatched': dispatched}


def tick(host, state_path, now):
    """Deliver every wake the host says is due at ``now``."""
    with continuous.locked_state(state_path) as state:
        continuous.require_current_package(state)
    return [handle_wake(host, state_path, now, wake) for wake in host.due(now)]
