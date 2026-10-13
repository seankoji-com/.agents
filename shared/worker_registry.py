#!/usr/bin/env python3
"""Managed worker definitions, installation identity, policy and job pins.

This is a local file registry. It never discovers or launches native agents.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from core.jobs.store import trusted_link

try:
    import fcntl
except ImportError:  # pragma: no cover - unsupported platform is reported on use
    fcntl = None

SCHEMA_VERSION = 1
DEFAULT_AGENTS_ROOT = '~/.agents/agents/t3-plugins'
SHARED_REQUIRED = ('boundaries.md',)
WORKER_CATALOG = {
    'imps': {
        'stage-executor': ('engineering stage completion and verification preparation', ['run']),
        'investigator': ('read-only cited investigation', ['issues', 'discussion']),
        'auditor': ('evidence-based audit and refutation', ['audit', 'blast-radius']),
        'reviewer': ('independent exact-snapshot change review', ['run', 'prs']),
    },
    'ape': {'source-researcher': ('pinned source comparison and transferable proposals', ['forage', 'study']),
           'synthesizer': ('accepted report comparison and bounded experiment proposals', ['forage'])},
    'elephant-goldfish': {'factual-checker': ('repository and command claim verification', ['elephant', 'check']),
                          'cold-reader': ('document-only usability and evidence verdict', ['thinking', 'elephant'])},
    'babysitter': {'pr-maintainer': ('one scoped PR triage and authorized repair', ['pr', 'repo', 'org']),
                   'pr-reviewer': ('independent final combined PR review', ['pr', 'repo', 'org'])},
    'agent-tuneup': {'config-researcher': ('provider-format and scope research with sources', ['audit', 'align']),
                     'config-verifier': ('authorized configuration change verification', ['audit', 'align', 'apply'])},
}


class RegistryError(ValueError):
    """A registry refusal; `code` is a stable contract error code when one applies."""
    def __init__(self, message='', code=None):
        super().__init__(f'{code}: {message}' if code else message)
        self.code = code


_LOCK_DEPTH = {}


@contextmanager
def locked(directory: Path):
    """Serialize registry transactions across processes on the same filesystem."""
    if fcntl is None:
        raise RegistryError('process-safe registry locking is unavailable on this platform')
    directory = directory.expanduser().absolute()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / '.t3-plugins-registry.lock'
    key = str(lock_path)
    owner = threading.get_ident()
    if _LOCK_DEPTH.get(key) == owner:
        yield
        return
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RegistryError('registry lock is not a regular file')
        fcntl.flock(fd, fcntl.LOCK_EX)
        _LOCK_DEPTH[key] = owner
        try:
            yield
        finally:
            _LOCK_DEPTH.pop(key, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def read_regular(path: Path, label: str) -> bytes:
    """Open a regular file without following symlinks or blocking on special files."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except OSError as exc:
        raise RegistryError(f'{label} is missing or unsafe: {path}') from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RegistryError(f'{label} must be a regular file: {path}')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def serialized_registry(function):
    @wraps(function)
    def call(args, *rest, **kwargs):
        if getattr(args, 'dry_run', False):
            return function(args, *rest, **kwargs)
        with locked(registry_root(args.agents_root)):
            return function(args, *rest, **kwargs)
    return call


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def atomic(path: Path, data: bytes, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def safe_component(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}', value) or value in ('.', '..'):
        raise RegistryError(f'invalid encoded registry component: {value!r}')
    return value


def ensure_no_symlink_path(path: Path, stop: Path):
    path, stop = path.absolute(), stop.absolute()
    if not path.is_relative_to(stop):
        raise RegistryError('registry path escapes agents root')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink() and not trusted_link(current): raise RegistryError(f'registry path crosses symlink: {current}')


def installation_id(prefix: Path, create: bool = True) -> str:
    """Read/create stable identity in the data prefix, not derived from its path."""
    with locked(prefix):
        return _installation_id_locked(prefix, create)


def _installation_id_locked(prefix: Path, create: bool = True) -> str:
    marker = prefix / '.t3-plugins-installation.json'
    try:
        marker.lstat()
    except FileNotFoundError:
        marker_missing = True
    else:
        marker_missing = False
    if not marker_missing:
        try: value = json.loads(read_regular(marker, 'installation identity marker').decode('utf-8'))
        except (OSError, ValueError, UnicodeError) as exc: raise RegistryError('installation identity marker is corrupt') from exc
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise RegistryError('installation identity marker has an unknown schema')
        identity = value.get('installation_id')
        try: return str(uuid.UUID(identity))
        except (ValueError, TypeError, AttributeError) as exc: raise RegistryError('installation identity is invalid') from exc
    if not create: raise RegistryError('installation identity is missing; explicit adoption is required')
    identity = str(uuid.uuid4())
    prefix.mkdir(parents=True, exist_ok=True)
    atomic(marker, canonical({'schema_version': 1, 'installation_id': identity}), 0o600)
    return identity


def registry_root(value: str | Path | None) -> Path:
    return Path(value or DEFAULT_AGENTS_ROOT).expanduser().absolute()


def bundle_dir(root: Path, identity: str, plugin: str, version: str) -> Path:
    identity = safe_component(identity); plugin = safe_component(plugin); version = safe_component(version)
    return root / 'installations' / identity / plugin / version


def package_file(version_dir: Path, rel: str) -> Path:
    if not isinstance(rel, str): raise RegistryError('package manifest path is not a string')
    if version_dir.is_symlink(): raise RegistryError('package directory is a symlink')
    candidate = Path(rel)
    if candidate.is_absolute() or not rel or '\\' in rel or '..' in candidate.parts:
        raise RegistryError('package manifest path traversal')
    current = version_dir
    for part in candidate.parts:
        current = current / part
        if current.is_symlink(): raise RegistryError('package manifest path crosses a symlink')
    if version_dir.exists() and not current.resolve().is_relative_to(version_dir.resolve()):
        raise RegistryError('package manifest path escapes package directory')
    return current


def load_manifest(plugin_dir: Path) -> dict:
    path = plugin_dir / 'plugin.json'
    try: meta = json.loads(read_regular(path, 'plugin manifest').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError(f'invalid plugin manifest: {plugin_dir}') from exc
    if not isinstance(meta, dict) or meta.get('name') != plugin_dir.name:
        raise RegistryError(f'{path}: plugin name does not match its directory')
    if not isinstance(meta.get('operations', []), list) or any(not isinstance(op, str) for op in meta.get('operations', [])):
        raise RegistryError(f'{path}: operations must be a string list')
    workers = meta.get('workers', [])
    if not isinstance(workers, list): raise RegistryError(f'{path}: workers must be a list')
    expected_ids = {f'{meta.get("name")}/{name}' for name in WORKER_CATALOG.get(meta.get('name'), {})}
    seen = set()
    for item in workers:
        if not isinstance(item, dict) or set(item) != {'id', 'path', 'operations', 'role', 'responsibility'}:
            raise RegistryError(f'{path}: malformed worker declaration')
        wid, rel, ops, role = item['id'], item['path'], item['operations'], item['role']
        if (not isinstance(wid, str) or wid in seen or
                not re.fullmatch(re.escape(meta['name']) + r'/[a-z][a-z0-9-]*', wid)):
            raise RegistryError(f'{path}: duplicate or invalid worker id')
        seen.add(wid)
        if not isinstance(rel, str) or '\\' in rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise RegistryError(f'{path}: worker definition path must stay in plugin source')
        source = plugin_dir / rel
        ensure_no_symlink_path(source, plugin_dir)
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(plugin_dir.resolve()):
            raise RegistryError(f'{path}: worker definition missing or unsafe: {rel}')
        if (not isinstance(ops, list) or any(not isinstance(op, str) for op in ops) or
                len(set(ops)) != len(ops) or not set(ops) <= set(meta.get('operations', [])) or
                role not in ('workhorse', 'reviewer', 'judgement') or
                not isinstance(item['responsibility'], str) or not item['responsibility'].strip()):
            raise RegistryError(f'{path}: invalid worker operation mapping or role')
    if workers and expected_ids and seen != expected_ids:
        raise RegistryError(f'{path}: worker catalog is incomplete or has unexpected IDs')
    return meta


def declared_assets(plugin_dir: Path, shared_dir: Path):
    meta = load_manifest(plugin_dir)
    assets = []
    if not meta.get('workers'):
        return meta, assets
    for worker in meta.get('workers', []):
        path = plugin_dir / worker['path']
        try: data = path.read_bytes(); data.decode('utf-8')
        except (OSError, UnicodeError) as exc: raise RegistryError(f'worker definition is not readable UTF-8: {path}') from exc
        if not data.strip(): raise RegistryError(f'worker definition is empty: {path}')
        rel = f"workers/{worker['id'].split('/', 1)[1]}.md"
        assets.append((rel, data, {'id': worker['id'], 'source': worker['path'],
                                               'operations': worker['operations'], 'role': worker['role'],
                                               'responsibility': worker['responsibility']}))
    shared = meta.get('worker_shared', list(SHARED_REQUIRED))
    if (not isinstance(shared, list) or any(not isinstance(rel, str) for rel in shared) or
            len(set(shared)) != len(shared) or not set(SHARED_REQUIRED) <= set(shared)):
        raise RegistryError(f"{plugin_dir / 'plugin.json'}: worker_shared must include {SHARED_REQUIRED}")
    for rel in shared:
        if not isinstance(rel, str) or '\\' in rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise RegistryError('shared worker asset path is unsafe')
        path = shared_dir / 'agents' / rel
        ensure_no_symlink_path(path, shared_dir)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to((shared_dir / 'agents').resolve()):
            raise RegistryError(f'missing or unsafe declared shared worker asset: {rel}')
        try: data = path.read_bytes(); data.decode('utf-8')
        except (OSError, UnicodeError) as exc: raise RegistryError(f'shared worker asset is not readable UTF-8: {rel}') from exc
        if not data.strip(): raise RegistryError(f'shared worker asset is empty: {rel}')
        assets.append((f'shared/{rel}', data, {'source': f'shared/agents/{rel}'}))
    return meta, assets


def package_digest(manifest: dict) -> str:
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
        raise RegistryError('package manifest file list is malformed')
    seen = set()
    for item in manifest['files']:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str) or
                not isinstance(item.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']) or
                item['path'] in seen):
            raise RegistryError('package manifest file entry is malformed')
        seen.add(item['path'])
    return digest(canonical(manifest['files']))


def verify_package_files(package: Path, manifest: dict) -> None:
    """Verify regular owned package files and reject unlisted or special entries."""
    expected = {entry['path'] for entry in manifest.get('files', [])}
    expected.add('install-manifest.json')
    expected_dirs = set()
    for rel in expected:
        if rel == 'install-manifest.json': continue
        for parent in Path(rel).parents:
            if parent != Path('.'): expected_dirs.add(parent.as_posix())
    actual, actual_dirs = set(), set()
    for candidate in package.rglob('*'):
        rel = candidate.relative_to(package).as_posix()
        if '__pycache__' in candidate.parts:
            continue
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode): raise RegistryError(f'installed package contains a symlink: {rel}')
        if stat.S_ISREG(mode): actual.add(rel)
        elif stat.S_ISDIR(mode): actual_dirs.add(rel)
        else: raise RegistryError(f'installed package contains a special file: {rel}')
    if actual != expected or actual_dirs != expected_dirs:
        raise RegistryError('installed package has missing or unlisted files/directories')
    for entry in manifest.get('files', []):
        target = package_file(package, entry.get('path', ''))
        if digest(read_regular(target, 'installed package asset')) != entry.get('sha256'):
            raise RegistryError(f'installed package integrity failure: {entry.get("path")}')


