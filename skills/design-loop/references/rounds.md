# Candidate and round accounting

## Preserve the run

Record run ID, authority, scope, frozen evaluation contract, model identities and
options, task handles, phase, any explicit user limits and their consumption. Each candidate
needs an exact source identity, build/environment identity, parent candidate,
check results, judge results, finding dispositions and report path. Preserve owned
local commits where authorized, or exact patches/snapshots otherwise. Keep this
record across continuation and failed dispatches.

Each repair round starts from the current phase's best candidate, not an unselected
regression. On equal scores retain the earlier best candidate. Preserve every
candidate and its evidence. Restoring a candidate must preserve unrelated work;
use safe scoped changes or supported isolation, never destructive cleanup or
rewriting a published branch to move backwards. The code-review repair rule below
overrides the repair base when necessary to retain required bug fixes.

## State transitions

| Event | Metric and state change |
| --- | --- |
| Baseline primary evaluation completes | Seed primary best from primary score; counter = 0 |
| Primary repair round completes | Compare primary score with primary best |
| Primary target, required checks and coverage all pass | Enter panel once; do not reopen primary. Primary-only roster: accept and stop successfully |
| First complete panel evaluation | Seed panel best from minimum of all judge scores; counter = 0 |
| Panel repair round completes | Compare minimum of all current judge scores with panel best |
| Current phase metric strictly exceeds best | Replace best candidate and score; counter = 0 |
| Current phase metric equals or falls below best | Retain best; increment counter |
| Counter reaches 2 | Stop GOAL NOT MET |
| Every panel judge passes on this candidate, required checks pass and coverage is complete | Accept this candidate and stop successfully |

Apply events in this order: validate evaluation identity/completeness; test final
acceptance in panel or panel entry in primary; otherwise compare progress and test
stagnation. A gate-passing candidate advances even if its score ties or falls below
the historical best. On advancement or acceptance, leave the old counter unchanged
and record the qualifying candidate separately from the historical best. A new
panel seed sets its own counter to zero as above. If no stage gate passes, use the
normal progress/counter rules, including rounds that fix checks without raising scores.

Baseline and initial panel evaluation are seeding evaluations, not repair rounds.
If the baseline already meets the primary gate, enter panel without needless edits.
Check and coverage failures block transition and success even when the score
reaches target. Save the exact panel-entry candidate for fallback, rather than
assuming it is the primary phase's historical best.

The panel includes the primary plus the extra judges selected at setup. A
primary-only roster skips the panel, so the primary gate is final acceptance. Every
panel repair round re-evaluates the entire panel on the same frozen candidate;
historical passes cannot fill its cells. Use the rubric's fixed precision for all
comparisons. The phase change seeds a different metric; it does not reset the
explicit user limits, erase findings or restart the separate code-review budget.

## Failures and explicit limits

If the candidate cannot build or run, allow one in-round repair attempt, then
count the round as non-improving if evaluation remains blocked by that candidate.
Record its score as unavailable and the failure as the reason for incrementing;
do not assign a fictional zero. A required-check failure on an otherwise viewable
candidate retains its observed scores, but prevents acceptance.

A judge timeout, missing score, infrastructure outage or changed build makes the
evaluation incomplete. It does not advance the score counter. Allow at most one
retry of the failed operation after diagnosing the cause, within explicit user limits.
Then stop incomplete if still blocked. Do not rerun a valid low score to shop for
a higher one. Bound setup/access pilots by the same retry rule. Record failed
attempts and consumption of explicit limits even when no score exists.

No design ceiling or endpoint allowance is required. Continue until the target
and required gates pass or two consecutive rounds fail to improve the best score.
Honour any operator-set round, deadline or observable spend limit across both
phases without resetting it. An absolute deadline/spend limit also covers endpoint
work. Independent PR code review keeps its normal budget and release gates.
If an explicit limit prevents a required step, stop incomplete and report the
blocked endpoint with preserved evidence. No limit implies approval or permission
for more work.

At stagnation, an explicit limit or before proposing an extension, apply
review's [budget diagnosis](../../review/references/budget-exhaustion.md).
Preserve the scoring and stagnation rules above. Any extension request carries the
approval history, progress diagnosis, changed approach and finishing assessment
to the operator under that procedure; additional rounds alone cannot restart
the stopped run or reset its counters.

