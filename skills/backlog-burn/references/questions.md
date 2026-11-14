# Question playbook

The point of asking is to remove the decision that blocks the next action. A
question that does not change what happens next is noise.

## Batch protocol

- Ask up to 10 independent decisions per round through the host's question tool.
  If it caps the batch (Claude Code allows four), split the round across calls
  without waiting between calls.
- One decision per question. Do not combine "choose the behaviour and approve the
  deploy" into one answer.
- Recommendation first, with the tradeoff and the evidence. Include issue numbers
  and the consequence of each option.
- Defer questions that depend on an unanswered one.
- Do not ask what the code, issue body, comments or repository docs already
  answer.
- If the request was inventory or triage only, stop after classification. Do not
  close issues, dispatch or merge.
- Question-only requests also propose actions. Autonomous closure, dispatch and
  merge require clear, burn-down or implement intent within the requested scope.
- After the answers, restate the decisions in the ledger before acting.
- Dispatch newly ready issues before returning to unrelated triage or reporting.
  A released hold or approved fix without a task receipt is still actionable.
- Before a question that blocks or ends the turn, fill available slots with ready
  independent work and record dispatch receipts. If dispatch itself requires a
  yield, preserve the unsent question and submit it on the next permitted turn.
- If the owner requests evidence before choosing, investigate it, then explicitly
  submit the remaining decision. A recommendation ending "say the word" is not
  a pending question unless the question was actually asked.

Recommended question shape:

> **#123 — which compatibility window should the fix keep?**
> Recommended: keep the current two releases because the migration is already
> deployed. Cost: the old path stays until the next major.
> Options: two releases (recommended), drop immediately, defer.

## What to ask

### A decision that makes an issue dev-ready

Name the missing choice, the two or three viable answers, the evidence, and what
each answer unblocks. Offer "defer" when the owner may not want the work now.

### Protected closure or material risk decision

Ordinary evidence-supported obsolete, already-done and low-value closures need
no question during burn-down. Apply the classification rubric and report the
verified closure. Ask when a protected issue, stricter repository rule or material
risk decision requires owner review.

> **#456 — retire this protected issue about an already-retired component?**
> Evidence: current source and #400 confirm retirement; the protected label
> requires your review. Recommended: close as not-planned with this evidence.
> Alternative: keep open if a related live risk remains.

For these cases, wait for the answer before closure. Never present a proposed
closure as already done.

### A live-write approval

Ask one action at a time. Include:

- exact host and command or API call;
- what will change and the blast radius;
- the rollback or restoration path;
- the verification after the action;
- the window and whether a restart is involved.

A merge that already triggers an automatic deployment is covered by the standing
merge authority, not by this question. If the host's approval path is unavailable,
stop at the proposal and record the blocker.

### A scope split

> **#789 is three independent outcomes. Split into #789a/b/c and implement a first?**
> Recommended: split, because each has a separate acceptance test and owner.

### A pull request closure or dependency migration

Ask before closing a draft or a PR whose changes exist nowhere else, giving the
evidence and the recommended disposition. For a dependency bump that needs a
real migration, offer: migrate now, or close with an ignore rule for that version.

> **#46 — the hono 4.13 → 5.0 bump breaks routing across three modules.**
> Recommended: close with an ignore rule for 5.x until the router migration is
> planned. Cost: the service stays on 4.x. Alternative: migrate in this PR.

### An explicit hold

If the owner does not want the work, record an owner hold with the reason, owner
and next review trigger. A hold is not a closure unless the owner also confirms
the closure.

### A blocker the agent cannot resolve

Missing live access, an unavailable approval path, an outside party or an
unanswered external dependency is a blocker, not a hold. Ask the owner how to
proceed. A `blocked-external` issue stays open and is reported until the owner
decides. Only the owner's answer can end the loop.

## Stop condition

Stop asking once the issue closes under the rubric or the owner declares a hold. Every
blocker the agent cannot resolve becomes a question first. Continue independent
work; do not turn the round into a status request.

An unanswered question pauses only its dependent work. Continue discovery,
dispatch and delivery for independent issues where the host permits. Before a
voluntary yield, apply backlog-burn's queue audit. If a tool requires yielding,
preserve the discovery cursor, ready queue and task/watch receipts for the next
wake. Follow that instruction rather than claiming background progress.

Report "awaiting owner" only when all remaining issues and PRs are explicitly
held, in flight elsewhere or await actually submitted questions, with at least
one unanswered. Keep questions
and continuation active; without a question tool, ask the same batch explicitly
as plain text. Unexamined work, approved-but-undispatched work, investigations,
live steps without exact approval questions and owned PRs with actionable gates
cannot justify this pause. An owned PR whose only remaining action depends on a
submitted unanswered question may pause with its watch and ownership retained. Work with a verified live owner elsewhere needs no ownership question:
record its owner link and next trigger without claiming to own or monitor it.
Silence is not approval, and a status report is not completion.

## Anti-patterns

- Asking one question per turn when ten independent decisions are ready.
- Asking the owner to choose something the code already settles.
- Asking for confirmation of an ordinary closure already authorized by the rubric.
- Presenting a recommendation without the tradeoff.
- Treating silence as approval.
- Calling an agent blocker an owner hold.
- Asking for a blanket "yes to all live changes" instead of per-action approval.
- Stopping a whole backlog because one issue needs an answer or one PR is watched.
