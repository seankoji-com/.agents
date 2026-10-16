# Generic jobs and complete results (v1)

State is private, process-locked JSON outside the repository. Supply an explicit
`--state-root` and safe `--job` ID. The installed helper is
`python3 PKG/shared/job_cli.py COMMAND --state-root ROOT --job ID --input INPUT.json`.
Run existing jobs from a stored pinned package; a current pointer never selects a
replacement package, worker override or limit. Recovery pins retain both a quoted
`compatible_pinned_invocation` and structured `compatible_pinned_argv`. The latter
resolves the exact package through `t3-plugins --job JOB.json path PLUGIN`.
Exit 0 means the requested state operation succeeded; exit 2 means invalid input,
unsafe state or caller mismatch. It does not mean the job is accepted.

Creation takes the complete `job.schema.json` object and `--prefix`, `--agents-root`,
optional `--config`. Dependencies are unique `{key,plugin}` records with optional
explicit locators. Stages declare IDs, acyclic predecessors, requirement IDs, criteria,
resources and validator dependency. Tasks declare finite logical slots, request and
worker IDs, dependency key, authority, target, write scope and result contract. Pins
include exact immutable package/bundle hashes, physical base/shared definitions,
effective UTF-8 bytes and hashes, override status/bytes/hash and task-contract bytes.
The job policy freezes positive artifact-byte limits, optional worker capacity and
nonnegative repair limits. Default repairs are 3; artifact transport defaults to 16 MiB.
Explicit larger artifact limits are supported. A subsequent increase needs an owner
record; a narrowed limit retains already performed counters.

Mutation input includes `caller: {actor,installation_id,workflow,package_digest}`.
The actor must be explicit. Coordinators alone prepare, dispatch-record, ingest,
revise plans, accept, cancel or discard. Workers can use the separate evidence-write
API only with their exact task ID, stage, package and declared scope. Worker files
are confined to `artifacts/tasks/<task-id>/`; special files, symlinks and traversal
fail before writes. Shared library callers supply the stored-pin verifier through
`pinned_store`; installed CLIs also verify their executing package. These checks
record declared ownership; they are not cryptographic proof of operator intent.

Commands are `create`, `overview`, `status`, `prepare`, `result`,
`task-observation`, `followup-prepare`, `observation`, `finding-disposition`, `decision`, `plan-revision`, `document-revision`, `retry`, `cancel`, `discard`.
A decision needs a stable ID, literal quote, absolute source-file path, matching
source SHA-256 and scope. The quote must occur in the actual UTF-8 source bytes.
Its source must lie outside this job directory and all declared worker write scopes.
The host supplies and verifies owner intent; a matching source file records
provenance and cannot cryptographically authenticate the same OS user.
Normal briefs carry only decisions scoped to their task waivers. Document-only
briefs retain their isolated context. Plan revisions
retain prior requirements/history and performed counters. Added slots/dependencies,
weaker coverage/constraints, changed worker authority or raised limits require a
matching `plan:<revision-id>` decision. Narrowing and harmless reordering do not.
`revision.adopt_keys` explicitly adopts updated definitions/overrides for declared
dependencies; the adapter snapshots only changed keys and keeps other pins byte for
byte. Affected acceptance and briefs, including transitive successors, become stale.

`prepare` input names a task and optional target reason. Its output is only path,
SHA-256, byte count and compact provenance. Each attempt brief is immutable and
self-contained; its internal effective hash excludes only that hash field. Normal
briefs carry exact constraints, pins, predecessor outputs, scope and stop conditions.
A `document-only` task supplies a document path/hash. Its brief omits the job objective,
predecessor reports, resource context, requirement statements and other definitions;
it carries only procedural role/output instructions, the document and opaque correlation
fields. A job-specific task contract is forbidden for this isolated context.

