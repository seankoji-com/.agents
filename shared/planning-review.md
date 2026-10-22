# Planning review runtime

`shared/planning_review.py` implements the S-PLANNING acceptance boundary. It
stores local evidence and returns host dispatch instructions. It never launches
models, asks model-selection questions or schedules work. The coordinator keeps
ownership of independent review of an implementation.

Run `python3 PKG/shared/planning_review_cli.py COMMAND --input FILE`, or
`t3-plugins planning-review COMMAND --input FILE`. Job operations also need
`--state-root ROOT --job ID`; `create` needs `--prefix PREFIX --agents-root ROOT`.
Each command returns one JSON value and exits 0, or exits 2 with a refusal.

## Admission and snapshot

1. Collect the work/panel/replacement choices using `model_selection.freeze`.
   Freeze `scope_id` to `logical_output_id(request_reference, output_name)` and
   retain actual session identity/options separately from requested child options.
2. `capture(data)` binds `output_name`, `output_type`, `requirements`,
   `load_bearing_decisions`, verbatim `requests` and `decisions`, source
   `documents`, `rubrics`, renderer `templates`, `evidence_paths`,
   `declared_paths`, `authors` and optional `repository_head` information.
  With `repository_root`, capture reads the actual Git HEAD. Parent validation can
  request `report_head: true` to return the receipt alongside a fresh
  `head_observation`, without staling unchanged relevant paths. Author records may
  carry a host `driver_kind` for custom provider/model aliases, checked against
  frozen capabilities; an unrecorded author is explicitly `unknown`.
   Request/decision records contain a real `reference`, absolute file `path`,
   and contiguous character-range `clauses` mapping every character to a
   `requirement` or explicit `non_goal`. Their bytes are retained privately.
   File entries may be paths or `{path, data_class}` records. Confidential classes
   such as `private-settings` require specific recipient authority. `authors`
   include the coordinator, synthesizers and any contributor whose replacement
   prose was adopted; read-only critique alone adds no author.
3. `create(data, state_root, prefix, agents_root, environ=None)` accepts only a
   NEW job. Its data contains `job_id`, `installation_id`, `plugin`, `project_id`,
   `owner`, `invocation_id`, `scope_id`, `selection`, `snapshot`, and optional
   `data_classes`. It returns the job locator, `subject_file` and `caller`.
   It does not accept imported stages, tasks, history, purpose or policy.
   A verified pinned plugin manifest must declare `planning_review` under
   `planning-policy.schema.json`: purpose `planning-review`, permitted output
   types and a declared reviewer/judgement `worker_id`. The imps manifest supplies
   the first hook. Other adopter manifests add their own policy/worker in their
   implementation stage; this hook does not activate their public workflows.

The separate job has one planning stage. Existing thinking, factual, cold-read,
handoff, code-review and `review_required` stages keep their existing validators
and independence policy. They cannot be imported or waived into this runtime.

## Host lifecycle and acceptance

- `begin(store, caller, snapshot=None, requested_rereview=False)` reserves a
  content round. The first actual assessment charges it; technical failures do
  not. A repair binds a new snapshot and carries every prior finding. Requirements
  and output purpose cannot be weakened by a repair. Re-review of unchanged
  accepted content needs an explicit request.
- `next_candidate(job, slot_id, sharing=None)` computes the next authorised
  candidate. It exhausts cross-lineage children before same-lineage children
  within the frozen finite replacement set. `sharing` may revoke existing grants,
  only after `revoke-sharing` persists the actual source evidence; a supplied
  current list must match derived state. It cannot invent exclusions. Primary selection authorises ordinary
  repository/topic material for that invocation. Explicit stronger independent
  slots refuse degraded review.
- `revoke_sharing(store, caller, grants, source, source_file)` retains a real
  authority revocation with its verbatim answer/reference/hash and external source
  bytes. It names actual frozen grants, survives replacement jobs and cannot
  silently restore an old grant. A new genuine owner grant has its own producing
  source. Private-data exclusions cannot be manufactured by passing an empty list.
- `launch(store, caller, slot_id, request_id, sharing=None)` reserves one finite
  technical attempt and uses existing job `prepare` to write its immutable brief.
  It returns exact target/options, task/request IDs, mode and brief descriptor.
  The coordinator calls the host with that request ID. Re-presenting an unfinished
  request is idempotent; a prepared or uncertain request blocks replacement.
  Preparation commits before the subject is charged; a rejected preparation
  leaves the subject unchanged. If saving the charge is interrupted, no brief is
  returned. Re-present that same request to recover its charge exactly once
  before dispatch; replacement and release remain blocked meanwhile.
  First launch and replay share `path`, `sha256`, `target`, `task_id`,
  `request_id` and `mode`; other descriptor fields can differ. Replay requires
  current prepare authorization and pins, and refuses cancelled/discarded jobs.
- `host_event(store, caller, task_id, event)` records existing job lifecycle
  events. Host observations retain real task/thread IDs and requested versus
  observed identity. Uncertain launches have the existing original-plus-two retry
  bound and must reconcile under their original request before replacement.
  Events receive local receipt timestamps; caller-supplied `recorded_at` is refused.
- `unavailable(store, caller, task_id, failure)` requires correlated tool,
  `call_id`, `request_id`, actual `receipt`, and `host_task_id` when created.
  A no-handle failure needs `prelaunch: true`. It cannot reclassify substantive,
  incomplete or adverse output as technical unavailability. Terminal executor
  failure is recorded as a host failure, explicitly not a fabricated worker result.
