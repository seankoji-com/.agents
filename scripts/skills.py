"""Managed skill adapters for T3's provider-specific discovery roots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

import install as installer
from core.jobs.store import trusted_link  # importing install puts the repository root on sys.path

MARKER = '.t3-plugins-skill.json'
# Codex reads picker metadata from agents/openai.yaml beside SKILL.md. The receipt
# owns it by relative path, so only these names can ever be replaced or removed.
OPENAI_YAML = 'agents/openai.yaml'
OWNED_EXTRAS = (OPENAI_YAML,)


def validate_picker(meta):
    """Reject incomplete or ambiguous picker routing before rendering an adapter."""
    operations = meta.get('operations')
    picker = meta.get('picker')
    routes = meta.get('routes')
    standalone_flags = meta.get('standalone_flags', [])
    if (not isinstance(operations, list) or not isinstance(picker, list) or
            not 2 <= len(picker) <= 4 or
            any(not isinstance(op, str) for op in picker) or
            len(set(picker)) != len(picker) or any(op not in operations for op in picker)):
        raise ValueError(f"{meta.get('name', 'plugin')}: picker must contain 2 to 4 unique operation IDs")
    if not isinstance(routes, list):
        raise ValueError(f"{meta.get('name', 'plugin')}: routes must be a list")
    if (not isinstance(standalone_flags, list) or
            any(not isinstance(flag, str) or not re.fullmatch(r'--[A-Za-z0-9][A-Za-z0-9-]*', flag)
                for flag in standalone_flags) or
            len(set(standalone_flags)) != len(standalone_flags)):
        raise ValueError(f"{meta.get('name', 'plugin')}: standalone_flags must be unique long flags")
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'pattern', 'operation'}:
            raise ValueError(f"{meta.get('name', 'plugin')}: route must contain pattern and operation")
        pattern, operation = route['pattern'], route['operation']
        if (not isinstance(pattern, str) or not isinstance(operation, str) or
                operation not in operations):
            raise ValueError(f"{meta.get('name', 'plugin')}: routes must target known operations")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{meta.get('name', 'plugin')}: invalid route pattern") from exc
        # Check the anchors and alternations while respecting escapes and
        # character classes. A closing bracket immediately after `[` or `[^`
        # is a literal class member, not the end of the class.
        if not pattern.startswith('^'):
            raise ValueError(f"{meta.get('name', 'plugin')}: route must start with ^")
        depth = 0
        in_class = False
        escaped = False
        class_first = False
        end_anchor = False
        for index, char in enumerate(pattern[1:], 1):
            was_escaped = escaped
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
                if in_class:
                    class_first = False
            elif char == '[':
                in_class = True
                class_first = True
            elif in_class and class_first and char == '^':
                class_first = False
            elif char == ']' and in_class and not class_first:
                in_class = False
            elif in_class:
                class_first = False
            elif not in_class and char == '(':
                depth += 1
            elif not in_class and char == ')':
                depth -= 1
            elif not in_class and depth == 0 and char == '|':
                raise ValueError(f"{meta.get('name', 'plugin')}: route alternation must be grouped")
            if index == len(pattern) - 1 and char == '$' and not was_escaped and not in_class:
                end_anchor = True
        if not end_anchor:
            raise ValueError(f"{meta.get('name', 'plugin')}: route must end with an unescaped $")


def route(meta, text):
    """Return the first manifest route matching all of the free text, if any."""
    validate_picker(meta)
    text = text.strip()
    if meta.get('standalone_flags'):
        flags = '|'.join(re.escape(flag) for flag in meta['standalone_flags'])
        text = re.sub(r'(?<!\S)(?:' + flags + r')(?!\S)', '', text).strip()
    if not text:
        return None
    for item in meta['routes']:
        if re.fullmatch(item['pattern'], text, re.DOTALL):
            return item['operation']
    return None


def trusted_root_link(root):
    """Whether the root may be followed as a link: only a trusted one, whatever
    the path holds when sampled. An untrusted link swapped in later is refused."""
    return root.is_symlink() and trusted_link(root)


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
    validate_picker(meta)
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
    picker = ', '.join('`' + op + '`' for op in meta['picker'])
    routes = '\n'.join('- `' + route['pattern'] + '` -> `' + route['operation'] + '`'
                        for route in meta['routes'])
    return ('\n'.join(header) + '\n\n# ' + meta['name'] + ' in T3 Code\n\n'
            'Read the installed entry file at ' + json.dumps(str(entry)) + ' and follow it.\n' +
            'The package directory is the directory containing that entry file.\n' +
            ('Use the text after the skill mention as the operation and arguments. '
             if meta['routes'] else '') +
            'Operations: ' + ', '.join('`' + op + '`' for op in meta['operations']) + '.\n'
            "With no request, ask through the host's native question picker. Recommend the first option. " +
            'Do nothing until the owner answers. Options: ' + picker + '.\n'
            + ('For imps, a task without an operation means `run <task>`.\n'
               if meta['name'] == 'imps' else '')
            + ('Ignore standalone flags when choosing the operation.\n'
               if meta.get('standalone_flags') else '')
            + ('For free text, test the full string against these manifest routes in order. '
               'Use the operation from the first matching route. If no route matches, ask which operation to run.\n'
               + routes + '\n' if meta['routes'] else
               'With no route table, ask which operation to run.\n') +
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


# One adapter transaction pins the skill root, the adapter directory and each
# owned subdirectory by descriptor, opened once and without following symlinks.
# Every read, write and unlink happens relative to those descriptors, so a
# directory swapped mid-run (for a link or another directory) cannot redirect a
# write or delete: validation and mutation see the same directories. The root
# follows a link only when safe_path() accepted it as a trusted link; the
# ancestors above it are the caller's choice and are not pinned.
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY
NOFOLLOW_DIR = DIRECTORY | os.O_NOFOLLOW
# O_NONBLOCK keeps a FIFO from blocking the open before the file-type check.
NOFOLLOW_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def mkdir_at(dir_fd, name):
    """Create `name` under `dir_fd`; True only when this call created it."""
    try:
        os.mkdir(name, 0o755, dir_fd=dir_fd)
        return True
    except FileExistsError:
        return False


def read_at(dir_fd, name, label):
    """Bytes of a regular file, or None when absent. Anything else raises."""
    try:
        fd = os.open(name, NOFOLLOW_FILE, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f'skill adapter path is not a plain file: {label}') from exc
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f'skill adapter path is not a plain file: {label}')
        return stream.read()


def write_at(dir_fd, name, data):
    temporary = f'.t3-skill-{os.getpid()}-{secrets.token_hex(4)}'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=dir_fd)
        except FileNotFoundError:
            pass


class Adapter:
    """An adapter directory pinned by descriptor for one install or removal."""

    def __init__(self, directory, create=False, root_is_link=False):
        """`root_is_link` records what safe_path() saw: only a root that was already
        a trusted link when validated may be followed now."""
        self.path, self.root, self.top, self.created, self.subs = directory, None, None, False, {}
        try:
            self.root = os.open(directory.parent, DIRECTORY if root_is_link else NOFOLLOW_DIR)
            made = create and mkdir_at(self.root, directory.name)
            self.top = os.open(directory.name, NOFOLLOW_DIR, dir_fd=self.root)
            # A directory created here and still empty when opened is new. One
            # swapped in after the mkdir is not, and gets the ownership check.
            self.created = bool(made) and not os.listdir(self.top)
        except OSError as exc:
            self.close()
            raise ValueError(f'skill adapter directory is not a plain directory: {directory}') from exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for fd in (*self.subs.values(), self.top, self.root):
            if fd is not None:
                os.close(fd)
        self.subs, self.root, self.top = {}, None, None

    def sub(self, name, create=False):
        """Pinned descriptor of a subdirectory, opened once per transaction, or None
        when absent. Creating one that was absent fails closed unless this call
        made it and it is still empty, so nothing swapped in is ever written to."""
        if name not in self.subs:
            self.subs[name] = self._open_sub(name)
        if self.subs[name] is None and create:
            made = mkdir_at(self.top, name)
            fd = self._open_sub(name)
            try:
                if fd is None or not made or os.listdir(fd):
                    raise ValueError(f'skill adapter directory changed during the run: {self.path / name}')
            except BaseException:
                if fd is not None:
                    os.close(fd)
                raise
            self.subs[name] = fd
        return self.subs[name]

    def _open_sub(self, name):
        try:
            return os.open(name, NOFOLLOW_DIR, dir_fd=self.top)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValueError(f'skill adapter path is not a plain directory: {self.path / name}') from exc

    def read(self, relative):
        if '/' not in relative:
            return read_at(self.top, relative, self.path / relative)
        sub, leaf = relative.split('/')
        fd = self.sub(sub)
        return None if fd is None else read_at(fd, leaf, self.path / relative)

    def write(self, relative, data):
        if '/' not in relative:
            return write_at(self.top, relative, data)
        sub, leaf = relative.split('/')
        write_at(self.sub(sub, create=True), leaf, data)

    def unlink(self, relative):
        """Unlink one owned file; a subdirectory left empty goes too. Operator
        files and anything refilled or replaced meanwhile stay."""
        if '/' not in relative:
            try:
                os.unlink(relative, dir_fd=self.top)
            except FileNotFoundError:
                pass
            return
        sub, leaf = relative.split('/')
        fd = self.sub(sub)
        if fd is None:
            return
        try:
            os.unlink(leaf, dir_fd=fd)
        except FileNotFoundError:
            pass
        if not os.listdir(fd):
            try:
                os.rmdir(sub, dir_fd=self.top)
            except OSError:
                pass

    def entries(self):
        return sorted(os.listdir(self.top))

    def remove_if_empty(self):
        if not os.listdir(self.top):
            try:
                os.rmdir(self.path.name, dir_fd=self.root)
            except OSError:
                pass  # refilled or replaced since the listing: leave it


def managed(adapter, name, pending=None):
    """Verify the marker owns an unmodified adapter. `pending` maps owned files to
    the digests an install is about to write; a file already holding those bytes
    is the trace of an interrupted install, not an edit."""
    pending = pending or {}
    marker, skill = adapter.read(MARKER), adapter.read('SKILL.md')
    if marker is None:
        raise ValueError(f'refusing an unowned skill directory: {adapter.path}')
    receipt = json.loads(marker)
    if (not isinstance(receipt, dict) or receipt.get('schema_version') != 1 or receipt.get('name') != name
            or skill is None or digest(skill) not in (receipt.get('sha256'), pending.get('SKILL.md'))):
        raise ValueError(f'refusing a modified or invalid skill adapter: {adapter.path}')
    # Receipts written before extras existed have no `files`; they own SKILL.md only.
    files = receipt.get('files', {})
    if not isinstance(files, dict) or not set(files) <= set(OWNED_EXTRAS):
        raise ValueError(f'refusing a modified or invalid skill adapter: {adapter.path}')
    for relative, sha in files.items():
        data = adapter.read(relative)
        if data is not None and digest(data) not in (sha, pending.get(relative)):
            raise ValueError(f'refusing a modified skill adapter file: {adapter.path / relative}')
    return receipt


def remove_owned(adapter, receipt):
    """Remove the adapter files the verified receipt owns. Operator files stay."""
    for relative in receipt.get('files', {}):
        adapter.unlink(relative)
    adapter.unlink('SKILL.md')
    adapter.unlink(MARKER)


def interrupted_first_install(adapter, expected):
    """True when a marker-less adapter directory holds only regular files an
    earlier install of these exact bytes wrote before it was interrupted."""
    subdirs = {relative.split('/')[0] for relative in OWNED_EXTRAS}

    def kind(dir_fd, name):
        return stat.S_IFMT(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)

    found = []
    for name in adapter.entries():
        if name == MARKER:
            return False
        if kind(adapter.top, name) == stat.S_IFREG:
            found.append(name)
        elif kind(adapter.top, name) == stat.S_IFDIR and name in subdirs:
            fd = adapter.sub(name)
            if fd is None:
                return False  # vanished since the listing
            for child in os.listdir(fd):
                if kind(fd, child) != stat.S_IFREG:
                    return False
                found.append(f'{name}/{child}')
        else:
            return False
    return all(relative in expected and digest(adapter.read(relative)) == expected[relative]
               for relative in found)


def install(root, prefix, meta):
    root = safe_path(root)
    root_is_link = trusted_root_link(root)
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
    receipt = {'schema_version': 1, 'name': name, 'entry': str(entry), 'sha256': digest(data)}
    result = {'name': name, 'path': str(directory / 'SKILL.md'), 'entry': str(entry)}
    root.mkdir(parents=True, exist_ok=True)
    with Adapter(directory, create=True, root_is_link=root_is_link) as adapter:
        # Only a directory this call created, or the exact leftovers of an
        # interrupted install, skips the ownership check.
        if adapter.created or interrupted_first_install(adapter, pending):
            previous = {}
        else:
            previous = managed(adapter, name, pending)
        existing = adapter.read(OPENAI_YAML)
        # An existing openai.yaml the receipt does not own is the operator's; keep it,
        # unless it is byte-identical to ours (an interrupted earlier install).
        if existing is not None and OPENAI_YAML not in previous.get('files', {}) and existing != yaml:
            result['preserved_files'] = [OPENAI_YAML]
        else:
            adapter.write(OPENAI_YAML, yaml)
            receipt['files'] = {OPENAI_YAML: digest(yaml)}
        adapter.write('SKILL.md', data)
        adapter.write(MARKER, (json.dumps(receipt, indent=2) + '\n').encode())
    return result


def remove_retired(root, plugin):
    """Remove a retired plugin's adapter only when its own marker proves it is ours
    and unmodified. Anything else is preserved untouched and reported."""
    name = 't3-' + plugin
    try:
        directory = safe_path(root) / name
        root_is_link = trusted_root_link(directory.parent)
    except ValueError as exc:
        return {'name': name, 'root': str(root), 'removed': False, 'preserved': str(exc)}
    if not directory.exists() and not directory.is_symlink():
        return None
    receipt = {'name': name, 'root': str(directory.parent), 'removed': False}
    try:
        if directory.is_symlink():
            raise ValueError(f'skill directory is a symlink: {directory}')
        with Adapter(directory, root_is_link=root_is_link) as adapter:
            remove_owned(adapter, managed(adapter, name))
            kept = adapter.entries()
            if not kept:
                adapter.remove_if_empty()
    except (ValueError, OSError) as exc:
        return dict(receipt, preserved=str(exc))
    return dict(receipt, removed=True, kept=kept)


def uninstall(root, meta):
    name = 't3-' + meta['name']
    directory = safe_path(safe_path(root) / name)
    root_is_link = trusted_root_link(directory.parent)
    if not directory.exists():
        return {'name': name, 'removed': False}
    with Adapter(directory, root_is_link=root_is_link) as adapter:
        remove_owned(adapter, managed(adapter, name))
        # Preserve anything the operator added to the adapter directory.
        adapter.remove_if_empty()
    return {'name': name, 'removed': True}
