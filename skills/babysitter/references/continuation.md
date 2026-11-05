# Continue an owned PR through merge

Read this when starting, repairing or resuming babysitting. Record the next
executable action in the host's existing task record, or a small ignored note
inside the owned worktree. This is recovery evidence, not another scheduler.

## Preserve unfinished work

For every requested PR retain:

- URL/repository, source/base refs and SHAs, writer/coordinator, dependencies,
  authority source and explicit holds.
- Phase, next action, actor and trigger. Useful phases are repair, review,
  checks, merge, queued, external hold, merged, closed and continuation unavailable.
- Feedback IDs/content, validated findings, severity, disposition, repair commit
  and verification. Observed, assigned and pushed remain unfinished; confirmed
  fixed, justified rejection or tracked deferral closes the item.
- Reviewer task/receipt, identity/lineage, reviewed head or precise diff, findings,
  remaining acceptance and review/retry budget across pushes and resumes.
- Watch owner/receipt, last reconciled head and pending jobs. Record merge or
  closure only from a fresh GitHub read with its evidence.

Update after material actions and before yielding. On resume reconcile the
record with GitHub, including old/outdated unresolved feedback and review bodies.
Notification delivery is not evidence that a repair happened. A failed child
leaves its work pending; replace or perform it after confirming no old writer
remains active. Duplicate wakes do not create competing workers, replies, issues
or merges. A new head invalidates stale evidence unless semantic review reuse is
justified. An old wake means refresh, not act on the old revision.

Before dispatching review, identify an available eligible reviewer and who will
receive its result. A repair child returns its exact diff/head and review packet;
the parent obtains review. Record unavailable routes once, try another unnamed
eligible route when allowed, and retain named-model and sharing constraints.
Finish independent checks while review runs. A reviewer that never started
needs a trigger or replacement, not repeated passive waiting.

## Repair without repeating a stalled approach

Fix verified in-scope code, test, CI and review defects together. Isolate
independent writers and reactivate dependents after prerequisite merges.
Coordinate overlapping ownership instead of competing pushes.

Rerun an evidenced transient failure once before investigating recurrence,
unless repository policy supplies another bounded retry. Retain failure
signature and attempt count. Repeated identical failures need log inspection,
a reproduction or another diagnostic approach. Code failures need repairs;
do not repeatedly rerun them or weaken checks. There is no fixed repair-push
cap while verified progress continues within scope and the active task budget.

This workflow allows three independent review attempts per PR across repairs/resumes.
After review's [budget diagnosis](../../review/references/budget-exhaustion.md),
allow one automatic extension of at most two attempts only with a changed
approach, expected new evidence and a stop condition. Stricter caller budgets
win. A new reviewer, push or phase never resets attempts. At exhaustion, retain
the exact gate and monitoring, continue other work, and request only the concrete
decision/access or bounded extension needed. Exhaustion is partial work.
Record the automatic extension and its caller-rule authority in the shared
procedure's history. Include it alongside any user-approved extensions when
handing off or presenting a later extension request. Hold further review if the
diagnosis cannot justify a changed approach; continue independent authorised work.

## Trigger actual review services

Inspect configured bots and their documented triggers. After material pushes,
trigger applicable re-review when needed and confirm registration for that head.
Distinguish pending, failed, skipped-by-policy, never-started and completed
reviews. Green checks do not dispose of existing findings. Paginate history.

Some bots run only after draft conversion. Establish a pre-existing draft's
purpose and readiness acceptance; preserve explicit owner holds.
Mark ready when authorized and its actual hold is satisfied, then
request review. Use the configured service's documented registration grace and
native events. At expiry, diagnose why it never started. Do not invent absent
bots, send speculative bot commands or wait indefinitely for unused services.
Advisory status does not waive required review, approvals or release findings.

## Keep one continuation owner

Reconcile feedback immediately before arming/rearming the sole native watch.
Verify registration and follow the returned next action; end the turn immediately
when required. On wake sweep existing feedback, not only the notification.
When the host permits a post-registration reconciliation, inspect that gap;
never ignore a required yield. Open PRs, merge queues and approval holds retain
their watch. Report unavailable continuation rather than claiming monitoring.

