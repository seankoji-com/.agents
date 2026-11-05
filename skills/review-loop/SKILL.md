---
name: review-loop
description: "Use when the user requests an iterative implementation, independent review and repair loop, or invokes review-loop to carry a goal to an agreed endpoint."
---

# Implement, review, repair

## Triggers

Infer the goal and endpoint from the request; ordinary engineering work does not
automatically need this loop.

## Workflow

1. Inspect the request, repository rules, working tree and existing progress.
   Establish scope, observable acceptance criteria and the authorized endpoint,
   which may be a verified local change. Ask only about material unresolved choices.
   Preserve explicit user limits. Fix the scoring rubric, precision and target
   before implementation; reuse supplied criteria and ask only if the target
   cannot be inferred. Seed the best score with a baseline evaluation. Hill-climb
   from the best candidate: only a strict increase replaces the best and resets
   the consecutive non-improvement counter. A tie or regression increments it.
   Stop successfully when the target and required acceptance gates are met, or
   stop incomplete after two consecutive rounds without improving the best score.
   No round cap, deadline or spend ceiling is required. Honour explicit user
   limits. Preserve scores and counters across repairs, reviewers and resumes.
   Test target and required gates before stagnation. Baseline seeds the best with
   counter zero; later completed evaluations count once each. Retain the earlier
   best on ties. Preserve required bug fixes when selecting the repair base or
   final candidate; a higher historical score cannot justify dropping them.
   When additional judges score a round, use the lowest score on the same frozen
   candidate. Record any metric change explicitly; retain prior progress history.
2. Apply [review](../review/SKILL.md) for cross-lineage eligibility, reviewer
   selection and dispatch. Every loop participant reads and applies that skill
   for its assigned role: the coordinator obtains review and owns
   [feedback dispositions](../review/references/feedback-dispositions.md),
   implementers repair selected findings, and evaluators return evidence without
   further delegation. Follow review's rule for named reviewers and conflicts.
3. For UI work likely to end in a PR, apply [raise-pr](../raise-pr/SKILL.md) early
   to capture practical mobile and desktop before screenshots.
   Implement directly unless substantial independent work warrants delegation;
   make small review repairs directly when authorized. Keep concise notes in a
   verified ignored task directory: goal, authority, scope, milestones, base/head,
   exact models and
   options, scores, best candidate, non-improvement counter, explicit limits,
   task handles, stable finding IDs, dispositions,
   checks and next action. Use one cross-lineage evaluator per round. Add another
   opinion only for a concrete unresolved risk or disagreement. Additional judges
   may share a lineage under review's higher-reasoning exception. Apply review's
   selection policy; report unavailable choices. Inside [implement](../implement/SKILL.md), that policy
   remains cost-aware across all rounds and additional opinions. Routine rechecks
   can use the original reviewer's lineage
   while it remains eligible under review, including after repairs by new authors.
   Keep the rubric and target fixed; agreement alone is not acceptance.
   Follow review's dispatch rules for every round. All loop briefs include
   review's path and require the participant to read and apply it in its assigned
   role, including implementation participants and assigned reviewers.
   Schedule independent preparation and covering checks concurrently where their
   resources do not interfere. Dispatch multiple selected evaluators together
   once their prerequisites are met. While review runs, organize evidence,
   prepare the handoff and investigate existing failures read-only; draft repair
   options as notes. Keep source, build, runtime and test data frozen for all
   evaluators. Use isolation for conflicting checks or defer them. Wait only
   when remaining work depends on results, following host continuation rules.
4. Run covering checks before review and report missing or pre-failing checks.
   Establish the merge-base and owned paths, including untracked source, for the
   review phase. Round one uses a fresh read-only evaluator on the full scoped
   diff, surrounding callers and every acceptance criterion. Supply intent,
   exclusions, version, checks, rubric and target; require a score with evidence.
   Ask for consequential
   bugs, broken callers and unnecessary code, tests, guards or procedure.
   Apply [review](../review/SKILL.md) and include it in the
   review brief. Require key-state screenshots for visible behavior and every
   visible finding; the reviewer reports bugs and SEV1–SEV3 severity to the parent,
   which owns repair, deferral and issue-filing decisions within its authority.
   Require a complete plain-text final report with stable finding IDs, severity,
   file:line, evidence and impact. Delegates must not use `html_render`; findings
   must reach the coordinator, not only a child-thread presentation.
   Do not edit scoped files while evaluation runs. A timeout, error, missing reply
   or task completion status is not approval. Cancel failed work and verify it
   stopped before one diagnosed retry. Missing evaluations have no score and do
   not advance the score counter; stop incomplete if recovery fails.
