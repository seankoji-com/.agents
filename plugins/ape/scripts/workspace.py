#!/usr/bin/env python3
"""Create or validate ape workspace ownership before writing or deleting data."""
import argparse
import json
from pathlib import Path
import sys

MARKER = '.ape-workspace.json'


def validate(path):
    marker = path / MARKER
    expected = {'schema_version': 1, 'owner': 'agents/ape', 'workspace': str(path.resolve())}
    if marker.is_symlink() or not marker.is_file():
        raise ValueError('workspace has no regular ape ownership marker')
    if json.loads(marker.read_text()) != expected:
        raise ValueError('workspace ownership marker does not match this directory')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'validate'])
    parser.add_argument('workspace', type=Path)
    args = parser.parse_args()
    path = args.workspace.expanduser()
    base = (Path.home() / 'tmp/repo-research').resolve()
    try:
        if path.is_symlink() or path.resolve().parent != base:
            raise ValueError('workspace must be a direct, non-symlink child of ~/tmp/repo-research')
        if args.action == 'init' and not path.exists():
            path.mkdir(parents=True)
            data = {'schema_version': 1, 'owner': 'agents/ape', 'workspace': str(path.resolve())}
            with (path / MARKER).open('x') as stream:
                json.dump(data, stream)
        validate(path)
    except (OSError, ValueError) as exc:
        print(f'ape workspace: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
