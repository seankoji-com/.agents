# Troubleshooting

Use the exact error and identities from `agents status`. Preserve private logs
locally; redact paths, credentials and transcripts before reporting a bug.

## The agent cannot read the entry

Run `agents start NAME` on the machine running provider tools. Inspect its
`skill_file`, `manifest_file`, `package_root` and absolute `interpreter`.
A local install cannot provide files to a remote provider. See
[custom locations](cli.md#custom-locations).

## `doctor` reports an outdated snapshot

A new invocation selects current author source; an existing job keeps its pin.
That difference is expected after edits. `agents status` reports source and installed
infrastructure separately. Ordinary body/helper edits need no installation.
Infrastructure changes require explicit `agents self-install` after review.

## `doctor` reports modified or missing files

A pin or installed resolver integrity failure is a refusal, not permission to
overwrite it. Preserve the evidence and restore the exact trusted dependency.
Never edit an immutable package or substitute current source for an older job.

## The skill is missing from the slash menu

Check the provider's discovery root, explicit skill mention and session refresh in
[slash commands](slash-commands.md). After adding, renaming or deleting a skill,
the owner runs `agents discovery`. An unowned destination collision needs
reconciliation; never delete a native skill root to make installation succeed.
Verify built-in-name collisions, including `plan`, in a fresh session.

## A T3 task or watch tool is missing

Record the T3 build and missing tool; discover live capabilities. Authorized direct
work may continue. A required independent review remains blocked. Do not substitute
another provider's CLI or a polling process for unavailable host tools.

## imps is blocked after interruption

Resume using the recorded job/run ID, state root and pinned package. Reconcile
owned child handles and uncertain stops before launching replacements.
Do not edit state versions, acceptance receipts or terminal flags.

## Homebrew has an older catalog

Homebrew is the retained legacy channel. New source work uses the reviewed
`.agents` checkout and stable launcher. Keep the tap installable for unmigrated
hosts. Remove this project's local keg only after the independent bridge,
interpreter and an actual old-job resume have passed. See
[legacy compatibility](cli.md#legacy-compatibility).

## Setup stopped partway through

Run `agents status` and inspect the pending transaction. Use `agents recover`
for its recorded continuation, or `agents recover --restore` for a receiver
transaction's exact recorded restore. Adoption recovery is a continuation.
If a path contains owner edits, recovery stops; preserve and reconcile those
edits before retrying. Never reset, clean, stash or delete the source directory.

## Learnings report `unavailable` with a denied write

A reason starting "the sandbox or filesystem permissions deny" has two possible
causes, and each has its own fix. The skill still finishes its work and reports the
proposed lesson.

- **The provider's sandbox doesn't allow the learnings folder.** Lessons live under
  `agents/jobs/learnings` in XDG state. `agents permissions` prints the narrow native
  grants without changing settings; `agents setup --grant-learnings` adds the grant.
  Only `agents/jobs`, `agents/snapshots` and `agents/locks` belong in agent-write
  grants; keep updater, launcher, ownership receipts, active records and service units
  protected. If setup returns `status: manual`, the provider config is dotfiles-managed:
  add the printed `snippet` to the printed `target` at its source and sync.
- **Ordinary filesystem permissions or a read-only mount.** A sandbox grant can't fix
  these. Check who owns the state root and the learnings folder, their permission
  bits, and whether the mount is read-only, then fix whichever blocks your user.

Then follow [confirm a real write](learnings.md#confirm-a-real-write). Don't move
lessons to the project or a temporary folder, and don't turn the sandbox off.

## Resume a job after an interruption

Use `agents --job /absolute/JOB.json path NAME` for a source-backed job.
Inventoried old-format jobs use `t3-plugins --job /absolute/JOB.json path NAME`.
Load that exact body, read the compact overview and reconcile recorded task
handles. A missing reply does not justify relaunching work. `status` changes no
observations. See [pinned job paths](cli.md#pinned-job-paths).

## A job is blocked

| Report | Next step |
| --- | --- |
| `uncertain_dispatch` | Reconcile the retained host handle; do not replace uncertain work |
| `capacity_deferred` | Continue on a completion notification from owned work |
| `attempt_budget_exhausted` | Obtain an explicit owner decision before raising limits |
| `undeclared_expansion` | Record an owner decision for the added scope |
| `required_review_unavailable` | Restore the selected reviewer; self-review cannot replace it |
| `stale_evidence`, `dependency_stale` | Recheck the changed revision and affected dependencies |
| `pin_mismatch` | Restore the exact retained package/bundle, never switch silently |
| Rejected result | Repair the schema/transport; never truncate or infer a result |

Resume or replacement never resets counters.

## Uninstall says a version is still in use

Do not retire a compatibility path while any resumable or missing/unknown reference
remains. The private inventory retains exact legacy jobs, claims, packages and
stored recovery commands. Age, absent files and live flags alone prove no
abandonment. Retirement requires an owner-reviewed zero-reference report.

## `doctor` reports a worker bundle or job pin problem

Restore the exact version and integrity receipt named by the job. A package that
predates worker bundles retains its original capabilities; migration does not
invent a new bundle or convert its state. Keep the old runtime until references
permit retirement.

## A worker override is ignored

Overrides are bound to the selected bundle digest. Inspect
`agents --pin PIN agents list NAME` and `agents --pin PIN agents show NAME WORKER`,
then reconcile an explicitly enabled override against that definition.
Running jobs keep their original effective definitions.

## The CLI succeeded but imps is not complete

A successful `validate` command can report incomplete readiness. Read
`data.ready`, `data.outcome` and the evidence details from the pinned package.
Local readiness, hosted CI, merge and live deployment remain separate claims.

## Report a bug

Use the inherited [issue forms](https://github.com/seankoji-com/.agents/issues/new/choose).
Include a minimal reproduction, source/launcher/pin identities, T3/provider versions,
expected behavior and redacted errors.
