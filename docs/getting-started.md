# Installation

Install once, then invoke a workflow from a T3 thread attached to your project.
The terminal commands below install local files; they do not call a model.

You need T3 Code with a working provider and local file/shell access. Python 3.10+
runs the core and most helpers. Homebrew installs Python 3.12. The Codex settings
audit and TOML conversion need Python 3.11+. GitHub workflows also use Git, `gh`,
and `jq`; install those only if you use the relevant plugins.

## From source

Source installation uses the current six-workflow catalog. For a packaged release,
use Homebrew catalog v0.5.0 or later as described below.

```sh
git clone https://github.com/seankoji-com/t3-plugins.git
cd t3-plugins
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
python3 bin/t3-plugins prompt imps doctor
```

Use `python3 bin/t3-plugins` wherever the guides say `t3-plugins`.
`setup`
creates your user-owned snapshots and managed [skill adapters](slash-commands.md)
in `~/.agents/skills`, `~/.claude/skills`, and `~/.gemini/config/skills`.
Enable **Show skills in slash menu** in T3's General settings and restart the agent
session.
Paste the final prompt command's output when a provider lacks skill discovery.
By default, setup does not edit provider settings or overwrite unowned or edited
skills. It also prints optional learning-directory grants. Apply them only with
`--grant-learnings`; see [learnings and harvest](learnings.md#sandbox-grants).

`doctor` should print `"ok": true` for each installed plugin and exit 0. It checks
files, not T3 or your model. The final command prints a line beginning `Read`;
paste that whole line into T3 for the workflow readiness check. Then follow
[your first workflow](first-workflow.md).

To install just one plugin's snapshot, use `t3-plugins install ape`.
Use `t3-plugins setup imps` for one plugin plus its adapters, or repeat
`--root PATH` to choose custom skill roots instead of the three defaults.
`t3-plugins list` shows the bundled catalog.

## Homebrew release channel

Catalog v0.5.0 and later uses the setup commands in these guides. Earlier releases
have different commands. Ralph requires a catalog that lists it in `t3-plugins list`;
use source installation until your packaged release includes it.
Install the latest formula, then set up your user snapshots
and skill adapters:

```sh
brew update
brew install seankoji-com/tap/t3-plugins
t3-plugins setup
t3-plugins doctor
```

If already installed, use `brew upgrade seankoji-com/tap/t3-plugins` instead of
`brew install`. Check `brew list --versions t3-plugins` for v0.5.0 or later.
If the tap has not reached v0.5.0 yet, use the source installation above until its
formula update is merged.
Homebrew's formula test uses an isolated temporary home; run setup in your own shell
to populate your skill adapters.

## Paths and remote environments

Snapshots live in `~/.local/share/t3-plugins/<plugin>/<version>/`. A `current` symlink
gives the agent a stable entry path. Each snapshot contains its required shared files;
it does not depend on the source checkout remaining in place. Worker definitions go
into a matching bundle under `~/.agents/agents/t3-plugins`, and jobs keep their state
in `~/.local/state/t3-plugins/jobs`. See [custom locations](cli.md#custom-locations)
to move the agents root.

Install on the machine where the T3 provider executes tools. A path on your laptop
is not automatically available to a remote provider. If its sandbox cannot access
the default prefix, choose an allowed location:

```sh
t3-plugins --prefix /tmp/my-t3-plugins install
t3-plugins --prefix /tmp/my-t3-plugins prompt ape doctor
```

Set `T3_PLUGINS_PREFIX` to reuse a custom prefix. Use a persistent writable directory
for long-term installations; `/tmp` is only a demonstration.

## Upgrade and rollback

```sh
git pull --ff-only
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
```

Run these commands in your source checkout. For a Homebrew installation, use
`brew upgrade t3-plugins`, then `t3-plugins setup` and `t3-plugins doctor`. Installation
is idempotent for identical files. A changed package gets a new snapshot. Local edits
to that same snapshot cause refusal; `--force` is an explicit overwrite. Older
snapshots remain available, including any edits you made there.

Use a version printed by the installer to roll back:

```sh
t3-plugins activate imps VERSION
```

Activation changes only `current` and selects that version's worker bundle with it.
Jobs already running keep the versions they pinned. Running `install` again while rolled back reports
`reactivated`: the snapshot already existed and only `current` moved back to it.
Run `doctor` afterward: an intentional rollback
reports `snapshot_outdated` when its files differ from the bundled package. The Homebrew
`imps` command also warns about this mismatch; it does not rewrite snapshots. Use the
rolled-back snapshot's `cli.py` when you need its matching state engine.
Installing the full catalog
activates each plugin separately; a failure can leave a partial catalog upgrade.
Read the per-plugin receipts and retry after resolving the error.

### Retired plugins

offload-sidecar and prompt-builder left the catalog. `t3-plugins setup` removes their
slash-menu adapters when the adapter's own `.t3-plugins-skill.json` marker shows that
setup wrote it and the adapter is unchanged. It keeps edited adapters, symlinks,
adapters with corrupt markers, and any files you added, and prints a receipt for each.
Old snapshots stay until you remove them:

```sh
t3-plugins uninstall offload-sidecar
t3-plugins uninstall prompt-builder
```

`uninstall` accepts a retired name only when an installed manifest records it.

## Model routing

Delegating workflows choose child models from a routing config in your user
configuration directory: `$XDG_CONFIG_HOME/t3-plugins/routing.json`, or
`~/.config/t3-plugins/routing.json` when `XDG_CONFIG_HOME` is unset. Setup writes a
starting config from a capabilities response the agent saved to a file. It never
calls T3 or reads credentials, and it never replaces an existing config.

```sh
t3-plugins setup --capabilities caps.json
t3-plugins resolve reviewer --capabilities caps.json
```

The config lists tiers from cheapest to most capable, a T3 `runtimeMode` per provider,
and the `workhorse`, `reviewer` and `judgement` roles. Each role entry names a provider
instance, a model, its tier and its `lineage`. Setup's tiers and lineage labels are
guesses: edit them. Providers default to `auto`, except OpenCode, which defaults to
`full-access` with `"requireRuntimeMode": true` because its children otherwise stall
on permission prompts.

```json
{
  "schema_version": 1,
  "tiers": ["low", "medium", "high"],
  "providers": {
    "codex": {"runtimeMode": "auto"},
    "opencode": {"runtimeMode": "full-access", "requireRuntimeMode": true}
  },
  "roles": {
    "reviewer": [
      {"providerInstanceId": "codex", "model": "MODEL_ID",
       "tier": "medium", "lineage": "openai"}
    ]
  }
}
```

`resolve` prints the role's candidates that the capabilities file can run, in tier
order, and lists each configured entry it could not use with the reason. It never
substitutes a different model. When a child's mode is broader than the parent
thread's, T3 refuses it, so `resolve` lowers the mode to the parent's and adds an
`owner_action` saying which mode to switch the child to. A provider with
`requireRuntimeMode` (OpenCode, unless set to `false`) is listed as unavailable instead. With `--implementer-lineage
LINEAGE`, each candidate is marked `independent`: `true` for another known lineage,
`null` when either lineage is `unknown`, `false` for the same lineage. They print in
that order. A repository can override
roles, providers or tiers in `.t3-plugins/routing.json`; repository policy wins.

## Uninstall

Remove skill adapters from every root first, then remove snapshots. Omitting the
plugin name attempts removal for all bundled plugins in that root. It stops at the
first modified or unowned adapter with exit 2; preserve those files and resolve the
conflict before retrying. Retired adapters need their explicit name, or the owned
adapter cleanup performed by `setup`:

```sh
t3-plugins skills uninstall --root ~/.agents/skills
t3-plugins skills uninstall --root ~/.claude/skills
t3-plugins skills uninstall --root ~/.gemini/config/skills
t3-plugins uninstall ape

# For a Homebrew installation only:
brew uninstall t3-plugins
```

Snapshot removal deletes only manifest-owned, unmodified files for that plugin and
its worker bundle. Added files, local edits and worker overrides remain. A version
that a live or resumable job pins is refused with `version_referenced`. Repeat for other snapshots you want removed
before uninstalling the Homebrew command. Run and job state are never removed by uninstall.

Homebrew's `imps` command runs the packaged CLI directly. It does not silently
install, overwrite, or change your user snapshots.