def create_bundle(root: Path, identity: str, plugin: str, version: str, assets, package_hash: str) -> dict:
    dest = bundle_dir(root, identity, plugin, version)
    root.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_path(dest, root)
    entries = []
    for rel, data, fields in sorted(assets):
        safe = Path(rel)
        if safe.is_absolute() or '..' in safe.parts or not data:
            raise RegistryError(f'invalid or empty worker asset: {rel}')
        entries.append({'path': rel, 'sha256': digest(data), 'size': len(data), **fields})
    bundle_manifest = {'schema_version': 1, 'installation_id': identity, 'plugin': plugin,
                       'package_version': version, 'package_digest': package_hash, 'assets': entries}
    bundle_hash = digest(canonical(bundle_manifest))
    if dest.exists():
        checked = verify_bundle(dest, identity, plugin, version, package_hash)
        if checked['bundle_digest'] != bundle_hash: raise RegistryError('immutable bundle conflicts with existing content')
        return {'bundle_dir': str(dest), 'bundle_digest': bundle_hash, 'bundle_manifest': bundle_manifest}
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.' + version + '.', dir=dest.parent))
    try:
        for rel, data, _ in assets:
            path = temp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data); os.chmod(path, 0o444)
        (temp / 'manifest.json').write_bytes(canonical(bundle_manifest)); os.chmod(temp / 'manifest.json', 0o444)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, dest)
    finally:
        if temp.exists(): shutil.rmtree(temp)
    return {'bundle_dir': str(dest), 'bundle_digest': bundle_hash, 'bundle_manifest': bundle_manifest}


