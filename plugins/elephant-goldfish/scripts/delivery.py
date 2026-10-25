#!/usr/bin/env python3
"""Selected delivery for a reviewed elephant design; no network or publication."""
import argparse
import json
from pathlib import Path
import sys

PKG = Path(__file__).resolve().parents[1]
ROOT = next(p for p in (PKG, PKG.parent.parent) if (p / 'shared').is_dir())
sys.path.insert(0, str(ROOT))
from core.fsutil import atomic_json
from shared import adopter_planning, delivery, planning_review


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('start', 'observe', 'status', 'complete'))
    p.add_argument('--descriptor', type=Path, required=True)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--input', type=Path)
    a = p.parse_args(argv)
    try:
        desc = json.loads(a.descriptor.read_text())
        selected = desc['admission']['selection']
        data = json.loads(a.input.read_text()) if a.input else {}
        state = json.loads(a.state.read_text()) if a.state.exists() else None
        if a.action in ('start', 'complete'):
            adopter_planning.validate(desc, PKG)
            planning_review.current_file(desc['document'])
        if a.action == 'start':
            candidate = delivery.start(selected, desc['document']['sha256'], data.get('subissues', []))
            if state:
                delivery.check_state(selected, state)
                if any(candidate[k] != state[k] for k in ('content_sha256', 'subissues', 'agreement_sha256')):
                    raise ValueError('retain partial IDs; changed content needs a scoped revision')
            else:
                state = candidate
            result = state
        elif a.action == 'observe':
            result = delivery.reconcile(selected, state, **data); state = result['state']
        elif a.action == 'complete':
            result = delivery.thinking(selected, state, desc['document']['sha256'], source_ready=True,
                                       revision=data.get('revision'))
        else:
            delivery.check_state(selected, state); result = state
        if a.action in ('start', 'observe'):
            atomic_json(a.state, state)
        print(json.dumps(result, sort_keys=True)); return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('delivery_error: ' + str(exc), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
