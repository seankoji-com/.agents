---
name: review-loop
description: "Run independent review and repair rounds. Use when asked to iterate on an implementation, or when think or hillclimb needs review rounds."
---

# Review, repair and recheck

Run these rounds in the calling thread. Use implementation mode by default.
For a brief from `think`, follow [readiness rounds](references/readiness.md).
For `hillclimb`, use its confirmed judging contract and
[phase rules](../hillclimb/references/rounds.md). Follow the chosen mode
through each step and return the result to the caller.

1. **Set scope and acceptance.** Read the request, rules, working tree and
   existing progress. Record observable criteria and the authorised endpoint.
   Ask only about material unresolved choices. In implementation mode, apply
   [issue status](../ship/references/issue-status.md) when starting an issue and
   read [delivery](references/delivery.md) before editing UI work.

2. **Prepare the round.** In a verified ignored or host-approved directory,
   record the run ID, goal, authority, scope, base and candidate, model settings,
   task handles, attempts and limits, findings, dispositions, checks and next
   action. For scored runs, add the fixed rubric, decimal places, target, current
   and best eligible candidate and score. For Hillclimb, add the phase high
   and the consecutive below-high count.
   Reuse supplied criteria and infer the target when possible. If a
   [native task list](../ship/references/native-task-list.md) is available, show
   the baseline, rounds, repairs and verification there.
   In implementation mode, prepare the candidate within existing authority
   before its first scored review.

3. **Evaluate the frozen candidate.** Follow [review](../review/SKILL.md) for
   dispatch, eligibility and required companions. Use one primary unless the
   mode supplies a roster. Recheck eligibility for every dispatch, including
   after a repair adds an author. Give each reviewer the absolute path to the
   [assigned-reviewer card](../review/references/assigned-reviewer.md). Start
   required evaluators together when independent. Freeze the brief or source,
   build, runtime and test data. While reviewers work, organise evidence,
   investigate failures read-only and follow host continuation rules.

   - Run covering checks. Report missing and pre-failing checks. Give evaluators
     the exact brief, artifact or full scoped diff, intent, exclusions, criteria,
     revision and evidence. For implementation, include the merge base, owned
     paths including untracked source, and affected callers. Ask for material
     defects, broken callers and unnecessary code, guards, tests or procedure.
   - For scored runs include the rubric and target. Require a score with a 3–5
     bullet rationale and any component scores. Use the lowest required score
     when several judges evaluate the same candidate.
   - Require screenshots of key visible states and findings when reviewing
     behaviour. Require a plain-text report with stable finding IDs, severity,
     location, evidence and impact. Verify the identity, scope and completeness
     of the report. Task completion alone does not establish approval.
   - For a failed scored evaluation, cancel any failed task still running and
     verify it stopped. Diagnose before one operation retry. Record missing
     scores as unavailable. If that retry fails, standard mode returns a
     failed invocation and Hillclimb returns blocked without a score failure.
     Apply readiness attempt rules to plan reviews.

4. **Record the outcome and check the gates.** Use the run record for every
   mode. For scored runs, follow the [score line graph](../review/references/score-chart.md)
   procedure. Update the cumulative JSON ledger and standalone HTML after
   each evaluation, including incomplete rounds, baseline and panel entry.
   Update them again after recovery and at final handback. Present the chart
   inline when supported and link the HTML file at handback.

   - Check acceptance and any panel transition before progress. In Hillclimb,
     start the confirmed panel on the first valid primary score at or above 90%
     of target. In implementation mode, honour an adopted
     [one-round exception](../review/references/single-round.md)
     for eligible repairs. Readiness uses its reasoned verdict.
   - In implementation mode, allow two scored review rounds per invocation by
     default, including the first evaluation. If the last round misses the
     target or required gates, return a failed invocation. The one recovery
     has at most two more rounds. Record rounds across both invocations.
   - Hillclimb has no default round cap. Only two consecutive complete scores
     strictly below the comparable phase high fail the invocation. A tie or
     improvement clears the streak. Follow the phase rules for baselines.
   - Preserve the best eligible candidate and required fixes. Honour explicit
     overall limits and cancellation across both invocations.

5. **Repair and recheck.** Verify findings. For each finding, apply the
   [disposition rules](../review/references/feedback-dispositions.md). Record
   impact and severity. Preserve finding IDs and append fixes, rejections and
   deferrals with evidence. Respect the calling mode's repair authority.
   Implement directly by default. For substantial independent repairs, use
   the [implementation-participant card](../review/references/implementation-participant.md)
   for any authorised delegate. Make small repairs directly.

   - When two consecutive code reviews expose different material defects from
     the same design assumption, record the assumption, both findings and an
     option that removes the assumption or why none is viable. Ask the next
     reviewer to test the assumption.
   - Take fresh captures of visible fixes. Use diff growth to check scope.
     Repeat step 3 for material changes, consequential open findings or gaps
     in acceptance evidence. Supply the full scope, changes since the last
     review, checks and prior findings. Broaden scope when an affected shared
     assumption or interface requires it. Record any changed base or scope and
     each superseding revision with its own evidence.

6. **Return the outcome to the caller.** Give the caller the current and best
   eligible candidates, the failed gate and the evidence. When scoring fails,
   the caller applies the [single recovery](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop).
   It diagnoses the cause, adjusts the approach and invokes these rounds
   once more under the same run ID and remaining limits. For a direct request,
   the current coordinator is the caller. Reconcile the recorded recovery
   state before dispatching on resume. If the retry fails, the caller explains
   what went wrong and why and asks the operator what to do. On cancellation,
   stop only owned work.

   Preserve unresolved findings and evidence gaps. In implementation mode,
   apply review's release rules and track confirmed non-blocking bugs with
   verified issue URLs or owned filing requests within authority. For an
   implementation endpoint, use [delivery](references/delivery.md). Hillclimb handles
   delivery using its final candidate rules. Readiness hands the brief,
   verdict and open decisions back to `think`.

## Outputs

Give the result, material findings and next action after each round. At
handback include revision, attempts, limits, models, checks, dispositions and
open gates. For scored runs report the target, best and current scores, relevant
counters and artifact links. Distinguish local validation, hosted checks, independent review,
merge and deployment. Report usage when available. Delegates return plain text
and score ledger paths to the coordinator for chart rendering.

Use authorised native orchestration. Keep scope, unrelated work and repository
protections intact. Publication, spending, merge and deployment require existing
authority.
