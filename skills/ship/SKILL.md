---
name: ship
description: Use when the user explicitly asks to ship a change through delivery, visible progress tracking and a final workflow retrospective.
---

# Ship

An explicit "ship" request authorizes completing the requested change through
a merged PR while the user is away. It includes task-related tests, committing,
pushing, merging through repository protections and rebasing the PR's own branch
with `--force-with-lease`. Explicit narrower limits still apply.

It also authorises the coordinator to file confirmed deferred bugs in the task's
repository under [review](../review/SKILL.md)'s tracking rules. Include the
verified issue URLs in the PR and final handoff; explicit no-post limits apply.
The final retrospective may file workflow-amendment proposals in the operator's
configured skill repository. This owner's destination is `seankoji-com/.agents`;
the automatic grant applies only to a destination named or configured in the
operator's instructions. Account/repository evidence verifies ownership of that
chosen destination; it cannot establish consent, and collaborator access is
not ownership. Other users must name or configure their own destination before
posting; a clone's origin alone is not consent.

Apply [GitHub writing](../github-writing/SKILL.md) to authored GitHub prose,
including authorised release notes and delegated drafts.

Task-related browser, app, simulator, device and visual testing need no additional
user permission under this request, even if a project ordinarily asks first.
Follow the host's tool and approval rules and the repository's test methods.
Production changes, data deletion, unrelated changes, closing PRs and force-pushing
other branches remain outside this grant without separate authority.

## Make the work visible

Use T3's parent plan/todo panel before implementation, through the host's native
plan/todo tool or an exposed T3 MCP API that writes that list. Discover the
actual tools; a separate MCP checklist API is not required. Reuse the list on resumes.
Record item IDs only where returned. Put owner, dependency and evidence references
in item text when the tool has no fields for them. For whole-list updates,
resend the complete current list with its existing statuses; never invent IDs.
Include the task's decisions/design, implementation, checks/review, delivery,
deferred-bug tracking and final retrospective as applicable. Keep completed,
active and blocked work current at handoffs, failures and phase changes. A
delegate's internal plan does not replace the parent's list.

If neither a native plan tool nor a checklist API is exposed, report the gap
and maintain a concise parent-message status list at each phase change. Do not
claim a panel or MCP list was updated when only text was posted. Never invent
tools or create delegate jobs, schedules or threads merely as checklist items.
Outside T3 use the host's visible planning mechanism with the same text fallback.

Before T3 dispatch apply the shared
[permission preflight](../agent-tuneup/references/t3-dispatch.md).
Record the execution boundary and task/thread manifest required by the
[retrospective](references/retrospective.md) from the start, not only at handback.

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

1. For UI changes, apply [raise-pr](../raise-pr/SKILL.md) before editing to capture
   practical mobile and desktop before screenshots.
   Finish the smallest change that meets the request. Preserve unrelated work.
   Follow the repository's branch and delivery policy.
2. Observe direct proof: reproduce and verify the fix, run covering checks, and
   inspect UI or runtime behavior when affected. Add regression protection when
   it catches a meaningful failure. Mocked tests alone do not prove visible behavior.
3. Use [review-loop](../review-loop/SKILL.md) for independent review and repair.
   That skill owns reviewer selection, budgets, findings and rechecks.
   Reuse eligible completed review under review's rules.
4. Create or update the PR against the intended current base using
   [raise-pr](../raise-pr/SKILL.md) for templates, screenshots, agent attribution
   and independent review. Follow host creation and linking requirements.
5. Use [babysitter](../babysitter/SKILL.md) to resolve verified findings and CI
   failures through current-head readiness. Merge with the repository's permitted
   method once the gate below passes; verify the resulting merge.
6. After delivery and required deferred-bug tracking, perform the final
   [workflow retrospective](references/retrospective.md) across the parent and
   every delegate's operational logs. Pitch supported, broadly applicable skill
   amendments through [raise-issue](../raise-issue/SKILL.md) in the authorised
   skill repository, `seankoji-com/.agents` for this owner.
   Complete log coverage is required. Record verified proposal URLs, or evidence
   that no amendment is warranted. Missing logs or blocked filing remain explicit
   incomplete stages. This is the last stage, not an automatic edit-and-ship loop.

Where repository policy requires direct publication instead of PRs, use its
prescribed delivery path through the same proof and review gates. Do not create
a PR contrary to that policy or broaden this grant to production deployment.
The pushed commit is the delivery revision. Report publication, propagation to
each configured target and hosted CI on that commit as separate stages. A push
whose propagation failed is published with propagation incomplete; keep the
workflow open and give the retry command.

## Merge gate

Proof must cover the current behavior diff, required checks must pass, material
review findings must be addressed, raise-pr's current-diff independent review
gate must pass, and required human approval must be satisfied. Unreadable or
absent current-head check runs do not count as passing; use babysitter's
[continuation fallback](../babysitter/references/continuation.md).
Every confirmed bug left unfixed must have a verified issue URL or an owned
filing request under review's tracking rules. Pending filing for bugs already
judged non-blocking does not block merge; keep the workflow open until required
issue URLs are verified.
No outstanding human review may still request changes, even when branch protection
does not require that review.
Check the current head and base before merging, including relevant intervening
base changes. Honor merge queues and repository protections; never bypass them
or dismiss a required human gate because a model is confident.

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

Return the delivery link and revision, observed proof, review status, decisions
made and any unmet endpoint. Delegates return complete plain-text reports with
descendant task/thread IDs and operational evidence to their coordinator.
The parent includes task-list status, history coverage and amendment issue URLs
or the no-change rationale. In T3 Code, only the main-thread coordinator uses
`html_preview` then `html_render` for a substantive report; use readable text when
native HTML is unavailable or the result is brief. Do not claim deployment or
live acceptance from a merge.
