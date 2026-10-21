"""User-local model routing for T3 delegation.

The config lives at $XDG_CONFIG_HOME/t3-plugins/routing.json, falling back to
~/.config/t3-plugins/routing.json. `write_default` builds it from an
orchestrator_capabilities response the agent saved to a file; nothing here calls
T3 or reads host credentials. `resolve` returns the configured candidates for a
role that the saved capabilities can actually run, in tier order, and reports
every configured entry it could not use instead of substituting another model.
A repository's `.t3-plugins/routing.json` takes precedence over the user config.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from shared.lineage import DRIVER_LINEAGE, FAMILY_LINEAGE, MULTI_LINEAGE_DRIVERS, lineage

SCHEMA_VERSION = 1
ROLES = ('workhorse', 'reviewer', 'judgement')
TIERS = ('low', 'medium', 'high')
# Cheap/fast model families, matched as whole tokens of the model's base name. Setup
# uses them only to guess the starting tiers; the operator edits the config. Tokens,
# never version-bearing IDs — and whole tokens, so `gemini` cannot match `mini`.
CHEAP_MODEL_TOKENS = frozenset({'haiku', 'flash', 'mini', 'nano', 'lite', 'small', 'luna'})
RUNTIME_MODES = ('approval-required', 'auto-accept-edits', 'auto', 'full-access')
# Owner defaults written into a new config; after that the config is the source.
DEFAULT_RUNTIME_MODE = 'auto'
DEFAULT_RUNTIME_MODES = {'opencode': 'full-access'}  # by driverKind
# Drivers that fail below their configured mode: resolve skips them rather than
# launching them at a narrower parent mode.
DEFAULT_REQUIRED_MODES = {'opencode'}  # by driverKind
# Default lineage labels for a new config. A provider can serve several lineages,
# so multi-model gateways are labelled from the model's family instead.


class RoutingError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def config_path(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    base = environ.get('XDG_CONFIG_HOME')
    if base and Path(base).is_absolute():
        root = Path(base)
    else:
        root = Path(environ.get('HOME') or Path.home()) / '.config'
    return root / 't3-plugins' / 'routing.json'


def load_capabilities(path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise RoutingError('capabilities_unreadable', f'cannot read capabilities file {path}: {exc}') from exc
    if isinstance(data, dict) and isinstance(data.get('response'), dict):
        data = data['response']  # the shape imps records
    if not isinstance(data, dict) or not isinstance(data.get('providers'), list):
        raise RoutingError('capabilities_invalid', 'capabilities need a "providers" list from orchestrator_capabilities')
    return data


def _runnable(provider: dict) -> bool:
    return provider.get('canRunChildTask') is True


def _models(provider: dict) -> list:
    return [m['id'] for m in provider.get('models') or [] if isinstance(m, dict) and isinstance(m.get('id'), str)]


def _offered_modes(provider: dict) -> list:
    """Modes the catalog says this provider can run, broadest ordering kept.
    Absent or malformed catalog data means no constraint is known."""
    modes = provider.get('runtimeModes')
    if not isinstance(modes, list):
        return []
    return [m for m in RUNTIME_MODES if m in modes]


def _default_mode(driver: str, offered=()) -> str:
    wanted = DEFAULT_RUNTIME_MODES.get(driver, DEFAULT_RUNTIME_MODE)
    if not offered or wanted in offered:
        return wanted
    # Never write a mode the provider cannot run (T3's Muse driver, for
    # example, offers no auto variant). Take the broadest offered mode at or
    # below the default; only when every offered mode is broader, take the
    # narrowest offered mode so the default stays launchable and visible.
    at_or_below = [m for m in offered if RUNTIME_MODES.index(m) <= RUNTIME_MODES.index(wanted)]
    return at_or_below[-1] if at_or_below else offered[0]


def _provider_defaults(driver: str, offered=()) -> dict:
    settings = {'runtimeMode': _default_mode(driver, offered)}
    if driver in DEFAULT_REQUIRED_MODES:
        settings['requireRuntimeMode'] = True
    return settings


def model_tier(model: str) -> str:
    """Setup's starting tier guess for one advertised model: `low` for a cheap family
    such as a haiku-, flash-, mini- or luna-class model, `medium` otherwise. The
    session model is placed at `high` separately. Only a guess: the operator edits it."""
    tokens = re.split(r'[^a-z0-9]+', model.rsplit('/', 1)[-1].lower())
    return 'low' if CHEAP_MODEL_TOKENS.intersection(tokens) else 'medium'


def default_config(capabilities: dict) -> dict:
    """A starting config: the session model judges, and the cheapest advertised models
    work. Workhorses are every cheap-family model at the `low` tier, in catalog order,
    with the session model appended last as the only fallback; reviewers are the first
    advertised model of every other lineage, ahead of the session model. Tiers and
    lineage labels are guesses the owner is expected to edit."""
    providers = [p for p in capabilities['providers'] if isinstance(p, dict) and _runnable(p) and _models(p)]
    if not providers:
        raise RoutingError('no_runnable_providers', 'the capabilities list no provider that can run child tasks')
    drivers = {p['providerInstanceId']: p.get('driverKind', '') for p in providers}
    offered = {p['providerInstanceId']: _offered_modes(p) for p in providers}
    home_id = capabilities.get('inheritedProviderInstanceId')
    home_model = capabilities.get('inheritedModel')
    home = next((p for p in providers if p['providerInstanceId'] == home_id and home_model in _models(p)), None)
    if home is None:
        home = providers[0]
        home_model = _models(home)[0]

    def entry(provider, model, tier):
        return {'providerInstanceId': provider['providerInstanceId'], 'model': model, 'tier': tier,
                'lineage': lineage(provider.get('driverKind', ''), model)}

    session = entry(home, home_model, 'high')
    # The cheapest advertised models work, so a delegating workflow's children land on a
    # cheap model without the owner editing anything. The session model stays last, so a
    # catalog with no cheap family behaves exactly as before.
    workhorse, keyed = [], {(session['providerInstanceId'], session['model'])}
    for provider in providers:
        for model in _models(provider):
            key = (provider['providerInstanceId'], model)
            if key not in keyed and model_tier(model) == 'low':
                keyed.add(key)
                workhorse.append(entry(provider, model, 'low'))
    workhorse.append(session)
    reviewers, seen = [], {session['lineage']}
    for provider in providers:
        for model in _models(provider):
            candidate = entry(provider, model, model_tier(model))
            if candidate['lineage'] not in seen and candidate['lineage'] != 'unknown':
                seen.add(candidate['lineage'])
                reviewers.append(candidate)
    reviewers.append(session)
    return {
        'schema_version': SCHEMA_VERSION,
        'tiers': list(TIERS),
        'providers': {pid: _provider_defaults(driver, offered[pid]) for pid, driver in sorted(drivers.items())},
        'roles': {'workhorse': workhorse, 'reviewer': reviewers, 'judgement': [session]},
    }


def validate(config) -> dict:
    if not isinstance(config, dict) or config.get('schema_version') != SCHEMA_VERSION:
        raise RoutingError('config_invalid', f'routing config needs "schema_version": {SCHEMA_VERSION}')
    tiers = config.get('tiers')
    if not isinstance(tiers, list) or not tiers or not all(isinstance(t, str) and t for t in tiers) \
            or len(set(tiers)) != len(tiers):
        raise RoutingError('config_invalid', '"tiers" must be a non-empty list of unique names, cheapest first')
    providers = config.get('providers', {})
    if not isinstance(providers, dict):
        raise RoutingError('config_invalid', '"providers" must map provider instance IDs to settings')
    for pid, settings in providers.items():
        if not isinstance(settings, dict) or settings.get('runtimeMode') not in RUNTIME_MODES:
            raise RoutingError('config_invalid', f'provider {pid} needs a runtimeMode from {list(RUNTIME_MODES)}')
        if not isinstance(settings.get('requireRuntimeMode', False), bool):
            raise RoutingError('config_invalid', f'provider {pid} requireRuntimeMode must be true or false')
    roles = config.get('roles')
    if not isinstance(roles, dict):
        raise RoutingError('config_invalid', '"roles" must map role names to entries')
    for role, entries in roles.items():
        if not isinstance(entries, list):
            raise RoutingError('config_invalid', f'role {role} must be a list of entries')
        for item in entries:
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k]
                                                     for k in ('providerInstanceId', 'model', 'lineage', 'tier')):
                raise RoutingError('config_invalid', f'every {role} entry needs providerInstanceId, model, lineage and tier')
            if item['tier'] not in tiers:
                raise RoutingError('config_invalid', f'{role} entry names unknown tier {item["tier"]!r}')
    return config


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RoutingError('config_invalid', f'cannot parse {path}: {exc}') from exc


def read_config(path) -> dict | None:
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    return validate(_read_json(path))


def write_default(capabilities_file, path=None) -> dict:
    """Write a new config, never replacing an existing one (valid or not)."""
    path = Path(path) if path else config_path()
    if path.exists() or path.is_symlink():
        try:
            read_config(path)
        except RoutingError as exc:
            return {'routing': str(path), 'action': 'preserved', 'valid': False, 'error': str(exc)}
        return {'routing': str(path), 'action': 'preserved', 'valid': True}
    config = default_config(load_capabilities(capabilities_file))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.routing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(config, indent=2) + '\n')
        os.chmod(temporary, 0o600)
        os.link(temporary, path)  # fails rather than replacing a config written meanwhile
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'routing': str(path), 'action': 'written', 'valid': True,
            'note': 'tiers and lineage labels are defaults; edit them to match your providers'}


def effective_config(user_path=None, repo=None) -> tuple[dict, list]:
    """Repository policy (`.t3-plugins/routing.json`) wins over the user config:
    each role or provider it names replaces the user's, and its tiers win."""
    user_path = Path(user_path) if user_path else config_path()
    config, sources = read_config(user_path), []
    if config is not None:
        sources.append(str(user_path))
    repo_file = Path(repo) / '.t3-plugins' / 'routing.json' if repo else None
    if repo_file and (repo_file.exists() or repo_file.is_symlink()):
        policy = _read_json(repo_file)
        if not isinstance(policy, dict) or not all(isinstance(policy.get(k, {}), dict) for k in ('providers', 'roles')):
            raise RoutingError('config_invalid', f'{repo_file} must be a JSON object with object "providers" and "roles"')
        base = config or {'schema_version': SCHEMA_VERSION, 'providers': {}, 'roles': {}}
        config = validate({'schema_version': policy.get('schema_version', SCHEMA_VERSION),
                           'tiers': policy.get('tiers', base.get('tiers')),
                           'providers': {**base.get('providers', {}), **(policy.get('providers') or {})},
                           'roles': {**base['roles'], **(policy.get('roles') or {})}})
        sources.append(str(repo_file))
    if config is None:
        raise RoutingError('config_missing', f'no routing config at {user_path}; run t3-plugins setup --capabilities FILE')
    return config, sources


