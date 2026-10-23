# ralph

ralph splits building from judging. One model implements your goal in a fresh T3 task;
a model from a different lineage evaluates the result in another fresh task.
Blocking issues send the work back to a new implementation task with the same model
and worktree. Safe later improvements become repository issues. When a full review
reports the goal met with no undisposed feedback, ralph opens a PR.

## Try it

```text
$t3-ralph fix the parser and add regression coverage
```

ralph first asks you to choose the implementer and the evaluator from T3's live model
catalog. Then it runs attempts until the evaluator is satisfied or the limit (20 by
default) runs out. Other forms:

```text
$t3-ralph --max-attempts 8 implement the export endpoint
$t3-ralph status /path/to/ralph-state.json
$t3-ralph resume /path/to/ralph-state.json
$t3-ralph cancel /path/to/ralph-state.json
```

Choosing `t3-ralph` from the `/` menu inserts the `$t3-ralph` mention. ralph needs
catalog v0.5.0 or later. If `t3-plugins list` doesn't include it, run
`brew update && brew upgrade t3-plugins` (or
[install from source](../getting-started.md#from-source)), then run
`t3-plugins setup ralph` and restart the agent session.

## What you get

- for a code change that passes: a normal PR from the run's branch;
- otherwise: the remaining feedback and the checkpoint path, never a success claim;
- a checkpoint file outside the repository with every task ID, the chosen models, the
  worktree and each round's result, so `status` and `resume` work across sessions.

## Choose the pair

Each new run asks for both models from the live T3 catalog, including custom models
and their settings, and keeps that pair for the whole run. One provider can host
several model lineages, so picking two providers doesn't prove independence. Unknown
lineage labels need your confirmation; if the pair can't be shown to be independent,
the run doesn't start.

The installed skill points at the versioned ralph package, which carries its
checkpoint helper and the shared T3 instructions. Runtime modes are resolved per
provider within the parent thread's limits and shown next to the model choices.
OpenCode needs Full Access, because other modes can stall on T3 permission requests.
If you choose OpenCode from a narrower parent mode, ralph stops before dispatch and
asks you to switch the parent to Full Access.

## Feedback and stopping

The default limit is 20 implementation attempts, including the first. Use
`--max-attempts N` to change it. The evaluator reports whether the observable goal
was achieved, every feedback item, and the evidence it inspected. Success requires
an achieved goal and no undisposed feedback in a full review. Blocker/major findings
and a failure verdict require another attempt. Minor/info findings first enter
triage: safe deferrals need a verified issue in the target repository, a reason,
impact, owner and next action. Filing them uses no implementation attempt and
preserves the original review. A failed required check or unmet requirement cannot
be deferred to obtain success. An unavailable issue service leaves explicit unfiled
work and a filing gap in the handoff.

After each returned review, the coordinator gives you at most three sentences
about its findings and next action. The final handoff summarizes deferred fixes
with issue links and captures a build/test lesson from observed review churn.

Children receive only the supplied brief. ralph carries the original goal,
constraints, acceptance criteria, every earlier verdict and all feedback into each
new task, plus the latest implementation and evaluation reports, failure details
and recovery reasons. Earlier reports stay in the checkpoint, so the brief doesn't
grow by a full report every round. Code remains in
the same worktree. It does not discard previous attempts or swap models after
criticism.

The first evaluation is a full review of the goal and the whole change. After a
rejection, the next evaluation is a narrower re-review that continues the
rejecting evaluator's conversation, so it doesn't re-read the code from scratch. It
checks each open feedback item and the files changed since the rejecting review. That
re-review can send the work back, but it can't finish the run. When it finds nothing,
a full fresh review of the same tree decides, and that extra review doesn't use up
an attempt. Long runs spend most of their rounds on cheap re-reviews; a run that
passes on its second evaluation pays for one extra narrow review.

An evaluator that remembers its earlier verdict tends to stick to it, so only these
re-reviews continue a conversation: they can send work back but never approve it.
The final full review and every implementation attempt start fresh. T3's own
guidance asks for each review round to be a new task; ralph departs from it for
re-reviews only.

A saved checkpoint keeps request IDs, task IDs, chosen targets, the worktree, and
round results across completion notifications and parent turns. T3 runs the tasks;
the helper only stores observations and prepares the next request. A lost dispatch
response stays uncertain until reconciled with the same request ID. No replacement
child starts while an earlier task or its descendants are still running.

Missing evidence, malformed evaluation, unavailable models and permission failures
stay visible. Changes during evaluation invalidate its verdict and require a fresh
evaluation. Exhausting the attempt limit reports the remaining feedback and the
checkpoint path. It never becomes a success claim.

Malformed verdicts and terminal provider failures record a recoverable blocker,
the raw result, and the saved task ID. After addressing the cause, `resume` records
a recovery reason and creates a fresh task with the same pair and worktree.
Implementation retries still count against the limit. Temporary pending child runs
clear after their terminal statuses are observed, restoring the earlier stage.
Missing model identity needs an exact saved T3 delegation receipt or authoritative
status; ralph never guesses aliases or accepts an unverified model as success.

## PR delivery

Successful runs that produce code changes normally finish by opening a normal PR.
ralph may edit, test, commit owned paths, push the task branch, and open that PR.
Your narrower instructions take precedence. It follows repository checks and
pre-PR review requirements, uses the intended base, and verifies the PR head.
It does not merge, deploy, release, or send messages without separate authority.
Runs with no code changes return the evaluated result without an empty PR.

The evaluator reviews committed output before publication. A subsequent edit or
commit requires fresh evaluation. Unrelated dirty work stays outside the commit.
The checkpoint reports paths changed since the run started. The parent still
checks ownership and whether those paths are code changes before opening a PR.
If publication fails, ralph reports the evaluated result and the separate PR
delivery blocker. Current-head CI, merge, deployment and live acceptance remain
separate outcomes.

Cancellation stops only this run's tracked children. ralph waits for T3 to confirm
they and their pending turns have stopped; requesting cancellation is not proof.
Keep the checkpoint until you are finished with the run. It can contain private
goal text and feedback, so store it outside the repository and do not commit it.
Checkpoint format 3 records each evaluation's review scope. ralph upgrades a
format 2 checkpoint the next time it saves one, and earlier ralph versions refuse
format 3. The original experimental format is separate: resume those checkpoints
using their original installed snapshot rather than rewriting them.

## Compatibility

ralph is experimental. Behavioural tests cover checkpoints, feedback decisions,
revision invalidation, cancellation and the installed helpers, without live model
calls. They don't show live provider compatibility or a completed model-driven run.

Jobs created through the shared CLI carry `policy.identity: observed`. Required reviewer executions, their subjects, and slots marked `independent_of_author` need verified host identity at acceptance. Authoring jobs enforce author-lineage checks from `policy.author_independence`, even if a slot omits its flag. Legacy jobs without the identity marker retain target-only acceptance semantics. A first author record cannot identify earlier authors of an unrecorded document. Direct cold-read stages cannot fall back to the coordinator.

## Resume and written strategies

New runs freeze work/review choices. Explicit resume offers retain-or-stop for the
pinned pair and options; it cannot rotate targets after feedback. Automatic wakes
reuse the active choices. Legacy checkpoints remain readable and need explicit
retain-or-stop admission before new work.

Ordinary iterations add no planning artifact or evaluator. An actually written
strategy receives planning review before dependent work. Its fallback policy cannot
replace Ralph's different-lineage evaluator, blocking-feedback repair rule or full
final evaluation.

See [planning review](../plan-review.md) for default triggers, model choices,
receipt freshness, fallback labels and requester reporting.
