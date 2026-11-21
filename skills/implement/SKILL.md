---
name: implement
description: "Implement through T3 delegation when the user requests it or invokes implement. Return reviewed commits to the main thread for integration and delivery."
---

# Implement off the main thread

The main thread dispatches one working lead in an isolated T3 worktree. The lead
codes directly, delegates substantial independent parts when useful, and runs
[review-loop](../review-loop/SKILL.md) before returning reviewed commits. The
main thread owns acceptance, integration and shipping.

Read [project settings](../ship/references/project-settings.md) at start for
routing, review limits and ready-work capacity refill.
The main thread applies [plan-report](../plan-report/SKILL.md) when proposing, completing a task,
handing back and on request. Review/fix rounds get short chat
updates. Leads return timing and cost
observations; only the main thread presents the report. Track the main thread's
phases on the [native task list](../ship/references/native-task-list.md) when
the host exposes one; the lead's own list stays separate.

## Main-thread responsibilities

1. **Brief the lead.** Read the repository rules and working tree. Include the
   request and authority, scope and exclusions, settled product/design decisions,
   acceptance criteria, verification, repository identity, exact source HEAD and
   the main thread's model identity/lineage.
   Include the paths to this skill, review-loop and [review](../review/SKILL.md).
2. **Check the starting revision.** Isolated delegates start from the parent's
   committed HEAD. Identify required uncommitted prerequisites before dispatch. Commit
   them only with existing or newly obtained authority; otherwise report the
   blocker. Preserve unrelated work. Verify the prepared worktree's base before editing.
3. **Dispatch a working lead.** Follow the model-selection rules below. Discover
   exact T3 capabilities and use `delegate_task` with `isolation: 'worktree'`. Explicitly
   authorise the lead in its task to act as the implementation coordinator and
   dispatch scoped worker and reviewer children. Follow the returned `next`.
   If the required T3 route is unavailable, report it without substituting a
   shell launcher, native agent or top-level thread.
4. **Verify the handoff.** Check the worktree, exact HEAD, checks, review and
   remaining gates against the brief before accepting or integrating. When a handoff defers a bug, record its
   packet under [tracking](../review/references/deferred-bugs.md), dispatch it
   through raise-issue and retain ownership until its issue URL is verified.
   Code readiness and tracking completion are separate states. Continue
   independent work under the caller's authority.

## Model and effort selection

