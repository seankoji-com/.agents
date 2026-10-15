# imps

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
worker's claim does not. `doctor`, `status` and `verification-init` stay direct. A
single bounded change can stay one direct run.

`prs` pins babysitter inside the same job and loads it through
[`--job JOB path babysitter`](../cli.md#pinned-job-paths). For a job, `status` prints
the overview and `resume` starts from it.

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

## Limits

imps costs more turns than a direct request. It pays off when you need the evidence,
when the work may be interrupted, or when another model should review it. The unit
tests cover the state engine, not whether a given model follows the workflow; see
[compatibility](../compatibility.md).

Jobs created through the shared CLI carry `policy.identity: observed`. Required reviewer executions, their subjects, and slots marked `independent_of_author` need verified host identity at acceptance. Authoring jobs enforce author-lineage checks from `policy.author_independence`, even if a slot omits its flag. Legacy jobs without the identity marker retain target-only acceptance semantics.
