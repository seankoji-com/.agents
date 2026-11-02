---
name: ship
description: Use when the user explicitly asks to ship a change through tests, review and merge.
---

# Ship

An explicit "ship" request authorizes completing the requested change through
a merged PR while the user is away. It includes task-related tests, committing,
pushing, merging through repository protections and rebasing the PR's own branch
with `--force-with-lease`. Explicit narrower limits still apply.

It also authorises the coordinator to file confirmed deferred bugs in the task's
repository under [review](../review/SKILL.md)'s tracking rules. Include the
verified issue URLs in the PR and final handoff; explicit no-post limits apply.

Task-related browser, app, simulator, device and visual testing need no additional
user permission under this request, even if a project ordinarily asks first.
Follow the host's tool and approval rules and the repository's test methods.
Production changes, data deletion, unrelated changes, closing PRs and force-pushing
other branches remain outside this grant without separate authority.

## Choose supporting skills

Choose skills that help the current task, reusing settled decisions and existing
evidence. These are options, not a required sequence:

- [grilling](../grilling/SKILL.md) for unresolved product decisions that could
  materially change implementation.
- [design-chooser](../design-chooser/SKILL.md) when product decisions are settled
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

Where repository policy requires direct publication instead of PRs, use its
prescribed delivery path through the same proof and review gates. Do not create
a PR contrary to that policy or broaden this grant to production deployment.

## Merge gate

Proof must cover the current behavior diff, required checks must pass, material
review findings must be addressed, raise-pr's current-diff independent review
gate must pass, and required human approval must be satisfied.
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
made and any unmet endpoint. Delegates return complete plain-text reports to
their coordinator. In T3 Code, only the main-thread coordinator uses
`html_preview` then `html_render` for a substantive report; use readable text when
native HTML is unavailable or the result is brief. Do not claim deployment or
live acceptance from a merge.
