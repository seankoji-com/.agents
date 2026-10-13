"""CSV import and export."""
import csv

from .model import Entry, format_cents, parse_amount

FIELDS = ('date', 'account', 'description', 'amount')


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError('missing columns: ' + ', '.join(missing))
        return [Entry(row['date'], row['account'], row['description'], parse_amount(row['amount']))
                for row in reader]


def write_csv(entries, path):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for entry in entries:
            writer.writerow([entry.date, entry.account, entry.description, format_cents(entry.cents)])
