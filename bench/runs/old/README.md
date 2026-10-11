# Old baseline (imps at `6e4cf82`)

Status: **complete**. Four counted attempts, one per slot, no retries. Run on
2026-10-11 between 05:44 and 06:12 UTC (16:44–17:12 AEDT), all four slots in parallel.
Each worker ran on Opus 5.5 at `xhigh` in runtime mode `auto`, read back from the
thread configuration.

The first attempt to register the workspaces failed with `capability_denied`, because the
executor thread ran in `auto`. The owner then gave the executor thread full access, and the
runs went ahead under the unchanged protocol.

## Audit test

[audit-test.json](audit-test.json): one worker delegated one Claude child. Both transcripts
were found, parsed and attributed by workspace path. The audit found 0 void and 0 review.

## Results

| Slot | Outcome | Wallclock (min) | Parent-Opus tokens | Cache-read | Delegations | Child tokens (Codex rollouts) | Task result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| a1 | completed | 27.7 | 392,231 | 19,732,058 | 1 (Codex Sol 6.1 review) | 348,380 + 90,547 | `task_a.py`: 4/4 required, 3/3 informational pass |
| a2 | completed | 24.5 | 347,788 | 18,097,628 | 1 (Codex Sol 6.1 review) | 312,820 + 13,539 | `task_a.py`: 4/4 required, 3/3 informational pass |
| b1 | completed; imps `blocked` (sandbox prevented the full suite) | 21.9 | 244,864 | 11,115,987 | 0 | – | hidden tests fail (3/3) |
| b2 | completed; imps `blocked` (sandbox prevented the full suite) | 29.7 | 270,893 | 14,159,045 | 0 | – | hidden tests fail (3/3) |

Wallclock runs from the thread's first run start to its last run end. Workers that
waited on a background test run resumed in a second or third thread run, and that time
is included. Parent-Opus tokens are input + output + cache-creation; cache-read is not
counted. Child tokens are Codex's last cumulative `total_tokens` for each rollout whose
`cwd` is the workspace. Two rollouts matched each Task A workspace.

Means per task (the protocol's "median" with two runs):

| Task | Parent-Opus tokens | Wallclock (min) |
| --- | --- | --- |
| A | 370,010 | 26.1 |
| B | 257,879 | 25.8 |

After the baseline, `task_a.py` was hardened in review: it now parses HTML instead of
matching quoted attributes, and it rejects non-string station IDs. Re-running the
updated checker on both Task A outputs gives the same result, 4/4 required and 3/3
informational passing. The Task A results in `summary.json` were recorded with the
earlier checker.

## Notes for stage 5

- **Task B hidden tests are design-specific.** Both workers fixed the bug by writing an
  owner token into the worktree's git admin directory, and both wrote regression tests
  that fail before the fix and pass after. The hidden tests instead expect the upstream
  design: the identity carries the `.git` pointer file's `st_dev`/`st_ctime_ns`, a failed
  identity capture refuses cleanup, and inode-only legacy identities read as `replaced`.
  The gate "hidden tests pass on both new Task B runs" therefore measures whether a run
  lands on the upstream design, not only whether it fixes the bug. This is a decision for
  the owner before stage 5.
- **Audit precedent.** Every attempt had `void` proposals from the audit script. On
  inspection, none read repository content outside the workspace. They fall into four groups:
  - shell-variable paths that resolve inside the workspace (`$S/red.log`)
  - text inside written files
  - the harness's own per-project directory and temp output
  - toolchain discovery: listing `~/.local/bin`, `/Applications/*` browsers and
    `~/Library/Caches/ms-playwright`; running a uv-installed Python or headless Chrome
    with its profile in the session temp directory

  The executor ruled all four attempts valid and treated toolchain discovery like the
  allowed system paths. Stage 5 should apply the same rule. Each `summary.json` records
  the decision.
- **Environment.** System `python3` is 3.9.6, below the repo's 3.10 floor. Workers found
  Homebrew 3.12 or uv 3.10. The worker sandbox blocks `ps` and loopback listening, so
  7–9 tests in the Task B suite cannot run there. This is why both Task B imps runs ended
  `blocked`.

Each slot directory holds `summary.json`, `report.md` (the worker's final message) and
`output/` (Task A: the committed files outside `vendor/`; Task B: `git format-patch`).
Raw transcripts, imps run state and audit logs are in the private directory and are
identified in each summary by sha256.
[package.json](package.json) and [install-manifest.json](install-manifest.json) record
the installed package, which still verified clean when each attempt was recorded.
