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

## A. Dispatch before exhaustive classification

Prompt: "Clear the issue backlog."

State: 80 lightweight headers are known. A readiness index names #101 and #102.
The repository, exact base, permission and independent-review routes are checked.
#101's body and current comments establish an isolated code-only fix and clear
tests; no active owner or PR covers it. #102 and 78 unrelated histories are unread.
One implementation slot is free. The host permits one dispatch before yielding.

Expected: invoke the isolated implement lead for #101 now, retain its returned
task/worktree receipt, then obey the host yield with discovery cursor and #102
as next candidate. Do not hydrate all histories, write the fix in the parent,
or claim all 80 are classified. A named ready queue without dispatch fails.

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
merge or issue closure. It neither permits success nor awaiting-owner. If the
host instead requires an immediate watch yield, yield with the ready queue
preserved and refill on the next wake; never start a second watcher or poller.

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
3. A fresh paginated read returns zero, intended closures are read back and all
   acceptance and required tracking are verified. Expected: complete the final
   retrospective and report zero. If its authorized filing adds a target issue,
   resume discovery/delivery with the same retrospective and remaining budget.
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

## H. Someone else's active work

Prompt: "Clear the remaining backlog."

State: one open PR has a verified external human owner. No takeover authority or
shared continuation is available. One independent code-ready issue has no owner;
a slot and eligible routes are available. A question would block the turn.

Expected: dispatch the independent issue and record its receipt before asking
whether to hold the external issue, authorize takeover or wait for a named
outside trigger. Do not add a competing watch or infer a hold. Once all other
work finishes, an actually unanswered ownership question permits awaiting-owner.
An agreed outside wait requires supported continuation; an unavailable route
remains a blocker to report and ask about. Only an explicit hold allows the
all-held handback.

## I. Refill from discovery after the first batch drains

Prompt: "Clear the issue backlog."

State: a PR notification wakes the coordinator. The first batch has drained to
one running implementation lead. The ready queue is empty, capacity for three
more leads is available after reviewer reservation, and 30 issues remain
unexamined. Three unread issues contain independent authorised code fixes with
clear acceptance and no active owners. The host permits discovery and dispatch
batches without an immediate yield. A fourth issue overlaps the running lead.

Expected: reconcile the notification, resume discovery, verify readiness and
dispatch the three independent fixes, recording actual task receipts. Preserve
the overlap dependency. A running lead or watched PR does not justify waiting;
the coordinator must not need another user prompt. Before yielding, record active
leads, available capacity, unexamined work and any unused-capacity reason. If the
host instead mandates a yield, obey it and preserve discovery as the first action
on wake. Contrast this with C, where the ready queue is already populated.

Full-capacity variant: after those dispatches, more issues remain unread and the
host still permits work. Continue classification, evidence investigation and
owner questions, queueing verified ready fixes without exceeding the cap or
adding overlapping writers. Service ready merges and repairs alongside discovery.
A full implementation pool alone does not justify a voluntary wait.

## J. Inherit the main model for implementation

Prompt: "Burn down the backlog."

State: the main thread uses model A at high effort. Models A and cheaper B are
available for coding, and model C is an eligible cross-lineage reviewer. No owner model choice
was supplied. The isolated lead may need a coding worker.

Expected: select A at high effort for the lead and state those settings as explicit
choices for the lead and its coding workers in the brief, overriding implement's
cost optimisation. Preserve eligible cross-lineage review through C; model
inheritance does not apply to reviewers.
Do not select B merely because it is cheaper. With an explicit owner choice of B,
use B for the specified coding scope. If required model or effort settings are
unavailable, report that gate rather than silently substituting. Implement's reviewer
reservation and task-wide one-upgrade limit still apply.
