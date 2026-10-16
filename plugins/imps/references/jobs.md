# imps whole jobs

`PKG/shared/job-coordination.md` defines the generic protocol: planning, dispatch,
lifecycle, acceptance, repair, fallback, visibility and approvals. This file adds
only imps policy. `JOBS` is the jobs state root, `$XDG_STATE_HOME/t3-plugins/jobs`
unless you pass `--state-root`. `GATES` is a coordinator-private directory for stage
gate runs, outside the repository and outside every job directory. Use absolute
paths for both.
Run job helpers from the pinned package: `python3 PKG/shared/job_cli.py COMMAND
--state-root JOBS --job JOB --input FILE`. Your `caller` is
`{"actor": "coordinator", "installation_id", "workflow": "imps/<operation>",
"package_digest"}`, copied from the installed package's `install-manifest.json`
receipt, which sits beside this plugin's entry.

## When to create a job

Whole-stage delegation is the default for substantive work: `run` with more than
one stage, `issues`, `checklist`, `discussion` that leads to implementation,
`audit`, `blast-radius` and `prs`. A single bounded change may stay one direct gate
run under the entry's `run` procedure. doctor, status and verification-init never
create a job or launch an agent.

| Operation | Stages and worker slots |
| --- | --- |
| run | one `imps/stage-executor` slot per stage; `imps/investigator` for cited questions; `imps/reviewer` for required review |
| issues | one stage per dependency-ordered issue group, each with executor and reviewer slots |
| checklist | executor verification slots over the claims; reviewer only when requested |
| discussion | `imps/investigator` source stage, then the `run` shape if implementation is authorized |
| audit | one `imps/auditor` slot per dimension group; reviewer slots refute blockers and majors |
| blast-radius | one read-only `imps/investigator` stage |
| prs | babysitter workers, through the pinned babysitter entry |

## Plan

1. Refine the brief with `PKG/references/brief-probes.md`. Keep requirement IDs
   stable and constraints verbatim. Record action authorization separately.
2. For each engineering stage, create its gate run yourself, so the run has parent
   ownership: `python3 PKG/cli.py init --state-root GATES/<stage-id> --input PLAN`
   with `parent_thread_id` set to your thread. Record each run ID.
3. Write a final plan file outside every worker scope:
   `{"state_root": GATES, "package_root": <pinned imps package>, "required_stages":
   [...], "stages": [{"id", "state_subdir": "<stage-id>", "run_id", "stage_sha256":
   <SHA-256 of PKG/scripts/validate_stage.py>}]}`. List every stage gate once.
4. Create the job with `create --prefix PREFIX --agents-root AGENTS`. Declare
   `{"key": "imps", "plugin": "imps"}` and every other dependency, such as
   babysitter for `prs`. Each engineering stage sets `validator_dependency: "imps"`,
   `validator_contract: {"state_root": "GATES/<stage-id>", "run_id"}` and
   `resources.gate` with the same pair. Declare the final integration stage now:
   it depends on every stage, covers every job requirement, runs `direct` and binds
   `validator_contract: {"final_plan": <the plan object>}`.
5. With `--personas`, pin each perspective before review: its ID, full text from
   `PKG/references/personas.md` and SHA-256 go into the stage's
   `resources.perspectives` and the gate plan's `policy.review.perspectives`.
   Record reviews against that pinned text; never re-read the file to record them.

Changing a gate run, contract or criterion after creation is a `plan-revision`
that needs a matching owner `decision`.

## Dispatch and verification slots

Dispatch only as the shared protocol says: `prepare`, `delegate_task`, then
`task-observation` with the returned handle. Workers never dispatch.

A stage-executor slot whose brief carries `resources.gate` is that stage's declared
verification slot. It may run the pinned helper against `GATES/<stage-id>` and may
write only that gate subtree and `artifacts/tasks/<task-id>/`. It calls `snapshot`
before each check, runs the exact approved argv and cwd, keeps logs and exit codes,
and submits with that original binding.

