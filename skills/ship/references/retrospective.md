# Finish with a workflow retrospective

The main-thread coordinator owns this final stage, after the authorised delivery
endpoint and required deferred-bug tracking. It proposes improvements and saves
durable decisions; it does not silently amend skills or broaden the delivered
change.
For a terminal blocked handback, analyse the available activity and report the
delivery and coverage gaps. File supported proposals from that history within
the same established posting authority, unless cancelled or posting is prohibited.
An incomplete delivery does not require suppressing useful workflow proposals.

For backlog-burn, an awaiting-owner pause leaves this stage pending. If filings
add issues to its target backlog, it resumes delivery and extends the same
retrospective's cutoff, manifest and coverage within the remaining inspection
budget. Include new delivery activity, without retrospecting the proposal filing
itself or resetting budgets. Missing authority to file warranted proposals leaves
drafts and an incomplete stage with an owner question, not completed tracking.

## Establish coverage

1. At ship start, record the parent thread/run and the request's starting item
   or position. Keep a manifest of every owned delegate, descendant and resumed
   run, including failed or cancelled attempts, reviews and issue writers.
2. At existing task completions and handoffs, record the observed outcome,
   run or item range covered, failed or blocked steps, and evidence links for
   consequential results. Reuse the run ledger and verified tool receipts.
   Include the parent's own checks and delivery transitions. A status flag or
   final summary without supporting evidence establishes no operational coverage.
3. After delivery and tracking, freeze the history cutoff and reconcile the
   manifest against host task/run records, including descendants and failed or
   cancelled attempts. For a small run, read the scoped operational activity
   directly. If the history will not fit the inspection budget, use the evidence
   recorded as work happened to account for routine outcomes. Read underlying
   activity for uncovered ranges, failures, disputed results, handoffs and any
   evidence cited for a proposed amendment. Record the ranges covered by each
   method. Coverage is complete when direct reads or recorded evidence support
   the outcome of every scoped operational event in the reconciled manifest and
   parent history. A missing, inaccessible or unclassified range leaves the
   retrospective incomplete, even if delivery succeeded.

In T3, read activity with `t3_thread_read` using `view: 'activity'`, initially
`limit: 25` and `maxCharsPerItem: 1500`. Use `afterPosition`/`nextPosition` and
filter by the recorded execution boundaries. `runLimit` limits run metadata,
not the activity window. Follow truncated items with `itemId` and
`textOffset`/`nextTextOffset` where the evidence needs it. Extract relevant fields
from larger authorised artifacts deterministically. Use supported APIs and
authorised logs. Exclude unrelated threads, credentials and private reasoning.

Set an inspection budget before starting: by default at most 30 history/detail
reads or 10 minutes, whichever comes first. Keep the counts, cursor and covered
ranges across resumes. Do not reset the budget; request an extension only when
needed and authorised. At exhaustion, report partial coverage and the remaining
range and mark the retrospective incomplete. Group related routine events
when the recorded evidence supports their outcome, and label any unclassified
events as gaps. Before task/worktree cleanup, preserve required evidence in a
verified host-approved parent location or inspect it first. Keep evidence
addresses usable through this phase.

## Propose reusable changes

Identify repeated friction, avoidable failures, missing handoff information,
unnecessary work and successful patterns worth making explicit. Separate a
workflow defect from a repository-specific bug, a transient provider outage or
an unsupported hypothesis. A proposal needs an observed execution example and
a reason the change would help other tasks or repositories.

For each supported proposal, prepare:

- The affected skill and source revision, current rule and observed problem.
- Minimal redacted evidence with stable run/item or evidence references.
- A broadly applicable rule amendment, its scope and exceptions.
- Expected benefit, tradeoffs and a discriminating validation case.

Preserve cross-lineage review, permissions, budgets, human approvals and evidence
requirements. Do not propose removing a safeguard merely because it blocked an
attempt. Deduplicate related proposals. Do not invent a minimum issue count;
record an evidence-based no-change result only with complete coverage and no
warranted amendment. Partial coverage can report no proposals found so far,
but cannot close the phase as a no-change success.

## Save durable decisions to memory

Use the host's memory tools and [reremember](../../reremember/SKILL.md) to
record what later work would act on differently. Memory holds facts and settled
decisions, not new workflow rules: an amendment still goes to its issue, and no
instruction file is edited from this stage.

Save only a fact that outlives the run, changes what a later agent does, and
that no commit, PR, issue or code comment already says better. Typically that is
a decision the run settled, a constraint the code does not reveal, or a
remembered claim the run disproved. Never save a transcript, per-run status,
scores, cost, transient identifiers, private evidence or secrets.

Write to the project memory for the repository the run worked in. When the
session's memory covers another workspace or that repository has none, report
the gap instead of misfiling another repository's decisions.

Search first and reuse the owning record. Write claim, scope, exact values,
evidence and date in reremember's shape, and supersede a stale record rather
than adding a parallel one. One record or none is a normal result. Report each
title, the backend's acknowledgement and whether it is visible now or waits for
a rebuild. A blocked or unavailable backend is reported once and never invented;
it does not hold an otherwise-ready merge.

## File and close the run

Use [raise-issue](../../raise-issue/SKILL.md) to check for existing reports and
file or update proposals in the operator's configured skill repository, rather
than assuming the delivered product's repository. For this owner that is
`seankoji-com/.agents`. The destination must already be named or configured in
the operator's instructions. Account/repository evidence can verify ownership
of that chosen destination, not consent to post; write or collaborator access
is not ownership. A clone or origin URL establishes neither. The owner's ship
request includes these scoped writes. Other users must name or configure a destination; until then,
keep private drafts and request that choice instead of posting to this owner.
Preserve explicit no-post limits and sharing restrictions for private evidence.
Issue preparation remains asynchronous and owned by the main thread. Send a
redacted proposal packet, not a raw transcript. Remove private repository names,
machine paths, hostnames and secrets. Verify each resulting issue URL
and record it against the proposal; a draft or task handle is not completion.
Mark hypotheses and proposals honestly, using existing repository conventions.

Keep this phase bounded: logs after the cutoff that concern retrospective issue
filing contribute their result or blocker to the final handoff, without starting
another retrospective of the retrospective. Once all owned writers finish,
report delivery evidence, log coverage/gaps, the memory result and verified
proposal URLs or the no-change rationale. If filing or log access is blocked, leave this stage visibly
incomplete and retain the redacted draft and exact next action. Do not hold an
otherwise-ready merge on this post-delivery stage.
