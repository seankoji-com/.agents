# Troubleshooting

Find the symptom, run the check, apply the fix. If nothing here matches,
[report a bug](#report-a-bug) with the exact output.

## The agent cannot read the entry

Run `t3-plugins path PLUGIN` on the machine where the provider runs tools, and check
that the path is inside the folders it can read. If not, install under a
[custom prefix](getting-started.md#paths-and-remote-environments) it can reach. An
install on your laptop doesn't put files on a remote provider's machine.

## `doctor` reports an outdated snapshot

`brew upgrade` updates the package but not your installed snapshots or skills. Run
`t3-plugins setup` after every upgrade. `doctor` compares each snapshot with the
bundled package and reports `snapshot_outdated` when they differ, including after an
intentional rollback. The packaged `imps` command warns too, without changing files.

## `doctor` reports modified or missing files

The terminal `doctor` checks the installed files. Look at the files it names before
reinstalling. Copy any edits you want to keep, then run `t3-plugins install PLUGIN
--force` to overwrite that snapshot. The agent's `$t3-PLUGIN doctor` is a different
check: it covers workflow prerequisites and T3 capabilities.

## The skill is missing from the slash menu

Check three things: the skill is in the folder your provider reads (see
[slash commands](slash-commands.md)), **Show skills in slash menu** is on, and you
restarted the agent session after `setup`. Custom provider homes use their own
folders. Meanwhile, `t3-plugins prompt PLUGIN OPERATION` prints a line you can paste
instead.

## A T3 task or watch tool is missing

Note the T3 build and the missing tool, and have the agent list T3's live
capabilities. Work the playbook allows to run directly can continue. A required
independent review can't be replaced by the agent reviewing its own output, and the
agent must not start another provider's CLI to stand in for a missing T3 task tool.

## imps is blocked after interruption

Resume in the same thread with the recorded run ID and state root. Reconcile child
handles, verify uncertain stops and collect missing evidence. The process lock keeps
submissions atomic; it does not decide which agent should perform the work.
Do not run two agents against the same working tree.

For state major version 1, activate the previous installed imps package and use its
entry to inspect, resume or cancel the run. See [previous runs](plugins/imps.md#previous-runs).
Do not change the state version or try to convert it by editing JSON.

## Homebrew has an older catalog

These guides describe the current `master`. Check with `t3-plugins list`: no `ralph`
means you have the stable v0.4.0 formula. Reinstall the
[HEAD build](getting-started.md#homebrew-release-channel), or install from source.
To pick up new commits on a HEAD install, run `brew upgrade --fetch-HEAD t3-plugins`;
plain `brew upgrade` doesn't check for them. Run `t3-plugins setup` after either. A GitHub release and its
tap formula update are separate steps, so a new release can take a while to reach
`brew`.

## Setup stopped partway through

Setup prints one receipt per completed step and stops on a conflict. An existing
skill directory without a valid ownership marker, edited generated files or a
symlinked root can cause refusal. Preserve the conflicting files and follow the
[adapter recovery steps](slash-commands.md#ownership-and-removal), then retry.
Do not delete a whole skill root or use snapshot `--force` to solve a skill conflict.

## Resume a job after an interruption

Ask the same workflow to `resume` with the job ID, in the same thread when you can.
The agent first resolves the pinned entry with
`t3-plugins --job ~/.local/state/t3-plugins/jobs/JOB_ID/job.json path PLUGIN` and loads
that one, even if `current` has moved. It then reads the job overview, checks every
recorded task handle with `task_status`, and only then acts. A missing reply is never
a reason to start the same work again. `status` prints the overview without changing
anything.

The overview lists every stage, requirement coverage, the current stage, open
decisions, blockers, task handles and `fallback: direct (<reason>)` markers. It does
not read worker transcripts.

## A job is blocked

| Report | Meaning | Next step |
| --- | --- | --- |
| `uncertain_dispatch` | A launch had no clear answer after two same-ID retries | Find the task in T3. Nothing replaces it until it is proven absent or stopped |
| `capacity_deferred` | T3 refused the launch while this job had live tasks | Wait; the retry follows the next completion notification from a task this job owns |
| `attempt_budget_exhausted` | The stage used its initial attempt and every repair | Choose in the picker: raise the limit, narrow the work or stop |
| `undeclared_expansion` | The change adds work, widens authority or weakens a requirement | Answer the picker question; the agent records your exact words |
| `required_review_unavailable`, or an adverse review | No approving reviewer on another known lineage | Configure a reviewer in routing; self-review cannot replace it |
| `stale_evidence` or `dependency_stale` | Inputs, pins or an earlier stage changed after acceptance | Let the agent repair and accept the stage again |
| `pin_mismatch` (`wrong executing package` or a changed pin) | A helper ran from a package the job did not pin | Load the entry printed by `--job JOB path PLUGIN` |
| `pin_mismatch: legacy package has no worker bundle` | The active package predates worker bundles | Activate a listed version that has bundles, or run `t3-plugins setup PLUGIN` |
| a rejected result | The worker returned prose, a partial object or oversize output | It counts as a failed attempt; results are never truncated or guessed |

Blocked stages keep their counters. Resume, a new model or a replacement task never
resets them.

## Uninstall says a version is still in use

`version_referenced` means a live or resumable job pins that package or worker
bundle. Uninstall checks `$XDG_STATE_HOME/t3-plugins/jobs` and every state root
recorded in `<agents-root>/job-index.json` when a job was created, including custom
`--state-root` paths. Finish, cancel or discard the job first; both keep its artifacts.

Uninstall also refuses when that index is corrupt, or when a recorded job's state is
missing or unreadable and the job was never cancelled or discarded. Restore the state
root, or repair the index entry if you deleted that job deliberately.

## `doctor` reports a worker bundle or job pin problem

`worker_bundle_missing` means the package was installed before bundles existed: run
`t3-plugins setup PLUGIN`. `worker_bundle_digest_mismatch` and other bundle errors mean
the bundle no longer matches its receipt; reinstall rather than editing it.
`job_*` errors name a live job whose pinned package or bundle is missing, changed or
corrupt. Restore that version, or cancel the job. An identity conflict after moving a
prefix needs `t3-plugins adopt --from-prefix OLD`.

## A worker override is ignored

`agents list` shows `stale` after an upgrade: the override was enabled against the
previous bundle digest. Review your file against the new definition from
`agents show`, then enable it again with the new `bundle_digest`. Running jobs keep
the override text they started with. See [overrides and limits](cli.md#overrides-and-limits).

## The CLI succeeded but imps is not complete

`imps validate` exits 0 when validation succeeds, even if requirements remain open.
Read `data.ready`, `data.outcome` and its evidence details. The report separates
local readiness from remote confirmation. See [CLI receipts](cli.md#inspect-imps-state).

## Report a bug

Use the organization's inherited [issue forms](https://github.com/seankoji-com/t3-plugins/issues/new/choose).
Include the smallest reproduction, plugin/T3/provider versions, expected and actual
behavior, and redacted error output. Avoid private transcripts or live credentials.
