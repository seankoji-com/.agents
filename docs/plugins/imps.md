# imps

Choose Open PR, Tagged Version or Verified in Prod unless already supplied. The scoped agreement covers exact chains, actions, destinations and checks. Open PR needs a real linked current-head reviewed/green PR; later targets need the repository's release/distribution or named live deployment evidence. Source gates and queued workflows do not complete a remote endpoint. Unchanged repair/resume reuses the agreement and remaining budgets.

imps turns one bounded task into a plan with numbered requirements, makes the change,
runs the checks it planned, and gets an independent review. Every check is tied to the
revision it ran on. If the agent edits a file afterwards, the check goes stale and the
report says so. For a one-line edit, ask the agent directly instead.

## Try it

In a T3 thread attached to your repository, check readiness first:

```text
$t3-imps doctor
```

Doctor runs `cli.py doctor` to check Python, Git, the state root and the learnings
load, then asks T3 which providers can run child tasks. Its only write is one temporary
file inside an existing state root, removed straight away. If the state root does not
exist yet, doctor writes nothing, not even to a parent directory, and still passes: the
first run creates it. It adds an advisory `os.access` answer for the nearest existing
parent. If the state root is a symlink, the file goes in the directory it points to; a
broken symlink fails.

Then give it a task with a finish line and a limit:

```text
$t3-imps run Fix the date parser: reject 31 April with a useful error. Add a regression check. Verify locally without committing or publishing.
```

No slash menu? `t3-plugins prompt imps run '…'` prints the same request as a line to
paste. [Your first imps run](../first-workflow.md) walks through one end to end.

## What you get

- the change, in your working tree;
- a run ID and state root, to [resume later](../first-workflow.md#resume-inspect-or-stop);
- a validation report that maps each requirement to its check or review and the
  revision it ran on, with paths to the saved output;
- every missing, failed or stale check named, with what's left to do.

The report keeps local readiness separate from anything remote you authorized, such
as a PR or a merge. A job adds a job ID and an overview of every stage.

## Operations

`doctor`, `run`, `resume`, `status`, `cancel`, `verification-init`, `blast-radius`,
`audit`, `issues`, `prs`, `checklist`, `discussion`. The
[entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/imps/entry.md)
names the file the agent loads for each one.

imps picks the operation from what you send. Free text starts `run`. Issue numbers
select `issues`, a GitHub Discussion URL selects `discussion`, and a path to an
existing Markdown file selects `checklist`. The checklist helper parses claims and
criteria without running commands; checks and fixes run only as far as you authorize.

`--personas` adds architecture, edge-case, operations, acceptance and UX reviews on
top of the default independent review. Each is tracked as a required review tied to
the revision. A Discussion keeps its source and seeds a normal run; posting a summary
back needs separate permission.

## Jobs and workers

Multi-stage work runs as one [job](../architecture.md#whole-jobs). Your thread stays
the coordinator and fresh T3 tasks run the `imps/stage-executor`,
`imps/investigator`, `imps/auditor` and `imps/reviewer` workers. Each engineering
stage keeps its own gate run, and that run's `validate` decides acceptance; a
worker's claim does not. `doctor` and `status` stay direct. Verification-init reviews authored facts and
recipe decisions before execution; scaffold/check remains direct. A single bounded
change can stay one direct run.

`prs` pins babysitter inside the same job and loads it through
[`--job JOB path babysitter`](../cli.md#pinned-job-paths). For a job, `status` prints
the overview and `resume` starts from it.

## Plan and conclusion review

Before substantive work, approve exact work/reviewer chains, options and the scoped
path together. Aliases and unchanged resumes reuse that agreement and remaining
budgets. A material expansion holds only its dependent action for a scoped decision.

Audit, investigation and blast-radius review their final integrated conclusions,
including zero findings and no-change recommendations. Initial run/issues/checklist/
discussion plans are reviewed before execution when they contain a write, multiple
stages or a synthesis output. Verification-init reviews the authored launch,
feature selection, drive and cleanup decisions before those steps run.

A separate planning job records the actual review mode, rounds and findings against
the original request, criteria and source bytes. Missing or stale receipts block
readiness. Later engineering and persona reviews retain their own stricter gates.
Planning review grants no permission to execute a command or publish a change.
Raw lookups, deterministic scaffold/check and unchanged reviewed recipes add no
new review. Historical runs retain their evidence as legacy-unreviewed.

## Previous runs

State major version 1 is refused by this gate without conversion or writes.
Keep the previous installed version until its runs are finished. Find its version
in the installation receipt. If `t3-plugins path imps` prints
`<prefix>/imps/current/entry.md`, the version folders are in `<prefix>/imps/`,
alongside `current/`. Then use
`t3-plugins activate imps <previous-version>`. Read that version's entry through
`t3-plugins path imps`; use its `status`, `resume` or `cancel` operation with the
original run ID and state root. Activate the new version again when done.
Never hand-edit a run's version number. Activation changes only the selected package;
it does not migrate state. The [migration record](../imps-gate-migration.md) explains
the removed APIs and retained evidence boundaries.

### Upgrading a whole job

A whole job pins its installed packages. Activating a newer version leaves those
pins unchanged. If a required plan revision reaches an older package's 16 or 64 MiB
state ceiling, keep the complete job and old package intact. New packages allow
256 MiB of job state, including retained plan snapshots; input and artifact limits
remain unchanged. This is still a finite ceiling, not a guarantee that every job fits.

After every owned task is reconciled and its result ingested, record an owner
decision scoped to `plan:<revision-id>` through the pinned package. From the
reviewed newer installed package, run:

```sh
python3 "$NEW_PACKAGE/shared/job_cli.py" upgrade-package \
  --state-root "$JOBS" --job "$JOB_ID" \
  --prefix "$PREFIX" --agents-root "$AGENTS_ROOT" --input upgrade.json
```

The input contains `caller` from the existing job, `dependency_key`,
`expected_state_sha256` for the exact current `job.json`,
`expected_package_digest` from the new installation receipt, and
`revision: {id, owner_decision_id, reason}`. The chosen dependency must resolve to
the executing package in the same installation. The command verifies both sets
of package files and worker bundles and keeps an immutable, private copy of the
old state under `migrations/`, named by its hash.

The job ID, evidence history, handles, findings, decisions and repair counters
survive. Dependent acceptance becomes stale and requires fresh validators.
Resolve the new pinned path with `t3-plugins --job "$JOBS/$JOB_ID/job.json" path imps`
and use its receipt digest for subsequent caller metadata. A changed state hash,
missing owner decision, pending work, wrong installation or altered package
refuses the upgrade. Ordinary commands still refuse an unpinned package.
Older packages cannot read a job that has grown beyond their ceiling. Never
patch installed code, truncate history or change a pin by hand.

## Limits

imps costs more turns than a direct request. It pays off when you need the evidence,
when the work may be interrupted, or when another model should review it. The unit
tests cover the state engine, not whether a given model follows the workflow; see
[compatibility](../compatibility.md).

Jobs created through the shared CLI carry `policy.identity: observed`. Required reviewer executions, their subjects, and slots marked `independent_of_author` need verified host identity at acceptance. Authoring jobs enforce author-lineage checks from `policy.author_independence`, even if a slot omits its flag. Legacy jobs without the identity marker retain target-only acceptance semantics. A first author record cannot identify earlier authors of an unrecorded document. Direct cold-read stages cannot fall back to the coordinator.

See [planning review](../plan-review.md) for default triggers, model choices,
receipt freshness, fallback labels and requester reporting.