def claim_installation(root: Path, identity: str, prefix: Path):
    """Keep one active prefix locator per UUID; a copied marker cannot claim twice."""
    with locked(root):
        return _claim_installation_locked(root, identity, prefix)


def same_prefix(recorded: str, prefix: Path) -> bool:
    """Whether two spellings name one prefix directory (e.g. macOS /var and /private/var)."""
    return Path(recorded).absolute() == prefix.absolute() or os.path.realpath(recorded) == os.path.realpath(prefix)


def _claim_installation_locked(root: Path, identity: str, prefix: Path):
    root.mkdir(parents=True, exist_ok=True)
    claims = root / 'claims.json'
    try:
        claims.lstat()
        data = json.loads(read_regular(claims, 'registry claims').decode('utf-8'))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError('registry claims are corrupt') from exc
    if not isinstance(data, dict): raise RegistryError('registry claims are malformed')
    current = data.get(identity)
    if current and (not isinstance(current, dict) or not isinstance(current.get('prefix'), str) or
                    not same_prefix(current['prefix'], prefix)):
        raise RegistryError('identity conflict: installation UUID already claims another prefix; use explicit adoption')
    locators = current.get('locators', []) if isinstance(current, dict) else []
    if not isinstance(locators, list) or any(not isinstance(item, str) for item in locators):
        raise RegistryError('installation locator history is malformed')
    current_path = str(prefix.absolute())
    data[identity] = {'prefix': current_path, 'locators': list(dict.fromkeys([*locators, current_path]))}
    atomic(claims, canonical(data), 0o600)


def assert_owned_locator(root: Path, identity: str, prefix: Path):
    claims_path = root / 'claims.json'
    try: claims = json.loads(read_regular(claims_path, 'installation locator claim').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError('installation locator claim is missing or corrupt') from exc
    claim = claims.get(identity) if isinstance(claims, dict) else None
    if not isinstance(claim, dict) or not isinstance(claim.get('prefix'), str) or not same_prefix(claim['prefix'], prefix):
        raise RegistryError('identity conflict: this prefix is not the owned locator; explicit adoption is required')


JOB_INDEX = 'job-index.json'
JOB_INDEX_STATES = ('live', 'cancelled', 'discarded')
JOB_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')


def job_agents_roots(pins: dict) -> list[Path]:
    """The owning agents root of each pinned bundle: <root>/installations/<id>/<plugin>/<version>."""
    roots = {Path(pin['bundle_dir']).absolute().parents[3] for pin in pins.values()
             if isinstance(pin, dict) and isinstance(pin.get('bundle_dir'), str) and Path(pin['bundle_dir']).is_absolute()}
    return sorted(roots, key=str)


def load_job_index(agents_root: Path) -> dict:
    """Read the private job-root index; corruption fails closed for removal."""
    path = Path(agents_root) / JOB_INDEX
    try:
        path.lstat()
    except FileNotFoundError:
        return {'schema_version': 1, 'jobs': {}}
    try: data = json.loads(read_regular(path, 'job root index').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError(f'job root index is corrupt; refusing removal: {path}') from exc
    jobs = data.get('jobs') if isinstance(data, dict) and data.get('schema_version') == 1 else None
    if not isinstance(jobs, dict) or any(
            not isinstance(entry, dict) or set(entry) != {'state_root', 'job_id', 'status'} or
            not isinstance(entry['state_root'], str) or not Path(entry['state_root']).is_absolute() or
            not isinstance(entry['job_id'], str) or not JOB_ID.fullmatch(entry['job_id']) or
            entry['status'] not in JOB_INDEX_STATES or key != str(Path(entry['state_root']) / entry['job_id'])
            for key, entry in jobs.items()):
        raise RegistryError(f'job root index is malformed; refusing removal: {path}')
    return data


def record_job_root(agents_roots, state_root, job_id: str, status: str = 'live') -> list[Path]:
    """Atomically index a job's state root in each owning agents root.

    A live record never overwrites an existing one; cancel/discard records replace it.
    Returns the roots where a new record was added, so a failed creation can roll back.
    """
    if status not in JOB_INDEX_STATES or not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise RegistryError('invalid job root index record')
    state = str(Path(state_root).expanduser().absolute())
    key = str(Path(state) / job_id)
    added = []
    for root in sorted({Path(r).absolute() for r in agents_roots}, key=str):
        with locked(root):
            index = load_job_index(root)
            if key not in index['jobs']: added.append(root)
            elif status == 'live': continue
            index['jobs'][key] = {'state_root': state, 'job_id': job_id, 'status': status}
            atomic(root / JOB_INDEX, canonical(index), 0o600)
    return added


def forget_job_root(agents_roots, state_root, job_id: str) -> None:
    """Remove live records this process added for a job that was never created."""
    key = str(Path(state_root).expanduser().absolute() / job_id)
    for root in sorted({Path(r).absolute() for r in agents_roots}, key=str):
        with locked(root):
            index = load_job_index(root)
            if index['jobs'].get(key, {}).get('status') == 'live':
                del index['jobs'][key]
                atomic(root / JOB_INDEX, canonical(index), 0o600)


def referenced_versions(agents_root: Path, bundle: Path | None, state_root: Path | None = None,
                        package_dir: Path | None = None) -> list[str]:
    """Find live/resumable job references conservatively; malformed jobs block deletion.

    Scans the default (or given) job root and every state root recorded in the agents
    root's job index. A recorded live job whose state is missing or unreadable blocks
    removal; only an explicit job_cli cancel/discard releases it.
    """
    if state_root is None:
        state_root = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))).expanduser() / 't3-plugins/jobs'
    found, seen = [], set()
    job_paths = sorted(state_root.glob('*/job.json')) if state_root.exists() else []
    index_path = Path(agents_root) / JOB_INDEX
    for key, entry in sorted(load_job_index(agents_root)['jobs'].items()):
        if entry['status'] != 'live': continue
        job_path = Path(key) / 'job.json'
        try:
            if not stat.S_ISREG(job_path.lstat().st_mode): raise OSError('not a regular file')
        except OSError as exc:
            raise RegistryError(f'recorded job state is missing or unreadable; restore it, or cancel/discard the job '
                                f'through job_cli before removal (index {index_path}): {key}') from exc
        job_paths.append(job_path)
    for job_path in job_paths:
        if job_path.absolute() in seen: continue
        seen.add(job_path.absolute())
        try: job = json.loads(read_regular(job_path, 'job state').decode('utf-8'))
        except (OSError, ValueError, UnicodeError) as exc: raise RegistryError(f'cannot determine pin references: {job_path}') from exc
        if not isinstance(job, dict) or job.get('schema_version') != 1: raise RegistryError(f'unknown job schema blocks removal: {job_path}')
        status = job.get('status', 'live')
        if status in ('accepted', 'cancelled', 'discarded', 'complete') or job.get('discard_requested'): continue
        pins = job.get('pins', {})
        deps = job.get('dependencies', [])
        if not isinstance(pins, dict) or not isinstance(deps, list):
            raise RegistryError(f'malformed dependency references block removal: {job_path}')
        for dep in deps:
            if not isinstance(dep, dict) or not isinstance(dep.get('key'), str):
                raise RegistryError(f'malformed dependency reference blocks removal: {job_path}')
            if dep['key'] not in pins:
                raise RegistryError(f'unresolved dependency reference blocks removal: {job_path}:{dep["key"]}')
        if set(pins) != {dep['key'] for dep in deps}:
            raise RegistryError(f'undeclared job pin blocks removal: {job_path}')
        for key, pin in pins.items():
            if (not isinstance(pin, dict) or not isinstance(pin.get('package_dir'), str) or
                    not Path(pin['package_dir']).is_absolute()):
                raise RegistryError(f'malformed package pin blocks removal: {job_path}:{key}')
            if pin.get('bundle_dir') is not None and (not isinstance(pin['bundle_dir'], str) or
                    not Path(pin['bundle_dir']).is_absolute()):
                raise RegistryError(f'malformed bundle pin blocks removal: {job_path}:{key}')
        serialized = json.dumps(pins, sort_keys=True)
        if ((bundle is not None and str(bundle.absolute()) in serialized) or
                (package_dir is not None and str(package_dir.absolute()) in serialized)):
            found.append(str(job_path.parent))
    return found


