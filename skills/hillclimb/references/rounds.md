# Candidate and round accounting

## Preserve the run

Record run ID, authority, scope, frozen evaluation contract, confirmed roster,
panel trigger and primary choice, model identities and options, task handles,
phase, explicit user limits and their consumption. Each candidate
needs an exact source identity, build/environment identity, parent candidate,
check results, judge results, finding dispositions and report path. Preserve owned
local commits where authorized, or exact patches/snapshots otherwise. Keep this
record across continuation and failed dispatches.

Each repair round starts from the current phase's best eligible candidate.
On equal scores retain the earlier best candidate. Preserve every
candidate and its evidence. Restoring a candidate must preserve unrelated work;
use safe scoped changes or supported isolation, never destructive cleanup or
rewriting a published branch to move backwards. Apply the formal delivery
repair rule below when the repair base needs to retain required fixes.

## State transitions

The confirmed primary scores alone until its first valid complete score reaches
90% of the target. Compare `score × 10 >= target × 9` using the reported score
at the rubric's precision. Keep the threshold exact. At the trigger, freeze
that candidate and have the confirmed primary and secondary score it together,
along with any additional confirmed panel judges. Start the panel before
editing again, including when the initial baseline qualifies.

| Event | Metric and state change |
| --- | --- |
| Baseline primary evaluation completes | Seed primary best from primary score; counter = 0 |
| Primary repair round completes | Compare primary score with primary best |
| A complete primary score reaches 90% of target | Start the confirmed panel on this candidate |
| First complete panel evaluation | Seed panel best from minimum of all judge scores; counter = 0 |
| Panel repair round completes | Compare minimum of all current judge scores with panel best |
| Current phase metric strictly exceeds best | Replace best candidate and score; counter = 0 |
| Current phase metric equals best | Keep the earlier best candidate and clear the below-high count |
| Current phase metric falls strictly below best | Keep the earlier best candidate and increment the below-high count |
| Below-high count reaches 2 | Return a scored failure for the caller's one recovery |
| Every confirmed panel judge passes on this candidate, required checks pass and coverage is complete | Accept this candidate and stop successfully |

Validate the evaluation's identity and completeness. Record a phase seed when
applicable. Test final acceptance or panel entry before comparing progress and
testing the below-high count. A gate-passing candidate advances even if its score ties
or falls below the historical best. On advancement or acceptance, leave the old counter unchanged
and record the qualifying candidate separately from the historical best. A new
panel seed sets its own counter to zero as above. If no stage gate passes, use the
normal progress/counter rules, including rounds that fix checks without raising scores.

Baseline and initial panel evaluation seed the phase without consuming a
repair round. Required checks and coverage still gate final acceptance.
A valid primary score can trigger panel entry while those gates are open.
Save the exact panel-entry candidate for fallback.

Every panel repair round needs fresh scores from the full confirmed panel. Use
the rubric's fixed precision for all comparisons. Preserve explicit user
limits, findings and the separate formal review budget when the panel seeds
its metric. Continue in the panel phase after entry.

Before later roster changes, state the reason and get explicit confirmation.
The single automatic recovery is the exception: a replacement from an already
authorised eligible model that needs no new lineage approval may proceed
without confirmation. Record it and reseed the phase under the replacement
roster, as the recovery procedure requires; earlier scores become historical.
A confirmed expansion seeds the new panel on a single frozen candidate before
further edits, preserving earlier metrics, findings and limits. Keep prior
comparison and counters if reconciling an unavailable judge without adding
seats; a recovery replacement is a roster change, not a reconciliation.
Preserve any incomplete evaluation, failed attempts and consumed limits.
Keep a stopped run's result and apply the recovery or extension procedure below.

## Failures and explicit limits

Set and record a deadline for each judge or access attempt based on its scope
and any explicit time limit. Use a native task timeout or expiry wake where
supported. Follow the host's continuation instructions. If the host wakes only
on completion, tell the operator the deadline and how to resume if it passes.
On a continuation at or after the deadline, cancel any outstanding attempt
through the host and handle it as a timeout.

