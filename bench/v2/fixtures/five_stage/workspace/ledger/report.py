"""Aggregations over ledger entries."""


def totals(entries):
    """Total cents per account, sorted by account name."""
    result = {}
    for entry in entries:
        result[entry.account] = result.get(entry.account, 0) + entry.cents
    return dict(sorted(result.items()))
