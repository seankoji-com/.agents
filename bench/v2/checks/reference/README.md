# ledger

A small command-line ledger for CSV files with the columns
`date,account,description,amount`. Amounts have at most two decimal places and are
stored exactly as integer cents. Requires Python 3.10+, standard library only.

```sh
python3 -m ledger total data/sample.csv              # account<TAB>total
python3 -m ledger report data/sample.csv --by month  # YYYY-MM<TAB>account<TAB>total
python3 -m ledger export data/sample.csv out.csv
python3 -m unittest discover -s tests
```

`export` prefixes text cells that a spreadsheet would read as a formula with `'`, and
refuses to overwrite its own input. Invalid input prints `error: <reason>` to stderr
and exits with status 2.
