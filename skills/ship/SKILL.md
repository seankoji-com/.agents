---
name: ship
description: "Deliver and verify a change when the user explicitly asks to ship or backlog-burn calls for delivery. Show progress and finish with a retrospective."
---

# Deliver a change

Settle decisions that could change the work, implement, verify the result and
obtain independent review. Carry it through the authorised delivery endpoint,
then report the evidence and review how the run went.

## What a ship request authorises

An explicit "ship" request authorises completing the change through a merged
PR while the user is away. You may test, commit, push, rebase the PR's own branch
with `--force-with-lease` and merge through repository protections. Honour any
explicit narrower limits.

It also authorises the coordinator to file confirmed deferred bugs in the task's
repository under [review](../review/SKILL.md)'s tracking rules. Include the
verified issue URLs in the PR and final handoff; explicit no-post limits apply.
The retrospective may file workflow amendments only in a skill repository the
operator named or configured. This owner configured `seankoji-com/.agents`.
Verify ownership through account and repository evidence. Confirm posting
authority from the operator's instructions. A clone's origin or collaborator
access does not establish either.
It may also record verified, durable decisions in the memory of the repository
the run worked in, under [reremember](../reremember/SKILL.md). Memory is a
record, not another proposal route: it never replaces a commit, PR or issue,
and it never edits an instruction file.

Apply [GitHub writing](../github-writing/SKILL.md) to authored GitHub prose,
including authorised release notes and delegated drafts.

Task-related browser, app, simulator, device and visual testing need no additional
user permission under this request, even if a project ordinarily asks first.
Follow the host's tool and approval rules and the repository's test methods.
Production changes, data deletion, unrelated changes, closing PRs and force-pushing
other branches remain outside this grant without separate authority.

## Make the work visible

Read [project settings](references/project-settings.md) at start for routing,
review limits and ready-work capacity refill. Ship owns the
[up-front blocker batch](references/start-and-blockers.md) before dispatch;
read it for manual follow-ups and other runs' processes.

Apply [plan-report](../plan-report/SKILL.md) at proposal, task completion, final
handback and on request. Review/fix rounds get short chat updates. When completed
work changes something visible, show a captioned screenshot through the host's
image tool alongside the completion report. The main thread feeds final
estimate/actual, model, effort, segment and review-round calibration into the
retrospective, preserving unknown cost coverage.

When backlog-burn invokes ship, use its existing authority and narrower limits;
this invocation adds no permissions from the explicit ship grant above. Keep one
parent plan and execution manifest across its delivery batches. Apply proof and
merge gates to each change, then perform one consolidated retrospective at final
handback. Question-round pauses leave it pending. Missing authority for warranted
proposals leaves it incomplete with drafts and an owner question. Backlog-burn retains
owner decisions, issue closure and the queue's stop condition.
Backlog discovery and dispatch continue across PR deliveries. Apply its queue
audit before voluntarily yielding; one PR watch does not complete the backlog.
In backlog-burn, issue fixes use implement leads; the parent does not implement
them inline. The optional implement choice below applies to standalone ship.

Use T3's parent plan/todo panel before implementation under the
[native task list](references/native-task-list.md) rules. Its items cover the
task's decisions/design, implementation, checks/review, delivery, deferred-bug
tracking and final retrospective as applicable. Without an exposed tool, report
the gap and post a status list at each phase change; never claim a panel update
from text alone.
Keep the recovery record current at phase changes and use
[continuation recovery](../babysitter/references/continuation.md) after lost context.

Before T3 dispatch apply the shared
[dispatch preflight](../agent-tuneup/references/t3-dispatch.md).
Record the execution boundary, manifest and evidence for the
[retrospective](references/retrospective.md) as work happens.

## Choose supporting skills

Choose skills that help the current task, reusing settled decisions and existing
evidence. These are options, not a required sequence:

- [think](../think/SKILL.md) for unresolved product decisions that could
  materially change implementation.
- [choose-design](../choose-design/SKILL.md) when product decisions are settled
  but a material UI or interaction choice remains.
- [implement](../implement/SKILL.md) when moving coding into an isolated T3
  delegate is worthwhile, particularly for substantial implementation work.

## Finish the endpoint

1. For UI changes, apply [raise-pr](../raise-pr/SKILL.md) before editing to plan
   the after captures and take practical mobile and desktop baseline screenshots.
   At delivery start, apply its [preflight](../raise-pr/references/preflight.md)
   to identify effective rules and validation gates early.
   Finish the smallest change that meets the request. Preserve unrelated work.
   Follow the repository's branch and delivery policy.
