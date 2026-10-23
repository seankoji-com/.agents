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


def handle_wake(host, state_path, now, wake):
    """Reconcile one delivered wake and reserve each resulting action."""
    state = _state(state_path)
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
        if action.get('kind') not in ('dispatch-fixer', 'merge'):
            continue
        receipt = host.dispatch(action, now)
        if receipt.get('status', 'accepted') != 'accepted':
            dispatched.append({'action': action, 'status': receipt.get('status'),
                               'reason': receipt.get('reason')})
            continue
        try:
            recorded = continuous.cmd_dispatch(_namespace(
                state=str(state_path), now=now, pr=action['pr'],
                request_id=action.get('request_id'),
                kind='fixer' if action['kind'] == 'dispatch-fixer' else 'merge',
                host_task_id=receipt.get('host_task_id'), head=action.get('head'),
                attempt=action.get('attempt'),
                review_triage=bool(action.get('review_triage'))))
        except continuous.ContinuousError as exc:
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
    return [handle_wake(host, state_path, now, wake) for wake in host.due(now)]