`result` input has a completion ID and either `result: {json: FULL_JSON_STRING}` or
`result: {path: TRANSPORT_FILE}`. The complete bytes pass the strict parser with the
stored brief correlation, assigned requirement IDs, revision and binding. No prose,
fences, heuristic extraction or truncation. Every finding remains referenced with a
separate disposition; a blocker/major forces an adverse verdict. Waivers must carry the exact stored owner decision (quote, source, source SHA-256,
`waiver:<task-id>` scope) and the requirement must be permitted by
`policy.waivable_requirements`. Worker-authored waiver claims do not authorize skipping. Metrics are finite numbers, or `{value:null,reason:...}` when unavailable.
Duplicate completions are idempotent. Unusable accepted executions consume their
attempt; a new request or resume cannot reset the counters.

Initial pass 0 plus repairs 1–3 are shared across primary/support/review failures.
Failed slots in one pass share the same next cycle; eligible current successful
support evidence can remain. Preparation records the stage pass an execution belongs
to (`cycle`), so a slot first executed in a later pass is charged a new pass when it
fails; an executed slot without a recorded pass is never treated as pass 0. A pass
that was already validated admits no new execution, retry join or follow-up without a
charged pass, and a stage whose repair passes are spent refuses every new request.
A capacity deferral cannot apply to an executed request and never clears staleness.
A follow-up also requires an unspent execution budget. Every fresh attempt gets a new deterministic request
ID; original requests/handles stay in history. Observations record exact accepted
host IDs, status, work_state and pending-child state. An uncertain original dispatch
permits two same-ID retries, then blocks. Capacity retries require newly observed,
deduplicated owned completion notifications. A follow-up requires an authoritative
terminal original with no pending runs, unchanged target/scope, a new tracked host ID
and parent relationship. `followup-prepare` takes caller, task ID and a new
request ID, and freezes its full brief before launch. There is one follow-up slot
by default; the plan can disable it. Original briefs, results and referenced
evidence remain immutable. Nothing in these helpers calls a model or schedules work.
Cancellation/discard record intent and preserve artifacts; host termination still
requires an authoritative observation.

Host identity is separate evidence on each handle. Store only returned status,
receipt and child-configuration provider/model fields. A status provider must be
present to verify identity; use its model, then the receipt model, then the
configuration model when those sources report one. Receipt-only, configuration-only
and provider-only records are `unreported`. Never substitute target values. Provider
or model mismatch retains the host handle and adds a sticky `identity-mismatch`
blocker; a terminal `reconciled` observation records the host's final state without
erasing that blocker. Redelivered completion notifications do not replace earlier
identity evidence.

Review and document-only slots refuse `followup-prepare`. If a forbidden follow-up is
observed after launch, retain its handle and blocker, ingest its bytes only to
`results/quarantine/<request-id>.json`, and mark that execution non-accepting. The
request can be reconciled and a charged fresh retry can proceed. Acceptance never
parses or selects quarantined bytes.

Acceptance uses `shared.job_acceptance.accept_stage`, `validate_stage` and
`validate_final`, or the installed `shared/job_acceptance_cli.py` actions
`accept-stage`, `validate`, `validate-final`. Exit 0 means current authoritative
acceptance, 1 means rejected/unverified, 2 means invalid invocation. Only exact
verified pinned adapter programs run, never returned artifacts. Input descriptors
bind the arguments and files the adapter actually consumes. Imps descriptors bind
state_root/run_id or state_root/final_plan; document handoff descriptors bind
root/slug/mode. A pre-check semantic generation and all real input/program hashes
are captured before execution. Changed input during checks cannot be certified
retroactively. Execution and acceptance share stage pass 0 plus repairs 1–3. Validation of
the current execution uses that pass; repeating standalone validation advances
the same counter. Worker stages require fresh charged execution after a failed
pass. Read-only receipt checks do not consume another pass. Failed passes remain charged; receipts are immutable, sequenced and
hashed. Receipt revalidation recursively checks predecessor chains and reruns current
authoritative validators. Hand-edited accepted flags or recomputed hashes do not
replace the current validator. Every selected slot needs its current ingested ready result, matching immutable
brief/request/revision, current artifact bytes, and resolved blocker/major
dispositions. Live handles, pending children or approval waits block. The complete
reserved job generation is checked again before committing acceptance. The commit also
rereads the adapter and compares its program, pin and actual inputs (observation, run,
plan, source or backup bytes and criterion IDs) with the binding reserved before the
validator ran. A different, unavailable or malformed reading stales the stage, publishes
no acceptance, and keeps the receipt for the reserved bytes and its charged pass in
history; it never rebinds to the new bytes. Changes after that commit-time reading are not
observed. `validate_stage`
captures the job generation before its validator and `validate_final` reserves it while
charging the final pass; after validators return, both reread the job and reject any
generation change, live/pending work, pin failure, coverage gap or broken receipt chain.
A rejected final pass stays charged and records a final-failure entry. Status
commands render derived readiness without mutating job state or minting authority.
Validator helpers have pinned ceilings of 30 seconds and 1 MiB combined output;
stage.validator_limits may narrow them. Timeout/output overflow retain a failed
receipt and kill only the validator process group.

