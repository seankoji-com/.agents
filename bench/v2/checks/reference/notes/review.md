Verdict: approve
Finding: The seeded decimal truncation defect is repaired in the current implementation.
Changed: ledger/model.py:22
Seeded: ledger/model.py:16, input 0.29, actual 0.28, expected 0.29
Evidence: C2-exact-cent-totals PASS with food\t24.20; C8-workspace-tests-pass PASS on the current workspace.
Disposition: fixed
