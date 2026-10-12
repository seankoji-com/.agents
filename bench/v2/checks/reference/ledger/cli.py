"""Command line interface.

  python3 -m ledger total FILE
  python3 -m ledger report FILE --by month
  python3 -m ledger export FILE OUT
"""
import argparse
import os
import sys

from . import io, report
from .model import format_cents


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ledger')
    sub = parser.add_subparsers(dest='command', required=True)
    total = sub.add_parser('total', help='print the total of each account')
    total.add_argument('file')
    monthly = sub.add_parser('report', help='print totals per month and account')
    monthly.add_argument('file')
    monthly.add_argument('--by', choices=['month'], required=True)
    export = sub.add_parser('export', help='write the entries to a new CSV file')
    export.add_argument('file')
    export.add_argument('out')
    args = parser.parse_args(argv)
    try:
        entries = io.read_csv(args.file)
        if args.command == 'total':
            output = [f'{account}\t{format_cents(cents)}' for account, cents in report.totals(entries).items()]
        elif args.command == 'report':
            output = [f'{month}\t{account}\t{format_cents(cents)}'
                      for (month, account), cents in report.by_month(entries).items()]
        else:
            if os.path.exists(args.out) and os.path.samefile(args.file, args.out):
                raise ValueError('refusing to overwrite the input file')
            io.write_csv(entries, args.out)
            output = []
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    for line in output:
        print(line)
    return 0
