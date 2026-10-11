#!/usr/bin/env python3
"""Create a fresh benchmark workspace: a fixture tree in a new git repository.

Task A copies `bench/fixtures/task_a/workspace/`. Task B exports the tree of the commit
before the worktree-identity fix (`d6bed53^`) through a temporary index, so the
repository's `export-ignore` attributes do not drop files and its later history never
enters the workspace. Both get one commit with a fixed author and date, so every
workspace for a task has the same commit ID. `.bench-state/` is listed in
`.git/info/exclude` so imps run state never shows as an untracked change.

Usage: python3 bench/tools/prepare_workspace.py {a,b} DEST [--repo REPO]
DEST must not exist. REPO (Task B only) defaults to this checkout.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
TASK_B_BASE = 'd6bed537f48f9df3c030ea4920ee2c196f64589e^'
TASK_B_FORBIDDEN = 'tests/test_resources_identity.py'
IDENTITY = {'GIT_AUTHOR_NAME': 'bench', 'GIT_AUTHOR_EMAIL': 'bench@example.invalid',
            'GIT_COMMITTER_NAME': 'bench', 'GIT_COMMITTER_EMAIL': 'bench@example.invalid',
            'GIT_AUTHOR_DATE': '2026-01-01T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00+00:00'}


def git(*args, cwd, env=None) -> str:
    merged = dict(os.environ, **(env or {}))
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        if not env or key not in env:
            merged.pop(key, None)
    return subprocess.run(['git', *args], cwd=cwd, env=merged, check=True, capture_output=True, text=True).stdout.strip()


def export_commit(repo: Path, rev: str, dest: Path) -> str:
    tree = git('rev-parse', f'{rev}^{{tree}}', cwd=repo)
    with tempfile.TemporaryDirectory() as tmp:
        env = {'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
        git('read-tree', tree, cwd=repo, env=env)
        git('checkout-index', '--all', f'--prefix={dest}/', cwd=repo, env=env)
    return tree


def init_repo(dest: Path, message: str) -> str:
    git('init', '--quiet', '--initial-branch=main', cwd=dest)
    git('add', '--all', cwd=dest)
    git('-c', 'commit.gpgsign=false', 'commit', '--quiet', '--no-verify', '-m', message, cwd=dest, env=IDENTITY)
    # Run state lives in <workspace>/.bench-state; keep it out of `git status` without a tracked file.
    with open(dest / '.git' / 'info' / 'exclude', 'a') as handle:
        handle.write('.bench-state/\n')
    return git('rev-parse', 'HEAD', cwd=dest)


def prepare(task: str, dest: Path, repo: Path) -> dict:
    if dest.exists():
        raise SystemExit(f'{dest} already exists')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if task == 'a':
        shutil.copytree(BENCH / 'fixtures' / 'task_a' / 'workspace', dest)
        head = init_repo(dest, 'Task A fixture')
        return {'task': 'a', 'workspace': str(dest), 'head': head, 'tree': git('rev-parse', 'HEAD^{tree}', cwd=dest)}
    dest.mkdir()
    tree = export_commit(repo, TASK_B_BASE, dest)
    if (dest / TASK_B_FORBIDDEN).exists():
        raise SystemExit(f'{TASK_B_FORBIDDEN} must not be in the Task B workspace')
    head = init_repo(dest, 'Task B fixture')
    actual = git('rev-parse', 'HEAD^{tree}', cwd=dest)
    if actual != tree:
        raise SystemExit(f'exported tree {actual} does not match {TASK_B_BASE} tree {tree}')
    return {'task': 'b', 'workspace': str(dest), 'head': head, 'tree': tree}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('task', choices=('a', 'b'))
    parser.add_argument('dest', type=Path)
    parser.add_argument('--repo', type=Path, default=BENCH.parent)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.task, args.dest.resolve(), args.repo.resolve())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
