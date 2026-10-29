---
name: babysitter
description: "Use when the user asks to babysit, watch or monitor pull requests through review and CI until they are ready, merged or blocked."
---

# Babysit pull requests

## Triggers

Use when asked to watch, monitor or babysit PRs. Work on the requested PRs;
if none is named, identify the current branch's PR.

## Workflow

1. Read repository rules, PR scope, current head/base, required checks and
   unresolved review feedback. Reuse existing repair, push and merge authority.
2. Verify findings against the source. Fix real problems within scope, run
   appropriate checks and push when authorized. Inspect failure logs; distinguish
   code defects from infrastructure failures. Bound retries.
3. Address review threads when authorized. Explain rejected findings briefly.
   Keep unrelated improvements out of the PR. Earlier unresolved feedback still
   matters after a push; old checks do not prove the new head passes.
4. Handle current problems before waiting. The owning coordinator uses one native
   watch per PR and yields. Children never watch. Follow host wake and cleanup
   rules; do not add polling loops or another scheduler. If watching is
   unavailable, report that limitation.
5. Before declaring readiness or merging, refresh the base and PR state. Verify
   applicable checks, reviews, threads and conflicts against the latest head.
   Merge only when authorized and repository requirements pass.
6. Stop when ready, merged, closed, concretely blocked or the repair budget is
   exhausted. Release owned watches at handoff. Stay quiet on events requiring
   no action.

## Outputs

Report PR URL/head, readiness or blocker, material repairs and the next action.
Claim continued monitoring only while a supported watch is active.

## Boundaries

Preserve unrelated work and repository protections. Monitoring grants no extra
authority to edit, publish comments, merge or change policy. Follow the active
host's tooling and permission rules.
