# Run, resume or cancel a study

Before substantive `run`, collect a fresh upfront selection as in the plan
playbook, with operation `run`, exact matrix/analyst/fidelity targets and options.
Admit it with `plan_review.py admit`, then record it using `plan_review.py run`
with `{state_root, study, admission}`. This revalidates the exact study-plan
receipt. The public job create/prepare/direct/accept boundaries also enforce it,
even when a caller omits the policy marker. A generic work choice cannot replace
a participant model or analyst.

Unchanged `resume` and automatic wakes reuse the agreement, choices and remaining
budgets without retain-or-stop. Changed models need an authorised study revision,
review and approval; retain prior findings and observations.
Read-only status/doctor/cancel and nested helper calls stay direct.

Every launch passes `study.py` admission first. The helper charges budgets and
refuses; T3 owns dispatch, status and cancellation. Never write a polling loop or
start a watcher; T3 completion notifications wake you.

## Preflight

Optional procedural context is target-specific and reviewed separately from
product stimulus. The exact file/hash and mandatory source must remain intact,
and the fresh catalog's actual harness must match before admission or preparation.
Dispatch the generated `context_files` unchanged. A participant cannot add siblings
or nested references. Retain the actual trace harness and classify auxiliary reads
as procedure, never product evidence; missing/opaque evidence stays unverified.

An explicitly delegated revision also needs its current grant, original native
owner context and exact independent receipt to remain live. Use
`authority.py revision-inputs` for its bounded generic revision, then the public
decision/guarded plan-revision route. Required guards cannot be removed. Adopt
reviewed packages while still direct/unmarked, before enabling delegation;
upgrade-package refuses afterwards. Never bypass that refusal. Recheck authority
immediately before host dispatch and retain any already accepted/uncertain handle.
Revocation stops new authority-dependent preparation/disclosure/acceptance, while
raw result ingestion, cancellation and reconciliation remain usable.

Save a fresh `orchestrator_capabilities` response and wrap it as a catalog
observation (`schema_version`, `observed_at`, `source`, `response`, optional
schema `observations`; see `PKG/references/study-contract.md`). Save a new one
before each dispatch batch; it expires after 15 minutes.

```sh
python3 PKG/scripts/study.py check-run --state-root ROOT --study ID --capabilities observation.json
```

It refuses an unapproved revision, an approval whose lifetime ceiling no longer
covers the revision (`approval_insufficient`), changed material, a passed deadline,
a cancelled study, a stale or older observation, a model, option, provider or
reviewer independence the fresh catalog no longer supports (`readiness_stale`), and
a required hard stop the observation does not show. On `inputs_changed` or
`readiness_stale`, return to `plan <study>`; on `approval_insufficient`, ask the
owner to approve the amendment instruction it shows.

## Create the job

On the first `run`, build the generic job from the approved revision and create
it with the shared helper:

```sh
python3 PKG/scripts/study.py job-spec --state-root ROOT --study ID \
  --installation-id INSTALLATION --documents participant-briefs.json --capabilities observation.json
python3 PKG/shared/job_cli.py create --state-root ROOT --job ID --input job.json \
  --prefix PREFIX --agents-root AGENTS_ROOT
```

`participant-briefs.json` maps each participant task ID to its document-only brief
`{path, sha256}` from `evidence.py brief` (see `PKG/playbooks/journeys.md`).
`job-spec` refuses a missing, hand-written, changed or contaminated brief. A
participant slot also carries the exact approved pack paths and hashes as
`context_files`, initial viewport first. `prepare` grants read authority to those
files; dispatch that prepared brief unchanged. It checks each file before launch,
and admission checks the pack and slot mapping before charging. Do not replace
these references with unresolved filenames or promise attachments the host did not
deliver. Use the host's image-read receipts as delivery evidence; a participant's
claim or a filename is not a receipt. Missing image events stay `unknown`, including
when the Codex activity surface omits image-view events. OpenCode host `read`
receipts reporting `Image read successfully` can support delivery of those images.

A journey brief exists only after its cell's first impression is accepted and
frozen, so the first job uses `--defer-journeys`. The job declares
first-impression, journey (combined only), analysis and a final review stage, and
pins this package and its worker definitions. The analysis and review slots stay
unpreparable until `report.py` binds their inputs, report documents, authors and
author independence (below). Each journey depends on its own cell's first
impression, not on the whole first-impression stage.

Once a cell's journey brief exists, add its slot through the shared plan-revision
route:

