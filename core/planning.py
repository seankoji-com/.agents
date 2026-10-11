"""Build a new run record from a plan, plugin defaults and repository policy.

Precedence: plugin defaults < plan < repository policy file
(<repo>/.t3-plugins/<plugin>.json). Repository policy can name a fixed target
for a role, mark checks repository-required and forbid waivers; the plan cannot
loosen those."""
from __future__ import annotations

import copy
from pathlib import Path

from . import contract, review as review_rules, schema, snapshot
from .errors import InvalidInput
from .fsutil import read_json
from .store import now_iso


def deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value) if key in merged else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


def repository_policy(worktree: Path, plugin: str) -> dict:
    path = Path(worktree) / '.t3-plugins' / f'{plugin}.json'
    if not path.is_file():
        return {}
    value = read_json(path)
    schema.validate(value, 'repository-policy', 'repository_policy_invalid')
    value['_source'] = str(path)
    return value


TASK_DEFAULTS = {'kind': 'code', 'depends_on': [], 'requirement_ids': [], 'acceptance': [], 'constraints': [],
                 'files': [], 'expected_output': '', 'verification': '', 'writes': True}


def _tasks(plan_tasks, mode, req_ids, default_role):
    tasks = []
    for raw in plan_tasks:
        task = dict(copy.deepcopy(TASK_DEFAULTS), **copy.deepcopy(raw))
        task.setdefault('executor', 'delegate' if mode == 'delegated' else 'self')
        task.setdefault('role', default_role)
        if task['kind'] in ('review', 'probe') or task['id'].startswith(('review-', 'probe-', 'repair-')):
            raise InvalidInput('reserved_task', f'task {task["id"]} uses a reserved kind or prefix')
        if task['kind'] == 'read':
            task['writes'] = False
        unknown = set(task['requirement_ids']) - req_ids
        if unknown:
            raise InvalidInput('task_requirements', f'task {task["id"]} names unknown requirements {sorted(unknown)}')
        task.update(status='pending', rounds=[], worktree=None, branch=None, result=None,
                    correction_used=False, next_round=None, pinned_target=bool(task.get('target')))
        tasks.append(task)
    ids = [task['id'] for task in tasks]
    if len(ids) != len(set(ids)):
        raise InvalidInput('duplicate_task', 'task IDs must be unique')
    known = set(ids)
    for task in tasks:
        missing = set(task['depends_on']) - known
        if missing:
            raise InvalidInput('task_dependency', f'{task["id"]} depends on unknown {sorted(missing)}')
    seen, visiting = set(), set()

    def visit(task_id):
        if task_id in seen:
            return
        if task_id in visiting:
            raise InvalidInput('task_cycle', f'dependency cycle through {task_id}')
        visiting.add(task_id)
        for dep in next(t for t in tasks if t['id'] == task_id)['depends_on']:
            visit(dep)
        visiting.discard(task_id)
        seen.add(task_id)
    for task_id in ids:
        visit(task_id)
    return tasks


