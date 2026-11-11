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
  dispatch or merge without clear, burn-down or implement wording.
- After the answers, restate the decisions in the ledger before acting.

Recommended question shape:

> **#123 — which compatibility window should the fix keep?**
> Recommended: keep the current two releases because the migration is already
> deployed. Cost: the old path stays until the next major.
> Options: two releases (recommended), drop immediately, defer.

## What to ask

### A decision that makes an issue dev-ready

Name the missing choice, the two or three viable answers, the evidence, and what
each answer unblocks. Offer "defer" when the owner may not want the work now.

### Confirmation to close

> **#456 — close as wontfix?**
> Evidence: the component was retired in #400; the issue's acceptance path no
> longer exists. Recommended: close as not planned, link this evidence, and keep
> the tracker's history. Alternative: keep open as a documentation task.

Never present a closure as already done. The owner's answer is the authority.

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

Stop asking about an issue only when the owner declares a hold for it. Every
blocker the agent cannot resolve becomes a question first. Continue independent
work; do not turn the round into a status request.

An open question round is a pause in the run, not completion. End the turn with
the questions and watches active. Without a question tool, ask the same batch as
plain text. If every remaining issue waits on an answer, report "awaiting owner";
silence is not approval.

## Anti-patterns

- Asking one question per turn when ten independent decisions are ready.
- Asking the owner to choose something the code already settles.
- Presenting a recommendation without the tradeoff.
- Treating silence as approval.
- Calling an agent blocker an owner hold.
- Asking for a blanket "yes to all live changes" instead of per-action approval.
