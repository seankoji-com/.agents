#!/usr/bin/env python3
"""IMPS admission and consumption of separate shared planning receipts."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
root = next(p for p in Path(__file__).resolve().parents if (p / 'shared/imps_planning.py').is_file())
sys.path.insert(0, str(root))
from core.jobs.store import _regular, strict_load
from shared import imps_planning as imps


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['admit', 'continue', 'prepare', 'attach', 'validate', 'recipe-ready'])
    p.add_argument('--input', required=True)
    a = p.parse_args(argv)
    package = Path(__file__).resolve().parents[1]
    try:
        d = strict_load(_regular(Path(a.input)))
        if a.command == 'admit':
            out = imps.admit(d)
        elif a.command == 'continue':
            out = imps.continuation(d['admission'], invocation_id=d['invocation_id'], event=d.get('event', 'wake'),
                                   forward=d.get('forward', False), retain=d.get('retain'))
        elif a.command == 'prepare':
            out = imps.prepare(d['descriptor'], d['inputs'], d['metadata_file'], package)
        elif a.command == 'attach':
            out = imps.attach(d['descriptor'], d['metadata_file'], d['receipt'], package)
        elif a.command == 'recipe-ready':
            out = imps.recipe_ready(d['descriptor'], package, d['recipe_file'])
        else:
            out = imps.validate(d['descriptor'], package)
        print(json.dumps(out, sort_keys=True)); return 0
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        print('imps_planning_error: ' + str(exc), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
