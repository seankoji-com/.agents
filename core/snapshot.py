"""Revision snapshots that hash dirty content, not just a clean/dirty bit.

Editing a file that is already dirty leaves `git status --porcelain` unchanged
but changes `content_hash`, so readiness recorded earlier goes stale."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .errors import Environment, InvalidInput


def git(cwd, *args, check=True) -> str:
    try:
        result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, check=False)
    except OSError as exc:
        raise Environment('git_unavailable', f'cannot run git: {exc}') from exc
    if check and result.returncode != 0:
        raise Environment('git_failed', f'git {args[0]} failed',
                          {'argv': ['git', '-C', str(cwd), *args],
                           'stderr': result.stderr.decode(errors='replace')[-400:]})
    return result.stdout.decode(errors='replace')


def toplevel(path) -> Path:
    try:
        return Path(git(path, 'rev-parse', '--show-toplevel').strip()).resolve()
    except Environment as exc:
        raise InvalidInput('not_a_repository', f'{path} is not inside a git worktree') from exc


def _porcelain(root: Path):
    raw = subprocess.run(['git', '-C', str(root), 'status', '--porcelain=v1', '-z', '--untracked-files=all',
                          '--ignore-submodules=none'], capture_output=True, check=False)
    if raw.returncode != 0:
        raise Environment('git_failed', 'git status failed', {'stderr': raw.stderr.decode(errors='replace')[-400:]})
    entries = raw.stdout.decode(errors='surrogateescape').split('\0')
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if 'R' in status or 'C' in status:
            index += 1  # skip the rename/copy source, whichever column flags it
        yield status, path


def _excluded(path: Path, exclusions) -> bool:
    return any(path == item or path.is_relative_to(item) for item in exclusions)


def take(worktree, exclude=()) -> dict:
    """HEAD, branch and a content hash over every dirty or untracked path."""
    root = toplevel(worktree)
    exclusions = []
    for item in exclude:
        if item:
            try:
                exclusions.append(Path(item).resolve())
            except OSError:
                continue
    head = git(root, 'rev-parse', '--verify', '-q', 'HEAD', check=False).strip() or None
    branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD', check=False).strip() or None
    digest = hashlib.sha256()
    paths = []
    for status, rel in sorted(_porcelain(root), key=lambda pair: pair[1]):
        absolute = (root / rel)
        # The path itself, not its symlink target: a tracked file swapped for a link into
        # an excluded location is still a change.
        if _excluded(absolute, exclusions):
            continue
        paths.append(rel)
        digest.update(status.encode() + b'\0' + rel.encode(errors='surrogateescape') + b'\0')
        try:
            mode = os.lstat(absolute).st_mode
        except OSError:
            mode = 0
        digest.update(b'mode:' + oct(mode & 0o170111).encode() + b'\0')
        if absolute.is_dir() and not absolute.is_symlink() and (absolute / '.git').exists():
            # A submodule: its own HEAD and dirty content, recursively.
            inner = take(absolute)
            digest.update(b'submodule:' + token(inner).encode())
        elif absolute.is_symlink():
            digest.update(b'link:' + os.readlink(absolute).encode(errors='surrogateescape'))
        elif absolute.is_file():
            try:
                with open(absolute, 'rb') as stream:
                    for block in iter(lambda: stream.read(1 << 16), b''):
                        digest.update(block)
            except OSError as exc:
                # Deleted or unreadable mid-scan: hash the condition so the token still moves.
                digest.update(b'unreadable:' + type(exc).__name__.encode())
        else:
            digest.update(b'absent')
        digest.update(b'\0')
    if paths:
        # Staged blobs too: the same working bytes with different staged content commit differently.
        staged = subprocess.run(['git', '-C', str(root), 'ls-files', '-s', '-z', '--', *paths], capture_output=True)
        digest.update(b'index:' + staged.stdout)
    return {'worktree': str(root), 'head': head, 'branch': branch,
            'dirty_paths': len(paths), 'content_hash': digest.hexdigest()}


def token(snap: dict) -> str:
    """Compact identity of a snapshot, carried by actions and echoed by records."""
    return f'{snap.get("head")}:{snap.get("content_hash")}'


def same(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return all(a.get(key) == b.get(key) for key in ('worktree', 'head', 'content_hash'))


def changed_files(worktree, base: str) -> set:
    """Committed changes since base plus uncommitted changes in a worktree."""
    root = toplevel(worktree)
    committed = git(root, 'diff', '--name-only', f'{base}...HEAD', check=False).split('\n')
    files = {line for line in committed if line}
    for _status, rel in _porcelain(root):
        files.add(rel)
    return files


def commit_reachable(worktree, sha: str) -> bool:
    root = toplevel(worktree)
    exists = subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{sha}^{{commit}}'], capture_output=True)
    if exists.returncode != 0:
        return False
    ancestor = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', sha, 'HEAD'], capture_output=True)
    return ancestor.returncode == 0


def _blob(root: Path, path: str) -> str | None:
    absolute = root / path
    if absolute.is_symlink():
        target = os.readlink(absolute).encode(errors='surrogateescape')
        return hashlib.sha1(b'blob %d\0' % len(target) + target).hexdigest()
    if absolute.is_dir() and (absolute / '.git').exists():
        return 'submodule:' + token(take(absolute))
    if not absolute.is_file():
        return None
    return git(root, 'hash-object', '--', path).strip()


def _index(root: Path) -> dict:
    """Modes, object IDs and merge stages, keyed by literal index paths."""
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-s', '-z'], capture_output=True)
    if result.returncode != 0:
        raise Environment('git_failed', 'git ls-files failed',
                          {'stderr': result.stderr.decode(errors='replace')[-400:]})
    entries = {}
    for entry in result.stdout.decode(errors='surrogateescape').split('\0'):
        if entry:
            metadata, rel = entry.split('\t', 1)
            entries.setdefault(rel, []).append(metadata)
    return entries


def baseline(worktree) -> dict:
    """HEAD, index entries and the content of every dirty path, so later changes can be told
    apart from work that was already there."""
    root = toplevel(worktree)
    head = git(root, 'rev-parse', '--verify', '-q', 'HEAD', check=False).strip() or None
    return {'head': head, 'dirty': {rel: _blob(root, rel) for _status, rel in _porcelain(root)},
            'index': _index(root)}


def changed_since(worktree, base: dict) -> set:
    """Paths whose working content or index entries differ from a `baseline`."""
    root = toplevel(worktree)
    candidates = set(base.get('dirty') or {})
    if base.get('head'):
        candidates |= {line for line in git(root, 'diff', '--name-only', base['head'], 'HEAD', check=False).split('\n')
                       if line}
    candidates |= {rel for _status, rel in _porcelain(root)}
    changed = set()
    if 'index' in base:
        before_index, current_index = base['index'], _index(root)
        changed |= {rel for rel in before_index.keys() | current_index.keys()
                    if before_index.get(rel) != current_index.get(rel)}
    else:
        # Older baselines lack staged provenance. Report staged candidates
        # conservatively; the caller still verifies ownership before publication.
        args = ['diff', '--cached', '--name-only', '-z']
        if base.get('head'):
            args.append(base['head'])
        changed |= {rel for rel in git(root, *args).split('\0') if rel}
    for rel in candidates:
        if rel in (base.get('dirty') or {}):
            before = base['dirty'][rel]
        elif base.get('head'):
            before = git(root, 'rev-parse', '-q', '--verify', f'{base["head"]}:{rel}', check=False).strip() or None
        else:
            before = None
        if _blob(root, rel) != before:
            changed.add(rel)
    return changed
