#!/usr/bin/env python3
"""Admit ape work and bind final report metadata to actual shared planning receipts."""
import argparse
import json
from pathlib import Path
import sys

root = next(p for p in Path(__file__).resolve().parents if (p / 'shared/ape_planning.py').is_file())
sys.path.insert(0, str(root))
from core.jobs.store import _regular, strict_load
from shared import ape_planning as ape


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['admit', 'continue', 'prepare', 'attach', 'validate'])
    parser.add_argument('--input', required=True)
    args = parser.parse_args(argv)
    rubric = Path(__file__).resolve().parents[1] / 'references/plan-review-rubric.md'
    try:
        data = strict_load(_regular(Path(args.input)))
        if args.command == 'admit':
            result = ape.admit(data)
        elif args.command == 'continue':
            result = ape.continuation(data['admission'], invocation_id=data['invocation_id'],
                                      event=data.get('event', 'wake'), forward=data.get('forward', False))
        elif args.command == 'prepare':
            result = ape.prepare(data['descriptor'], data['inputs'], data['job_file'], data['stage_id'],
                                 data['metadata_file'], rubric)
        elif args.command == 'attach':
            result = ape.attach(data['descriptor'], data['metadata_file'], data['receipt'], rubric)
        else:
            result = ape.validate(data['descriptor'], rubric)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        print('ape_planning_error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
