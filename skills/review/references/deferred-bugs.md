# Track confirmed deferred bugs

The coordinator owns tracking after validating a finding and deciding to leave
the bug unfixed. An assigned reviewer reports the finding and evidence without
filing issues or deciding deferrals.

For bugs already judged non-blocking, issue preparation and filing are not merge
gates. They remain workflow completion requirements. A blocking finding remains
blocked unless its release treatment permits an exception; asynchronous tracking
does not grant one.

Apply [raise-issue](../../raise-issue/SKILL.md) to identify the owning repository,
search existing reports, prepare the issue and file or update it within the
caller's authority. That skill owns repository policy, duplicate handling,
submission and read-back verification for owned, organisation and upstream repos.

For deferred review bugs:

1. The main-thread coordinator owns each asynchronous filing job. Delegated
   callers return a complete filing request with the finding IDs, repository,
   posting authority, validated evidence, source worktree/revision and related PR.
   Record a request's owner and state, then the T3 task handle when dispatched.
   Avoid duplicate dispatch when implement, review-loop and babysitter encounter
   the same finding. Keep evidence accessible until the issue writer has it.
2. Reuse an actionable issue only when it covers the same unresolved defect;
   retain every relevant finding ID. Otherwise track each distinct bug separately.
3. Include the stable finding ID, severity and impact, affected revision,
   expected/actual behavior, reproduction or supporting evidence, workaround,
   reason for deferral and observable fix acceptance criteria. Link the related
   PR when one exists. Use verified existing labels; label creation needs
   separate authority. State unknowns rather than inventing evidence.
   Reference deferred issues with ordinary links, not closing keywords in the
   delivery PR: merging that PR must not close a bug it leaves unfixed.
4. Record the verified issue URL alongside the finding, disposition and deferral
   reason in the ledger, PR handoff and final report. Do not mark the bug fixed
   merely because it is filed.

Code-ready handoffs and otherwise-ready merges may proceed with owned filing
requests pending. The main thread dispatches them under raise-issue's host-aware
continuation rules and keeps responsibility after merge. Do not cancel those
jobs or remove their evidence as routine PR cleanup. Report tracking pending
until URLs are verified; a task handle or prepared request is not a filed issue.

If authority, access or the destination is missing, retain a draft and report
the exact tracking gap and next action. Explicit no-post or read-only limits
still apply. An execution workflow must report incomplete tracking rather than
claiming that every deferred bug has an issue. A direct read-only review can
finish by returning its findings and identifying the unfiled follow-up.
