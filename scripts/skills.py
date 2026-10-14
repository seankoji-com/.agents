"""Managed skill adapters for T3's provider-specific discovery roots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

import install as installer
from core.jobs.store import trusted_link  # importing install puts the repository root on sys.path

MARKER = '.t3-plugins-skill.json'
# Codex reads picker metadata from agents/openai.yaml beside SKILL.md. The receipt
# owns it by relative path, so only these names can ever be replaced or removed.
OPENAI_YAML = 'agents/openai.yaml'
OWNED_EXTRAS = (OPENAI_YAML,)


def safe_path(path):
    path = Path(path).expanduser().absolute()
    for part in [*reversed(path.parents), path]:
        if part.is_symlink() and not trusted_link(part):
            raise ValueError(f'skill path contains a symlink: {part}')
    return path


def metadata_fields(meta):
    """Frontmatter metadata for the generated adapter. Agent Skills defines
    metadata as a flat string-to-string map, so everything beyond name and
    description lives inside it and the top level stays within the portable
    six-field spec. A structured origin is flattened onto namespaced keys.
    OpenCode's documented metadata keys carry the invocation policy: every
    adapter is user-invocable as a /name command, and each plugin that is not
    model-invocable stays out of model auto-selection."""
    values = {}
    for key in ('version', 'kind', 'compatibility'):
        if meta.get(key) is not None:
            values['t3-plugins-' + key] = str(meta[key])
    origin = meta.get('origin')
    if origin:
        for key in ('repository', 'plugin', 'version'):
            if origin.get(key) is not None:
                values['t3-plugins-origin-' + key] = str(origin[key])
    values['opencode/slash'] = 'true'
    if not meta.get('model_invocable', False):
        values['opencode/autoinvoke'] = 'false'
    return values


def render(meta, entry):
    # Pickers expose the description across providers; keep argument syntax there
    # rather than relying on a provider-specific argument-hint frontmatter field.
    description = meta['description']
    if meta.get('argument_hint'):
        description += ' Args: ' + meta['argument_hint'] + '.'
    # JSON strings are valid quoted YAML scalars. Descriptions may contain colons.
    header = ['---', 'name: t3-' + meta['name'], 'description: ' + json.dumps(description)]
    metadata = metadata_fields(meta)
    if metadata:
        header.append('metadata:')
        header.extend('  ' + key + ': ' + json.dumps(value) for key, value in metadata.items())
    header.append('---')
    return ('\n'.join(header) + '\n\n# ' + meta['name'] + ' in T3 Code\n\n'
            'Read the installed entry file at ' + json.dumps(str(entry)) + ' and follow it.\n'
            'The package directory is the directory containing that entry file.\n'
            'Use the text after the skill mention as the operation and arguments. Operations: ' +
            ', '.join('`' + op + '`' for op in meta['operations']) + '.\n'
            'With no arguments, run `doctor`.\n' +
            ('For imps, a task without an operation means `run <task>`.\n' if meta['name'] == 'imps' else '') +
            'If the entry is missing, report that this adapter needs `t3-plugins install ' + meta['name'] +
            '` using the same package prefix; do not switch to another ' + meta['name'] + ' installation.\n'
            'This adapter grants no additional authorization. T3 owns delegation and watches.\n')


def openai_yaml(meta):
    """Codex picker metadata. JSON strings are valid double-quoted YAML scalars.
    A manifest `short_description` keeps the picker blurb short; otherwise the
    description is used as written."""
    name = 't3-' + meta['name']
    interface = {
        'display_name': 'T3 ' + meta['name'].replace('-', ' ').title(),
        'short_description': meta.get('short_description') or meta['description'],
        'default_prompt': 'Use $' + name + ' with one operation: ' + ', '.join(meta['operations']) + '.',
    }
    return ('interface:\n' + ''.join(f'  {key}: {json.dumps(value)}\n' for key, value in interface.items())).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.t3-skill-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def managed(directory, name, pending=None):
    """Verify the marker owns an unmodified adapter. `pending` maps owned files to
    the digests an install is about to write; a file already holding those bytes
    is the trace of an interrupted install, not an edit."""
    pending = pending or {}
    marker = directory / MARKER
    skill = directory / 'SKILL.md'
    if not marker.is_file() or marker.is_symlink() or skill.is_symlink():
        raise ValueError(f'refusing an unowned skill directory: {directory}')
    receipt = json.loads(marker.read_text())
    if (not isinstance(receipt, dict) or receipt.get('schema_version') != 1 or receipt.get('name') != name
            or digest(skill.read_bytes()) not in (receipt.get('sha256'), pending.get('SKILL.md'))):
        raise ValueError(f'refusing a modified or invalid skill adapter: {directory}')
    # Receipts written before extras existed have no `files`; they own SKILL.md only.
    files = receipt.get('files', {})
    if not isinstance(files, dict) or not set(files) <= set(OWNED_EXTRAS):
        raise ValueError(f'refusing a modified or invalid skill adapter: {directory}')
    for relative, sha in files.items():
        path = extra_path(directory, relative)
        if path.exists() and digest(path.read_bytes()) not in (sha, pending.get(relative)):
            raise ValueError(f'refusing a modified skill adapter file: {path}')
    return receipt


def extra_path(directory, relative):
    path = directory / relative
    for part in (path.parent, path):
        if part.is_symlink():
            raise ValueError(f'skill adapter path is a symlink: {part}')
    if path.exists() and not path.is_file():
        raise ValueError(f'skill adapter path is not a file: {path}')
    return path


def remove_owned(directory, receipt):
    """Remove the adapter files the verified receipt owns and any directory
    left empty by that. Operator files stay."""
    for relative in receipt.get('files', {}):
        path = extra_path(directory, relative)
        path.unlink(missing_ok=True)
        if path.parent != directory and path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    (directory / 'SKILL.md').unlink()
    (directory / MARKER).unlink()


def install(root, prefix, meta):
    root = safe_path(root)
    name = 't3-' + meta['name']
    directory = safe_path(root / name)
    current = prefix / meta['name'] / 'current'
    if not current.is_symlink() or not current.resolve().is_relative_to(current.parent.resolve()):
        raise ValueError(f'install {meta["name"]} before installing its skill adapter')
    manifest = installer.load_manifest(current / installer.MANIFEST)
    if manifest.get('plugin') != meta['name']:
        raise ValueError('installed plugin manifest mismatch')
    for item in manifest['files']:
        path = installer.owned_path(current.resolve(), item['path'])
        if not path.is_file() or installer.sha256(path) != item['sha256']:
            raise ValueError(f'installed plugin is modified: {item["path"]}')
    entry = current / meta['entry']
    if not entry.is_file() or any(ord(c) < 32 for c in str(entry)):
        raise ValueError('invalid installed entry path')
    data = render(meta, entry).encode()
    yaml = openai_yaml(meta)
    pending = {'SKILL.md': digest(data), OPENAI_YAML: digest(yaml)}
    previous = managed(directory, name, pending) if directory.exists() else {}
    receipt = {'schema_version': 1, 'name': name, 'entry': str(entry), 'sha256': digest(data)}
    result = {'name': name, 'path': str(directory / 'SKILL.md'), 'entry': str(entry)}
    directory.mkdir(parents=True, exist_ok=True)
    target = extra_path(directory, OPENAI_YAML)
    # An existing openai.yaml the receipt does not own is the operator's; keep it,
    # unless it is byte-identical to ours (an interrupted earlier install).
    if (target.exists() and OPENAI_YAML not in previous.get('files', {})
            and target.read_bytes() != yaml):
        result['preserved_files'] = [OPENAI_YAML]
    else:
        target.parent.mkdir(exist_ok=True)
        atomic_write(target, yaml)
        receipt['files'] = {OPENAI_YAML: digest(yaml)}
    atomic_write(directory / 'SKILL.md', data)
    atomic_write(directory / MARKER, (json.dumps(receipt, indent=2) + '\n').encode())
    return result


def remove_retired(root, plugin):
    """Remove a retired plugin's adapter only when its own marker proves it is ours
    and unmodified. Anything else is preserved untouched and reported."""
    name = 't3-' + plugin
    try:
        directory = safe_path(root) / name
    except ValueError as exc:
        return {'name': name, 'root': str(root), 'removed': False, 'preserved': str(exc)}
    if not directory.exists() and not directory.is_symlink():
        return None
    receipt = {'name': name, 'root': str(directory.parent), 'removed': False}
    try:
        if directory.is_symlink():
            raise ValueError(f'skill directory is a symlink: {directory}')
        owned = managed(directory, name)
    except (ValueError, OSError) as exc:
        return dict(receipt, preserved=str(exc))
    remove_owned(directory, owned)
    kept = sorted(path.name for path in directory.iterdir())
    if not kept:
        directory.rmdir()
    return dict(receipt, removed=True, kept=kept)


def uninstall(root, meta):
    name = 't3-' + meta['name']
    directory = safe_path(safe_path(root) / name)
    if not directory.exists():
        return {'name': name, 'removed': False}
    remove_owned(directory, managed(directory, name))
    # Preserve anything the operator added to the adapter directory.
    if not any(directory.iterdir()):
        directory.rmdir()
    return {'name': name, 'removed': True}
