"""Ledger entries and amount handling. Amounts are stored as integer cents."""
import re
from dataclasses import dataclass

AMOUNT = re.compile(r'(-?)([0-9]+)(?:\.([0-9]{1,2}))?')


@dataclass(frozen=True)
class Entry:
    date: str  # ISO date, YYYY-MM-DD
    account: str
    description: str
    cents: int


def parse_amount(text):
    """Parse a decimal amount such as '12.34' or '-5' into integer cents, exactly."""
    match = AMOUNT.fullmatch(text or '')
    if not match:
        raise ValueError(f'invalid amount {text!r}: use digits with at most two decimal places')
    sign, whole, fraction = match.groups()
    cents = int(whole) * 100 + int((fraction or '').ljust(2, '0'))
    return -cents if sign else cents


def format_cents(cents):
    """Format integer cents as a decimal amount with two places."""
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}{cents // 100}.{cents % 100:02d}'