## Final candidate and PR

For success use the accepted candidate, even on a score tie. For an incomplete run
use the current phase's best fully scored candidate, with its own check status and
evidence. If panel scoring never completes, retain the panel-entry candidate and explicitly
state that it has no complete panel result. If baseline scoring never completes,
preserve the available work and report no ranked best. A no-change result does
not justify an empty PR: return the baseline/report and explain that limitation.

Freeze the selected final revision before independent code review. Confirm that
its actual diff, screenshots and check results match; any repairs after review
need reassessed review coverage. Code-review repairs honour explicit user limits;
they cannot inherit design approval for changed UI.

After required code-review fixes, select the repaired candidate as the new repair
base and final head. Retaining those fixes is a required gate: do not revert to a
higher-scored candidate that lacks them. Preserve the old best score for progress
comparisons, with its historical candidate clearly labelled; changing the repair
base does not reset scores, counters or consumed budgets. Separately track the
highest fully scored candidate retaining all required fixes, keeping the earlier
candidate on a tie. Update this eligible best even when its score stays below the
historical best. Subsequent repairs start from this eligible best, or from the
repaired candidate while no fix-retaining candidate has a complete score. On an
incomplete stop, select that eligible best as final head; if none is fully scored,
use the repaired candidate with its missing scores explicit. A new required fix
invalidates candidates lacking it, but never resets progress counters or the
historical comparison score. These rules override repair/final-head selection
from the historical best, without changing the score-based stagnation rule.

If the repair changes UI and design has not stopped for stagnation,
cancellation or an unresolved blocker, evaluate it as a panel repair round when
the run has entered panel, otherwise as a primary repair round. It counts against the
explicit user limits; apply the same stage gates, metric and counter rules.
If design has stopped or evaluation cannot run within explicit user limits, use the repaired
candidate as draft head with GOAL NOT MET, scores unavailable for that head and the
old design evidence labelled stale. Never pretend that the historical metric scores
the repaired head. Code review and required rechecks still gate PR creation; if
explicit limits prevent them, hand back a blocked PR preparation instead.

## Walkthrough cases

Use these synthetic cases to check the instructions without live models:

| Inputs | Expected outcome |
| --- | --- |
| Primary baseline 7.0; rounds 7.5, 7.5, 7.4; target 9 | Best 7.5; counters 0, 1, 2; stop, draft head is 7.5 candidate |
| Primary best 8; rounds 7.5, 8 | Counters 1, 2; recovery is not improvement |
| Primary best 8; rounds 8, 8.1 | Counters 1, 0; strict increase resets |
| Target 9; primary 9; required task fails | Stay primary; no acceptance or panel transition |
| Target 9; initial panel scores 9.2, 8.5, 9.0 | Seed panel best 8.5, counter 0; all subsequent changes need whole panel |
| Panel best 8.5; minima 8.4, 8.5 | Counters 1, 2; stop despite recovered average or individual passes |
| Panel best 9; checks fail; next candidate ties 9 with all gates passing | Accept current candidate; do not revert to failing earlier best |
| Primary best X=9.4 with failed checks; Y=9.2 fails, then Z=9.3 passes all gates; target 9 | Enter panel with Z before a stagnation stop; retain Z if panel seeding fails |
| One panel result missing after retry | No minimum, no fabricated approval; stop incomplete without increment |
| Candidate fails to build after one repair | Unavailable score, one non-improvement increment, report failure |
| Judge captures a different build | Invalidate that evaluation; bounded recovery, never transfer approval |
| Code-review UI repair S-prime after an explicit design limit reached; endpoint work permitted | Code-review repaired head S-prime; draft GOAL NOT MET, old design evidence stale |
| Code-review repair cannot fit absolute deadline or spend cap | Stop with endpoint blocked; no overrun or inferred PR review waiver |
| Historical panel best 9.4 lacks required fixes; repaired minima 8.8 then 9.0; target 9.2 | Counter advances twice against 9.4; draft head is fix-retaining 9.0 candidate |
| Code-review fix changes button copy or focus-ring colour | UI changed; renew design judging if allowed, otherwise mark changed-head approval unavailable |

These are acceptance scenarios for the instruction contract, not evidence of a
successful live design-improvement run.
