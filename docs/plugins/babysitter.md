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

A run keeps going until every targeted PR has merged or needs a person:

1. **Quick pass.** Before any child starts, the thread merges each targeted PR that
   GitHub already allows: CLEAN, or UNSTABLE with every required check green, with
   resolved threads and no conflicts. It updates branches that are behind. Under
   *enable auto-merge on all PRs* it also arms GitHub's native auto-merge.
2. **Fixers, all at once.** Every PR with work left gets its own T3 child in a
   separate worktree, in parallel. That covers conflicts, failing checks, unresolved
   threads and requested changes. The brief lists every blocker the merge helper
   found, not only the first. The child fixes the branch and pushes. It may rebase
   and publish with `--force-with-lease` pinned to the head it fetched. It never
   merges. The model comes from the `workhorse` role in your
   [routing config](../getting-started.md#model-routing), cheapest tier first. Without
   a config the thread picks a cheap model itself. A child that gets stuck hands off
   to the next candidate, with no cap on rounds.
3. **Threads.** Before another merge attempt or watch, the coordinator inspects every
   unresolved thread at the current head, including outdated ones. It verifies the
   fix, posts an evidence-based reply and resolves the thread. Findings that need no
   change get a reply explaining why. Actionable minor findings still need fixes.
   A reply alone does not count as resolution. A refused action is reported at once.
4. **Land and watch.** GitHub's own requirements are the gate. Babysitter adds no
   review of its own unless you ask for review before landing. The thread merges each
   PR as soon as GitHub allows it, watches the rest, and refills fixers on every wake.
   It never ends a turn while a PR has fixable work and no child on it.

Through-merge requests default to **enable auto-merge on all PRs**, without another
question. The thread records that choice from your original request. You can
explicitly choose **leave auto-merge as set** (arm and clear nothing) or **ignore PRs
with auto-merge** (exclude those PRs). Inspect-only runs arm nothing. An armed
request never withholds a fixer push, resolution or permitted merge, and never
counts as progress while threads, conflicts or red checks remain.

Repo and org scope stays open throughout the active run. The thread refreshes
discovery on every wake or child completion and before yielding or handing back.
New matching PRs join automatically under your original authorization, with their
own action records and jobs. The initial list is never a frozen roster. Partial
discovery is reported as a gap; it cannot support an "all done" claim.

The thread keeps one table of the targeted PRs and posts it at the end of every turn.
Its shape, with made-up PRs:

| PR | Description | Not merged because |
|---|---|---|
| [owner/repo#12](https://github.com/owner/repo/pull/12) | Fix login redirect | 3 unresolved threads; failing check `lint`; fixer round 2 |
| [owner/repo#9](https://github.com/owner/repo/pull/9) | Bump parser | merged |

A green local test, an approved review and an actual merge are three different things.
The table reports only merges it has seen.

Thread resolution, the latest review state, required checks and mergeability are
separate gates. Resolving a thread does not remove a requested-changes review.
Babysitter never dismisses a review to clear that gate. If package health or job
ledger integrity blocks the supported workflow, it reports the exact failure and
stops writes for that PR. It does not bypass the workflow to land it.

## Operations

`doctor`, `pr`, `repo`, `org`. The
[entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/babysitter/entry.md)
names the file the agent loads for each one.

## Jobs and workers

Each PR that needs a child runs as its own [job](../architecture.md#whole-jobs), so one
PR's ledger and failures never hold up another. Roster listing, the quick pass, thread
resolution and the PR table stay in your thread.

- `babysitter/pr-maintainer` triages or repairs one PR in its own worktree, within the
  actions you authorized for that PR.
- `babysitter/pr-reviewer` runs only when you ask for review before landing. It
  reviews the final combined change at the pushed head, on a different known lineage
  from the fixer.

`scripts/validate_pr.py` accepts a PR only from your thread's own observation of its
current head, required checks, the complete list of resolved threads and the
authorized endstate. A worker reporting "pushed" or a queued auto-merge is not
acceptance. New PRs matching your repo/org scope need no renewed permission. A
different repository or organization, excluded PR, or action outside your request
needs new authority.

## Authorize the finish line

Invoking `pr`, `repo` or `org` authorizes babysitting through merge within that scope:
fixing and pushing to the targeted PR branches (rebases published with a pinned
`--force-with-lease`), updating behind branches, replying on and resolving their
threads, and merging them once GitHub allows it. The read-only example in
[Try it](#try-it) narrows that to inspection. A clean PR can merge in the quick pass
without a fixer, so use `repo` or `org` only when you mean every eligible PR there.
Repo/org runs include all authors and bots. Drafts and forks are left alone unless
you explicitly include them; the helper then uses `--include-drafts` or
`--include-forks`. Confirmed ownership by another active thread stays
visible; babysitter continues the other PRs without creating a competing writer.
Protected-branch rules still apply. Babysitter never uses admin bypass, never
dismisses reviews, and never force-pushes a base branch.

## Routine decisions

The brief and your earlier answers settle routine choices. Babysitter does not ask
you to select a default that the task already supplies:

| Event | What happens without a question |
|---|---|
| No auto-merge preference in a through-merge request | Enable it when the landing gates permit. |
| Another matching PR appears | Add it and continue maintenance. |
| A PR head moves | Fetch, integrate and revalidate in the isolated worktree, unless competing ownership is confirmed. |
| CI downloads or setup fail repeatedly | Stop identical retries after 3 attempts or 5 minutes, whichever comes first; diagnose and repair safe setup within scope. |

Questions are for a material product choice, missing access or secrets, a necessary
ownership transfer, or new authority. Repeated failures alone are not a reason to
hand back fixable work. Branch protection, worktree ownership and package/ledger
integrity remain gates.

## Limits

T3's native watches cover linked PRs, so they cannot discover new PRs while the
thread is idle. Discovery runs again on the next wake and before handoff. Persistent
discovery after handoff needs an explicitly requested host schedule; the thread
reports any idle discovery gap. Unit tests don't show how a given model behaves;
see [compatibility](../compatibility.md).

Jobs created through the shared CLI carry `policy.identity: observed`. Required reviewer executions, their subjects, and slots marked `independent_of_author` need verified host identity at acceptance. Authoring jobs enforce author-lineage checks from `policy.author_independence`, even if a slot omits its flag. Legacy jobs without the identity marker retain target-only acceptance semantics. A first author record cannot identify earlier authors of an unrecorded document. Direct cold-read stages cannot fall back to the coordinator.

## Choices and written strategies

Delegating maintenance asks for work/review choices upfront and reuses them on
automatic wakes. Ordinary maintenance adds no planning artifact or evaluator. An
actual written repair or landing strategy receives planning review before dependent
actions. Merge authority, requested final-head review and the coordinator's native
PR watch remain separate requirements.

See [planning review](../plan-review.md) for default triggers, model choices,
receipt freshness, fallback labels and requester reporting.
