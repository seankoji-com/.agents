#!/usr/bin/env python3
"""Compare explicit provider sources; apply one approved native candidate at a time."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import secrets

# -I installations must resolve the adjacent helper without relying on cwd/sys.path.
import importlib.util
_spec = importlib.util.spec_from_file_location('tuneup_audit', Path(__file__).with_name('audit.py'))
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)
# The package's core/jobs/store.py (installed beside scripts/, or the source checkout root)
# owns the one rule for immutable system symlinks; without it every symlink stays refused.
_store = next((p / 'core/jobs/store.py' for p in Path(__file__).resolve().parents
               if (p / 'core/jobs/store.py').is_file()), None)
if _store is None:
    def trusted_link(path):
        return False
else:
    _spec = importlib.util.spec_from_file_location('tuneup_core_store', _store)
    _core_store = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_core_store)
    trusted_link = _core_store.trusted_link

ADAPTERS = {'claude', 'codex', 'opencode', 'antigravity', 'muse'}
ROOTS = {
    'claude': {'permissions', 'mcpServers', 'enabledPlugins', 'enabledMcpjsonServers',
               'disabledMcpjsonServers', 'disabledMcpServers', 'enableAllProjectMcpServers', 'sandbox'},
    'codex': {'approval_policy', 'sandbox_mode', 'sandbox_workspace_write', 'mcp_servers', 'plugins'},
    'opencode': {'permission', 'mcp', 'plugin'},
    'antigravity': {'mcpServers'},
    # Muse keeps MCP servers and plugins outside settings.json; only its
    # permission profiles are a settings-owned policy surface.
    'muse': {'permissions'},
}
KINDS = {'mcp', 'plugin'}
SAFE_ERRORS = {
    'python_3_11_required', 'apply_requires_posix', 'shared_writable_file',
    'absolute_path_required', 'symlink_refused', 'unsafe_file', 'unsafe_source',
    'new_risky_permission_patterns', 'unsupported_or_empty_change',
    'changed_keys_do_not_match', 'stale_or_unapproved_plan', 'stale_plan',
    'invalid_backup', 'protective_setting_weakened',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_permission(value, depth=0):
    if isinstance(value, dict):
        if depth >= 2:
            raise ValueError('invalid_settings')
        for action in value.values():
            validate_permission(action, depth + 1)
    elif not isinstance(value, str) or value not in {'allow', 'ask', 'deny'}:
        raise ValueError('invalid_settings')


def parse(adapter, raw):
    if adapter not in ADAPTERS:
        raise ValueError('unsupported_adapter')
    text = raw.decode('utf-8')
    if adapter == 'codex':
        try:
            import tomllib
        except ImportError:
            raise ValueError('python_3_11_required') from None
        data = tomllib.loads(text)
    else:
        data = json.loads(audit.jsonc(text) if adapter in {'opencode', 'antigravity'} else text)
    if not isinstance(data, dict):
        raise ValueError('invalid_settings')
    if adapter != 'antigravity':
        audit.inspect(adapter, data)
    if adapter == 'opencode':
        validate_permission(data.get('permission', {}))
        agents = data.get('agent', {})
        if not isinstance(agents, dict):
            raise ValueError('invalid_settings')
        for agent in agents.values():
            if not isinstance(agent, dict):
                raise ValueError('invalid_settings')
            validate_permission(agent.get('permission', {}))
    resources(adapter, data)  # Validate fields used by the inventory.
    return data


def resources(adapter, data):
    result = {'mcp': {}, 'plugin': {}}

    def record(name, state):
        previous = result['mcp'].get(name)
        if state == 'approval_only' and previous is not None:
            return
        if previous in (None, 'approval_only'):
            result['mcp'][name] = state
        elif previous != state:
            result['mcp'][name] = 'scope_conflict'

    key = {'codex': 'mcp_servers', 'opencode': 'mcp'}.get(adapter, 'mcpServers')
    # Muse's settings.json defines no MCP servers; do not read another
    # harness's key if an unrelated file happens to carry one.
    servers = {} if adapter == 'muse' else data.get(key, {})
    if not isinstance(servers, dict):
        raise ValueError('invalid_mcp')
    if adapter == 'claude':
        projects = data.get('projects', {})
        if not isinstance(projects, dict):
            raise ValueError('invalid_projects')
        # This separate store is project-keyed; never mistake nested definitions
        # for absence. Selecting/merging a project remains provider-specific.
        for project in projects.values():
            if not isinstance(project, dict):
                raise ValueError('invalid_projects')
            nested = resources('claude', {k: v for k, v in project.items() if k != 'projects'})
            for name in nested['mcp']:
                record(name, 'project_scoped')
        for field in ('disabledMcpjsonServers', 'enabledMcpjsonServers', 'disabledMcpServers'):
            names = data.get(field, [])
            if not isinstance(names, list) or any(not isinstance(v, str) for v in names):
                raise ValueError('invalid_mcp')
        for name in data.get('disabledMcpjsonServers', []) + data.get('disabledMcpServers', []):
            record(name, 'disabled')
        for name in data.get('enabledMcpjsonServers', []):
            record(name, 'approval_only')
    for name, config in servers.items():
        if not isinstance(config, dict):
            raise ValueError('invalid_mcp')
        enabled = config.get('enabled', True)
        disabled = config.get('disabled', False)
        if type(enabled) is not bool or type(disabled) is not bool:
            raise ValueError('invalid_mcp')
        # A configured server does not prove approval, authentication or reachability.
        state = 'disabled' if not enabled or disabled else 'configured'
        record(name, state)
    if adapter == 'claude':
        plugins = data.get('enabledPlugins', {})
        if not isinstance(plugins, dict) or any(type(v) is not bool for v in plugins.values()):
            raise ValueError('invalid_plugins')
        result['plugin'] = {name: 'configured' if enabled else 'disabled' for name, enabled in plugins.items()}
    elif adapter == 'opencode':
        plugins = data.get('plugin', [])
        if not isinstance(plugins, list) or any(not isinstance(v, str) for v in plugins):
            raise ValueError('invalid_plugins')
        result['plugin'] = dict.fromkeys(plugins, 'configured')
    # Codex plugin identity policies are not proof of installed/enabled plugins.
    return result


def compare(catalog, inventory):
    providers = catalog.get('providers')
    supplied = inventory.get('providers')
    if inventory.get('version') != 1 or not isinstance(providers, list) or not isinstance(supplied, list):
        raise ValueError('invalid_inventory')
    ids = [p['providerInstanceId'] for p in providers]
    given = [p['provider_instance_id'] for p in supplied]
    if len(set(ids)) != len(ids) or len(set(given)) != len(given) or set(given) - set(ids):
        raise ValueError('invalid_inventory')
    indexed = dict(zip(given, supplied))
    rows, observations = [], {}
    for index, provider in enumerate(providers):
        ident = provider['providerInstanceId']
        entry = indexed.get(ident, {})
        adapter = entry.get('adapter')
        source_rows = []
        observations[ident] = []
        for number, source in enumerate(entry.get('sources', [])):
            row = {'source': number, 'status': 'manual', 'permissions': 'unknown'}
            if source.get('scope') not in {'global', 'project', 'local', 'managed', 'host'}:
                raise ValueError('invalid_scope')
            if adapter in ADAPTERS:
                try:
                    data = parse(adapter, read_source(Path(source['path']).expanduser()))
                    observations[ident].append(resources(adapter, data))
                    row.update(status='parsed', scope=source['scope'],
                               findings=audit.inspect(adapter, data) if adapter != 'antigravity' else [])
                    row['permissions'] = 'known_patterns_only' if adapter != 'antigravity' else 'manual'
                except (OSError, ValueError) as exc:
                    row['status'] = 'unreadable_or_invalid'
                    if str(exc) == 'python_3_11_required':
                        row['error'] = 'python_3_11_required'
            source_rows.append(row)
        rows.append({'provider': index, 'catalog_runnable': provider.get('canRunChildTask') is True,
                     'adapter': adapter if adapter in ADAPTERS else 'manual',
                     'catalog_constraints': 'present_review_private_catalog' if provider.get('constraints') else 'none_reported',
                     'sources': source_rows, 'coverage': 'supplied_sources_only' if source_rows else 'unconfigured_inventory'})
    gaps = []
    for number, capability in enumerate(inventory.get('capabilities', [])):
        kind = capability.get('kind')
        members = capability.get('members')
        if kind not in KINDS or not isinstance(members, dict) or set(members) - set(ids):
            raise ValueError('invalid_capability')
        statuses = []
        for ident in ids:
            native = members.get(ident)
            if native is None:
                status = 'unmapped'
            elif not isinstance(native, str):
                raise ValueError('invalid_capability')
            elif not observations[ident] or (kind == 'plugin' and indexed.get(ident, {}).get('adapter') in {'codex', 'antigravity', 'muse'}):
                status = 'unknown'
            else:
                states = {o[kind][native] for o in observations[ident] if native in o[kind]}
                states_without_approval = states - {'approval_only'}
                status = 'unknown' if 'project_scoped' in states or states == {'approval_only'} else (
                    next(iter(states_without_approval)) if len(states_without_approval) == 1 else
                    'scope_conflict' if states_without_approval else 'not_in_supplied_sources')
                # A failed layer makes the complete state unknown even if another parsed.
                if any(s['status'] != 'parsed' for s in rows[ids.index(ident)]['sources']):
                    status = 'unknown'
            statuses.append(status)
        gaps.append({'capability': number, 'kind': kind, 'states': statuses,
                     'equivalence': 'operator_mapping_requires_review'})
    return {'ok': True, 'providers': rows, 'capabilities': gaps, 'writes': 0,
            'effective_permissions': 'unverified', 'live_acceptance': 'not_run'}


def read_source(path):
    """Read-only inventory can follow an explicitly selected alias, never a FIFO."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('unsafe_source')
        return stream.read()


