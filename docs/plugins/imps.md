# imps

Implement with revision-bound evidence.

## When to use it

A failing behavior needs fixing, or a small feature has clear acceptance criteria.
Use a direct request for a trivial edit; use imps when current checks, independent
review or interruption recovery justify saved run state.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt imps doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt imps run 'Fix the date parser: reject 31 April with a useful error. Add a regression check. Verify locally without committing or publishing.'
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-imps**
from `/` and append the same request instead.

## Operations

`doctor`, `run`, `resume`, `status`, `cancel`, `verification-init`, `blast-radius`, `audit`, `issues`, `prs`, `checklist`, `discussion`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/imps/entry.md) names the file to load for each operation.

Free-text starts `run`. Issue numbers select `issues`; a GitHub Discussion URL
selects `discussion`; an existing Markdown path selects `checklist`. The checklist
helper parses claims and criteria without executing commands. Checks and subsequent
remediation run only within the operator's authorization.

`--personas` adds architecture, edge-case, operations, acceptance, and UX reviews.
The core tracks each perspective as a required, revision-bound review. It supplements
the default independent review. Discussion input retains its source and seeds the
normal run; posting a summary is a separately authorized action.

Install the `t3-imps` adapter using the [slash commands guide](../slash-commands.md)
to discover this same entry through supported provider skill integrations. Follow
the guide's per-provider discovery and live-verification steps.

## What you get

You receive a run ID, current validation report and paths to copied evidence.
The report distinguishes local readiness from the authorized remote outcome.
If a check or review is missing, failed or stale, it names the remaining work.
Keep the run ID and state root to [resume later](../first-workflow.md#resume-inspect-or-stop).

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

Use a direct edit for trivial work. imps earns its overhead when acceptance evidence, interruption recovery, or delegation matters. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
