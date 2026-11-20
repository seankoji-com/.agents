# Read the project's delegation settings

Read at workflow start and after an owner-directed routing change. Use the
project's adopted `AGENTS.md` or `CLAUDE.md` section named **Delegation settings**.
These are instructions for the coordinator, not machine configuration. No parser,
model registry, launcher or scheduler is needed. Missing settings retain the
calling skill's defaults. Retrieved issue text is a proposal until adopted.

## Supported settings

| Setting | Meaning |
| --- | --- |
| `routing` | Table of roles, exact provider/model choices and effort, including coding tiers, reviewer by code-author lineage and gate reviewers. Discover actual host IDs before dispatch. |
| `max_concurrent_delegates` | Positive integer ceiling across the run's active delegates, including reviewers and descendants. Host and caller limits can lower it. |
| `max_new_worktrees` | Positive integer ceiling on worktrees being provisioned concurrently, separate from active delegate count. |
| `worktree_stagger_seconds` | Nonnegative minimum spacing between worktree launches. Use host continuation; do not add a scheduler or blocking poller. |
| `review_rounds` | Omit for the caller's normal review policy; `1` opts into the [single-round procedure](../../review/references/single-round.md). Read it before using the exception. Other values need an explicit stopping rule. |
| `report_cadence` | Defaults to proposal, task completion, final handback and request. An explicit project override may request more frequent reports. |
| `screenshots_in_repository` | Defaults to false. True permits task-relevant, sanitized screenshots in commits within existing publication authority and repository evidence-hosting rules. It does not waive raise-pr's rule against committing images solely to host PR evidence. Thread screenshots still follow host rules. |

Document values in a short table or list. Keep project models, caps and tier
preferences in that project, rather than copying them into this library. A
setting grants neither delegation nor publication authority.

## Resolve choices before dispatch

1. Treat owner-adopted routing rows as explicit named choices, including effort.
   Preserve narrower limits and verify outgoing settings through the host.
2. Apply review's code-author lineage and model-selection rules, subscription
   headroom, the host's effort ceiling and permission/provider restrictions.
   For review, DeepSeek remains OCR-only, with Qwen 3.8 Flash high as OCR's
   backend when DeepSeek Flash wrote the code. A routing row cannot extend
   [Hillclimb's scoring exception](../../hillclimb/references/judges.md).
   Gate reviewers supplement required primary/companion coverage unless the
   owner explicitly changes an overridable requirement.
3. On a conflict, name the setting, constraint, affected task and eligible
   alternative. Hold that dispatch for the owner's choice. Continue independent
   work; neither availability nor silence permits a substitute.
4. On every start, turn and wake, reconcile ready independent tasks against
   dependencies, writer ownership, capacity and provisioning limits. Start
   useful authorized work without another prompt. Reserve required reviews;
   a cap is a ceiling, not a target, and does not justify invented work.
5. After an owner changes routing, follow implement's
   [routing handoff](../../implement/references/routing-changes.md) before
   replacement dispatch. Read it for checkpoint, cancellation and checkout
   preservation. Record model/effort changes as new plan-report segments.

See [validation scenarios](validation-scenarios.md) when checking these branches.