def risk_counts(adapter, data):
    if adapter == 'antigravity':
        return Counter()
    findings = audit.inspect(adapter, data)
    if adapter == 'claude':
        sandbox = data.get('sandbox', {})
        if not isinstance(sandbox, dict):
            raise ValueError('invalid_sandbox')
        if sandbox.get('enabled') is False:
            findings.append({'code': 'sandbox_disabled'})
    if adapter == 'opencode':
        agents = data.get('agent', {})
        if not isinstance(agents, dict):
            raise ValueError('invalid_agents')
        for agent in agents.values():
            if not isinstance(agent, dict):
                raise ValueError('invalid_agents')
            findings.extend(audit.inspect(adapter, {'permission': agent.get('permission', {})}))
    return Counter(f['code'] for f in findings if f['code'] != 'duplicate_rule')


def risk_locations(adapter, data, prefix=()):
    """Keep native override identities internally; public receipts expose codes only."""
    if adapter == 'antigravity':
        return set()
    local = {k: v for k, v in data.items() if k != 'profiles'} if adapter == 'codex' else data
    result = {(prefix, f['code'], 'permission' if adapter == 'opencode' and
               f['code'] == 'all_tools_allowed' else f['location'])
              for f in audit.inspect(adapter, local)
              if f['code'] != 'duplicate_rule' and
              not (adapter == 'claude' and f['code'] == 'broad_execution_allow')}
    # Claude allow arrays are compared by exact rule identity in protect_policy,
    # so inserting/removing an earlier entry cannot invent a risk at a new index.
    if adapter == 'codex':
        for name, profile in data.get('profiles', {}).items():
            result |= risk_locations(adapter, profile, prefix + ('profiles', name))
    elif adapter == 'opencode':
        for name, agent in data.get('agent', {}).items():
            result |= risk_locations(adapter, {'permission': agent.get('permission', {})}, prefix + ('agent', name))
    return result


