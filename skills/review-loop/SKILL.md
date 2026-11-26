---
name: review-loop
description: "Implement, review and repair in rounds when asked to iterate with independent review or when the user invokes review-loop. Work toward the agreed score and acceptance criteria."
---

# Implement, review, repair

Agree on what success looks like, then alternate repairs and independent
evaluation. Stop when the score and required checks pass, or report the best
result if two consecutive rounds fail to improve it. A failed run gets one
recovery: diagnose, fix, re-invoke once, then report. Ordinary engineering work
does not automatically need this loop.

## Workflow

1. **Set the scope and score.** Read the request, repository rules, working tree
   and existing progress. Identify observable acceptance criteria and the
   authorised endpoint, which may be a verified local change. Ask only about
   material unresolved choices. Apply the
   [issue status](../ship/references/issue-status.md) start transition when this
   run starts an issue.

   - Fix the rubric, decimal places and target before editing. Reuse supplied criteria
     and ask about the target only if you cannot infer it.
   - Score a baseline and start the non-improvement counter at zero. Count each
     completed evaluation once. A higher score becomes the best and resets the
     counter. A tie or lower score increments it and keeps the earlier best.
   - Check the target and required gates first. If they pass, finish. Otherwise
     stop incomplete after two consecutive rounds without a higher score. A
     stop-incomplete run gets the single recovery in step 7.
   - Preserve required bug fixes when choosing the repair base or final candidate,
     even if an older candidate scored higher. Keep scores, counters and prior
     progress across repairs, reviewers and resumes. Record any metric change.
   - If multiple judges score a round, use the lowest score on the same frozen
     candidate. Honour explicit round, deadline and spending limits.
     No default ceiling.

2. **Choose reviewers and assign roles.**

   - The coordinator reads [review](../review/SKILL.md) for eligibility, named
     models, conflicts and dispatch. Before deciding findings, read the
     [feedback dispositions](../review/references/feedback-dispositions.md).
   - Before reviewing, evaluators read the [assigned-reviewer card](../review/references/assigned-reviewer.md)
     and return evidence without delegating.
   - Before repairing, implementers read the
     [implementation-participant card](../review/references/implementation-participant.md)
     and repair selected findings.

3. **Prepare the run.**

   - For UI work likely to end in a PR, use [raise-pr](../raise-pr/SKILL.md)
     before editing to capture practical mobile and desktop baselines.
   - Implement directly by default. Delegate substantial independent work when
     it warrants a worker. Make small authorised review repairs directly.
   - In a verified ignored directory, record goal, authority, scope, milestones,
     base and head, models and options, scores, best candidate, non-improvement
     counter, limits, task handles, finding IDs, dispositions, checks and next
     action. If the host exposes a [native task list](../ship/references/native-task-list.md),
     show the baseline, rounds, repairs and final verification there. Keep scores
     and counters in the notes.
   - Use one primary evaluator and review's required companions. Add opinions only
     for an unresolved material risk or disagreement. Apply review's model
     selection to every round, including inside implement. Code-author lineage
     restricts code review only. Reuse the reviewer's lineage for a routine recheck
     if it still qualifies after any repairs. Report unavailable choices.
   - Follow review's dispatch rules. Give every participant the absolute path
     to their role card and require them to read it. Run independent preparation
     and checks in parallel, and start selected evaluators together.
   - Freeze source, build, runtime and test data during evaluation. While it runs,
     organise evidence, prepare the handoff, investigate failures read-only and
     record repair options. Isolate checks that could disturb the candidate, or
     defer them. Follow host continuation rules while results are pending.

4. **Evaluate the frozen candidate.**

   - Run covering checks and report missing or pre-failing ones. Record the
     merge base and owned paths, including untracked source.
   - For round one, give a fresh read-only evaluator the full scoped diff,
     callers and acceptance criteria. Include intent, exclusions, revision,
     check results, rubric and target. Ask for a score with a 3–5 bullet
     rationale (plus any component dimension scores), material bugs, broken
     callers and unnecessary code, guards, tests or procedure.
   - Require screenshots of key visible states and findings. Require a
     plain-text report to the parent with stable IDs, SEV1–SEV3 severity,
     location, evidence and impact. Delegates may not use `html_render`.
     Task completion alone does not establish approval.
   - Keep scoped files frozen. If evaluation fails or returns no report, cancel
     any active failed task and verify it has stopped. Diagnose the failure before one
     retry. Missing evaluations have no score and leave the counter unchanged.
     If that retry still fails, apply the single recovery in step 7, or stop
     incomplete when it is unavailable.