```sh
python3 PKG/scripts/lifecycle.py journey-slots --state-root ROOT --study ID --documents journey-briefs.json
```

It returns `decision_input` (the owner's approval of this exact revision, as the
`plan:<id>` decision) and `plan_revision_input` adding only undeclared journey
slots. Record them with `job_cli.py decision` and `job_cli.py plan-revision`.
Existing slots, results and the study budget are unchanged; a slot already
declared is skipped. The journey stage stays unaccepted until every slot it needs
has an accepted result.

After the owner approves a new revision, the job still prepares the old one, and
`check-run`, admission and `resume` hold every launch (`job_revision_stale`). Move it
through the same shared route:

```sh
python3 PKG/scripts/lifecycle.py job-revision --state-root ROOT --study ID [--documents briefs.json]
```

Without `--documents` it lists each slot of the revision: `current`, `filled` (an
accepted or carried result), `needs-brief` (build it with `evidence.py brief` for the
task ID shown), or `held-live` (unsettled host work keeps its old contract until it
settles). With the briefs it returns `decision_input` (the approval of this exact
revision) and `plan_revision_input`, which move the stage contracts, authority,
policy, targets and briefs; record both as above. Requests, handles, execution
history, earlier briefs, accepted results and charges are never rewritten. An
executed slot runs again only after a charged `job_cli.py retry` and a new
admission. A slot whose job brief or target is still an earlier revision's is held
(`job_slot_stale`).

## Dispatch one task

For each slot, in dependency order:

