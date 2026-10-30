---
name: full-send
description: Trigger this if the user says 'full send'.
---

# Full send

An explicit "full send" request authorizes completing the requested change through
a merged PR while the user is away. It includes task-related tests, committing,
pushing, merging through repository protections and rebasing the PR's own branch
with `--force-with-lease`. Explicit narrower limits still apply.

Task-related browser, app, simulator, device and visual testing need no additional
user permission under this request, even if a project ordinarily asks first.
Follow the host's tool and approval rules and the repository's test methods.
Production changes, data deletion, unrelated changes, closing PRs and force-pushing
other branches remain outside this grant without separate authority.

## Finish the endpoint

1. Finish the smallest change that meets the request. Preserve unrelated work.
   Follow the repository's branch and delivery policy.
2. Observe direct proof: reproduce and verify the fix, run covering checks, and
   inspect UI or runtime behavior when affected. Add regression protection when
   it catches a meaningful failure. Mocked tests alone do not prove visible behavior.
3. Use [review-loop](../review-loop/SKILL.md) for independent review and repair.
   That skill owns reviewer selection, budgets, findings and rechecks.
4. Create or update the PR against the intended current base, with concise proof
   in its description. Follow host creation and linking requirements.
5. Use [babysitter](../babysitter/SKILL.md) to resolve verified findings and CI
   failures through current-head readiness. Merge with the repository's permitted
   method once the gate below passes; verify the resulting merge.

Where repository policy requires direct publication instead of PRs, use its
prescribed delivery path through the same proof and review gates. Do not create
a PR contrary to that policy or broaden this grant to production deployment.

## Merge gate

Proof must cover the current behavior diff, required checks must pass, material
review findings must be addressed, and required human approval must be satisfied.
No outstanding human review may still request changes, even when branch protection
does not require that review.
Check the current head and base before merging, including relevant intervening
base changes. Honor merge queues and repository protections; never bypass them
or dismiss a required human gate because a model is confident.

## Waiting and blockers

Use babysitter's native watcher. In T3 Code, register `watch_pull_request` and
end the turn while checks or review are pending so the host can wake the thread.
This is a pending continuation, not a handback. Unwatch when handing back ready,
blocked or cancelled work. Never add a second watcher or polling loop.

Continue authorized work until the endpoint or a concrete blocker. Ask through
the host's question tool only for a material ambiguity, missing authority or
proof/gate you cannot obtain yourself. Include the link, blocker, recommendation
and alternatives. Silence is not approval. If no answer or tool is available,
leave dependent work incomplete and report the specific next action.

## Report

Return the delivery link and revision, observed proof, review status, decisions
made and any unmet endpoint. In T3 Code, use `html_preview` then `html_render`
for a substantive report; use readable text when native HTML is unavailable or
the result is brief. Do not claim deployment or live acceptance from a merge.
