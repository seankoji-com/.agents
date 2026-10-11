# Benchmark protocol (frozen)

Frozen on 2026-10-11, before any baseline run, for stage 1 of issue #15. Stage 5 runs
this protocol unchanged against the new imps. Any change after the first baseline run
makes the baseline stale, except for the single Task B amendment below authorised
by issue #15 §7.

## Stage 5 amendment: Task B behaviour gate (2026-10-11)

The upstream tests distinguish one identity design, rather than the reported bug.
Both old fixes use an admin-directory owner token and fail those design assertions.
The candidate Task B gate is `checks/task_b.py`, at SHA-256
`f00c365cff2081e264e76871392d35149db89c719d4d8817396d0751dd967508`.
The grader records a real worktree through the target core CLI and snapshots every
path in the worktree root and repository Git metadata, including the containing
`.git/worktrees` directory. It removes and recreates it, then simulates inode
reuse through os/native-os stat, descriptor, pathlib and directory-entry APIs. Real nanosecond timestamps,
device fields, files and Git operations remain intact. It requires both refusal of
replacement cleanup and an offered command for an untouched owned worktree.
Patches are installed before importing the target, including aliases and default
arguments captured at import time. The simulation covers these Python APIs only.
Inode reads made in subprocesses or native code (for example `stat`, `ls -i`, Git
index inspection or ctypes) remain a known gap. A passing result does not establish
safety for those designs; such a candidate requires separate evidence and cannot
be accepted solely from this grader.

Validation is recorded in `checks/task_b_validation.json`: the unfixed tree fails,
`d6bed53` and both old fixes pass. Old summaries retain the upstream test output as
`matches_upstream_design`, an informational field, and add `behaviour_grader`.
References below and in the frozen rubric to Task B's hidden-test gate are superseded
by this amendment. The upstream tests and full suite remain informational. The frozen summariser remains unchanged: after it runs, the executor renames
`hidden_tests` to `matches_upstream_design` and adds the separate behaviour result.
No worker prompt, execution setting, attempt rule, token parser, Task A check or rubric changes.

The first grader passed two inode-only mutants. Its correction came after the four
new workers launched. Those initial attempts are retained as informational and
cannot establish benchmark acceptance. Their confinement audits voided all four
slots. The issue permits one retry per voided slot and requires stale runs to be
repeated. The retries must use the repaired grader frozen before launch and a
scratch install from the final implementation commit. No attempt, audit finding or
process deviation is omitted from the report.

Review round 4 rejected the previous candidate: `InodeStat` exposed the real
inode through stat-result slices and negative indexes (M3), with filesystem-dependent
false passes. After the three planned repair rounds, the owner explicitly authorised
one additional repair round. The current candidate replaces the inode before any
sequence indexing or slicing, with regression cases for both. Review round 5 found
no blockers or majors and approved freezing this SHA within the documented scope.
It verified 22 inode-only mutants twice on Python 3.10, 3.12 and 3.13 (132 failures
as required), plus the red/green matrix. Minor m6 is deferred: the proxy is not a
real stat_result and copy/pickle/type-sensitive designs may fail; contrived count
or index calls can access real tuple values. These designs need separate evidence.
Minor m7 is fixed by recording this review in the amendment before retry launch.
Initial attempts remain diagnostic; stage acceptance awaits valid retries. The
subprocess/native-code gap remains unverified.

The benchmark compares two imps versions on two tasks: the **old** package (built from
`6e4cf82`, tag `bench/old-imps`) and the **new** package (built in stage 5 from the final
commit). It measures outcome, wallclock, parent-Opus tokens and delegation. It is a
parent-context measure, not a total-cost measure.

## Locations

| What | Where | Committed |
| --- | --- | --- |
| Protocol, rubric, checks, fixtures, tools | `bench/` | yes |
| Sanitised run summaries and outputs | `bench/runs/<version>/<slot>/` | yes |
| Private results directory | `~/t3-plugins-bench/` | no |
| Installed packages | `~/t3-plugins-bench/install/imps-<commit>/` (read-only) | no |
| Run workspaces | `~/t3-plugins-bench/ws/<workspace id>/` | no |
| Task B grader bundle | `~/t3-plugins-bench/private/task_b/test_resources_identity.py` | no; sha256 only |
| Raw transcripts and audit logs | `~/t3-plugins-bench/private/runs/<version>/<slot>/` | no; sha256 only |
| Version key for blind grading | `~/t3-plugins-bench/private/grading/` | no |

`bench/` is `export-ignore`, so none of it ships in the release archive.

## Packages

Each version is installed once with that commit's own installer into a scratch prefix,
then made read-only:

