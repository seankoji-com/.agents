# Diagnose a stalled or exhausted review

The coordinator reads this before proposing more rounds, using a caller's
automatic extension, or escalating a review that has stopped making progress.
Use the existing reports and checks for this diagnosis, not another evaluator.
This procedure preserves the caller's limits and release gates. It grants no
extra rounds, model upgrades, scope changes or authority to ship.

## Reconcile allowance and approval history

Retain the original allowance or stopping rule and each extension in the task's
existing record. For each extension, record its amount, whether user-approved or
caller-granted automatically, the approval message or caller rule establishing
authority, and attempts consumed. Distinguish extensions already used from the
one now proposed. Carry this history through resumes and parent handoffs.

Reconcile cumulative authorised allowance, attempts used including failures,
and remaining allowance before proposing an addition. Show the proposed amount
and resulting total separately from existing authority. For uncapped workflows,
state the actual scoring and stagnation rules and any explicit limits instead of
inventing a round cap. Keep separate budgets distinct. Record automatic
extensions even when they needed no user question.

Recover missing history from available task records first. Label unrecoverable
approvals, amounts or consumption unknown; do not treat them as zero or infer
permission to continue. If an unknown prevents establishing remaining authority,
hold dependent review and identify the exact confirmation needed.

## Establish what another round could change

Reconcile the round ledger with the current revision. For each attempt, record
the stable finding IDs, severity, evidence, disposition, repair made and result
of the covering check. Count failed attempts. Identify which findings are new,
fixed, reopened or unchanged. Preserve the ledger across resumes and reviewers.
Include each attempt's material result and, for scored loops, the target, best
and current scores and stagnation counter under the caller's accounting rules.

Classify the remaining obstacle using the evidence:

- A reproducible defect needs a repair or an authorised disposition.
- Missing runtime evidence, a broken environment or unavailable permissions need
  access or a focused experiment. Another source opinion may add nothing.
- An unresolved product decision needs a precise choice from its owner.
- Reviewer disagreement needs comparison against requirements and evidence.
  Repeated agreement requests and style preferences do not establish a defect.

Look for the same finding surviving successive repairs, repairs undoing each
other, expanding scope, moving acceptance criteria, repeated tool failures or
rounds producing no new evidence. State whether progress is converging, stalled
or cycling, and cite the attempts that support that assessment. A high severity
alone does not make another round useful.
Explain why the allowance ran out or the stopping rule fired. Explicitly reassess
whether the current scope, acceptance criteria and repair strategy still offer
a credible path to the goal. Distinguish necessary discovery from scope drift;
changing acceptance criteria requires its own authority.

