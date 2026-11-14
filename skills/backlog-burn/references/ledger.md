# Ledger

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
the evidence it is live and the next trigger. For adopted rows record the watch
receipt. For closed rows record the evidence comment and read-back state.

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

1. Target the maximum host-supported concurrency up to 20 delegates across the
   entire run. Verify the host's concurrent limit, its scope and existing occupied
   slots. A batch-creation limit does not establish concurrent capacity. Honor
   any smaller host ceiling, including limits shared with other sessions.
2. When no ceiling is disclosed, work toward 20 incrementally. On a capacity
   rejection, record the observed current limit and queue the rejected task for
   retry when capacity becomes available. Do not repeat identical rejected calls
   or bypass the host. Capacity loss is not a code failure.
3. Count every delegate the run starts against its cap and any host pool it shares,
   including nested leads, workers, reviewers, investigations, issue-filing and
   retrospective tasks. Allocate each
   lead an explicit maximum number of child slots in its brief; a lead cannot
   exceed that allocation. Charge reserved child slots before dispatch, not only
   after a child appears. Require descendant task receipts and slot releases.
   Allocate an eligible-reviewer slot per lead, or specify that a lead with no
   child slots returns to the coordinator for review.
4. Allocate slots between implementation, investigation and eligible review so
   reviews can run. Reconcile active tasks and reclaim unused child reservations
   only after the lead finishes or confirms it will start no further children.
   Keep allocated plus
   unallocated active slots within the effective cap; avoid counting a running
   child twice inside its reservation.
5. Refill on completion, answer and wake. If the ready queue empties, discover
   more work. Use maximum capacity when useful independent authorized work is
   available, without inventing work to fill slots. Reduce actual use only for
   host limits, required review headroom, overlapping ownership/shared writers,
   concrete resource contention or insufficient independent work.
6. Before yielding, record active and reserved slots, unused-capacity reasons,
   pending retries, discovery cursor and next action. Full capacity still permits
   coordinator classification, investigation and owner questions. Follow mandatory
   host yields and retain the same continuation and manifest.

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
4. Confirm one watch per owned PR; release watches for merged or closed PRs.
   Hold no watch on in-flight-elsewhere PRs.
5. On every completion, PR notification, answer or continuation wake, reconcile
   active and reserved slots and refill capacity. Apply settled answers and dispatch ready
   work before submitting blocking questions. If the ready queue is empty,
   resume discovery from the cursor. At full delegate capacity, continue classification,
   investigation and owner questions, queueing ready fixes. Record receipts,
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
receipts and the first action on wake. Voluntary awaiting-owner requires no
unexamined, ready, approved-but-undispatched, investigable, unasked or actionable
owned work. An owned PR waiting only on a submitted question keeps its watch and
ownership through the pause. Work with a verified live owner elsewhere needs its owner link, evidence
and next trigger, not an assumed watch or hold.
Every residual item must instead have an explicit hold, a verified live owner
elsewhere or an actual unanswered question; silence and a status recommendation
do not qualify.

Zero requires fresh paginated issue and PR lists and verified delivery or
justified, authorized retirement for every closure. A handback where every
remaining item is held or in flight elsewhere stays "not zero". An owned PR,
an acceptance-pending issue or an unavailable continuation remains unfinished
and retains its owner and next trigger.

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
