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

Resume in the same thread with the recorded run ID and state root. The core prevents
two owners from changing a run at once. Only recover a claim when its previous owner
is confirmed dead; never take over a live thread's work. Keep the exact blocker report.

## Sidecar processing fails

Try `process.py --doctor`, then a deterministic operation in a scratch directory.
Confirm paths are under `SIDECAR_ROOT` and output directories exist. For model work,
inspect engine configuration and `offload_sidecar.py status`. Cloud calls need explicit
consent in the one-shot request and a configured engine. A quota block is not success.

## Homebrew has an older catalog

Run `brew update`, `brew upgrade t3-plugins`, then `t3-plugins setup`. A GitHub release
and its tap formula update are separate steps. Check the release notes and tap PR if
the expected version has not reached the formula yet.

## Report a bug

Use the organization's inherited [issue forms](https://github.com/seankoji-com/t3-plugins/issues/new/choose).
Include the smallest reproduction, plugin/T3/provider versions, expected and actual
behavior, and redacted error output. Avoid private transcripts or live credentials.
