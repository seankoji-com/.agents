"""Resolve a role's target from an explicit fallback chain and the live catalog.

Chain entries:
  {"select": "inherit"}                         the parent's provider/model
  {"select": "fixed", "providerInstanceId", "model", "options"?}
  {"select": "catalog", "exclude_roles": [...]} first available catalog provider
                                                 not used by those roles
  {"select": "same_provider", "of_role": name}  a fresh child on that role's target

A candidate is skipped only when it is unavailable (absent from the catalog,
cannot run child tasks, or recorded unavailable for this round). Verdicts never
advance the chain."""
from __future__ import annotations

from .errors import InvalidInput


def _provider(caps: dict, provider_id: str):
    for item in (caps or {}).get('providers', []):
        if item.get('id') == provider_id:
            return item
    return None


def _target_key(target: dict) -> str:
    return f'{target.get("providerInstanceId")}/{target.get("model")}'


def _inherit(caps, host):
    inherited = (caps or {}).get('inherited') or {}
    provider = inherited.get('providerInstanceId') or host.get('provider_instance_id')
    model = inherited.get('model') or host.get('model')
    if not provider:
        return None
    return {'providerInstanceId': provider, 'model': model, 'options': {}}


def actual_providers(state: dict, roles) -> list:
    """Providers that actually wrote this run's changes under the given roles:
    the parent for self-executed work, each dispatched target for delegated work."""
    found = []
    host = (state.get('host') or {}).get('provider_instance_id')
    for task in state.get('tasks', []):
        if not task.get('writes') or task.get('kind') in ('review', 'probe') or task.get('role') not in roles:
            continue
        if task.get('executor') == 'self':
            if host:
                found.append(host)
            continue
        for item in task.get('rounds') or []:
            if item.get('task_id') and (item.get('target') or {}).get('providerInstanceId'):
                found.append(item['target']['providerInstanceId'])
        if (task.get('target') or {}).get('providerInstanceId'):
            found.append(task['target']['providerInstanceId'])
    return sorted(set(found))


def candidates(state: dict, role: str, depth: int = 0) -> list:
    """Ordered (target, why) pairs for a role, before availability filtering."""
    if depth > 4:
        raise InvalidInput('role_cycle', f'role chain for {role} refers back to itself')
    policy_fixed = ((state.get('policy') or {}).get('role_overrides') or {}).get(role)
    spec = (state.get('roles') or {}).get(role)
    if spec is None and not policy_fixed:
        raise InvalidInput('unknown_role', f'no role named {role} in this run', {'role': role})
    chain = [dict(policy_fixed, select='fixed', why='repository policy names this target')] if policy_fixed else spec['chain']
    caps = state.get('capabilities') or {}
    host = state.get('host') or {}
    result = []
    for index, entry in enumerate(chain):
        start = len(result)
        kind = entry.get('select')
        why = entry.get('why') or f'{role} chain entry {index + 1} ({kind})'
        if kind == 'inherit':
            target = _inherit(caps, host)
            if target:
                result.append((target, why))
        elif kind == 'fixed':
            result.append(({'providerInstanceId': entry['providerInstanceId'], 'model': entry.get('model'),
                            'options': entry.get('options') or {}}, why))
        elif kind == 'same_provider':
            for target, _ in candidates(state, entry['of_role'], depth + 1)[:1]:
                result.append((dict(target), why + f'; fresh isolated child on the {entry["of_role"]} target'))
        elif kind == 'catalog':
            excluded = set(actual_providers(state, entry.get('exclude_roles', [])))
            for other in entry.get('exclude_roles', []):
                for target, _ in candidates(state, other, depth + 1)[:1]:
                    excluded.add(target['providerInstanceId'])
            preferences = (state.get('policy') or {}).get('model_preferences') or {}
            for provider in caps.get('providers', []):
                if provider['id'] in excluded or not provider.get('models'):
                    continue
                model = preferences.get(provider['id'])
                if model not in provider['models']:
                    model = provider['models'][0]
                result.append(({'providerInstanceId': provider['id'], 'model': model, 'options': {}},
                               why + f'; first catalog provider other than {sorted(excluded)}'))
        else:
            raise InvalidInput('chain_entry', f'unknown chain entry {kind!r} for {role}')
        if entry.get('runtimeMode'):
            # An explicit mode (from the routing config) wins for every selector,
            # including a same_provider target copied from another role.
            for target, _ in result[start:]:
                target['runtimeMode'] = entry['runtimeMode']
    return result


def availability(state: dict, target: dict) -> tuple[bool, str]:
    caps = state.get('capabilities')
    if not caps:
        return False, 'capabilities not discovered'
    if not caps.get('available'):
        return False, caps.get('reason') or 'orchestration unavailable'
    provider = _provider(caps, target['providerInstanceId'])
    if provider is None:
        return False, f'{target["providerInstanceId"]} is not in the live catalog'
    if not provider.get('available'):
        return False, f'{target["providerInstanceId"]} cannot run child tasks: ' + (
            ', '.join(provider.get('unavailable_reasons') or ['unavailable']))
    if target.get('model') and target['model'] not in provider.get('models', []):
        return False, f'model {target["model"]} is not advertised by {target["providerInstanceId"]}'
    return True, 'available in the live catalog'


def resolve(state: dict, role: str, skipped=()) -> dict:
    """First available candidate. `skipped` holds target keys recorded unavailable
    for the current round. Returns {target, why, considered} or {target: None, ...}."""
    considered = []
    seen = set()
    for target, why in candidates(state, role):
        key = _target_key(target)
        if key in seen:
            continue
        seen.add(key)
        if key in skipped:
            considered.append({'target': target, 'skipped': 'recorded unavailable this round'})
            continue
        ok, detail = availability(state, target)
        if ok:
            return {'target': target, 'why': f'{why}; {detail}', 'considered': considered}
        considered.append({'target': target, 'skipped': detail})
    return {'target': None, 'why': 'no available candidate', 'considered': considered}


def key(target: dict) -> str:
    return _target_key(target)
