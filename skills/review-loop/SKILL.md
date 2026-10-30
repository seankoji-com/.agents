---
name: review-loop
description: "Use when the user requests an iterative implementation, independent review and repair loop, or invokes review-loop to carry a goal to an agreed endpoint."
---

# Implement, review, repair

## Triggers

Use for requested implementation and review loops. Infer the goal and endpoint
from the request; ordinary engineering work does not automatically need this loop.

## Workflow

1. Inspect the request, repository rules, working tree and existing progress.
   Establish scope, observable acceptance criteria and the authorized endpoint,
   which may be a verified local change. Ask only about material unresolved choices.
   Preserve user-set implementation limits. Retry only with new evidence or a
   changed hypothesis; stop repeating an approach that makes no progress and
   diagnose the cause or report the blocker. Allow at most three evaluation
   rounds for a bounded change, including the first. For larger goals, allocate
   review budgets to milestones before dispatch; do not reset them by relabeling
   work. Extend a review phase
   to five rounds only while an evidenced blocker or major finding remains in
   security, permissions, authentication, data loss or state/concurrency, or when
   the user requests it. Record the reason and count failed attempts.
2. Discover supported native tasks and exact model identities. Preserve explicit
   model and option choices. Otherwise select the first available evaluator in
   this order whose verified lineage differs from the work being reviewed:
   **Sol, Opus, Wonder Full, Argon, Grok 4.7**. These are preferences, not hardcoded
   provider IDs; resolve them from current capabilities. A different version,
   effort setting or provider alias of the same lineage does not qualify.
   Account for every model that materially authored the reviewed change. If work
   lineage is unknown or no eligible evaluator is available, report the blocker.
   Never silently use a different preference order or same-lineage review.
3. Implement directly unless substantial independent work warrants delegation;
   make small review repairs directly when authorized. Keep concise notes in a verified ignored
   task directory: goal, authority, scope, milestones, base/head, exact models and
   options, remaining budgets, task handles, stable finding IDs, dispositions,
   checks and next action. Use one cross-lineage evaluator per round. Add another
   opinion only for a concrete unresolved risk or disagreement, within the same
   phase's round budget. Do not require scores or unanimous satisfaction.
   In T3 Code, discover models with `orchestrator_capabilities` and use a fresh
   `delegate_task` for each review or recheck. Record its `taskId` and follow the
   returned `next`; do not poll or replace it with a top-level thread. Follow
   host orchestration elsewhere. Children do not start further agents.
4. Run covering checks before review and report missing or pre-failing checks.
   Establish the merge-base and owned paths, including untracked source, for the
   review phase. Round one uses a fresh read-only evaluator on the full scoped
   diff, surrounding callers and every acceptance criterion. Supply intent,
   exclusions, version, checks and evaluation criteria. Ask for consequential
   bugs, broken callers and unnecessary code, tests, guards or procedure.
   Do not edit scoped files while evaluation runs. A timeout, error, missing reply
   or task completion status is not approval. Cancel failed work and verify it
   stopped before retrying within the remaining budget.
5. Verify each finding using severity, location, reproduction or supporting evidence,
   and impact. Rare failures can still be serious; judge consequence and evidence,
   not frequency alone. Repair blocker/major findings and unmet criteria within
   scope. Prefer deleting or narrowing over adding machinery when it fixes the
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
7. Accept when evidence covers the current behavior, consequential findings and
   required criteria are addressed, and no supported substantive concern remains.
   Reviewer verdicts inform that decision; agreement alone does not prove it. Defer
   minor/info findings unless they pose an actual handoff, merge or launch risk.
   Keep reasons in the handoff; file issues only when authorized. Stop circular
   debate or repeated attempts without progress. Escalate only material decisions
   the user must make; budget exhaustion is not approval. Continue independent
   authorized work while dependent work is blocked.
8. Complete the agreed endpoint with its required evidence. A source fix does not
   complete a requested merge or deployment. Bundle local review repairs before
   pushing when practical; push earlier when authorized hosted checks or previews
   are needed for proof. Refresh current-head checks/reviews before merging.
   Verify the deployed revision and actual behavior on each requested target.
   At a concrete blocker or exhausted budget, report what remains incomplete.

On resume, reconcile existing tasks and preserve decisions, findings and remaining
budgets. On cancellation, stop only owned work and confirm it stopped.

## Outputs

Keep updates brief: result, material findings and next action. Final handoff includes
revision, implementation attempts and evaluation rounds used/limits, exact work and
review models, checks, finding dispositions, deferrals and endpoint evidence or
remaining blockers. Report usage only when exposed. Separate local validation,
hosted checks, independent review, merge and deployment. In T3 Code, use
`html_preview` then `html_render` for substantive findings and disposition reports;
use readable text when native HTML is unavailable or the result is brief.

## Boundaries

Use authorized native orchestration, without another scheduler or top-level thread
substitute. Follow host model, sharing and permission rules. Preserve unrelated
work and repository protections. Reuse existing authority; this skill grants no
extra permission to publish, message others, spend, merge or deploy.
