# babysitter

A pull request is stuck: review comments, a red check, a conflict with the base
branch. babysitter fixes what you authorize, pushes to the PR branch, asks T3 to wake
it when something new happens, and keeps going until each PR merges or needs a person.
It reports a merge only after GitHub shows one.

## Try it

Start read-only, with one PR:

```text
$t3-babysitter pr https://github.com/OWNER/REPO/pull/NUMBER Inspect reviews and CI only. Report blockers; do not edit, post, push or merge.
```

When you want it landed, send the same URL without the restriction:

```text
$t3-babysitter pr https://github.com/OWNER/REPO/pull/NUMBER Babysit through merge.
```

`repo OWNER/REPO` and `org OWNER` widen the scope to every open PR there, which can
mean many branches and model calls. Send `$t3-babysitter doctor` first on a new
machine or provider.

## What you get

A run has three steps:

1. **Quick pass.** The thread merges every targeted PR that GitHub reports ready at
   its current head and tries to arm auto-merge on the rest, including PRs with open
   threads or conflicts. Where GitHub refuses, the thread merges the PR itself once it
   is ready.
2. **Fixers.** Each PR with work left (conflicts, failing checks, review comments)
   gets its own low-cost T3 child in a separate worktree. The child fixes the
   branch, replies to and resolves the threads it handled, and pushes. The model
   comes from the `workhorse` role in your [routing config](../getting-started.md#model-routing),
   cheapest tier first. A child that gets stuck hands off to the next candidate.
   `setup` makes the session model the only workhorse, so add cheaper models
   to that role before a large run.
3. **Watch.** The thread watches every open PR. When T3 wakes it for a new failure,
   comment or conflict, it sends the next fixer round, until each PR merges or needs
   a person.

The thread keeps one table of the targeted PRs and posts it again whenever one merges.
Its shape, with made-up PRs:

| PR | Description | Not merged because |
|---|---|---|
| [owner/repo#12](https://github.com/owner/repo/pull/12) | Fix login redirect | failing check `lint`; auto-merge armed; fixer round 1 |
| [owner/repo#9](https://github.com/owner/repo/pull/9) | Bump parser | merged |

A green local test, armed auto-merge and an actual merge are three different things.
The table reports only merges it has seen.

## Operations

`doctor`, `pr`, `repo`, `org`. The
[entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/babysitter/entry.md)
names the file the agent loads for each one.

## Jobs and workers

Multi-PR and repair work runs as one [job](../architecture.md#whole-jobs) with one
stage per PR. Roster listing, the quick pass and the PR table stay in your thread.

- `babysitter/pr-maintainer` triages or repairs one PR in its own worktree, within the
  actions you authorized for that PR.
- `babysitter/pr-reviewer` reviews the final combined change at the pushed head, on a
  different known lineage from the fixer.

`scripts/validate_pr.py` accepts a PR only from your thread's own observation of its
current head, required checks, resolved threads and the authorized endstate. A
worker reporting "pushed" or a queued auto-merge is not acceptance. More PRs, more
actions or more repairs than the plan allows are asked through the question picker.

## Authorize the finish line

Invoking `pr`, `repo` or `org` authorizes babysitting through merge within that scope.
The read-only example in [Try it](#try-it) narrows that to inspection. The quick pass
tries to arm auto-merge even while review threads are open, so on a repository
without a conversation-resolution rule a PR can land as soon as its checks pass. Use
`repo` or `org` only when you mean that wider scope. Protected-branch rules still
apply, and unknown or unsafe changes stay blocked.

## Limits

T3 watches PRs that already exist. Picking up future PRs across a repository or
organization needs a separately authorized scheduled sweep. Unit tests don't show how a
given model behaves; see [compatibility](../compatibility.md).
