# Ledger

Keep one markdown ledger for the run. Prefer an ignored directory in the session
worktree, for example `out/backlog-burn/ledger.md`; confirm it with
`git check-ignore`. If the repository has no suitable ignored path, use a
session-owned temporary directory and record its absolute path in the report.

## Header

```markdown
# Backlog burn — <owner/repo> — <YYYY-MM-DD>

Start count: N
Current count: N
Board read: yes | no (<reason>)
Authority: standing merge on gates; duplicate auto-close; other closures batched;
live writes per action.
Ship plan and execution manifest: <parent plan and task/thread evidence>
Retrospective: pending | complete | incomplete; <history boundary, coverage,
remaining read/time budget, proposal URLs or drafts>
```

## Table

| Issue | Title | Class | Evidence / missing | PR | State | Next action | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |

Classes: `dev-ready`, `decision`, `evidence`, `live-only`, `duplicate`,
`obsolete`, `in-flight`, `hold` (owner-declared), `blocker` (agent cannot proceed).

States: `dispatched`, `in-review`, `checks`, `mergeable`, `merged`, `closed`,
`question`, `blocked`.

## Round log

After each question round, record the decisions and their consequences:

```markdown
## Round 1 — <date>

- #123: owner chose two-release compatibility → dispatch.
- #456: owner confirmed wontfix → close with evidence.
- #789: split approved; filed #789a–c.
- #999: live write approved for <exact action>; executed and verified.
```

## Resume checklist

1. Refresh GitHub: issue states, PR heads, checks, reviews and threads.
2. Reconcile the ledger against the live count; mark stale rows.
3. Re-check every open PR's current head and base; discard stale-head results.
4. Confirm one watch per open PR; release watches for merged or closed PRs.
5. Continue the oldest actionable row first; do not re-ask a settled question.
6. Report any ledger row that has no owner and no next action.
7. Resume the same ship plan and manifest; preserve retrospective coverage,
   cursors and budgets. An owner-question pause does not finish that stage.
   Record it as pending; missing authority or blocked filing for warranted
   proposals is incomplete, with drafts and an owner question. Newly filed target issues
   re-enter the queue without starting another retrospective or resetting budgets.

## Handoff

The ledger stays with the task artifacts until the run ends. Because the worktree
may be pruned, the final report must contain the complete open-item table, not
just a pointer to the ledger. Preserve the ledger while any issue, PR, follow-up
filing or hold remains. Remove it only after the final report and any required
issue URLs are verified.
