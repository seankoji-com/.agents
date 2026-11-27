# Ledger

The `workflows/backlog-burn.ts` workflow keeps this ledger and returns it in the
run result. The tables below are the report contract: read the result, do not
retype the workflow's rows. The coordinator still writes the final report from
them.

Keep one markdown ledger for the run. Prefer an ignored directory in the session
worktree, for example `out/backlog-burn/ledger.md`; confirm it with
`git check-ignore`. If the repository has no suitable ignored path, use a
session-owned temporary directory and record its absolute path in the report.

## Header

```markdown
# Backlog burn — <owner/repo> — <YYYY-MM-DD>

Start count: N issues, N PRs
Current count: N issues, N PRs
Discovery cursor: <page/cursor or complete>
Unexamined issue and PR IDs: <IDs; never imply the backlog is fully classified>
Ready queue: <issue IDs, acceptance scope and overlap constraints>
Slots: <host ceiling and scope/evidence; run cap <=20; active leads/workers/reviewers;
child-slot allocations; available capacity; review headroom; contention limits>
Unused capacity: <specific reason and next discovery or dispatch action>
Implementation model and effort: <main thread's exact settings; explicit owner override if any>
Eligible reviewer route: <provider/model and lineage eligibility>
Board read: yes | no (<reason>)
Authority: standing merge on gates; ordinary evidence-based closures;
protected closures and material risk acceptance need owner review; live writes per action.
Ship plan and execution manifest: <parent plan and task/thread evidence>
Retrospective: pending | complete | incomplete; <history boundary, coverage,
remaining read/time budget, proposal URLs or drafts>
```

## Table

| Issue | Title | Class | Evidence / missing | PR | State | Next action | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |

Classes: `unexamined`, `dev-ready`, `decision`, `evidence`, `live-only`, `duplicate`,
`already-done`, `substantially-done`, `obsolete`, `low-value`, `in-flight`,
`hold` (owner-declared), `blocker` (agent cannot proceed).

States: `queued`, `dispatched`, `in-review`, `checks`, `mergeable`, `merged`,
`acceptance-pending`, `closed`, `question`, `blocked`.

Keep open PRs in a second table:

| PR | Title | Author | Head SHA | Class | Evidence | Owner / watch | Next action |
| --- | --- | --- | --- | --- | --- | --- | --- |

PR classes follow [the PR rules](pull-requests.md): `in-flight-elsewhere`,
`adopted`, `retire`, `ask`. For in-flight-elsewhere rows record the owner link,
the evidence it is live and the next trigger. For adopted rows record the
workflow's current-head review receipt (and coordinator watch receipt only when
a merge turn hands off `pending-review`). For closed rows record the evidence
comment and read-back state.

For dispatched work record the task/thread handle, bound worktree, base/head,
model/effort and scoped owner. For a question record the actual submitted prompt
or request receipt, its affected issue/action and the answer when received.
For pending PRs or runtime acceptance record the current gate and continuation
receipt or the exact unsupported route. A plan entry is not a dispatch receipt;
an assignee or stale branch is not verified active ownership.

For closures record the verified useful outcome, current evidence, retired
residue, closure comment and read-back state reason. Separate completed from
not-planned retirement; an unfixed retired defect stays described as unfixed.

## Delegate capacity

1. Target the maximum host-supported concurrency up to 20 active delegates
   across the entire run. Verify the host's concurrent limit and honor any
   smaller ceiling, including limits shared with other sessions.
2. When no ceiling is disclosed, work toward 20 incrementally. On a capacity
   rejection, record the observed current limit and queue the rejected task for
   retry when capacity becomes available. Do not repeat identical rejected calls
   or bypass the host. Capacity loss is not a code failure.
3. The workflow runs a flat shared delegate pool (`T3.within("delegates", { limit: capacity })`):
   every active implementer, repair worker and reviewer draws one slot from the
   same pool, and dispatched children start no nested subagents.
4. Passive PR check/merge waits and owner asks hold no delegate slot. Reserve
   active slots across implementation, repair and independent review so reviews
   are never starved behind waits.