def validate_job_references(state_root: Path | None = None) -> list[str]:
    """Validate every live pin locally; do not infer missing or unknown state."""
    if state_root is None:
        state_root = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))).expanduser() / 't3-plugins/jobs'
    errors = []
    if not state_root.exists(): return errors
    for job_path in sorted(state_root.glob('*/job.json')):
        try: job = json.loads(read_regular(job_path, 'job state').decode('utf-8'))
        except (OSError, ValueError, UnicodeError):
            errors.append(f'job_corrupt:{job_path}'); continue
        if not isinstance(job, dict) or job.get('schema_version') != 1:
            errors.append(f'job_schema_unknown:{job_path}'); continue
        if job.get('status', 'live') in ('accepted', 'complete', 'cancelled', 'discarded'):
            continue
        pins = job.get('pins', {})
        if not isinstance(pins, dict):
            errors.append(f'job_pins_malformed:{job_path}'); continue
        deps = job.get('dependencies', [])
        if not isinstance(deps, list):
            errors.append(f'job_dependencies_malformed:{job_path}'); continue
        unresolved = False
        for dep in deps:
            if not isinstance(dep, dict) or not isinstance(dep.get('key'), str) or dep['key'] not in pins:
                errors.append(f'job_dependency_unresolved:{job_path}'); unresolved = True
        if set(pins) != {dep.get('key') for dep in deps if isinstance(dep, dict)}:
            errors.append(f'job_pin_declaration_mismatch:{job_path}'); unresolved = True
        if unresolved: continue
        for key, pin in pins.items():
            if not isinstance(pin, dict):
                errors.append(f'job_pin_malformed:{job_path}:{key}'); continue
            package = Path(pin.get('package_dir', ''))
            if not package.is_absolute():
                errors.append(f'job_package_path_not_absolute:{job_path}:{key}'); continue
            try: package_manifest = json.loads(read_regular(package / 'install-manifest.json', 'package receipt').decode('utf-8'))
            except (OSError, ValueError, UnicodeError):
                errors.append(f'job_package_missing:{job_path}:{key}'); continue
            if not isinstance(package_manifest, dict):
                errors.append(f'job_package_corrupt:{job_path}:{key}'); continue
            if package_manifest.get('package_digest') != pin.get('package_digest') or package_digest(package_manifest) != pin.get('package_digest'):
                errors.append(f'job_package_digest_mismatch:{job_path}:{key}'); continue
            try:
                verify_package_files(package, package_manifest)
            except (OSError, RegistryError):
                errors.append(f'job_package_integrity_failure:{job_path}:{key}'); continue
            bundle = pin.get('bundle_dir')
            if bundle:
                if (pin.get('installation_id') != package_manifest.get('installation_id') or
                        os.path.realpath(bundle) != os.path.realpath(package_manifest.get('bundle_dir', '')) or
                        pin.get('bundle_digest') != package_manifest.get('bundle_digest')):
                    errors.append(f'job_bundle_receipt_mismatch:{job_path}:{key}'); continue
                try:
                    checked = verify_bundle(Path(bundle), pin.get('installation_id'), package_manifest.get('plugin'),
                                            package_manifest.get('version'), pin.get('package_digest'))
                    if checked['bundle_digest'] != pin.get('bundle_digest'):
                        errors.append(f'job_bundle_digest_mismatch:{job_path}:{key}')
                except RegistryError:
                    errors.append(f'job_bundle_invalid:{job_path}:{key}')
            else:
                try: plugin_meta = json.loads(read_regular(package / 'plugin.json', 'installed plugin manifest').decode('utf-8'))
                except (OSError, ValueError, UnicodeError):
                    errors.append(f'job_plugin_manifest_missing:{job_path}:{key}'); continue
                if isinstance(plugin_meta, dict) and plugin_meta.get('workers'):
                    errors.append(f'job_worker_bundle_missing:{job_path}:{key}')
    return errors


