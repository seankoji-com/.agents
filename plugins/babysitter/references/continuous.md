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
`schedule-record` for the same ID refreshes its next run and is idempotent; a
different ID for the same scope is refused until the old schedule is stopped. Report
coverage separately from authorisation:

- `scheduled` means a schedule receipt is recorded;
- `scheduled-unverified` means scheduled mode is authorised but no host receipt exists;
- `stopped` or `stop-unverified` follows an explicit stop receipt;
- `event-only` means there is no host wake at all.

`next_wake_at` is only ever a confirmed host `nextRunAt`. A delivered scheduled wake
consumes it (`awaiting_receipt`: true) until the next host receipt; the helper never
invents `now + cadence`, and an overdue receipt stays visible as overdue. If coverage
drops to `event-only` (the scheduler becomes unavailable or is no longer authorised),
the old receipt moves to `historical_next_run_at`. An existing schedule remains
`stop-unverified`, with its owned stop operation, until the host confirms removal.
Late scheduled wakes produce no actions after revocation. Stop through the host,
then record the verified result:

```sh
python3 PKG/scripts/continuous.py schedule-stop --state <state.json> --now <RFC3339> \
  --schedule-id <ID> --verified yes
```

An unverified stop blocks re-arming until it is verified. A verified stop increments
the schedule generation, so `schedule-plan` returns a new request key and a replacement
may be recorded without losing the roster, dispatch history or ownership state. If the
scheduler is unavailable or the owner has not authorised it, record event-only coverage
and state the gap: native watches cover linked PR changes only, so idle discovery and
queue-age diagnosis cannot run.

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
`merge_state_status`, `checks_state`, `unresolved_threads`,
`review_threads_complete`, its `checks` (name, status, conclusion, `created_at`,
`started_at`) and any `owner` or `human_blocker`. A `list-prs.sh` line can be passed
unchanged as a `prs` item: its `pending_checks`, `failing` names, `checks_complete`
and `queue_clock_gaps` are read, and `oldest_pending_check` carries the job's
creation clock. GraphQL's `CheckRun` has no `createdAt`, so the reader obtains a
queued job's creation clock from the supported Actions job API named in
`detailsUrl`; a job whose clock is unavailable reports `queue-age-unknown` instead
of an invented age.

`required_contexts` is the complete configured set, which only a snapshot such as
branch-protection evidence can claim. A single-PR reader supplies the required names
among the contexts it saw in `required_contexts_observed` (binding `isRequired` on
both `CheckRun` and `StatusContext`) and always sets `required_contexts_known: false`;
a search page supplies neither. A present required check that fails is repaired, an
optional failure is not; `optional_contexts_observed` retains per-context optional
evidence even when another protection blocks landing. Diagnose that protection and
obtain configured requirements with a targeted read. `checks_state` is GitHub's `StatusState`, which has no
`UNSTABLE` value: optional-failure evidence is `merge_state_status: UNSTABLE`. A
`checks_complete: false` page is a recorded check-discovery gap for reader and full
snapshots alike; it returns a continuation to re-read the remaining contexts and can
never authorise a landing.

An omission never closes a known open PR. Resolve it from an explicit targeted host
read with `continuous.py resolve --state <state.json> --now <RFC3339> --pr <url>
--resolution merged|closed --head <sha>`; a temporary search omission only sets
`reconcile-discovery` with a next check and the current discovery gap as its detail.
A closed PR observed open again is restored to open and reconsidered. An admitted PR
that becomes a draft, fork or explicit exclusion stays visible as `excluded` with no
action until it matches the scope again; its previous next action is cleared so a
status report cannot recommend a landing that is no longer permitted.

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
`running-tests` (in progress), `queue-age-unknown`, `stale-head-checks`,
`missing-contexts`, `stuck-aggregate-gate`, `fixer-in-flight` or `stalled-work`.
Crossing the threshold produces `diagnose-queue` in existing authority: inspect the job
and its queue reason, then act on what is repairable. A failed required check, an
unresolved thread, a conflict or an actionable requested-change review is handled
before queue diagnosis, so a queued job never starves repair on the same PR. Do not
raise timeouts, weaken checks, restart infrastructure, or rerun an unchanged failure to
manufacture progress. An external cause stays a named blocker with a next check. A
queued auto-merge or armed watch is never reported as merged or complete.

Every landing decision uses current-head evidence only: checks and the checks header
must belong to `head_sha`, `review_threads_complete` must be true after reading every
conversation page, and a merge request is bound to its exact head. Rejected, cancelled
or superseded attempts are reconciled, then either retried within the bounded budget or
reported as `merge-rejected`. A live fixer blocks any merge or resolution write.

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
maintains the PR owns it, a missing continuation field on a partial update keeps the
last confirmed one, and only an explicit handoff or release value frees the PR.
Unfamiliar continuation values retain ownership, including after a terminal turn.
Historical links never exclude a PR forever. A tracked fixer suppresses a merge or
branch update until its result is ingested.

