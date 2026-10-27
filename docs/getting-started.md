# Install and first invocation

Use a supported Python interpreter (3.10+ core, 3.11+ native TOML helpers), Git,
and a T3 provider that can read files and run local commands. GitHub workflows also
need authenticated Git, `gh` and `jq`. No model runs during installation.

## From source

```sh
git clone --branch main https://github.com/seankoji-com/.agents.git "$HOME/.agents"
python3 "$HOME/.agents/bin/agents" self-install --profile author
"$HOME/.local/bin/agents" adopt --from-source "$HOME/.agents"
"$HOME/.local/bin/agents" status
```

The launcher records the absolute interpreter and verifies its XDG installation
before importing code. `~/.agents` stays the editable source. Infrastructure edits
need an explicit `self-install`; ordinary skills, shared instructions and helpers
need no install, release, version bump or commit.

## Paths and remote environments

Install on the host where T3's provider executes tools. Paths returned by the
launcher belong to that host. An explicit worktree test does not redirect native
discovery. Keep XDG data/state outside the source; `agents status` shows each
selected source, runtime and interpreter. Remote host rollout needs its own
authorization and live observations.

## Existing populated home

Ship the companion dotfiles guard before cutover. Inventory skill ownership,
custom picker files, native links, indexed jobs/claims, PATH collisions and every
old recovery command. Keep the private inventory and exact backups outside Git.

Run `self-install` from the reviewed source checkout, keeping `~/.agents` as the
configured production source. Before removing the Brew keg, use `agents legacy
inventory` and `agents legacy install-bridge` as described in the [CLI](cli.md).
Then run `agents adopt --from-source /absolute/reviewed/checkout`.

Adoption records old bytes and a restore map, preserves the existing directory and
legacy registry paths, and publishes ownership only after source/index/ref and
native links agree. Modified or unowned collisions need explicit reconciliation.
`agents recover` resumes an interrupted adoption; never use reset, clean or stash
as a migration step. The backup path is returned by adoption.

## Native discovery and permissions

Enable T3's **Show skills in slash menu**, restart the agent session, then send
`$imps doctor`. Each required unprefixed name must appear once. Use the explicit
skill picker/mention for builtin collisions such as `plan`; an unresolved collision
blocks that host/name's rollout.

The source-owned [discovery registry](https://github.com/seankoji-com/.agents/blob/main/discovery.json)
installs only per-skill links it owns. It preserves vendor stores, native credentials
and settings. It generates no `agents/openai.yaml`; custom files are preserved.

`agents permissions` prints three writable subtrees: XDG `agents/jobs`,
`agents/snapshots` and `agents/locks`. Merge those narrow grants through the native
configuration owner. The companion dotfiles renderer adds them after verified
cutover. Retain old-job grants while their references remain. Never grant their
parent directory: control records, updater code, receipts, launchers and units
must remain outside normal agent writes. Verify actual access in a fresh session.

## Try an uncommitted change

Edit `~/.agents/skills/imps/SKILL.md` or an ordinary helper. The next invocation
captures one coherent source pin and reloads its body. Resume an earlier pin to
check that its body/helper/worker identities remain unchanged. Explicit worktree
tests use `agents --source /absolute/worktree start imps`; native discovery still
points to `~/.agents`.

For an added, renamed or deleted skill, run `agents discovery` from the owner
terminal to reconcile its native name. This changes only owned links and protected
receipts. It needs no package install or commit. Explicit `--source` worktree tests
cannot change production discovery. Existing bodies/helpers need no reconciliation.

## Receiving hosts

Install with `--profile receiver`, adopt the reviewed source, then verify manual
`agents sync` before `agents receive enable`. A usable Linux systemd user manager
is required for the five-minute timer and startup catch-up. No lingering or WSL
configuration is changed. Without that manager, automatic receiving is unavailable;
manual sync remains usable. The author profile cannot enable receiving.

## Model routing

Save T3's live capabilities response and run routing commands through an explicit
source pin, as the selected workflow instructs. The manifest owns operation routes;
skill frontmatter owns names, descriptions and portable metadata. Frozen model and
agreement records remain bound to the job. No model broker or scheduler is added.
OpenCode defaults to `full-access` with `"requireRuntimeMode": true`, because its
children otherwise stall on permission prompts. An explicit lower OpenCode mode is
accepted when T3 advertises it and the parent permits it. This does not change the
defaults or override a configured required mode.

## Homebrew release channel

The old formula is retained for unmigrated hosts. New project publishing has ended.
An installed keg can be removed only after the retained interpreter, complete
compatibility runtime, bridge and a real old-job resume work independently of Brew.
The [original recording](assets/recordings/quickstart.txt) documents that historical
installation and is not evidence for this source checkout interface.

## Retired plugins

elephant-goldfish, offload-sidecar and prompt-builder remain legacy-only inventory
entries. No unprefixed native skill is published for them. Preserve old pins and
recovery commands; a rename never reactivates a retired workflow.