Workflow observations are explicit coordinator receipts with observer, operation kind,
source, full content and SHA-256 of canonical content. They bind reported coverage,
head/check/thread/endstate or factual/cold-read/load observations. They establish
record provenance and declared criteria, not external truth through a readiness
boolean. Imps final plans list all required stage-local gates at current integrated
inputs. Final failures reopen responsible stage evidence and stale successors;
final passes retain their separate budget. Live provider fidelity remains a separate
gate, never inferred from these deterministic tests.

Adapter contracts are declared before workers run. Ape binds input criteria to
stage.criteria; babysitter and tuneup bind stage.validator_contract fields to
the complete input (required_contexts/authorized_endstate, or audit criteria).
Empty required PR contexts require explicit permission and a matching latest
host-policy observation. Multiple PR observations have strictly increasing
coordinator sequence numbers; only the latest is current. Document observation
contracts bind path/hash and the invoked root/slug. Imps final plans must use
the same state_root as the bound invocation. Their stage rows need unique non-empty
string IDs; the adapter refuses repeated or invalid IDs. Before any snapshot or stage
gate runs, the final gate also refuses a plan unless required_stages names every
declared row exactly once and each row binds a contained state_subdir, run_id and
validator hash. It then snapshots every row's binding before the first gate, runs each
gate only at its reserved binding and snapshots the whole set again after the last gate;
a changed, unavailable or malformed binding fails, naming its stage. The adapter binds
only the plan bytes, so this final recheck is what keeps earlier stages current. Nothing
observes changes after that final snapshot. Tuneup apply needs a recorded change
or explicit allow_noop_apply criteria. These input contracts cannot be weakened
by a returned result.

Before acceptance, use `observation` with caller, stage_id and input_file to freeze
coordinator input outside every worker artifact subtree. It returns path/SHA/bytes;
that returned path is the validator input. The stage records the immutable reference.
Publishing changed input invalidates current and dependent acceptance. Direct
coordinator stages explicitly declare execution_mode direct. Worker stages require
every selected current result; zero workers do not substitute for worker evidence.

`finding-disposition` takes task_id, finding_id, disposition fixed/rejected/deferred,
and evidence {path,sha256,bytes}. A finding ID reused across executions with changed
content is retained as a separate row with its request ID and `finding_sha256`; pass
`finding_sha256` to select it. Identical re-reports share one row. It verifies and freezes nonempty coordinator
evidence, preserves the prior disposition in history and binds it into acceptance.
Deferred blocker/major findings remain unresolved. Never edit job.json to dispose
findings. Removed logical slots retain their performed counters; replacement task
IDs inherit the same stage/logical-slot budget. New slots cannot invent runtime
results/handles and receive initial defaults. Uncertain exhaustion prevents fresh
preparation and charged replacement until the original is authoritatively reconciled.
An accepted observation records an existing host handle; it does not launch work.
Uncertainty observations cannot replace an already accepted handle. Retry requires
every owned handle terminal with result_available and no pending child runs. Late
observations for older requests update their retained handles and history only.
Plan changes stale acceptance while preserving any live handle and its immutable
brief. Changed live task authority is refused. Those invalidated task inputs cannot
be accepted until a charged repair after reconciliation. A replaced worker pin,
a changed upstream observation and a final-pass reopen invalidate tasks the same way,
including live ones. A stale task stays `stale` when its result or a terminal
observation arrives; it cannot prepare or adopt a follow-up. A follow-up brief takes
its stage, slot, worker, definition, target, write scope, authorization, constraints,
requirements and revision from the current task contract and is refused when they
differ from the original brief; the host follow-up observation must match the current
target and write scope. Only a fresh preparation of a never-executed slot clears
`inputs_stale`; an executed slot needs a charged retry.

