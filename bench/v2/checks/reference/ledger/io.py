"""CSV import and export."""
import csv

from .model import Entry, format_cents, parse_amount

FIELDS = ('date', 'account', 'description', 'amount')
FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError('missing columns: ' + ', '.join(missing))
        return [Entry(row['date'], row['account'], row['description'], parse_amount(row['amount']))
                for row in reader]


def neutralise(text):
    """Stop spreadsheets from evaluating a text cell as a formula."""
    return "'" + text if text.startswith(FORMULA_START) else text


def write_csv(entries, path):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for entry in entries:
            writer.writerow([neutralise(entry.date), neutralise(entry.account), neutralise(entry.description),
                             format_cents(entry.cents)])