def protect_policy(adapter, old, new):
    """Conservative checks on exact native fields; no cross-provider translation."""
    if adapter == 'claude':
        for kind in ('deny', 'ask'):
            before = old.get('permissions', {}).get(kind, [])
            after = new.get('permissions', {}).get(kind, [])
            if not isinstance(before, list) or not isinstance(after, list) or any(not isinstance(v, str) for v in before + after):
                raise ValueError('invalid_settings')
            if set(before) - set(after):
                raise ValueError('protective_setting_weakened')
        before, after = old.get('sandbox', {}), new.get('sandbox', {})
        if before.get('enabled') is True and after.get('enabled') is not True:
            raise ValueError('protective_setting_weakened')
        for key in ('allowUnsandboxedCommands', 'autoAllowBashIfSandboxed'):
            if key in after and type(after[key]) is not bool:
                raise ValueError('invalid_settings')
            if (before.get(key) is False and after.get(key) is not False or
                    after.get(key) is True and before.get(key) is not True):
                raise ValueError('protective_setting_weakened')
        if new.get('enableAllProjectMcpServers') is True and old.get('enableAllProjectMcpServers') is not True:
            raise ValueError('protective_setting_weakened')
        # Count-only comparisons let a duplicate broad rule conceal a different one.
        def broad_rules(data):
            return {rule for rule in data.get('permissions', {}).get('allow', [])
                    if audit.inspect('claude', {'permissions': {'allow': [rule]}})}
        if broad_rules(new) - broad_rules(old):
            raise ValueError('new_risky_permission_patterns')
    elif adapter == 'codex':
        for key, unsafe in [('approval_policy', 'never'), ('sandbox_mode', 'danger-full-access')]:
            if key in old and old[key] != unsafe and key not in new:
                raise ValueError('protective_setting_weakened')
        before, after = old.get('sandbox_workspace_write', {}), new.get('sandbox_workspace_write', {})
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError('invalid_settings')
        if after.get('network_access') is True and before.get('network_access') is not True:
            raise ValueError('protective_setting_weakened')
        for name, profile in old.get('profiles', {}).items():
            protect_policy('codex', profile, new.get('profiles', {}).get(name, {}))
        for name in new.get('profiles', {}).keys() - old.get('profiles', {}).keys():
            protect_policy('codex', {}, new['profiles'][name])
    elif adapter == 'opencode':
        def protect_actions(before, after):
            rank = {'deny': 0, 'ask': 1, 'allow': 2}
            if isinstance(before, dict):
                for key, value in before.items():
                    protect_actions(value, after.get(key) if isinstance(after, dict) else after)
            elif before in ('ask', 'deny'):
                if not isinstance(after, str) or after not in rank or rank[after] > rank[before]:
                    raise ValueError('protective_setting_weakened')
        protect_actions(old.get('permission', {}), new.get('permission', {}))
        for name, agent in old.get('agent', {}).items():
            protect_policy('opencode', agent, new.get('agent', {}).get(name, {}))
    elif adapter == 'muse':
        # Dimension ranks verified against Muse 1.4.7. A stated protective
        # value may tighten or stay; loosening or deleting it is refused.
        # Profiles inheriting through `extends` state partial dimensions, so
        # only dimensions the old profile stated are compared.
        network_rank = {'restricted': 0, 'proxy_only': 1, 'enabled': 2}
        before_profiles = old.get('permissions', {}).get('profiles', {})
        after_profiles = new.get('permissions', {}).get('profiles', {})
        if not isinstance(before_profiles, dict) or not isinstance(after_profiles, dict):
            raise ValueError('invalid_settings')
        for name, before in before_profiles.items():
            after = after_profiles.get(name)
            if after is None:
                if any(key in before for key in ('approval', 'filesystem', 'network', 'reviewer')):
                    raise ValueError('protective_setting_weakened')
                continue
            if before.get('approval') == 'on_request' and after.get('approval') != 'on_request':
                raise ValueError('protective_setting_weakened')
            if before.get('reviewer') == 'human' and after.get('reviewer') != 'human':
                raise ValueError('protective_setting_weakened')
            if ('filesystem' in before and before['filesystem'] != 'unrestricted'
                    and after.get('filesystem') == 'unrestricted'):
                raise ValueError('protective_setting_weakened')
            before_mode = before.get('network', {}).get('mode') if isinstance(before.get('network'), dict) else None
            after_mode = after.get('network', {}).get('mode') if isinstance(after.get('network'), dict) else None
            if before_mode in network_rank and (after_mode not in network_rank
                                                or network_rank[after_mode] > network_rank[before_mode]):
                raise ValueError('protective_setting_weakened')