def inspect_agents(agents_root: Path, plugin: str | None = None, prefix: Path | None = None,
                   config_path: Path | None = None) -> list[dict]:
    cfg = load_workers_config(config_path or worker_config_path())
    claims_path = agents_root / 'claims.json'
    try:
        claims_path.lstat()
        claims = json.loads(read_regular(claims_path, 'registry claims').decode('utf-8'))
    except FileNotFoundError:
        claims = {}
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError('registry claims are corrupt') from exc
    if not isinstance(claims, dict): raise RegistryError('registry claims are malformed')
    roots = []
    if prefix:
        marker = prefix / '.t3-plugins-installation.json'
        if marker.exists():
            identity = installation_id(prefix, create=False)
            assert_owned_locator(agents_root, identity, prefix)
            for pdir in (agents_root / 'installations' / identity).glob('*'):
                if plugin and pdir.name != plugin: continue
                for version_dir in pdir.glob('*'):
                    roots.append((identity, pdir.name, version_dir))
    else:
        base = agents_root / 'installations'
        if base.exists():
            for identity_dir in base.iterdir():
                if identity_dir.is_symlink() or not identity_dir.is_dir(): continue
                for pdir in identity_dir.iterdir():
                    if plugin and pdir.name != plugin: continue
                    for version_dir in pdir.iterdir(): roots.append((identity_dir.name, pdir.name, version_dir))
    result = []
    for identity, pname, version_dir in roots:
        if version_dir.is_symlink(): raise RegistryError('managed worker directory is a symlink')
        checked = verify_bundle(version_dir, identity, pname, version_dir.name)
        claim = claims.get(identity)
        if not isinstance(claim, dict) or not isinstance(claim.get('prefix'), str):
            raise RegistryError(f'managed bundle has no installation locator claim: {identity}')
        package = Path(claim['prefix']) / pname / version_dir.name
        try: receipt = json.loads(read_regular(package / 'install-manifest.json', 'package receipt').decode('utf-8'))
        except (OSError, ValueError, UnicodeError) as exc: raise RegistryError(f'managed package receipt is missing: {package}') from exc
        if (receipt.get('installation_id') != identity or receipt.get('plugin') != pname or
                receipt.get('version') != version_dir.name or receipt.get('bundle_dir') != str(version_dir.absolute()) or
                receipt.get('bundle_digest') != checked['bundle_digest'] or
                receipt.get('package_digest') != checked['manifest'].get('package_digest') or
                package_digest(receipt) != receipt.get('package_digest')):
            raise RegistryError(f'managed package/bundle pair does not match: {package}')
        verify_package_files(package, receipt)
        for asset in checked['manifest']['assets']:
            if not asset.get('id'): continue
            override = validate_override(agents_root, asset['id'], checked['bundle_digest'], cfg)
            result.append({'id': asset['id'], 'plugin': pname, 'version': version_dir.name,
                           'role': asset['role'], 'override_status': (override or {}).get('status', 'disabled'),
                           'integrity': 'ok', 'bundle_digest': checked['bundle_digest']})
    return sorted(result, key=lambda item: (item['plugin'], item['id'], item['version']))


def show_agent(agents_root: Path, plugin: str, worker: str, prefix: Path | None = None,
               config_path: Path | None = None) -> dict:
    items = [item for item in inspect_agents(agents_root, plugin, prefix, config_path) if item['id'] == f'{plugin}/{worker}']
    if not items: raise RegistryError(f'worker is not installed: {plugin}/{worker}')
    active = None
    if prefix:
        current = prefix / plugin / 'current'
        if current.is_symlink(): active = current.resolve().name
    item = next((candidate for candidate in items if candidate['version'] == active), items[-1])
    path = bundle_dir(agents_root, installation_id(prefix, False), plugin, item['version']) if prefix else None
    if path is None:
        candidates = list((agents_root / 'installations').glob(f'*/{plugin}/{item["version"]}'))
        if len(candidates) != 1: raise RegistryError('worker installation is ambiguous; supply --prefix')
        path = candidates[0]
    manifest = json.loads(read_regular(path / 'manifest.json', 'bundle manifest').decode('utf-8'))
    asset = next(a for a in manifest['assets'] if a.get('id') == item['id'])
    data = (path / asset['path']).read_bytes()
    override = validate_override(agents_root, item['id'], item['bundle_digest'], load_workers_config(config_path or worker_config_path()))
    shared = [(a['path'], (path / a['path']).read_bytes()) for a in manifest['assets']
              if a['path'].startswith('shared/')]
    custom = override['content'] if override and override.get('status') == 'enabled' else ''
    definition = compose_worker(shared, data, custom, None)
    return {'worker': item, 'provenance': {'bundle_dir': str(path), 'base_path': str(path / asset['path']),
            'base_sha256': digest(data), 'shared_paths': [name for name, _ in shared],
            'override_path': (override or {}).get('path'), 'override_status': (override or {}).get('status', 'disabled'),
            'override_sha256': (override or {}).get('sha256')}, 'definition': definition}


def compose_worker(shared, base: bytes, customization: str, task_contract: bytes | None) -> str:
    text = ('# Shared boundary contracts\n' + '\n'.join(data.decode('utf-8') for _, data in sorted(shared)) +
            '\n\n# Specialized worker definition\n' + base.decode('utf-8'))
    if customization:
        text += '\n\n# Explicit worker customization (advisory; cannot grant authority or change runtime mode)\n' + customization
    text += ('\n\n# Pinned task contract\nThe task brief and repository instructions set the authority ceiling. '
             'Customization cannot add permissions, change runtime mode, dispatch children, or accept work.\n')
    return text + (task_contract.decode('utf-8') if task_contract else 'No additional task contract was supplied.')


def set_override(root: Path, worker_id: str, base_digest: str, enabled: bool, config_path: Path | None = None):
    path = config_path or worker_config_path()
    with locked(path.parent):
        cfg = load_workers_config(path)
        if enabled:
            record = {'worker_id': worker_id, 'base_bundle_digest': base_digest,
                      'path': f'{worker_id}.md', 'enabled': True}
            cfg['overrides'] = [r for r in cfg['overrides'] if r['worker_id'] != worker_id] + [record]
            checked = validate_override(root, worker_id, base_digest, cfg)
            if checked is None: raise RegistryError('override enable did not take effect')
        cfg['overrides'] = [r for r in cfg['overrides'] if r['worker_id'] != worker_id]
        cfg['overrides'].append({'worker_id': worker_id, 'base_bundle_digest': base_digest,
                                 'path': f'{worker_id}.md', 'enabled': bool(enabled)})
        atomic(path, canonical(cfg), 0o600)
    return {'worker_id': worker_id, 'enabled': bool(enabled), 'config': str(path)}