A native watch may stay silent while an unchanged job sits queued. Before
yielding, record each pending current-head job's queue age and runner state. A
job queued without a runner for about 15 minutes needs diagnosis on the next
wake: runner labels, concurrency groups, pending workflow approval and
organization runner limits. Report the concrete blocker and its next check. Do
not rerun, raise timeouts or weaken checks to show progress, and do not count an
armed watch or enabled auto-merge as progress. When no wake is guaranteed,
because no event will fire and no authorised schedule exists, report that
stall-detection gap at handback rather than claiming coverage.

Transfers need the successor's accepted scope, live task/watch receipt and next
action before releasing the old watch under host rules. Sending a message or
creating a thread does not establish transfer. Status replies are yields; final
handback states its terminal/transfer reason before unwatching. Retain evidence
for pending deferred-issue writers.

Outside T3, `pr-wait` reports intermediate conditions, not merge permission.
Event de-duplication is not a work backlog: recollect feedback after restart.
A ready/green exit requires fresh gates and the authorized next action. When
GraphQL is exhausted, REST may allow PR state at `repos/<owner>/<repo>/pulls/<n>`
and checks at `repos/<owner>/<repo>/commits/<sha>/check-runs`. Inspect reset
evidence; do not add a second watcher or tightly retry an exhausted API.

Before trusting a green required aggregate, compare the workflows expected for
the current head with its observed runs. A missing expected workflow leaves the
head unverified even when other workflows ran, for example a conflicting PR
whose `pull_request` workflows never started while `pull_request_target` ones
did; integrate the base and get runs on a real head.

Some tokens cannot read check runs (fine-grained tokens lack `checks:read`). On
a 403, record the denied read, then read Actions runs for the exact head
(`repos/<owner>/<repo>/actions/runs?head_sha=<sha>`), their jobs and failed
logs, plus `commits/<sha>/status`. A workflow's conclusion is not a required
context's result: a context passes only when the job that reports it succeeded
on this head. Report unmapped or ambiguous contexts as unverified, keeping
success, failure, skipped and unknown distinct. After merge, read the
default-branch push runs for the merge commit.

Zero observed CI checks do not establish that no CI is expected; a review-bot
check alone does not establish CI registration either. The fallback
waits three minutes for registration, then returns an inspection action rather
than readiness. Use `--allow-no-checks` only after repository policy/source
establishes that no checks are expected. Missing required checks still block.
After ten minutes a pending check emits an inspection notice without turning
the check into a failure or waiving it. Draft/current-head change-request holds
return action. After earlier feedback is addressed, trigger re-review and retain
the watch while an older-head change request awaits a new decision. Unknown
review provenance requires inspection. Human-approval waits remain active without
extra GraphQL refreshes. If protection APIs deny access, report that concrete
gate; unknown required checks are not an empty requirements list.

## Verify behavior, not prose

Use synthetic helper tests and, when authorized, bounded host trials. Link tests
cannot prove that a live agent follows the loop. Record revision, actions,
watch/review receipts and outcomes; listed scenarios are not executed evidence.

1. A ready PR produces an expected-head merge attempt and fresh MERGED read.
2. A failed-check wake leads through diagnosis, repair, checks, push, an owned
   independent review, current-head hosted CI and verified merge.
3. Missing review gets a supplied actor. Unavailable review stays a gate without
   stopping independent checks or other PRs.
4. Interruption after observation/dispatch leaves feedback actionable. Duplicate
   wakes/resumes recover work without competing writers or repeated side effects.
5. Changed head/base invalidates old evidence; late bots are triggered or diagnosed.
6. Queue acceptance/auto-merge retains ownership until MERGED. Human approvals
   and release holds remain intact; other open PRs retain confirmed watches.
7. Rejected merges are diagnosed/repaired within authority. Failed watch
   registration is reported as a continuation failure, never active monitoring.
8. An approval that arrives with new review threads leaves the PR unready until
   each thread is fixed, rejected with reasons or tracked.
9. A job queued without a runner is diagnosed on the next wake, or reported as
   a stall-detection gap when nothing will wake the coordinator.

Fallback cases additionally cover two samples of the same head/base, a head
changing during collection, pending checks, draft/approval holds, no-check repos
and truncated feedback. Keep these separate from native T3 lifecycle acceptance.