def allowed_change(adapter, parts, old, new):
    if parts[0] in ROOTS[adapter]:
        return True
    # Nested policy overrides are supported; model/agent identity edits are not.
    root = 'profiles' if adapter == 'codex' else 'agent' if adapter == 'opencode' else None
    if parts[0] != root or len(parts) < 2:
        return False
    allowed = ROOTS['codex'] - {'plugins'} if adapter == 'codex' else {'permission'}
    if len(parts) >= 3:
        return parts[2] in allowed
    sections = [data.get(root, {}).get(parts[1], {}) for data in (old, new)]
    return all(isinstance(section, dict) and set(section) <= allowed for section in sections)


def equal_value(before, after):
    """JSON/TOML types remain distinct inside arrays as well as object fields."""
    if type(before) is not type(after):
        return False
    if isinstance(before, list):
        return len(before) == len(after) and all(equal_value(a, b) for a, b in zip(before, after))
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(equal_value(before[k], after[k]) for k in before)
    return before == after


def changed_paths(before, after, prefix=(), adapter=None):
    if isinstance(before, dict) and isinstance(after, dict):
        ordered_policy = adapter == 'opencode' and (
            prefix[:1] == ('permission',) or
            len(prefix) >= 3 and prefix[0] == 'agent' and prefix[2] == 'permission')
        # Retained patterns can change last-match precedence even when other
        # patterns are added/deleted at the same time. Review the whole parent.
        if ordered_policy and ([k for k in before if k in after] !=
                               [k for k in after if k in before]):
            return [prefix]
        paths = []
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                paths.append(prefix + (key,))
            else:
                paths.extend(changed_paths(before[key], after[key], prefix + (key,), adapter))
        return paths
    # bool and int compare equal in Python but have distinct native config types.
    return [] if equal_value(before, after) else [prefix]


