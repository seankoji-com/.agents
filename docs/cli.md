# Command-line reference

Use the stable `$HOME/.local/bin/agents`. The repo-local `bin/agents` delegates
operational commands to it. `bin/agents dev ...` explicitly selects that worktree.
All helpers use Python 3.10+ and the standard library; TOML support needs 3.11+.

## Catalog commands

| Command | Result |
| --- | --- |
| `self-install [--source PATH] [--profile author|receiver]` | Explicitly validate/install resolver infrastructure; retain the previous installation |
| `status` | Show source HEAD/status/ahead/behind, active pin, infrastructure/interpreter, pending recovery and last sync |
| `permissions` | Print narrow native write grants; change no settings |
| `discovery` | Owner-run reconciliation of native links after adding, renaming or deleting skills; install no package and change no source |
| `validate-source` | Check source identity, canonical frontmatter/manifests and bootstrap contracts |
| `start NAME` | Select a coherent source pin and return its body, manifest, package and registry paths |
| `--source PATH start NAME` | Test an explicit author worktree for this invocation |
| `resume PIN NAME` | Verify and reuse that exact immutable source pin |
| `--pin PIN path NAME` | Print the pinned body path; never follow a moving current path |
| `--job JOB.json path NAME` | Resolve only that job's exact source-backed dependency |
| `adopt --from-source PATH` | Inventory/back up and adopt the existing source directory in place |
| `sync` | Receive validated fast-forward source on a receiver; reject dirty/staged/ahead/diverged source |
| `recover` | Resume the exact pending source/adoption transaction; refuse owner edits |
| `recover --restore` | Restore only recorded receiver transaction bytes/ref changes |
| `rollback PIN` | Keep a previously validated runtime selected without deleting newer source or pins |
| `rollback follow-source` | Explicitly release the rollback hold for the next sync |
| `receive enable|disable` | Manage the owned Linux systemd user timer; no shell-start fallback |

`start` returns JSON. Read `skill_file` and `manifest_file` before substantive
workflow work, using `package_root`, `package_prefix` and `registry_root` for later
helpers. The manifest routing contract is [shared](https://github.com/seankoji-com/.agents/blob/main/shared/manifest-routing.md).
Single-file prose may declare a validated bootstrap exemption and needs no snapshot.

Workflow commands `selection`, `agreement`, `planning-review`, `resolve` and
`agents list|show` require `--pin PIN`; they execute/inspect that pin's code and
worker definitions. Workflow job creation and evidence commands stay in its pinned
package. These interfaces do not dispatch agents or select models themselves.

## Managed workers

Use `agents --pin PIN agents list NAME` or `agents --pin PIN agents show NAME WORKER`
to inspect the selected source's worker bundle, definition and integrity. New runs
record effective worker definitions with the same package and source pin.

### Overrides and limits

Explicit worker overrides remain owner-managed configuration under XDG config
`agents/workers.json`. Their base digest must match the selected bundle. They do
not replace the canonical skill body or add a second model-selection authority.
Existing legacy overrides remain with their retained runtime until reconciled.

## Pinned job paths

`agents --job JOB.json path NAME` resolves the dependency named by that job and
verifies its original source-backed package. It never substitutes a current
installation. Old-format jobs use the inventoried `t3-plugins --job JOB.json path
NAME` compatibility interface described below.

## Custom locations

`--source /absolute/worktree` is an explicit author-test selection. XDG state/data
overrides must be absolute and keep mutable state outside the repository. The
native discovery source remains `~/.agents`; a test worktree does not take it over.

## Inspect imps state

After resolving imps, invoke its returned pinned `package_root/cli.py` with
`status`, `validate` or `report` and the recorded `--state-root`/`--run-id`.
Whole-job status uses that same package's `shared/job_cli.py overview --compact`.
Do not load a moving current package to inspect or mutate an older job.

## Storage and recovery

The author profile captures dirty/untracked managed assets and retains old pins.
The receiver selects Git objects at the protected active commit. A shared kernel
lock serializes launch/apply. Pending recovery refuses new starts; explicit old
pins remain verifiable. Per-file discovery publication is atomic; an ordinary
multi-file checkout is not. Status exposes source/runtime divergence.

XDG state holds `agents/jobs`, `agents/snapshots`, `agents/locks`, protected
`agents/control` and bounded logs. XDG data holds protected updater and retained
legacy installations. No new mutable state belongs in `~/.agents`.
No pins are garbage-collected or deemed abandoned from age/live flags.

## Legacy compatibility

`legacy inventory --root /absolute/old/registry` reads every indexed job and claim.
Repeat `--root`; add `--job-file /absolute/job.json` for jobs outside those indexes.
Use `--run-root /absolute/old/state` for retained version-1/2 gate runs. Their
original package paths and an absolute-interpreter status command are recorded;
they are not converted to new jobs or moved into the new source.
The private report classifies resumable, terminal and missing/unknown jobs; it never
deletes unknowns or infers test leaks. `legacy install-bridge --catalog-root
/absolute/keg/libexec` retains the complete old runtime and installs a job-bound
`t3-plugins` command independently of Brew.

The bridge requires `t3-plugins --job INVENTORIED_JOB ...`, exact original pins
and an allowed old-job operation. It cannot set up/install/register new workflows.
Existing jobs, receipts, old schemas, registry paths and immutable history remain
at their original locations. A retirement report needs owner review and zero
resumable/unknown references before any compatibility path can be removed.

Pre-#198 files that hold settings or exclusive state stay in use where they are
until you move them. While only the old copy exists, the current runtime reads and
writes it in place; once a current copy exists, it wins. This covers repository
`.t3-plugins/<plugin>.json` and `routing.json`, the user `t3-plugins/routing.json`
and `workers.json`, the installation marker and registry lock, lessons, standing
model grants, planning-review subjects, the bug-report ledger, the tests-omg run
index and the babysitter workspace and org-scan lock. Two records for one
planning-review output are refused rather than merged.