If the candidate cannot build or run, allow one in-round repair attempt.
If evaluation remains blocked, record the unavailable score and report the
blocker. Leave the below-high count unchanged. A required-check failure on an otherwise viewable
candidate retains its observed scores, but prevents acceptance.

A judge timeout, missing score, infrastructure outage or changed build makes the
evaluation incomplete. It does not advance the score counter. Allow at most one
retry of the failed operation after diagnosing the cause, within explicit user limits.
If it is still blocked, report the incomplete run and its blocker. The single
scored recovery is reserved for two consecutive below-high scores.
Keep every valid score. Bound setup/access pilots by the same retry rule. Record failed
attempts and consumption of explicit limits even when no score exists.

No fixed round ceiling or endpoint allowance is required. Continue until the
target and gates pass or two consecutive rounds score strictly below the phase high.
Honour any operator-set round, deadline or observable spend limit across both
phases without resetting it. An absolute deadline/spend limit also covers endpoint
work. Formal delivery review keeps its normal budget and release gates.
If an explicit limit prevents a required step, stop incomplete and report the
blocked endpoint with preserved evidence. Limits bound existing authority.

For a scored failure, use the [scored recovery](../../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop).
For a blocker or explicit limit, use [budget diagnosis](../../review/references/budget-exhaustion.md)
to report what would let the run continue. Keep prior counters, results and
limits in the record.

## Final candidate and PR

For success use the accepted candidate, even on a score tie. For an incomplete run
use the current phase's best fully scored candidate, with its own check status and
evidence. If panel scoring never completes, retain the panel-entry candidate and explicitly
state that it has no complete panel result. If baseline scoring never completes,
preserve the available work and report no ranked best. A no-change result does
not justify an empty PR: return the baseline/report and explain that limitation.

After the automatic recovery, rank candidates across invocations only when the
phase, rubric, target, required checks and roster all match. Otherwise use the
retry's best under the frozen current contract. A retry that starts in an
existing panel phase uses its frozen repaired baseline as the panel entry when
no complete panel score exists. A retry that starts in primary and later enters
panel keeps the candidate that entered panel when panel scoring never
completes. When neither run has a fully scored eligible
candidate, preserve the latest eligible work and report no ranked best.
Required formal fixes still constrain the handback.

Freeze the selected final revision before formal delivery review. Confirm that
its actual diff, evidence and check results match. Reassess formal review
coverage after repairs, and bind scores and required gate evidence to the
changed delivery candidate in every mode.

After required formal delivery fixes in any mode, select the repaired candidate
as the new repair base and final head. Retain the required fixes when selecting
later candidates. Preserve the old best score for progress
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
from the historical best and preserve the below-high count.

If the repair changes the candidate and scoring has not stopped after a scored failure,
cancellation or an unresolved blocker, evaluate it as a panel repair round when
the run has entered panel, otherwise as a primary repair round. It counts against the
explicit user limits; apply the same stage gates, metric and counter rules.
If scoring has stopped or evaluation cannot run within explicit user limits,
use the repaired candidate as draft head with GOAL NOT MET, scores unavailable
for that head and old scoring evidence labelled stale. If explicit limits
prevent formal review or required rechecks, hand back the blocked PR preparation.

## Walkthrough cases

Use these synthetic cases to check the instructions without live models:

