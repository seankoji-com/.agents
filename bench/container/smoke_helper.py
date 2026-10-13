#!/usr/bin/env python3
"""Deterministic helper used by the no-model container smoke probe."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

WORKSPACE_ROOT = '/bench/ws'


def open_confined(root, target):
    """Open target for writing without following a symlink anywhere below root."""
    root, target = Path(root), Path(target)
    if not target.is_absolute() or any(part in {'.', '..'} for part in target.parts):
        raise SystemExit('helper output must be an absolute, normalised path')
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise SystemExit('helper output is outside the assigned workspace') from None
    if not parts:
        raise SystemExit('helper output must name a file below the workspace')
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for name in parts[:-1]:
                try:
                    os.mkdir(name, 0o777, dir_fd=directory)
                except FileExistsError:
                    pass
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o666, dir_fd=directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise SystemExit(f'helper output path rejected: {exc.strerror}') from None
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise SystemExit('helper output must be a single-link regular file')
    os.ftruncate(fd, 0)
    return fd


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit('usage: smoke_helper.py INPUT OUTPUT')
    source, target = map(Path, argv)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with os.fdopen(open_confined(WORKSPACE_ROOT, target), 'w', encoding='utf-8') as stream:
        stream.write(json.dumps({'input_sha256': digest}, sort_keys=True) + '\n')
    print(json.dumps({'input_sha256': digest, 'output': target.name}, sort_keys=True))


if __name__ == '__main__':
    main()
