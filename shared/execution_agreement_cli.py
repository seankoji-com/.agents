"""JSON-file public agreement and observed-delivery boundary. Never dispatches."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import execution_agreement as agreements, delivery, model_selection as models
from core.jobs.store import strict_load, _regular


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inventory', 'inspect', 'freeze', 'admit', 'inherit',
                                           'complete', 'delivery-start', 'delivery-observe', 'delivery-complete'))
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = strict_load(_regular(args.input))
        if args.command == 'inventory':
            result = agreements.inventory(**data)
        elif args.command == 'inspect':
            result = agreements.inspect(data)
        elif args.command == 'freeze':
            result = agreements.freeze(**data)
        elif args.command == 'admit':
            data.pop('event', None)  # unchanged continuation consumes the same producing binding
            result = agreements.admit(**data)
        elif args.command == 'inherit':
            result = agreements.inherit(**data)
        elif args.command == 'complete':
            result = delivery.engineering(**data)
        elif args.command == 'delivery-start':
            result = delivery.start(**data)
        elif args.command == 'delivery-observe':
            result = delivery.reconcile(**data)
        else:
            result = delivery.thinking(**data)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print('agreement_error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
