# Installation

You need T3 Code with a working provider and local file/shell access. Python 3.10+
runs the core and most helpers. Homebrew installs Python 3.12. The Codex settings
audit and TOML conversion need Python 3.11+. GitHub workflows also use Git, `gh`,
and `jq`; install those only if you use the relevant plugins.

## Homebrew

On macOS or Linux with Homebrew:

```sh
brew install seankoji-com/tap/t3-plugins
t3-plugins install
t3-plugins doctor
t3-plugins prompt imps doctor
```

`brew install` adds the catalog and imps command-line tools. `t3-plugins install`
creates your user-owned snapshots. Paste the final command's output into T3.
Installation does not edit provider settings or register slash commands.

To install just one plugin's snapshot, use `t3-plugins install ape`.
`t3-plugins list` shows the bundled catalog.

## From source

```sh
git clone https://github.com/seankoji-com/t3-plugins.git
cd t3-plugins
python3 bin/t3-plugins install --dry-run
python3 bin/t3-plugins install
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
t3-plugins install
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
