"""Narrow opt-in provider grants. Config changes are not proof of live access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from learning_store import Unavailable, atomic_file, directory, locked, read_file, state_root, trusted_link


SOURCES = {
    'claudeAgent': 'https://code.claude.com/docs/en/sandboxing',
    'codex': 'https://developers.openai.com/codex/config-reference/',
    'opencode': 'https://opencode.ai/docs/permissions/',
}


def snippet(driver, change):
    """The exact text an operator merges into a config that setup will not edit."""
    if driver == 'codex':
        roots = change['sandbox_workspace_write']['writable_roots']
        return '[sandbox_workspace_write]\nwritable_roots = ' + json.dumps(roots) + '\n'
    return json.dumps(change, indent=2) + '\n'


def codex_update(raw, subtree):
    try:
        import tomllib
    except ImportError as exc:
        raise Unavailable('Codex TOML grants require Python 3.11+; configure the printed grant manually') from exc
    text = raw.decode()
    parsed = tomllib.loads(text)
    table = parsed.get('sandbox_workspace_write', {})
    roots = table.get('writable_roots', [])
    if not isinstance(roots, list) or not all(isinstance(p, str) for p in roots):
        raise Unavailable('Codex writable_roots is not an array of strings')
    if subtree in roots:
        return raw
    roots = roots + [subtree]
    value = 'writable_roots = ' + json.dumps(roots) + '\n'
    match = re.search(r'^\[sandbox_workspace_write\][ \t]*(?:#[^\n]*)?\n', text, re.M)
    if match:
        end = re.search(r'^\[', text[match.end():], re.M)
        limit = match.end() + end.start() if end else len(text)
        block = text[match.end():limit]
        assignment = re.search(r'^writable_roots\s*=\s*\[.*?\][ \t]*(?:#[^\n]*)?(?:\n|$)', block, re.M | re.S)
        if 'writable_roots' in table and not assignment:
            raise Unavailable('unsupported Codex TOML layout; configure the printed grant manually')
        if assignment:
            block = block[:assignment.start()] + value + block[assignment.end():]
        else:
            block = value + block
        changed = text[:match.end()] + block + text[limit:]
    else:
        if 'sandbox_workspace_write' in parsed:
            raise Unavailable('unsupported Codex TOML layout; configure the printed grant manually')
        changed = text.rstrip() + '\n\n[sandbox_workspace_write]\n' + value
    updated = tomllib.loads(changed)
    expected = dict(parsed)
    expected['sandbox_workspace_write'] = dict(table, writable_roots=roots)
    if updated != expected:
        raise Unavailable('Codex edit would change unrelated settings')
    return changed.encode()


def json_update(raw, driver, subtree):
    data = json.loads(raw or b'{}')
    if not isinstance(data, dict):
        raise Unavailable('provider config is not an object')
    if driver == 'claudeAgent':
        sandbox = data.setdefault('sandbox', {})
        filesystem = sandbox.setdefault('filesystem', {})
        grants = filesystem.setdefault('allowWrite', [])
        if not isinstance(grants, list) or not all(isinstance(p, str) for p in grants):
            raise Unavailable('allowWrite is not an array of strings')
        if subtree in grants:
            return raw
        grants.append(subtree)
    else:
        permission = data.setdefault('permission', {})
        if not isinstance(permission, dict):
            raise Unavailable('preserving scalar OpenCode permission; configure the printed grant manually')
        grants = permission.setdefault('external_directory', {})
        if not isinstance(grants, dict):
            raise Unavailable('preserving scalar external_directory permission')
        pattern = subtree + '/**'
        if grants.get(pattern) == 'allow' and list(grants)[-1] == pattern:
            return raw
        # Last matching rule wins; preserve other rules and insert exactly this subtree last.
        grants.pop(pattern, None)
        grants[pattern] = 'allow'
    return (json.dumps(data, indent=2) + '\n').encode()


def grant(driver, project, apply=False, env=None):
    env = os.environ if env is None else env
    try:
        subtree = str(state_root(project, env) / 't3-plugins/learnings')
        # Provider pattern languages treat these characters specially. Refuse ambiguous paths.
        if any(c in subtree for c in ('*', '?', '\n', '\r', '[', ']', '$', '~', '\\')):
            raise Unavailable('learning path contains provider-pattern metacharacters')
        home = Path(env.get('HOME', str(Path.home())))
        xdg = Path(env.get('XDG_CONFIG_HOME') or str(home / '.config'))
        if driver == 'claudeAgent':
            path = Path(env.get('CLAUDE_CONFIG_DIR') or str(home / '.claude')) / 'settings.json'
            change = {'sandbox': {'filesystem': {'allowWrite': [subtree]}}}
        elif driver == 'codex':
            path = Path(env.get('CODEX_HOME') or str(home / '.codex')) / 'config.toml'
            change = {'sandbox_workspace_write': {'writable_roots': [subtree]}}
        elif driver == 'opencode':
            path = xdg / 'opencode/opencode.json'
            change = {'permission': {'external_directory': {subtree + '/**': 'allow'}}}
            if (path.parent / 'opencode.jsonc').exists() or env.get('OPENCODE_CONFIG') or env.get('OPENCODE_CONFIG_CONTENT'):
                raise Unavailable('OpenCode config override/JSONC needs a manual grant')
        else:
            return {'provider': driver, 'status': 'unavailable', 'reason': 'no documented subtree grant adapter'}
        receipt = {'provider': driver, 'status': 'proposed', 'config': str(path), 'grant': change,
                   'source': SOURCES[driver], 'scope': 'configuration only; live access must be checked'}
        # Dotfiles-managed configs: writing through the link would be lost on the next sync.
        link = next((p for p in (path, *path.parents) if p.is_symlink() and not trusted_link(p)), None)
        if link is not None:
            try:
                target = path.resolve()
            except (RuntimeError, OSError) as exc:  # A symlink loop: 3.12 raises RuntimeError.
                return dict(receipt, status='manual', target=None, snippet=snippet(driver, change),
                            action=(f'{link} is a symlink that does not resolve ({exc}). Fix the link, then '
                                    'merge the snippet into the file it points to, keeping existing entries.'))
            return dict(receipt, status='manual', target=str(target), snippet=snippet(driver, change),
                        action=(f'{link} is a symlink and setup does not write through it. Merge the snippet '
                                f'into {target} in its source repository, keeping existing entries, then '
                                'sync and run t3-plugins doctor to confirm learnings_write is writable.'))
        if not apply:
            return receipt
        if project is not None and path.absolute().is_relative_to(Path(project).resolve()):
            raise Unavailable('provider config is inside the project')
        with directory(path.parent, True) as fd, locked(fd, path.name + '.learnings.lock', True):
            try:
                raw = read_file(fd, path.name)
            except FileNotFoundError:
                raw = b''
            updated = codex_update(raw, subtree) if driver == 'codex' else json_update(raw, driver, subtree)
            if updated == raw:
                return dict(receipt, status='unchanged')
            import hashlib
            backup = path.name + '.pre-learnings-' + hashlib.sha256(raw).hexdigest()
            try:
                if read_file(fd, backup) != raw:
                    raise Unavailable('provider backup collision')
            except FileNotFoundError:
                atomic_file(fd, backup, raw)
            atomic_file(fd, path.name, updated)
            return dict(receipt, status='applied', backup=str(path.parent / backup))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'provider': driver, 'status': 'unavailable', 'reason': str(exc)}


def setup_grants(project, capabilities=None, apply=False, env=None):
    drivers = sorted({p['driverKind'] for p in capabilities['providers']}) if capabilities else [
        'claudeAgent', 'codex', 'opencode', 'antigravity', 'cursor', 'grok']
    return [grant(driver, project, apply, env) for driver in drivers]
