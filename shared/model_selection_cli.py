"""JSON-file interface to model selection. Never asks questions or launches tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.jobs.store import strict_load, _regular
from shared import model_selection as selection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'validate', 'discover', 'gate', 'dispatch',
                                         'correlate', 'panel', 'prospective', 'save-authority', 'load-authority'))
    parser.add_argument('--input', required=True)
    args = parser.parse_args(argv)
    try:
        data = strict_load(_regular(Path(args.input), max_bytes=16 * 1024 * 1024))
        if args.action == 'freeze':
            result = selection.freeze(data)
        elif args.action == 'validate':
            result = selection.validate(data['record'], data.get('expected'))
        elif args.action == 'discover':
            result = selection.discover(**data)
        elif args.action == 'gate':
            result = selection.gate(**data)
        elif args.action == 'dispatch':
            result = selection.dispatch(**data)
        elif args.action == 'correlate':
            result = selection.correlate(**data)
        elif args.action == 'panel':
            result = selection.panel_report(**data)
        elif args.action == 'prospective':
            result = selection.prospective(**data)
        elif args.action == 'save-authority':
            result = selection.save_authority(**data)
        else:
            result = selection.load_authority(**data)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print('selection_error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