Ape criteria declare id/kind (source-provenance or finding-source-coverage), never
status. Optional minimum_findings is a nonnegative integer. The stage contract
pins sources {id,url,revision,path,sha256} before work; validators read the actual
absolute source bytes and check finding quotes against those sources. The adapter
also binds the observation's operation to the workflow (ape/study: study; ape/forage:
forage-research, or forage-synthesis, which needs dependencies), its requirement
IDs to the stage, and synthesis consumed_reports to the dependency outputs.
validate_report.py then checks report sections, pinned revisions, citations, coverage
and coordinator inspection receipts. These checks establish provenance/coverage, not
the semantic truth of all research conclusions.
Babysitter contracts declare pr, head_sha, required_contexts, optional_contexts,
allow_empty_required_contexts and authorized_endstate. Optional failures remain
visible and cannot be silently promoted to required or ignored without policy.
Document contracts declare absolute root, slug, mode and, for observations, absolute
document_path/document_sha256. Imps contracts bind state_root/run_id or final_plan
{required_stages,stages}; a named integrated stage can explicitly certify that set.

Read-only status verifies local receipt and input hashes without running validators
or persisting invalidation. Explicit validate reruns current adapters. CLI descriptors
are bounded at 16 MiB before JSON parsing; result transport remains 32768 bytes.
Persisted job state also has a 16 MiB ceiling on reads and writes. Oversize history
blocks without truncation or replacing the prior state. Validator subprocesses
retain failed receipts and charged cycles on timeout, including closed output
pipes, and terminate their owned process group even after its leader exits.
Conflicting dependency limits need explicit job policy instead of silent first-pin
selection. Overview includes actual original/followup host IDs, request IDs, child
thread IDs, lifecycle states and pending-child observations.

Criterion or validator-contract changes require a source-bound plan decision;
criterion list reordering alone preserves its meaning and acceptance binding.

Plan revisions preserve runtime-owned request IDs, immutable brief references, uncertainty and capacity counters, reconciliation and observations when those fields are omitted. Supplied runtime values must match the stored state. A request changes only through charged retry or prepared follow-up APIs after owned handles are reconciled. A plan revision cannot remove or change the contract of a slot with an open or uncertain dispatch, a blocked dispatch, a handle that is not terminal with work_state result_available and no pending runs, or an unreconciled conflicting host (slot record or job blocker); a plan decision is not evidence that host work ended or never started. Applied revision IDs cannot be reused, including retries; inspect the stored revision receipt and use a fresh revision plus a matching fresh owner decision for another expansion. Decision IDs are immutable.

Request and task IDs are reserved across the whole retained job history: current requests, `original_request_id`, `retired_request_ids` (every request a retry or replaced staged follow-up gave up), handles, follow-ups, staged or uncertain follow-up dispatch, dispatch history, host conflicts, execution history and superseded-plan task snapshots. A new plan slot, charged retry or follow-up cannot take a reserved request ID, a new slot cannot take a task ID retained by a removed slot, and every write refuses state in which one task's request is retained by another task. A completion ID ingested or notified for one request cannot be ingested or notified for another request, including removed tasks and earlier attempts of the same task. A new stage cannot take a stage ID retained by superseded-plan history, so a removed stage cannot return with reset `cycle`, `validated_cycle`, `acceptance_runs` or `attempts`. A host task ID stays bound to its first request, including on removed tasks. One completion notification permits one capacity retry per job. The follow-up budget belongs to the logical slot: a replacement task in the same stage and slot inherits follow-ups already dispatched there. A staged follow-up can launch only from the handle of the task's current request and only if its frozen brief follows that request; after a retry, prepare a new follow-up. A slot with a blocker or major finding cannot be removed until that finding has a `fixed` or `rejected` disposition with evidence. Normal briefs are `briefs/<task_id>-<sha256(request_id)>.json` and follow-up briefs are `briefs/followup/<task_id>-<sha256(request_id)>.json`; late results use the same lookup. Result transports, briefs, follow-up briefs, coordinator observations, disposition evidence and acceptance receipts are create-exclusive: an existing path accepts only identical bytes and is never replaced. An owner plan decision authorizes adding or removing slots, not rebinding earlier execution evidence.

