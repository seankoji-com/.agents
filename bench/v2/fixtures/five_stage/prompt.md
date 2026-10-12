The repository in your workspace is a small CSV ledger (`python3 -m ledger`). Complete
the five stages below in order. Each stage depends on the accepted result of the stage
before it. Commit at the end of each stage on the current branch with a message that
starts with `stage-N:` (for example `stage-2: exact cent arithmetic`).

**Stage 1: investigate.** Users report that account totals are sometimes one cent too
low, for example an entry of `1.15` is counted as `1.14`. Find the root cause without
changing code. Write `notes/investigation.md` with the cause, at least one reproducing
input, and a citation of the defective line in `path:line` form against the current
revision.

**Stage 2: fix.** Parse amounts exactly. An amount has an optional leading `-`, digits,
and at most two decimal places (`3`, `2.5`, `-0.05`, `1200.00`). Anything else,
including exponents such as `1e3`, more than two decimal places, or an empty value, is
invalid: every command prints `error: <reason>` to stderr, prints nothing to stdout and
exits with status 2. Add regression tests.

**Stage 3: monthly report.** Add `python3 -m ledger report FILE --by month`. Print one
line per month and account that has at least one entry: `YYYY-MM<TAB>account<TAB>total`,
with the total formatted like `total` does. Sort by month, then account. A date that is
not a valid `YYYY-MM-DD` calendar date is invalid input (same error contract as stage
2). Add tests.

**Stage 4: audit.** Audit the `export` command for spreadsheet formula injection and for
destructive path handling. Write `notes/audit.md` listing each finding with a severity
(high, medium or low), the evidence, and whether it is fixed. Fix every confirmed
finding and add tests. Exported amounts must remain plain numbers.

**Stage 5: integrate.** Update `README.md` for every user-visible change and add entries
for all of them under `## Unreleased` in `CHANGELOG.md`. The full test suite
(`python3 -m unittest discover -s tests`) must pass. Obtain an independent review of the
combined change and record its verdict and every finding, with what you did about each,
in `notes/review.md`.

Use only the Python standard library.
