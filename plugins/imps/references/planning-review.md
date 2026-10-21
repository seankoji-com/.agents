# IMPS review admission and receipts

Use `python3 PKG/cli.py plan-review ACTION --input FILE`. These helpers store and
validate evidence; the coordinator alone asks choices or calls T3. Apply
`PKG/shared/model-selection.md` before investigation/drafting and
`PKG/shared/planning-review.md` for the separate review job and bounded repairs.

1. `admit` takes `operation`, real `request_reference`, stable `output_name`,
   `invocation_id`, `selection` and separately retained `selection_sha256`.
   Choose judgement work for audit/investigation/blast-radius, workhorse for gate
   plans/recipes, with role corrections where needed. The source request plus named
   output fixes the logical subject; job replacement never resets its budget.
2. `continue` takes the returned `admission`, `invocation_id` and optional
   `event` (wake/repair/compaction/resume), `forward`, `retain`. Alias/cross-plugin
   forwarding consumes one record once, without another picker. Explicit pinned
   resume displays the frozen targets/options and requires `retain: true`; stop
   otherwise. Reconcile owned tasks first. New commands obtain fresh choices.
3. `prepare` takes `descriptor`, `inputs`, `metadata_file`. Keep metadata outside
   the target repository and worker scope, in coordinator-owned persistent state.
   Inputs are verbatim `requests`/`decisions` with real references and contiguous
   clause mappings, exact `requirements`, `repository_root`, `evidence_paths`, and
   optional `load_bearing_decisions`, `declared_paths`, `attachments`. Confidential
   classes need specific authority. The adapter binds all these plus the local
   rubric, actual/prospective authors and the producing choice.
4. Create a NEW separate `imps/planning-review` job using shared `create` with the
   returned snapshot and scope, then begin/launch/host-event/result/finish through
   the shared helper. The pinned imps manifest owns permitted output types and
   reviewer. Retain real host identities/options and handles. Do not fabricate a
   direct child, reclassify an adverse verdict or recursively review helper checks.
5. `attach` takes `descriptor`, `metadata_file`, `receipt` (actual finish file).
   It validates before storing. Add returned `metadata` as descriptor's
   `planning_review`. `validate` dereferences it and the real planning receipt.

Descriptors contain `admission`, `kind` and:

- `initial-plan`: native major-version-2 `plan`, and `stages` with distinct `id`,
  explicit `actions` and `output_type`. Declare every stage, including integration.
  Review if any write, multiple stages or a synthesis/recommendation/strategy output.
- `synthesis`: pinned `document`, exact `requirements`, optional producing `job_file`.
  For a job, use that job file so all actual and superseded author executions and
  their producing selections/briefs/options are bound. Missing attachment authorship
  remains unknown. Default review covers audit, investigation and blast-radius conclusions,
  including zero/no-change. Literal lookups use a plain single-stage read-only run
  without synthesizing a diagnosis or recommendation.
- `verification-recipe`: pinned facts JSON as `document`, exact `requirements`.
  The adapter also binds the two scaffold templates. Scaffold/check stays direct.

Public gate `init` accepts the native plan plus an `imps` context. The context has
`admission`; plan operations also have `stages` and `planning_review` when triggered.
Synthesis operations have `output_path`, fixed before work. Verification-init has
`recipe` (reviewed descriptor) and `recipe_file`. Initialization refuses missing or
stale required review before returning a run to execute. `prepare` returns the
content-addressed initial-plan document and full descriptor; use that descriptor
for the separate review job and attachment. Initial receipt bytes remain historical
proof of the pre-execution gate after planned source edits; final code/evidence
still needs verification at the changed snapshot. For a whole job, bind the authored `job_contract` projection returned by the shared
adapter in `imps_initial_plan`, and retain `imps_admission` beside the producing
selection. Job creation, preparation and direct-stage admission check that plan
before any executor starts. Every job stage must be declared. An owner-bound
`plan-revision` with changed authored semantics supplies a fresh `imps_initial_plan`;
the adapter stores its descriptor/check in one stage's `resources.imps_initial_review`,
using the existing core resource contract. Keep each revision's metadata at a distinct
path so the original producing reference remains intact. Target-only changes
retain the original producing review; changed authored stage semantics reopen it.

The original contract,
selection and persistent subject reference are retained in the run's notes.

Before returning synthesis, submit the reviewed descriptor through `finalize
--run-id RUN --input FILE`. `validate`, `report` and the installed stage/final
validator require this actual current receipt in addition to the unchanged core
requirements/code/persona gate. Finalization is no action authority. Legacy gate
runs without admission are `legacy-unreviewed`; use the pinned old installation to
read historical completion, never import a boolean as current acceptance.

Before each authored launch/drive/cleanup, `recipe-ready` takes `descriptor` and
`recipe_file`. It checks the receipt, generated instructions and executable fields against
reviewed facts/templates. Stamping accepts only the recipe bound to that run. It returns admission only; it runs no command. Run execution still
needs the owner's action authority and normal snapshots/evidence. Recipe stamping
adds runtime proof and retains the separate planning evidence. Changed executable
steps reopen review. Deterministic scaffold/check adds no model or review of itself.

Report actual modes, selected panel/substitutions, rounds, material refinements,
fixed/rejected/deferred findings, unverified coverage and next action. Keep plan
review, core evidence, code/persona review and live acceptance separate. Local host
observations are transcribed evidence, not cryptographic proof of model adherence.
