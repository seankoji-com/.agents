---
name: backlog-burn
description: Clear or burn down a repository's issue backlog. Use when asked to clear or burn down the backlog, unblock issues by asking the owner questions, dispatch implementation delegates for open issues, or drive the open issue count toward zero, including phrases like "clear the backlog", "burn down issues", "unblock the backlog" or "get open issues to zero".
---

# Burn the backlog to zero

A backlog is a queue of unresolved decisions as much as a queue of code. Treat
each open issue as code that is ready to build, a decision only the owner can
make, missing evidence, work that needs a live system, a duplicate, or work that
should close without a fix. The target is zero open issues, reached by fixing,
merging, verified duplication, or an explicit owner decision — never by quietly
closing work to improve a number.

## Authority and limits

- You have standing authority to implement, push scoped branches, open PRs,
  request cross-lineage review, and squash-merge when the repository's gates are
  green. Merging includes any automatic post-merge deployment the repository
  already defines; name its effect in the report. A merged fix closes its issue
  only when acceptance is code-only.
- A request to inventory or triage only stops after classification and a report.
  Dispatch and merge require clear, burn-down or implement wording.
- You may auto-close an issue only as a verified duplicate with an open canonical
  issue and a `duplicate` state reason. Every other closure — obsolete, wontfix,
  accepted risk — needs the owner's explicit confirmation in a question round.
- Manual deployments, live host, secret and destructive-data actions need
  per-action approval. Propose the exact command, host, blast radius, rollback
  and verification; execute only inside the host's approval path. A merge that
  already triggers an automatic deployment is covered by the standing merge
  above. If approval is unavailable, record the blocker and continue independent
  work.
- An explicit read-only, no-merge, no-close or release hold overrides these
  defaults. Required human approvals remain gates; never bypass protection,
  manufacture approval, or force-push a shared branch.

Read the repository's `AGENTS.md`, contribution guide and known-live-issues index
before classifying anything. For careynas.net, load [the careynas.net
profile](references/careynas-net.md) before classifying. Settled decisions are
evidence, not invitations to reopen them. Repository-specific confirmation rules still apply: for example, a
wiki page edit may need explicit confirmation; an owner-filed issue that
explicitly requests the change is that confirmation, otherwise ask.

## 1. Inventory

List every open issue with pagination, including labels, body, comments, linked
PRs, assignees and board state where the host exposes it. Read the repository's
triage and routing docs. Record the starting count and a ledger at an ignored path in the session
worktree, using [the ledger template](references/ledger.md); verify the path with
`git check-ignore`. The ledger is the resume point, not a second tracker.

## 2. Classify by what is missing

Use [the classification rubric](references/classification.md). The short form:

- **Dev-ready** — clear acceptance criteria or a named defect with a fix path,
  hermetic verification, no live access, no secret, no unresolved product choice,
  and not already in flight.
- **Needs decision** — the owner must choose scope, behaviour, priority,
  compatibility or risk.
- **Needs evidence** — a diagnosis or reproduction is missing; investigate before
  asking the owner.
- **Live-only** — needs a host, secret, deploy or destructive operation.
- **Duplicate** — same component, failure mode and recovery path as an open
  canonical. Protected issues are never folded.
- **Obsolete or wontfix** — the outcome no longer applies; propose closure with
  evidence.
- **In flight** — an open PR or active owner already covers it.

Do not classify an issue as dev-ready because it is old, short, or labelled
`complexity:low`. Ambiguity is a decision or an evidence gap.

## 3. Dispatch the dev-ready work

Use [implement](../implement/SKILL.md) for new work, [raise-pr](../raise-pr/SKILL.md)
to push and open the PR, and [babysitter](../babysitter/SKILL.md) for PR
maintenance. implement returns reviewed commits and does not push or open the PR
itself; the coordinator integrates them and raises the PR. Give each delegate the
repository, exact base, issue and acceptance criteria, authority, review model and
the skills it must read. One issue, one PR unless the repository explicitly allows
a combined change. If T3 delegation or an eligible review route is unavailable,
report the blocker; do not substitute a shell launcher or self-review. The
coordinator records every deferred-bug packet a lead returns and files it through
[raise-issue](../raise-issue/SKILL.md) before declaring the parent complete.
Material decisions a lead returns become question-round items; send the owner's
answer back to that lead's thread rather than starting a new delegate.

- Up to 10 top-level implementation delegates may run at once; each may own
  reviewer or worker children. Lower the cap when runner queue time grows. Watch
  the shared runner
  pool: serialise workflows known to contend, and treat a job cancelled by
  capacity as a rerun, not a code defect.
- Delegated children do not hold PR watches. The coordinator links each PR and
  owns the native watch, repair dispatch and merge until GitHub confirms it.
- If nested review dispatch is unavailable, obtain the cross-lineage review
  yourself against the exact committed HEAD. Self-review does not satisfy the
  gate.
- Merge only when the current head has green required checks, an eligible
  cross-lineage review, no unresolved threads, and no applicable hold. Use the
  repository's permitted merge method; squash when that is the rule.

## 4. Ask the owner, in batches

Use [the question playbook](references/questions.md). Ask only what the code,
issue body and comments cannot answer. Batch up to 10 independent decisions per
round through the host's question tool, one decision per question, your
recommended answer first with its tradeoff, the issue numbers and the evidence.
Defer questions that depend on an unanswered one. If the tool caps a batch
(Claude Code allows four), split the round across calls without waiting between
calls.

Typical rounds:

- product and scope choices that make an issue dev-ready;
- confirmation to close obsolete or wontfix issues;
- exact live-write approvals, one action at a time;
- permission to split an epic into child issues;
- an explicit hold when the owner does not want the work.

Stop asking about an issue only when the owner declares a hold for it. Every
blocker the agent cannot resolve — missing live access, an unavailable approval
path, an outside party — becomes a question. Record it as a blocker, not a hold.
A blocked-external issue stays open and is reported until the owner decides.

An open question round is a pause, not completion: end the turn with the questions
and watches active, and without a question tool ask the same batch as plain text.
If every remaining issue waits on an answer, stop and report "awaiting owner";
silence is not approval.

## 5. Apply the answers

Update the ledger first, then reclassify. Dispatch newly unblocked work, close
confirmed issues, execute approved live actions through the supported approval
path, and file follow-up issues for confirmed deferred defects before declaring
the parent complete. Read back every closure and issue URL.

## 6. Close correctly

- A merged fix closes its issue through the PR only when acceptance is code-only.
  When live verification or a protected issue is involved, use `Refs #N` instead
  of a closing keyword; close after the acceptance is recorded. Verify only the
  intended issues closed.
- A duplicate closes against an open canonical with a link and `duplicate` state
  reason. Never fold a protected issue — security, hardware, resilience, or
  priority P0/P1 — without explicit owner review.
- An obsolete or wontfix closure needs the owner's confirmation and a recorded
  reason.
- Never close an issue merely because it is old, blocked, or inconvenient.

## 7. Loop to zero

Re-inventory after each batch. Repeat dispatch, merge, question and closure rounds
until zero issues remain open, or until the owner has explicitly held every
remaining issue or every remaining issue awaits an unanswered question. Report
"not zero" honestly when a hold or an open question remains; name the gate and
owner rather than implying completion.

## 8. Report

Before and after counts at a stated time; issues opened during the run; merged PRs
with commit SHAs; closed issues and why;
follow-ups filed; still-open issues by class, owner and next trigger; the ledger
path; models and effort used; and verification separated into local checks,
current-head CI, merge, deployment and live acceptance. A code merge is not a
deployment or a live acceptance result.
