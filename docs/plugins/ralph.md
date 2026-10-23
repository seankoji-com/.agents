# ralph

Choose Open PR, Tagged Version or Verified in Prod upfront unless supplied. Recommend finite exact work/reviewer backup chains once; unchanged resume does not ask retain-or-stop. Reconcile the original task before approved fallback and recheck independence against every actual author. The full different-lineage evaluation remains mandatory. `readyForPublication` reports source readiness; `complete` and `endpointComplete` require actual evidence for the selected target. Legacy checkpoints keep their original pinned package and authority; new targets require an admitted restart preserving findings and remaining limits.

ralph splits building from judging. One model implements your goal in a fresh T3 task;
a model from a different lineage evaluates the result in another fresh task.
Blocking issues send the work back to a new implementation task in the same
worktree under the approved work chain. Safe later improvements become repository
issues. When a full review reports the goal met with no undisposed feedback,
source evaluation is complete and the selected delivery gates follow.

## Try it

```text
$t3-ralph fix the parser and add regression coverage
```

ralph inspects context, then recommends exact work/reviewer chains and options from
T3's live catalog in one scoped agreement unless already supplied. Then it runs attempts until the evaluator is satisfied or the limit (20 by
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

- for a code change that passes: the agreed Open PR, Tagged Version or Verified in Prod endpoint;
- otherwise: the remaining feedback and the checkpoint path, never a success claim;
- a checkpoint file outside the repository with every task ID, the chosen models, the
  worktree and each round's result, so `status` and `resume` work across sessions.

## Choose the models

Each new run records task-suitable exact work/reviewer primary and finite backup
chains, their supported options and authority from the live T3 catalog, including
custom models. Questions come in short rounds: implementer,
evaluator, then each missing option or backup decision. Explicit answers skip their questions. A lineage
or sharing conflict gets its own short question only when it needs a decision.
The picker shows a short relevant list; the final summary records roles, exact
models, options, scope and authority before dispatch. All required evaluators must
be independent of every actual author. One provider can host
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
preserves the original review. Triage also requires the coordinator's actual GitHub
API issue snapshot, with matching issue identity and a marker bound to the exact
finding and reviewed revision. The receipt is stored and its integrity checked
again before publication; a URL and evidence sentence alone leave a filing gap.
The coordinator obtains and verifies the API response; the helper remains offline.
A failed required check or unmet requirement cannot
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
rejection, a fresh tracked task checks open feedback and changed files. This delta
review can request repair but cannot finish the run; a full fresh review decides
acceptance. Every new agreement-bound review round uses `delegate_task`. Legacy
pinned packages retain their historical delta-conversation contract.

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

## Selected delivery

The scoped agreement selects Open PR, Tagged Version or Verified in Prod. It
records action authority for the necessary displayed path. Open PR requires a
real linked intended-base/current-head PR with required local checks, independent
review and current-head CI passed. Later endpoints follow the target repository
release/deployment procedures and require actual revision/version observations.
A queued workflow, local tag, image alone or healthy older runtime cannot pass.
No-change work reports its evaluated outcome without inventing a PR or tag.

Source evaluation and endpoint completion remain separate. Subsequent source edits
require fresh evaluation. Publication failure retains the checkpoint and exact
blocker without downgrading the selected endpoint.

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

Unchanged resume and notification wakes reuse the saved agreement, choices and
remaining budgets without another chooser. Approved outage replacements require
original-task reconciliation and exact options. Healthy adverse reviews require
repair. Legacy checkpoints stay with their original pinned package; new authority
needs a separately admitted restart preserving findings and remaining limits.

Ordinary iterations add no planning artifact or evaluator. An actually written
strategy receives planning review before dependent work. Its fallback policy cannot
replace Ralph's different-lineage evaluator, blocking-feedback repair rule or full
final evaluation.

See [planning review](../plan-review.md) for default triggers, model choices,
receipt freshness, fallback labels and requester reporting.