Optimise expected total cost across implementation, context, review, retries and
repairs while meeting the quality bar. Apply this policy to the lead and coding
workers. Every reviewer, recheck and additional opinion uses
[review's model selection](../review/references/model-selection.md) before dispatch.

- Discover provider/model identities, options and tool support; apply
  [T3 preflight](../agent-tuneup/references/t3-dispatch.md) before dispatch. Preserve
  explicit model choices subject to review's eligibility rules.
- Choose the provider before the model. After the lineage, permission and
  tool-support gates, take the provider with the highest limits-MCP pace score.
  An unscored provider cannot win; when nothing is scored, keep the static order.
  That may pick a different family than a fixed order would.
- Then match the model to the work inside that provider. A bounded mechanical
  edit with deterministic checks can take its smaller model. Ambiguous behavior,
  shared interfaces, security or state/concurrency work needs the stronger one,
  never a model the provider does not offer.
- Keep effort high. A smaller model never justifies lower effort. Where the host
  exposes no effort control, keep the provider default and record effort as not
  applicable; a variant whose name carries high reasoning is the alternative where
  the route offers one.
- Compare feasible choices using available cost and capability evidence, including
  likely extra attempts and coordination overhead. If reliable prices or task
  performance are unavailable, state the heuristic and uncertainty. Do not invent
  prices, claim a measured optimum or build a model registry.
- Reserve primary and companion review routes before assigning coding workers.
  The primary code reviewer must differ in lineage from every material code author.
  A lead or main thread that only orchestrates imposes no lineage restriction.
  Shipping can reuse review when it covers the accepted code and its authors.
  Reassess eligibility after repairs or model changes. Record each model, effort,
  role, selection reason and exposed usage; unknown usage stays unknown.

## Working lead

1. Work directly by default. Add a worker only for a substantial independent part
   whose expected benefit justifies startup, context and integration cost. Give
   each worker non-overlapping ownership, acceptance criteria, exact base, local
   commit authority and the absolute path of review's
   [implementation-participant card](../review/references/implementation-participant.md)
   to read. Workers and assigned reviewers do not delegate further.
2. Use T3-isolated worktrees for coding workers. Commit required lead checkpoints
   before dispatch so workers inherit the intended state. Integrate their scoped
   commits into the lead's worktree through the repository's permitted method,
   preserving other work. Evaluate the integrated result, not just each worker's
   report. Keep one writer per owned scope.
3. Return any material product, design or scope decision to the main thread with
   the affected work, recommendation and evidence. Continue only independent
   work; do not ask the user directly from a delegate or settle the decision by
   expanding scope. A pending decision makes the handoff incomplete.
4. Run review-loop as its coordinator, using review's model selection,
   evidence, severity and eligibility rules. Supply that
   selection context in every review brief. Reviewers work read-only against the
   lead's frozen current state; they do not need a separate coding worktree.
   Include all integrated changes and acceptance criteria. Preserve findings,
   dispositions, scores, best candidate and stagnation counter across repairs and resumes.

## Pause and resume

Before returning for a decision, checkpoint scoped work locally. Report task
handles, worktree, branch, HEAD, dirty paths, ledger, scores, counters and explicit
limits. Mark work incomplete; exclude secrets and unrelated changes.

The main thread returns the settled answer to the same lead child thread through
`t3_thread_send`, restating the coordinator role, dispatch authority, scores,
counters and explicit limits, and recording the returned task handle. Before resuming, the lead
verifies its existing worktree, branch, HEAD and ledger against the handoff.
Resume the existing lead for a settled decision; owner routing changes use the
[routing handoff](references/routing-changes.md). Never create a replacement checkout. If its
bound checkout cannot be recovered, report the blocker.

If nested reviewer dispatch is unavailable, the lead returns checkpointed work
marked review-pending. The main thread obtains review against that worktree's
exact committed HEAD using the same preserved review-loop progress and selection
policy and rechecks eligibility against the actual code authors. Give the reviewer the
lead worktree's absolute path and exact HEAD; require it to verify that HEAD
before reading the scoped source there. Do not review the main checkout as a
substitute. The main thread sends any required repairs back to the preserved
lead through the resume route above. Only a completed eligible review can
establish readiness.

## One automatic upgrade

Read [routing changes](references/routing-changes.md) before an upgrade,
owner-directed reassignment or moved-base conflict. It owns the single automatic
upgrade, checkpoint/cancellation handoff and preservation of the owning checkout.

## Ready work and return

Create scoped local commits and complete the applicable review policy against the returned
revision. Ready means the agreed criteria, required checks and applicable
runtime/UI evidence are met, with an eligible completed cross-lineage review
and finding dispositions allowed by review. Missing material evidence or
unresolved gates must be reported as incomplete.
Keep every handed-off candidate SHA reachable until the parent confirms it is
no longer needed. Submit repairs or an authorised rebase as a new candidate with its
own exact SHA and evidence. Identify which candidate the new one supersedes.
Apply review's deferred-bug tracking rule. Code-ready work may return with
non-blocking filing requests for the main thread to dispatch through
[raise-issue](../raise-issue/SKILL.md). Include the evidence, finding IDs, source
revision and posting authority, and mark tracking pending until URLs are verified.

Return a compact plain-text handoff containing:

- Repository, worktree, branch, exact base and reviewed HEAD, and commit IDs.
- Implemented scope, checks and evidence, findings and dispositions, remaining
  limitations and the next integration action.
- Models/lineages, selection reasons, upgrade use, scores, stagnation counter,
  explicit limits and exposed usage/cost.
- Code-author eligibility and scope for reuse, and any integration/base changes
  that would require affected behavior to be reviewed again.
- Task/thread manifest including descendants, failures and cancellations; worker
  worktree paths, evidence locations and cleanup status.
- Verified deferred-bug issue URLs or pending filing requests and their owner.

Stop owned workers, servers and monitoring when finished. Keep the lead worktree
and commits available for parent integration. Remove integrated worker worktrees
only through T3 tooling when supported; otherwise report them for T3 cleanup.
Preserve evidence needed by the handoff before removing task artifacts.
Keep source/evidence required for pending issue filing accessible to the main
thread and issue writer; a code-ready handoff does not complete that tracking.

Invoking implement authorises scoped local commits by the lead and its workers
in their T3 worktrees, and filing of confirmed deferred bugs arranged by the
main thread in the task's repository. Explicit no-post limits apply. It does not authorise committing
prerequisites in the parent checkout, parent integration, pushing, PR creation,
merging or deployment.
Explicit narrower limits still apply; if they prevent the requested commit
handoff, report that conflict.
