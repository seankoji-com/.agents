"""Atomic writes, hashing and path containment."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .errors import Environment, InvalidInput


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 16), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def hash_value(value) -> str:
    return sha256_bytes(canonical(value))


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """mkstemp in the target directory, fsync the file, os.replace, fsync the directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    except OSError as exc:
        raise Environment('io_error', f'cannot write {path.name}: {exc.strerror or exc}') from exc
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value) -> None:
    atomic_write_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())


def read_json(path: Path):
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise Environment('io_error', f'cannot read {Path(path).name}: {exc.strerror or exc}') from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInput('invalid_json', f'{Path(path).name} is not valid JSON: {exc.msg}',
                           {'line': exc.lineno}) from exc


def contained(path: Path, roots) -> Path:
    """Resolve symlinks fully and require the result to sit inside one of roots.

    Rejects `..` traversal and symlinks that escape. Raises InvalidInput."""
    raw = Path(path)
    if any(part == '..' for part in raw.parts):
        raise InvalidInput('path_traversal', 'path must not contain ".." segments', {'path': str(raw)})
    try:
        resolved = raw.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise InvalidInput('path_missing', 'path does not exist or loops', {'path': str(raw)}) from exc
    for root in roots:
        if root is None:
            continue
        root = Path(root).resolve()
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise InvalidInput('path_escape', 'path resolves outside the permitted roots',
                       {'path': str(raw), 'resolved': str(resolved)})


def copy_artifact(source: Path, run_dir: Path, category: str, roots) -> dict:
    """Copy evidence into the run directory so it survives worktree cleanup."""
    source = contained(source, roots)
    if not source.is_file():
        raise InvalidInput('artifact_not_file', 'evidence artifact must be a regular file', {'path': str(source)})
    digest = sha256_file(source)
    if not category.replace('-', '').isalnum():
        raise InvalidInput('bad_category', 'artifact category must be alphanumeric', {'category': category})
    target_dir = Path(run_dir) / 'artifacts' / category
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in source.name)[:80] or 'artifact'
    target = target_dir / f'{digest[:12]}-{stem}'
    if not target.exists():
        tmp = target.with_name('.' + target.name + '.tmp')
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
    return {'path': target.relative_to(run_dir).as_posix(), 'sha256': digest, 'source': str(source)}


def write_artifact(run_dir: Path, category: str, name: str, data: bytes) -> dict:
    digest = sha256_bytes(data)
    target = Path(run_dir) / 'artifacts' / category / f'{digest[:12]}-{name}'
    if not target.exists():
        atomic_write_bytes(target, data)
    return {'path': target.relative_to(run_dir).as_posix(), 'sha256': digest}


def verify_artifact(run_dir: Path, entry: dict) -> str | None:
    """Return None when the stored artifact still matches, else a reason."""
    rel = Path(entry.get('path', ''))
    if rel.is_absolute() or '..' in rel.parts:
        return 'artifact path escapes the run directory'
    path = Path(run_dir) / rel
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        return 'artifact missing'
    if not resolved.is_relative_to(Path(run_dir).resolve()):
        return 'artifact symlink escapes the run directory'
    if sha256_file(resolved) != entry.get('sha256'):
        return 'artifact hash changed'
    return None
