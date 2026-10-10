"""Run-owned resources: worktrees, branches and processes. Identity checks happen
before any cleanup command is offered, so a reused PID is never signalled."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def fingerprint(pid: int) -> str | None:
    out = subprocess.run(['ps', '-o', 'lstart=', '-o', 'command=', '-p', str(int(pid))], capture_output=True)
    text = out.stdout.decode(errors='replace').strip()
    return text or None


def _git(cwd, *args) -> str | None:
    out = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True)
    return out.stdout.decode(errors='replace').strip() if out.returncode == 0 else None


def worktree_identity(path) -> dict | None:
    """The worktree's own `.git` file and admin directory: recreating a worktree at
    the same path makes new ones."""
    gitdir = _git(path, 'rev-parse', '--absolute-git-dir')
    if not gitdir:
        return None
    try:
        return {'gitdir': gitdir, 'gitdir_inode': os.stat(gitdir).st_ino,
                'dotgit_inode': os.lstat(Path(path) / '.git').st_ino}
    except OSError:
        return None


def branch_identity(repo, branch) -> dict | None:
    """The branch's creation entry in its reflog, plus its tip when recorded."""
    tip = _git(repo, 'rev-parse', '--verify', '-q', 'refs/heads/' + branch)
    if not tip:
        return None
    log = _git(repo, 'reflog', 'show', '--date=raw', '--format=%H %gd', 'refs/heads/' + branch) or ''
    lines = [line for line in log.splitlines() if line]
    return {'origin': lines[-1].replace('refs/heads/' + branch, '', 1) if lines else None, 'tip': tip}


def _exists(item: dict) -> bool:
    if item['kind'] == 'worktree':
        return Path(item['path']).exists()
    if item['kind'] == 'branch':
        return _git(item['repo'], 'rev-parse', '--verify', '-q', 'refs/heads/' + item['branch']) is not None
    if item['kind'] == 'process':
        return fingerprint(item['pid']) is not None
    return False


def _same(item: dict) -> bool:
    recorded = item.get('identity')
    if item['kind'] == 'process':
        return fingerprint(item['pid']) == item['fingerprint']
    if not recorded:
        return True  # recorded before identities were kept
    if item['kind'] == 'worktree':
        return worktree_identity(item['path']) == recorded
    if item['kind'] == 'branch':
        current = branch_identity(item['repo'], item['branch'])
        if current is None:
            return False
        if recorded.get('origin') and current['origin']:
            return current['origin'] == recorded['origin']
        # No reflog: the recorded tip must still be in the branch history.
        return _git(item['repo'], 'merge-base', '--is-ancestor', recorded['tip'], current['tip']) is not None
    return False


def live(item: dict) -> bool:
    """True only while the resource still exists and is still the one recorded."""
    return _exists(item) and _same(item)


def identity(item: dict) -> str:
    """'live', 'gone' or 'replaced' (a PID, path or branch name now used by something else)."""
    if not _exists(item):
        return 'gone'
    return 'live' if _same(item) else 'replaced'
