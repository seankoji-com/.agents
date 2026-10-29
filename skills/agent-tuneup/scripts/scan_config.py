#!/usr/bin/env python3
"""Read one authorized JSON file; report counts and broad permission pointers.

Values are omitted. Key pointers may be private: keep output host-local.
This heuristic does not evaluate provider semantics or effective precedence.
"""
import argparse
import json
import sys
from pathlib import Path


def scan(value):
    leaves, flags = 0, []

    def walk(node, pointer='', permission=False):
        nonlocal leaves
        if isinstance(node, dict):
            for key, child in node.items():
                escaped = key.replace('~', '~0').replace('/', '~1')
                walk(child, pointer + '/' + escaped,
                     permission or key.lower() in {'permissions', 'permission', 'allow', 'deny'})
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, pointer + '/' + str(index), permission)
        else:
            leaves += 1
            if permission and isinstance(node, str) and ('*' in node or node.lower() == 'allow'):
                flags.append(pointer)

    walk(value)
    return {'leaves': leaves, 'broad_permission_pointers': flags,
            'limit': 'heuristic only; no precedence or provider semantics evaluated'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    try:
        result = scan(json.loads(args.file.read_text(encoding='utf-8')))
    except (OSError, ValueError, RecursionError):
        parser.exit(2, 'Cannot read valid bounded JSON; input values omitted.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10+ required')
    main()
