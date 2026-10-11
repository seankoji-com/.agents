#!/usr/bin/env python3
"""Optional learning helper installed with every plugin. Input is JSON data."""
import argparse
import json
from pathlib import Path

from learning_store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('load', 'maintain', 'write', 'harvest'))
    parser.add_argument('--project', required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    proposal = {}
    try:
        if args.input:
            proposal = json.loads(args.input.read_text())
        manifest = json.loads((args.package / 'install-manifest.json').read_text())
        store = Store(args.project, manifest['plugin'], manifest['version'])
        result = store.operate(args.operation, proposal)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {'status': 'unavailable', 'reason': str(exc), 'proposed_learning': proposal}
    print(json.dumps(result))
    return 0  # Optional learning I/O never blocks the main work.


if __name__ == '__main__':
    raise SystemExit(main())
