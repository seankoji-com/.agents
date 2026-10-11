# imps

Implement with revision-bound evidence.

## When to use it

A bounded bug fix or change needs a plan, current-revision checks, and an independent review.

## Try it

```sh
t3-plugins install imps
t3-plugins prompt imps doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/imps/current/entry.md and run:
run fix the failing date parser and verify locally
```

Replace sample repositories, paths, and tasks with your own.

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

A run ID, an evidence contract, copied artifacts, recorded child handles and a report.
The agent plans and executes the work; the gate validates the evidence. Capture a
binding before verification, then submit the check or inspection with that binding.
An edit makes earlier evidence stale. Pending child runs prevent readiness.

The CLI commands are `init`, `status`, `snapshot`, `check`, `evidence`, `review`,
`child`, `waive`, `note`, `policy`, `remote`, `validate`, `report`, `cancel`,
`recipe-scaffold`, `recipe-check` and `recipe-stamp`. JSON inputs use `--input FILE`.
The package's `core/schemas/submission-*.schema.json` files describe each input.
`validate` reports local readiness and the authorised outcome separately.

## Previous runs

State major version 1 is refused by this gate without conversion or writes.
Keep the previous installed version until its runs are finished. Use
`t3-plugins list` to find installed versions, then
`t3-plugins activate imps <previous-version>`. Read that version's entry through
`t3-plugins path imps`; use its `status`, `resume` or `cancel` operation with the
original run ID and state root. Activate the new version again when done.
Never hand-edit a run's version number. Activation changes only the selected package;
it does not migrate state. The [migration record](../imps-gate-migration.md) explains
the removed APIs and retained evidence boundaries.

## Limits

Use a direct edit for trivial work. imps earns its overhead when acceptance evidence, interruption recovery, or delegation matters. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
