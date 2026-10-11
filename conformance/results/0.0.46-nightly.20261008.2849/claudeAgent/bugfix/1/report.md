# Run 20261009-130011-58da50: completed

Phase `completed` at generation 19. Readiness: `ready`. Repository `~/.t3/scratch/2026-10-09-this-thread-runs-the-imps-f9ad676c/bugfix-1` on `case/bugfix` at `e0c1a65d1791`.

**Brief:** wordstat count prints 2 for notes.txt ("one two" line 1, "three" line 2); expected 3

## Notes

- **cause:** wordstat.count_words used text.split(" "), which splits only on spaces, so words separated by newlines merged ("two\nthree" counted as one) and notes.txt gave 2.
- **fix:** Changed count_words to len(text.split()) (split on any whitespace) and added CLI-seam test_multiline; no larger change needed.
- **before:** red.log: count notes.txt printed 2 (expected 3); red-test.log: test_multiline failed 2 != 3.
- **after:** green.log: count notes.txt prints 3; unit-g5.log: all 3 tests pass at e0c1a65.

## Requirements

| ID | Kind | Status | Explanation |
| --- | --- | --- | --- |
| REQ-REPRO | command | passed | Original command rerun unchanged prints 3 (was 2 in red.log). |
| REQ-REGRESSION | command | passed | CLI-seam test_multiline failed before the fix (2 != 3, red-test.log) and passes after (unit check, exit 0). |

Counts: passed 2, failed 0, unverified 0, unavailable 0, waived 0. Waived is never counted as passed.

## Checks

- `python3 -m unittest discover -s tests`: passed

## Review

- Required: True; status: passed
- Round 1: approve by codex/gpt-6.1-sol (task node:delegated-task:command%3Amcp%3Ade1b38c7-b6d1-4d5d-a6dc-1366f22c7db0%3Adelegate-task%3A20261009-130011-58da50%253Areview-1%253Ar1, request 20261009-130011-58da50:review-1:r1). Why: default chain: first available catalog provider that is not the implementer; first catalog provider other than ['claudeAgent']; available in the live catalog

## Delegated tasks

- review-1 round 1 (initial): T3 task `node:delegated-task:command%3Amcp%3Ade1b38c7-b6d1-4d5d-a6dc-1366f22c7db0%3Adelegate-task%3A20261009-130011-58da50%253Areview-1%253Ar1`, request `20261009-130011-58da50:review-1:r1`, last status completed

## Evidence

Artifacts: `$TMPDIR/b1/state/runs/20261009-130011-58da50/artifacts` (never removed by cleanup).