- `ingest(store, caller, task_id, raw, completion_id)` uses the strict existing
  worker-result parser and the actual immutable brief, owned terminal execution,
  verified host identity, requested options and canonical lineage. Delegated
  results add `planning_review` under `planning-assessment.schema.json`: explicit
  coverage of every requirement and load-bearing decision, inspected paths and
  responses to retained findings. The CLI uses `result_file` for the raw transport.
  Valid findings from correlated partial objects survive as open objections.
  Complete disagreement is adverse; missing outcomes/envelope/coverage is
  incomplete. Neither permits availability shopping.
- `direct(store, caller, observation, sharing=None)` accepts only the distinct
  `planning-direct.schema.json` observation. Every required panel slot must have
  exhausted suitable permitted children and separately permitted self-review.
  The identity is the real coordinator/session identity, with actual or explicitly
  unknown `observed_options` and an `identity_reference`. There are no child
  identity fields. A combined self-review is one pass and a degraded panel, never
  several named model approvals.
- `finish_round(store, caller)` closes an adverse/incomplete round for repair, or
  returns `{reference, accepted}` for an accepted review. Readiness needs all
  named panel obligations (or the explicitly permitted combined self-review),
  complete supported coverage, no unresolved major/blocker and current evidence.
- `validate_receipt(reference, expected_snapshot=None)` is the parent-facing gate.
  It re-reads the authoritative subject, pinned job/manifest, producing selection,
  immutable brief/result or direct observation, host identities, owner sources and
  relevant files. A receipt boolean, parser pass or provenance check is insufficient.
  A later charged review round for the same full snapshot supersedes an earlier
  receipt immediately, including while another panel slot is pending. Starting a
  replacement round or stopping it for technical unavailability without a charged
  assessment does not supersede the earlier receipt.
  Executing acceptance code and schemas must match the pinned package bytes;
  a changed source helper cannot certify an older pin. Direct fallback must also
  meet every panel role's judgement floor in the actual coordinator context.
  The CLI action is `validate` with `{reference, expected_snapshot?}`.

All API mutations also accept `environ=None` for explicit XDG fixture isolation.
The CLI uses the process environment. Callers must pass the returned `caller` to
mutations. File descriptors contain `path`, SHA-256 and integer `bytes`.

## Findings, persistence and bounds

Authoritative state is
`$XDG_STATE_HOME/t3-plugins/review-subjects/PROJECT/LOGICAL-ID/review.json`
(default `~/.local/state`). The stable logical ID uses the source request reference
and named output, never a replaceable job or content digest. Existing no-symlink,
private-directory, process-lock and atomic-write primitives protect transactions.
One active job owns an output. Jobs/revisions, frozen bytes, technical attempts,
content rounds, findings, dispositions, owner decisions and receipts persist.
Adopter metadata stores `subject_file` plus the validated receipt descriptor.

The initial limit is three substantive rounds. A finite technical allowance is
frozen for the candidate chain and retained across replacement jobs. Existing
host idempotent retry bounds apply separately. `release` refuses live/uncertain or
unfinished substantive work; a technical-only stopped round can release without
charging content. It never erases counters or findings. `owner-decision` can
increase `round_limit` and/or `technical_limit` only with a scoped actual owner
answer/source file. No silent limit reset follows a new job or model selection.

Finding keys start with canonical lineage plus stable reviewer ID. A reused ID
with different content is retained as a separate open account, `lineage:id@<digest>`
(with a numeric suffix if needed), with a `finding-id-collision` history event on
both accounts. Responses, dispositions and owner decisions must use the exact key
from `prior_findings` or the receipt. Every finding has
severity, scenario, source evidence and `smallest_correction`. `disposition` can
record an evidenced rejection, open item or minor deferral with impact/owner/next
action. Rejected/deferred major/blocker findings remain adverse. A counted fresh
child of the original lineage can accept a rebuttal; main-context review cannot.
A changed source plan can be reviewed as an actual repair through the normal
fallback chain. A scoped `finding-decision` or explicitly labelled
`finding-waiver` needs genuine owner source evidence; requirements remain intact.

## Downstream integration and limits

Thinking must review discovery/spec/attachments with renderer and rubric before
handoff generation, then dereference this receipt in gate/list/resolve/render.
Ape reports, imps notes and recipe plans, tuneup proposals, elephant designs and
written Ralph/babysitter strategies must reference this subject and consume the
receipt through their domain validators. Their chooser triggers, legacy treatment,
owner acceptance, code/factual/cold-read gates and public-flow tests belong to the
later adopter stages. This runtime does not claim those integrations are complete.

Review evidence binds declared paths and any inspected path present in the frozen
pre-read set, including dirty/untracked bytes. Unexpected reads require a new
snapshot/review. Relevant file, request, decision, rubric, template and producing
selection changes invalidate acceptance. Unrelated files and HEAD movement alone
do not force review; the caller reports the observed HEAD separately. If relevant
paths cannot be bounded, the caller must provide the whole permitted snapshot.

Catalogs, suitability profiles, sharing grants, source-message references, actual
read lists and host observations are coordinator-transcribed local evidence.
They are not cryptographic proof of a remote execution, truthful prose, exhaustive
authorship or the semantic completeness of a clause mapping. Validators check
correlation, current bytes, declared coverage and policy. Deterministic fixtures
prove these checks, not live model adherence. A separately authorised conformance
run must observe exact host targets/options, reviewer depth and fallback behavior.

One combined self-review covers only uncovered required slots whose finite child
chains are exhausted and whose exact self-review grants pass authority, role and
data checks. Other slots retain their actual child passes. The receipt records
`covered_slot_ids`, per-slot `slot_modes` and one degraded panel. Missing, duplicate
or arbitrary coverage cannot pass. Report each blocker/major clearing mode and
lineage, including `fixed-by-self-review`, without erasing earlier adverse rounds.