def pointer(parts):
    return '/' + '/'.join(p.replace('~', '~0').replace('/', '~1') for p in parts)


def checked_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute_path_required')
    # Refuse symlinks in every component, including directory aliases, except
    # root-owned system links that no other user can swap (macOS /var, /tmp).
    for component in [*reversed(path.parents), path]:
        if component.is_symlink() and not trusted_link(component):
            raise ValueError('symlink_refused')
    return path


def open_parent(path):
    """Anchor every directory without following symlinks, including ancestors."""
    if os.name != 'posix':
        raise ValueError('apply_requires_posix')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, component in enumerate(path.parent.parts[1:], 2):
            follow = trusted_link(Path(*path.parent.parts[:index]))
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | (0 if follow else os.O_NOFOLLOW), dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_at(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError('unsafe_file')
        if info.st_mode & 0o022:
            raise ValueError('shared_writable_file')
        return stream.read(), info


def read_regular(path):
    parent = open_parent(path)
    try:
        return read_at(parent, path.name)
    finally:
        os.close(parent)


def prepare(adapter, target, candidate, allowed):
    target, candidate = checked_path(target), checked_path(candidate)
    if target == candidate:
        raise ValueError('candidate_is_target')
    before, info = read_regular(target)
    after, _ = read_regular(candidate)
    old, new = parse(adapter, before), parse(adapter, after)
    changes = changed_paths(old, new, adapter=adapter)
    if not changes or any(not allowed_change(adapter, p, old, new) for p in changes):
        raise ValueError('unsupported_or_empty_change')
    before_risks, after_risks = risk_counts(adapter, old), risk_counts(adapter, new)
    if after_risks - before_risks or risk_locations(adapter, new) - risk_locations(adapter, old):
        raise ValueError('new_risky_permission_patterns')
    protect_policy(adapter, old, new)
    actual = sorted(pointer(p) for p in changes)
    if sorted(set(allowed)) != actual:
        raise ValueError('changed_keys_do_not_match')
    document = {'version': 1, 'adapter': adapter, 'target': str(target), 'candidate': str(candidate),
                'before_sha256': sha(before), 'after_sha256': sha(after),
                'target_identity': [info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)],
                'changed_keys': actual, 'risk_patterns_before': dict(before_risks),
                'risk_patterns_after': dict(after_risks),
                'permission_semantics': 'not_evaluated_review_every_changed_key', 'validation': 'parse_and_known_patterns_only'}
    document['approval_digest'] = sha(json.dumps(document, sort_keys=True).encode())
    return document, before, after