def verify_bundle(path: Path, identity: str, plugin: str, version: str, expected_package_digest: str | None = None) -> dict:
    if path.is_symlink(): raise RegistryError('bundle directory is a symlink')
    manifest_path = path / 'manifest.json'
    ensure_no_symlink_path(manifest_path, path)
    try: manifest = json.loads(read_regular(manifest_path, 'bundle manifest').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError(f'bundle manifest is missing or corrupt: {path}') from exc
    if not isinstance(manifest, dict): raise RegistryError('bundle manifest must be an object')
    if (manifest.get('schema_version') != 1 or manifest.get('installation_id') != identity or
            manifest.get('plugin') != plugin or manifest.get('package_version') != version or
            (expected_package_digest and manifest.get('package_digest') != expected_package_digest)):
        raise RegistryError('bundle identity or package pairing mismatch')
    entries = manifest.get('assets')
    if not isinstance(entries, list) or not entries: raise RegistryError('bundle assets are empty or malformed')
    expected = {'manifest.json'}
    expected_dirs = set()
    seen_assets = set()
    for item in entries:
        rel = item.get('path') if isinstance(item, dict) else None
        if not isinstance(rel, str) or '\\' in rel or Path(rel).is_absolute() or '..' in Path(rel).parts: raise RegistryError('bundle asset traversal')
        if rel in seen_assets: raise RegistryError('bundle manifest contains a duplicate asset')
        seen_assets.add(rel)
        file = path / rel; ensure_no_symlink_path(file, path)
        try: data = read_regular(file, 'bundle asset')
        except RegistryError as exc: raise RegistryError(f'bundle asset integrity failure: {rel}') from exc
        if (type(item.get('size')) is not int or len(data) != item['size'] or
                digest(data) != item.get('sha256')):
            raise RegistryError(f'bundle asset integrity failure: {rel}')
        expected.add(rel)
        for parent in Path(rel).parents:
            if parent != Path('.'): expected_dirs.add(parent.as_posix())
    all_paths = list(path.rglob('*'))
    for candidate in all_paths:
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode): raise RegistryError('bundle contains a symlink')
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise RegistryError(f'bundle contains a special file: {candidate.relative_to(path)}')
    actual = {p.relative_to(path).as_posix() for p in all_paths if stat.S_ISREG(p.lstat().st_mode)}
    actual_dirs = {p.relative_to(path).as_posix() for p in all_paths if stat.S_ISDIR(p.lstat().st_mode)}
    if actual != expected: raise RegistryError('bundle has missing or unexpected files')
    if actual_dirs != expected_dirs: raise RegistryError('bundle has missing or unexpected directories')
    return {'bundle_dir': str(path), 'bundle_digest': digest(canonical(manifest)), 'manifest': manifest}


def worker_config_path(env=None) -> Path:
    env = os.environ if env is None else env
    config = Path(env.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))).expanduser()
    return config / 't3-plugins' / 'workers.json'