First apply [review's release treatment](../SKILL.md). If the current reviewed
behavior meets the criteria and only non-blocking findings remain, close with
explicit dispositions and required bug tracking. Do not spend another round on
declined nits or unanimity. Unreviewed material repairs, missing required proof
and unresolved blocking findings still prevent acceptance.

## Choose a credible next approach

Recommend an approach tied to the diagnosed cause, with its next action,
expected evidence, cost or effort and remaining risk. Assess at least one
alternative to extending the review count. Choose the relevant route, rather
than presenting a generic menu:

- Build a targeted reproduction or run the missing check on the exact revision.
  Explain what result would confirm or reject the suspected cause.
- Change the repair strategy within scope, such as replacing an oscillating
  patch with a simpler implementation. Identify the different hypothesis and
  retain the caller's implementation and model-upgrade limits.
- Propose a smaller deliverable or a return to an already reviewed checkpoint.
  Explain what the user would lose and obtain authority for a material scope
  change or revert. Changed behavior still needs the applicable review.
- Preserve the unresolved work and send a concrete evidence packet to the owner
  of a missing environment, permission or upstream fix. Finish independent
  authorised work and identify the exact action needed to unblock the rest.
- Ask the specific product or risk decision that only the user can make.

Do not manufacture an alternative that cannot satisfy the user's goal. When
every credible route depends on the same external gate, explain that constraint
and provide the prepared work and recovery action.

Recommend additional rounds only when a changed hypothesis, new evidence or a
different bounded approach gives them a specific purpose. State what the next
round will evaluate, why it can change the outcome, the proposed count and the
stop condition. Obtain any required extension authority before dispatch. The
caller may allow an extension without a new question, but it still requires
this diagnosis and a recorded authority source. A new reviewer or phase label
never resets the budget.
When the caller's limit admits no extension, as with think's readiness
limit, report the diagnosis and incomplete gate without proposing extra rounds.

Assess whether the proposed allowance can plausibly finish the remaining work
or only fund a specific experiment. Explain the evidence for that assessment,
dependencies, uncertainty, and what happens if the expected result fails to
appear. Completion remains conditional on required checks and review gates;
do not promise that a count of rounds guarantees it.

Without an evidence-backed changed approach, hold further review instead of
asking for more rounds with low confidence. Complete useful independent work
within existing authority and return the concrete blocker, recovery action or
credible alternative. User approval of a count alone does not supply the missing
diagnosis or waive the caller's other stopping rules.

## Escalate a decision, not a counter

Every extension request must be self-contained where the user makes the
decision. Give the parent or user a concise assessment containing:

- Original allowance/stopping rule; each previous extension and its authority;
  cumulative allowance, attempts used and remaining; proposed addition and
  resulting total. Explicitly state when there were no prior extensions or
  history is unknown. Separate user approvals from automatic extensions.
- Current revision, outstanding finding IDs and gates, and each round's material
  result. Explain why the budget or stopping rule was reached and support the
  converging, stalled or cycling diagnosis with specific attempts.
- Reassessment of the path to the goal; the changed approach, expected new
  evidence and why it can change the outcome. Compare a credible alternative,
  including what can finish now and what remains blocked.
- Finishing prospects within the proposed allowance, supporting evidence,
  dependencies and uncertainty. State whether this aims to finish or to resolve
  one experiment, the exact stop condition and the action if it fails.
- The recommended decision and bounded extension only when justified. Make
  the consequence of declining clear without presenting an unjustified extension
  as the only route forward.

Do not default to "approve more rounds" as the recommended choice against
"stop and block". Continue a changed approach within existing authority and
budgets; ask only for a material decision or missing authority. A delegated
coordinator returns this assessment to the main thread. It cannot grant itself
more rounds or ask the operator directly when its role requires a parent handoff.
The main thread preserves these decision fields in the user-facing request;
links to earlier reports may supplement them but cannot replace them. Verify
delegated authority claims or mark them unknown rather than dropping the history.

## Continue a stopped scoring loop

Use this for an incomplete `review-loop` or `hillclimb` run. Preserve its
outcome and complete the diagnosis above.

### One automatic recovery

A failed invocation gets one recovery before any operator question. A failure
is a stop-incomplete run or an evaluation operation that still fails after its
one retry; formal delivery review keeps its own rules. The loop skill's
standing rule supplies the authority for this one retry. The recovery may
change the repair strategy, implementation, setup, loop rubric, target,
loop-required checks and a roster seat, but not scope or a hard gate.

1. Record before acting, against the original run ID: `committed` with the
   trigger and diagnosis before the fix; `fix-failed` when that fix fails or
   is blocked, before any dispatch; `dispatching` with the intended route and
   frozen candidate before the host call or the first inline retry action;
   `started` with the delegate task and child thread, or the inline run ID and
   start time, once the retry begins; `returned` with its result. On resume,
   reconcile the repair from the retained evidence. A `committed` record with
   no later outcome may resume the fix and launch once. `fix-failed` means the
   recovery is spent: keep the stop, dispatch nothing and report the failed or
   blocked fix. `dispatching` or `started` without a usable handle means the
   slot is spent and the launch state is unknown, so report and never relaunch.
   No recoverable record means no automatic recovery.
2. Diagnose from the retained evidence; start no evaluator for the diagnosis.
   Keep the existing one-operation retry inside every invocation. Only this
   loop-level recovery is capped at one.
3. Preauthorised changes are the repair strategy, implementation, setup, loop
   rubric, target, loop-required checks, and a roster replacement from an
   eligible model already authorised for the run that needs no new lineage
   approval. Prefer a confirmed alternate. Record every change and its reason.
   A new provider or model, user constraint, repository gate, permission,
   publication authority, formal delivery review or scope change blocks the
   recovery. Record `fix-failed`, report and stop.
4. Fit the remaining allowance before the fix. An explicit repair-round cap
   counts a candidate-changing fix, including a pre-baseline fix.
   Re-baselining consumes no repair round. An exhausted deadline or spend cap
   blocks every recovery action, including setup. A spent repair-round
   allowance still permits a setup-only recovery and blocks a
   candidate-changing fix. Record either blocked case as `fix-failed`: the
   slot is spent because the limit made that recovery unavailable.
5. Freeze the latest candidate after the fix as the new baseline before scoring,
   and retain the phase: primary stays primary; panel stays panel with every
   confirmed scorer. Reuse a score only when the candidate and evaluation
   contract both match. A roster or criteria change seeds a new baseline under
   the frozen revised contract.
6. Start a fresh non-improvement counter. Preserve prior scores, findings,
   candidates and consumed limits as history, and append a new era to the score
   ledger for the [score line graph](score-chart.md) with `comparable_to_prev: false`
   whenever criteria or roster changed. A pass under a revised
   evaluation contract, whether criteria or roster, delivers normally, with the
   report and PR naming the original target, the revised one, the reason and
   the score history. It never claims the original target was met.
7. The retry is one run, not a new one. Give its launch brief the original run
   ID and the consumed recovery slot, and require it to return its outcome to
   the original coordinator. A failure inside the retry ends the recovery; it
   never opens a new slot. If the retry also fails, stop and report both
   triggers, diagnoses, fixes, attempts, scores, limits and unresolved gates.
   Start no second recovery and no continuation delegate.

Handback after a second failure: under an unchanged contract, use the best
eligible candidate across both invocations that retains required fixes, even
when the retry scored lower. When the phase, rubric, target, required checks or
roster changed, scores are not comparable. Use the retry's best under the
frozen current contract. If the retry started in an existing panel phase and
never completed a panel score, use its frozen repaired baseline as the panel
entry. If the retry started in primary, later entered panel, and never
completed a panel score, use the candidate that entered panel. If the retry
never entered panel and panel scoring never completed, use the earlier
panel-entry candidate. If neither invocation has a fully scored eligible
candidate, preserve the latest eligible work, report that there is no ranked
best, and
name the retry's frozen baseline as the fallback. Mark older scores historical.

### Operator-approved continuation

After the automatic recovery is spent, collect short retrospective notes
from the implementer, or write them yourself if you did the implementation.
Reconcile the attempts, useful evidence, failed assumptions and what would
change the outcome. Ask the implementer to recommend a change to the premise,
solution or way the loop works. Use existing handoffs and request missing notes
from the implementer when available. If you cannot obtain them, identify the gap
and use the evidence the run retained.

Present the latest candidate, its known scores and checks, the recommendation
and its tradeoff. Give the operator the choice to stop with the existing result
or approve a changed approach starting from that latest candidate. If a
blocker prevents continuation, name what would unblock it. A request for more
rounds alone does not restart the loop. Get explicit approval for the approach
and any changes to scope, rubric, roster, checks or limits before proceeding.

For an approved continuation:

1. Preserve the old run's best and latest candidates, scores, findings,
   non-improvement counter, attempts, consumed limits and the spent recovery
   slot. Record the approved changes in the same ledger or report. Carry
   forward remaining authority, required repairs and delivery gates.
2. Freeze the latest candidate as the new baseline. Retain any required fixes
   and record a new revision if they need to be reapplied. Reuse valid scores
   and check evidence for that exact candidate and evaluation contract.
   Obtain missing or invalidated evidence before seeding the new score and
   setting the new non-improvement counter to zero. Keep results under old
   scoring criteria labelled as historical.
3. Carry forward successful judge capability and access checks when they cover
   the same judge, route, permissions, environment and required actions.
   A new baseline alone calls for no new pilots. Probe only capability or
   access that was never established or whose conditions changed. Run the
   required checks, fresh captures and evaluations for changed candidates
   under the workflow's normal rules.

## Walkthrough cases

Use these synthetic cases to check the instruction contract without live models:

| Situation | Required assessment and action |
| --- | --- |
| First extension for a caller that permits extensions after a three-attempt allowance; a failed dispatch and two completed reviews used it | State no previous extensions, 3 authorised, 3 used, 0 remaining; propose 1 additional, total 4, pending approval. Explain each attempt, changed approach, likely outcome and stop condition before requesting it. |
| Think exhausts its hard three-readiness-review limit | Report the diagnosis and readiness incomplete. Hold implementation; do not propose a fourth review. |
| Resume after 3 original attempts, a user-approved addition of 2, then a separately approved addition of 1; 6 used | Show both approvals and their amounts, 6 authorised/used and 0 remaining. A proposed addition of 1 makes 7 only if approved. Resume and reviewer changes grant no fresh budget. |
| Caller allowed one automatic addition of 2 after its original 3; all 5 used | Show the automatic addition and its caller-rule authority separately from user approvals. Any later request reports 5 used, not just the original 3. |
| A finding survives successive repairs and the next proposal repeats the same repair without new evidence | Diagnose stalled or cycling using the attempts. Hold review, omit an extension request, and give a reproduction, different repair or concrete blocker while independent work continues. |
| Old approval says only "continue" and the amount cannot be recovered | Mark the amount and cumulative authority unknown; show known consumption. Hold dependent review if remaining authority cannot be established and request the precise missing confirmation. |
| Uncapped scored loop stops after two non-improving rounds | Show target, best/current scores, counter and actual attempts; state no numeric cap. Diagnose stagnation, apply the single automatic recovery, then propose a changed approach; extra rounds alone do not override the stopping rule. |
| After two non-improving rounds, best is 8.8 and latest is 8.4. The automatic recovery is spent and the operator approves a different repair strategy. The latest candidate's evidence, rubric, check context and judges still apply | Seed the new phase at 8.4 with counter zero. Retain the 8.8 result, stopped phase and consumed limits. Reuse the existing capability pilots. |
| Latest candidate has a missing score, or the operator changes the rubric or a judge's required test modality | Keep the candidate as baseline, obtain the missing or invalidated evidence, and probe only capability or access the earlier checks did not prove. Seed the new score when the required evaluation is complete. |
| A technical failure remains after its one operation retry | Record the recovery, diagnose, fix, and re-invoke once from the latest candidate with a fresh counter. |
| The recovery retry also fails | Stop the loop and report both attempts; no second recovery and no continuation delegate. |
| An explicit repair-round cap is spent | Permit a setup-only fix; block a candidate-changing fix, report it and stop. |
| A deadline or spend cap is already exhausted | Record `fix-failed`, dispatch nothing and report. The slot is spent because the limit blocked recovery. |
| The retry revises the rubric or roster and passes | Deliver with the original and revised targets flagged; never claim the original target was met. |
| The retry starts in an existing panel phase and never gets a complete panel score | Hand back the retry's frozen repaired baseline as the panel entry and state that it has no complete panel result. |
| The retry starts in primary, enters panel on a later candidate, and never gets a complete panel score | Hand back that later panel-entry candidate and state that it has no complete panel result. |
| A resume finds `committed` followed by `fix-failed` | Treat the recovery as spent, dispatch nothing and report the failed or blocked fix. |
| A resume finds `committed` with no later outcome | Resume the fix and launch once. |
| A resume finds `started` with no usable handle | Treat the recovery as spent, dispatch nothing and report the unknown state. |
| A resume finds `dispatching` with no handle | Treat the slot as spent, reconcile the repair from evidence and report; never relaunch. |
| The retry brief omits the original run ID or recovery slot | Invalid recovery; carry both and return the outcome to the original coordinator. |
| Neither invocation has a fully scored eligible candidate | Preserve the latest eligible work, report no ranked best and name the retry's frozen baseline as fallback. |
| First run best is 8.8; the retry under the same contract finishes at 8.4 | Hand back the 8.8 eligible candidate that retains required fixes; the lower retry does not replace it. |

These walkthroughs specify expected decisions, not observed live-agent compliance.
