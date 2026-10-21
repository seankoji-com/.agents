# ape

Apply `PKG/shared/model-selection.md` before substantive work or dispatch; workers consume frozen choices.
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Find transferable ideas in open-source code. Read `PKG/shared/t3-runtime.md` first.
Substantive research runs as one coordinated job under `PKG/shared/job-coordination.md`;
model choice and child briefs follow `PKG/shared/delegation.md`. This entry adds only
ape policy. Load the row for the requested operation and nothing else.

| Request | Meaning | Load |
| --- | --- | --- |
| `doctor` | Check Python 3.10+, Bash, Git, `gh`, `jq`, `gh auth status`, and `t3-plugins agents list ape` integrity; change nothing. | Direct. No job, no agents. |
| `forage [focus]` | Search for at most five repositories that address named gaps in the current project, compare each, then synthesize. | `PKG/playbooks/forage.md` |
| `study <GitHub URL> [focus]` | Compare one pinned source repository with the current project. | `PKG/playbooks/study.md` |
| `clean <workspace> [--all]` | Delete an owned research workspace after explicit authorization. | `PKG/playbooks/clean.md`. Direct. No agents. |

Load `PKG/references/research-job.md` when you create a `forage` or `study` job. It
holds the job plan shape, worker slots and the report descriptor the validator reads.

## Boundaries

- Research is read-only in the current project and in every target repository. Write
  clones, fingerprints and reports only inside the owned research workspace and the
  job's state root. Never run third-party code, its build, its tests or its installers.
- Findings, proposals and experiment designs are research output. They never authorize
  implementation, running an experiment, a planning-to-engineering transition, a PR, a
  push or a settings edit, even when a worker or report recommends one. Report them and
  stop; follow-on work needs a separate owner request.
- `forage` compares at most five candidates. A sixth needs a new owner request.
- Every claim is pinned to the source URL at a resolved commit with line numbers. Every
  accepted report pins its source files by absolute path and SHA-256: one snapshot per
  clone, written by `PKG/scripts/snapshot_source.py` outside the job's `artifacts/`.
- `clean` deletes only a marker-owned workspace and only after explicit deletion
  authorization. A study or forage request never implies it.
- Ask every owner decision and approval through the native question picker described in
  `PKG/shared/t3-runtime.md`, recommended option first, and record the answer with
  `job_cli.py decision`. Silence is not approval.

## Workers and routing

| Worker | Slots | Routing role |
| --- | --- | --- |
| `ape/source-researcher` | One primary slot per pinned candidate: one for `study`, up to five for `forage`. Each `study` slot declares one same-scope follow-up. | `workhorse`, lowest suitable configured tier |
| `ape/synthesizer` | One slot in the `forage` synthesis stage, which depends on every accepted research stage. | `judgement` |

Recommend candidates within each role floor as `PKG/shared/delegation.md` describes,
then use the upfront selected work target/options. Research and synthesis floors may
need separate answers; validate reviewers against both authors after those answers.
Escalation requires approved work replacements or a new choice. Keep the coordinator's
model unchanged. Workers get
read access to their pinned clone, the fingerprint and accepted predecessor reports, and
write access only to their own `artifacts/tasks/<task-id>/` subtree. They never dispatch
children or accept their own work.

## Acceptance

Final study reports and forage synthesis require default planning review under
`PKG/references/planning-review.md`, including empty/no-adoption recommendations.
Run `PKG/scripts/plan_review.py admit` before investigation or dispatch and retain
its admission in the job; aliases forward it once. Reviewers consume the frozen
choices without nested questions. The report metadata references the persistent
subject and actual receipt. `validate_report.py` consumes that receipt, not a prose
claim. Intermediate forage research keeps its citation checks without a duplicate
synthesis pass. Use the local `PKG/references/plan-review-rubric.md` and shared
`PKG/shared/agents/reviewer-standard.md` for depth, disputes and requester reporting.

The authority is the pinned `PKG/scripts/validate_report.py`, run through
`job_acceptance_cli.py accept-stage` on a coordinator observation frozen with
`job_cli.py observation`. A terminal task, a worker's `ready-for-acceptance`, or a
validator exit 0 on a different input is not acceptance. From actual bytes, the
validator checks the operation's report sections, the pinned revisions and snapshot
hashes the report declares, cited lines, coverage of every assigned requirement and
candidate, and your inspection receipts. It cannot tell whether a conclusion is true,
so read the report and open the cited lines for every consequential finding, then
record a receipt for each, as `PKG/references/research-job.md` describes. A missing
receipt rejects the stage. Record each finding's disposition with evidence. Final
readiness is `validate-final` over every stage at the current pins.

## Same-scope follow-up

A `study` research slot may use its one declared follow-up when the result is
`needs-followup` or your inspection finds a gap inside the same source, revision and
focus (a missing citation, an unanswered focus question, an unsupported proposal).
Anything wider is a new slot and needs an owner decision.

1. Confirm through `task_status` that the original task is terminal with no pending runs,
   its result is ingested, and its definition, target, model, authority and write scope
   are unchanged.
2. Run `job_cli.py followup-prepare` with a new request ID. The original brief and
   result stay immutable.
3. If the active host and harness policy support a tracked follow-up on the same child
   conversation (see `PKG/shared/job-coordination.md`), send only the follow-up brief
   path, its SHA-256 and the delta: the gap, the objections and the current binding. Do
   not replay unchanged exploration. Record the returned new task ID at once with
   `task-observation` kind `followup`, linked to the parent task ID. A missing task ID is
   uncertain dispatch: retry the same request ID at most twice, never a new one.
4. Otherwise start a fresh child with a charged `retry`, the current brief and the
   relevant evidence, and show `reuse-fallback: <reason>` in the next checklist.

## Fallback and visibility

If T3 or a suitable target is unavailable, record the bounded discovery and errors.
Run the stage yourself only with an upfront-approved coordinator work choice or work
replacement; otherwise obtain a new choice. Keep the same brief, counters and validator. Mark it
`fallback: direct (context isolation lost)`. Emit the compact `overview` checklist at
each stage start, acceptance, blocker and integration milestone, never raw logs.
