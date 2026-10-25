# Study contract

Record shapes and interfaces that `scripts/study.py` enforces. Every record is
canonical JSON; hashes are SHA-256 of canonical bytes.

## Files

| Path under `ROOT/<study>/focus-group/` | Contents | Mutability |
| --- | --- | --- |
| `plans/<revision>.json` | `{schema_version, plan}`; `revision` is the hash of `plan` | immutable |
| `assessments/<revision>.json` | latest catalog, diversity, independence, capability and mode assessment | replaced on re-plan |
| `approvals/<revision>/<nnnn>.json` | message reference, verbatim statement, source path and hash, approved scope and lifetime ceiling, predecessor hash | append-only |
| `current.json` | current revision and earlier revisions in order | replaced |
| `ledger.json` | charged pools, per-slot attempts, admitted requests and their state, newest catalog observation verdict | replaced under lock |
| `accepted/*.json` | coordinator-accepted participant results with bindings | immutable |
| `carry/<revision>.json` | explicit carry-forward mapping into a revision | immutable |

The generic job in `ROOT/<study>/job.json` keeps briefs, attempts, handles and
acceptance receipts. Workers write only `ROOT/<study>/artifacts/tasks/<task-id>/`.

## Plan

The draft fields are `study_id`, `audience`, `decision`, `target`
(`kind` url|pack, `url`, `environment` fixture|staging|live), `mode`
(combined|capture-only), `journeys` (`id`, `goal`, `permitted_actions`,
`excluded_actions`), `exclusions`, `journey_context` (`class`
fresh-anonymous|preauthenticated-test, `reference`, required for a preauthenticated
test context; defaults to fresh-anonymous), `personas` (`id`, `label`, `goal`,
`priorities`, `experience`, `constraints`, `invented: true`), `participant_models`,
`analysis` and `review` targets (`providerInstanceId`, `model`, `options`, optional
explicit `runtimeMode`),
`capture_profile` (`label`, `viewport`, `extra_views`), `prompts`
(`first_impression`, `journey`), `stimulus` (`files` with absolute `path`, `name`,
`sha256`; `coordinator_inspected`; optional `manifest_sha256` and `provenance`),
`sharing`, `limits` and `coverage_policy`. Every field is material-bearing: any
change is a new revision.

Target options follow the catalog's declared option type. A `select` option takes
one advertised string ID; a select with no, empty or malformed choices cannot be
requested (`option_domain_unavailable`). A `boolean` option takes JSON `true` or
`false`. Any other type is refused.

A cell ID is `<persona-id>--<target-key>`, where the target key hashes provider,
model and options, plus `runtimeMode` when explicitly declared. Omitting the mode
preserves historical cell keys. Modes remain exact in admission, job targets,
brief selection, pilot/recovery requests and report requests; changing only the mode
requires a new reviewed and approved revision. Different modes of one model do not
satisfy the two distinct model ID requirement. Observed identity reports only what
the host supplied; a requested mode never fills an unreported observation. The first
cell of each target is its pilot; pilots are normal cells, not extra tasks.

## Task arithmetic

With `C` cells, combined mode has `2C` participant first attempts and capture-only
has `C`. Analysis and review add one each. The maximum adds the three repair pools.
Every charged admission counts toward the study across all revisions, so a
revision's `ceiling` is the tasks already charged, plus the first attempts this
revision still needs, plus the unspent repair pools. Charging inside the revision
leaves its ceiling unchanged; charges made under another revision raise it.

## Approval

The statement must be exactly the helper's `approval_instruction`
(`Approve focus-group revision <12 hex> (ceiling <N> tasks)`). The saved owner
source must be a single-answer record: one nonblank line holding exactly the
instruction, alone or after a `Selected option:`, `Answer:` or `Reply:` label.
A different or empty labelled answer, a rejection, negation, quotation or qualified
mention is refused as not affirmative. Any other content is refused as ambiguous: a
question, an option list, a second answer, a condition or a cancellation. The
helper does not decide which part of a longer transcript is the owner's authority;
it holds the approval instead. The record keeps the source path, its SHA-256 and the
message reference. This checks that the saved source is consistent; it cannot prove
that the answer came from the native picker.