1. `python3 PKG/scripts/study.py admit --state-root ROOT --study ID --input req.json --capabilities observation.json`
   with `revision`, `request_id` (the job slot's current request ID), `stage`,
   `cell_id` (null for analysis and review), `target`, `material_classes` and
   `purpose` (`initial`, `repair`, `replacement` or `resume`).
2. Only on `admitted: true`, follow `PKG/shared/job-coordination.md`: `prepare`,
   `delegate_task` with the exact target and `clientRequestId` set to the request
   ID, then record the handle with `job_cli.py task-observation` (`accepted`, with
   the host's status identity). Every participant task is a fresh child; never
   continue a participant through a follow-up or a message to its thread.
   Shared preparation also reserves global/provider capacity. On `admission_deferred`,
   retain the charged request and wait for an owned completion; reconcile and re-admit
   the same ID before preparing again. Never reset its charge or issue a replacement ID.
3. A lost `delegate_task` response is recorded as `uncertain` and retried with the
   same request ID; admission returns `duplicate: true` and charges nothing. Its
   pilot is checked again first: if the pilot no longer passes, the duplicate is
   refused (`pilot_failed` or `pilot_pending`) and reconcile lists the request under
   `launch_held`. Concurrency is checked again the same way, without counting the
   request's own reservation: while other owned work, such as a closed request whose
   host task reopened, fills the limit, it is refused `concurrency_limit` and held
   until that work settles. Do not dispatch a held request. Ask the host for its
   `clientRequestId` and record any task found; a task the host already started
   (`host_started: true`) is reconciled as usual. A request from a superseded revision (`superseded_revision`) or a closed one
   (`request_closed`) is never launched. A charged new attempt is a
   `job_cli.py retry`, which records the slot's new request ID; admit that ID and it
   draws from the shared repair pool. While the slot's earlier request is still open
   or cancelling, any other new request ID for it is refused `slot_in_flight` and
   charges nothing.

## Pilots

The first cell of each model is its pilot and a normal matrix cell. Admission
refuses that model's other first impressions (`pilot_pending`, `pilot_failed`)
until the pilot's first impression is accepted, usable and of verified identity
(or of an identity discrepancy the owner accepted). Journeys are gated the same way
by the pilot journey, which needs browser tools, a verified cell-bound context and
hands-on goals; a pilot whose journey is all gaps makes the model's journeys
unavailable (`journey_unavailable`). The two gates are independent, so capture
cells continue when no isolation exists. A journey is never admitted before its own
current brief exists (`journey_brief_missing`), so an unbriefable journey is never
charged. `lifecycle.py pilots` shows every gate. A protocol, persona or material
change is a new revision: the old pilot is never relabelled, and the new revision's
pilot runs again unless its result carries unchanged.

### Recovering a spent pilot after a workflow fix

Retain every rejected transport, trace decision, charge, attempt and approval.
Installing a fixed package does not move an existing job's pins or make its old
evidence usable. First reconcile all owned work and ingest every returned result.
For an explicit same-job package change, use the hash-bound `upgrade-package`
procedure in the imps user guide (`docs/plugins/imps.md`, "Upgrading a whole job"):
record owner authority for `plan:<upgrade-id>`, invoke the new installed package's
`shared/job_cli.py upgrade-package` with the old caller, exact current state hash,
new package digest, dependency key `focus-group`, prefix and agents root. Keep the
retained migration backup. Do not edit pins or counters by hand.

Then plan and approve the required study revision. A changed generated prompt
needs a changed approved `prompts` value so its input binding changes; a wording
change in the installed generator alone cannot silently reset a slot. If the same
inputs need more attempts, raise `max_attempts_per_slot` and the repair pool as
needed, approve the new lifetime ceiling, and apply `lifecycle.py job-revision`
with newly generated briefs. This also updates the job's shared repair policy.
Use `job_cli.py retry` and admit its new request ID before preparing a fresh child.
Both the study and generic job must have headroom. A larger overall allowance
alone never authorizes a third attempt in a two-attempt slot. Contaminated
executions stay contaminated; never reclassify them or edit their payloads.

Admission refuses everything `check-run` refuses, plus a revision other than the
approved one, a cell or target outside the matrix, a journey in a capture-only
revision or on a model the observation shows without browser tools or isolation,
material a provider instance is not granted for that role, a slot already filled
in this revision or by its carry mapping, a slot held for an unwritten carry
mapping (`carry_unresolved`), a job slot without this revision's brief and target
(`job_slot_stale`, `job_slot_missing`), the concurrency limit, a spent slot or pool,
and the approved lifetime ceiling. Concurrency counts each distinct unresolved
owned host task (a handle or a retained conflict, even for a request closed
earlier) plus one reservation per live request with no host task yet. A settled
handle frees its slot even while its request's conflict still runs.

## Notifications and reconciliation

On every T3 completion notification, call `task_status` for the named owned task,
record what it returned (`job_cli.py task-observation`: `completion` or
`reconciled`, with `status`, `work_state` and `has_pending_child_runs`; a pending
question as `approval-wait`), then run once:

```sh
python3 PKG/scripts/lifecycle.py reconcile --state-root ROOT --study ID --now NOW
```

It reads the recorded job and study once and returns each request's state and the
bounded actions for this wake: `ingest`, `task_status`, `task_cancel` (owned
handles only), `dispatch_same_request` (open requests with no host task that may
start now), `launch_held` (those whose pilot no longer passes or whose start other
owned work would push over the concurrency limit) and `rediscover`. A request owns its
accepted handle and every other host task returned for it that the job retained as
a conflict (`host_conflicts`): a refused observation never proves that task did not
run. Each such task stays listed (`conflicting-host`) until its own `reconciled`
observation is terminal with no pending runs. Only when every owned host task is
terminal, with no pending child runs and no nested work, does the request close
and free concurrency; a charge is never refunded. A parent marked done, a summary saying
done, `cancel_requested` or a pending question never establishes quiescence. An
earlier terminal reading contradicted by a later one is `conflicting-observations`
until a fresh `task_status` is recorded; once cancelling or past the deadline, that
owned handle is listed under `task_cancel` instead. Repeating it with the same records changes
nothing. Then end the turn; never poll or start a watcher. With a job, `study.py
release` is refused: requests close only from recorded host observations.

## Accept results

Submit the complete output with `job_cli.py result`: the shared strict parser
checks the correlations, revision and binding and retains each transport it
reads, malformed ones included. A `{path}` transport above 32,768 bytes is refused
before the job reads it. Run `ingest` after every `result`, refused or not: it
retains the complete bytes (up to 16 MiB) and logs the refusal, never truncating
or extracting:

```sh
python3 PKG/scripts/lifecycle.py ingest --state-root ROOT --study ID --input ingest.json --capabilities observation.json
```

with `task_id`, `request_id`, `completion_id`, `transport` (the same complete
bytes), and `image_delivery` for a first impression or `context` and
`material_inspection` for a journey. It retains the raw bytes under
`focus-group/sessions/` first, before even the catalog check, and appends each
outcome to that request's session log. It refuses a stale catalog observation
(ingest the same bytes again with a fresh one), an oversize transport, one the
shared parser has not recorded, a conflicting second response, a malformed or
not-ready result, an unsettled host task or unreconciled conflicting host task, a
wrong slot and a missing, ambiguous or altered
`artifacts/tasks/<task-id>/payload.json`. These are session, lifecycle or provider
outcomes, never product friction. Identity comes from the recorded host sources
under the shared rules: `verified`, `mismatched` (another catalog model or
provider), `ambiguous` (an observed ID the catalog does not list; never resolved to
the request) or `unreported` (no provider or no model). The accepted record keeps
that identity as history; pilots, `progress`, `resume`, coverage, carry, disclosure,
briefs and admission read the identity its own request's handle shows now, so a
later host source naming another model makes the record, and any journey built on
it, unusable. Only `verified` is verified coverage. Show the owner the cell's
`identity_evidence` from `progress`: every recorded reading and the exact
`instruction`. `lifecycle.py accept-identity` records the owner's acceptance of
exactly that evidence (`Accept observed model P/M for focus-group cell C S request R
(requested P/M)`, or for contradictory readings `Accept contradictory host identity
for focus-group cell C S request R (requested P/M; readings ...; resolved ...; now
P/M)`). Use then stays disclosed as an accepted discrepancy and never carries. While
the job handle is `mismatched`, it also prints `decision_input`: the same owner source
and quote as the shared `identity-exception:task:<task-id>` for exactly that
execution. Record it once with `job_cli.py decision`; nothing is asked again. Stage
acceptance can then take the execution as unverified evidence. The handle and its
blocker stay, and `decision_recorded: true` means it is already in the job. An
equivalent reading from another source keeps the study decision but changes the job
binding: run `accept-identity` again with the same owner source, statement and
`message_ref`. It returns the recorded decision unchanged and a new `decision_input`
for the current binding; record that one too, with no new prompt. A new
provider/model association or a changed canonical resolution voids both decisions, and
the old answer no longer matches, so ask again with the new instruction. A reading
after the stage was accepted stales that acceptance. A validated pass is accepted
again only after a charged re-execution of a participant slot. Without a
complete canonical identity or two contradicting complete readings, there is nothing
to accept: the cell stays a visible hold showing its `missing` fields.

`ingest` then calls the participant acceptance boundary. `study.py
record-acceptance` exposes the same boundary only for a study without a job; once a
job exists it refuses (`host_ingest_required`). The boundary reopens those exact bytes and every file they cite, then
scans and validates them. Suspect material is quarantined before any accepted
record exists. In the same step the helper freezes the first impression or binds
the journey evidence to these bytes. A journey binds only the first impression
accepted in, or carried into, its own cell and revision; write the revision's carry
mapping first. A result for a slot that the written mapping already fills is
refused (`slot_already_filled`); its raw artifact and charge stay recorded.
`evidence.py freeze-first` and `accept-journey` only re-verify that binding, and
`evidence.py coverage` reports it.

## Accept a stage

Only the pinned study validator accepts a stage. For each stage, in dependency order:

```sh
python3 PKG/scripts/report.py observation --state-root ROOT --study ID --stage STAGE
python3 PKG/shared/job_cli.py observation --state-root ROOT --job ID --input observation-input.json
python3 PKG/shared/job_acceptance_cli.py accept-stage --state-root ROOT --job ID --input accept.json
```

Save the printed `observation` outside every worker artifact folder; the
`job_cli.py observation` input is `{caller, stage_id, input_file}` and it returns the
frozen path. `accept.json` is `{caller, stage_id, revision, input_file: FROZEN,
validator_argv: [PKG/scripts/validate_study.py, --input, FROZEN]}`. A worker's
`ready-for-acceptance` or approval is never acceptance. Journey slots can be added
one cell at a time, for example after a pilot journey: a later `journey-slots` call
stales only the journey stage's acceptance and its successors. Journeys already run
keep their requests and results, so accept the stage again once every slot is ready.
A stage already accepted before the addition needs a charged pass for the new slot's
first execution (`job_cli.py retry` on that slot); unchanged slots are never re-run.

## Synthesis, fidelity review and export

The operation matrix deliberately retains this existing stronger final review:
it checks the exact integrated report against all accepted inputs, omitted
contradictions, quotes, support, dissent and current author identity. No duplicate
planning pass is added to that same synthesis. It remains a separate fidelity
slot, with a fresh distinct-lineage child and its existing repair budget; a
planning fallback receipt can never stand in for it.

Record shapes are in `PKG/references/report-contract.md`.

1. With the participant stages accepted, freeze the analysis inputs and bind the
   analyst slot (record both outputs with `job_cli.py decision` and `plan-revision`):
   `python3 PKG/scripts/report.py analysis-inputs --state-root ROOT --study ID
   --capabilities observation.json`. Admit, prepare and dispatch the analyst; the
   brief is document-only. It also lists, as hash-bound `context_files`, a copy of
   every cleared pack file and accepted journey file the inputs cite; preparation
   rehashes each and grants read access to exactly those files. Journey text files
   are inlined too. Tell the analyst to open its brief's context files; whether the
   provider can view an image is not established by this delivery.
2. After `job_cli.py result`, run `report.py synthesis --input {task_id: analysis,
   request_id, completion_id}`, then accept the analysis stage. A refusal is never
   fixed by editing the artifact; ask for a charged repair.
3. A coordinator change to findings or wording is `report.py edit --input ...
   --capabilities caps.json` with your own fresh `orchestrator_capabilities`
   response; it makes you a synthesis author. Never hand-edit a rendered file.
4. `report.py render --out DIR` writes the bundle outside the job directory.
   Inspect `report.md`, the issue drafts, the copied evidence and `sources/`: one
   portable projection of each cited accepted payload, with its parent hashes,
   disclosure decision and any path-to-file-name change. Every observation links to
   it, and its pointer resolves there to the exact quote.
5. `report.py review-slot --bundle DIR --capabilities observation.json` checks the
   reviewer can run, has a known lineage different from every author, and that every
   earlier finding has a disposition. The round's context names the analysis inputs
   document and every context file, so the reviewer can check material the synthesis
   left out. Record its outputs, then (for a later round)
   `job_cli.py retry` with category `review`, and admit, prepare and dispatch a fresh
   reviewer. Dispose each review finding with `job_cli.py finding-disposition`; a
   contested finding is `rejected` with your frozen response, and the next round
   receives it. A spent review pool blocks another round.
6. Accept the review stage. `report.py status` shows the review state from current
   receipts; `complete` is true only with a current reviewed receipt, no unresolved
   owned work and no journey gap, and a capture-only study never completes the
   combined scope (`combined_scope_complete: false`).
7. `report.py export --bundle DIR --out NEW` writes the portable export locally with
   its review status. It publishes nothing and starts no fix or imps run; any later
   issue, PR or implementation is a separate, separately authorised request.
   `report.py verify-export --bundle NEW` rechecks a moved copy.

## Resume

Start with `status`, call `task_status` for every recorded owned handle and record
each answer, then:

```sh
python3 PKG/scripts/lifecycle.py resume --state-root ROOT --study ID --now NOW --capabilities observation.json
```

It reconciles first (as above, including the deadline), then checks the source
bindings (approval, material, pack, written carry mapping and the fresh catalog)
and lists every declared slot: `accepted`, `in-flight` (never dispatched again),
`held` with its refusal (also an open request with no host task whose pilot no
longer passes or that other owned work keeps over the concurrency limit), `slot-undeclared` or `dispatchable` with the admission
check it passed (a dry run that charges nothing). Changed material holds every
slot until a new revision. Accepted cells, running tasks and charged counters are
never duplicated or reset; analysis and review report `in-flight` while running.
It never reports completion; the study validator decides that, and never while
owned work is unresolved. For a new revision run `study.py carry --write`, then
`lifecycle.py job-revision`, before dispatch: unchanged accepted cells carry
forward by explicit mapping and are never dispatched again; changed inputs stale
only the affected cells and successors.

## Cancel

```sh
python3 PKG/scripts/study.py cancel --state-root ROOT --study ID
```

It stops all further admissions, marks owned open requests cancel-requested and
returns the same recorded-host view as `reconcile`: `cancel` lists every unresolved
owned request, including one closed earlier whose later host reading shows pending
work, and `task_cancel` its owned handles. Record job intent with `job_cli.py
cancel`, call `task_cancel` for each listed handle (owned handles only), record each
terminal `task_status`, and run `reconcile` again. `cancellation_confirmed` (the
same in `cancel`, `reconcile` and `wake`) stays false until every owned host task's
latest recorded reading, conflicting ones included, is terminal with no pending
child runs. A request with no immutable brief and no host task in the job could not
have been dispatched: it closes as `never-prepared`, charge kept, and reopens if a
brief or handle for it is ever recorded. A prepared request with no recorded host
task (a crash or a lost response) is listed under `rediscover` with its
`clientRequestId`: ask the host for that task, record one it finds as `accepted`
with the same request ID before `job_cli.py cancel`, then cancel it. If the host
cannot resolve it, the request stays named and cancellation unconfirmed; it is
never dispatched again. Artifacts are retained.
`lifecycle.py progress` is the read-only summary of pilots, identity, session
failures and unresolved owned work.
