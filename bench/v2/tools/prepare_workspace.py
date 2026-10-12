#!/usr/bin/env python3
"""Create a bench-v2 run workspace from the frozen five-stage fixture.

Copies only fixtures/five_stage/workspace (never checks/ or the reference solution)
into DEST, initialises Git with a fixed synthetic identity and date, and commits it.
Every workspace therefore starts from the same tree and commit ID. Prints one JSON
object with the workspace path, head commit and fixture tree digest.

Usage: python3 bench/v2/tools/prepare_workspace.py DEST
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

V2 = Path(__file__).resolve().parent.parent
FIXTURE = V2 / 'fixtures' / 'five_stage' / 'workspace'
IDENTITY = {'GIT_AUTHOR_NAME': 'bench fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_NAME': 'bench fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
            'GIT_AUTHOR_DATE': '2026-10-12T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-10-12T00:00:00+00:00'}


def tree_digest(root: Path) -> str:
    """sha256 over sorted (relative path, file sha256) pairs; caches are excluded."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if path.is_file() and '__pycache__' not in rel.parts and '.git' not in rel.parts:
            digest.update(f'{rel.as_posix()}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n'.encode())
    return digest.hexdigest()


def prepare(dest: Path) -> dict:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f'{dest} exists and is not empty')
    shutil.copytree(FIXTURE, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    env = dict(os.environ, **IDENTITY, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return subprocess.run(['git', '-C', str(dest), *args], env=env, check=True, capture_output=True,
                              text=True).stdout.strip()

    git('init', '-q', '-b', 'main')
    git('add', '-A')
    git('commit', '-q', '-m', 'fixture: five-stage ledger')
    return {'workspace': str(dest), 'head': git('rev-parse', 'HEAD'), 'fixture_tree_sha256': tree_digest(FIXTURE)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('dest', type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.dest.absolute())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
