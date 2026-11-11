# Finish with a workflow retrospective

The main-thread coordinator owns this final stage, after the authorised delivery
endpoint and required deferred-bug tracking. It proposes improvements; it does
not silently amend skills or broaden the delivered change.
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
2. After delivery and tracking, set a bounded history cutoff. Read the parent's
   operational activity for this ship invocation and every manifest member,
   including checks, tool errors, repairs, dispatch/permission events, handoffs
   and delivery results. In T3 use `t3_thread_read` with `view: 'activity'`.
   Use small pages, initially `limit: 25` and `maxCharsPerItem: 1500`.
   Page with `afterPosition`/`nextPosition`, inventorying every operational event.
   Classify outcomes from concise event data when sufficient. Follow truncated
   bodies with `itemId` and `textOffset`/`nextTextOffset` only when needed to
   determine the outcome, cause or proposed amendment; extract relevant fields
   from large artifacts deterministically. Unclassifiable events remain gaps.
   `runLimit` limits
   run metadata, not the activity window: filter by recorded run/item boundaries.
3. Reconcile children found in the activity with the manifest recursively.
   A final delegate summary alone does not establish coverage of its execution.
   Read through supported APIs or authorised log artifacts; never alter T3's live
   database or inspect unrelated threads or credentials. Activity APIs can
   include reasoning items; do not analyse, quote or publish private reasoning.
   Record each covered run/range and any missing or inaccessible operational logs.
   Missing logs make the retrospective incomplete, even if delivery succeeded.

Set an inspection budget before starting: by default at most 30 history/detail
reads or 10 minutes, whichever comes first. Keep the counts, cursor and covered
ranges across resumes. Do not reset the budget; request an extension only when
needed and authorised. At exhaustion, report partial coverage and the remaining
range instead of silently skipping it or claiming completion. Coverage means
every operational event has a supported outcome classification, with deeper
inspection where necessary; it does not require copying every log byte into
the main context. Before task/worktree cleanup, preserve required evidence in
a verified host-approved parent location or inspect it first, then follow host
cleanup rules. Keep logs and evidence addresses usable through this phase.

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
report delivery evidence, log coverage/gaps and verified proposal URLs or the
no-change rationale. If filing or log access is blocked, leave this stage visibly
incomplete and retain the redacted draft and exact next action. Do not hold an
otherwise-ready merge on this post-delivery stage.
