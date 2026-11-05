# Respond to review feedback

Use this for PR review threads, review bodies, bot comments and findings from
review-loop evaluators. The coordinator chooses each disposition. Reviewers report
findings, and implementers repair the findings the coordinator selects.

Validate each item before answering it. Reproduce the problem or read the code,
then compare the request with the PR's stated goal, the brief and decisions the
owner has already made. Choose one disposition below. Each disposition is a
complete answer: a thread does not need a code change to be finished.

## Fix

Fix valid, in-scope findings. SEV1 findings always need a fix or the user's
explicit release exception. Fix SEV2 findings by default unless the parent's
release evaluation in [review](../SKILL.md) accepts a stated workaround. Reply
with the repairing commit and resolve the thread once the fix is verified on the
current head.

## Decline

You may say no to an item that is:

- **Invalid.** It does not reproduce, misreads the code, is already handled, or
  contradicts the brief or an owner decision. Cite the evidence.
- **Scope creep.** It may be reasonable on its own but falls outside the PR's
  stated goal, such as a new feature, an unrelated refactor, a broader redesign
  or a preference with no effect on behavior users rely on.

Reply once with the reason and evidence, then resolve the thread. Be direct and
courteous. Do not apologise for declining, and do not promise follow-up work that
nothing tracks. Feature ideas and preferences need no issue; the reply can invite
the reviewer to open one. A confirmed bug is never declined as scope creep. If it
falls outside the PR, defer it to an issue as described below.

## Defer to an issue

You may agree with a valid SEV3 finding and leave it out of this PR. Prefer
deferral when the fix would widen the diff, need fresh review or delay an
otherwise-ready merge. A small fix to lines this PR already changes can be made
in place instead. Choose the option that keeps the PR smaller and easier to review.

File the issue through [deferred-bug tracking](deferred-bugs.md), reply on the
thread with the verified issue link and resolve it. Link the issue with an
ordinary reference, not a closing keyword. Deferral does not lower severity.
Deferring a SEV2 finding needs the parent's release evaluation and a stated
workaround. A SEV1 finding cannot be deferred without the user's explicit approval.

## Limits

- Disagreement never bypasses a merge gate. A required human approval or a
  changes-requested review still blocks merge. Do not dismiss reviews.
- Reassess when a human reviewer reopens or answers a declined or deferred thread
  with new evidence. If they repeat the disagreement without new evidence, leave
  the thread unresolved and bring the decision to the owner. Never resolve a
  thread again after a human reopened it.
- Follow a repository rule that only reviewers resolve their own threads. Reply
  with the disposition and leave resolution to them.
- Explicit no-post or read-only limits win. Draft the replies and dispositions and
  report them instead of posting.
- Apply [github-writing](../../github-writing/SKILL.md) to every reply.
- Record each item's disposition, reason, evidence and issue URL in the finding
  ledger and the PR handoff.
