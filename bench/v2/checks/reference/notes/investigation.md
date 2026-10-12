# Investigation: totals one cent low

Cause: `parse_amount` converts the text to a binary float and truncates
(`ledger/model.py:16`, after `float(text)` on `ledger/model.py:15`). `1.15 * 100` is
`114.99999999999999`, and `int()` truncates it to `114`.

Reproduce: a CSV with one entry of `1.15`; `python3 -m ledger total` prints `1.14`.