def build(plan: dict, defaults: dict, *, state_root: Path, plugin: dict, clock_iso: str | None = None) -> dict:
    schema.validate(plan, 'plan', 'plan_invalid')
    if defaults:
        schema.validate(defaults, 'defaults', 'defaults_invalid')
    worktree = snapshot.toplevel(Path(plan.get('repo', {}).get('worktree') or '.'))
    repo_policy = repository_policy(worktree, plugin['name'])
    merged = deep_merge(deep_merge(defaults or {}, {k: v for k, v in plan.items() if k != 'schema_version'}),
                        {k: v for k, v in repo_policy.items() if k in ('policy', 'roles')})
    policy = merged.get('policy') or {}
    if repo_policy:
        repo_checks = [dict(check, repository_required=True, required=True)
                       for check in (repo_policy.get('policy') or {}).get('checks', [])]
        names = {check['name'] for check in repo_checks}
        policy['checks'] = repo_checks + [c for c in (merged.get('policy') or {}).get('checks', []) if c['name'] not in names]
        policy['repository_policy'] = repo_policy['_source']
    if 'checks' in policy:
        names = [c['name'] for c in policy['checks'] if isinstance(c, dict) and 'name' in c]
        if len(names) != len(set(names)):
            raise InvalidInput('duplicate_check', 'check names must be unique',
                               {'names': sorted({n for n in names if names.count(n) > 1})})
    base_ref = (plan.get('repo') or {}).get('base_ref') or 'HEAD'
    base_sha = snapshot.git(worktree, 'rev-parse', '--verify', f'{base_ref}^{{commit}}').strip()
    source = (plan.get('brief') or {}).get('requirements_source')
    if source:
        source = str(Path(source).resolve())
        parsed = contract.load_source(Path(source))
    else:
        parsed = contract.normalise((plan.get('brief') or {}).get('requirements', []),
                                    (plan.get('brief') or {}).get('constraints', []))
    execution = merged.get('execution') or {}
    mode = execution.get('mode', 'direct')
    roles = merged.get('roles') or {}
    default_role = policy.get('work_role') or (next(iter(roles)) if roles else None)
    if default_role and default_role not in roles:
        raise InvalidInput('unknown_role', f'work_role {default_role} is not a configured role')
    req_ids = {req['id'] for req in parsed['requirements']}
    plan_tasks = merged.get('tasks') or []
    if not plan_tasks:
        plan_tasks = [{'id': 'main', 'purpose': (plan.get('brief') or {}).get('text', 'implement the brief')[:200],
                       'requirement_ids': sorted(req_ids)}]
    tasks = _tasks(plan_tasks, mode, req_ids, default_role)
    resolvable = set(roles) | set(policy.get('role_overrides') or {})
    for task in tasks:
        if task['executor'] == 'delegate' and not task.get('target') and task['role'] not in resolvable:
            raise InvalidInput('unknown_role', f'delegated task {task["id"]} names no configured role '
                                               f'({task["role"]!r}); configure roles or set work_role',
                               {'task': task['id'], 'role': task['role']})
    review = dict({'required': False, 'role': None, 'waivable': True}, **(policy.get('review') or {}))
    review_rules.perspectives(review)
    if review['required'] and review['role'] not in roles:
        raise InvalidInput('unknown_role', f'review role {review["role"]!r} is not configured')
    budget = int(policy.get('budget_seconds', 14400))
    if not 0 < budget <= 86400:
        raise InvalidInput('budget', 'budget_seconds must be within 1..86400')
    concurrency = int(execution.get('concurrency', 4))
    if not 1 <= concurrency <= 10:
        raise InvalidInput('concurrency', 'concurrency must be within 1..10')
    at = clock_iso or now_iso()
    authorization = dict({'local': [], 'remote': [], 'endstate': 'local', 'evidence': ''}, **(plan.get('authorization') or {}))
    host = dict({'kind': 't3', 'parent_thread_id': None, 'provider_instance_id': None, 'model': None}, **(plan.get('host') or {}))
    state = {
        'created_at': at, 'updated_at': at,
        'plugin': plugin,
        'labels': merged.get('labels') or {},
        'phase': 'planned', 'resume_phase': None,
        'repo': {'worktree': str(worktree), 'base_ref': base_ref, 'base_sha': base_sha,
                 'branch': snapshot.git(worktree, 'rev-parse', '--abbrev-ref', 'HEAD', check=False).strip() or None},
        'brief': {'text': (plan.get('brief') or {}).get('text', ''), 'requirements': parsed['requirements'],
                  'constraints': parsed['constraints'], 'requirements_source': source,
                  'contract_hash': contract.contract_hash(parsed)},
        'authorization': authorization,
        'execution': {'mode': mode, 'isolation': execution.get('isolation'), 'concurrency': concurrency},
        'host': host,
        'capabilities': None,
        'roles': roles,
        'policy': {
            'checks': policy.get('checks', []),
            'review': review,
            'repair_limit': int(policy.get('repair_limit', 2)),
            'worktree_root': str(Path(policy.get('worktree_root') or (Path(state_root) / 'worktrees')).expanduser()),
            'role_overrides': policy.get('role_overrides') or {},
            'model_preferences': policy.get('model_preferences') or {},
            'brief_notes': policy.get('brief_notes'),
            'evidence_roots': policy.get('evidence_roots') or [],
            'work_role': default_role,
            **({'repository_policy': policy['repository_policy']} if policy.get('repository_policy') else {}),
        },
        'probes': {},
        'tasks': tasks,
        'checks': [], 'acceptance': [], 'reviews': [], 'waivers': [],
        'remote': {'receipts': [], 'observations': []},
        'resources': [], 'integrations': [], 'blockers': [],
        'cancellation': None,
        'counters': {'repairs': {}, 'review_rounds': 0},
        'budget': {'seconds': budget, 'spent_seconds': 0},
        'notes': {}, 'readiness': None,
        'events': [{'at': at, 'kind': 'init', 'summary': f'run created in {mode} mode'}],
    }
    for check in state['policy']['checks']:
        if not isinstance(check.get('argv'), list) or not check['argv'] or not all(isinstance(a, str) and a for a in check['argv']):
            raise InvalidInput('check_argv', f'check {check.get("name")} needs a literal argv array')
        check.setdefault('required', True)
    return state
