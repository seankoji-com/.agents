# Ralph for T3 Code

Apply `PKG/shared/model-selection.md` before substantive work or dispatch; workers consume frozen choices.
Use `PKG/shared/adopter-planning.md` and `PKG/references/adopter-review-rubric.md`
for public admission and receipt gates through `PKG/scripts/plan_review.py`.
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Implement, evaluate, and retry in T3 child tasks. Implementations and full reviews
are fresh; delta re-reviews may continue the rejecting reviewer's thread. Read
`PKG/shared/t3-runtime.md` and `PKG/shared/delegation.md` once, then
`PKG/playbooks/loop.md`. Ralph requires a verified different evaluator lineage;
the shared contract's same-lineage fallback does not apply.

`PKG` is the directory containing this entry. Invoke the deterministic checkpoint
helper with `python3 PKG/cli.py OPERATION --state FILE`. It stores observations and
prints the next delegation arguments. It never starts models or schedules tasks.
Use JSON files with `--input FILE`; never interpolate goal text into shell code.

## Requests

- `<goal>` or `run <goal>` starts a run. `--max-attempts N` sets the number of
  implementation attempts, including the first, to a positive integer. Default: 20.
  Ask the user to choose both models from T3's live catalog for every new run.
- `resume <state-file>` asks retain-or-stop for the pinned pair/options, then reconciles the existing task before continuing. Retain the
  chosen pair, worktree, goal, feedback and limit. Never restart an active task.
  Resolved result/provider failures use the helper's `recover` operation with a
  recorded reason. Unverified identity cannot be waived through recovery.
- `status <state-file>` reads the checkpoint without dispatch; the agent separately
  reads T3 `task_status` for recorded task IDs.
- `cancel <state-file>` stops only this run's children, including pending runs.
  Cancellation is complete only after T3 confirms terminal status and no pending runs.
- `doctor` checks Python 3.10+, Git, live delegation/status/cancellation capability,
  and that at least two runnable, verified model lineages are available. Change nothing.
  The helper has no `doctor` operation: run `python3 --version` and `git --version`,
  then call T3 `orchestrator_capabilities`.

The default authority covers local edits, tests, commits, push of the task branch,
and opening a normal PR for code changes. Respect narrower user instructions and
repository rules. Merge, deployment, release, credential changes and messages to
others need separate authorization. Cross-provider evaluation may receive only the
goal's approved material; ask if the repository's private-data boundary is unclear.
OpenCode tasks require explicit Full Access. If the parent is narrower, explain
the requirement before starting; never silently broaden the parent.

Finish only when a full-scope evaluation reports the goal achieved with an empty
feedback list, the parent confirms the evidence is current, and the authorized PR outcome
is observed. Every feedback item causes another implementation attempt, regardless
of severity or a simultaneous success claim. A task's `completed` status alone is
never a success verdict. Report exhausted attempts, unavailable evaluation, denied
permissions and missing verification plainly. Do not substitute direct execution,
another scheduler, top-level threads, or a same-lineage review.
