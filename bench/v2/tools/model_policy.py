"""Fail-closed live-test target validation. No models are launched by this module.

The container driver must call validate_target before every parent/canary launch
and child dispatch, including retries, resumes and reviews. Exact model IDs come
from the container's live catalog, never an inherited session default.
"""
import argparse
import json
import re
import sys
from pathlib import Path


FAMILIES = {'codex': 'luna', 'claudeAgent': 'haiku'}
PATTERNS = {'codex': re.compile(r'gpt-[0-9]+(?:\.[0-9]+)?-luna'),
            'claudeAgent': re.compile(r'claude-haiku-[0-9]+(?:-[0-9]+)*')}
ROLES = {'parent', 'worker', 'reviewer', 'canary', 'retry', 'repair', 'resume', 'child', 'native-child'}
CHILD_ROLES = {'worker', 'reviewer', 'child', 'native-child'}


def validate_target(catalog: dict, target: dict, pinned: dict | None = None,
                    role: str | None = None) -> dict:
    """Return an explicit cheap target or reject it before any paid request."""
    role = role or target.get('role', 'worker')
    if role not in ROLES:
        raise ValueError('live-test target role is unsupported')
    provider_id = target.get('providerInstanceId')
    family = FAMILIES.get(provider_id)
    model_id = target.get('model')
    if not family or not isinstance(model_id, str) or not model_id:
        raise ValueError('live tests require an explicit Codex Luna or Claude Haiku target')
    if not PATTERNS[provider_id].fullmatch(model_id):
        raise ValueError(f'live tests require {family}; target rejected')
    frozen = pinned.get(provider_id) if pinned is not None else None
    if pinned is not None and not isinstance(frozen, dict):
        raise ValueError('provider is absent from the frozen live-test allowlist')
    if frozen is not None:
        if (frozen.get('providerInstanceId') != provider_id
                or not isinstance(frozen.get('model'), str)
                or not PATTERNS[provider_id].fullmatch(frozen['model'])
                or model_id != frozen.get('model')):
            raise ValueError(f'frozen {family} target is invalid')
    driver = target.get('driverKind')
    if driver is not None and driver != provider_id:
        raise ValueError('provider driver mismatch')
    providers = [p for p in catalog.get('providers', [])
                 if p.get('providerInstanceId') == provider_id]
    if len(providers) != 1 or providers[0].get('enabled') is False:
        raise ValueError('required live-test provider unavailable; no model fallback')
    if role in CHILD_ROLES and providers[0].get('canRunChildTask') is not True:
        raise ValueError('required live-test provider unavailable; no model fallback')
    models = [m for m in providers[0].get('models', []) if m.get('id') == model_id]
    if len(models) != 1 or models[0].get('enabled') is False:
        raise ValueError('exact live-test model unavailable or ambiguous; no model fallback')
    # Explicit standard-tier options prevent an inherited priority/fast-mode setting.
    available = {o['id']: o for o in models[0].get('options', [])}
    if family == 'luna':
        expected = {'reasoningEffort': 'low', 'serviceTier': 'default'}
    elif 'effort' in available:
        expected = {'effort': 'low'}
        if 'fastMode' in available:
            expected['fastMode'] = False
    elif (available.get('thinking', {}).get('type') == 'boolean'):
        # Older Haiku catalogs expose only extended-thinking on/off. False is
        # the lowest supported setting; the API request must omit thinking.
        expected = {'thinking': False}
    else:
        raise ValueError('Haiku catalog exposes no supported low-effort control')
    if frozen is not None and (frozen.get('options') != expected or any(type(frozen['options'][k]) is not type(v) for k, v in expected.items())):
        raise ValueError('frozen live-test options are invalid')
    options = target.get('options')
    if options != expected or any(type(options[k]) is not type(v) for k, v in expected.items()):
        raise ValueError('live tests require low effort and standard service; options rejected')
    for key, value in expected.items():
        option = available.get(key)
        if option is None:
            raise ValueError(f'required live-test option unavailable: {key}')
        if option.get('type') == 'boolean':
            if not isinstance(value, bool):
                raise ValueError(f'invalid live-test option: {key}')
        elif value not in {v.get('id') for v in option.get('options', [])}:
            raise ValueError(f'required live-test option value unavailable: {key}')
    return {'providerInstanceId': provider_id, 'model': model_id,
            'options': {k: v for k, v in expected.items() if k in available}}


def validate_frozen_map(catalog: dict, pinned: dict, role: str = 'canary') -> dict:
    if not isinstance(pinned, dict) or set(pinned) != set(FAMILIES):
        raise ValueError('frozen target policy must contain exactly both cheap providers')
    return {provider: validate_target(catalog, target, pinned, role=role)
            for provider, target in pinned.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--policy', type=Path, required=True,
                        help='stage-local frozen live target map')
    parser.add_argument('--role', choices=sorted(ROLES), default='parent',
                        help='execution role used for capability validation')
    args = parser.parse_args()
    try:
        policy = json.loads(args.policy.read_text()) if args.policy else None
        pinned = policy.get('targets') if policy else None
        if args.policy and not isinstance(pinned, dict):
            raise ValueError('frozen target policy is malformed')
        catalog = json.loads(args.catalog.read_text())
        target = validate_target(catalog, json.loads(args.target.read_text()), pinned,
                                 role=args.role)
        validate_frozen_map(catalog, pinned, role=args.role)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        print(f'live-test model policy: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(target, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
