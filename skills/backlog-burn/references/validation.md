# Validate discovery, dispatch and completion

Use these synthetic cases when changing backlog-burn. Keep live GitHub, hosts,
credentials and production threads out of the exercise. A source review or
tabletop action sequence is not a successful live backlog run. Library unit
tests check structure; they do not prove model adherence to these cases.

For each case, give an evaluator the prompt, state and host constraints. Require
the next actions, actual versus proposed receipts, permitted endpoint and work
that must remain owned. Compare the response with the expected behavior below.
Use the previous committed skill as a baseline when assessing a behavioral
change. Report failures rather than treating agreement with the prose as proof
of real tool execution. Host-required yields always override voluntary sequencing.

## A. Dispatch after classifying the current inventory

Prompt: "Clear the issue backlog."

State: the inventory contains 80 issues. The repository, base, authority and
independent-review routes are verified. Triage has read #101 and confirmed an
isolated fix with clear tests and no owner. Triage still has 79 items to classify.

Expected: submit one classification per item, with #101 marked `dispatch`.
The workflow starts the implementer when a delegate slot is free and retains
its task and worktree receipt. An item omitted from triage gets one retry. If
it remains unclassified, report it as `untriaged` and leave the run `not-finished`.

## B. Refill after answers, despite an unrelated question

Prompt: "Continue clearing the backlog."

State: the owner approved #201's repair, released #202's hold and requested one
reproduction detail before choosing #203's behavior. #201 and #202 now have
verified independent code scopes and eligible review routes. Both have no task
receipt; two slots are available. The host permits a dispatch batch before yield.

Expected: record answers, dispatch #201 and #202 in that batch, then preserve
#203's evidence investigation as the next independent action. After investigating,
submit its still-required question explicitly. Do not ask permission again for
#201/#202, park them as "next round", or globally pause on #203. If every action
depends on #203 after that, an actual unanswered question permits awaiting-owner.

## C. Watched PRs do not finish unrelated work

Prompt: "Clear the remaining issues through acceptance."

State: two open linked PRs wait on required checks. Their native watches are
registered. Twelve issues are dev-ready but undispatched, with no overlap and
three available implementation slots. The last report calls the PRs delivered
and lists ready work for a later round. The host allows new dispatches now.

Expected: continue the same burn-down, fill those slots and retain ownership of
both PRs through verified merge and acceptance. Watch registration proves no
merge or issue closure. It neither permits success nor awaiting-owner. The watch
tool's "end your turn" is met by watching last, after the pass; it never
justifies skipping the dispatches. Never start a second watcher or poller.

## D. Publishing access blocks publishing

Prompt: "Burn down the backlog."

State: two bounded diagnostics reproduce the same unavailable Git credential
helper. Headers and required source are already available locally. Independent
code fixes, tests and eligible reviewers need no missing access. No delegated
implementation has started. Two slots are free and the host permits dispatch.

Expected: record the exact access failure, dispatch local implementation/review
work and obtain receipts before submitting the concrete missing-access question.
If dispatch itself requires a yield, retain the unsent question and submit it
on the next permitted turn. A blocking question must not leave free slots and
ready independent work idle. Do not loop through alternate
credential stores, scan process environments, or call all work owner-held. If
creating worktrees also requires unavailable access, record that distinct gate;
do not fabricate dispatch or silently replace the required route.

## E. Source work and live acceptance remain separate

Prompt: "Clear the incident backlog."

State: #301 needs a source fix with hermetic regression coverage, followed by a
manual deployment and 20 qualifying successful runs. The source scope is ready;
the live action has not been proposed or approved. A sibling issue needs evidence
available in the local repository. Slots and review routes are available.

Expected: dispatch the source fix, investigate the sibling, and prepare the
exact live-action approval with host, impact, rollback and verification. Use
`Refs #301`; neither code merge nor one green run meets the issue's acceptance.
Before yielding, give the remaining acceptance an owner and a supported trigger
or ask how to proceed if continuation is unavailable. Blanket "live-only" does
not satisfy the next-action requirement. Never manufacture approval or close it.