```sh
git clone --no-hardlinks <repo> ~/t3-plugins-bench/install/src-<commit>
git -C ~/t3-plugins-bench/install/src-<commit> checkout --detach <commit>
python3 ~/t3-plugins-bench/install/src-<commit>/scripts/install.py --plugin imps \
  --prefix ~/t3-plugins-bench/install/imps-<commit>
chmod -R a-w ~/t3-plugins-bench/install/imps-<commit>
python3 bench/tools/verify_package.py ~/t3-plugins-bench/install/imps-<commit>/imps/<version>
```

The entry path given to workers is the version directory's `entry.md`, never `current`.
`verify_package.py` runs before the first and after the last run of each version; both
outputs are kept in the summary. Old: see [runs/old/package.json](runs/old/package.json).

## Tasks and slots

| Task | Prompt | Workspace | Gate (stage 5) |
| --- | --- | --- | --- |
| A | [fixtures/task_a/prompt.md](fixtures/task_a/prompt.md) | `prepare_workspace.py a` | `checks/task_a.py` passes and the grader does not prefer old in both pairs |
| B | [fixtures/task_b/prompt.md](fixtures/task_b/prompt.md) | `prepare_workspace.py b` | `checks/task_b.py` passes |

Each version runs four slots: `a1`, `a2`, `b1`, `b2`. Old and new runs with the same slot
form a grading pair. Slots of one version may run at the same time; each has its own
workspace and T3 project.

## Runner

For each attempt:

1. Create the workspace: `python3 bench/tools/prepare_workspace.py <a|b> ~/t3-plugins-bench/ws/<id>`,
   where `<id>` is 8 random hex characters. The path never names the version or slot.
2. Register it: `t3_project_create` with `title: "bench <id>"` and `workspaceRoot` set to
   the workspace.
3. Launch the worker: `t3_thread_launch` with
   ```json
   {"projectId": "<project id>", "title": "bench <id>",
    "workspaceStrategy": {"type": "root"},
    "modelSelection": {"instanceId": "claudeAgent", "model": "claude-opus-5-5",
                       "options": [{"id": "effort", "value": "xhigh"}]},
    "runtimeMode": "auto", "interactionMode": "default",
    "message": "<worker prompt>"}
   ```
   Then read the thread's configuration back and record it. `xhigh` is the effort option
   the Claude provider advertises. The runtime mode is `auto`, the owner default for
   every provider except OpenCode, whose children use `full-access`. A worker's children
   inherit its workspace, and T3 refuses a child broader than its parent.
4. Wait for the thread's run to reach a terminal state. Do not message the worker.
   A run that has not finished after 4 hours is interrupted and counted as a failure.
5. Record the attempt (see Records), run the audit, then grade.

This is the only use of `t3_thread_launch` in the benchmark, authorised by the owner for
benchmarking. The executor of a stage never acts as a worker.

### Worker prompt