Approvals are append-only. The latest record is in force and authorises at most its
recorded lifetime `max_tasks`. If the revision's ceiling later exceeds it, for
example after work charged under another revision, the approval is `insufficient`:
`run`, `resume` and `admit` refuse until the owner approves an amendment that names
the new ceiling. Earlier records and charged counters are never changed.

### Explicit bounded delegation

`python3 PKG/scripts/authority.py grant|status|revoke|approve-delegated|revision-inputs
--state-root ROOT --study ID [--input FILE]` provides a separate explicit route.
It never interprets contextual prose as a literal per-revision approval.
Only a genuinely owner-authorized coordinator records a grant. Keep the complete
owner context, verbatim granting quote, message reference, and exact external
source/native-observation descriptors (`path`, `sha256`, `bytes`). Native message
IDs and creationSource must occur in that observation. These are retained host
provenance under the existing source trust boundary, not human authentication by
hash or cryptography.

The grant input names `id`, `owner` (`id`, `message_ref`, `context`, `quote`,
`source`, `native_observation`, `native_messages`), `delegate` (`id`, exact generic
`caller`), `package` (dependency_key, installation_id, package_digest, bundle_digest),
`review` (exact owner-selected independent target/options/runtimeMode), `expires_at`
and `constraints` (max_tasks, max_concurrency, max_attempts_per_slot,
max_repair_cycles, deadline, modes and product_writes:false). The recorded grant
freezes panel, sharing, material and protocol; only its explicitly permitted mode
and bounded limits may vary. No model is hardcoded. Grant and revocation chains in
`authority/grants/` and `authority/revocations/` are append-only. Status retains all
history, including revoked authority.

`approve-delegated` takes revision, grant_id and exact delegate. It requires the
real accepted independent planning receipt with observed identity/options and
current scope. It appends a visibly derived approval retaining full original owner
provenance, grant and receipt references. `revision-inputs` takes revision, kind and
new_plan; it freezes an exact candidate/generation proof and returns generic
decision and plan-revision inputs. The decision source under
`ROOT/delegated-decisions/<study>/` is explicitly derived. Never substitute it for
the native owner's answer. Apply only through the existing public decision and
guarded plan-revision route. It records no generic job mutation itself.
Owner `amendments` retain each later genuine source/context/quote, including a
changed reviewer choice. Grant `review_source` names that exact original or amended
source; every amendment is reopened at use. No later source retrospectively relabels
old reviews. If charges under another revision raise this revision's ceiling, a
fresh bounded delegated amendment is required before applying or executing it.

The pinned adapter requires the typed authorization marker and all four generic
transaction guard operations; stripping either fails closed. Application checks
the original canonical candidate, actual normalized authored fields, current job
generation, study revision, package/adoption identity, native source, grant,
revocation, accepted review, charge/attempt/concurrency bounds and expiry under
job.lock then study.lock, holding both through persistence. Direct approvals keep
their exact literal grammar. A genuine new direct approval can replace delegated
mode through the guarded route; the guard policy remains enabled.

Adopt a supported reviewed package while the job is still direct/unmarked, before
enabling delegation. Afterwards unguarded upgrade-package refuses before adoption,
backup or registry changes. Later recovery revisions use guarded job_cli. A future
guarded upgrade needs separate reviewed scope. Preparation/admission and acceptance
recheck live authority; revoke during a final validator prevents accepted success.
No local lock can atomically bind a remote host launch: the coordinator rechecks
immediately before dispatch and retains/reconciles any already accepted or uncertain
execution and its charges. Raw ingestion, cancellation and reconciliation remain
usable after revocation.

## Pre-dispatch observation

### Exact procedural context

The optional plan field `procedural_context` is a list of exact per-participant
target declarations. Each entry has `target` (full provider/model/options/runtime
choice), `harness` (the actual catalog driverKind), absolute regular-file `path`,
full `sha256`, `purpose`, `mandatory_instruction` (`path`, full `sha256`, verbatim
`quote`), `applicability`, `sharing` and `inspection`. Sharing is exactly the target
provider, consumer `participant`, material_class `procedural-instruction`.
Inspection records `inspector`, UTC `reviewed_at`, the full instruction `sha256`,
mandatory `source_sha256` and verdict `cleared`. These are explicit coordinator
observations of the complete bytes; the existing independent planning receipt
must also cover the declaration and both exact review paths. The plan-review CLI
adds those paths to its explicit evidence index. Callers of the shared prepare
API must supply them explicitly; missing review paths block readiness.

