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


def validate_target(catalog: dict, target: dict) -> dict:
    """Return an explicit cheap target or reject it before any paid request."""
    provider_id = target.get('providerInstanceId')
    family = FAMILIES.get(provider_id)
    model_id = target.get('model')
    if not family or not isinstance(model_id, str) or not model_id:
        raise ValueError('live tests require an explicit Codex Luna or Claude Haiku target')
    pattern = (r'gpt-[0-9]+(?:\.[0-9]+)?-luna' if family == 'luna'
               else r'claude-haiku-[0-9]+(?:-[0-9]+)*')
    if not re.fullmatch(pattern, model_id):
        raise ValueError(f'live tests require {family}; target rejected')
    providers = [p for p in catalog.get('providers', [])
                 if p.get('providerInstanceId') == provider_id]
    if len(providers) != 1 or providers[0].get('canRunChildTask') is not True:
        raise ValueError('required live-test provider unavailable; no model fallback')
    models = [m for m in providers[0].get('models', []) if m.get('id') == model_id]
    if len(models) != 1:
        raise ValueError('exact live-test model unavailable or ambiguous; no model fallback')
    # Explicit standard-tier options prevent an inherited priority/fast-mode setting.
    expected = ({'reasoningEffort': 'low', 'serviceTier': 'default'} if family == 'luna'
                else {'effort': 'low', 'fastMode': False})
    available = {o['id']: o for o in models[0].get('options', [])}
    if 'fastMode' not in available:
        expected.pop('fastMode', None)
    options = target.get('options')
    if options != expected:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    try:
        target = validate_target(json.loads(args.catalog.read_text()), json.loads(args.target.read_text()))
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        print(f'live-test model policy: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(target, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
