# Diagnose a stalled or exhausted review

The coordinator reads this before proposing more rounds, using a caller's
automatic extension, or escalating a review that has stopped making progress.
Use the existing reports and checks for this diagnosis, not another evaluator.
This procedure preserves the caller's limits and release gates. It grants no
extra rounds, model upgrades, scope changes or authority to ship.

## Establish what another round could change

Reconcile the round ledger with the current revision. For each attempt, record
the stable finding IDs, severity, evidence, disposition, repair made and result
of the covering check. Count failed attempts. Identify which findings are new,
fixed, reopened or unchanged. Preserve the ledger across resumes and reviewers.

Classify the remaining obstacle using the evidence:

- A reproducible defect needs a repair or an authorised disposition.
- Missing runtime evidence, a broken environment or unavailable permissions need
  access or a focused experiment. Another source opinion may add nothing.
- An unresolved product decision needs a precise choice from its owner.
- Reviewer disagreement needs comparison against requirements and evidence.
  Repeated agreement requests and style preferences do not establish a defect.

Look for the same finding surviving successive repairs, repairs undoing each
other, expanding scope, moving acceptance criteria, repeated tool failures or
rounds producing no new evidence. State whether progress is converging, stalled
or cycling, and cite the attempts that support that assessment. A high severity
alone does not make another round useful.

First apply [review's release treatment](../SKILL.md). If the current reviewed
behavior meets the criteria and only non-blocking findings remain, close with
explicit dispositions and required bug tracking. Do not spend another round on
declined nits or unanimity. Unreviewed material repairs, missing required proof
and unresolved blocking findings still prevent acceptance.

## Choose a credible next approach

Recommend an approach tied to the diagnosed cause, with its next action,
expected evidence, cost or effort and remaining risk. Assess at least one
alternative to extending the review count. Choose the relevant route, rather
than presenting a generic menu:

- Build a targeted reproduction or run the missing check on the exact revision.
  Explain what result would confirm or reject the suspected cause.
- Change the repair strategy within scope, such as replacing an oscillating
  patch with a simpler implementation. Identify the different hypothesis and
  retain the caller's implementation and model-upgrade limits.
- Propose a smaller deliverable or a return to an already reviewed checkpoint.
  Explain what the user would lose and obtain authority for a material scope
  change or revert. Changed behavior still needs the applicable review.
- Preserve the unresolved work and send a concrete evidence packet to the owner
  of a missing environment, permission or upstream fix. Finish independent
  authorised work and identify the exact action needed to unblock the rest.
- Ask the specific product or risk decision that only the user can make.

Do not manufacture an alternative that cannot satisfy the user's goal. When
every credible route depends on the same external gate, explain that constraint
and provide the prepared work and recovery action.

Recommend additional rounds only when a changed hypothesis, new evidence or a
different bounded approach gives them a specific purpose. State what the next
round will evaluate, why it can change the outcome, the proposed count and the
stop condition. Obtain any required extension authority before dispatch. The
caller may allow an extension without a new question, but it still requires
this diagnosis. A new reviewer or phase label never resets the budget.

## Escalate a decision, not a counter

Give the parent or user a concise assessment containing:

- Rounds used and limit, current revision, and outstanding finding IDs and gates.
- Progress or loop diagnosis, with evidence from the ledger.
- The recommended next approach and why it is preferable, including what can
  finish now and what remains blocked.
- Any required decision, and a bounded extension only if justified above.

Do not default to "approve more rounds" as the recommended choice against
"stop and block". Continue a changed approach within existing authority and
budgets; ask only for a material decision or missing authority. A delegated
coordinator returns this assessment to the main thread. It cannot grant itself
more rounds or ask the operator directly when its role requires a parent handoff.