| Inputs | Expected outcome |
| --- | --- |
| Primary baseline 7.0; rounds 7.5, 7.5, 7.4; target 9 | Best 7.5; below-high counts 0, 0, 1. Continue. |
| Primary best 8; rounds 7.5, 8, 7.6 | Counts 1, 0, 1. Continue. |
| Primary best 8; rounds 7.5, 7.6 | Counts 1, 2. Return a scored failure even though 7.6 rose from 7.5. |
| Target 9.0; primary scores 8.0, then 8.1 | Stay primary at 8.0. At 8.1, add the second reviewer on that frozen candidate. |
| Target 9.0; primary baseline 8.1 and a required check fails | Start the panel on the baseline. The failed check still blocks acceptance. |
| Target 9.5 at one decimal place; primary scores 8.5, then 8.6 | The exact threshold is 8.55. Stay primary at 8.5 and enter panel at 8.6. |
| Primary attempts to score but returns an incomplete report | Preserve the attempt. Evaluate the threshold only once a complete valid score arrives. |
| Target 9; initial panel scores 9.2, 8.5, 9.0 | Seed panel best 8.5, counter 0; all subsequent changes need whole panel |
| Opus high reaches the trigger and Fable high was preapproved for the panel | Fresh Fable task scores the same frozen candidate with every other confirmed judge. Seed using the panel minimum and retain earlier scores and consumed limits. |
| Primary and one additional judge pass; a second confirmed additional judge has yet to return | Panel incomplete, no acceptance and no progress comparison |
| Panel best 8.5; minima 8.4, 8.5 | Counts 1, 0. The tie clears the streak. |
| Panel best 9; checks fail; next candidate ties 9 with all gates passing | Accept current candidate; do not revert to failing earlier best |
| Target 9.0; primary 9.4 and panel minimum 8.6 on the same candidate | Retain the primary history and seed the panel high at 8.6 with count zero. The target remains 9.0. |
| One panel result missing after retry | When the recovery is unavailable, no minimum, no fabricated approval; stop incomplete without increment |
| A judge is still pending at the attempt deadline | Cancel the timed-out attempt, record the missing result, and use the bounded incomplete-evaluation rule |
| Candidate fails to build after one repair | Blocked evaluation, unavailable score and unchanged count |
| Judge captures a different build | Invalidate that evaluation; bounded recovery, never transfer approval |
| Code-review repair S-prime after the scoring limit is reached; endpoint work permitted | Code-review repaired head S-prime; draft GOAL NOT MET, old score evidence stale |
| Code-review repair cannot fit absolute deadline or spend cap | Stop with endpoint blocked; no overrun or inferred PR review waiver |
| Historical panel best 9.4 lacks required fixes; repaired minima 8.8 then 9.0; target 9.2 | Count advances twice against 9.4. On final stop, the fix-retaining 9.0 candidate is the draft head. |
| Formal review changes a workflow, document or UI candidate | Renew scoring and covering checks if allowed; record changed-candidate approval as unavailable otherwise |
| Formal review permits coordinator verification under `review_rounds: 1`, but the repaired head has no Hillclimb score | The formal recheck can pass. Hillclimb remains incomplete until its own score and checks pass |
| Evaluation stays blocked after its one operation retry | Report the blocker without spending the scored recovery. |
| Retry changes the rubric or roster and passes | Deliver with the original and revised targets flagged; older scores are historical |
| Retry starts in an existing panel phase and panel scoring never completes | Hand back the retry's frozen repaired baseline as the panel entry and state that it has no complete panel result |
| Retry starts in primary, later enters panel, and panel scoring never completes | Hand back the candidate that entered panel and state that it has no complete panel result |
| Explicit repair-round cap is spent | A setup-only fix may recover; a candidate-changing fix is blocked and reported |
| Deadline or spend cap is already exhausted | Record the recovery as failed before dispatch and report; dispatch nothing |
| Resume finds a started recovery with no usable handle | Treat the recovery as spent, dispatch nothing and report |
| Resume sees `dispatching` with no handle | Treat the slot as spent, reconcile the repair and report; never relaunch |
| Retry delegate lacks the original run ID and recovery slot | Invalid recovery; carry both in its brief and return its outcome to the original coordinator |
| Recovery replaces a timed-out panel judge with an authorised eligible model | No new confirmation; record it, reseed the panel and label earlier scores historical |
| Neither invocation has a fully scored eligible candidate | Preserve the latest eligible work, report no ranked best and name the retry's frozen baseline as fallback |
| Retry starts in an existing panel phase and the old panel-entry candidate is ineligible | Use the retry's frozen repaired baseline as the panel-entry candidate |

These synthetic acceptance scenarios check the instruction contract. Verify
live run access and behavior separately.
