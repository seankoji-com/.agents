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
permissions. See [slash commands](slash-commands.md). The old Claude colon commands
remain separate. Use `t3-plugins prompt PLUGIN OPERATION` as the direct-entry fallback.

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

Run `brew update`, `brew upgrade t3-plugins`, then `t3-plugins setup`. A GitHub release
and its tap formula update are separate steps. Check the release notes and tap PR if
the expected version has not reached the formula yet.

## Report a bug

Use the organization's inherited [issue forms](https://github.com/seankoji-com/t3-plugins/issues/new/choose).
Include the smallest reproduction, plugin/T3/provider versions, expected and actual
behavior, and redacted error output. Avoid private transcripts or live credentials.
