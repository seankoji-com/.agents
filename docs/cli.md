# Command-line reference

There are two interfaces. `t3-plugins` manages the catalog and prints prompts for
T3. `imps` is the evidence-state CLI used by the agent; it does not implement a task
or run tests for you.

For source installs, use `python3 bin/t3-plugins` in place of `t3-plugins`.
Run `t3-plugins --help` or `t3-plugins COMMAND --help` for all options.

## Catalog commands

| Command | Result |
| --- | --- |
| `list` | Print bundled plugin names and descriptions; does not list installed versions |
| `setup [PLUGIN]` | Install snapshots and skill adapters; omit the name for all five |
| `install [PLUGIN]` | Install snapshots only |
| `path PLUGIN` | Print the active installed entry path |
| `prompt PLUGIN [REQUEST…]` | Print a prompt to paste into T3; defaults to `doctor` |
| `doctor [PLUGIN]` | Check installed files and package currency; omit the name for all five |
| `activate PLUGIN VERSION` | Select an existing snapshot without migrating run state |
| `uninstall PLUGIN [--version VERSION]` | Remove owned snapshot files, preserving local edits and run state |
| `skills install [PLUGIN] --root PATH` | Install an adapter into one provider skill root |
| `skills uninstall [PLUGIN] --root PATH` | Remove an unchanged owned adapter |
| `resolve ROLE --capabilities FILE` | List available configured child-model candidates |

Omit the plugin from a `skills` command to act on all bundled plugins.

`setup --root PATH` replaces the default skill roots. Repeat it for multiple roots.
`setup --capabilities FILE` initializes routing from a saved T3 capabilities response.
`setup --grant-learnings` also applies the proposed learning-directory grants after
backing up provider configuration. See [routing](getting-started.md#model-routing)
and [learnings](learnings.md#sandbox-grants) before using these optional flags.

## Custom locations

Pass `--prefix` **before** the command, or set `T3_PLUGINS_PREFIX` consistently:

```sh
t3-plugins --prefix /tmp/example-t3-plugins install imps
t3-plugins --prefix /tmp/example-t3-plugins doctor imps
t3-plugins --prefix /tmp/example-t3-plugins prompt imps doctor
```

Use a persistent writable directory for a permanent installation. State uses
`XDG_STATE_HOME` separately; changing the package prefix does not move existing runs.

## Receipts and exit codes

Installation, setup, removal and integrity checks print JSON receipts. Setup prints
multiple lines, one per completed step. It is not a single all-catalog transaction;
read earlier receipts when a later step fails, resolve the conflict and retry.
`path`, `prompt` and `list` print text.

| Exit | Catalog meaning |
| --- | --- |
| `0` | Command succeeded |
| `1` | Integrity check failed, routing has no candidates, or setup retained an invalid routing config |
| `2` | Invalid arguments, unreadable input or configuration error |
| `4` | Installation refused because owned files were modified locally; back up edits before using `--force` |
| `5` | Installation I/O error |

A successful prompt command proves only that an entry exists. A successful catalog
`doctor` proves installed integrity and currency, not model behavior or T3 readiness.
The agent's `doctor` checks workflow prerequisites instead.

`install --dry-run` previews snapshot installation; it does not preview skill setup.
`uninstall PLUGIN --dry-run` previews removal. `--force` on installation overwrites
modified owned files; on removal it deletes them. Back up edits before using it.

## Inspect imps state

Homebrew installs the `imps` executable. In a source checkout use
`python3 plugins/imps/cli.py`. To use a selected snapshot's matching engine, obtain
its entry with `t3-plugins path imps` and run `cli.py` in that directory.

```sh
imps status --run-id RUN_ID
imps validate --run-id RUN_ID
imps report --run-id RUN_ID
```

Pass `--state-root PATH` on every call when the run used a custom root. `status`
reads stored observations; `validate` computes readiness against the current tree;
`report` writes JSON and Markdown reports using that same validation.

The CLI prints a JSON envelope with `ok`, `op`, `run_id` and either `data` or `error`.
Exit codes are `0` success, `2` input/version, `3` conflict, `4` prohibited and `5`
environment failure. **Exit 0 from `validate` means validation ran, not that the work
is ready.** Read `data.ready`, `data.outcome` and the missing/failed/stale evidence.

`snapshot` captures the current tree without a submission. The agent uses `init`,
`check`, `evidence`, `review`, `child`, `waive`,
`note`, `policy`, `remote` and `cancel` with schema-checked submissions. JSON goes
through `--input FILE`; `--input -` reads stdin, or `--json OBJECT` takes inline JSON.
Recipe commands are
`recipe-scaffold`, `recipe-check` and `recipe-stamp`. See the
[imps entry](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/imps/entry.md)
and [submission schemas](https://github.com/seankoji-com/t3-plugins/tree/master/core/schemas)
when integrating directly. Never edit stored run JSON to force completion.