5. **Verify findings and repair within scope.**

   - Confirm each finding's location, evidence, severity and impact. The parent
     decides repairs, deferrals and issue filing under review's release rules.
   - If consecutive completed code reviews find different verified material
     defects from the same design assumption, reconsider it before the next
     repair. Record the assumption, both finding IDs and an option that removes
     the assumption while meeting the criteria, or explain why none is viable.
   - Address selected findings and unmet criteria. Delete or narrow code when
     that fixes the cause. Decline unsupported requests with evidence.
   - Preserve original findings and IDs. Append each fix, rejection or deferral
     with its evidence. Take fresh captures of visible fixes. Use diff growth to
     check scope, without setting a line-count target.

6. **Recheck material changes.**

   - Re-review changed behaviour, unresolved consequential findings and gaps
     in acceptance evidence. Editorial corrections and declined nits need no
     new round. Never transfer approval across unreviewed behaviour or shop
     for reviewers.
   - If the project adopted `review_rounds: 1`, read and apply the
     [one-round exception](../review/references/single-round.md) before verifying
     eligible repairs. Otherwise dispatch a fresh read-only evaluator.
   - Supply the full scoped diff, changes since the last review, checks and findings.
     If a design assumption recurred, name it and ask whether the repair still
     relies on it. Broaden review when shared assumptions, interfaces or earlier
     behaviour change.
   - Keep base and scope explicit; record any change and reassess evidence.
     Preserve handed-off candidates and name each superseding SHA
     with the checks run on it.

7. **Accept the evidence or explain the stop.**

   - Confirm current evidence covers the criteria, required checks and score.
     Apply the adopted one-round exception only where it replaces the score gate.
     Report incomplete visual coverage in the release recommendation.
   - Apply review's release rules to each remaining finding. The parent owns
     deferrals and retains severity and evidence. Agreement or a release exception
     alone does not prove the work is fixed.
   - Track confirmed non-blocking bugs left unfixed. Use verified issue URLs or
     owned asynchronous filing requests within authority. Tracking finishes when
     the URLs are verified.
   - If the loop stops incomplete, apply the [single recovery](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop):
     record the attempt, diagnose from the retained evidence, fix the cause and
     re-invoke once from the latest candidate under the original run ID and
     spent slot. Record any revised criteria or roster and flag a pass under
     either with the original target. A second
     failure stops the loop and reports both attempts. Use [progress diagnosis](../review/references/budget-exhaustion.md)
     for remaining limits and extensions. Escalate only user decisions; continue
     independent authorised work.

8. **Verify the agreed endpoint.**

   A source fix does not complete a requested merge or deployment.

   - For PR creation or updates use [raise-pr](../raise-pr/SKILL.md) for
     evidence, templates, screenshots, attribution and independent review.
     New PRs need completed independent review. If proof needs a PR before
     review, state the dependency and obtain an explicit waiver from the user.
   - Bundle local repairs before pushing when practical. An authorised branch
     push or existing PR update can happen earlier for hosted checks or previews.
     Refresh checks and reviews for the current head before merging.
   - For a deployment, verify the revision and behaviour on each target; report
     the endpoint and any incomplete gate. When production is verified, apply
     [issue status](../ship/references/issue-status.md) done.

On an ordinary resume, reconcile tasks and preserve decisions, findings, scores,
best candidate, counters and limits. Reconcile the recovery record. A
`fix-failed` record is spent. A `dispatching` or `started` recovery without a
usable handle is spent and is never redispatched. A `committed` record with no
later outcome may resume the fix once. Use the
continuation procedure after the automatic recovery for an operator-approved
new baseline. On cancellation, stop only owned work and confirm it stopped.

## Outputs

Keep updates brief: result, material findings and next action. After each
completed scoring round, recovery and final handback, update the JSON score
ledger and follow [score line graph](../review/references/score-chart.md) to
render it inline (`html_preview` then `html_render` in T3, text/link fallback
elsewhere). Final handoff includes revision, attempts, rounds, target/best/current
scores, counter, limits, models, checks, dispositions, deferrals and endpoint
evidence. Report usage only when exposed. Separate local validation, hosted
checks, independent review, merge and deployment. Delegates return plain-text
reports and the score ledger path; only the main thread renders charts and
substantive findings reports.

## Boundaries

Use authorised native orchestration, not another scheduler or top-level substitute. Follow host model, sharing and permission rules. Preserve unrelated
work and repository protections. Reuse existing authority; this skill grants no
extra permission to publish, message others, spend, merge or deploy.
