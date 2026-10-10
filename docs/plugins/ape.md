# ape

Find ideas that transfer to your project.

## When to use it

You want to learn from a named repository or discover several candidates for a specific local gap.

## Try it

```sh
t3-plugins install ape
t3-plugins prompt ape doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/ape/current/entry.md and run:
study https://github.com/python/cpython testing strategy
```

Replace sample repositories, paths, and tasks with your own.

## Operations

`doctor`, `forage`, `study`, `clean`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/ape/entry.md) routes each operation to its focused playbook.

## What you get

A source-pinned report with adopt, adapt, and reject decisions, plus bounded experiments.

## Limits

Cleanup accepts only workspaces carrying a matching `.ape-workspace.json` marker
from the initializer. Unmarked legacy folders are left untouched; inspect and archive
them manually before creating a new workspace. Initialization does not adopt existing data.

Research stays read-only in the current project. It never executes third-party code or silently starts implementing recommendations. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