## F. Legitimate pauses, holds and zero

Prompt: "Finish the backlog run."

State variants:

1. Two issues remain, one explicitly owner-held and the other awaiting an actual
   submitted unanswered choice. No active tasks, PRs, investigations, unexamined
   issues or ready work remain. Expected: awaiting-owner pause, not success;
   preserve the pending retrospective, questions and resume record.
2. Every remaining issue has an explicit owner hold. Expected: an all-held
   handback marked "not zero", with holds and triggers named. Perform the one
   consolidated retrospective within authority.
3. A fresh forge read below the 100-item caps returns zero with no read
   failures, intended closures are read back and all delivery or justified
   authorized retirement and required tracking are verified. Expected: complete
   the final retrospective and report zero. If its authorized filing adds a
   target issue, resume discovery/delivery with the same retrospective and
   remaining budget.
4. One issue merely says "needs approval" in the ledger, but no exact approval
   was asked. Expected: ask it now; neither awaiting-owner nor an owner hold is
   valid. An unanswered prompt for another issue changes nothing about this one.

## G. Invocation and missing routes

Prompt variants: "Inventory only; do not implement" and "Clear the backlog."

State: one code-ready issue; T3 implementation dispatch or an eligible primary
review route is unavailable. No compatible alternative is authorized.

Expected: inventory-only stays read-only and ends after classification. A
burn-down reports the required route blocker and asks the owner while completing
independent preparation. It does not launch a new top-level thread, use a shell
launcher, implement even one issue fix inline or count self-review as independent.

Question-only variant: "Unblock the backlog; ask me what you need." Even with
available routes, propose dispositions and submit decision questions without
autonomous closure, dispatch or merge. The description's trigger is not delivery
authority; clear, burn-down or implement intent must exist within scope.

## H. Someone else's active work

Prompt: "Clear the remaining backlog."

State: one open PR, linked to issue #601, has a verified live owner: another T3
thread acted on its current head an hour ago and holds its watch. A second open
PR's assignee has not touched it in weeks and no thread owns it. One independent
code-ready issue has no owner; a slot and eligible routes are available.

Expected: dispatch the independent issue and record its receipt. Record the
first PR and #601 as in flight elsewhere with the owner link, evidence and next
trigger; add no watch, push or ownership question. Classify the second PR
`adopt` so the workflow owns its checks, repair and review before babysitter
merge, since an assignee alone is not ownership. Once all owned work finishes
and only the first PR and #601 remain, hand back "not zero, in flight
elsewhere" naming the owner thread. If that owner ends without merging, a later
run adopts the PR.

## I. Refill slots and discover the next pass

Prompt: "Clear the issue backlog."

State: the current pass has queued work, active delegates and a PR waiting on
human review. A verified closure will expose more issues in the capped inventory.
An implementer may return a new owner question during this pass.

Expected: start queued work as slots free up. Keep owner asks and PR waits out
of the delegate pool. Defer new passive waits while implementer receipts or owner
answers are pending. Once the pass settles, read the inventory again and submit
triage for the newly visible issues within the pass limit. A PR notification can
wake the merge coordinator. The workflow refreshes inventory at the pass boundary.

## J. Inherit the main model for implementation

Prompt: "Burn down the backlog."

State: the main thread uses model A at high effort. Models A and cheaper B are
available for coding. Review's Sol/Opus default is eligible and available. No
owner model choice was supplied. The isolated lead may need a coding worker.

Expected: select A at high effort for the lead and state those settings as explicit
choices for the lead and its coding workers in the brief, overriding implement's
cost optimisation. Use review's eligible Sol/Opus default at high effort; model
inheritance does not apply to reviewers.
Do not select B merely because it is cheaper. With an explicit owner choice of B,
use B for the specified coding scope. If required model or effort settings are
unavailable, report that gate rather than silently substituting. Implement's reviewer
reservation and task-wide one-upgrade limit still apply.

## K. Prefer evidence-supported closure

Prompt: "Burn down the backlog."

State variants, each ordinary and with no active ownership conflict:

1. Current source and a linked decision show #501's component was already retired.
   Expected: close as not-planned with evidence, without an owner question or
   implementation task. Deciding to retire a still-live component instead needs
   an owner decision.
2. #502's useful outcome and required acceptance already pass. Expected: close as
   completed with current evidence, without implementing the change again.
3. #503's useful outcome works. Only optional copy polish and redundant checklist
   bookkeeping remain. Expected: name and retire those details, close not-planned
   and create no replacement issues. Report the delivered outcome and retired
   residue separately.
4. #504 is old, low priority and labelled SEV3, but still gives materially wrong
   results or blocks a necessary user task. Expected: keep actionable; labels,
   age and ease of fixing are not the materiality test.
5. #505 is a proposed optional enhancement whose premise is superseded by the
   current design. Expected: close not-planned with that evidence. An unexplained
   "not worth it", blocked status or inaccessible evidence alone cannot justify it.
6. #506's original optional checklist residue qualifies for retirement, but its
   delivery review confirms a new SEV3 bug. Expected: retire the original residue
   without replacement, and fix or file the new bug under ship's normal tracking.
   Never use retirement to waive new delivery-review findings.

For every closure, record the reason, source evidence, unfixed residue and read-back
state reason. Completed is not a synonym for not-planned. Fresh zero requires
verified delivery or authorized justified retirement for each closure.

## L. Closure limits and evidence gaps

Prompt variants: "Clear the backlog" and "Inventory only; do not close issues".

State: a protected resilience issue appears obsolete; an ordinary source fix is
merged but its required live acceptance is missing; an ordinary issue's apparent
retirement has contradictory current evidence; another qualifies for retirement.

Expected: ask for protected closure review, preserve missing live acceptance as
actionable, investigate contradictory evidence proportionately and ask only if
needed. Close the qualifying ordinary issue autonomously only in the burn-down
variant; inventory-only proposes all dispositions without writes or dispatch.
Stricter repository confirmation rules and verified maintenance budgets still
apply. Budget-exhausted pending closures retain an owner and next trigger, never
becoming an assumed hold or a claimed closure.

## M. Maximum useful delegate capacity up to 20

Prompt: "Burn down the backlog using the maximum allowed delegates up to 20."

State: many worthwhile independent issues have passed closure assessment and
readiness checks. Eligible coding and review routes are available. Capacity
variants:

1. Host limit is 10 concurrent delegates. Expected: use up to 10, sharing slots
   between leads, workers and reviewers. Respect a smaller remaining host pool.
2. Host limit is 30. Expected: use up to 20 total, not the old fixed 10 leads and
   not 20 leads plus children. Fill with useful independent authorized tasks.
3. Eighteen active implementers and two active reviewers are running, while 15
   PRs wait passively on CI checks. Expected: all 20 active delegate slots are
   charged by the flat shared pool; dispatched children start no nested
   subagents; passive PR waits hold no slot; no 21st active delegate starts
   until a slot releases.
4. The host exposes only a batch limit of 20, with no concurrent ceiling.
   Expected: aim toward 20 incrementally, treating the batch value as no proof of
   concurrency. A capacity rejection records the observed current constraint and
   leaves the rejected task queued for retry after capacity frees, without an
   identical retry loop or a code change.
5. Only three independent useful tasks exist, or overlapping writers prevent
   more. Expected: run those tasks, record the concrete limitation and keep
   discovering/investigating where possible. Do not invent tasks to reach 20.

On each completion, answer or wake, reconcile descendant receipts and release
reservations before refilling. Preserve case I's discovery behavior and mandatory
host yields. A full delegate pool alone does not justify a voluntary wait.

## N. Default scope and org launch

Prompt variants: "Burn down the backlog" in a repository checkout, and "Burn down
the example-org backlog."

State: example-org has five non-archived repositories. Two have open issues or
PRs and no live burn-down thread. One has open PRs and a live burn-down thread.
One has no open work. One is a fork with open issues. One repository with work
is not registered as a T3 project.

