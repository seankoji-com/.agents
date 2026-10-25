# Planning review runtime

`shared/planning_review.py` implements the S-PLANNING acceptance boundary. It
stores local evidence and returns host dispatch instructions. It never launches
models, asks model-selection questions or schedules work. The coordinator keeps
ownership of independent review of an implementation.

Run `python3 PKG/shared/planning_review_cli.py COMMAND --input FILE`, or
`t3-plugins planning-review COMMAND --input FILE`. Job operations also need
`--state-root ROOT --job ID`; `create` needs `--prefix PREFIX --agents-root ROOT`.
Successful commands return one JSON value and exit 0. Refusals exit 2 on stderr;
`check-draft` also uses exit 2 with a JSON diagnostic on stdout for invalid drafts.

## Draft diagnostics before completion

An active planning reviewer can check a saved draft before returning it, when its
brief permits these procedural reads. The checker reads the exact brief, its
declared inputs and assigned task artifacts. It never opens live job/subject
stores, charges a round, records a result or launches work:

```sh
python3 PKG/shared/planning_review_cli.py check-draft --input draft-input.json
```

`begin` puts the pinned helper descriptor and one-correction bound in
`resources.draft_check`; preparation binds them into the immutable brief.
The descriptor grants no new reads. Before capture, the coordinator must declare
the helper and any needed procedural reads in the permitted pre-review scope.
Keep the input frame as well as the draft in the assigned artifact directory.
The one-correction bound is procedural; this stateless checker cannot count
invocations. The reviewer verifies the helper's descriptor hash before running it.
At capture, include separately opened helper/source files in `evidence_paths`.
The assigned brief and own task-subtree input frames, drafts and diagnostics are
contract/outputs, not additional `inspected_paths`; their hash and artifact
bindings still apply. Do not use this distinction to hide separately read content.

