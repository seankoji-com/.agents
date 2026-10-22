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
| `setup [PLUGIN]` | Install snapshots, worker bundles and skill adapters; omit the name for all plugins |
| `install [PLUGIN]` | Install snapshots and worker bundles, without skill adapters |
| `path PLUGIN` | Print the active installed entry path |
| `prompt PLUGIN [REQUEST…]` | Print a prompt to paste into T3; with no request, offer the workflow's manifest picker |
| `doctor [PLUGIN] [--project PATH]` | Check installed files and package currency, and probe whether this process can write learnings (a global check from any directory); `--project` also refuses a learnings root inside that project, as its plugin runs would. Omit the name for all plugins |
| `activate PLUGIN VERSION` | Select an existing snapshot without migrating run state |
| `uninstall PLUGIN [--version VERSION]` | Remove owned snapshot and bundle files, preserving local edits, overrides and state; refuses a version a live job pins, in any recorded state root |
| `skills install [PLUGIN] --root PATH` | Install an adapter into one provider skill root |
| `skills uninstall [PLUGIN] --root PATH` | Remove an unchanged owned adapter |
| `resolve ROLE --capabilities FILE` | List available configured child-model candidates |
| `agents list [PLUGIN]` | List installed workers with version, role, override status and integrity |
| `agents show PLUGIN WORKER` | Print one worker's effective definition and provenance |
| `agents enable-override WORKER_ID --base-digest DIGEST` | Turn on one worker override |
| `agents disable-override WORKER_ID --base-digest DIGEST` | Turn it off again |
| `--job JOB.json path PLUGIN` | Print the entry pinned by a job, not the active one |
| `adopt --from-prefix OLD` | Keep a moved installation's identity after verifying its receipt |

Omit the plugin from a `skills` command to act on all bundled plugins.

Each workflow manifest declares 2 to 4 unique operation IDs for its picker and
anchored regular-expression routes for free text. A generated adapter lists those
options and routes. Remove any declared standalone flags before trying the routes.
Match the full request against the patterns in order and use the first match. If
no route matches, ask the user to choose an operation. A bare command never
defaults to `doctor`.

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

Worker bundles go under the agents root, `~/.agents/agents/t3-plugins` by default.
Change it with `--agents-root PATH` before the command or `T3_PLUGINS_AGENTS_ROOT`.
Keep one agents root per prefix: installing into a prefix whose versions use another
root fails with `agents_root_conflict`.

## Managed workers

These two commands are read-only:

```sh
t3-plugins agents list babysitter
t3-plugins agents show babysitter pr-maintainer
```

`list` prints one JSON line per worker: `id`, `version`, `role`, `override_status`
(`disabled`, `enabled` or `stale`), `integrity` and `bundle_digest`. `show` adds the
bundle and file paths, their hashes and the composed effective text.

### Overrides and limits