2. Observe direct proof: reproduce and verify the fix, run covering checks, and
   inspect UI or runtime behavior when affected. Add regression protection when
   it catches a meaningful failure. Mocked tests alone do not prove visible behavior.
   Apply [proof quality](../review/references/proof-quality.md) to bundle adoption,
   HTTP access evidence and unavailable local tools before deferring proof.
3. Use [review-loop](../review-loop/SKILL.md) for independent review and repair.
   That skill owns reviewer selection, budgets, findings and rechecks.
   Reuse eligible completed review under review's rules.
4. Create or update the PR against the intended current base using
   [raise-pr](../raise-pr/SKILL.md) for templates, screenshots, agent attribution
   and independent review. Follow host creation and linking requirements.
5. Use [babysitter](../babysitter/SKILL.md) as the sole owner of the PR's
   delivery lifecycle: its pre-watch audit, repair and review rules, merge
   eligibility, merge action, readback and watch rules apply unchanged. Supply
   ship's own acceptance requirements — observed proof, retrospective and
   deferred-bug tracking — to that owner rather than running a parallel merge
   path. Merge with the repository's permitted method once the gate below passes;
   verify the resulting merge.
6. After delivery and required deferred-bug tracking, perform the final
   [workflow retrospective](references/retrospective.md) using the recorded
   evidence and targeted log reads. Pitch supported, broadly applicable skill
   amendments through [raise-issue](../raise-issue/SKILL.md) in the authorised
   skill repository, `seankoji-com/.agents` for this owner. Save durable
   decisions the run settled under the retrospective's memory rules.
   Apply the retrospective's coverage rules. Record verified proposal URLs or
   evidence that no amendment is warranted. Coverage gaps and blocked filing
   leave the retrospective incomplete. This stage ends with proposals and the
   memory result. Finish the run with [settle](../settle/SKILL.md) as the last
   step, once this outermost handback has nothing left.

Where repository policy requires direct publication instead of PRs, use its
prescribed delivery path through the same proof and review gates. Do not create
a PR contrary to that policy or broaden this grant to production deployment.
The pushed commit is the delivery revision. Report publication, propagation to
each configured target and hosted CI on that commit as separate stages. A push
whose propagation failed is published with propagation incomplete; keep the
workflow open and give the retry command.

## Merge gate

Babysitter's merge-eligibility rules are this gate: current head and base,
required checks, human approvals, thread dispositions, merge method, protections
and readback all follow it, including its rule that unreadable or absent
current-head check runs do not count as passing. Ship additionally requires:

- Proof covering the current behavior diff, from observed behavior rather than
  mocks alone.
- raise-pr's independent review gate passes, including an adopted
  [single-round exception](../review/references/single-round.md) when applicable;
  material findings are addressed.
- Every confirmed bug left unfixed has a verified issue URL or an owned filing
  request under review's tracking rules. Pending filing for bugs already judged
  non-blocking does not block merge; keep the workflow open until required issue
  URLs are verified.
- No outstanding human review still requests changes, even when branch
  protection does not require that review.

Honor merge queues and intervening base changes; never bypass them or dismiss a
required human gate because a model is confident.

## Waiting and blockers

Use babysitter's native watcher and its rules for when monitoring ends. Never
add a second watcher or polling loop.

Use [raise-issue](../raise-issue/SKILL.md) for asynchronous issue preparation and
filing. Keep ownership of pending requests after merge and preserve their evidence.
Follow T3's continuation instructions rather than waiting or polling. Report a
merged result with tracking pending as ongoing work, not completed shipping.

Continue authorized work until the endpoint or a concrete blocker. Ask through
the host's question tool only for a material ambiguity, missing authority or
proof/gate you cannot obtain yourself. Include the link, blocker, recommendation
and alternatives. Silence is not approval. If no answer or tool is available,
leave dependent work incomplete and report the specific next action.

## Report

Return the delivery link and revision, [cited proof](../review/references/proof-quality.md#cite-verification-in-the-handoff)
for material verification claims, review status, decisions and any unmet
endpoint. Delegates return complete plain-text reports with descendant
task/thread IDs and operational evidence to their coordinator.
The parent includes task-list status, history coverage, the memory result and
amendment issue URLs or the no-change rationale. In T3 Code, only the main-thread coordinator uses
`html_preview` then `html_render` for a substantive report; use readable text when
native HTML is unavailable or the result is brief. Do not claim deployment or
live acceptance from a merge.
