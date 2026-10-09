"""Run-owned resources: worktrees, branches and processes. Identity checks happen
before any cleanup command is offered, so a reused PID is never signalled."""
from __future__ import annotations

import subprocess
from pathlib import Path


def fingerprint(pid: int) -> str | None:
    out = subprocess.run(['ps', '-o', 'lstart=', '-o', 'command=', '-p', str(int(pid))], capture_output=True)
    text = out.stdout.decode(errors='replace').strip()
    return text or None


def live(item: dict) -> bool:
    """True only while the resource still exists and is still the one recorded."""
    if item['kind'] == 'worktree':
        return Path(item['path']).exists()
    if item['kind'] == 'branch':
        check = subprocess.run(['git', '-C', item['repo'], 'rev-parse', '--verify', '-q', 'refs/heads/' + item['branch']],
                               capture_output=True)
        return check.returncode == 0
    if item['kind'] == 'process':
        return fingerprint(item['pid']) == item['fingerprint']
    return False


def identity(item: dict) -> str:
    """'live', 'gone' or 'replaced' (a process whose PID now belongs to something else)."""
    if item['kind'] == 'process':
        current = fingerprint(item['pid'])
        if current is None:
            return 'gone'
        return 'live' if current == item['fingerprint'] else 'replaced'
    return 'live' if live(item) else 'gone'