def write_private(path, raw):
    path = checked_path(path)
    parent = open_parent(path)
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def apply(document, approval, backup):
    current, before, after = prepare(document['adapter'], document['target'], document['candidate'], document['changed_keys'])
    if current != document or approval != document['approval_digest']:
        raise ValueError('stale_or_unapproved_plan')
    target = checked_path(document['target'])
    backup = checked_path(backup)
    if backup in {target, Path(document['candidate'])}:
        raise ValueError('invalid_backup')
    parent = open_parent(target)
    temporary = '.t3-tuneup-' + secrets.token_hex(16)
    created = False
    try:
        # Backups contain original bytes and must never overwrite an existing file.
        write_private(backup, before)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     document['target_identity'][2], dir_fd=parent)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), document['target_identity'][2])
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        latest, info = read_at(parent, target.name)
        identity = [info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)]
        if sha(latest) != document['before_sha256'] or identity != document['target_identity']:
            raise ValueError('stale_plan')
        # Directory fds prevent ancestor swaps redirecting this write. The final
        # file compare/replace is optimistic: stop other config writers first.
        os.replace(temporary, target.name, src_dir_fd=parent, dst_dir_fd=parent)
        created = False
        os.fsync(parent)
        applied, _ = read_at(parent, target.name)
        if sha(applied) != document['after_sha256']:
            raise ValueError('post_write_mismatch')
        parse(document['adapter'], applied)
    finally:
        if created:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)
    return {'ok': True, 'writes': 1, 'backup_created': True, 'parse': 'passed', 'live_acceptance': 'not_run'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    compare_cmd = sub.add_parser('compare')
    compare_cmd.add_argument('--catalog', type=Path, required=True)
    compare_cmd.add_argument('--inventory', type=Path, required=True)
    plan_cmd = sub.add_parser('plan')
    plan_cmd.add_argument('--adapter', choices=sorted(ADAPTERS), required=True)
    plan_cmd.add_argument('--target', required=True)
    plan_cmd.add_argument('--candidate', required=True)
    plan_cmd.add_argument('--allow-key', action='append', required=True)
    plan_cmd.add_argument('--out', required=True)
    apply_cmd = sub.add_parser('apply')
    apply_cmd.add_argument('--plan', type=Path, required=True)
    apply_cmd.add_argument('--approval', required=True)
    apply_cmd.add_argument('--backup', required=True)
    args = parser.parse_args(argv)
    started_apply = args.operation == 'apply'
    try:
        if args.operation == 'compare':
            receipt = compare(json.loads(args.catalog.read_text()), json.loads(args.inventory.read_text()))
        elif args.operation == 'plan':
            document, _, _ = prepare(args.adapter, args.target, args.candidate, args.allow_key)
            out = checked_path(args.out)
            write_private(out, (json.dumps(document, indent=2) + '\n').encode())
            receipt = {'ok': True, 'approval_digest': document['approval_digest'],
                       'changed_key_count': len(document['changed_keys']), 'settings_writes': 0,
                       'validation': document['validation'],
                       'risk_patterns_before': document['risk_patterns_before'],
                       'risk_patterns_after': document['risk_patterns_after'],
                       'permission_semantics': document['permission_semantics']}
        else:
            receipt = apply(json.loads(args.plan.read_text()), args.approval, args.backup)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Neither native parser errors nor paths/keys belong in public receipts.
        receipt = {'ok': False, 'error': str(exc) if isinstance(exc, ValueError) and str(exc) in SAFE_ERRORS else 'invalid_unsafe_stale_or_unapproved_input',
                   'settings_writes': 'inspect_target_and_backup' if started_apply else 0}
        print(json.dumps(receipt))
        return 2
    print(json.dumps(receipt))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
