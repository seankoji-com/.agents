# imps for T3 Code

You are running **imps**: a workflow for bounded engineering work inside a T3 Code thread, on any provider. A small Python core owns run state and evidence rules. You supply judgment and use your native tools. Follow this file. Load another file only when a rule below names it.

## Locate the package

`PKG` is the directory containing this file. Run the core as `python3 PKG/cli.py <op> ...`; it finds the core in an installed package or a source checkout. Each call prints one JSON object. Check `ok` and the exit code:

| Exit | Meaning | Do |
| --- | --- | --- |
| 0 | success | continue |
| 2 | invalid input, schema or version | fix your input; never edit state files |
| 3 | ownership or stale generation | run `status`, refresh `generation`, retry once |
| 4 | prohibited by state or policy | read `error.message`; it names what is missing |
| 5 | environment or I/O | report it as unavailable |

Shell safety: never put task text, findings, JSON or paths inside a shell string. Write JSON to a file under the run's `scratch/` directory and pass `--input FILE`, with every argument passed separately.

State lives in `~/.local/state/t3-plugins/imps` unless you pass `--state-root`. If your sandbox cannot write there, pick a writable directory outside the repository, pass it on every call, and say so in the report.

## Operations

The operator names one operation: `doctor`, `run <task>`, `resume <run-id>`, `status <run-id>`, `cancel <run-id>` or `verification-init`.

**doctor.** Make no changes. Report: `python3 --version` (3.10 or later), `git --version`, whether the state root is writable, and whether the T3 tools respond. Call `orchestrator_capabilities` and list the providers that can run child tasks, plus any that are disabled, uninstalled or unauthenticated. Then list which operations are supported here. If the operator asks which providers are tested, load `PKG/references/compatibility.md`. Without T3 tools, delegated work and independent review are `unavailable`; direct work still runs.

**run <task>.**
1. Read the repository's instructions (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING*`) and `git status`. Preserve unrelated work.
2. Pick the playbook. For a bug, regression, failing check or wrong output, load `PKG/playbooks/bug-fix.md` and follow it. It covers the plan, the loop and the report. For a question that needs a cited answer and no code change, load `PKG/playbooks/investigation.md`. For other bounded changes, continue below.
3. Write the plan (schema: `PKG/core/schemas/plan.schema.json`). Give each requirement a stable ID, wording, and kind (`inspection`, `command`, `runtime` or `manual`). Copy constraints verbatim. Set `authorization.endstate` to the outcome the operator authorised (`local` unless they asked for a PR), and quote their words in `authorization.evidence`. Add `host.parent_thread_id` from `orchestrator_capabilities`. Add the repository's required checks as literal argv arrays.
4. Choose the mode. Use **direct** (the default) when you can make and verify the change yourself. Use **delegated** only when each task resolves a distinct unknown or produces an independently checkable output. If you choose delegated, load `PKG/references/delegation.md`.
5. Run `init --input plan.json` and note the `run_id`. Then run the loop.

**resume <run-id>.** Call `orchestrator_capabilities`, run `claim`, and record the capabilities response. Then run the loop. If `claim` exits 3 and the owner is a prior turn of this same thread, that turn has ended, because a thread runs one turn at a time. Run `recover --token <owner token from status> --confirmed-dead` and claim again. Never recover a claim held by a different thread.

**status <run-id>.** Run `status`, `validate` and `report`, then show the Markdown report. Change nothing.

**cancel <run-id>.** Claim, then record `transition` to `cancelling`. Follow the loop until `next` offers `transition` to `cancelled` or reports a block. Only a confirmed stop counts. If a stop is uncertain, the block names the exact task IDs.

**verification-init.** Load `PKG/references/verification-init.md` and follow it.

## The loop

Each turn: `claim` (keep the token) → `next` → do each action → `record` → `next` again, until no actions remain or you must wait. Then `release` before you end the turn. Every `record` passes `--run-id`, `--kind`, `--token`, `--expect-generation <current generation>`, `--parent-thread-id <this thread>` and `--input`. A `dispatch` or `integration` record carries the action's `id` as `action_id`; if a dispatch you already sent is refused as no longer permitted, record it again with the whole action as `action`. When an action has `args.snapshot` or `args.binding`, its record carries those values under the same names. If the tree changed in between, the record is refused and `next` asks again.

