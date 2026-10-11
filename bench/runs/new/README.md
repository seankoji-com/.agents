# Stage 5 benchmark evidence

Status: **in progress**. Attempt 1 artifacts in this directory are not an
accepted new baseline or a fair comparison. The issue body was saved in the executor run's scratch notes before
implementation; all work used that saved copy of issue #15.

This is an interim handoff snapshot, not the terminal stage report. Both retry
Task A blind grades have been collected and their arithmetic verified:
pair 1 prefers old (0.96 versus 0.89); pair 2 prefers new (0.93 versus 0.85).
Both are informational because preliminary confinement audits void the retries.
Retry A1, A2 and B1 summaries are retained; B2 still needs final collection.
Final confinement adjudications, private-file hashes, the final requirement
matrix, final-head checks and the executor's terminal closeout remain outstanding.
No further benchmark retry or protocol waiver is authorised.

The initial REQ-B-GRADER preparation was invalid. The executor launched all four workers
before the grader's valid freeze; subsequent reviews found false passes and
required three repairs. Review round 4 found M3: stat-result slicing and
negative indexing exposed the real inode. After three repairs, the owner explicitly
authorised one additional repair round. M3 is now fixed with regression cases; the
fresh review found no blockers or majors and approved the grader within its documented scope. A local negative-index mutant reproduced
the false pass; the slice mutant failed in that invocation, consistent with the
reviewer's observed filesystem dependence. See [grader-rejection.json](grader-rejection.json).

REQ-B-NEW and the benchmark acceptance gates remain unmet until valid retries
finish and are graded. The package
used by the four attempts was built from `12b51fc`, not the final code head. It is
kept immutable and its manifest and verification results are retained. Later
grader edits make the attempts stale independently of their audit decisions.
All four protocol-authorised retries launched after the approved grader was frozen
in `cc014ab`, using the scratch package built from implementation commit `0181c2b`. The initial process deviation remains in the record.
No owner waiver is assumed.

## Retained implementation

- A real CLI-recorded worktree probe, with an untouched positive control and an
  inode-reuse replacement check. The candidate matrix is red on the unfixed base,
  green on upstream and both old fixes, and red on refusal of all cleanup.
- All five plugin manifests at `1.0.0`.
- Migration reasons and upgrade steps for both retired plugins, dispatcher/claim/
  generation removal, and consolidated delegation rules. The compatibility ledger
  is labelled with its historical version; no new provider certification is claimed.
- Core size: 1,563 Python lines versus 4,313 baseline lines and the 2,156 limit.

## Review disposition

| Round | Findings | Disposition |
| --- | --- | --- |
| 1 | Incomplete inode coverage; summariser naming; provenance; checks under `-O`; migration wording | Fixed, with regression cases and diagnostic matrix |
| 2 | Import-bound stat aliases/defaults; subprocess/native-code reads | Aliases/defaults fixed; external/native reads documented as an unverified gap |
| 3 | Recreated `.git/worktrees` parent; direct native-OS stat | Fixed, with regression cases |
| 4 | Stat-result slices/negative indexes expose real inode (M3) | Fixed in one additional owner-authorised repair round; round 5 approved |
| 5 | Optional proxy type/copy/pickle limitations; pending amendment wording | Limitations documented and deferred; wording fixed before retry launch |

The owner authorised committing and pushing this interim snapshot for handoff.
No PR has been opened; the benchmark acceptance gates remain unmet.
Hosted CI, merge, release, tap update and Pages deployment have not occurred.

## Checks and changed tests

Local test, docs and strict MkDocs checks pass. The grader's six test methods also
pass on isolated Python 3.10.22. The additional repair includes M3 regression cases. Documentation pages
were inspected at 1280×800 and 390×844, with no horizontal overflow.
Log hashes and the size breakdown are in [local-evidence.json](local-evidence.json)
and [size.json](size.json). Raw logs remain private.

| Test file | Change | Reason |
| --- | --- | --- |
| `tests/test_task_b_grader.py` | Added | Preserve all real non-inode stat fields; exercise real Git resources, positive control, several inode-only designs, descriptors/scandir/pathlib, import aliases/defaults, containing-directory inodes and native-OS calls |

No existing tests or assertions were changed or deleted. No workflow files changed.

## Scope and private storage

Source changes are confined to this repository. The disposable executor root is
`<executor>`; the saved issue, imps run state, virtual environment, isolated Python
3.10 interpreter, validation trees, check logs and documentation preview live there.
`<home>/t3-plugins-bench/` holds scratch installs, eight fixture workspaces and private
transcripts/audits/grading bundles. The executor did not alter the owner's real
configuration, default installations, provider settings or dotfiles. Audit findings
about worker/child reads outside confinement are retained and adjudicated separately.

Each attempt has a summary, final worker report, committed output, raw-file hashes
and an audit-decision record. Initial-attempt results and blind grades are informational only. Retry eligibility
is determined by each final confinement audit.
Parent-Opus tokens are a parent-context metric, not proof of total cost. Children are
reported separately with measured tokens or unknown; no unknown amount is treated as 0.