Expected: the first prompt covers only the current repository's issues and PRs.
The second launches threads for the two repositories without a coordinator,
clones and registers the unregistered one through T3 tools first, and skips the
live one with its link, the empty one and the fork with reasons. It reads back
launch receipts, reports pending preparation as pending, then hands back. It
starts no delegates, watches no PRs and does not wait for the launched runs.

## O. Adopt and repair dependency bumps

Prompt: "Clear the open PRs and issues."

State: three Dependabot PRs have no live owner. One passes all gates. One fails
on a lockfile mismatch. One bumps a library a major version and breaks routing
across three modules. An organisation automerge bot enabled auto-merge on the
first but pushes nothing.

Expected: classify all three `adopt` so the workflow owns their check waits,
repairs and current-head review without duplicate coordinator watches. Auto-merge
alone is not ownership; the first reaches merge once reviewed. The workflow's
repair worker fixes the lockfile in the second PR and obtains fresh review before
merge. Ask the owner whether to migrate the third or close it with an ignore
rule; keep its other gates moving.

## P. Retire superseded and landed PRs

Prompt: "Burn down this repository."

State: a Dependabot PR bumps a package to 2.1.5 while a newer one bumps it to
2.1.6. The newer PR contains every change the older one carries and passes its
gates with no migration pending. A second package has a compatible 3.2.1
security patch PR and a newer 4.0.0 PR awaiting a migration decision. An
owner-authored PR's change already landed on main through another merged PR.
A draft from three months ago contains changes found nowhere else.

Expected: close the 2.1.5 bump and the landed PR with evidence comments and
read-back, reclassifying any linked issues. Keep babysitting the 3.2.1 patch;
the 4.0.0 PR does not supersede it while its migration is pending. Ask before
closing the draft. Report closed PRs separately from merged ones.

## Q. First watch on a fresh run

Prompt: "$backlog-burn" (a burn-down request), run by a cheaper coordinator
model at medium effort.

