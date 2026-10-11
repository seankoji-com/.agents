"""Private, optional learning storage. No scheduler, model client or GitHub calls."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid
from urllib.parse import urlsplit


class Unavailable(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def canonical_remote(remote):
    """Transport and credential independent remote identity; preserve repository case."""
    if '://' not in remote:
        match = re.fullmatch(r'(?:[^/@:]+@)?([^/:]+):(.+)', remote)
        if match:
            host, path = match.groups()
        else:
            return 'path:' + str(Path(remote).expanduser().resolve())
    else:
        url = urlsplit(remote)
        if not url.hostname:
            return 'path:' + str(Path(url.path).resolve())
        host, path = url.hostname, url.path
    path = path.strip('/').removesuffix('.git')
    if not host or not path:
        raise Unavailable('remote has no repository identity')
    return host.lower() + '/' + path


def project_identity(project):
    project = Path(project).resolve()
    try:
        probe = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode and 'not a git repository' not in probe.stderr.lower():
            raise Unavailable('Git project lookup failed; refusing to change learning identity')
        result = subprocess.run(['git', '-C', str(project), 'remote'], capture_output=True,
                                text=True, timeout=10)
        if probe.returncode == 0 and result.returncode:
            raise Unavailable('Git remote lookup failed; refusing to change learning identity')
        remotes = sorted(result.stdout.split()) if result.returncode == 0 else []
        if remotes:
            name = 'origin' if 'origin' in remotes else remotes[0]
            result = subprocess.run(['git', '-C', str(project), 'remote', 'get-url', name],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise Unavailable('cannot read selected remote')
            identity = canonical_remote(result.stdout.strip())
            return digest(identity), identity
    except FileNotFoundError:
        pass  # Git is optional, including for installed helpers.
    except subprocess.TimeoutExpired as exc:
        raise Unavailable('project identity lookup timed out') from exc
    identity = 'path:' + str(project)
    return digest(identity), project.name or 'project'


def state_root(project, env=None):
    env = os.environ if env is None else env
    root = Path(env.get('XDG_STATE_HOME') or str(Path(env.get('HOME', str(Path.home()))) / '.local/state'))
    if not root.is_absolute() or '..' in root.parts:
        raise Unavailable('state root must be absolute')
    if project is not None and root.resolve().is_relative_to(Path(project).resolve()):
        raise Unavailable('state root is inside the project')
    # Validate existing ancestors without creating anything, including for grant proposals.
    try:
        with directory(root):
            pass
    except FileNotFoundError:
        pass
    return root


@contextlib.contextmanager
def directory(path, create=False):
    """Walk with directory descriptors, refusing symlinks even during concurrent renames."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise Unavailable('directory must be absolute and contained')
    if not hasattr(os, 'O_NOFOLLOW'):
        raise Unavailable('safe directory operations unavailable on this platform')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


def read_file(fd, name):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Unavailable('learning artifact must be an unlinked regular file')
        return stream.read()


def atomic_file(fd, name, data):
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Unavailable('refusing non-regular learning artifact')
    except FileNotFoundError:
        pass
    temporary = '.learning-' + uuid.uuid4().hex
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def locked(fd, name, writable):
    try:
        import fcntl
    except ImportError as exc:
        raise Unavailable('process locking unavailable on this platform') from exc
    flags = os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_CREAT if writable else os.O_RDONLY)
    handle = os.open(name, flags, 0o600, dir_fd=fd)
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Unavailable('unsafe lock file')
        if writable:
            os.fchmod(handle, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX if writable else fcntl.LOCK_SH)
        yield
    finally:
        os.close(handle)


VERSION = re.compile(r'^\d+\.\d+\.\d+\+(?:g[0-9a-f]{7,40}|content\.[0-9a-f]{8,64})$')


def validate_version(version):
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise Unavailable('version must be an installed manifest version')


def validate_entry(entry):
    if not isinstance(entry, dict):
        raise Unavailable('invalid learning entry')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', entry.get('id', '')):
        raise Unavailable('invalid stable entry ID')
    for name in ('summary', 'failure'):
        if not isinstance(entry.get(name), str) or not entry[name].strip():
            raise Unavailable('each entry needs a summary and observed failure')
    if '\n' in entry['summary'] or '\r' in entry['summary']:
        raise Unavailable('summary must be one line')
    for name in ('authored_version', 'last_validated_version'):
        validate_version(entry.get(name))
    if entry.get('upstream') and not re.fullmatch(r'seankoji-com/t3-plugins#[1-9]\d*', entry['upstream']):
        raise Unavailable('invalid upstream issue')
    if not isinstance(entry.get('destinations', {}), dict):
        raise Unavailable('invalid harvest destinations')


def encode(label, data):
    if not isinstance(label, str) or '\n' in label or '\r' in label:
        raise Unavailable('display label must be one line')
    return ('# ' + label + '\n\n```json\n' + json.dumps(data, indent=2, ensure_ascii=False) + '\n```\n').encode()


