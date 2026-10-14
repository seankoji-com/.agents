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

A run has four steps:

1. **Quick pass.** Before any child starts, the thread merges each targeted PR whose
   current head is already clean: green checks, resolved threads, no conflicts. It
   arms nothing. An armed auto-merge would land a later fixer push before anyone
   reviewed it. If you asked for review before landing, it skips this pass.
2. **Fixers.** Each PR with work left (conflicts, failing checks, review comments)
   gets its own T3 child in a separate worktree. The child fixes the branch, replies to
   and resolves the threads it handled, and pushes. It never merges. The model comes
   from the `workhorse` role in your [routing config](../getting-started.md#model-routing),
   cheapest tier first; a child that gets stuck hands off to the next candidate.
3. **Review, then land.** After the last push, `babysitter/pr-reviewer` reviews the
   combined change at that exact head, on a different model lineage from the fixer.
   Only an approval at that head lets the thread merge, and the merge call names the
   head, so a later push can't slip through. Findings go back to the next fixer round.
4. **Watch.** The thread watches every open PR. When T3 wakes it for a new failure,
   comment or conflict, it starts the next round, until each PR merges or needs a
   person.

Two things stop it from fanning out:

- **No routing config.** Plain `t3-plugins setup` writes none. Without one, the thread
  asks you through the question picker before it starts any fixer. To create one, have
  the agent save T3's capabilities response to a file and run
  `t3-plugins setup --capabilities caps.json`. The starting config makes the session
  model the only workhorse, so add cheaper models to that role before a large run.
  An existing config is never replaced.
- **Auto-merge someone else armed.** A PR that already has auto-merge queued gets no
  fixer that pushes, because GitHub would land the push before review. The thread
  asks you to disable it first.

The thread keeps one table of the targeted PRs and posts it again whenever one merges
or a blocker changes. Its shape, with made-up PRs:

| PR | Description | Not merged because |
|---|---|---|
| [owner/repo#12](https://github.com/owner/repo/pull/12) | Fix login redirect | failing check `lint`; awaiting review gate; fixer round 1 |
| [owner/repo#9](https://github.com/owner/repo/pull/9) | Bump parser | merged |

A green local test, an approved review and an actual merge are three different things.
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

Invoking `pr`, `repo` or `org` authorizes babysitting through merge within that scope:
fixing and pushing to the targeted PR branches, replying on them, and merging them once
the review gate passes. The read-only example in [Try it](#try-it) narrows that to
inspection. A clean PR can still merge in the quick pass without a fixer or reviewer,
so use `repo` or `org` only when you mean every eligible PR there. Drafts, forks and
other authors' PRs are left alone unless you name them. Protected-branch rules still
apply; babysitter never uses admin bypass, dismisses reviews or force-pushes.

## Limits

T3 watches PRs that already exist. Picking up future PRs across a repository or
organization needs a separately authorized scheduled sweep. Unit tests don't show how a
given model behaves; see [compatibility](../compatibility.md).
