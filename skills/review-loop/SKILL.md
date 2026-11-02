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
   Preserve user-set implementation limits. Retry only with new evidence or a
   changed hypothesis; stop repeating an approach that makes no progress and
   diagnose the cause or report the blocker. Allow at most three evaluation
   rounds for a bounded change, including the first. For larger goals, allocate
   review budgets to milestones before dispatch; do not reset them by relabeling
   work. Extend a review phase to five rounds only while an evidenced blocker or
   major finding remains in
   security, permissions, authentication, data loss or state/concurrency, or when
   the user requests it. Record the reason and count failed attempts.
2. Apply [review](../review/SKILL.md) for cross-lineage eligibility, reviewer
   selection and dispatch. Every loop participant reads and applies that skill
   for its assigned role: the coordinator obtains review and owns dispositions,
   implementers repair selected findings, and evaluators return evidence without
   further delegation. Follow review's rule for named reviewers and conflicts.
3. For UI work likely to end in a PR, apply [raise-pr](../raise-pr/SKILL.md) early
   to capture practical mobile and desktop before screenshots.
   Implement directly unless substantial independent work warrants delegation;
   make small review repairs directly when authorized. Keep concise notes in a
   verified ignored task directory: goal, authority, scope, milestones, base/head,
   exact models and
   options, remaining budgets, task handles, stable finding IDs, dispositions,
   checks and next action. Use one cross-lineage evaluator per round. Add another
   opinion only for a concrete unresolved risk or disagreement, within the same
   phase's round budget. For that additional opinion, apply review's selection
   policy to eligible unused reviewer lineages unless explicitly named; report
   unavailable choices. Inside [implement](../implement/SKILL.md), that policy
   remains cost-aware across all rounds and additional opinions. Routine rechecks
   can use the original reviewer's lineage
   while it remains eligible under review, including after repairs by new authors.
   Do not require scores or unanimous satisfaction.
   Follow review's dispatch rules for every round. All loop briefs include
   review's path and require the participant to read and apply it in its assigned
   role, including implementation participants and assigned reviewers.
4. Run covering checks before review and report missing or pre-failing checks.
   Establish the merge-base and owned paths, including untracked source, for the
   review phase. Round one uses a fresh read-only evaluator on the full scoped
   diff, surrounding callers and every acceptance criterion. Supply intent,
   exclusions, version, checks and evaluation criteria. Ask for consequential
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
   stopped before retrying within the remaining budget.
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
7. Accept when evidence covers the current behavior, required criteria are met
   and remaining findings have explicit dispositions consistent with
   review's release treatment. An approved exception does not mean the bug is fixed. Incomplete
   visual review remains an evidence gap in the release recommendation.
   Reviewer verdicts inform that decision; agreement alone does not prove it.
   The parent decides deferrals and retains severity and supporting evidence.
   Apply review's deferred-bug tracking rule: hand off verified issue URLs or
   owned asynchronous filing requests for already non-blocking bugs. Filing
   remains within authority and tracking stays incomplete until URLs are verified.
   Stop circular
   debate or repeated attempts without progress. Escalate only material decisions
   the user must make; budget exhaustion is not approval. Continue independent
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
   At a concrete blocker or exhausted budget, report what remains incomplete.

On resume, reconcile existing tasks and preserve decisions, findings and remaining
budgets. On cancellation, stop only owned work and confirm it stopped.

## Outputs

Keep updates brief: result, material findings and next action. Final handoff includes
revision, implementation attempts and evaluation rounds used/limits, exact work and
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