def decode(raw):
    text = raw.decode()
    match = re.fullmatch(r'# ([^\r\n]*)\n\n```json\n(.*)\n```\n', text, re.S)
    if not match:
        raise Unavailable('unrecognised learning format')
    data = json.loads(match[2])
    if not isinstance(data, dict) or data.get('format_version') != 1 or not isinstance(data.get('entries'), list):
        raise Unavailable('unsupported learning format version')
    validate_version(data['maintained_version'])
    seen = set()
    for entry in data['entries']:
        validate_entry(entry)
        if entry['id'] in seen:
            raise Unavailable('duplicate learning ID')
        seen.add(entry['id'])
    return match[1], data


def upstream_completed(entry, states, version):
    build = version.partition('+g')[2]
    if not build:
        return False
    for observation in states:
        # A fixture/API observation must bind BOTH compare endpoints. Unknown stays.
        if (observation.get('upstream') == entry.get('upstream')
                and observation.get('state') == 'closed'
                and observation.get('state_reason') == 'completed'
                and re.fullmatch(r'[0-9a-f]{40}', observation.get('closing_commit', ''))
                and observation.get('compare_base') == observation['closing_commit']
                and observation.get('compare_head') == build
                and observation.get('compare_status') in ('ahead', 'identical')):
            return True
    return False


class Store:
    def __init__(self, project, plugin, version, env=None):
        if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', plugin):
            raise Unavailable('invalid plugin name')
        validate_version(version)
        self.key, self.label = project_identity(project)
        self.root = state_root(project, env)
        self.folder = self.root / 't3-plugins/learnings' / self.key
        self.name = plugin + '.md'
        self.version = version

    def operate(self, operation='load', proposal=None):
        """All I/O failures are soft. Callers report proposed work and continue the task."""
        proposal = {} if proposal is None else proposal
        try:
            return self._operate(operation, proposal)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, AttributeError) as exc:
            return {'status': 'unavailable', 'reason': str(exc), 'proposed_learning': proposal}

    def _operate(self, operation, proposal):
        if operation not in ('load', 'write', 'maintain', 'harvest'):
            raise Unavailable('unknown learning operation')
        writable = operation != 'load'
        empty = {'format_version': 1, 'maintained_version': self.version, 'entries': []}
        try:
            with directory(self.folder, writable) as fd, locked(fd, self.name + '.lock', writable):
                try:
                    raw = read_file(fd, self.name)
                    label, data = decode(raw)
                except FileNotFoundError:
                    raw, label, data = None, self.label, empty
                original = digest(data)
                if operation == 'load':
                    return self.receipt(data, original)
                if operation in ('maintain', 'harvest') and proposal.get('expected') != original:
                    raise Unavailable('learnings changed; reload before applying judgement')
                if operation == 'write':
                    if data['maintained_version'] != self.version:
                        raise Unavailable('maintenance pending; load and maintain before writing')
                    entry = dict(proposal['entry'])
                    old = next((e for e in data['entries'] if e['id'] == entry.get('id')), None)
                    entry['authored_version'] = old['authored_version'] if old else self.version
                    entry['last_validated_version'] = self.version
                    if old and old.get('destinations'):
                        entry['destinations'] = old['destinations']
                    validate_entry(entry)
                    data['entries'] = [e for e in data['entries'] if e['id'] != entry['id']] + [entry]
                elif operation == 'maintain':
                    if data['maintained_version'] == self.version:
                        return self.receipt(data, original)
                    backup = self.name + '.pre-' + data['maintained_version']
                    if raw is not None:
                        try:
                            if read_file(fd, backup) != raw:
                                raise Unavailable('owned backup already exists with different content')
                        except FileNotFoundError:
                            atomic_file(fd, backup, raw)
                    removals = set(proposal.get('remove', []))
                    amendments = {e['id']: e for e in proposal.get('amend', [])}
                    ids = {e['id'] for e in data['entries']}
                    if not (removals | amendments.keys()) <= ids:
                        raise Unavailable('maintenance names unknown entries')
                    entries = []
                    for entry in data['entries']:
                        if entry['id'] in removals or upstream_completed(entry, proposal.get('states', []), self.version):
                            continue
                        revised = dict(entry)
                        if entry['id'] in amendments:
                            # Model judgement may amend content, never history or publication receipts.
                            patch = amendments[entry['id']]
                            if set(patch) - {'id', 'summary', 'failure', 'upstream'}:
                                raise Unavailable('maintenance amendment contains protected fields')
                            revised.update(patch)
                        revised['last_validated_version'] = self.version
                        validate_entry(revised)
                        entries.append(revised)
                    data['entries'] = entries
                    data['maintained_version'] = self.version
                elif operation == 'harvest':
                    from harvest import apply_receipts
                    data['entries'] = apply_receipts(data['entries'], proposal)
                atomic_file(fd, self.name, encode(label, data))
                return self.receipt(data, digest(data))
        except FileNotFoundError:
            if not writable:
                # No file/lock/directory means no lessons, with no read-only writes.
                if self.folder.exists() and (self.folder / self.name).exists():
                    raise Unavailable('learning file has no owned lock')
                return self.receipt(empty, digest(empty))
            raise

    def receipt(self, data, revision):
        return {'status': 'available', 'path': str(self.folder / self.name), 'key': self.key,
                'label': self.label, 'data': data, 'revision': revision,
                'pending_maintenance': data['maintained_version'] != self.version,
                'upstream_check': 'eligible' if '+g' in self.version else 'skipped: content install'}