5. Verify each finding using severity, location, reproduction or supporting evidence,
   and impact, and apply review's release treatment for its SEV level.
   Repair findings selected by the
   parent and unmet criteria within scope. Capture fresh evidence for visible
   fixes and preserve original findings. Prefer deleting or narrowing when it fixes the
   cause. Challenge incorrect or unnecessary requests with evidence rather than
   appeasing the reviewer. Preserve original finding IDs and append fixed,
   rejected or deferred evidence. Track diff growth as a prompt to examine scope,
   not a line-count target.
6. Later rounds use fresh read-only evaluation tasks focused on changed behavior
   and unresolved findings. Supply the full scoped diff, the delta since the last
   review, checks and finding ledger. Broaden review when a change affects shared
   assumptions, interfaces or previously reviewed behavior. Keep the phase's base
   and scope explicit; if either changes, record why and reassess affected evidence.
   Re-review material behavior changes, unresolved consequential findings or gaps
   in acceptance coverage. Editorial corrections and declined nits need no new
   round. Never transfer approval across unreviewed behavior or shop for reviewers.
7. Accept when the score meets target, evidence covers current behavior, criteria are met
   and remaining findings have explicit dispositions consistent with
   review's release treatment. An approved exception does not mean the bug is fixed. Incomplete
   visual review remains an evidence gap in the release recommendation.
   Reviewer verdicts inform that decision; agreement alone does not prove it.
   The parent decides deferrals and retains severity and supporting evidence.
   Apply review's deferred-bug tracking rule: hand off verified issue URLs or
   owned asynchronous filing requests for already non-blocking bugs. Filing
   remains within authority and tracking stays incomplete until URLs are verified.
   On stagnation, explicit limits or extension requests, apply
   [progress diagnosis](../review/references/budget-exhaustion.md)
   and report the unmet target and remaining gates. Stagnation is not approval.
   Escalate only material decisions the user must make. Continue independent
   authorized work while dependent work is blocked.
8. Complete the agreed endpoint with its required evidence. For PR creation or
   updates, apply [raise-pr](../raise-pr/SKILL.md) for templates, screenshots,
   agent attribution and independent review. A source fix does not
   complete a requested merge or deployment. Bundle local review repairs before
   pushing when practical; an authorized branch push or existing-PR update may
   happen earlier when hosted checks or previews are needed for proof. New PR
   creation still requires completed independent review under raise-pr. If proof
   requires creating a PR before review, report that dependency and seek an
   explicit user waiver rather than infer one. Refresh current-head
   checks/reviews before merging.
   Verify the deployed revision and actual behavior on each requested target.
   At a blocker, stagnation stop or explicit limit, report what remains incomplete.

On resume, reconcile existing tasks and preserve decisions, findings and remaining
scores, best candidate, counters and explicit limits. On cancellation, stop only
owned work and confirm it stopped.

## Outputs

Keep updates brief: result, material findings and next action. Final handoff includes
revision, implementation attempts, rounds used, target/best/current scores,
non-improvement counter, explicit limits, exact work and
review models, checks, finding dispositions, deferrals and endpoint evidence or
remaining blockers. Report usage only when exposed. Separate local validation,
hosted checks, independent review, merge and deployment. Delegated coordinators
return complete plain-text reports; only the main thread presents them. In T3
Code, the main-thread coordinator uses `html_preview` then `html_render` for
user-facing substantive findings and disposition reports;
use readable text when native HTML is unavailable or the result is brief.

## Boundaries

Use authorized native orchestration, without another scheduler or top-level thread
substitute. Follow host model, sharing and permission rules. Preserve unrelated
work and repository protections. Reuse existing authority; this skill grants no
extra permission to publish, message others, spend, merge or deploy.
