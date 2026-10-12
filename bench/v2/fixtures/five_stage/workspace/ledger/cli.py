"""Command line interface.

  python3 -m ledger total FILE
  python3 -m ledger export FILE OUT
"""
import argparse
import sys

from . import io, report
from .model import format_cents


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ledger')
    sub = parser.add_subparsers(dest='command', required=True)
    total = sub.add_parser('total', help='print the total of each account')
    total.add_argument('file')
    export = sub.add_parser('export', help='write the entries to a new CSV file')
    export.add_argument('file')
    export.add_argument('out')
    args = parser.parse_args(argv)
    try:
        entries = io.read_csv(args.file)
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    if args.command == 'total':
        for account, cents in report.totals(entries).items():
            print(f'{account}\t{format_cents(cents)}')
    else:
        io.write_csv(entries, args.out)
    return 0