def load_workers_config(path: Path) -> dict:
    try:
        path.lstat()
    except FileNotFoundError:
        return {'schema_version': 1, 'max_live_workers': None, 'max_repair_cycles': 3, 'overrides': []}
    try: cfg = json.loads(read_regular(path, 'workers config').decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc: raise RegistryError('workers config is malformed') from exc
    if not isinstance(cfg, dict) or cfg.get('schema_version') != 1 or set(cfg) != {'schema_version','max_live_workers','max_repair_cycles','overrides'}:
        raise RegistryError('workers config schema is invalid')
    live, repair = cfg['max_live_workers'], cfg['max_repair_cycles']
    if live is not None and (type(live) is not int or live <= 0): raise RegistryError('max_live_workers must be null or positive integer')
    if type(repair) is not int or repair < 0: raise RegistryError('max_repair_cycles must be nonnegative integer')
    if not isinstance(cfg['overrides'], list): raise RegistryError('overrides must be a list')
    identities = set()
    for entry in cfg['overrides']:
        if not isinstance(entry, dict) or set(entry) != {'worker_id','base_bundle_digest','path','enabled'}:
            raise RegistryError('override record is malformed')
        key = entry['worker_id']
        if not isinstance(key, str) or key in identities or type(entry['enabled']) is not bool or not re.fullmatch(r'[0-9a-f]{64}', str(entry['base_bundle_digest'])):
            raise RegistryError('override record has invalid ID, digest, or enabled flag')
        expected_path = f'{key}.md' if isinstance(key, str) and key.count('/') == 1 else None
        override_rel = entry['path']
        if (not isinstance(override_rel, str) or override_rel != expected_path or
                Path(override_rel).is_absolute() or '..' in Path(override_rel).parts):
            raise RegistryError('override path must remain under the sole override root')
        identities.add(key)
    return cfg


def override_path(root: Path, worker_id: str) -> Path:
    if not re.fullmatch(r'[a-z][a-z0-9-]*/[a-z][a-z0-9-]*', worker_id): raise RegistryError('invalid worker id')
    return root / 'overrides' / (worker_id + '.md')


def validate_override(root: Path, worker_id: str, base_digest: str, cfg: dict) -> dict | None:
    record = next((r for r in cfg['overrides'] if r['worker_id'] == worker_id), None)
    if not record or not record['enabled']: return None
    if record['base_bundle_digest'] != base_digest: return {'status': 'stale', 'path': str(override_path(root, worker_id))}
    path = override_path(root, worker_id); ensure_no_symlink_path(path, root)
    if not path.is_file(): raise RegistryError(f'enabled override is missing: {worker_id}')
    data = read_regular(path, 'worker override')
    try: text = data.decode('utf-8')
    except UnicodeError as exc: raise RegistryError(f'override is not UTF-8: {worker_id}') from exc
    if not text.strip() or f'worker_id: {worker_id}' not in text: raise RegistryError(f'override worker ID mismatch: {worker_id}')
    return {'status': 'enabled', 'path': str(path), 'content': text, 'sha256': digest(data)}


def bundled_versions(plugin_root: Path, plugin: str) -> list[str]:
    """Installed versions of a plugin whose receipts name a worker bundle (not verified here)."""
    found = []
    if not plugin_root.is_dir() or plugin_root.is_symlink(): return found
    for version_dir in sorted(plugin_root.iterdir()):
        if version_dir.name == 'current' or version_dir.is_symlink() or not version_dir.is_dir(): continue
        try: receipt = json.loads(read_regular(version_dir / 'install-manifest.json', 'package receipt').decode('utf-8'))
        except (OSError, ValueError, UnicodeError): continue
        if (isinstance(receipt, dict) and receipt.get('plugin') == plugin and receipt.get('bundle_dir') and
                not receipt.get('preserved_modified')):
            found.append(version_dir.name)
    return found


def snapshot_pins(job_path: Path, dependency_plugins: dict[str, str], prefix: Path, agents_root: Path,
                  config_path: Path | None = None, task_contract: bytes | None = None) -> dict:
    """Return exact dependency-keyed package/bundle/worker/limits pin payload for Stage 3."""
    job = json.loads(read_regular(job_path, 'job state').decode('utf-8'))
    if not isinstance(job, dict) or job.get('schema_version') != 1 or not isinstance(job.get('dependencies'), list):
        raise RegistryError('job.json is malformed or has unknown schema_version')
    declared = {}
    for dep in job['dependencies']:
        if not isinstance(dep, dict) or not isinstance(dep.get('key'), str) or not isinstance(dep.get('plugin'), str):
            raise RegistryError('job dependency record is malformed')
        if dep['key'] in declared: raise RegistryError(f'duplicate job dependency key: {dep["key"]}')
        declared[dep['key']] = dep['plugin']
    if 'pins' in job and not isinstance(job['pins'], dict): raise RegistryError('job pin state is malformed')
    if job.get('pins') and set(job['pins']) != set(declared): raise RegistryError('job pins are missing or undeclared')
    if set(dependency_plugins) != set(declared) or any(declared[k] != v for k, v in dependency_plugins.items()):
        raise RegistryError('requested pins do not exactly match declared job dependencies')
    cfg = load_workers_config(config_path or worker_config_path())
    pins = {}
    for key, plugin in dependency_plugins.items():
        item = next(d for d in job['dependencies'] if d.get('key') == key)
        existing_pin = job.get('pins', {}).get(key, {}) if isinstance(job.get('pins', {}), dict) else {}
        locator = item.get('package_dir') or existing_pin.get('package_dir')
        uses_active_locator = not locator
        if locator:
            if not isinstance(locator, str) or not Path(locator).is_absolute():
                raise RegistryError(f'package pin path must be absolute: {key}')
            version_dir = Path(locator).absolute()
        else:
            plugin_root = prefix / plugin
            current = plugin_root / 'current'
            if not current.is_symlink() or not current.resolve().is_relative_to(plugin_root.resolve()):
                raise RegistryError(f'no safe active package to pin for dependency: {key}')
            version_dir = current.resolve()
        try: manifest = json.loads(read_regular(version_dir / 'install-manifest.json', 'package receipt').decode('utf-8'))
        except (OSError, ValueError, UnicodeError) as exc: raise RegistryError(f'unresolved package pin: {key}') from exc
        if manifest.get('plugin') != plugin or manifest.get('version') != version_dir.name: raise RegistryError(f'wrong package pin: {key}', 'pin_mismatch')
        if not manifest.get('bundle_dir'):
            bundled = bundled_versions(version_dir.parent, plugin)
            raise RegistryError(f'legacy package has no worker bundle: {key} ({plugin} {version_dir.name}); new-format jobs '
                                f'need a package with worker bundles; installed versions with bundles: '
                                f'{", ".join(bundled) if bundled else "none (install the current release)"}', 'pin_mismatch')
        package_hash = manifest.get('package_digest')
        if not isinstance(package_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', package_hash): raise RegistryError(f'package digest missing: {key}', 'pin_mismatch')
        verify_package_files(version_dir, manifest)
        if package_digest(manifest) != package_hash: raise RegistryError(f'package manifest digest mismatch: {key}', 'pin_mismatch')
        identity = manifest.get('installation_id')
        dependency_root = Path(manifest.get('agents_root', '')).expanduser().absolute()
        if uses_active_locator and dependency_root != agents_root.absolute():
            raise RegistryError(f'active dependency uses a different agents root: {key}')
        bundle_locator = item.get('bundle_dir') or existing_pin.get('bundle_dir') or Path(manifest['bundle_dir']) if manifest.get('bundle_dir') else None
        if bundle_locator is None:
            raise RegistryError(f'legacy package has no worker bundle: {key}')
        bundle = Path(bundle_locator).absolute()
        expected_bundle = bundle_dir(dependency_root, identity, plugin, manifest['version'])
        if bundle != expected_bundle.absolute(): raise RegistryError(f'dependency bundle path is outside its owned registry: {key}')
        package_prefix = version_dir.parent.parent
        assert_owned_locator(dependency_root, identity, package_prefix)
        checked = verify_bundle(bundle, identity, plugin, manifest['version'], package_hash)
        declared_bundle_digest = item.get('bundle_digest') or existing_pin.get('bundle_digest') or manifest.get('bundle_digest')
        if checked['bundle_digest'] != declared_bundle_digest: raise RegistryError(f'bundle digest mismatch: {key}', 'pin_mismatch')
        workers, shared = {}, {}
        for asset in checked['manifest']['assets']:
            data = (bundle / asset['path']).read_bytes()
            if asset['path'].startswith('workers/'): workers[asset.get('id')] = {'bytes': data.decode('utf-8'), 'sha256': digest(data)}
            elif asset['path'].startswith('shared/'): shared[asset['path'][len('shared/'):]] = {'bytes': data.decode('utf-8'), 'sha256': digest(data)}
        effective = {}
        for wid, base in workers.items():
            customization = validate_override(dependency_root, wid, checked['bundle_digest'], cfg)
            custom_bytes = customization['content'] if customization and customization.get('status') == 'enabled' else ''
            composed = compose_worker([(k, v['bytes'].encode('utf-8')) for k, v in shared.items()],
                                      base['bytes'].encode('utf-8'), custom_bytes,
                                      task_contract if task_contract else None)
            raw = composed.encode('utf-8')
            effective[wid] = {'bytes': composed, 'sha256': digest(raw), 'override_status':
                              (customization or {}).get('status', 'disabled'), 'override_sha256':
                              (customization or {}).get('sha256'), 'override_bytes':
                              (customization or {}).get('content') if customization and customization.get('status') == 'enabled' else None,
                              'base_sha256': base['sha256']}
        pins[key] = {'installation_id': identity, 'package_dir': str(version_dir), 'package_digest': package_hash,
                     'bundle_dir': str(bundle), 'bundle_digest': checked['bundle_digest'], 'workers': workers,
                     'shared': shared, 'effective_workers': effective,
                     'task_contract': ({'bytes': task_contract.decode('utf-8'), 'sha256': digest(task_contract)}
                                       if task_contract is not None else None),
                     'limits': {'max_live_workers': cfg['max_live_workers'], 'max_repair_cycles': cfg['max_repair_cycles']}}
        pins[key]['compatible_pinned_invocation'] = f't3-plugins --job {job_path.absolute()} path {plugin}'
    return {'schema_version': 1, 'pins': pins,
            'compatible_pinned_invocations': {key: f't3-plugins --job {job_path.absolute()} path {plugin}'
                                              for key, plugin in dependency_plugins.items()}}


def adopt(prefix: Path, old_prefix: Path, agents_root: Path) -> dict:
    """Explicit path relocation: identity and all content must verify before locator changes."""
    with locked(agents_root):
        return _adopt_locked(prefix, old_prefix, agents_root)


def _adopt_locked(prefix: Path, old_prefix: Path, agents_root: Path) -> dict:
    try:
        old_id = installation_id(old_prefix, create=False)
    except RegistryError:
        if not prefix.is_dir(): raise RegistryError('neither relocation locator has a verifiable identity marker')
        old_id = installation_id(prefix, create=False)
        claims_path = agents_root / 'claims.json'
        try: old_claims = json.loads(read_regular(claims_path, 'registry claims').decode('utf-8'))
        except (OSError, ValueError, UnicodeError) as exc: raise RegistryError('old relocation locator is not present in registry claims') from exc
        claim = old_claims.get(old_id)
        if not claim or not same_prefix(claim.get('prefix', ''), old_prefix):
            raise RegistryError('old relocation locator does not match this installation identity')
    new_marker = prefix / '.t3-plugins-installation.json'
    if new_marker.exists():
        if installation_id(prefix, create=False) != old_id: raise RegistryError('identity conflict at destination')
    root = agents_root
    claims = root / 'claims.json'
    current = {}
    if claims.exists():
        try: current = json.loads(read_regular(claims, 'registry claims').decode('utf-8'))
        except (ValueError, OSError, UnicodeError) as exc: raise RegistryError('registry claims are corrupt') from exc
    claim = current.get(old_id)
    if claim and (not isinstance(claim, dict) or not isinstance(claim.get('prefix'), str) or
                  not same_prefix(claim['prefix'], old_prefix)):
        raise RegistryError('identity conflict: duplicate live locator')
    # Validate all existing bundle pairs before changing either path record.
    source_root = old_prefix
    for pdir in old_prefix.iterdir() if old_prefix.is_dir() else ():
        if pdir.name.startswith('.') or not pdir.is_dir(): continue
        for version in pdir.iterdir():
            if version.is_symlink(): continue
            mf = version / 'install-manifest.json'
            if not mf.is_file(): continue
            manifest = json.loads(read_regular(mf, 'install receipt').decode('utf-8'))
            if manifest.get('installation_id') != old_id: raise RegistryError('copied receipt identity conflict')
            if manifest.get('bundle_dir'):
                if os.path.realpath(Path(manifest.get('agents_root', '')).expanduser()) != os.path.realpath(root):
                    raise RegistryError('receipt agents root does not match adoption root')
                expected = bundle_dir(root, old_id, manifest['plugin'], manifest['version'])
                if Path(manifest['bundle_dir']).absolute() != expected.absolute():
                    raise RegistryError('receipt bundle path does not match owned registry location')
                checked = verify_bundle(expected, old_id, manifest['plugin'], manifest['version'], manifest['package_digest'])
                if checked['bundle_digest'] != manifest.get('bundle_digest'):
                    raise RegistryError('receipt bundle digest is invalid')
    if not prefix.is_dir(): raise RegistryError('destination prefix does not exist; relocation must be copied first')
    for pdir in prefix.iterdir():
        if pdir.name.startswith('.') or not pdir.is_dir(): continue
        for version in pdir.iterdir():
            if version.is_symlink(): continue
            mf = version / 'install-manifest.json'
            if not mf.is_file(): continue
            manifest = json.loads(read_regular(mf, 'install receipt').decode('utf-8'))
            if manifest.get('installation_id') != old_id: raise RegistryError('destination receipt does not match source identity')
            if manifest.get('bundle_dir'):
                if os.path.realpath(Path(manifest.get('agents_root', '')).expanduser()) != os.path.realpath(root):
                    raise RegistryError('destination receipt agents root does not match adoption root')
                expected = bundle_dir(root, old_id, manifest['plugin'], manifest['version'])
                if Path(manifest['bundle_dir']).absolute() != expected.absolute():
                    raise RegistryError('destination receipt bundle path does not match registry location')
                checked = verify_bundle(expected, old_id, manifest['plugin'], manifest['version'], manifest['package_digest'])
                if checked['bundle_digest'] != manifest.get('bundle_digest'):
                    raise RegistryError('destination bundle digest is invalid')
            for entry in manifest.get('files', []):
                target = package_file(version, entry['path'])
                if target.is_symlink() or not target.is_file() or digest(target.read_bytes()) != entry['sha256']:
                    raise RegistryError(f'destination package integrity failure: {target}')
    prefix.mkdir(parents=True, exist_ok=True)
    atomic(new_marker, canonical({'schema_version': 1, 'installation_id': old_id}), 0o600)
    prior = current.get(old_id, {})
    history = prior.get('locators', []) if isinstance(prior, dict) else []
    if not isinstance(history, list) or any(not isinstance(item, str) for item in history):
        raise RegistryError('installation locator history is malformed')
    history = list(dict.fromkeys([*history, str(old_prefix.absolute()), str(prefix.absolute())]))
    current[old_id] = {'prefix': str(prefix.absolute()), 'previous_prefix': str(old_prefix.absolute()),
                       'locators': history}
    atomic(claims, canonical(current), 0o600)
    return {'installation_id': old_id, 'old_prefix': str(old_prefix.absolute()), 'new_prefix': str(prefix.absolute()), 'verified': True}
