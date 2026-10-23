# Continuous mode

Read with `PKG/playbooks/maintain.md` and `PKG/references/scope.md`. This file is the
execution contract for a repo or org sweep that must keep moving between native PR
wakes. Prose about "monitoring continues" is not coverage: either the coordinator
holds a recorded host schedule and a next action for every admitted PR, or it reports
the event-only gap.

## Schedule contract

Create recurring work only after the owner explicitly asks for continuous or
scheduled coverage. Invoking `repo` or `org` authorises the active run, not an
indefinite schedule. Record the authorisation source (the owner request bytes and
their SHA-256), then use the host scheduler:

```sh
python3 PKG/scripts/continuous.py start --state <state.json> --now <RFC3339> \
  --scope-kind org --scope-value <owner> --scheduler scheduled \
  --authorization-source <owner-request.txt> --thread-id <this-thread> \
  --cadence-seconds 600 --queue-threshold-seconds 900
python3 PKG/scripts/continuous.py schedule-plan --state <state.json>
```

Keep `<state.json>` in the private run state, for example
`$XDG_STATE_HOME/t3-plugins/babysitter/continuous/<run-id>.json`; never in a PR
worktree or the job directory. It holds no credentials, only the recorded scope,
policy, schedule receipt and PR state.

Defaults are a **10-minute sweep** and a **15-minute queued-job threshold**. Pass
`--stall-threshold-seconds` (default 1800) to change when unchanged work is a diagnosed
stall. `schedule-plan` returns the structured `schedule_task` arguments, a stable
`clientRequestId`, and the stop tool. Create it once, then record the host receipt:

```sh
python3 PKG/scripts/continuous.py schedule-record --state <state.json> --now <RFC3339> \
  --schedule-id <returned ID> --next-run-at <returned nextRunAt>
```

The recorded scope, cadence, schedule ID and stop operation
(`delete_scheduled_task` with that ID) go in the next status report. A second
`schedule-record` for the same ID is idempotent; a different ID for the same scope is
refused until the old schedule is stopped. On cancellation or handoff, stop the owned
schedule and verify it is absent or disabled. If the scheduler is unavailable or the
owner has not authorised it, record event-only coverage and state the gap: native
watches cover linked PR changes only, so idle discovery and queue-age diagnosis cannot
run.

## Observation and state

Every scheduled wake, native event, child completion and manual resume passes a fresh
discovery snapshot through:

```sh
python3 PKG/scripts/continuous.py observe --state <state.json> --now <RFC3339> \
  --wake-kind schedule|event|manual|resume --wake-id <host event or wake ID> \
  --observation <snapshot.json>
```

The snapshot has `complete`, optional `gaps` (`pagination`, `rate-limit`,
`partial-search`, `denied`) and `prs`. Each PR carries `repo`, `number`, `state`,
`head_sha` (or the reader's `head_oid`), `draft`, `fork`, `mergeable`,
`merge_state_status`, `checks_state`, `unresolved_threads`, `required_contexts`,
its `checks` (name, status, conclusion, `created_at`, `started_at`) and any `owner` or
`human_blocker`. A `list-prs.sh` line can be passed unchanged as a `prs` item: its
`pending_checks` and `failing` names are read, and `oldest_pending_check` carries the
job's creation clock.

An omission never closes a known open PR. Resolve it from an explicit targeted host
read with `continuous.py resolve --state <state.json> --now <RFC3339> --pr <url>
--resolution merged|closed --head <sha>`; a temporary search omission only sets
`reconcile-discovery` with a next check.

The helper is deterministic and offline. It preserves the roster, admission and
progress state between turns and returns the actions plus their deadlines. It never
calls T3, GitHub or a model, and it never treats its own output as a merge receipt.

## Progress, stalls and next actions

For every admitted open PR the coordinator records:

- queue age from the oldest pending check, measured against the coordinator's own
  observation time, not from the last wake;
- the last **meaningful** progress: head change, check-state change, thread reduction,
  review change or observed merge. A repeated identical read is not progress;
- the next action and its check deadline;
- a concrete blocker when no action is available.

Queue diagnosis is specific: `waiting-for-runner` (queued, no runner),
`running-tests` (in progress), `stale-head-checks`, `missing-contexts`,
`stuck-aggregate-gate`, `fixer-in-flight` or `stalled-work`. Crossing the threshold
produces `diagnose-queue` in existing authority: inspect the job and its queue reason,
then act on what is repairable. Do not raise timeouts, weaken checks, restart
infrastructure, or rerun an unchanged failure to manufacture progress. An external
cause stays a named blocker with a next check. A queued auto-merge or armed watch is
never reported as merged or complete.

Every eligible open PR ends a turn with one of: a tracked child in flight, a permitted
merge action, confirmed ownership elsewhere, a concrete external blocker with its next
check, or an explicit human-only question. Routine repair, retry diagnosis and an
already-authorised merge never ask.

## Discovery, admission and ownership

Reconcile the whole current scope on every scheduled wake and ordinary completion. A
partial page, denied read or rate limit is a recorded discovery gap; never evidence
that the scope is empty or done. Continue with supported paginated or narrower reads.
Keep previously admitted open PRs visible when a temporary search omits them; only an
explicit merged or closed host state closes a row. Deduplicate by PR URL.

A new matching PR is admitted automatically under the original request, with its
per-PR actions recorded before writes and its own job when repair is needed. Explicit
exclusions, drafts, forks and confirmed active ownership stay honoured. Ownership
reconciliation uses work plus continuation state: a parked thread that still
maintains the PR owns it; a terminal turn with no live continuation releases it.
Historical links never exclude a PR forever. A tracked fixer suppresses a merge or
branch update until its result is ingested.

Repeated wakes and events share stable keys: the same wake and snapshot is a no-op,
and a fixer dispatch keeps one request ID per head and blocker fingerprint. Neither
duplicate schedules, dispatches, replies nor writers are created. Cancelled runs
produce no actions until an explicit resume.

## Report before yielding

Reporting uses unchanged evidence instead of regenerating a handoff round:

- scope, cadence, schedule ID, stop operation and whether the schedule receipt was
  verified;
- coverage mode, last complete discovery and any gap or omission;
- each PR's state, queue diagnosis and age, last meaningful progress time, next action
  and next check deadline;
- human-only blockers separately from routine waits.

## Resume and installed-package drift

`continuous.py version` reports the running package version and policy version.
`resume` compares the state's pinned `policy_version` and package with the running
package. It refuses a silent swap and returns `migration-required` with the exact
gaps. Migrate only through the supported path: record the owner decision, run
`job_cli.py upgrade-package` for a pinned job, then resume with
`--accept-migration --owner-decision-id <id>`. Immutable briefs, evidence and the
pinned package stay untouched; the migration receipt is appended to the state.

Offline and simulated tests prove the state decisions, idempotency and installed
artifact path. They do not prove a live T3 scheduler created a schedule or delivered a
wake; report those as separate live verification until observed.
