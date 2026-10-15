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

Store provider and model identity only when a host response reports them. Events may
carry `status_identity`, `receipt_identity` and `configuration_identity`, or one
`observed: {source, providerInstanceId, model}` record (`observed_identity` is an
alias). Sources are `status`, `receipt`, `configuration` (`thread-configuration`
is an alias), and corresponding `*_identity` event fields. Unknown sources are
rejected. Keep each source separate on the handle. Identity is mismatched if any reported provider or model in
any source differs from the pinned target. It is verified only when status reports the
target provider and some source reports the target model. Otherwise it is unreported.
A mismatch is sticky for its charged pass, retains the handle and blocks acceptance
after reconciliation. A same-pass follow-up cannot clear it; only a charged,
non-mismatched retry can. A redelivered completion ignores new identity data;
`reconciled` carries observed identity and terminal state.
Doctor reports recorded unreported providers separately from configured providers
with no recorded identity, and launches nothing.
`job_cli create` sets `policy.identity: observed` with no opt-out. Required reviewer,
subject and `independent_of_author` executions must report verified identity at
acceptance. Legacy jobs without the marker keep target-only acceptance semantics.
`elephant-goldfish/thinking` and `elephant-goldfish/elephant` set
`policy.author_independence`; preparation and acceptance enforce document lineage
despite a missing factual or cold-read slot flag. `elephant-goldfish/check` imports
matching-hash authors and enforces verified identity and a different lineage when
authors are known. Its factual slot must name the validated stage document. Extra
unknown subjects preserve the independence requirement and make preparation fail
closed. A zero-slot direct check of a document with recorded authors needs a
stage-scoped waiver bound to the latest `direct-execution` identity. Re-recording a
moved path unions both hashes; plan revisions retain job authors. Once enabled,
`policy.author_independence` cannot be disabled, even by owner decision. If the checked
hash has no author record, the read-only check may proceed with author independence
reported as unverified; a waiver cannot establish missing authorship. Direct factual
authoring stages stay blocked when authorship is unknown, even with a waiver.
SHA-256 author records retain every author. Waivers bind target, author list, slot
contract and document hash; they waive no requirement and expire when any bound value
changes. Capabilities are host evidence transcribed by the coordinator; validation
checks shape and correlation, not freshness or forgery. Recording an edited copy at a
temporary path and moving it into place also inherits authors recorded for the
destination path. The first record of an unrecorded document cannot discover earlier authors; it covers
only the current coordinator, and earlier authorship stays outside this boundary.
`document-revision` validates before updating the sidecar and unions existing
new-hash authors with inherited authors and the repairer. `record_document_author.py`
records `elephant.md`.
Elephant-goldfish coordinators record a document with
`thinking_state.py author <slug> <document.md> --capabilities FILE`; handoff rendering
uses `render_handoff.py <slug> --capabilities FILE`. A repair uses
`document-revision --capabilities FILE`. A source hash without a record keeps the
rendered handoff's authorship unknown. Zero-slot direct factual stages under author
independence set stage `independent_of_author: true`, record each executor with
`job_cli.py direct-execution --capabilities FILE`, and require known authorship and a
stage-scoped waiver bound to the latest observation. The checklist says
`fallback: direct, same-lineage (waived)`.
A direct cold-read stage is never a coordinator fallback. Acceptance refuses it; keep
`R-COLD` blocked until a separate reader completes.
Review and document-only slots use fresh executions, never same-child follow-ups.
Unexpected continuations stay owned and non-accepting, and their result bytes are
quarantined during ingestion.

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
then run the stage directly under the same contract, counters and gate. For an
author-independent factual stage, set `independent_of_author: true`, record each start
or resume with fresh capabilities, and obtain a stage-scoped owner waiver bound to the
latest executor. Show `fallback: direct, same-lineage (waived)` in the checklist.
Unknown authorship blocks acceptance because independence cannot be checked. A missing
required independent review stays a blocker; direct work cannot supply it.

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