No procedural text is added to product stimulus. Full instruction bytes and
participant-visible purpose/applicability are screened for secrets, other personas
or responses, preferred findings, code and backlog. The mandatory source is
provenance, not a participant read grant. No glob, directory, symlink, traversal,
sibling or nested-reference permission is created. Missing, changed, unreviewed,
conflicting, contaminated or harness-mismatched input fails before an admission
charge or catalog ledger update. The fresh actual target catalog must still name
the declared harness. Exact sharing and applicability are part of plan approval.

Only matching cells include `procedural_context_sha256` in their input/attempt
bindings. Cells without applicable entries retain their previous binding shape
and normal carry eligibility. The generated document has a separate Procedural
context section; its immutable metadata and outer `context_files` bind just that
target's auxiliary path/hash list after the normal product files. The product
viewport and report-stimulus inputs stay unchanged.

Trace inspection uses the execution's historical plan, generated metadata and
immutable outer scope. Exact auxiliary reads are classified separately as
procedural reads; writes and broader paths are refused. For procedural execution
the coordinator reports the actual `trace.harness`; a mismatch contaminates and
an absent observation leaves compliance unverified. Shell opacity, missing traces
and image-delivery uncertainty retain their existing meanings. Later clean traces
or expanded scope never clear historical contamination or refund old charges.

`check-run`, `admit` and `job-spec` require `--capabilities` with a fresh host
observation:

```json
{"schema_version": 1, "observed_at": "2029-06-01T00:00:00Z", "source": "...",
 "response": {"providers": []}, "observations": []}
```

`response` is a newly saved `orchestrator_capabilities` response and
`observations` are schema facts read at the same time. An observation older than
15 minutes, dated in the future, or older than the newest recorded one is refused.
The helper rechecks every exact model, option and provider, and reviewer
independence. It records the verdict and refuses dispatch (`readiness_stale`) while
the latest observation fails. A journey on a model whose observation shows no
browser tools or isolation is refused as a gap. The hard-stop decision also comes
from this observation.

## Admission

`admit` charges one launch. Attempts are counted per slot (`cell:stage`, or
`analysis:analysis`, `review:review`) and that slot's input hash. The first
execution uses the first-attempt allowance; every later execution with the same
inputs, from any revision, draws from that role's repair pool. A slot whose inputs
changed, such as an edited persona or a new reviewer target, starts a fresh first
attempt. A duplicate request ID is idempotent only while its request is open and
names the approved current revision. A request admitted under a superseded revision
is refused as `superseded_revision`, and a terminal or cancelling one as
`request_closed`; neither is a launch permission and neither charges. Reconcile
them from `task_status`. `release` marks a request terminal.

A participant slot that already has an accepted result in this revision, or one
carried in by the written mapping, is refused as `slot_already_filled`. Once the study
has a job, a new request for any slot whose earlier request is still open or cancelling
is refused as `slot_in_flight`, uncharged, after the pilot, job-slot and concurrency
checks: never start a second attempt beside one that has not settled. A slot that
an earlier revision's eligible result could fill is held as `carry_unresolved`
until `carry --write` records the revision's mapping.

## Accepted results and carry-forward

A participant result binds stage, cell, persona hash, first-impression prompt hash,
pack hash, capture-profile hash and requested target. The pack hash covers the
files, `manifest_sha256` and `provenance`. A journey also binds the journey prompt,
journey definitions, action scope, journey target (kind, URL, environment), the
plan's journey context, and its accepted first impression as predecessor. It
records the browser context it actually ran in (`class`, `reference`,
`binding_sha256`), which must satisfy the plan's context. A URL, environment or
context change therefore stales journeys but keeps first impressions, which judged
the same hash-bound images. Host-observed identity is stored separately; only
`verified` identity can carry.

A journey's predecessor is the first impression accepted in its own revision or
carried into it by the revision's written, revalidated `carry` mapping. The record
references the original revision, record and result hash; the raw result is never
copied or rewritten.

