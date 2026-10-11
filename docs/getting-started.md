# Installation

You need T3 Code with a working provider and local file/shell access. Python 3.10+
runs the core and most helpers. Homebrew installs Python 3.12. The Codex settings
audit and TOML conversion need Python 3.11+. GitHub workflows also use Git, `gh`,
and `jq`; install those only if you use the relevant plugins.

## Homebrew

On macOS or Linux with Homebrew:

```sh
brew install seankoji-com/tap/t3-plugins
t3-plugins setup
t3-plugins doctor
t3-plugins prompt imps doctor
```

`brew install` adds the catalog and imps command-line tools. `t3-plugins setup`
creates your user-owned snapshots and managed [skill adapters](slash-commands.md)
in `~/.agents/skills`, `~/.claude/skills`, and `~/.gemini/config/skills`.
Enable **Show skills in slash menu** in T3's General settings and restart the agent
session. You can combine the first two commands with `&&`.
Homebrew's post-install step uses an isolated temporary home, so setup runs in your
own shell instead. See [Homebrew's implementation](https://docs.brew.sh/rubydoc/Formula#run_post_install-instance_method).
Paste the final prompt command's output when a provider lacks skill discovery.
Setup does not edit provider settings or overwrite unowned or edited skills.

To install just one plugin's snapshot, use `t3-plugins install ape`.
Use `t3-plugins setup imps` for one plugin plus its adapters, or repeat
`--root PATH` to choose custom skill roots instead of the three defaults.
`t3-plugins list` shows the bundled catalog.

## From source

```sh
git clone https://github.com/seankoji-com/t3-plugins.git
cd t3-plugins
python3 bin/t3-plugins install --dry-run
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
python3 bin/t3-plugins prompt imps doctor
```

Use `python3 bin/t3-plugins` wherever the guides say `t3-plugins`. The legacy
`python3 scripts/install.py --plugin imps` interface still works for single plugins.

## Paths and remote environments

Snapshots live in `~/.local/share/t3-plugins/<plugin>/<version>/`. A `current` symlink
gives the agent a stable entry path. Each snapshot contains its required shared files;
it does not depend on the source checkout remaining in place.

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
brew upgrade t3-plugins
t3-plugins setup
t3-plugins doctor
```

For source installs, pull the desired revision and rerun the installer. Installation
is idempotent for identical files. A changed package gets a new snapshot. Local edits
to that same snapshot cause refusal; `--force` is an explicit overwrite. Older
snapshots remain available, including any edits you made there.

Use a version printed by the installer to roll back:

```sh
t3-plugins activate imps VERSION
```

Activation changes only `current`. Running `install` again while rolled back reports
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
`full-access` because its children otherwise stall on permission prompts.

```json
{
  "schema_version": 1,
  "tiers": ["low", "medium", "high"],
  "providers": {
    "codex": {"runtimeMode": "auto"},
    "opencode": {"runtimeMode": "full-access"}
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
`owner_action` saying which mode to switch the child to. With `--implementer-lineage
LINEAGE`, candidates of other lineages come first and each is marked `independent`. A repository can override
roles, providers or tiers in `.t3-plugins/routing.json`; repository policy wins.

## Uninstall

```sh
t3-plugins uninstall ape
brew uninstall t3-plugins
```

The first command removes only manifest-owned, unmodified files for that plugin.
Added files and local edits remain. Repeat for other snapshots you want removed
before uninstalling the Homebrew command. Run state is never removed by uninstall.

Homebrew's `imps` command runs the packaged CLI directly. It does not silently
install, overwrite, or change your user snapshots.
