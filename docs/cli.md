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

Inspect the compact definition explicitly:

```sh
agents --pin PIN agents show imps reviewer --compact
```

The JSON response includes `definition`, its exact UTF-8 SHA-256 and byte count,
and retention bindings. A new preparation pinning that package and override uses
those exact definition bytes. Plain `show` continues to return the complete
canonical v1 definition. Inspection grants no execution or read authority.

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

The coordinator drives jobs with `shared/job_cli.py` and
`shared/job_acceptance_cli.py` inside the pinned package. Like the imps CLI, they
store and validate data; they never call a model or dispatch work. See
[architecture](architecture.md#whole-jobs) for the model and the
[jobs contract](https://github.com/seankoji-com/.agents/blob/main/shared/agents/jobs-contract.md)
for inputs.

### Compact worker transport

For a **new** job, set `policy.worker_brief_transport` to
`"worker-brief-compact-v2"` in its creation input. A separate planning-review
`create` takes the same explicit choice as top-level `worker_brief_transport`.
Omitting it preserves v1. A job's transport choice cannot change through a plan
revision; resume with its pinned package and original format.

The existing public `prepare` command still returns only a path, file SHA-256,
byte count and provenance. Send that descriptor to the selected worker. A v2 file
has a version marker, a JSON header and a literal inline UTF-8 procedure body;
it is not one JSON object despite retaining the immutable `.json` brief filename.
Do not pass it to a v1 JSON consumer. The shared `compact_briefs.deserialize`
reader dispatches explicitly, and result admission verifies the exact file against
private coordinator state. Workers return `worker-result-v1` with version 1,
the header's remaining correlation fields and `binding: snapshot`.

Approved retention/source/procedure hashes, schemas, rubrics, package dependencies,
overrides, selection/options and current task authority are checked before result
admission and acceptance. Missing, changed, unsafe or mixed input fails closed.
No worker needs to discover omitted instructions or read the full job. Existing
full definitions, pinned v1 resume and original result schemas keep their meaning.

The [measured fixture bytes](architecture.md#tradeoffs) distinguish dependency-only
reduction from procedure serialization. All 18 default procedures fit 24 KiB with
their required inline shapes and procedural headers; evidence growth is accounted
separately. This does not establish token savings or live model compatibility.

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
