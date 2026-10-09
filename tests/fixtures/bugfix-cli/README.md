# wordstat fixture

A tiny CLI with one deterministic defect, used by the imps bug-fix tests and the
live conformance procedure.

- Run: `python3 wordstat.py count notes.txt`
- Test: `python3 -m unittest discover -s tests`
- Reported bug: a file containing `one two` on the first line and `three` on the
  second prints `2`; it should print `3`.