`draft-input.json` contains `brief_file` (the absolute file under `briefs/`),
`brief_sha256` (the dispatch descriptor's byte hash) and `result_file` (a saved
draft under that task's `artifacts/tasks/<task-id>/` subtree). No caller, state
root or job argument is needed. The output has kind `planning-draft-diagnostic`,
`valid`, `errors`, completed `checks` and `deferred_checks`. Exit 0 means the
available draft checks passed, including a valid adverse assessment. Invalid
drafts exit 2. `acceptance` is always false.

The checker reuses strict transport, correlation, finding, coverage, actual-read,
artifact and available response-transition checks on copied data. Artifact reads
are capped at 16 MiB; ingestion still enforces its pinned limit. A legacy carry
whose proof lives only in retained rounds is explicitly deferred. Current pins,
job/subject freshness, host identity/options, fresh execution, authoritative
finding history and remaining budgets are not certified by this diagnostic.
Changing declared evidence makes a draft invalid; an unexpected read must remain
disclosed, never removed to satisfy validation.

Allow at most one draft correction cycle before terminal completion. Retain saved
drafts and diagnostics under the existing evidence scope; do not suppress findings.
If correction needs new evidence or authority, return the truthful assessment and
gap. Returned results remain immutable and counted. No post-terminal reviewer
follow-up, refund, automatic replacement or acceptance follows from draft checking.
Document-only/cold-read slots cannot use this planning checker.

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
  Recovery validates the immutable brief, original named slot, frozen selection,
  target/options/runtime, lineage, snapshot and pins. It never selects another
  candidate for an old request. Accounting recovery precedes the current sharing
  and capacity checks. If either now denies dispatch, `launch` raises (the CLI
  exits 2) without returning a brief, but keeps the recovered charge. Replaying
  that refusal does not charge again. Reconcile the original reservation through
  `unavailable` with correlated failure evidence before release or replacement; an error is not
  dispatch permission and does not imply that accounting stayed unchanged.
  First launch and replay share `path`, `sha256`, `target`, `task_id`,
  `request_id` and `mode`; other descriptor fields can differ. Replay requires
  current prepare authorization and pins, and refuses cancelled/discarded jobs.
- `host_event(store, caller, task_id, event)` records existing job lifecycle
  events. Host observations retain real task/thread IDs and requested versus
  observed identity. Uncertain launches have the existing original-plus-two retry
  bound and must reconcile under their original request before replacement.
  Events receive local receipt timestamps; caller-supplied `recorded_at` is refused.
- `unavailable(store, caller, task_id, failure)` settles a failed host call or a
  local prelaunch refusal. `failure.kind` must be `technical`, `capacity` or
  `permission`; `tool`, `call_id` and `receipt` must be nonempty, and `request_id`
  must match the original task. An attempt with owned handles requires its actual
  `host_task_id`; one without handles requires `prelaunch: true`.
  Unknown/active work must first reconcile through the host lifecycle. Pending,
  uncertain or blocked host work is refused, as is any retained execution history.
  Substantive, incomplete or adverse output cannot become technical unavailability.
  Terminal executor failure is a host failure, never a fabricated worker result.

  After an interrupted charge, first replay `launch` with the original `slot_id`
  and `request_id`. If charge recovery succeeds but current sharing or capacity
  refuses dispatch, retain a caller-supplied `call_id` correlation token for that
  actual local CLI invocation and its refusal receipt. For example, generate a
  unique token before the call and retain it alongside the real argv, request ID,
  actual stderr and exit code. The CLI neither accepts nor emits `call_id`; the
  helper only requires it to be nonempty and imposes no token format. It is not a
  host-issued call ID.
  With no host handle or pending/uncertain dispatch, settle the original prepared
  `task_id` using the public command:

  ```sh
  python3 PKG/shared/planning_review_cli.py unavailable --input refusal.json --state-root ROOT --job ID
  # Equivalent: t3-plugins planning-review unavailable --input refusal.json --state-root ROOT --job ID
  ```

  `refusal.json` has this shape. Copy the returned `create.caller` object unchanged
  and substitute the original task/request IDs and actual local refusal evidence:

  ```json
  {
    "caller": {
      "actor": "coordinator",
      "workflow": "<create.caller.workflow>",
      "installation_id": "<create.caller.installation_id>",
      "package_digest": "<create.caller.package_digest>"
    },
    "task_id": "<original prepared task_id>",
    "failure": {
      "kind": "permission",
      "tool": "planning-review launch",
      "call_id": "<caller-supplied token for the actual local launch invocation>",
      "request_id": "<original request_id>",
      "receipt": {"error": "<actual launch stderr>", "exit_code": 2},
      "prelaunch": true
    }
  }
  ```

  Use `capacity` for a capacity refusal. The receipt object above preserves the
  actual CLI error; the helper requires a nonempty receipt rather than this exact
  receipt schema. A local refusal is not a failed host call. Do not invent a
  `host-event` or `host_task_id`. This command records the original attempt's
  unavailability without dispatch, another charge or a changed target/brief/selection.
  It refuses an unreconciled missing charge. Subsequent `next` or `release` uses
  the existing rules; another dispatch still needs current sharing, capacity and
  explicit authorization. Settlement grants no new permission.
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

New subjects start with five substantive rounds. Existing subjects keep their
recorded limit and counters. Batch supported repairs before verification, following
the shared reviewer's convergence rule. Limits are ceilings, not target pass counts;
changed relevant inputs still require their applicable review. Before dispatch,
check the subject has testable acceptance, a feasible dependency order and a bounded evidence set. Supply
the current immutable brief's correlation fields, all coverage IDs and exact retained
finding keys; historical examples are not current result templates. Bind needed
job/ledger evidence through stable projections or explicit immutable copies.
Do not hash live records that review ingestion itself rewrites, or the receipt
being produced, as source inputs. Use compact status and narrow field extraction;
keep full history on disk, all required findings and coverage in the brief.
Mark the planned last assessment and the last
available round as final under `shared/agents/reviewer-standard.md`: only blocking
issues require repair; safe deferrals become repository issues. A finite technical allowance is
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
An already agreed rebuttal can be acknowledged by another fresh child of that
lineage on unchanged authored content. The original clearing execution and lineage
remain intact; the new evidence appends to history. Legacy clearing content is
recovered only from its retained complete pass. Missing proof, changed content,
unknown/wrong lineage or an open account cannot use this carry path.
Agreement provenance is retained for every severity, including minor/note accounts.
For legacy accounts without a clearing record, recover it only from the current
uninterrupted agreement history and its complete retained pass.
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
