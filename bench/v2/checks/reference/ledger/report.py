"""Aggregations over ledger entries."""
import re
from datetime import date

ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')


def totals(entries):
    """Total cents per account, sorted by account name."""
    result = {}
    for entry in entries:
        result[entry.account] = result.get(entry.account, 0) + entry.cents
    return dict(sorted(result.items()))


def by_month(entries):
    """Total cents per (YYYY-MM, account), sorted by month then account."""
    result = {}
    for entry in entries:
        try:
            if not ISO_DATE.fullmatch(entry.date):
                raise ValueError
            date.fromisoformat(entry.date)
        except ValueError:
            raise ValueError(f'invalid date {entry.date!r}: use YYYY-MM-DD') from None
        key = (entry.date[:7], entry.account)
        result[key] = result.get(key, 0) + entry.cents
    return dict(sorted(result.items()))
