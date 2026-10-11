# babysitter

Carry pull requests through review and CI.

## When to use it

A PR needs fixes and follow-up through review, CI or conflicts. Start with one
named PR; repository and organization scopes can involve many branches and costs.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt babysitter doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt babysitter pr https://github.com/OWNER/REPO/pull/NUMBER 'Inspect reviews and CI only. Report blockers; do not edit, post, push or merge.'
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-babysitter**
from `/` and append the same request instead.

## Operations

`doctor`, `pr`, `repo`, `org`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/babysitter/entry.md) names the file to load for each operation.

## What you get

Findings against the current PR head, check status and exact remaining blockers.
When you authorize maintenance, the agent fixes eligible problems and observes the
result. A green local test, armed auto-merge and an actual merge are different
outcomes. T3 owns the watch and wakes the thread for later events.

## Authorize the finish line

The example above requests inspection. To let it land the PR, state that scope:

```sh
t3-plugins prompt babysitter pr https://github.com/OWNER/REPO/pull/NUMBER 'Babysit through merge: fix review findings and CI, push to this PR branch, and merge once current-head requirements pass.'
```

Use `repo OWNER/REPO` or `org OWNER` only when you intend that wider scope. Protected
branch rules remain required. Unknown or unsafe changes stay blocked.

## Limits

T3 watches existing PRs. Discovering future PRs across a repository or organization requires a separately authorized scheduled sweep. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