Fill `{ENTRY}`, `{WORKSPACE}` and `{TASK}` (the task's `prompt.md`, verbatim). Nothing
else changes between versions or tasks.

```text
Follow the installed imps entry at {ENTRY}: read it and act on it for the operation `run`, with the task below. The package directory is the directory that contains that entry file.

Pass `--state-root {WORKSPACE}/.bench-state` on every call to the imps core. This overrides the entry's advice to keep run state outside the repository.

Your workspace is {WORKSPACE}. Read, list, write and run git only inside it and inside the imps package directory. Do not fetch, browse, clone or search for anything about the upstream repository of this code, including its issues, pull requests and commits.

The operator authorises local work only: commit on the current branch, and do not push, open pull requests or publish anything. Do not ask questions; if something cannot be determined, state your assumption and continue.

Task:

{TASK}
```

## Attempts

Each slot ends with exactly one counted attempt. An attempt may be retried once, only
for an infrastructure failure (the thread never started, the provider errored before
the worker acted, or T3 lost the run) or because the audit voided it. Every attempt is
reported, including retried ones. A failed run that was not voided still counts. If a
slot uses its retry without a valid attempt, the stage ends `blocked` naming the slot.

With 2 counted runs per task and version, "median" means the mean of the two.

## Audit

Each workspace path has its own Claude Code project directory under
`~/.claude/projects/` (the path with every character other than letters, digits and
`-` replaced by `-`). The worker's session is the one whose first prompt starts with
`Follow the installed imps entry at`; every other session or subagent file there is a
descendant. Codex children are found by the `cwd` in their rollout files.

Before the first baseline run, one test worker is launched in its own Task A workspace,
with the Runner settings and this prompt:

```text
Follow the installed imps entry at {ENTRY} only to find the package directory; do not run imps. This is a transcript audit test. Call the T3 `delegate_task` tool once with the task "Reply with the single word: ok" and mode "wait", then report the child's taskId and its reply. Work only inside {WORKSPACE}. Do not change any files.
```

Both transcripts must be found, parsed and attributed by `tools/tokens.py run`;
otherwise the stage ends `blocked`.

After each attempt:

```sh
python3 bench/tools/audit.py <workspace> --package <version dir> --task <a|b> \
  --projects-dir ~/.claude/projects --codex-dir ~/.codex/sessions
```

The audit proposes `void`, `review` and `ok` findings from tool calls, not tool results.
The executor decides each `void` and `review` finding and publishes the decision in the
summary. An attempt is void if it:

- read, listed, or ran git outside its workspace, the installed imps package and the
  harness's own per-project directory; or
- for Task B, reached `seankoji-com/t3-plugins` on the network, or its issues, PRs or
  commits.

Files the harness itself writes for the worker (saved tool output, plugin scratch files
under the system temporary directory) are not the worker reading elsewhere.

## Tokens

`tools/tokens.py` is the frozen parser. Tests: `tests/test_bench.py`.

- **Parent-Opus tokens**: in the worker's session, every message from an Opus model,
  each message ID counted once: input + output + cache-creation. Cache-read is reported
  separately and not counted.
- A missing or non-integer usage field makes the total unknown (`null`), never 0.
- **Children**: Claude descendants are parsed the same way; Codex rollouts report their
  last cumulative `token_count`; any other provider is `unknown`.

## Grading

- **Task B gate**: `python3 bench/checks/task_b.py <workspace> --json`. Both new runs
  must pass; apply it to committed output in an isolated clone. The regraded old
  results are in `runs/old/b1/summary.json` and `runs/old/b2/summary.json`.
- **Task B upstream design (informational)**: `python3 bench/tools/grade_task_b.py <workspace> <bundle> --full --json`.
  The script refuses a bundle whose sha256 is not
  `19f12fe6d38ff0991c2f7000d3cb819d51f8ae58cb4f7122ba81610333d2465c`. It clones the
  workspace's `HEAD`, adds the hidden test and runs it; the full suite is informational.
- **Task A**: `python3 bench/checks/task_a.py <workspace>/out --json` for the absolute
  checks. Old-run results are informational; the stage 5 gate applies to new runs.
- **Grader**: Sol 6.1 through the Codex provider (`providerInstanceId: codex`, model
  `gpt-6.1-sol`, `reasoningEffort: xhigh`), run as a `delegate_task` child of the stage 5
  executor with `runtimeMode: auto`. It grades each Task A pair against
  [rubric.md](rubric.md), one child per pair. If that grader is unavailable in stage 5,
  the stage ends `blocked`; no other grader is used.
- **Blinding**: for each pair, a coin flip from `secrets.randbits(1)` assigns old and
  new to `X` and `Y`; the key stays in the private grading directory until grades are
  recorded. The bundle holds copies of `out/`, the committed non-`out/` files, and the
  check results. It excludes `.git/`, `.bench-state/`, transcripts, workspace IDs,
  package paths, thread IDs and any file that names an imps version.
- **Screenshots**: 1280×800 and 390×844 captures of each `out/index.html`, with the same
  tool and settings for both sides of a pair. If neither side can be captured, both are
  graded statically.

## Records

`tools/summarise.py` writes these records. For each attempt, `bench/runs/<version>/<slot>/` holds:

- `summary.json`: slot, attempt number, workspace ID, thread ID, outcome, wallclock
  (thread start to terminal state, and first to last transcript timestamp), parent-Opus
  tokens and cache-read, each descendant with provider, model and tokens or `unknown`,
  delegation count and each delegation's stated reason, model and effort as read back
  from the thread, retries with reasons, audit decision, check or grader results, the package's
  `verify_package.py` result at recording time, and
  the sha256 of every raw file kept privately.
- `output/`: the run's committed changes. Task A: `out/` plus any other committed files.
  Task B: `git format-patch` of the worker's commits.
- `report.md`: the worker's final message, with absolute paths replaced by
  `<workspace>`, `<package>` and `<home>`.

Raw transcripts and the imps run state stay in the private directory. Committed files
contain no credentials, private transcripts, absolute machine paths or private hostnames.

## Fallback

If `t3_project_create` or `t3_thread_launch` is unavailable, the stage ends
`awaiting-owner` with the prepared workspaces and the filled worker prompts, so the owner
can launch the runs by hand with the settings above.