| Action | What you do | Record kind |
| --- | --- | --- |
| `discover` | call `orchestrator_capabilities` | `capabilities` (`{"response": ...}`) |
| `transition` | nothing; it is the next phase | `transition` (`{"to": ...}`) |
| `implement` | do the work yourself from `args.brief` | `result` (`{"task_id", "text"}`: a final message ending in the result block shown in the brief) |
| `dispatch` | call `host_call.tool` with exactly `host_call.arguments` | `dispatch` (`{"action_id", "response"}` or `{"action_id", "error"}`) |
| `query_task` | end your turn if nothing else is actionable; T3 wakes you when the child finishes. Call `task_status` only when you need the result now | `observation` (`{"response"}`) |
| `collect_result` | `t3_thread_read` the child thread's final message | `result` (`{"task_id", "text"}`) |
| `create_worktree` | run `args.argv` | `resource` (`action_id`, `kind: worktree`, `name`, `path`, `branch`, `task_id`); only a fresh worktree from this action is accepted |
| `integrate` | run `args.argv` and keep the log | `integration` (`{"action_id", "exit_code", "log"}`) |
| `commit` | commit the change (PR endstates publish commits only) | none; call `next` |
| `run_check` | run `args.argv` in `args.cwd` with your native foreground command tool and save the output to `args.log_path` | `check` (`name`, `argv`, `cwd`, `exit_code`, `log`, `snapshot`) |
| `accept` | gather evidence of `args.kind` at the current revision and save it under `args.evidence_dir` | `acceptance` (`requirement_id`, `status`, `kind`, `explanation`, `artifacts`, `snapshot`) |
| `repair` | nothing yet; next offers the repair work | `repair` (`stage`, `findings`) |
| `publish` | push and open the PR with native tools | `remote-receipt` |
| `confirm_remote` | run `args.argv` and read the real state | `remote-observation` (`kind`, `url`, `state`, `head_sha`) |
| `cancel_task` / `confirm_stop` | call the `host_call` | `cancel` / `observation` |
| `cleanup` | run `args.argv`; if it is null the resource is already gone, so run nothing | `cleanup` (`resource_id`, `exit_code`) |
| `block` | nothing | `block` (`{"blocker": args.blocker}`), then `release` and report |
| `report` | run `report` | none |

Several actions at once are independent and may run in parallel. Long processes you start (servers, watchers) are recorded as `resource` with `kind: process` and `pid`, so cleanup and cancellation reach them and nothing else.

## Rules

- **Delegation goes through T3 only.** Use `delegate_task`, `task_status` and `task_cancel`, matched by base name whatever prefix your harness adds. Never use native subagents (`Agent`, `Task`, `Workflow`), `codex exec`, `claude -p`, `opencode run` or any shell-launched provider. Never use `create_threads` or `t3_thread_launch` for child work. Never `t3_thread_send` to a child: a new round is a new `dispatch` from `next`. If a T3 tool is missing or errors, load `PKG/references/t3-adapter.md`.
- **Evidence over claims.** A child's summary, a `completed` status or your own confidence is not acceptance. Only `record` evidence counts, and `validate` decides readiness at the current revision. Any edit after evidence makes it stale. Re-verify; never re-label.
- **Labels stay distinct.** `unverified`, `failed`, `unavailable` and `waived` mean different things. Record a waiver (`record --kind waiver`) only when the operator explicitly asks, and quote them. A waiver covers only the evidence recorded before it; newer evidence for the same obligation needs a new waiver.
- **Adverse review is final for that revision.** Repair within the limit or stop. Never ask another reviewer for a second opinion.
- **Blocked is a complete answer.** When `next` reports a block, record it, release, and show the report's Blocked section: the reason, the task IDs, the `resume` command and the paste line. Finish independent work first; `next` keeps offering it.
- **Endstates need proof.** Report `completed` only when the core says so. For a PR, completion needs an observed PR at the verified head. If the operator authorised a PR, link it with `t3_thread_update` (action `link_pull_request`). T3 has no PR-watcher tools; observe the PR with `gh pr view` when you claim the outcome.
- **Finish with the report.** End every run turn by running `report` and showing the Markdown it writes, or its path if it is long. Do not restate it in different words.