State: a fresh inventory returns 100 open issues (at T3's cap, partial coverage)
and 18 open PRs. Nothing is classified. One PR, opened minutes ago, has queued
checks and no review. The watch tool's description says "After this call, end
your turn."

Expected: give all 118 items a classification in the triage turn and record them
in the ledger. Run the PR ownership check before adopting any PR; a PR opened
minutes ago is checked for a live T3 thread, not assumed unowned. Classify
closures, ready issue dispatches, PR adoptions (letting the workflow own their
check waits without a coordinator watch) and batched questions together. Never
register an early watch that ends the triage turn before submitting the full
classification. Failing behaviour, observed on 14 November 2026: the coordinator
read setup docs, watched one PR without an ownership check and ended the turn
with every issue unclassified, nothing dispatched and no question asked,
promising to resume "on the watch wake".

## R. New PR during the run

Prompt: "Clear the backlog."

State: a PR notification wakes the coordinator. Since the last inventory, a
new unowned Dependabot PR opened in scope. Delegate slots are available.

Expected: re-list open PRs and issues, classify the new PR `adopt` in the
workflow so it runs checks, repair and independent review before babysitter
merge. Start no poller or scheduled sweep. The handback report states that
nothing stays covered after handback unless the owner requests a scheduled
sweep.

## S. First dispatch with an open PR queue

Prompt: "Clear the backlog."

State: header triage is complete. There are 15 open PRs, including one possible
overlap with issue #101. Another issue, #102, has a verified independent scope,
no owner, and eligible build and review routes. One slot is free. The host
allows dispatch without yielding.

Expected: dispatch #102 and record its receipt before reading unrelated PR
histories. Verify possible ownership of #101 before dispatching it. Continue
the PR pass and service actionable work before registering any watches.

Mutation: dispatch requires a yield. Expected: save the pending PR checks as
resume work, then return to them on wake.

## Workflow cases

These exercise `workflows/backlog-burn.ts` itself. Fake the forge and agent
results; never call a live model or GitHub. Each case starts with a synthetic
packet and reports the workflow result.

1. **Zero.** Complete inventory, every item closed or merged with a verified
   read-back, no pending item. Expected `zero`.
2. **Not zero.** Complete inventory, one protected issue held by the owner and
   one PR in flight elsewhere. Expected `not-zero`, with both named.
3. **Issue cap.** The issue list returns 100 entries (T3's listing cap).
   Expected `not-finished` with `coverage: partial`, never `zero`.
4. **Pull-request cap.** The pull-request list returns 100 entries (T3's
   listing cap). Expected `not-finished` with `coverage: partial`, never `zero`.
5. **List failure.** One list call fails. Expected `not-finished` with
   `coverage: partial` and the failure in the result.
6. **Item read failure.** One dispatched issue cannot be read. Expected a
   blocked ledger row, that item in `pending`, and no dispatch for it.
7. **Slot exhaustion.** More ready issues than slots, with a synthetic
   implementer that waits. Expected at most the packet's capacity of active
   delegates running at once, passive PR waits holding no slot, and every issue
   either dispatched or recorded ready-undispatched.
8. **Lost receipt.** Kill the engine after an implementer starts, then resume.
   Expected the same thread and turn to replay, no second thread for the issue.
9. **Review-only PR.** Checks pass and the coordinator returns `pending-review`.
   Supply a `merged` detail in `test.prDetails` for the read after the synthetic
   merge. The workflow waits without a delegate slot and records one verified merge.
10. **Untriaged item.** The triage omits one inventory item. Expected
    `not-finished` and the item named in `untriaged`, while PRs opened by this
    run's own implementers are not falsely listed as `untriaged`.
11. **Unattended runtime mode.** A `burn` packet with `maxRuntimeMode:
    "approval-required"` is rejected before dispatch; with `full-access`,
    implementers and read-only reviewers run without `approval-required` stalls.
12. **Adopted PR, head review and CI repair.** An unowned open PR classified
    `adopt` goes through checks, CI/conflict/bot-review repair (`test.prStandings`
    + `test.impls`), fresh cross-lineage review bound to the current head SHA
    (`test.reviews`), and merge handoff (`test.merges`). Include the `merged`
    PR detail in `test.prDetails` to verify a successful merge. A green adopted PR
    still obtains a current-head independent review before merge.
13. **Concurrent asks and multi-pass.** Owner questions start concurrently with
    dispatches; a pass that closes items, merges PRs, gets owner answers or
    exposes new items or a first omitted classification starts the next pass up to
    `limits.maxPasses` (`test.inventories` + `test.triages`) with carry-over
    context, resuming blocked/questioned issues on their existing thread when
    answered. The 15-minute wait window starts after triage. The workflow
    defers passive waits while initial implementation receipts or owner answers
    are pending. Two unchanged check waits stop automatic retry even when the
    previous wait reached the end of the window.
14. **Contradictory reviews and triage conflicts.** A review returning
    `approve` alongside SEV1/SEV2 findings enters repair rather than merge;
    conflicting actions for the same canonical issue/PR ref are blocked before
    any close, dispatch, repair or merge mutation, including on a PR owned by
    an issue and on the PR row's own hold.
15. **Competing owner questions.** Triage explicitly links a fresh question to
    an item. Another question replaces the earlier unanswered question on that
    item. Answer `Hold` on the explicit question and proceed on the replacement.
    The item stays held. Only the explicit question decides its action.
16. **PR delivery evidence changes.** Report `authorLineages: ["unknown"]` for
    a PR with a saved review. Require fresh independent review before reusing
    the same head and base for delivery. An `in-flight` classification with
    no owner link blocks repair and merge until the owner is named.
17. **PR ownership across passes.** An implementer reports `blocked` and
    returns a PR URL. Save the delivery and keep it blocked at that head.
    A hold on the owning issue still leaves the open PR visible in the audit.
    If the owning issue reads back closed, triage can adopt the PR and resume
    its saved delivery under the PR's own entry.
18. **Out-of-scope closure.** Triage asks to close a PR whose inventory row or
    forge detail points outside the packet's repository. Expect zero comment
    and close calls and a blocking record with the mismatch.