Coordinator and owner source boundaries compare physical paths, including Linux double-leading-slash aliases. Reads still use the original path with non-following descriptor traversal and reject parent components and symlinks. These checks rely on host permissions keeping external coordinator/owner records outside worker authority. They do not authenticate human intent or protect against a privileged actor able to replace or hard-link external records.

Pass 8 ingestion requires a coordinator-supplied outer `request_id`, separate
from the worker's JSON. If owned handles exist, that request must name one of
them; an observed completion ID must agree with its owned request. Late results
use that request's retained immutable brief and result path. They preserve old
execution evidence and charges without changing the replacement slot's status.
Current malformed completions charge once and retain their raw transport.

Required reviews compare recorded targets. The worker and each reviewer need a
known `providerInstanceId`, `model` and routing `lineage` on the declared target
and the owned handle; a follow-up handle inherits its parent's target. Review
preparation and acceptance refuse a reviewer on the same provider/model, on the
same lineage, or with unknown lineage. The target is the coordinator's record,
not host proof of the model that ran.

A review slot (`role: review`) names exactly one subject form. `reviewed_task_ids`
lists distinct worker tasks in its stage and needs the lineage checks above.
`reviewed_documents` lists distinct `{path, sha256}` records: absolute regular files
with no parent traversal or symlink component, outside the job state. A document-only
review names exactly its supplied `document`. Both forms, or neither, are refused.
Preparation and acceptance re-hash each document; changed bytes make the review
stale. For document subjects, set `independent_of_author: true` on the review slot
and record `document_authors` from records keyed by the exact document hash. Authoring
jobs with `policy.author_independence` enforce this check for every factual and
cold-read slot even when its own flag is absent. The
reviewer lineage must be known, canonical and different from every author lineage.
Unknown authorship or lineage fails closed. A factual slot must name the exact document validated by its stage. Unknown additional subjects cannot remove `independent_of_author`; they make the result stricter. New jobs require verified observed
identity for reviewers, their subjects and author-independent slots under
`policy.identity: observed`; legacy jobs without that marker keep target-only
acceptance semantics. Approval still needs the reviewer's completed owned host
execution and the `approve` verdict.

Author-independent jobs require `document_authors`. `create` imports records only
when the sidecar hash matches current bytes; it never adds the creating coordinator.
Handoff authorship unions renderer and source-hash authors. Missing source records
make authorship unknown. Record `elephant.md` with
`record_document_author.py <path> --capabilities FILE`; check jobs never record their
checker as author. `elephant-goldfish/thinking` and `elephant-goldfish/elephant`
enable `policy.author_independence`. `elephant-goldfish/check` imports matching-hash
authors and enforces a different lineage and verified worker identity when authors
are known. Without a matching record, its report says author independence is unverified.
`plan-revision` re-imports authors for changed or added slots and rechecks each slot
against its stage document. A zero-slot direct check of a recorded document requires
`direct-execution` evidence and a stage-scoped waiver bound to the latest executor.
If a direct check's hash has no author record, the read-only check may proceed with
author independence reported as unverified; a waiver cannot establish missing
authorship. Direct factual authoring stages stay blocked when authorship is unknown,
even with a waiver. A direct cold-read
stage cannot fall back to the coordinator and acceptance refuses it. Re-recording a
path inherits later records in its sidecar; plan revisions retain job authors. Once enabled,
`policy.author_independence` cannot be disabled, even by owner decision.

