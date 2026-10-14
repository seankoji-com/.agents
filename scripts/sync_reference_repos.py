#!/usr/bin/env python3
"""Shallow-clone or refresh the read-only upstream references in scripts/reference_repos.json.

Each entry lands in .repos/<name> at its recorded ref, detached. The checkouts are for
reading: never edit them, never import from them. A checkout with local changes is left
alone and reported, so a refresh cannot discard work.

Usage: python3 scripts/sync_reference_repos.py [--config PATH] [--root DIR] [name ...]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'scripts' / 'reference_repos.json'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
SHA = re.compile(r'[0-9a-f]{40}')
TIMEOUT = 600  # seconds per git call; a stalled network fails instead of hanging


class SyncError(Exception):
    pass


def git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    try:
        result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, env=env,
                                timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError(f'git {args[0]} failed: {exc}') from exc
    if result.returncode:
        raise SyncError(f'git {args[0]} failed: {(result.stderr or result.stdout).strip()}')
    return result.stdout.strip()


def load(config: Path) -> list[dict]:
    try:
        data = json.loads(config.read_text())
    except (OSError, ValueError) as exc:
        raise SyncError(f'cannot read {config}: {exc}') from exc
    repos = data.get('repos') if isinstance(data, dict) else None
    if not isinstance(repos, list) or not repos:
        raise SyncError(f'{config}: "repos" must be a non-empty list')
    seen = set()
    for entry in repos:
        if not isinstance(entry, dict):
            raise SyncError(f'{config}: every repo must be an object')
        for key in ('name', 'url', 'ref'):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise SyncError(f'{config}: repo needs a non-empty string "{key}"')
        if not NAME.fullmatch(entry['name']) or entry['name'] in ('.', '..'):
            raise SyncError(f'{config}: unsafe repo name {entry["name"]!r}')
        if entry['name'] in seen:
            raise SyncError(f'{config}: duplicate repo name {entry["name"]!r}')
        if entry['ref'].startswith('-') or entry['url'].startswith('-'):
            raise SyncError(f'{config}: {entry["name"]}: url and ref must not start with "-"')
        seen.add(entry['name'])
    return repos


def sync(entry: dict, root: Path) -> str:
    dest = root / entry['name']
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise SyncError(f'{dest} is not a plain directory')
    verb = 'refreshed' if dest.exists() else 'cloned'
    if dest.exists():
        if not (dest / '.git').exists():
            raise SyncError(f'{dest} exists but is not a git checkout; remove it or pick another name')
        if git(dest, 'status', '--porcelain', '--ignored=no'):
            raise SyncError(f'{dest} has local changes; these checkouts are read-only references, '
                            'so inspect and remove them first')
        git(dest, 'remote', 'set-url', 'origin', entry['url'])
    else:
        root.mkdir(parents=True, exist_ok=True)
        dest.mkdir()
        git(dest, 'init', '-q')
        git(dest, 'remote', 'add', 'origin', entry['url'])
    git(dest, 'fetch', '-q', '--depth', '1', '--no-tags', 'origin', entry['ref'])
    git(dest, 'checkout', '-q', '--detach', 'FETCH_HEAD')
    head = git(dest, 'rev-parse', 'HEAD')
    if SHA.fullmatch(entry['ref']) and head != entry['ref']:
        raise SyncError(f'{dest} is at {head}, expected {entry["ref"]}')
    return f'{verb} {entry["name"]} at {head}'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--root', type=Path, default=ROOT / '.repos', help='directory that holds the checkouts')
    parser.add_argument('names', nargs='*', help='sync only these entries')
    args = parser.parse_args(argv)
    try:
        repos = load(args.config)
        unknown = set(args.names) - {entry['name'] for entry in repos}
        if unknown:
            raise SyncError(f'not in {args.config.name}: {", ".join(sorted(unknown))}')
    except SyncError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    failed = 0
    for entry in repos:
        if args.names and entry['name'] not in args.names:
            continue
        try:
            print(sync(entry, args.root))
        except SyncError as exc:
            failed += 1
            print(f'error: {entry["name"]}: {exc}', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
