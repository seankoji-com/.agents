"""Ledger entries and amount handling. Amounts are stored as integer cents."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    date: str  # ISO date, YYYY-MM-DD
    account: str
    description: str
    cents: int


def parse_amount(text):
    """Parse a decimal amount such as '12.34' or '-5' into integer cents."""
    value = float(text)
    return int(value * 100)


def format_cents(cents):
    """Format integer cents as a decimal amount with two places."""
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}{cents // 100}.{cents % 100:02d}'
