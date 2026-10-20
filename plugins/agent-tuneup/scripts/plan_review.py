#!/usr/bin/env python3
"""Adopter admission and consumption of separate pinned planning jobs."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
root = next(p for p in Path(__file__).resolve().parents if (p / 'shared/adopter_planning.py').is_file())
sys.path.insert(0, str(root))
from core.jobs.store import _regular, strict_load
from shared import adopter_planning as adopter


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('admit','continue','dispatch','prepare','attach','validate','approve','apply-ready','publish'))
    p.add_argument('--input', required=True)
    a = p.parse_args(argv)
    package = Path(__file__).resolve().parents[1]
    try:
        d = strict_load(_regular(Path(a.input)))
        if a.command == 'admit':
            out = adopter.admit(PLUGIN, d)
        elif a.command == 'continue':
            out = adopter.continuation(**dict(d, record=d['admission']) if False else
                {'record':d['admission'], **{k:v for k,v in d.items() if k!='admission'}})
        elif a.command == 'dispatch':
            out = adopter.dispatch(d['admission'], **{k:v for k,v in d.items() if k!='admission'})
        elif a.command == 'prepare':
            out = adopter.prepare(d['descriptor'],d['inputs'],d['metadata_file'],package)
        elif a.command == 'attach':
            out = adopter.attach(d['descriptor'],d['metadata_file'],d['receipt'],package)
        elif a.command == 'publish':
            out = adopter.publish(d['descriptor'],d['output_file'],package)
        elif a.command == 'approve':
            out = adopter.approve(d['descriptor'],d['owner'],package)
        elif a.command == 'apply-ready':
            out = adopter.apply_ready(d['context'],d['document'],package)
        else:
            out = adopter.validate(d['descriptor'],package)
        print(json.dumps(out,sort_keys=True));return 0
    except (ValueError,KeyError,TypeError,OSError,StopIteration) as exc:
        print('adopter_planning_error: '+str(exc),file=sys.stderr);return 2


PLUGIN = 'agent-tuneup'
if __name__ == '__main__':
    raise SystemExit(main())
