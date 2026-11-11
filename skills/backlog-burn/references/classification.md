# Classification rubric

Classify from the issue body, its comments, linked PRs and the repository's own
triage rules. Record the evidence for the class, not just the label.

## Closure first

Before dispatching work, ask whether the issue still earns a place in the backlog.
Strongly prefer closure when current evidence shows the useful outcome is already
delivered, the issue is obsolete, or the remaining work adds too little value.
Ordinary qualifying issues close without a per-issue owner question during an
authorized burn-down. Inventory, triage-only and no-close requests propose the
disposition without writing it.

1. Read the body and comments, check ownership and linked work, then inspect the
   minimum current code, documentation or delivery evidence needed to classify.
   Reconcile an active owner or PR before closing its issue; ask about genuine
   conflicts instead of disrupting active work.
2. Identify the useful outcome and any remaining material gap. Seek concrete
   present value, rather than hypothetical future usefulness or perfect completion
   of stale checklists. Investigate missing evidence proportionately; uncertainty
   alone does not prove obsolescence.
3. Prefer one of these dispositions:
   - **Already done:** verify the required outcome and close as completed.
   - **Obsolete:** link evidence of a retired component, superseding design or
     requirement that no longer applies, then close as not-planned.
   - **Substantially done:** verify the useful outcome, name the trivial residue
     being retired and close as not-planned without replacement issues.
   - **No remaining value:** explain why the work no longer justifies pursuing
     and close as not-planned. Record an unfixed nonmaterial defect honestly.
4. Record the reason, evidence, delivered outcome and retired residue in the
   closure comment and ledger. Read back the issue state and state reason.

Judge materiality by actual user and operational impact. Severity, priority,
complexity, age, effort, blocked status or inability to reproduce alone never
decide closure. Material wrong output, data loss, security or reliability gaps,
blocked necessary user tasks and failed necessary outcomes remain actionable
whatever their labels. Cosmetic polish, redundant bookkeeping and stale optional
checklist items can retire. Required deployment or runtime acceptance is not
trivial, and a merge does not prove it passed.

Retirement without replacement applies only to trivial leftovers from the
original requested scope of the existing issue being closed. It is a final
not-planned disposition, not deferred implementation. Defects found or introduced
during implementation or delivery review still follow ship's deferred-bug
tracking unchanged, including fixing or filing new SEV3 findings.

Protected issues and stricter repository rules retain owner confirmation.
Retiring an already-obsolete issue differs from deciding to retire a live
component or accept a material risk; those decisions still need the owner.

## Dev-ready

All of these must hold:

- A clear acceptance criterion, or a named defect with the file and the fix path
  already identified.
- Verification can run in the repository: tests, fixtures, stubs or static
  checks. No live host, secret, deploy or destructive operation is required to
  prove it.
- No unresolved product, scope, compatibility or risk decision.
- Not already covered by an open PR or an active owner.
- Not superseded by a newer issue or an accepted design.
- The closure-first assessment leaves a worthwhile material outcome to deliver.

Complexity labels are estimates, not readiness. A `complexity:low` issue with an
open product question is not dev-ready.

## Needs decision

The owner must choose something: behaviour, scope, compatibility, priority,
whether to accept a material risk, whether to split an epic, or whether to retire
a live component. Already-retired components need no new retirement decision.
Prepare the options and a recommendation; do not dispatch
implementation that would pre-empt the answer.

## Needs evidence

A diagnosis, reproduction, log, version or affected path is missing. Investigate
first: read the code, run the reproducer, or ask for the smallest missing
artifact. A question to the owner is the fallback, not the first move.

## Live-only

The work needs a host, secret, deployment, restore, deletion or other live
operation. Split it: the repo-side change may be dev-ready, while the live step
becomes a per-action approval. Never treat a live step as covered by a merged PR.

## Duplicate

A duplicate shares the same root cause: same component, same failure mode, same
recovery path. Similar symptoms or shared labels are not enough.

- The canonical issue must be open. A closed canonical is not a fold target
  unless the repository's own policy says to reopen it for a proven recurrence.
- Protected issues (security, hardware, resilience, P0/P1) are never folded
  without explicit owner review.
- Close with a link to the canonical and the `duplicate` state reason.

## Hold and blocker

An **owner hold** is the owner saying "not now" to a specific issue, with a
reason and a review trigger. Only an owner hold can end the zero loop. An **agent
blocker** is something the agent cannot resolve — live access, an unavailable
approval path, an outside party, missing evidence. A blocker becomes a question,
not a hold. A `blocked-external` issue stays open and is reported until the owner
decides.

Classifications describe the next action, not a reason to stop. A live-only issue
needs an exact approval question and any independent source work dispatched.
An evidence gap needs an investigation or a precise question for inaccessible
evidence. An unasked question or unexamined issue cannot justify awaiting-owner.

## Obsolete or wontfix

Apply closure first. Ordinary obsolete or low-value issues may close with evidence
and a recorded reason. Protected cases and material risk acceptance require owner
confirmation. An owner hold keeps the issue open; retirement closes as not-planned
and never claims an unfixed outcome was delivered.

## In flight

An open PR or verified active owner already covers it. Record current ownership,
task/PR evidence and its next trigger, then reconcile delivery instead of adding
a second writer. An assignee or old remote branch alone does not prove activity.
If work is abandoned, record that and reclassify. An open PR is unfinished work,
not a completed issue or an owner hold.

If the coordinator cannot own that work, ask the owner to hold it, authorize
takeover, or wait for a named outside trigger. Do not assume ownership or add a
competing watch. An unanswered ownership question can pause this issue; an
agreed outside wait stays unfinished with supported continuation. If that route
is unavailable, report it and ask how to proceed. Only an explicit hold permits
an all-held handback.

## Protected issues

Treat security findings, hardware faults, resilience and recovery gaps, and
priority P0/P1 incidents as protected. They may be implemented when dev-ready,
but they are never auto-folded and never closed without explicit owner
confirmation. A live incident is not "closed" by a source-only merge. Use
`Refs #N` rather than a closing keyword when acceptance needs live verification,
so the merge does not close the issue.
