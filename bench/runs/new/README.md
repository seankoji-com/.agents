# Stage 5 benchmark evidence

Outcome: **blocked** on REQ-B-NEW and the benchmark gates that depend on it
(REQ-B-GATE-A, REQ-B-GATE-B, REQ-B-TOKENS). All eight attempts are void under the
confinement audit, and each slot has used its one permitted retry. There is no valid
new run to compare with `bench/runs/old/`. The implementation, grader, version and
migration work are reviewed and kept; whether the new version meets the quality
and parent-token targets is still unproven.

On 2026-10-11 the owner deferred the benchmark to
[#21](https://github.com/seankoji-com/t3-plugins/issues/21) and folded stage 5 into
`master` without it. The benchmark requirements are waived for this stage, not passed.

The issue body was saved in the executor run's scratch notes before implementation,
and all work used that copy of issue #15.

## Requirements

| REQ | Status | Evidence |
| --- | --- | --- |
| REQ-B-GRADER | Met | `bench/checks/task_b.py`, sha256 `f00c365c…`, frozen in `cc014ab` after five review rounds; validation in `bench/checks/task_b_validation.json`; old B runs regraded |
| REQ-B-NEW | **Blocked** | 8 attempts run and recorded; 0 valid. Retries exhausted ([attempts.json](attempts.json)) |
| REQ-B-GATE-B | **Unproven** | All four B attempts pass the behaviour grader, but every attempt is void |
| REQ-B-GATE-A | **Unproven** | All four A attempts pass the required checks; blind grades are informational only |
| REQ-B-TOKENS | **Unproven** | No accepted new median exists; none is calculated from void attempts |
| REQ-B-REPORT | Met | Every attempt below, with summaries, hashes, delegations and audit decisions |
| REQ-SIZE | Met | 1,563 core Python lines against the 2,156 limit (baseline 4,313), [size.json](size.json) |
| REQ-MAJOR | Met | All five `plugins/*/plugin.json` at `1.0.0`; no release cut |
| REQ-MIGRATION | Met | `docs/migration.md` "Plugin version 1.0.0"; ledger labelled "Historical port: pre-1.0.0" |

## Attempts

All runs used Claude Opus 5.5 at `xhigh` as the parent and the same 62-file package
([package.json](package.json)). Attempt 1 launched before the grader's valid freeze.
Retries launched after `cc014ab`. Child tokens are the Codex rollouts' reported
cumulative totals, which include cached input, so they are not comparable to the
parent figure.

| Slot | Attempt | Run outcome | Audit | Wallclock (min) | Parent-Opus tokens | Children: tokens | Delegations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | 1 | completed | void | 40.1 | 427,872 | 7: 2,330,369 | 4 review, Sol 6.1 high |
| A1 | 2 | completed | void | 30.1 | 356,409 | 2: 1,631,753 | 2 review, Sol 6.1 high |
| A2 | 1 | completed | void | 19.8 | 304,361 | 2: 777,816 | 2 review, Sol 6.1 high |
| A2 | 2 | completed | void | 31.9 | 441,505 | 3: 961,426 | 3 review, Sol 6.1 medium |
| B1 | 1 | blocked | void | 50.0 | 394,072 | 4: 5,057,274 | 3 review, Sol 6.1 high |
| B1 | 2 | cancelled | void | 24.6 | 277,278 | 1: 327,578 | 1 review, Sol 6.1 medium |
| B2 | 1 | completed | void | 35.9 | 280,689 | 3: 2,761,625 | 2 review, Sol 6.1 high |
| B2 | 2 | completed | void | 48.6 | 426,595 | 6: 4,686,372 | 3 review, Sol 6.1 high |

Each delegation's stated reason is in its attempt's `summary.json`. Every new run sends its
review to Codex children, whereas the old B runs had none. A lower parent count for a new B
run would therefore not show lower total cost. B1's retry was cancelled
while its own checks were pending; the cause is unknown, and its summary keeps that
state as observed.

Task results (informational): all four A attempts pass every required check. All
four B heads pass the behaviour grader on an isolated clone and fail the upstream
design tests (`matches_upstream_design: false`), as both old fixes do. Retry blind
grades: pair 1 prefers old (0.96 against 0.89); pair 2 prefers new (0.93 against 0.85).
Attempt-1 grades are in [grades/](grades/). No attempt is counted.

## Confinement adjudication

Each retry's audit decisions ([A1](a1/attempt-2/audit-decisions.json),
[A2](a2/attempt-2/audit-decisions.json), [B1](b1/attempt-2/audit-decisions.json),
[B2](b2/attempt-2/audit-decisions.json)) classify every non-ok finding against the private audit, whose sha256 it records. Regexes, sed ranges,
shell-variable suffixes and in-script strings were checked in context; any finding
no rule covered would fail the adjudication.

