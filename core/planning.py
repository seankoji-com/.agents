"""Build the evidence contract. Repository obligations take precedence."""
from __future__ import annotations

import copy
from pathlib import Path

from . import contract, review, schema, snapshot
from .errors import InvalidInput
from .fsutil import read_json
from .store import now_iso


def deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(override)


def repository_policy(worktree: Path, plugin: str) -> dict:
    path = next((p for p in (worktree / d / f'{plugin}.json' for d in ('.agents', '.t3-plugins')) if p.is_file()), None)
    if path is None:  # .agents wins; a pre-#198 .t3-plugins policy keeps binding until it is moved
        return {}
    data = read_json(path)
    schema.validate(data, 'repository-policy', 'repository_policy_invalid')
    return data


def build(plan, defaults, *, state_root, plugin, clock_iso=None):
    schema.validate(plan, 'plan', 'plan_invalid')
    schema.validate(defaults, 'defaults', 'defaults_invalid')
    worktree = snapshot.toplevel((plan.get('repo') or {}).get('worktree', '.'))
    repo_policy = repository_policy(worktree, plugin['name'])
    merged = deep_merge(deep_merge(defaults, plan), repo_policy)
    policy = merged.get('policy') or {}
    repo_checks = [dict(c, required=True, repository_required=True)
                   for c in repo_policy.get('policy', {}).get('checks', [])]
    names = {c['name'] for c in repo_checks}
    checks = repo_checks + [c for c in policy.get('checks', []) if c['name'] not in names]
    if len({c['name'] for c in checks}) != len(checks):
        raise InvalidInput('duplicate_check', 'check names must be unique')
    for check in checks:
        check.setdefault('required', True)
    review_policy = {'required': False, 'waivable': True}
    review_policy.update(policy.get('review') or {})
    review.perspectives(review_policy)
    base = plan.get('repo', {}).get('base_ref', 'HEAD')
    source = plan['brief'].get('requirements_source')
    if source:
        source = str(Path(source).resolve())
        parsed = contract.load_source(Path(source))
    else:
        parsed = contract.normalise(plan['brief'].get('requirements', []), plan['brief'].get('constraints', []))
    at = clock_iso or now_iso()
    return {
        'created_at': at, 'updated_at': at, 'phase': 'active', 'plugin': plugin,
        'repo': {'worktree': str(worktree), 'base_ref': base,
                 'base_sha': snapshot.git(worktree, 'rev-parse', '--verify', f'{base}^{{commit}}').strip()},
        'brief': dict(parsed, text=plan['brief']['text'], requirements_source=source),
        'authorization': dict({'endstate': 'local', 'local': [], 'remote': [], 'evidence': ''},
                              **plan.get('authorization', {})),
        'host': plan.get('host', {}), 'roles': merged.get('roles', {}),
        'policy': dict(policy, checks=checks, review=review_policy),
        'children': [], 'checks': [], 'acceptance': [], 'reviews': [], 'waivers': [],
        'remote': {'receipts': [], 'observations': []}, 'notes': [],
    }
