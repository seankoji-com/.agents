# ledger

A small command-line ledger for CSV files with the columns
`date,account,description,amount`. Amounts are decimal numbers; the ledger stores
them as integer cents. Requires Python 3.10+, standard library only.

```sh
python3 -m ledger total data/sample.csv        # one line per account: account<TAB>total
python3 -m ledger export data/sample.csv out.csv
python3 -m unittest discover -s tests          # run the tests
```

Invalid input prints `error: <reason>` to stderr and exits with status 2.