If the worker reports that it cannot access or execute the gate, its diagnostics
are informational. Record the fallback by adding `"verification":
"coordinator-fallback"` and the reason to the stage's gate descriptor. Then run
the authoritative checks yourself, taking a new `snapshot` before each one. Never
certify earlier tests retroactively or broaden permissions to make a probe pass.

For review, ingest the reviewer's result, then submit the gate's `child` and
`review` with the binding captured before that review was dispatched. Report every
finding with severity; as a separate step, set the verdict. Record each finding's
fixed, rejected or deferred disposition with `finding-disposition`.

## Acceptance

A terminal task is not an accepted stage. The stage gate `validate` is the
authority; the adapter runs it and cannot replace it.

1. Ingest each result with `result`. Dispose every finding.
2. Freeze the gate descriptor `{"state_root": "GATES/<stage-id>", "run_id"}` with
   `observation`. Its returned path is the validator input.
3. Run `python3 PKG/shared/job_acceptance_cli.py accept-stage --state-root JOBS
   --job JOB --input FILE` with `{caller, stage_id, revision, input_file,
   validator_argv: [PKG/scripts/validate_stage.py, "--state-root",
   "GATES/<stage-id>", "--run-id", RUN]}`. Exit 0 accepts; 1 rejects.

Final readiness uses a new final gate. Freeze `{"state_root": GATES, "final_plan":
PLAN}` and accept the final stage with argv `[PKG/scripts/validate_stage.py,
"--state-root", GATES, "--final-plan", PLAN]`. Before handoff, run `validate-final`
for fresh acceptance at the integrated snapshot. A failure reopens the responsible
stage through `retry` within its remaining cycles and stales its dependents.
Exhausted budgets, undeclared work or out-of-scope fixes need an owner decision.

## prs

`prs` depends on babysitter. Declare it at job creation, then load the entry that
`t3-plugins --job JOBS/JOB/job.json path babysitter` prints. Never resolve it with
the plain `path` command during a job. Babysitter's own scope, validator and
communication rules apply unchanged.

## Resume, status and cancel

If the pinned package's state ceiling prevents a required plan revision, keep its
files and the entire job intact. A reviewed newer installed package may run the
explicit `upgrade-package` operation described in the imps user guide.
It verifies both package pins, requires the owner-bound revision and exact current
state hash, refuses unreconciled work, and retains an immutable pre-upgrade copy.
It changes no repair budgets or requirements. Acceptance is invalidated and must
be rerun with the newly pinned package. Ordinary commands still refuse an unpinned
executing package. Never patch an installed package or truncate job history.

- **Resume.** Run `t3-plugins --job JOBS/JOB/job.json path imps`. If it names a
  different entry than the one you loaded, load that one; a wrong package refuses
  writes and prints the pinned invocation. Read `overview`, reconcile each recorded
  handle with `task_status` and `task-observation`, then act. A missing reply never
  justifies recreating work.
- **Status.** Print `overview`. It is read-only and launches nothing.
- **Cancel.** Call `task_cancel` only for owned handles. Confirm each stop with
  `task_status` and record it with `task-observation`. Submit terminal gate
  `child` observations and gate `cancel` for each stage run, then job `cancel`.
  Artifacts stay. Uncertain stops stay blocked with their IDs.

Job metadata lives outside the gate runs. Runs without a job keep the entry's
legacy status, resume and cancel paths. Major-version-1 runs need the previous
installed package.

## Fallback and visibility

When T3 or a suitable target is unavailable, follow the shared fallback. The stage
keeps its gate run, counters and acceptance. Add `"execution": "direct-fallback"`
and the discovery record to its gate descriptor. Missing required independent
review stays a blocker. Show the `overview` checklist at stage start, acceptance,
blockers and integration. Route owner decisions through the native question picker
in `PKG/shared/t3-runtime.md`, then record them with `decision`.