`carry` recomputes these bindings under the target revision and reopens every
accepted artifact. An entry carries only when the artifact is still the exact
hashed regular file inside its task scope, every binding is unchanged, identity is
verified, current analysis and review grants still allow its disclosure, and no
other result fills the slot. A result accepted in the target revision itself fills
its slot first. A journey also needs its exact predecessor record to be the slot's
effective first impression in the target revision: native, or carried by the same
mapping. A native predecessor's artifact is reopened with the same scope, regular-file
and SHA-256 checks; an unusable native result still occupies its slot but stales
every journey built on it. Otherwise the entry is stale with reasons; the accepted record is kept
unchanged. `check-run`, `admit`, `record-acceptance` and `job-spec` revalidate the
written mapping and refuse with `carry_invalid` once it no longer holds; plan a new
revision. A journey is never admitted on an unusable first impression
(`predecessor_unusable`). `record-acceptance` refuses a native result for a slot the written
mapping already fills, so each slot has one effective result in either command
order. Analysis and review results are
re-derived after any participant change. A capture-only revision stales journeys
and reports `combined_scope_complete: false`.

`validate-carry` checks the mapping's exact shape, each entry's fields, status and
provenance against the recomputed mapping, and the derived `filled_slots` and
`combined_scope_complete`. A subset is valid when it is closed: each carried
journey's first impression must be carried by the same mapping or accepted in the
target revision with a usable artifact (`predecessor_missing` otherwise). It returns the canonical
validated mapping and its hash.

## Downstream interfaces

Capture and pack validation (which populates `stimulus.manifest_sha256` and
`stimulus.provenance`), participant briefs, blinding checks, frozen first
impressions, context isolation and journey payloads are in
`PKG/references/evidence-contract.md`. `approve`, `check-run` and `admit` refuse a
pack that is not recorded `cleared` with exactly these files, provenance and
profile. `record-acceptance` is the participant ingestion boundary. It rescans and
validates the exact result bytes and the material they cite, quarantines suspect
material before any accepted record exists, and freezes or binds those bytes (see
Ingestion in the evidence contract). `job-spec` accepts only recorded, unchanged
generator briefs.

`scripts/lifecycle.py` (FG-3) adds, over the same records:

| Path under `ROOT/<study>/focus-group/` | Contents | Mutability |
| --- | --- | --- |
| `sessions/raw/<sha256>.bin` | every complete transport offered to `ingest`, byte for byte | create-exclusive |
| `sessions/<request>/<nnnn>.json` | that request's ingestion outcomes: code, category, transport hash, record | append-only, chained |
| `identity/<record-sha>.<evidence-sha>.json` | owner acceptance of one exact identity discrepancy and its evidence | immutable |

- **Pilot gates.** `admit` refuses a non-pilot cell until its model's pilot passed
  that stage (`pilot_pending`, `pilot_failed`, `journey_unavailable`). The charge
  and reservation of an open request are idempotent, but permission to start it is
  checked again. A duplicate of a request with a recorded host task returns
  `host_started: true` and is reconciled, never started again or held. A duplicate
  with no recorded host task, never prepared or prepared with a lost response, is
  admitted only while its pilot still passes. Otherwise it is refused under the
  pilot code, uncharged, keeping its ID, charge and reservation. `reconcile` then
  lists it under `launch_held`, not `dispatch_same_request`. `resume` marks its slot
  `held`. A fresh owner decision on the exact current evidence restores the pilot
  and the same ID, uncharged. A journey also needs
  its own current generator brief before admission (`journey_brief_missing`).
