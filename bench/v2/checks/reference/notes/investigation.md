# Investigation: totals one cent low

Cause: `parse_amount` converts decimal text to binary float, then truncates (`ledger/model.py:16`, after `float(text)` on `ledger/model.py:15`).

Input: `0.29`
Actual: `0.28`
Expected: `0.29`

Reproduce: a CSV with one entry of `0.29`; the old float path computes 28.999999999999996 cents and `int()` truncates it to 28.
