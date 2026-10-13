# Export audit

Finding: Spreadsheet formula injection in exported text.
Severity: high
Evidence: `ledger/io.py:24` writes account and description values directly.
Reproducer: export a CSV description `=HYPERLINK("https://invalid","x")`; a spreadsheet evaluates the cell.
Fix: `neutralise` prefixes dangerous text cells with an apostrophe.
Status: fixed.

Finding: Export can truncate its own input.
Severity: medium
Evidence: `ledger/cli.py:31` calls `io.write_csv(entries, args.out)` without checking aliases.
Reproducer: run `python3 -m ledger export data.csv data.csv`; the source is overwritten.
Fix: `cli.main` checks `os.path.samefile` and refuses the output before opening it.
Disposition: fixed.
Status: fixed.