- **Identity.** `identity_verdict` keeps the requested target apart from what the
  host reported: `verified`, `mismatched`, `ambiguous` (an observed model the fresh
  catalog does not list for that provider) or `unreported`. `ingest` reads it from
  the job handle's recorded sources and never softens the shared rules' verdict.
  Accepted records keep `identity` and, from `ingest`, `identity_detail`, as history.
  Pilots, `progress`, `resume`, coverage, carry and the shared usable-record
  resolver use `identity_state`: the record's own request handle re-read under the
  shared sticky rules (a later `mismatched` source withdraws `verified`, nothing
  upgrades), or an owner decision on exactly the discrepancy evidence shown now.
  `identity_evidence` replays the recorded observations of that host task
  cumulatively through the shared `_record_identity`, as the handle accumulated
  them, so a reading the handle's per-source row has since replaced stays visible
  with its source. It keeps provider/model `associations` as reported (a missing
  field stays missing) and the shared canonical resolution (status provider; status,
  receipt or configuration model) as `canonical` now and `resolutions` over time. It
  never pairs fields that no source or resolution paired. A complete canonical
  identity that every reading agrees with is a `wrong-model` discrepancy; two or more
  different complete associations are `contradictory`, accepted only by an
  instruction naming every association and resolution, with nothing observed.
  Anything else is a hold (`identity_unreported` when the canonical identity lacks a
  field, shown in `missing`, or `identity_indefinite`). The decision is keyed by
  `discrepancy_sha256` (request, host task, request target, shared status,
  associations, resolutions, canonical identity), and its stored statement must equal
  the current instruction, which names the request. An equivalent repeat keeps it; a
  new association or another resolution, such as a different status provider,
  voids it, and the old quote no longer matches. With a `mismatched` job handle,
  `accept-identity` also returns `decision_input`. That is the same owner authority as the
  generic `identity-exception:task:<task-id>` decision bound to that one execution,
  so participant stage acceptance can take it as unverified evidence without
  relabelling the handle or clearing its blocker. Its ID and binding follow the
  handle's full observed identity, so an equivalent reading from another source
  needs a fresh one: the same owner source, statement and `message_ref` return the
  stored decision byte for byte and a new current `decision_input`; any other
  authority for that evidence is `immutable_record`. `decision_recorded` compares the
  exact ID, quote, source, hash, scope and binding. Once a job exists,
  `record-acceptance` refuses (`host_ingest_required`); only `ingest` accepts.
- **Lifecycle.** `reconcile` and `resume` read `job.json` once and never write it.
  A request owns its accepted handle and every conflicting host task the job
  retained for it (`host_conflicts`). It closes only when all are terminal, without
  pending child runs and not working (a conflict through its own shared
  `reconciled` record); a closed request whose owned work later disagrees is
  unresolved again and occupies concurrency. Concurrency counts each distinct
  unresolved owned host task once, and one reservation for a live request with no
  host task; admission and `resume` use the same count. An open duplicate with no
  recorded host task is rechecked against that count, less its own reservation
  once: a closed request's host task can reopen after it was admitted. While other
  owned work fills the limit it is refused `concurrency_limit`, uncharged, keeping
  its ID, charge and reservation; `reconcile` lists it under `launch_held` and
  `resume` marks its slot `held`. Once that work settles the same ID starts,
  uncharged. A task it already started stays owned and is reconciled and ingested,
  even above the limit, and is never cancelled for capacity. With a stop in force, a request with
  no immutable brief and no host task closes as `never-prepared`; a prepared one
  without a host task is listed under `rediscover`. `release` is refused once a job
  exists. Analysis and review requests stay unresolved until their own
  observations close them.
- **Journey slots and revisions.** `job-spec` gives the journey stage no stage
  dependency; each journey depends on its own cell's first impression through its
  brief, admission and acceptance. `journey-slots` returns the decision and
  plan-revision inputs that add briefed journey slots through the shared route.
  `job-revision` does the same for a newly approved study revision: stage
  contracts, authority, policy and each settled slot's target and brief. Until the
  job names the current revision, `check-run`, `admit`, `job-spec` and `resume`
  refuse with `job_revision_stale`, and admission holds a slot still carrying an
  earlier brief or target (`job_slot_stale`). Both reuse the owner's approval of
  the exact revision as the `plan:<id>` decision.

`job-spec` declares the analysis slot document-only with no document and the review
slot with no subject, so preparation refuses both until `report.py analysis-inputs`
and `report.py review-slot` bind them through the same route. Admission holds an
analysis slot whose inputs are unbound or stale and a bound review slot whose report
is not the current render. The study validator (`scripts/validate_study.py`),
synthesis, fidelity review and local export are in `PKG/references/report-contract.md`.
The host producer of catalog observations is not implemented here.
