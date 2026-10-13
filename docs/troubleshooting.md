# Troubleshooting

## The agent cannot read the entry

Run `t3-plugins path PLUGIN` on the same machine as the provider. Check that the path
is inside its readable roots. Use a custom installation prefix if needed. A local
desktop install does not populate a remote provider's filesystem.

## `doctor` reports an outdated snapshot

Homebrew upgrades the package; `t3-plugins setup` updates user snapshots and skills. Run that
command after an upgrade. `doctor` compares snapshot contents with the bundled
package and reports `snapshot_outdated` when they differ, including intentional
rollbacks. The packaged `imps` command warns too, without changing installed files.

## `doctor` reports modified or missing files

The shell command checks installation integrity. Inspect the named files before
reinstalling. Preserve your edits elsewhere, or deliberately use `install PLUGIN
--force` to overwrite the affected snapshot. The agent's `doctor` operation separately
checks workflow prerequisites and T3 capabilities.

## The skill is missing from the slash menu

Install the adapter into the selected provider's skill root, enable **Show skills in
slash menu**, and restart the agent session. Check custom provider homes and skill
permissions. See [slash commands](slash-commands.md). Use `t3-plugins prompt PLUGIN OPERATION` as the direct-entry fallback.

## A T3 task or watch tool is missing

Record the exact T3 build and missing tool. Discover the live host capabilities.
Do direct work when the playbook allows it; an independent-review requirement cannot
be satisfied by reviewing your own output. Do not launch another provider CLI to
pretend a missing T3 task API exists.

## imps is blocked after interruption

Resume in the same thread with the recorded run ID and state root. Reconcile child
handles, verify uncertain stops and collect missing evidence. The process lock keeps
submissions atomic; it does not decide which agent should perform the work.
Do not run two agents against the same working tree.

For state major version 1, activate the previous installed imps package and use its
entry to inspect, resume or cancel the run. See [previous runs](plugins/imps.md#previous-runs).
Do not change the state version or try to convert it by editing JSON.

## Homebrew has an older catalog

These guides describe catalog v0.5.0 and later. If `brew list --versions t3-plugins`
reports an earlier version, upgrade or use the
[source installation path](getting-started.md#from-source).

Run `brew update`, `brew upgrade t3-plugins`, then `t3-plugins setup`. A GitHub release
and its tap formula update are separate steps. Check the release notes and tap PR if
the expected version has not reached the formula yet.

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
| attempt budget exhausted | The stage used its initial attempt and every repair | Choose in the picker: raise the limit, narrow the work or stop |
| `undeclared_expansion` | The change adds work, widens authority or weakens a requirement | Answer the picker question; the agent records your exact words |
| review absent, adverse or not independent | No approving reviewer on another known lineage | Configure a reviewer in routing; self-review cannot replace it |
| `stale_evidence` or a stale predecessor | Inputs, pins or an earlier stage changed after acceptance | Let the agent repair and accept the stage again |
| `wrong executing package` or a changed pin | A helper ran from a package the job did not pin | Load the entry printed by `--job JOB path PLUGIN` |
| a rejected result | The worker returned prose, a partial object or oversize output | It counts as a failed attempt; results are never truncated or guessed |

Blocked stages keep their counters. Resume, a new model or a replacement task never
resets them.

## Uninstall says a version is still in use

`version_referenced` means a live or resumable job under
`$XDG_STATE_HOME/t3-plugins/jobs` pins that package or worker bundle. Finish or
cancel the job first; cancelling keeps its artifacts. Uninstall checks only that
default jobs directory, so keep any version that a job under a custom `--state-root`
still uses.

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
