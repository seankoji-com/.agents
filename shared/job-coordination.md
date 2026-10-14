# Whole-job coordination

Shared by imps, ape, elephant-goldfish, babysitter and agent-tuneup. Plugin entries add
only their own policy: stages, workers, validator and boundaries. Exact helper inputs
and limits are in `PKG/shared/agents/jobs-contract.md`; model choice, allowed tools and
brief content are in `PKG/shared/delegation.md`; approvals follow `PKG/shared/t3-runtime.md`.

The coordinator is the main agent. It alone plans, dispatches, ingests, accepts and asks
the owner. Workers execute one slot, return one result and never dispatch, accept their
own work or widen their authority.

## 1. Cheap operations stay direct

`doctor`, `status`, list and inspection operations run their deterministic commands
directly. Never create a job or launch a worker for them.

## 2. Plan

Substantive multi-stage work gets one job. Write the complete `job.schema.json` object
and run, from the current package (`t3-plugins path PLUGIN`):

```sh
python3 "PKG/shared/job_cli.py" create --state-root "$ROOT" --job JOB_ID --input job.json --prefix PREFIX --agents-root AGENTS_ROOT
```

`ROOT` is `$XDG_STATE_HOME/t3-plugins/jobs` (default `~/.local/state/t3-plugins/jobs`,
mode 0700) or an explicit alternative, never inside the target repository. The plan
declares finite stages and task slots, acyclic dependencies, requirements and
constraints quoted verbatim, action authorization kept separate, every plugin
dependency (cross-plugin ones included), and a final integration/acceptance stage with
its verification and review slots. From then on resolve each package from its pin:
`t3-plugins --job "$ROOT/JOB_ID/job.json" path PLUGIN` prints the pinned entry, and
`PKG` is its directory. Run every later helper from that pinned `PKG`; a helper run from
another package refuses with `wrong executing package`. Every mutation input carries
`caller: {actor: "coordinator", installation_id, workflow, package_digest}` copied from
the job and its pin.

## 3. Dispatch

Per slot: `job_cli.py prepare` with `{caller, task_id, target_reason}` returns only path,
SHA-256, bytes and provenance. Choose the target with `t3-plugins resolve ROLE
--capabilities FILE`: the lowest suitable configured tier, a recorded reason and an
ordered escalation. Reviewers need a reviewer or judgement tier and a known different
lineage (`--implementer-lineage`). Launch T3 `delegate_task` asynchronously with the exact
target, options and role, and `clientRequestId` set to the slot's `request_id`. The
bootstrap tells the worker to read the brief at its path and stop if the SHA-256 differs.
Record the returned handle at once with `job_cli.py task-observation`, event
`{kind: "accepted", request_id, host_task_id, child_thread_id}`. A worker's request for
more work is checked against declared slots; anything else is a plan revision.

## 4. Lifecycle

T3 completion notifications wake the coordinator; never poll or start a watcher. Read
`task_status` (terminal status, `workState`, pending runs) and record it as a
`completion` observation with `completion_id`, `status`, `work_state` and
`has_pending_child_runs`. Ingest with `job_cli.py result`, passing the whole terminal
summary as `result: {json: ...}` or a declared result file as `result: {path: ...}`.
A truncated summary is recovered once through `t3_thread_read` as
`PKG/shared/delegation.md` describes, never re-run. The
parser rejects prose, fences, duplicate keys and oversize input; never extract or
truncate. An uncertain launch is recorded as `uncertain` and retried with the same
`clientRequestId` at most twice. A definite capacity rejection is `capacity-deferred` and
retries only after a new owned completion notification. Cancel follows
`jobs-contract.md`: `job_cli.py cancel` or `discard` records intent and keeps artifacts;
`task_cancel` each owned live task and record a terminal `reconciled` observation from
`task_status`.

## 5. Acceptance

A terminal task is not an accepted stage. Freeze coordinator-observed input with
`job_cli.py observation` (`{caller, stage_id, input_file}`), then run
`job_acceptance_cli.py accept-stage` with the pinned plugin validator argv and that
frozen path. Exit 0 accepts; 1 rejects or leaves it unverified; 2 is invalid input. For
imps, the stage gate `validate` stays the authority. Dispose every finding with
`job_cli.py finding-disposition` and coordinator evidence; unresolved blocker or major
findings block. Final readiness needs `job_acceptance_cli.py validate-final` (imps: a new
final gate) to accept every requirement at the integrated snapshot.

## 6. Repair

Each stage gets the initial attempt plus `max_repair_cycles` (default 3) through
`job_cli.py retry` (`{caller, task_id, reason, category}`, category `primary`, `support`
or `review`). Resume, escalation and replacement never reset counters. A bounded
same-scope follow-up uses `job_cli.py followup-prepare` (`{caller, task_id,
request_id}`), then `t3_thread_send` with `mode=queue` to the owned `childThreadId` only
when the host supports it as a new tracked task, recorded as a `followup` observation.
Otherwise launch a fresh child and show the reuse-fallback reason. When the coordinator
repairs a reviewed document, `job_cli.py document-revision` (`{caller, task_id,
document: {path, sha256}, reason}`) rebinds the new hash within the budget, without an
owner decision, and stales the affected stages; then `retry` each executed slot.
Exhausted budgets block for an owner decision (`attempt_budget_exhausted`).

## 7. Fallback

If T3 or every suitable target is unavailable, record the bounded discovery and errors,
then run the stage directly under the same contract, counters and gate. Show
`fallback: direct (<reason>)` in every checklist for that stage. A missing required
independent review stays a blocker; direct work cannot supply independence.

## 8. Visibility and resume

Emit a compact checklist from `job_cli.py overview` at each stage start, acceptance,
blocker and integration milestone: one line per stage with status, next dependency,
open decisions and fallback markers. Never stream raw logs or transcripts. Resume starts
from `overview` (or read-only `status`) and reconciles existing handles with
`task_status`; a missing reply never justifies recreating work.

## 9. Approvals and owner decisions

Ask every owner decision through the native question picker in
`PKG/shared/t3-runtime.md`, recommended option first. While a task waits on it, record a
`task-observation` `{kind: "approval-wait", wait_id}`; acceptance stays blocked. Save the
answer verbatim to a private file outside the job directory and worker write scopes,
record it with `job_cli.py decision` (`{id, quote, source, source_sha256, scope}`; scopes
`plan:<revision-id>`, `waiver:<task-id>`, `settings-change:<change-id>`), then record
`approval-resolved`. A `job_cli.py plan-revision` that returns `undeclared_expansion`
needs such a decision first. Silence is not approval.