Re-recording inherits its previous hash and every same-sidecar record ordered since
that path was last recorded. Copies or moves across directories and unrecorded edits
are outside the trust boundary. A first record cannot identify earlier authors; author
records remain host evidence transcribed by the coordinator, and shape and hash checks
do not prove freshness or detect forged files.

`document-revision` takes caller, task_id, `document: {path, sha256}`, reason and
`--capabilities FILE` for author-independent document jobs. The capabilities response
must include inherited provider, model and parent thread, and the inherited model must
be in that provider's catalog. It unions authors already recorded for the new hash,
prior authors and the repairing coordinator, then propagates them to affected slots.
A refused revision leaves sidecars untouched. The
task must name that path, have an ingested execution and be settled; the new hash must
differ and match the current bytes. Within the persisted repair budget it needs no
owner decision: it rewrites the hash in every stage contract and slot naming the path,
stales those stages and successors, and records history. Each executed slot then needs
a charged `retry`. A spent budget refuses with `attempt_budget_exhausted` and
`owner_decision_required`; raising it is a plan revision with an owner decision.
Zero-slot direct factual stages under author independence set
`independent_of_author: true`, record each start or resume with
`job_cli.py direct-execution --capabilities FILE`, and require known authorship plus
a current `lineage-waiver:stage:<stage-id>` decision bound to the latest recorded identity.
Their checklist says `fallback: direct, same-lineage (waived)`.

Observed identity may use `status_identity`, `receipt_identity` and
`configuration_identity`, or `observed: {source, providerInstanceId, model}`
(`observed_identity` is an alias). Sources are `status`, `receipt`, and
`configuration` (`thread-configuration` is an alias); unknown source names are
rejected. Each source is retained separately. Any present provider or model that
differs from the pinned target makes that execution mismatched, and the mismatch is
sticky for the charged pass in which it was recorded; a same-pass follow-up cannot
clear it. Only a charged retry whose new execution is non-mismatched clears it.
Verification requires the
status source to report the target provider and at least one source to report the
target model; incomplete evidence is unreported. A redelivered completion ignores its
new identity fields. A terminal `reconciled` observation retains its observed identity
and host state.

A second host ID for an already owned
original or follow-up request is refused; `task-observation` retains it in the
task's `host_conflicts` and the job `blockers`. Until a `reconciled`
`task-observation` for that host ID and request reports a terminal status, no pending
runs and a work_state other than working/waiting_for_children, the task refuses
retry, preparation, follow-up preparation and acceptance for any request. An
`uncertain` observation for the prepared follow-up request is same-ID follow-up
uncertainty (two retries, then blocked); it blocks those operations until a
`followup` observation records that request's host ID. Acceptance requires every
owned handle terminal with work_state result_available and no pending runs. An uncertain or blocked original needs an accepted host observation
for its request before its result is ingested or accepted. Late results for a
superseded follow-up use that follow-up's frozen brief. Plan revisions, waivers
and settings authorizations re-read the owner source and recheck its SHA-256 and
quote at each use. Brief, final-plan, document, receipt and observation reads are
bounded (16 MiB, or the job artifact limit) before parsing. JSON nested beyond the
parser's recursion limit is invalid input and exits 2.

Partial policy revisions preserve omitted limits. Explicit broadening still
requires its recorded owner decision. A task can declare `review_required: true`;
acceptance requires a current approve verdict, and any adverse or unavailable
verdict blocks acceptance. Validators must return their adapter's exact declared
criterion IDs; these are distinct from job requirement IDs. The integrated gate
also requires every job requirement to be covered by a stage.

Waiver decisions name explicit `requirement_ids`. An outcome must match both
that record and the job's waivable policy. Settings apply observations bind the
actual backup and before-edit bytes and cite the adopted owner decision scoped
as `settings-change:<change-id>`. Adoption history remains immutable. Host actor
and filesystem enforcement are integration prerequisites, not claims supplied
by a worker or established by hashing its assertions.