Repeated wakes and events share stable keys: the same wake and snapshot is a no-op,
and a fixer dispatch keeps one request ID per head, blocker fingerprint and attempt.
Neither duplicate schedules, dispatches, replies nor writers are created. The schedule
key includes a unique identity generated at exclusive creation, so identical run inputs never share
host idempotency or stop ownership. A dispatch is reserved before the host is touched:

```sh
python3 PKG/scripts/continuous.py dispatch --state <state.json> --now <RFC3339> \
  --pr <url> --request-id <id> --kind fixer|merge|resolution --head <sha> --reserve
# then perform the host launch, then attach the handle:
python3 PKG/scripts/continuous.py dispatch --state <state.json> --now <RFC3339> \
  --pr <url> --request-id <id> --kind fixer|merge|resolution --host-task-id <handle>
python3 PKG/scripts/continuous.py fixer-done --state <state.json> --now <RFC3339> \
  --pr <url> --request-id <id> --host-task-id <handle> \
  --result <job-dir>/results/<id>.json
python3 PKG/scripts/continuous.py receipt --state <state.json> --now <RFC3339> \
  --pr <url> --request-id <id> --status succeeded|failed|rejected|cancelled|armed|no-change
```

The reservation is the writer/merge lock: a competing fixer, merge or resolution is
refused while it exists, even before the host has returned a handle. New reservations
recheck current lifecycle, scope, ownership and head inside the transaction. A confirmed
refusal is `rejected`; a lost response, malformed acceptance or missing handle is
`uncertain` and keeps the guard. Reconcile through the host with the same request ID,
then attach its verified handle, or record confirmed refusal. Never infer absence from
a timeout. A changed head marks an open merge attempt stale but keeps its lock;
reconcile the original host operation to a terminal outcome before another write.
Terminal merge receipts for an attached task must name its recorded `--host-task-id`,
after verifying that task has ended. `armed` is accepted only for a merge and keeps it pending;
fixer and resolution receipts must name a terminal outcome. A receipt applies only to
the request it names: a replay is reported as `duplicate` or `stale` and changes no
guard or progress clock. An adopted writer (a PR observed with `fixer_in_flight` but
no local dispatch) carries the handle from `owner.host_task_id`; only a receipt naming
that handle and its accepted ingested job execution can close it. The retained transport
must match the job's hash, request, completion and terminal host observation with no
pending children. An arbitrary file is insufficient. Missing adopted identity may be
filled by another observation of the same writer; a different writer cannot replace it.
Terminal repair attempts are drawn from the bounded budget, never treated as a live
worker. Cancelled runs produce no actions until an explicit resume, though late
receipts and resolution remain safe.

The reference wiring for one sweep is `scripts/continuous_sweep.py`: a host adapter
maps `create_schedule`, `due`, `discover` and `dispatch` to the T3 tools, and the
module fixes the order reserve -> host launch -> attach handle. The installed adapter
and helper are exercised together against a fake host; that proves the installed code
path, never that a live T3 wake was delivered.

## Report before yielding

Reporting uses unchanged evidence instead of regenerating a handoff round:

- scope, cadence, schedule ID, stop operation and whether the schedule receipt was
  verified;
- coverage mode, last complete discovery and any gap or omission;
- each PR's state, queue diagnosis and age, last meaningful progress time, next action
  and next check deadline;
- human-only blockers separately from routine waits.

## Resume and installed-package drift

`continuous.py version` reports the running package version, policy version and the
installer manifest's package digest, after verifying its listed files. Source checkouts
use a source content fingerprint. `start` records the identity automatically
and defaults the pin to the installed version, so `resume` detects a swapped running
package without relying on `--package-version`. A state without the fingerprint is a
migration gap, not a silent resume. Resume refuses drift and returns
`migration-required` with the exact gaps. Migrate only through the supported path:
record the owner decision, run `job_cli.py upgrade-package` for a pinned job, then
resume with `--accept-migration --owner-decision-id <id>` and
`--upgrade-receipt <output.json> --job <job-dir>`. The helper verifies the actual job's
upgrade revision, owner decision source, new pin and retained previous job bytes against
the receipt, directory and package digest. Legacy states missing a job ID recover it
from this verified job. A digest-only receipt cannot authorise migration. Immutable briefs, evidence
and the pinned package stay untouched; the migration receipt is appended to the state.

A job created before continuous mode has no helper and no state at its pinned package.
Resolve the pinned `PKG` as `entry.md` requires to read its brief and evidence, but run
the **current** package's read-only preflight, not a helper from the legacy snapshot
(which has none):

```sh
python3 <current-package>/scripts/continuous.py preflight --job <job-dir> --now <RFC3339>
```

It reports `legacy-job` with `pinned-package-without-continuous` and changes nothing.
Upgrade the job's package through `job_cli.py upgrade-package`, then start state with
the upgraded package and `--job <job-dir>` to verify its pin. Do not swap the package
or rewrite the frozen brief.

Offline and simulated tests prove the state decisions, idempotency and installed
artifact path. They do not prove a live T3 scheduler created a schedule or delivered a
wake; report those as separate live verification until observed.
