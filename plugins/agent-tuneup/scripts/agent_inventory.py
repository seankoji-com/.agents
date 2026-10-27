#!/usr/bin/env python3
"""Bounded, read-only native definitions and portable roles. No migration writer.

All paths come from the private v2 wiring input. Reports use indices; the optional
private plan contains recovery metadata and source descriptors, never prompt bodies.
Receipts bind declared provenance, not human intent or runtime behavior.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 16
MAX_ENTRIES = 2048
SCOPES = {'global', 'project', 'managed', 'session', 'vendor', 'shared'}
DISPOSITIONS = {'keep', 'keep-as-native-exception', 'extract-role',
                'retire-managed-alias', 'preserve-unmanaged', 'unresolved'}
DIGEST = re.compile(r'[0-9a-f]{64}')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def absolute(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('invalid_agent_path')
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('invalid_agent_path')
    return path


def identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def parent_fd(path):
    """Walk from the trusted filesystem / descriptor, never following a link.

    Requires POSIX dir_fd, O_DIRECTORY and O_NOFOLLOW; no race-unsafe fallback.
    Only explicitly supplied discovery roots may be resolved once before this
    walk. Their canonical destinations are the read authority, never write scope.
    Keep every ancestor open and refuse replacement before publishing a read.
    """
    if (not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY')
            or any(f not in os.supports_dir_fd for f in (os.open, os.stat, os.readlink))):
        raise ValueError('secure_read_unavailable')
    path = absolute(str(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fds, links = [], []
    try:
        fds.append(os.open('/', flags))
        for part in path.parts[1:-1]:
            before = os.stat(part, dir_fd=fds[-1], follow_symlinks=False)
            child = os.open(part, flags, dir_fd=fds[-1])
            fds.append(child)
            opened = os.fstat(child)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError('concurrent_drift')
            links.append((fds[-2], part, opened.st_dev, opened.st_ino))
        yield fds[-1], path.name
        for parent, name, device, inode in links:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (device, inode):
                raise ValueError('concurrent_drift')
    finally:
        for fd in reversed(fds):
            os.close(fd)


def file_identity(path):
    with parent_fd(path) as (parent, name):
        return identity(os.stat(name, dir_fd=parent, follow_symlinks=False))


def read(path, expected=None):
    with parent_fd(path) as (parent, name):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('unsafe_file')
        if expected is not None and identity(before) != expected:
            raise ValueError('concurrent_drift')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            if identity(os.fstat(stream.fileno())) != identity(before):
                raise ValueError('concurrent_drift')
            raw = stream.read(MAX_BYTES + 1)
            if (identity(os.fstat(stream.fileno())) != identity(before)
                    or identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(before)):
                raise ValueError('concurrent_drift')
    if len(raw) > MAX_BYTES:
        raise ValueError('size_limit')
    return raw


def alias(path):
    """Python 3.10-compatible reparse detection; never traverse child junctions."""
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def depth(value, level=0):
    if level > MAX_DEPTH:
        raise ValueError('depth_limit')
    if isinstance(value, dict):
        for child in value.values():
            depth(child, level + 1)
    elif isinstance(value, list):
        for child in value:
            depth(child, level + 1)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def json_data(raw, comments=False):
    text = raw.decode('utf-8')
    if comments:
        # A state machine keeps URL strings and escaped quotes intact. Comments
        # and trailing commas are data syntax only; nothing is evaluated.
        text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                      lambda m: m[0] if m[0].startswith('"') else ' ', text)
        text = re.sub(r'("(?:\\.|[^"\\])*")|,(\s*[}\]])',
                      lambda m: m[1] if m[1] is not None else m[2], text)
    try:
        data = json.loads(text, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))
        depth(data)
    except RecursionError:
        raise ValueError('depth_limit') from None
    return data


def scalar(text):
    text = text.strip()
    if not text:
        return {}
    if text.startswith(('&', '*', '!', '{', '[')):
        if text.startswith(('{', '[')):
            return json_data(text.encode())
        raise ValueError('unsupported_yaml')
    if text.startswith('"'):
        return json_data(text.encode())
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise ValueError('invalid_frontmatter')
        return text[1:-1].replace("''", "'")
    if text in {'true', 'false'}:
        return text == 'true'
    if text in {'null', '~'}:
        return None
    if re.fullmatch(r'-?[0-9]+', text):
        return int(text)
    if re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', text):
        return json_data(text.encode())
    if ': ' in text or ' #' in text or '\t' in text:
        raise ValueError('unsupported_yaml')
    return text


def markdown(raw):
    """Bounded YAML data: maps/lists/scalars and |/> blocks with -/+ chomping.

    Block indentation is inferred from its first nonblank line. Explicit numeric
    indentation indicators, tags, anchors and complex keys remain unsupported.
    Comments outside blocks are ignored; block contents are literal prompt data.
    """
    text = raw.decode('utf-8')
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('missing_frontmatter')
    try:
        end = lines.index('---', 1)
    except ValueError:
        raise ValueError('invalid_frontmatter') from None
    tokens = []
    i = 1
    while i < end:
        line = lines[i]
        i += 1
        if '\t' in line:
            raise ValueError('unsupported_yaml')
        if line.strip() and not line.lstrip().startswith('#'):
            indent = len(line) - len(line.lstrip())
            header = re.fullmatch(r'(.*?: )([|>])([-+]?)(?: +#.*)?', line.lstrip())
            if header:
                content, content_indent = [], None
                while i < end:
                    child = lines[i]
                    if child.strip() and len(child) - len(child.lstrip()) <= indent:
                        break
                    if '\t' in child:
                        raise ValueError('unsupported_yaml')
                    if child.strip() and content_indent is None:
                        content_indent = len(child) - len(child.lstrip())
                    if child.strip() and len(child) - len(child.lstrip()) < content_indent:
                        raise ValueError('invalid_frontmatter')
                    content.append(child); i += 1
                content_indent = content_indent if content_indent is not None else indent + 1
                content = [c[content_indent:] if c.strip() else '' for c in content]
                value, previous = '', ''
                for n, child in enumerate(content):
                    separator = '\n'
                    if header[2] == '>' and n + 1 < len(content):
                        following = content[n + 1]
                        if child and following and not child.startswith(' ') and not following.startswith(' '):
                            separator = ' '
                        elif (not child and following and not following.startswith(' ')
                              and previous and not previous.startswith(' ')):
                            separator = ''
                    value += child + separator
                    if child:
                        previous = child
                if header[3] != '+':
                    value = value.rstrip('\n') + ('\n' if content and any(content) and header[3] != '-' else '')
                line = header[1] + json.dumps(value, ensure_ascii=False)
            tokens.append((indent, line.lstrip()))

    def block(i, indent, level=0):
        if level > MAX_DEPTH:
            raise ValueError('depth_limit')
        sequence = tokens[i][1].startswith('- ')
        result = [] if sequence else {}
        while i < len(tokens) and tokens[i][0] == indent:
            text = tokens[i][1]
            if sequence:
                if not text.startswith('- '):
                    raise ValueError('invalid_frontmatter')
                value = text[2:]
                if re.match(r'[\w-]+:( |$)', value):
                    # Expand a sequence mapping into an ordinary nested block.
                    tokens[i] = (indent + 2, value)
                    child, i = block(i, indent + 2, level + 1)
                else:
                    child = scalar(value); i += 1
                result.append(child)
                continue
            match = re.fullmatch(r'([A-Za-z_][\w-]*|"[^"\n]+"|\x27[^\x27\n]+\x27):(?: (.*))?', text)
            if not match:
                raise ValueError('unsupported_yaml')
            key, value = match[1].strip('"\x27'), match[2] or ''
            if key in result:
                raise ValueError('duplicate_key')
            i += 1
            if value.startswith(('|', '>')):
                raise ValueError('unsupported_yaml')
            if not value and i < len(tokens) and tokens[i][0] > indent:
                result[key], i = block(i, tokens[i][0], level + 1)
            else:
                result[key] = scalar(value)
        if i < len(tokens) and tokens[i][0] > indent:
            raise ValueError('invalid_frontmatter')
        return result, i

    data, consumed = block(0, 0) if tokens else ({}, 0)
    if consumed != len(tokens) or not isinstance(data, dict):
        raise ValueError('invalid_frontmatter')
    depth(data)
    return data, '\n'.join(lines[end + 1:])


def descriptor(path, access_path=None):
    """Capture the link itself separately from its target. Never read a directory."""
    result = {'path': str(path), 'status': 'unknown', 'mode': None,
              'sha256': None, 'bytes': None, 'link_target': None}
    path = access_path if access_path is not None else path
    try:
        info = path.lstat()
        result['mode'] = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            with parent_fd(path) as (parent, name):
                if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(info):
                    raise ValueError('concurrent_drift')
                target = os.readlink(name, dir_fd=parent)
            result.update(status='alias', link_target=target, sha256=sha(os.fsencode(target)),
                          bytes=len(os.fsencode(target)))
        elif getattr(info, 'st_file_attributes', 0) & 0x400:
            result.update(status='unsupported_alias')
            try:
                result['link_target'] = os.readlink(path)
            except OSError:
                pass
        elif stat.S_ISREG(info.st_mode):
            raw = read(path)
            result.update(status='file', sha256=sha(raw), bytes=len(raw))
        else:
            result['status'] = 'unsafe_file'
    except FileNotFoundError:
        result['status'] = 'absent'
    except (OSError, ValueError, RuntimeError) as exc:
        result['status'] = 'unreadable' if isinstance(exc, OSError) else 'invalid'
    return result


def evidence(items):
    if not isinstance(items, list) or len(items) > MAX_ENTRIES:
        raise ValueError('invalid_agent_evidence')
    checked = []
    for item in items:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256'}
                or not isinstance(item['sha256'], str) or not DIGEST.fullmatch(item['sha256'])):
            raise ValueError('invalid_agent_evidence')
        checked.append((absolute(item['path']), item['sha256']))
    if not checked:
        return 'unknown'
    state = 'bound'
    for path, expected in checked:
        try:
            if sha(read(path)) != expected:
                state = 'stale'
        except (OSError, ValueError, RuntimeError):
            state = 'unreadable'
    return state


def records(value, keys, required=()):
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        raise ValueError('invalid_agent_records')
    for item in value:
        if not isinstance(item, dict) or set(item) - set(keys) or set(required) - set(item):
            raise ValueError('invalid_agent_record')
    return value


def profiles():
    data = json_data(read(Path(__file__).resolve().parents[1] / 'references/native-agent-formats-v1.json'))
    if data['schema_version'] != 1:
        raise ValueError('unsupported_agent_formats')
    return data['profiles']


def validate(provider, *, require_identity=True):
    """Validate all v2 fields even when discovery is unsupported or unavailable."""
    keys = {'provider_instance_id', 'runtime_version', 'surfaces', 'skill_roots',
            'reads_shared_skills', 'adapter', 'agent_roots', 'agent_configs',
            'read_paths', 'ownership_receipts', 'caller_references', 'assessments'}
    if set(provider) - keys:
        raise ValueError('invalid_agent_provider')
    if require_identity and (not isinstance(provider.get('provider_instance_id'), str)
                             or not provider['provider_instance_id'].strip()):
        raise ValueError('invalid_provider_instance_id')
    if not isinstance(provider.get('adapter'), str):
        raise ValueError('invalid_agent_adapter')
    for field in ('agent_roots', 'agent_configs'):
        for item in records(provider.get(field, []), {'path', 'scope', 'format'}, {'path', 'scope', 'format'}):
            absolute(item['path'])
            if item['scope'] not in SCOPES or item['format'] not in {'markdown', 'json', 'jsonc'}:
                raise ValueError('invalid_agent_surface')
            if (field == 'agent_roots') != (item['format'] == 'markdown'):
                raise ValueError('invalid_agent_surface')
    if (not isinstance(provider.get('read_paths', []), list)
            or len(provider.get('read_paths', [])) > MAX_ENTRIES):
        raise ValueError('invalid_agent_read_paths')
    for path in provider.get('read_paths', []):
        absolute(path)
    evidence(provider.get('ownership_receipts', []))
    callers = provider.get('caller_references', {})
    if (not isinstance(callers, dict) or set(callers) - {'state', 'evidence', 'names'}
            or callers.get('state', 'unknown') not in {'complete', 'unknown'}
            or not isinstance(callers.get('names', []), list)
            or any(not isinstance(n, str) or not n for n in callers.get('names', []))):
        raise ValueError('invalid_caller_references')
    evidence(callers.get('evidence', []))
    for item in records(provider.get('assessments', []),
                        {'path', 'disposition', 'reason', 'evidence'}, {'path', 'disposition', 'reason', 'evidence'}):
        absolute(item['path'])
        if item['disposition'] not in DISPOSITIONS or not isinstance(item['reason'], str) or not item['reason'].strip():
            raise ValueError('invalid_agent_assessment')
        evidence(item['evidence'])
    if len({a['path'] for a in provider.get('assessments', [])}) != len(provider.get('assessments', [])):
        raise ValueError('duplicate_agent_assessment')


def ownership(spec, item):
    """Detached hash-bound receipts can describe provenance, never adopt a name.

    A verified row also needs unchanged owning-source bytes. Mode/link changes
    invalidate ownership. Multiple claims remain ambiguous, even identical ones.
    """
    claims = []
    for supplied in spec.get('ownership_receipts', []):
        if evidence([supplied]) != 'bound':
            claims.append({'status': 'stale-receipt'})
            continue
        try:
            data = json_data(read(absolute(supplied['path'])))
            if (not isinstance(data, dict) or data.get('schema_version') != 1
                    or not isinstance(data.get('owner'), str) or not data['owner']
                    or not isinstance(data.get('items'), list)):
                raise ValueError('invalid_receipt')
            for claim in data['items']:
                if (not isinstance(claim, dict) or set(claim) != {'path', 'sha256', 'mode', 'link_target', 'source', 'kind', 'content_sha256'}
                        or claim['kind'] not in {'native', 'primary-adapter', 'repo-worker', 'role', 'vendor'}
                        or type(claim['mode']) is not int or not 0 <= claim['mode'] <= 0o7777
                        or not isinstance(claim['sha256'], str) or not DIGEST.fullmatch(claim['sha256'])
                        or claim['link_target'] is not None and not isinstance(claim['link_target'], str)
                        or claim['content_sha256'] is not None and (not isinstance(claim['content_sha256'], str)
                            or not DIGEST.fullmatch(claim['content_sha256']))):
                    raise ValueError('invalid_receipt')
                absolute(claim['path'])
                evidence([claim['source']])
                if claim['path'] != item['path']:
                    continue
                bound = evidence([claim['source']]) == 'bound'
                same = all(claim[k] == item[k] for k in ('sha256', 'mode', 'link_target', 'content_sha256'))
                claims.append({'owner': data['owner'], 'kind': claim['kind'], 'source': claim['source'],
                               'receipt': supplied, 'status': 'verified' if same and bound else 'modified'})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            claims.append({'status': 'invalid-receipt'})
    if len(claims) > 1:
        return {'status': 'ambiguous', 'claims': claims}
    return claims[0] if claims else {'status': 'unmanaged'}


def metadata(data, body, adapter, default_mode=None):
    if not isinstance(data, dict):
        raise ValueError('invalid_agent_definition')
    # system is prompt text only. YAML/JSON containers, booleans, null and numbers
    # are invalid definitions, never Python repr converted into instructions.
    for key in ('name', 'description', 'mode', 'permissionMode', 'system'):
        if key in data and not isinstance(data[key], str):
            raise ValueError('invalid_agent_definition')
    for key in ('hidden', 'disabled'):
        if key in data and type(data[key]) is not bool:
            raise ValueError('invalid_agent_definition')
    mode = data.get('mode', default_mode or ('primary' if adapter == 'opencode' else 'subagent'))
    if mode not in {'primary', 'subagent', 'all'}:
        raise ValueError('invalid_agent_mode')
    if adapter == 'opencode' and set(data) & {'agent', 'permission', 'prompt', 'disable', 'tools', 'maxSteps'}:
        raise ValueError('mixed_agent_format')
    # Presence is a deterministic signal, not a semantic assessment of a prompt.
    prompt = body + ('\n' if body and data.get('system') else '') + data.get('system', '')
    permissions = data.get('permissions', [])
    if adapter == 'opencode' and not isinstance(permissions, list):
        raise ValueError('invalid_agent_permissions')
    if adapter == 'opencode' and any(not isinstance(p, dict) or set(p) != {'action', 'resource', 'effect'}
            or any(not isinstance(p[k], str) for k in p) or p['effect'] not in {'ask', 'allow', 'deny'}
            for p in permissions):
        raise ValueError('invalid_agent_permissions')
    return {'mode': mode, 'hidden': data.get('hidden', False), 'disabled': data.get('disabled', False),
            'authority_granted': False,
            'model_override': 'model' in data, 'permission_override': any(
                k in data for k in ('permissions', 'permissionMode', 'tools', 'disallowedTools')),
            'delegation_directive': bool(re.search(r'\b(delegate|delegation|subagents?|orchestrat\w*)\b', prompt, re.I))
                or any(isinstance(p, dict) and p.get('action') == 'subagent' for p in permissions),
            'hooks_present': 'hooks' in data, 'prompt_bytes': len(prompt.encode('utf-8'))}


def discover(spec, profile, index):
    items, surfaces = [], []
    roots = [absolute(r['path']) for r in spec.get('agent_roots', [])]
    roots_resolved = [p.resolve() for p in roots]
    allowed = {absolute(p).resolve() for p in spec.get('read_paths', [])}
    configs = spec.get('agent_configs', [])
    allowed.update(absolute(c['path']).resolve() for c in configs)
    default_refs = []
    entry_count = 0

    def within(path):
        return path in allowed or any(path.is_relative_to(root) for root in roots_resolved)

    def add_file(path, access_path, surface, name, role=False):
        captured = descriptor(path, access_path)
        row = {'provider': index, 'name': name, 'scope': surface['scope'], 'original': captured,
               'path': str(path), 'format': 'markdown', 'status': captured['status'],
               'configured': 'unknown', 'loaded': 'unverified', 'exercised': 'not-run',
               'classification': 'portable-role' if role else 'custom-definition', 'metadata': {}}
        items.append(row)
        try:
            if captured['status'] == 'alias':
                try:
                    resolved = access_path.resolve(strict=True)
                except FileNotFoundError:
                    row['status'] = 'broken-alias'; return
                if not within(resolved):
                    row['status'] = 'alias-target-out-of-scope'; return
                row['alias_target'] = str(resolved)
                expected = file_identity(resolved)
            elif captured['status'] != 'file':
                return
            else:
                resolved, expected = access_path, file_identity(access_path)
            raw = read(resolved, expected=expected)
            row['content'] = {'sha256': sha(raw), 'bytes': len(raw)}
            if (descriptor(path, access_path) != captured or file_identity(resolved) != expected
                    or path.resolve(strict=True) != resolved
                    or captured['status'] == 'file' and sha(raw) != captured['sha256']):
                raise ValueError('concurrent_drift')
            if role:
                text = raw.decode('utf-8')
                data, body = markdown(raw) if text.startswith('---\n') else ({}, text)
            else:
                data, body = markdown(raw)
                if spec.get('adapter') == 'claude':
                    if not data.get('name') or not data.get('description'):
                        raise ValueError('invalid_agent_definition')
                    row['name'] = data['name']
            default_mode = profile.get('builtin_modes', {}).get(row['name']) if profile and not role else None
            row['metadata'] = metadata(data, body, 'role' if role else spec.get('adapter'), default_mode)
            row.update(status='parsed', configured='disabled' if row['metadata']['disabled'] else 'configured')
        except FileNotFoundError:
            row['status'] = 'broken-alias' if captured['status'] == 'alias' else 'absent'
        except PermissionError:
            row['status'] = 'unreadable'
        except OSError:
            row['status'] = 'unreadable'
        except (ValueError, RuntimeError, RecursionError) as exc:
            row['status'] = 'invalid'
            row['error'] = str(exc) if str(exc) in {'size_limit', 'depth_limit', 'unsupported_yaml',
                'missing_frontmatter', 'invalid_frontmatter', 'duplicate_key', 'mixed_agent_format',
                'invalid_agent_permissions', 'invalid_agent_mode', 'invalid_agent_definition',
                'concurrent_drift', 'secure_read_unavailable'} else 'invalid_syntax'

    def walk(root, access_root, surface, level=0, prefix=''):
        nonlocal entry_count
        if level > 8:
            raise ValueError('agent_directory_depth_limit')
        # Read only one directory at a time; never follow child directory aliases.
        if os.scandir not in os.supports_fd:
            raise ValueError('secure_read_unavailable')
        with parent_fd(access_root / '.inventory-child') as (directory, _):
            with os.scandir(directory) as entries:
                names = []
                for entry in entries:
                    names.append(entry.name)
                    entry_count += 1
                    if entry_count > MAX_ENTRIES:
                        raise ValueError('agent_entry_limit')
        for name in sorted(names):
            path = root / name
            access_path = access_root / name
            if alias(access_path) or path.suffix == '.md':
                add_file(path, access_path, surface, prefix + path.stem, surface.get('role', False))
            elif access_path.is_dir():
                walk(path, access_path, surface, level + 1, prefix + name + '/')

    for surface, access_root in zip(spec.get('agent_roots', []), roots_resolved):
        path = absolute(surface['path'])
        row = {'path': str(path), 'scope': surface['scope'], 'kind': 'root', 'status': 'observed',
               'root_alias': alias(path)}
        surfaces.append(row)
        try:
            # Explicit root links are trusted read aliases, resolved once. Child
            # directory links are never traversed; canonical opens refuse swaps.
            walk(path, access_root, surface)
        except FileNotFoundError:
            row['status'] = 'broken-alias' if path.is_symlink() else 'absent'
        except OSError:
            row['status'] = 'unreadable'
        except (ValueError, RuntimeError) as exc:
            row.update(status='invalid', error=str(exc))
    for surface in configs:
        path = absolute(surface['path'])
        original = descriptor(path)
        row = {'path': str(path), 'scope': surface['scope'], 'kind': 'config', 'status': 'unknown',
               'original': original}
        surfaces.append(row)
        try:
            if original['status'] not in {'file', 'alias'}:
                row['status'] = original['status']; continue
            resolved = path.resolve(strict=True)
            if resolved not in allowed:
                raise ValueError('concurrent_drift')
            expected = file_identity(resolved)
            raw = read(resolved, expected=expected)
            data = json_data(raw, surface['format'] == 'jsonc')
            if not isinstance(data, dict):
                raise ValueError('invalid_config')
            if spec['adapter'] == 'opencode':
                if set(data) & {'agent', 'permission'}:
                    raise ValueError('mixed_agent_format')
                agents = data.get('agents', {})
                default = data.get('default_agent')
                if default is not None:
                    if not isinstance(default, str) or not default:
                        raise ValueError('invalid_default_agent')
                    default_refs.append({'name': default, 'scope': surface['scope'], 'path': str(path)})
            else:
                # Explicit --agents/managed capture, not a guessed settings key.
                agents = data
                if surface['scope'] not in {'session', 'managed'}:
                    raise ValueError('unsupported_config_surface')
            if not isinstance(agents, dict) or len(agents) > MAX_ENTRIES:
                raise ValueError('invalid_agents')
            pending = []
            for name, agent in sorted(agents.items()):
                if not isinstance(name, str) or not name:
                    raise ValueError('invalid_agents')
                meta = metadata(agent, '', spec['adapter'], profile.get('builtin_modes', {}).get(name))
                pending.append({'provider': index, 'name': name, 'path': str(path),
                    'scope': surface['scope'], 'format': surface['format'], 'original': original,
                    'content': {'sha256': sha(raw), 'bytes': len(raw)}, 'status': 'parsed',
                    'configured': 'disabled' if meta['disabled'] else 'configured',
                    'loaded': 'unverified', 'exercised': 'not-run',
                    'classification': 'custom-definition', 'metadata': meta})
            if len(items) + len(pending) > MAX_ENTRIES:
                raise ValueError('agent_entry_limit')
            if (descriptor(path) != original or path.resolve(strict=True) != resolved
                    or file_identity(resolved) != expected
                    or original['status'] == 'file' and sha(raw) != original['sha256']):
                raise ValueError('concurrent_drift')
            items.extend(pending)
            row['status'] = 'parsed'
        except FileNotFoundError:
            row['status'] = 'broken-alias' if original['status'] == 'alias' else 'absent'
        except OSError:
            row['status'] = 'unreadable'
        except (ValueError, RuntimeError, RecursionError):
            row['status'] = 'invalid'
    return items, surfaces, default_refs


def assess(items, surfaces, defaults, spec, profile):
    """Conservative source-layer classification and item-by-item proposal."""
    callers = spec.get('caller_references', {})
    caller_binding = evidence(callers.get('evidence', []))
    callers_known = callers.get('state') == 'complete' and caller_binding == 'bound'
    named_callers = set(callers.get('names', []))
    by_name = {}
    for item in items:
        by_name.setdefault(item['name'], []).append(item)
    aliases = {}
    for item in items:
        if item.get('alias_target'):
            aliases.setdefault(item['alias_target'], []).append(item)
    invalid_surfaces = any(s['status'] not in {'parsed', 'observed'} for s in surfaces)
    default_names = {d['name'] for d in defaults}
    for item in items:
        native = item['classification'] != 'portable-role'
        own = ownership(spec, dict(item['original'], content_sha256=item.get('content', {}).get('sha256')))
        item['ownership'] = own
        if own.get('status') == 'verified':
            item['classification'] = {'repo-worker': 'repo-managed-worker', 'vendor': 'vendor-content',
                                      'primary-adapter': 'primary-adapter', 'role': 'portable-role'}.get(
                                          own['kind'], item['classification'])
        if native and item['scope'] == 'vendor' and own['status'] == 'unmanaged':
            item['classification'] = 'vendor-content'
        siblings = by_name[item['name']]
        collision = len(siblings) > 1
        builtin = native and profile and item['name'] in profile['builtins']
        item['builtin_collision'] = bool(builtin)
        item['collision'] = collision
        item['ambiguous_alias'] = len(aliases.get(item.get('alias_target'), [])) > 1
        item['linked_parents'] = any(alias(p) for p in absolute(item['path']).parents)
        item['effective_layer'] = 'unknown'
        if not invalid_surfaces and item['status'] == 'parsed':
            ranks = profile['precedence'] if profile else ['shared', 'global', 'project']
            if all(s['scope'] in ranks for s in siblings):
                top = max(ranks.index(s['scope']) for s in siblings)
                winners = [s for s in siblings if ranks.index(s['scope']) == top]
                if spec.get('adapter') == 'opencode' and (collision or builtin):
                    item['effective_layer'] = 'merge-required'
                elif len(winners) == 1:
                    item['effective_layer'] = 'candidate' if item is winners[0] else 'shadowed'
                else:
                    item['effective_layer'] = 'ambiguous'
        referenced = item['name'] in default_names or item['name'] in named_callers
        item['references'] = {'default_agent': item['name'] in default_names,
                              'known_caller': item['name'] in named_callers,
                              'coverage': 'bound-declaration' if callers_known else 'unknown'}
        item['automatic_eligibility'] = False
        item['followup_operation'] = None
        item['preservation'] = {'required': True, 'original': item['original'],
                                'content': item.get('content'), 'source': own.get('source')}
        item['revalidation'] = ['recapture all destinations and caller/default references before any write',
            'verify owning source, receipt, bytes, mode and link target are unchanged',
            'refuse linked write parents and concurrent drift',
            'create exclusive verified backups outside checkouts before replacement or removal',
            'preserve unknown content and report partial completion; never restore over drift']
        disposition, reason = 'preserve-unmanaged', 'No verified ownership; preserve the object.'
        if (item['status'] != 'parsed' or collision or builtin or invalid_surfaces or item['ambiguous_alias']
                or item['effective_layer'] != 'candidate'
                or item['linked_parents'] or own['status'] in {
                'modified', 'ambiguous', 'invalid-receipt', 'stale-receipt'}):
            disposition, reason = 'unresolved', 'Discovery, ownership, collision or layer evidence is incomplete.'
        elif item['classification'] in {'vendor-content'}:
            disposition, reason = 'preserve-unmanaged', 'Vendor content remains outside managed retirement.'
        elif item['metadata'].get('hidden') or referenced or item['metadata'].get('mode') in {'primary', 'all'} and native:
            disposition, reason = 'keep-as-native-exception', 'Preserve a hidden, primary-capable or referenced native entrypoint.'
        elif item['classification'] in {'portable-role', 'repo-managed-worker'}:
            disposition, reason = 'keep', 'Retain the portable expertise or T3-owned worker without a native copy.'
        elif own['status'] == 'verified':
            reason = 'Verified ownership; preserve the object pending a bound assessment.'
        for request in spec.get('assessments', []):
            if request['path'] != item['path']:
                continue
            item['assessment_evidence'] = request['evidence']
            eligible = (disposition not in {'unresolved', 'keep-as-native-exception', 'preserve-unmanaged'}
                        or own['status'] == 'verified' and disposition == 'preserve-unmanaged')
            if (evidence(request['evidence']) != 'bound' or not eligible or not callers_known
                    or referenced or builtin or collision or item['metadata'].get('hidden')
                    or item['classification'] in {'vendor-content', 'repo-managed-worker'}):
                item['assessment_status'] = 'refused'
                continue
            requested = request['disposition']
            if requested == 'retire-managed-alias':
                if (own['status'] != 'verified' or item['original']['status'] != 'alias'
                        or item['classification'] == 'portable-role'):
                    item['assessment_status'] = 'refused'; continue
                item['automatic_eligibility'] = True
                item['followup_operation'] = 'review one owned alias unlink in its owning repository; no apply operation exists here'
            elif requested == 'extract-role':
                item['followup_operation'] = 'review expertise extraction in the owning repository; grant no tools or actions'
            disposition, reason = requested, 'Bound operator assessment; intent and semantic equivalence require review.'
            item['assessment_status'] = 'bound-declaration'
        item['disposition'], item['reason'] = disposition, reason
    def default_available(name):
        if invalid_surfaces or profile and name in profile['maintenance']:
            return False
        layers = by_name.get(name, [])
        if layers:
            # Do not infer an effective merge from one usable layer when another
            # supplied layer disables, hides or restricts the same entrypoint.
            return all(s['status'] == 'parsed' and not s['metadata'].get('disabled')
                       and not s['metadata'].get('hidden')
                       and s['metadata'].get('mode') in {'primary', 'all'} for s in layers)
        return bool(profile and profile.get('builtin_modes', {}).get(name) in {'primary', 'all'})

    return [{'name': d['name'], 'path': d['path'], 'scope': d['scope'],
             'status': 'resolved-in-supplied-layers' if default_available(d['name'])
             else 'missing-default-agent'} for d in defaults]


def unmatched_assessments(items, spec, findings, location):
    """Refuse each undiscovered path without publishing it or operator text."""
    paths = {item['path'] for item in items}
    refused = []
    for index, request in enumerate(spec.get('assessments', [])):
        if request['path'] in paths:
            continue
        findings.append({'code': 'agent_assessment_refused',
                         'location': f'{location}.assessments[{index}]'})
        refused.append({'assessment': index, 'path': request['path'],
                        'requested_disposition': request['disposition'], 'status': 'refused',
                        'reason': 'No discovered item matches the supplied path.',
                        'automatic_eligibility': False})
    return refused


def inspect(catalog, inventory):
    """Return a redacted report and private, deterministic plan for wiring v2."""
    if inventory.get('version') != 2:
        raise ValueError('unsupported_agent_inventory')
    allowed = {'version', 'authorities', 'providers', 'shared_skills', 'role_roots', 'role_evidence'}
    if set(inventory) - allowed:
        raise ValueError('invalid_agent_inventory')
    specs = inventory.get('providers', [])
    if not isinstance(specs, list):
        raise ValueError('invalid_agent_providers')
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError('invalid_agent_provider')
        validate(spec)
    identities = [spec['provider_instance_id'] for spec in specs]
    if len(identities) != len(set(identities)):
        raise ValueError('duplicate_provider_instance_id')
    role_roots = records(inventory.get('role_roots', []), {'path', 'scope'}, {'path', 'scope'})
    for root in role_roots:
        absolute(root['path'])
        if root['scope'] not in {'shared', 'global', 'project'}:
            raise ValueError('invalid_role_scope')
    formats = profiles()
    indexed = {s['provider_instance_id']: s for s in specs}
    providers, private, findings, fatal = [], [], [], False
    for index, provider in enumerate(catalog['providers']):
        spec = indexed.get(provider['providerInstanceId'])
        profile = formats.get(spec['adapter']) if spec else None
        version = spec.get('runtime_version') if spec else None
        supported = bool(profile and version in profile['versions'])
        state = 'unknown' if not version else 'supported' if supported else 'unsupported'
        items, surfaces, defaults = discover(spec, profile, index) if supported else ([], [], [])
        refs = assess(items, surfaces, defaults, spec, profile) if spec else []
        builtins = [{'name': n, 'classification': 'runtime-builtin', 'disposition': 'keep',
                     'mode': profile.get('builtin_modes', {}).get(n),
                     'hidden_maintenance': n in profile['maintenance'], 'automatic_eligibility': False,
                     'configured': 'documented-builtin', 'loaded': 'unverified', 'exercised': 'not-run',
                     'source': profile['documentation']} for n in profile['builtins']] if supported else []
        row = {'provider': index, 'catalog_runnable': provider.get('canRunChildTask') is True,
               'catalog_disabled': provider.get('enabled') is False or provider.get('disabled') is True,
               'discovery': state, 'configured': 'supplied-paths-only', 'loaded': 'unverified',
               'exercised': 'not-run', 'items': [], 'surfaces': [], 'builtin_count': len(builtins),
               'builtins': [{k: v for k, v in b.items() if k not in {'name', 'source'}} for b in builtins]}
        if state != 'supported':
            findings.append({'code': 'agent_discovery_' + state, 'location': f'wiring.providers[{index}].orchestration'})
        if supported and not surfaces:
            findings.append({'code': 'agent_roots_unknown', 'location': f'wiring.providers[{index}].orchestration'})
        for number, surface in enumerate(surfaces):
            row['surfaces'].append({'surface': number, 'status': surface['status'], 'kind': surface['kind']})
            if surface['status'] not in {'parsed', 'observed'}:
                findings.append({'code': 'agent_surface_' + surface['status'],
                                 'location': f'wiring.providers[{index}].orchestration.sources[{number}]'})
                fatal |= surface['status'] in {'invalid', 'unreadable'}
        for number, item in enumerate(items):
            public = {k: item[k] for k in ('status', 'scope', 'classification', 'configured', 'loaded',
                'exercised', 'metadata', 'effective_layer', 'collision', 'builtin_collision', 'disposition',
                'automatic_eligibility')}
            public.update(item=number, ownership=item['ownership']['status'],
                          source_bytes=item.get('content', {}).get('bytes'))
            row['items'].append(public)
            if item['disposition'] in {'unresolved', 'preserve-unmanaged'} or item.get('assessment_status') == 'refused':
                findings.append({'code': 'agent_' + ('assessment_refused' if item.get('assessment_status') == 'refused'
                                                   else item['disposition'].replace('-', '_')),
                                 'location': f'wiring.providers[{index}].orchestration.items[{number}]'})
            fatal |= item['status'] in {'invalid', 'unreadable', 'unsafe_file'}
        for number, reference in enumerate(refs):
            if reference['status'] == 'missing-default-agent':
                findings.append({'code': 'missing_default_agent',
                                 'location': f'wiring.providers[{index}].orchestration.defaults[{number}]'})
        refused = unmatched_assessments(items, spec or {}, findings,
                                       f'wiring.providers[{index}].orchestration')
        providers.append(row)
        private.append({'provider': index, 'discovery': state, 'items': items, 'sources': surfaces,
                        'assessment_refusals': refused,
                        'default_references': refs, 'builtins': builtins,
                        'caller_references': spec.get('caller_references', {}) if spec else {},
                        'scope_limit': 'No provider launch, implicit path discovery, transcript scan or runtime loading proof.'})
    role_evidence = inventory.get('role_evidence', {})
    if not isinstance(role_evidence, dict) or set(role_evidence) - {
            'ownership_receipts', 'assessments', 'caller_references', 'read_paths'}:
        raise ValueError('invalid_role_evidence')
    role_spec = dict(role_evidence, adapter='portable',
                     agent_roots=[dict(r, format='markdown') for r in role_roots])
    validate(role_spec, require_identity=False)
    role_spec['agent_roots'] = [dict(r, role=True) for r in role_spec['agent_roots']]
    roles, role_surfaces, _ = discover(role_spec, None, None)
    assess(roles, role_surfaces, [], role_spec, None)
    role_refused = unmatched_assessments(roles, role_spec, findings, 'wiring.role_evidence')
    for number, role in enumerate(roles):
        if role['status'] != 'parsed':
            findings.append({'code': 'role_' + role['status'], 'location': f'wiring.roles[{number}]'})
            fatal |= role['status'] in {'invalid', 'unreadable', 'unsafe_file'}
    for number, surface in enumerate(role_surfaces):
        if surface['status'] != 'observed':
            findings.append({'code': 'role_root_' + surface['status'], 'location': f'wiring.role_roots[{number}]'})
            fatal |= surface['status'] in {'invalid', 'unreadable'}
    if not role_roots:
        findings.append({'code': 'role_roots_unknown', 'location': 'wiring.roles'})
    plan = {'schema_version': 1, 'kind': 'agent-normalization-plan', 'wiring_version': 2,
            'providers': private, 'roles': roles, 'role_sources': role_surfaces,
            'role_assessment_refusals': role_refused,
            'writes': 0, 'authorization': 'not-granted', 'apply_supported': False,
            'followup_owner': 'owning repository; dotfiles retains dotfiles profiles and published roles',
            'revalidation': 'Rerun this same v2 inventory and compare the complete plan before a separately reviewed migration.'}
    plan['inventory_sha256'] = sha(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode())
    plan['catalog_sha256'] = sha(json.dumps(catalog, sort_keys=True, separators=(',', ':')).encode())
    plan['plan_sha256'] = sha(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode())
    return {'version': 2, 'coverage': 'explicit-paths-only', 'providers': providers,
            'roles': [{'item': i, 'status': r['status'], 'classification': r['classification'],
                       'disposition': r['disposition'], 'metadata': r['metadata']} for i, r in enumerate(roles)],
            'findings': findings, 'fatal': fatal, 'normalization': 'proposal-only', 'writes': 0,
            'loading': 'unverified', 'exercise': 'not-run', 'plan_sha256': plan['plan_sha256']}, plan


def revalidate(previous, current):
    if (not isinstance(previous, dict) or previous.get('kind') != 'agent-normalization-plan'
            or previous != current):
        raise ValueError('stale_agent_plan')
