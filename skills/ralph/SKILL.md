---
name: ralph
description: "Implement a goal with fresh T3 tasks, evaluate with another lineage, repair blockers and track safe deferrals as repository issues before the selected delivery endpoint. Args: run [--max-attempts N] <goal> | resume <state-file> | status <state-file> | cancel <state-file> | doctor."
metadata:
  agents-bootstrap: "1"
  opencode/slash: "true"
  opencode/autoinvoke: "false"
---


Before substantive work, run only:

```sh
"$HOME/.local/bin/agents" start ralph
```

Read the pinned SKILL.md and manifest before work. Already pinned: do not resolve again. Bind returned `package_root=PKG`, `pin=PIN`, `package_prefix=PREFIX`, `registry_root=AGENTS_ROOT`, `interpreter=PYTHON`; run Python examples with that absolute interpreter. Helpers, playbooks and workers use that pin only. Read `PKG/shared/manifest-routing.md`. Worktree tests add `--source /absolute/worktree` before `start`. Missing/incompatible launcher: explicit self-install.

# Ralph for T3 Code

Apply `PKG/shared/upfront-agreement.md` at this public entry. Inspect context before
asking; direct controls stay prompt-free. Substantive work records the scoped
agreement; nested calls and unchanged continuations reuse its binding and budgets.

Apply `PKG/shared/model-selection.md` before substantive work or dispatch; workers consume frozen choices.
Use `PKG/shared/adopter-planning.md` and `PKG/references/adopter-review-rubric.md`
for public admission and receipt gates through `PKG/scripts/plan_review.py`.
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Implement, evaluate, and retry in T3 child tasks. Implementations and every review round
use fresh tracked tasks under the agreed finite model chains. Read
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
  Recommend exact work/reviewer chains and options from the live catalog in one scoped agreement, unless supplied.
- `resume <state-file>` reuses the unchanged agreement without another chooser, then reconciles the existing task. Retain the
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

Offer exactly Open PR, Tagged Version and Verified in Prod unless supplied.
Record the necessary scoped action authority upfront, including merge/release/deploy
when selected. Respect narrower instructions and repository/external approval gates. Cross-provider evaluation may receive only the
goal's approved material; ask if the repository's private-data boundary is unclear.
OpenCode tasks require explicit Full Access. If the parent is narrower, explain
the requirement before starting; never silently broaden the parent.

Finish only when a full-scope evaluation reports the goal achieved with no
undisposed feedback, the parent confirms the evidence is current, and the selected
endpoint has current evidence through `complete`. Source evaluation alone is
intermediate. Apply the shared final-round triage directive: safe minor/info
findings become repository issues through `triage`, retain their original evidence
and do not consume another implementation attempt. Blocker/major findings and
unmet goals still require repair. Output at most three sentences in the main
context after every returned review, then report deferred fixes and the build/test
lesson at handoff. A task's `completed` status alone is
never a success verdict. Report exhausted attempts, unavailable evaluation, denied
permissions and missing verification plainly. Do not substitute direct execution,
another scheduler, top-level threads, or a same-lineage review.
