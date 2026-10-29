---
name: ralph
description: "Use when the user requests an iterative implementation, independent review and repair loop, or invokes Ralph to carry a goal to an agreed endpoint."
---

# Implement, evaluate, repair

## Triggers

Use for requested implementation/evaluation loops. Infer the goal and endpoint
from the request; ordinary engineering work does not automatically need this loop.

## Workflow

1. Inspect the request, repository rules, working tree and existing progress.
   Establish scope, observable acceptance criteria and the authorized endpoint,
   which may be a verified local change. Ask only about material unresolved choices.
   Set a finite round limit (default 20, including the first round).
2. Discover supported native tasks and work/evaluator models. Preserve user-selected
   models/options and require verified different work/evaluator lineages. If the
   required evaluation is unavailable, report the blocker; never silently substitute
   another model or same-lineage review. Keep concise notes in a verified ignored
   task directory: goal, authority, worktree/base/head, models/options, remaining
   budget, task handles, findings/dispositions, checks and next action.
3. Each round uses a fresh implementation task, then a fresh read-only evaluation
   task against the current base, resulting revision and every acceptance criterion.
   Follow host orchestration and continuation rules. Children do not recursively
   delegate unless explicitly permitted. Inspect actual artifacts and check results;
   a task's completion status is not acceptance.
4. Verify findings using severity, location, reproduction or supporting evidence,
   and impact. Repair blocker/major findings and unmet criteria within scope and
   budget. Preserve original findings and append fixed/rejected/deferred evidence.
   Changes need fresh evaluation; do not transfer approval or shop for reviewers.
   Stop early when repeated attempts make no progress.
5. Defer minor/info findings unless they pose an actual handoff, merge or launch
   risk. Keep deferrals and their rationale in the handoff; file issues only when
   authorized. Do not expand the goal to implement deferred work.
6. Complete the agreed endpoint with its required evidence. A source fix does not
   complete a requested merge or deployment. Refresh current-head checks/reviews
   before merging; for deployment, verify the deployed revision and actual behavior
   on each target. At a concrete blocker or exhausted budget, report what remains
   incomplete rather than declaring success.

On resume, reconcile existing tasks and preserve decisions, findings and remaining
budget. On cancellation, stop only owned work and confirm it stopped.

## Outputs

Keep round updates brief: result, material findings and next action. Final handoff
includes revision, checks, finding dispositions, deferrals, rounds used/limit and
endpoint evidence or remaining blockers. Separate local validation, hosted checks,
independent review, merge and deployment.

## Boundaries

Use authorized native orchestration, without another scheduler or top-level thread
substitute. Follow the host's model, sharing and permission rules. Preserve unrelated
work and repository protections. Reuse existing authority; this skill grants no
extra permission to publish, message others, spend, merge or deploy.