5. Refill as active delegates finish. Because T3's forge listing caps at 100
   issues and 100 PRs with no continuation cursor, multi-pass continuation
   re-lists after closures, merges or owner answers to uncover newly visible
   work without inventing tasks to fill slots.
6. Before yielding, record active slots, unused-capacity reasons, pending
   retries, coverage (`complete` vs `partial`) and next action.

## Round log

After each question round, record the decisions and their consequences:

```markdown
## Round 1 — <date>

- #123: owner chose two-release compatibility → dispatch.
- #456: retired component verified in current source; closed not-planned with evidence.
- #457: useful outcome verified; optional checklist residue retired, no replacement issue.
- #789: split approved; filed #789a–c.
- #999: live write approved for <exact action>; executed and verified.
```

## Resume checklist

1. Refresh GitHub: issue states, PR heads, checks, reviews and threads.
2. Re-list open issues and PRs and reconcile the ledger against both live
   counts; mark stale rows. Classify new PRs and recheck in-flight-elsewhere
   owners under the PR rules.
3. Re-check every owned PR's current head and base; discard stale-head results.
4. Keep workflow-owned PR waits inside the workflow without adding a duplicate
   coordinator watch; confirm one coordinator watch only on PRs whose merge
   turn handed off `pending-review`, and release watches for merged or closed
   PRs. Hold no watch on in-flight-elsewhere PRs.
5. At the start of each pass, after the previous pass's work returns, and in
   the coordinator's handoff, reconcile active and reserved slots and refill
   capacity. Apply settled answers and dispatch ready work before submitting
   blocking questions. If the ready queue is empty, resume discovery from the
   cursor. At full delegate capacity, continue classification, investigation
   and owner questions, queueing ready fixes. Record receipts,
   unused-capacity reasons and questions unsent because dispatch required a yield.
   Keep the same issue owner and preserve the implementation model policy.
6. Report any ledger row that has no owner and no next action.
7. Resume the same ship plan and manifest; preserve retrospective coverage,
   cursors and budgets. An owner-question pause does not finish that stage.
   Record it as pending; missing authority or blocked filing for warranted
   proposals is incomplete, with drafts and an owner question. Newly filed target issues
   re-enter the queue without starting another retrospective or resetting budgets.

## Yield and completion audit

Record the reason for each yield: host-required continuation, actual unanswered
owner questions, or a terminal blocker. Registering a PR watch is not a
host-required yield by itself: the watch call comes last, after the pass. Preserve cursor, queued issue IDs, active
receipts and the first action on wake. Voluntary awaiting-owner requires no unexamined, ready, approved-but-undispatched,
investigable, unasked or actionable owned work. An owned PR waiting only on a
submitted question keeps its ownership (and any active `pending-review` watch)
through the pause. Work with a verified live owner elsewhere needs its owner
link, evidence and next trigger, not an assumed watch or hold.
Every residual item must instead have an explicit hold, a verified live owner
elsewhere or an actual unanswered question; silence and a status recommendation
do not qualify.

Zero requires fresh issue and PR lists below T3's 100-item caps (complete
coverage, zero item-read failures) and verified delivery or justified,
authorized retirement for every closure. A handback where every remaining item
is held, in flight elsewhere or awaiting a submitted question stays "not zero".
An owned PR, an unsubmitted question, an acceptance-pending issue or partial
coverage remains `not-finished` and retains its owner and next trigger.

## Handoff

The ledger stays with the task artifacts until the run ends. Because the worktree
may be pruned, the final report must contain the complete open-item tables, not
just a pointer to the ledger.

The final report states:

- before and after issue and PR counts at a stated time, and items opened during the run;
- merged PRs with commit SHAs, and PRs closed unmerged with their reasons;
- completed versus retired issues and why, and follow-ups filed;
- still-open items by class, owner and next trigger, including in-flight-elsewhere owner links;
- the ledger path, discovery coverage and task/watch receipts;
- models and effort, retrospective coverage and proposals. Preserve the ledger while any issue, PR, follow-up
filing or hold remains. Remove it only after the final report and any required
issue URLs are verified.
