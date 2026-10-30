---
name: babysitter
description: "Repair and push pull request fixes through review and CI until merge-ready or concretely blocked. Use when asked to babysit, watch or monitor PRs; honor explicit read-only limits."
---

# Babysit PR

Many repos have AI review bots. They're helpful, even if they are not always
right.

## Default authority and outcome

The user's standing instruction for this skill is that invoking it authorizes
diagnosing and fixing every verified problem relevant to the requested PR,
running the required checks, committing the repairs and pushing them to that
PR's branch. Work toward merge readiness without asking again for routine repair
or push permission. This includes failing checks, review findings, conflicts and
missing PR acceptance work that can be completed within that scope. Continue
after each push until the latest head passes the applicable gates or a concrete
blocker needs user input.

Explicit instructions such as read-only, report-only, no edits or no push override
this default. A blocker report must identify what prevents further work and what
action or missing authority will unblock it. A failing check alone is work to
repair, not a reason to stop.

When delegating repairs, pass the authorized edit, commit and push scope to the
child. Do not turn an authorized repair assignment into a report-only brief.
Children still never watch PRs or exceed their assigned scope.

## Waiting

Never write your own watcher, polling loop, or `sleep` loop. Use one watcher
per PR: `watch_pull_request` in T3 Code, `pr-wait` everywhere else. Never run
both on the same PR. Every watcher on a GitHub account shares one rate limit.

### In T3 Code: `watch_pull_request`

Handle the existing checks and comments first. Then call
`watch_pull_request` and end your turn. T3 Code wakes you with a message when
a check fails, the required checks pass, someone comments or reviews, or the
branch conflicts.

- **Only the thread that owns the PR watches it.** If you are a delegated
  child task (such as a `delegate_task` child), never call
  `watch_pull_request`. The parent owns the PR. Do not watch PRs you are not
  working on.
- **A wake is news, not a merge decision.** Check the merge gate yourself.
- **Unwatch when you hand off.** A watched thread stays in Working and out of
  the user's inbox. When you stop (ready, blocked, or asking the user a question),
  call `unwatch_pull_request` first. A merge or close ends the watch on its
  own.
- **"Stopped watching, could not read it"** usually means GitHub's rate limit
  is used up. Run `gh api rate_limit --jq .resources.graphql` before you
  watch again. If `remaining` is near 0, wait for `reset` with one background
  command, then watch again. Never watch again in a tight loop.

### Everywhere else: `pr-wait`

Wait with `scripts/pr-wait` from this skill's directory (use its absolute
path).

```bash
pr-wait <pr> [--repo owner/name] [--until ready|green|any-change]
```

It prints one line per real event. It exits 0 when the `--until` condition is
met or the PR merges, 1 when it needs you (a required check failed, conflicts,
unresolved threads, PR closed), and 2 on bad input.

- `ready` (default): required checks green, and no unresolved threads. Use this to babysit.
- `green`: required checks only.
- `any-change`: exit on the first event.

In Claude Code, run it with the Monitor tool (`timeout_ms: 3600000`), so each
line wakes you. Without a monitor, run it as one long command. It ends on its
own.

Start it again after you push, after you handle an exit 1, and after a resume.
It remembers what it already reported, so nothing that arrived in between is
lost. If it says another pid already watches the PR, do not start a second one.
Kill the old one only if its events do not reach you.

If history exceeds the helper's single-page limit, it stops for manual inspection
rather than reporting readiness with feedback missing.

With either watcher: when an event needs no action, end your turn without a
message. Never post or say "still waiting".

## GitHub rate limits

`gh pr create`, `gh pr view`, and `gh pr checks` use GraphQL. When GraphQL is
used up, the REST limit is separate and usually still has room. Use
`gh api repos/<owner>/<repo>/pulls/<n>` to read a PR, and
`gh api repos/<owner>/<repo>/commits/<sha>/check-runs` for checks.

## Reviews

Confirm the target repository and work from its checkout. For repairs, run the
required checks, inspect the staged diff, commit explicit paths and push to the
explicit PR remote and branch. Distinguish code defects from infrastructure
failures and bound retries.

Assess checks on the current head and all unresolved feedback, including older
or outdated threads. Verify every bot finding against the current source before
changing code. Fix real findings and CI
failures, distinguish repository failures from infrastructure flakes, and reply
with a written reason when authorized to dismiss false positives.

If a review bot leaves feedback you believe is not worth addressing, reply with
a written reason and resolve the comment when authorized.

Screenshots and videos help as well, when you have a way to upload them.

Keep the PR at the size the user's goal needs. Review loops tend to grow a
PR one cheap-looking fix at a time. Fix real bugs in the intended case.
Decline the rest with a written reason, and list them as follow-ups:
unneeded tests, guards for edge cases that do not matter, extra integration
or compatibility, and small performance costs. Prefer the fix that deletes or
narrows code.

## Base branch and merging

Set every open PR in the babysitting scope to GitHub auto-merge when repository
rules and existing merge authority permit it, using the permitted merge method.
Keep required human approval and explicit no-merge limits in force. Do not promote
drafts merely to enable auto-merge. If enabling it could merge immediately, verify
that merge is already authorized before proceeding. Verify and report the resulting
auto-merge state or the specific blocker; do not silently omit a PR. Never bypass
protection or change repository settings to enable auto-merge.

Keep an eye on changes to `main` and rebase when needed. `pr-wait` reports when
new base commits touch this PR's files, and when the PR becomes BEHIND or DIRTY.
`watch_pull_request` reports conflicts only, so check for BEHIND yourself
before you call the PR ready.

If an overlapping PR makes this one obsolete, stop monitoring, report it to the
user, and ask before closing the PR unless closure was explicitly authorized.

If nothing has changed, stay quiet rather than posting filler comments. Stop
when `pr-wait` exits 0, or in T3 Code when the merge gate passes on the latest
head. Merge only when the user explicitly requested it;
otherwise report that the PR is ready. Right before a merge, run `git fetch` and
check the PR again. Never merge when it is BEHIND or DIRTY, or when base commits
that landed after the last green run touch this PR's files. Rebase, push, and
wait for green again.

## Outputs

Report PR URL/head, readiness or blocker, material repairs, auto-merge state
and the next action. Claim continued monitoring only while a supported watch is active.
In T3 Code, use `html_preview` then `html_render` for substantive multi-PR reports
and repair summaries; use readable text when native HTML is unavailable or the
result is brief.

## Boundaries

Preserve unrelated work and repository protections. Fix verified PR-related
problems; do not sweep unrelated improvements into the branch or weaken checks
to obtain a pass. Explicit status-only requests remain read-only. Respect
delegated child boundaries. This default does not authorize publishing comments,
merging, spending or infrastructure changes; reuse separate authority when it
exists and report any missing authority that blocks readiness. Follow the active
host's tooling and permission rules.
