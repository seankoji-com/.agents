# babysitter

Carry pull requests through review and CI.

## When to use it

A named PR, repository, or organization needs authorized maintenance and continued monitoring.

## Try it

```sh
t3-plugins install babysitter
t3-plugins prompt babysitter doctor
```

Paste the generated prompt into T3, then use an operation such as:

```text
Read ~/.local/share/t3-plugins/babysitter/current/entry.md and run:
pr https://github.com/OWNER/REPO/pull/NUMBER
```

Replace sample repositories, paths, and tasks with your own.

## Operations

`doctor`, `pr`, `repo`, `org`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/babysitter/entry.md) names the file to load for each operation.

## What you get

Current-head findings, verified fixes, observed merge state, or exact remaining blockers.

## Limits

T3 watches existing PRs. Discovering future PRs across a repository or organization requires a separately authorized scheduled sweep. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