def resolve(role: str, capabilities: dict, config: dict | None, implementer_lineage: str | None = None,
            profiles: dict | None = None) -> dict:
    """With `implementer_lineage`, every candidate says whether it is independent of the
    implementer: true for another known lineage, false for the same one, null when either
    lineage is `unknown`. Independent candidates come first, then unverified, then the
    same lineage, each group in tier order."""
    if profiles is not None:
        from shared.model_selection import discover
        return dict(discover(capabilities, profiles, config, role), role=role, recommendation_only=True)
    if config is None:
        raise RoutingError('profiles_missing', 'no config: supply a sourced suitability profile for catalog recommendations')
    if role not in config['roles'] or not config['roles'][role]:
        raise RoutingError('role_missing', f'role {role!r} is not configured')
    catalog = {p.get('providerInstanceId'): p for p in capabilities['providers'] if isinstance(p, dict)}
    parent_mode = capabilities.get('runtimeMode')
    order = {name: index for index, name in enumerate(config['tiers'])}
    candidates, unavailable = [], []
    for item in sorted(config['roles'][role], key=lambda e: order[e['tier']]):
        provider = catalog.get(item['providerInstanceId'])
        reason = None
        if provider is None:
            reason = 'provider_absent'
        elif not _runnable(provider):
            reason = 'provider_unavailable: ' + ('; '.join(provider.get('constraints') or []) or 'cannot run child tasks')
        elif item['model'] not in _models(provider):
            reason = 'model_absent'
        if reason:
            unavailable.append(dict(item, reason=reason))
            continue
        # A provider the config does not list gets the same owner defaults setup would write.
        settings = config.get('providers', {}).get(item['providerInstanceId']) \
            or _provider_defaults(provider.get('driverKind', ''), _offered_modes(provider))
        mode = settings['runtimeMode']
        candidate = dict(item, runtimeMode=mode)
        if parent_mode in RUNTIME_MODES and RUNTIME_MODES.index(mode) > RUNTIME_MODES.index(parent_mode):
            if settings.get('requireRuntimeMode', provider.get('driverKind') in DEFAULT_REQUIRED_MODES):
                unavailable.append(dict(candidate, reason=f'runtime_mode_above_parent: needs {mode}, parent runs {parent_mode}'))
                continue
            # T3 refuses a child broader than its parent. Launch at the parent's mode
            # and tell the owner; never lower it silently.
            candidate['runtimeMode'] = parent_mode
            candidate['owner_action'] = f'switch this child to {mode} in T3; it was launched in {parent_mode}'
        offered = _offered_modes(provider)
        if offered and candidate['runtimeMode'] not in offered:
            # The driver cannot run this mode at all (Muse offers no auto
            # variant). Substituting another mode would hide a config error.
            candidate.pop('owner_action', None)
            unavailable.append(dict(candidate, reason=(
                f"runtime_mode_unsupported: {candidate['runtimeMode']} not offered; "
                f"provider offers {', '.join(offered)}")))
            continue
        candidates.append(candidate)
    if implementer_lineage:
        rank = {True: 0, None: 1, False: 2}
        for candidate in candidates:
            if 'unknown' in (candidate['lineage'], implementer_lineage):
                candidate['independent'] = None  # no lineage data: independence unverified
            else:
                candidate['independent'] = candidate['lineage'] != implementer_lineage
        candidates.sort(key=lambda c: rank[c['independent']])  # stable: tier order within each group
    return {'role': role, 'candidates': candidates, 'unavailable': unavailable}
