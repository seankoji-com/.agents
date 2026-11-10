---
name: implement
description: Use when the user invokes implement or requests implementation through T3 delegates, returning reviewed commits for the main thread to integrate and ship.
---

# Implement off the main thread

The main thread dispatches one working lead in an isolated T3 worktree. The lead
codes directly, delegates substantial independent parts when useful, and runs
[review-loop](../review-loop/SKILL.md) before returning reviewed commits. The
main thread owns acceptance, integration and shipping.

## Main-thread responsibilities

1. Read the repository rules and working tree. Give the lead a compact brief:
   request and authority, scope and exclusions, settled product/design decisions,
   acceptance criteria, verification, repository identity, exact source HEAD and
   the main thread's model identity/lineage.
   Include the paths to this skill, review-loop and [review](../review/SKILL.md).
   Delegates receive their task, not the parent conversation.
2. Isolated delegates start from the parent's committed HEAD, without its dirty
   changes. Identify required uncommitted prerequisites before dispatch. Commit
   them only with existing or newly obtained authority; otherwise report the
   blocker. Do not silently omit them, copy unrelated work or invent a handoff
   route. Verify the prepared worktree's actual base before editing.
3. Select the working lead using the model-selection rules below. Discover exact
   T3 capabilities and use `delegate_task` with `isolation: 'worktree'`. Explicitly
   authorise the lead in its task to act as the implementation coordinator and
   dispatch scoped worker and reviewer children. Follow the returned `next`.
   If the required T3 route is unavailable, report it without substituting a
   shell launcher, native agent or top-level thread.
4. On return, verify the worktree, exact HEAD, checks, review and remaining gates
   against the brief before acceptance or integration. Record every deferred-bug
   packet under [tracking](../review/references/deferred-bugs.md), dispatch it
   through raise-issue and retain ownership until its issue URL is verified.
   Code readiness and tracking completion are separate states. Continue
   independent work under the caller's authority.

## Model and effort selection

Optimise expected total cost across implementation, context, review, retries and
repairs while meeting the quality bar. Apply this policy to the lead, workers
and every review round or additional opinion inside implement. Other workflows
retain review's default preferences.

- Discover provider/model identities, options and tool support; apply
  [T3 preflight](../agent-tuneup/references/t3-dispatch.md) before dispatch. Preserve
  explicit model choices subject to review's eligibility rules.
- Match capability to the work. A bounded mechanical edit with deterministic
  checks can use a smaller model and lower supported effort. Ambiguous behavior,
  shared interfaces, security or state/concurrency work needs stronger reasoning
  from the start. A low price does not establish suitability.
- Compare feasible choices using available cost and capability evidence, including
  likely extra attempts and coordination overhead. If reliable prices or task
  performance are unavailable, state the heuristic and uncertainty. Do not invent
  prices, claim a measured optimum or build a model registry.
- Reserve an eligible reviewer route before assigning coding workers. The reviewer
  must differ in lineage from the lead/coordinator and every material model author
  for primary review; additional judges may use review's higher-reasoning exception.
  When cost is comparable, prefer eligibility against the main thread too, so
  shipping can reuse the review. Report when that later eligibility is absent.
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
4. Run review-loop as its coordinator, using this skill's model-selection policy
   and review's shared evidence, severity and eligibility rules. Supply that
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
Do not launch a new isolated lead from the main thread's original base as a
resume route. If the bound checkout cannot be recovered, report the blocker;
do not set up a replacement checkout in the shell or a child's prompt.

If nested reviewer dispatch is unavailable, the lead returns checkpointed work
marked review-pending. The main thread obtains review against that worktree's
exact committed HEAD using the same preserved review-loop progress and selection
policy and rechecks eligibility against its own lineage. Give the reviewer the
lead worktree's absolute path and exact HEAD; require it to verify that HEAD
before reading the scoped source there. Do not review the main checkout as a
substitute. The main thread sends any required repairs back to the preserved
lead through the resume route above. Only a completed eligible review can
establish readiness.

## One automatic upgrade

Allow one model or effort upgrade for the whole task, shared by the lead,
workers and reviewers. It requires evidence of a capability failure or diagnosed
lack of progress, with a reason the stronger choice should help. An expected
failing regression test alone is not an escalation reason. Start high-risk work
at a suitable level rather than relying on a cheap failed attempt.

Record the consumed upgrade before dispatching it. Preserve the worktree state,
author identities, findings, review-loop scores and stagnation counter; changing models
does not reset any budget. Stop replaced tasks through T3 before handing their
ownership to another writer. Cancelling a lead also stops its descendants.
For stronger implementation, the lead may use the upgrade on a worker launched
from its current committed checkpoint and remain the coordinator. Do not pretend
the running lead's model changed. If the coordinator itself must be replaced
and T3 cannot preserve its checkout through a supported route, return a blocker
with the checkpoint handoff rather than starting again from the parent's base.

If the upgraded attempt is still stuck, or safe escalation is unsupported,
return the blocker and preserved work. Do not launch a second upgrade or label
budget exhaustion as success.

## Ready work and return

Create scoped local commits and complete review-loop against the returned
revision. Ready means the agreed criteria, required checks and applicable
runtime/UI evidence are met, with an eligible completed cross-lineage review
and finding dispositions allowed by review. Missing material evidence or
unresolved gates must be reported as incomplete.
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
- Review eligibility for main-thread reuse and any integration/base changes
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