| Slot | Void basis |
| --- | --- |
| A1 | Parent read a harness-bundled skill reference; reviewer read a global agent skill |
| A2 | Reviewer read a global agent skill |
| B1 | Parent listed the owner's t3-plugins configuration; reviewer read a global agent skill |
| B2 | Reviewers read a global agent skill, the provider memory file and dotfile runtime guidance |

Attempt-1 decisions use the earlier generic fragment classification. Their void
outcomes rest on the same kinds of read: global skills, provider memory, the learnings
store, dotfile guidance and owner configuration.

The pattern is consistent. Reviewer children start in a provider home that loads
global instructions and memory, and a worker prompt cannot prevent that. Another
benchmark needs a confinement setup that isolates child providers. The owner has not
yet authorised that protocol change.

## Grader preparation

The first REQ-B-GRADER freeze was invalid: the workers launched before it, and reviews
found false passes. Three repairs followed, then one more round that the owner
authorised for M3 (stat-result slices and negative indexes exposed the real inode).
Round 5 found no blocker or major issue. See [grader-rejection.json](grader-rejection.json) and [review.json](review.json).

| Round | Findings | Disposition |
| --- | --- | --- |
| 1 | Incomplete inode coverage; summariser naming; provenance; checks under `-O`; migration wording | Fixed, with regression cases and a diagnostic matrix |
| 2 | Import-bound stat aliases and defaults; subprocess and native-code reads | Aliases and defaults fixed; external and native reads documented as an unverified gap |
| 3 | Recreated `.git/worktrees` parent; direct native-OS stat | Fixed, with regression cases |
| 4 | Stat-result slices and negative indexes expose the real inode (M3) | Fixed in the owner-authorised extra round |
| 5 | Optional proxy type/copy/pickle limits; amendment wording | Limits documented; wording fixed before retry launch |

## Checks and changed tests

[local-evidence.json](local-evidence.json) hashes the test, docs and strict MkDocs logs
at implementation head `0181c2b`. The same checks are rerun at the commit that adds
this file and recorded in the executor's imps run, not here, so that recording them
cannot make the checked head stale. Raw logs stay private. The grader's tests also
pass on Python 3.10.22. Documentation was inspected at 1280×800 and 390×844.

| Test file | Change | Reason |
| --- | --- | --- |
| `tests/test_task_b_grader.py` | Added | Real Git resources, positive control, several inode-only designs, descriptor/scandir/pathlib, import aliases and defaults, containing-directory inodes and native-OS calls; non-inode stat fields stay real |

No existing test or assertion was changed or deleted. No workflow file changed.

## Scope and private storage

Source changes are confined to this repository. `<executor>` holds the saved issue,
imps run state, docs virtual environment, Python 3.10 interpreter, validation trees,
logs and preview. `<home>/t3-plugins-bench/` holds the scratch installs, eight
workspaces, and private transcripts, audits, blinding keys and grading bundles. The
owner's configuration, default installs, provider settings and dotfiles were not
changed. Patch author lines are redacted as in `bench/runs/old/`.

Recorded worker output is kept verbatim with one exception: line 57 of
`a2/output/tests/render_check.py` now matches the tile URL with a regex instead of a
substring test, to clear CodeQL alert 3 (`py/incomplete-url-substring-sanitization`),
which blocked the merge. The check's result is unchanged for the recorded page.

The stage merges by owner instruction with the benchmark gates waived. Release, tap
update and Pages deployment are not part of this stage.
