# Classification rubric

Classify from the issue body, its comments, linked PRs and the repository's own
triage rules. Record the evidence for the class, not just the label.

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

Complexity labels are estimates, not readiness. A `complexity:low` issue with an
open product question is not dev-ready.

## Needs decision

The owner must choose something: behaviour, scope, compatibility, priority,
whether to accept a risk, whether to split an epic, or whether to retire a
component. Prepare the options and a recommendation; do not dispatch
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

The outcome no longer applies, the component is retired, or the owner has
accepted the risk. Propose closure with evidence and a one-line reason. Close
only after the owner confirms in a question round. An accepted hold is not the
same as a fix.

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
