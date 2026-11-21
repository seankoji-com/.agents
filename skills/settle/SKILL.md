---
name: settle
description: "Close out a finished top-level thread and settle it in T3. Use at a completed handback or for /settle."
---

# Settle a finished thread

End a thread once its work is finished. Save what later work needs, remove what
this session created, hand off optional work, release what is already closed,
then settle the thread in T3.

## When this applies

- A top-level thread reaches the endpoint of its workflow and nothing remains in
  place.
- The user asks to settle, wrap up or close out the thread.

A delegated child does not settle. It finishes with its report to its
coordinator, and the top-level thread decides what remains.

Settle is the last step after a workflow's own endpoint, never a substitute for
it. It cannot close unfinished work, release a gate, or move an obligation to
another thread.

## Check first

1. Identify the calling workflow and confirm it reached its endpoint. If the
   caller is `ship`, `babysitter`, `backlog-burn` or `hillclimb`, its own rules
   define that endpoint.
2. List anything still in place: an open watched PR, a backlog-burn ledger row,
   a pending owner question, a deferred bug without a verified issue URL, a
   running delegate or background task. Wait for running work. Do not raise a
   mid-run task in a new thread.
3. Stop without settling when an obligation remains. Report the item, its owner,
   its next action and what would release it. An open watched PR keeps the
   thread open.
4. Record what the caller still needs: PR links and heads, issue URLs, ledger
   rows, captured evidence. Cleanup happens after that handback, not before.

## Save durable memory

Apply [reremember](../reremember/SKILL.md) before saving anything. Save only what passes its
durability test: a decision later work depends on, a verified correction, or an
initiative update. Never save a transcript, per-run status, scores, cost or
secrets.

When `ship` already recorded the run's decisions in its retrospective, reuse that
result instead of writing the same decision twice. Confirm the backend's
acknowledgement. If a write fails or the backend is unavailable, report the
unsaved item with the evidence and exact text a retry needs, then continue.
Never claim memory was written without an acknowledgement.

## Raise optional follow-ups

A free follow-up is work this run noticed but nobody owns: an optional
improvement, a non-blocking cleanup, a related idea the user did not ask for. It
carries no obligations, evidence gates or authority from this thread.

Ask about every free follow-up in one batched question set, one question each:
raise it in a new thread, or report it. Do not ask about work the caller's own
rules still own.

For an approved item, create the thread with a brief that stands alone. Confirm
creation from an identifiable thread or link. A `starting` status confirms
creation, not that work began. If creation is unconfirmed, retry once; if it is
still unconfirmed, keep this thread open and ask the user to withdraw or retry
rather than losing the approved work.

Report a declined item as unresolved and continue settling.

## Clean up

Remove only what this session owns:

- The session scratch directory and task artifact directories you verified are
  ignored.
- Temporary preview files and downloads the task created.
- Another disposable worktree this session created, only when it is clean and its
  HEAD commits are reachable from a remote.
- Task-owned processes, stopped by the PID captured at launch. Never match by
  name, port guess or path.

Before removing anything, check for unpushed commits, uncommitted intended work
and evidence the caller or user still needs. Keep what a configured settle
script reads.

Never delete the thread's own T3-managed worktree. T3's settle hook runs in it,
and host cleanup owns its removal. Never prune worktrees, and never touch
unrelated files, agents, servers or another thread's checkout.

## Release watches

Unwatch only a PR that is merged or closed and still registered to this thread.
If the call fails, keep the thread open and report it.

The calling workflow releases its own obligations first, under its own rules:
`babysitter` on a confirmed merge or closure, explicit user stop or one-shot
endpoint; `backlog-burn` when its ledger row closes; `ship` after verified deferred
bug filing. Settle never unwatches a live PR and never transfers a watch.

## Settle the thread

1. Confirm no delegate, background task or queued turn is still pending.
2. Call `t3_thread_organize` with action `settle`. Without that tool, report the
   gap and do not claim the thread is settled.
3. Report what was saved, cleaned, raised, released and settled. Settlement
   applies at turn end, and its acknowledgement means the request was accepted,
   not that the settle hook finished.

Do not archive the thread.

## Callers

`ship`, `babysitter`, `backlog-burn` and `hillclimb` name this skill as their last
step. It runs once, at the outermost handback: when `ship` calls `babysitter`, or
`backlog-burn` calls `ship`, the outer workflow settles, not each nested stage.
`implement`, `think`, `raise-issue` and `raise-pr` end mid-work and do not call
it.

## Report

Give the user a short list: what was saved, what was removed, which follow-ups
were raised or declined, which watches were released, and whether the thread was
settled. Name any obligation that kept it open, with its owner and next action.