Worker limits and overrides live in `$XDG_CONFIG_HOME/t3-plugins/workers.json`, or
`~/.config/t3-plugins/workers.json` when `XDG_CONFIG_HOME` is unset. A missing file
means the defaults below. Routing stays in [`routing.json`](getting-started.md#model-routing).

```json
{
  "schema_version": 1,
  "max_live_workers": null,
  "max_live_workers_by_provider": {},
  "max_repair_cycles": 20,
  "overrides": []
}
```

| Field | Meaning |
| --- | --- |
| `max_live_workers` | `null` for no plugin cap, or a positive integer. T3 capacity still applies |
| `max_live_workers_by_provider` | Optional positive limits keyed by exact live provider instance ID; omitted providers use only the global cap |
| `max_repair_cycles` | Repairs after the initial attempt, a nonnegative integer; default `20` |
| `overrides` | Records written by `enable-override` and `disable-override` |

Booleans, fractions and unknown fields are rejected. To customize a worker:

1. Write `<agents-root>/overrides/<plugin>/<worker>.md`. It must be a regular UTF-8
   file, not a symlink, and contain the line `worker_id: <plugin>/<worker>`.
2. Copy `bundle_digest` from `agents list` for the active version.
3. Run `t3-plugins agents enable-override <plugin>/<worker> --base-digest DIGEST`.

A file on disk does nothing until it is enabled. An enabled override that is missing
or malformed fails rather than falling back to the default. After an upgrade the
override shows `stale` and stays inactive until you enable it against the new
digest. Overrides change wording only; they cannot grant authority or change
runtime mode.

A job snapshots these limits and the exact definition and override bytes when it
is created. Later edits affect new jobs only. Bringing a change into an existing
job needs a recorded plan revision, new briefs, and stales the affected acceptance.

## Pinned job paths

Inside a job, resolve every plugin through its pin:

```sh
t3-plugins --job ~/.local/state/t3-plugins/jobs/JOB_ID/job.json path babysitter
```

This prints the entry inside the pinned version directory after checking the
package and bundle digests. It refuses a plugin the job did not declare and a
package that changed. Plain `path` still prints the active `current` entry.
A job helper run from another package refuses with `wrong executing package`; each
pin in `job.json` stores the recovery command as `compatible_pinned_invocation`.

The coordinator drives jobs with `shared/job_cli.py` and
`shared/job_acceptance_cli.py` inside the pinned package. Like the imps CLI, they
store and validate data; they never call a model or dispatch work. See
[architecture](architecture.md#whole-jobs) for the model and the
[jobs contract](https://github.com/seankoji-com/t3-plugins/blob/master/shared/agents/jobs-contract.md)
for inputs.

### Compact resumes and admission

Use the helper from the job's pinned package:

```sh
python3 PKG/shared/job_cli.py overview --state-root ROOT --job JOB --compact
python3 PKG/shared/job_cli.py status --state-root ROOT --job JOB --compact --since SHA
python3 PKG/shared/job_cli.py overview --state-root ROOT --job JOB --compact --cursor TOKEN
python3 PKG/shared/job_cli.py admission --state-root ROOT --job JOB
```

Compact pages contain active-task actions, capacity holders (including retained
history and conflicting handles), blockers, pending decisions, stage repair
allowances and coordination metrics. Each response is at most 16 KiB, with 20 records
by default (`--limit 1` through `100`). Counts and `next_cursor` make omissions explicit;
follow the cursor to inspect every obligation. Details remain in the referenced
`job.json` locations. Plain `overview` and `status` retain their full output.

Save `view_sha256` and pass it as `--since` on a later resume. An unchanged view
returns `changed: false` without replaying history. Cursors bind to the complete
derived view and are refused after a change; restart pagination. `--since` and
`--cursor` cannot be combined. Reads recheck receipt and artifact freshness before
comparing digests, never run validators and never mint acceptance.

Admission is job-local advice, rechecked under the preparation lock. Prepared briefs
reserve capacity alongside live and uncertain work. Follow-ups and terminal handles
with pending children also occupy a slot. Configure limits in `workers.json` or the
initial job policy; jobs freeze them at creation. Removing or raising a provider cap
needs an owner-bound plan revision. Old pinned limits retain their values.
Adding a cap for a previously unlimited provider narrows capacity and needs no owner
decision. Planning-review jobs freeze and enforce the same capacity limits before
charging a technical attempt. Other jobs
and host-wide capacity remain T3's responsibility. No helper dispatches or schedules.

Record host capacity or rate-limit refusal with `task-observation` kind
`capacity-deferred`, reason `capacity` or `rate-limit`. Only unlaunched requests can
defer. A retry needs a newly recorded owned completion ID; one completion permits
one capacity retry. Inspect existing owned work rather than polling or resetting it.

`coordination_metrics` counts accepted stages in the derived view, repair cycles,
retained unchanged observations, capacity deferrals, decision requests and result
transport bytes. Completed decision waits use local observation receipt timestamps,
with overlapping waits summed; they are not execution or personal attention time.
Historical missing sizes/timestamps, host token use and execution duration are
explicitly unknown. Deduplicated completion deliveries are not counted. Status is
read-only, and metrics never decide acceptance or consume repair budget.

Whole jobs default to 20 repairs after their initial pass. Ralph's separate
`--max-attempts` defaults to 20 total implementation attempts, including its first.
Explicit configured limits and existing pinned jobs keep their own allowances.

## Receipts and exit codes

Installation, setup, removal and integrity checks print JSON receipts. Setup prints
multiple lines, one per completed step. It is not a single all-catalog transaction;
read earlier receipts when a later step fails, resolve the conflict and retry.
`path`, `prompt` and `list` print text.

| Exit | Catalog meaning |
| --- | --- |
| `0` | Command succeeded |
| `1` | Integrity check failed, routing has no candidates, or setup retained an invalid routing config |
| `2` | Invalid arguments, unreadable input, configuration error, a refused pin, or a version a live job still pins |
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
