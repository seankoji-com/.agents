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

A babysitting run works in three steps:

1. **Quick pass.** The thread merges every targeted PR that GitHub reports ready at
   its current head and arms auto-merge on the rest, including PRs with open threads
   or conflicts.
2. **Fixers.** Each PR with work left (conflicts, failing checks, review comments)
   gets its own low-cost T3 child in a separate worktree. The child fixes the
   branch, replies to and resolves the threads it handled, and pushes. The model
   comes from the `workhorse` role in your [routing config](../getting-started.md#model-routing),
   cheapest first. A child that gets stuck hands off to the next candidate.
3. **Watch.** The thread watches every open PR. When T3 wakes it for a new failure,
   comment or conflict, it sends the next fixer round, until each PR merges or needs
   a person.

The thread keeps one table of the targeted PRs and posts it again whenever one merges:

| PR | Description | Not merged because |
|---|---|---|
| [owner/repo#12](https://github.com/owner/repo/pull/12) | Fix login redirect | failing check `lint`; auto-merge armed; fixer round 1 |
| [owner/repo#9](https://github.com/owner/repo/pull/9) | Bump parser | merged |

A green local test, armed auto-merge and an actual merge are different outcomes; the
table reports only merges it has observed.

## Authorize the finish line

Invoking `pr`, `repo` or `org` authorizes babysitting through merge within that
scope. The [Try it](#try-it) example asks for inspection only, which keeps the run
read-only. To land the PR, drop that restriction:

```sh
t3-plugins prompt babysitter pr https://github.com/OWNER/REPO/pull/NUMBER 'Babysit through merge.'
```

Auto-merge is armed even while review threads are open, so in a repository without
a conversation-resolution rule a PR can land once its checks pass. Use `repo
OWNER/REPO` or `org OWNER` only when you intend that wider scope. Protected branch
rules remain required. Unknown or unsafe changes stay blocked.

## Limits

T3 watches existing PRs. Discovering future PRs across a repository or organization requires a separately authorized scheduled sweep. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.
