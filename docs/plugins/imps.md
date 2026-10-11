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

`doctor`, `run`, `resume`, `status`, `cancel`, `verification-init`, `blast-radius`, `audit`, `issues`, `prs`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/imps/entry.md) names the file to load for each operation.

## What you get

A run ID, state records, and a report distinguishing completion from blockers.

## Limits

Use a direct edit for trivial work. imps earns its overhead when acceptance evidence, interruption recovery, or delegation matters. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
