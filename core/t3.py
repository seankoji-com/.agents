"""T3 Code orchestration adapter: builds tool calls and normalises responses.

Tool names come from the pinned orchestrator doc
(docs/orchestration-v2/orchestrator-mcp-server.md) and were confirmed live; see
plugins/*/references/t3-adapter.md. Harness prefixes such as `mcp__t3-code__`
vary, so callers match tools by these base names. This module never calls T3."""
from __future__ import annotations

from .errors import InvalidInput

HOST_ROLES = ('implementation', 'research', 'review', 'design', 'test', 'general')
TERMINAL_OK = {'completed', 'succeeded', 'success', 'done'}
TERMINAL_STOPPED = {'interrupted', 'cancelled', 'canceled', 'stopped', 'aborted'}
TERMINAL_FAILED = {'failed', 'error', 'errored'}
FEATURES_FOR_DELEGATION = ('appOwnedSubagents', 'cancellation')


def capabilities_call() -> dict:
    return {'tool': 'orchestrator_capabilities', 'arguments': {}}


def delegate_call(*, brief: str, title: str, role: str, client_request_id: str, target: dict | None,
                  mode: str = 'async') -> dict:
    if role not in HOST_ROLES:
        raise InvalidInput('host_role', f'T3 role must be one of {HOST_ROLES}', {'role': role})
    arguments = {'task': brief, 'title': title[:120], 'role': role, 'mode': mode,
                 'clientRequestId': client_request_id}
    if target:
        arguments['target'] = {key: target[key] for key in ('providerInstanceId', 'model', 'options')
                               if target.get(key) not in (None, {}, [])}
    return {'tool': 'delegate_task', 'arguments': arguments}


def status_call(task_id: str) -> dict:
    return {'tool': 'task_status', 'arguments': {'taskId': task_id}}


def cancel_call(task_id: str, reason: str, client_request_id: str) -> dict:
    return {'tool': 'task_cancel', 'arguments': {'taskId': task_id, 'reason': reason[:2000],
                                                   'clientRequestId': client_request_id}}


def observation(response: dict) -> dict:
    """Normalise a delegate_task or task_status response."""
    if not isinstance(response, dict):
        raise InvalidInput('host_response', 'T3 response must be a JSON object')
    task_id = response.get('taskId')
    if not task_id:
        raise InvalidInput('host_response', 'T3 response has no taskId', {'keys': sorted(response)})
    status = str(response.get('status') or '').lower() or None
    work_state = response.get('workState')
    summary = response.get('summary')
    if summary is None:
        summary = response.get('latestTerminalSummary')
    return {
        'task_id': task_id,
        'child_thread_id': response.get('childThreadId'),
        'status': status,
        'work_state': work_state,
        'has_pending_child_runs': bool(response.get('hasPendingChildRuns')),
        'wait_timed_out': bool(response.get('waitTimedOut')),
        'provider_instance_id': response.get('providerInstanceId'),
        'model': response.get('model'),
        'summary': summary,
    }


def outcome(obs: dict) -> str:
    """working | result | failed | stopped.

    `waiting_for_children` is never a final result even when the child's own
    turn finished: its nested work is still live."""
    if obs.get('work_state') != 'result_available':
        return 'working'
    status = obs.get('status') or ''
    if status in TERMINAL_OK:
        return 'result'
    if status in TERMINAL_STOPPED:
        return 'stopped'
    if status in TERMINAL_FAILED:
        return 'failed'
    return 'working'


def stop_confirmed(obs: dict) -> bool:
    return outcome(obs) in ('stopped', 'failed', 'result') and not obs.get('has_pending_child_runs')


def cancel_response(response: dict) -> dict:
    status = str((response or {}).get('status') or '').lower()
    return {'status': status, 'confirmed': status in TERMINAL_STOPPED | TERMINAL_OK | TERMINAL_FAILED
            and not (response or {}).get('hasPendingChildRuns')}


def _reason_class(text: str) -> str:
    lowered = text.lower()
    if 'auth' in lowered or 'logged in' in lowered or 'login' in lowered:
        return 'unauthenticated'
    if 'disabled' in lowered:
        return 'disabled'
    if 'not installed' in lowered or 'executable' in lowered:
        return 'not_installed'
    return 'other'


def capabilities(response: dict) -> dict:
    """Normalise orchestrator_capabilities. Missing auth, disabled providers and
    unavailable tools stay distinguishable."""
    if not isinstance(response, dict):
        raise InvalidInput('host_response', 'capabilities must be a JSON object')
    if response.get('unavailable'):
        return {'available': False, 'missing': ['orchestration_tools'],
                'reason': str(response.get('reason') or 'T3 orchestration tools are not callable'),
                'parent_thread_id': None, 'inherited': None, 'providers': [], 'features': {}}
    providers = []
    for item in response.get('providers') or []:
        reasons = [str(text) for text in item.get('constraints') or []]
        providers.append({
            'id': item.get('providerInstanceId'),
            'driver': item.get('driverKind'),
            'models': [model.get('id') for model in item.get('models') or [] if model.get('id')],
            'available': bool(item.get('canRunChildTask')),
            'cross_provider': bool(item.get('canRunCrossProviderChildTask')),
            'unavailable_reasons': sorted({_reason_class(text) for text in reasons}) if not item.get('canRunChildTask') else [],
            'constraints': reasons,
        })
    features = dict(response.get('features') or {})
    missing = [name for name in FEATURES_FOR_DELEGATION if not features.get(name)]
    if not response.get('parentThreadId'):
        missing.append('active_parent_run')
    return {
        'available': not missing,
        'missing': missing,
        'reason': None if not missing else 'required orchestration capability missing: ' + ', '.join(missing),
        'parent_thread_id': response.get('parentThreadId'),
        'inherited': {'providerInstanceId': response.get('inheritedProviderInstanceId'),
                      'model': response.get('inheritedModel')},
        'providers': providers,
        'features': features,
    }


def classify_dispatch_error(error: dict) -> str:
    """'unavailable' when the target cannot run (so a configured fallback may
    apply); 'error' otherwise."""
    code = str((error or {}).get('code') or '').lower()
    message = str((error or {}).get('message') or '').lower()
    unavailable_markers = ('capability_denied', 'unavailable', 'disabled', 'not authenticated', 'not installed',
                           'provider', 'no_active_run', 'unknown model')
    if any(marker in code or marker in message for marker in unavailable_markers):
        return 'unavailable'
    return 'error'
