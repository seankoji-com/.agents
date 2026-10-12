# Export audit

| Finding | Severity | Evidence | Status |
| --- | --- | --- | --- |
| Text cells starting with `=`, `+`, `-`, `@`, tab or CR are evaluated as formulas by spreadsheets | high | `write_csv` wrote descriptions verbatim | fixed: such cells get a leading `'`; amounts stay numbers |
| `export FILE FILE` overwrites its own input | medium | output opened for writing without checking it is the input | fixed: refused when both name the same file |
