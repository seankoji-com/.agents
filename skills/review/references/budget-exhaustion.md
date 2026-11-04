# Diagnose a stalled or exhausted review

The coordinator reads this before proposing more rounds, using a caller's
automatic extension, or escalating a review that has stopped making progress.
Use the existing reports and checks for this diagnosis, not another evaluator.
This procedure preserves the caller's limits and release gates. It grants no
extra rounds, model upgrades, scope changes or authority to ship.

## Reconcile allowance and approval history

Retain the original allowance or stopping rule and each extension in the task's
existing record. For each extension, record its amount, whether user-approved or
caller-granted automatically, the approval message or caller rule establishing
authority, and attempts consumed. Distinguish extensions already used from the
one now proposed. Carry this history through resumes and parent handoffs.

Reconcile cumulative authorised allowance, attempts used including failures,
and remaining allowance before proposing an addition. Show the proposed amount
and resulting total separately from existing authority. For uncapped workflows,
state the actual scoring and stagnation rules and any explicit limits instead of
inventing a round cap. Keep separate budgets distinct. Record automatic
extensions even when they needed no user question.

Recover missing history from available task records first. Label unrecoverable
approvals, amounts or consumption unknown; do not treat them as zero or infer
permission to continue. If an unknown prevents establishing remaining authority,
hold dependent review and identify the exact confirmation needed.

## Establish what another round could change

Reconcile the round ledger with the current revision. For each attempt, record
the stable finding IDs, severity, evidence, disposition, repair made and result
of the covering check. Count failed attempts. Identify which findings are new,
fixed, reopened or unchanged. Preserve the ledger across resumes and reviewers.
Include each attempt's material result and, for scored loops, the target, best
and current scores and stagnation counter under the caller's accounting rules.

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
Explain why the allowance ran out or the stopping rule fired. Explicitly reassess
whether the current scope, acceptance criteria and repair strategy still offer
a credible path to the goal. Distinguish necessary discovery from scope drift;
changing acceptance criteria requires its own authority.

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
this diagnosis and a recorded authority source. A new reviewer or phase label
never resets the budget.
When the caller's limit admits no extension, as with interrogate's readiness
limit, report the diagnosis and incomplete gate without proposing extra rounds.

Assess whether the proposed allowance can plausibly finish the remaining work
or only fund a specific experiment. Explain the evidence for that assessment,
dependencies, uncertainty, and what happens if the expected result fails to
appear. Completion remains conditional on required checks and review gates;
do not promise that a count of rounds guarantees it.

Without an evidence-backed changed approach, hold further review instead of
asking for more rounds with low confidence. Complete useful independent work
within existing authority and return the concrete blocker, recovery action or
credible alternative. User approval of a count alone does not supply the missing
diagnosis or waive the caller's other stopping rules.

## Escalate a decision, not a counter

Every extension request must be self-contained where the user makes the
decision. Give the parent or user a concise assessment containing:

- Original allowance/stopping rule; each previous extension and its authority;
  cumulative allowance, attempts used and remaining; proposed addition and
  resulting total. Explicitly state when there were no prior extensions or
  history is unknown. Separate user approvals from automatic extensions.
- Current revision, outstanding finding IDs and gates, and each round's material
  result. Explain why the budget or stopping rule was reached and support the
  converging, stalled or cycling diagnosis with specific attempts.
- Reassessment of the path to the goal; the changed approach, expected new
  evidence and why it can change the outcome. Compare a credible alternative,
  including what can finish now and what remains blocked.
- Finishing prospects within the proposed allowance, supporting evidence,
  dependencies and uncertainty. State whether this aims to finish or to resolve
  one experiment, the exact stop condition and the action if it fails.
- The recommended decision and bounded extension only when justified. Make
  the consequence of declining clear without presenting an unjustified extension
  as the only route forward.

Do not default to "approve more rounds" as the recommended choice against
"stop and block". Continue a changed approach within existing authority and
budgets; ask only for a material decision or missing authority. A delegated
coordinator returns this assessment to the main thread. It cannot grant itself
more rounds or ask the operator directly when its role requires a parent handoff.
The main thread preserves these decision fields in the user-facing request;
links to earlier reports may supplement them but cannot replace them. Verify
delegated authority claims or mark them unknown rather than dropping the history.

## Walkthrough cases

Use these synthetic cases to check the instruction contract without live models:

| Situation | Required assessment and action |
| --- | --- |
| First extension for a caller that permits extensions after a three-attempt allowance; a failed dispatch and two completed reviews used it | State no previous extensions, 3 authorised, 3 used, 0 remaining; propose 1 additional, total 4, pending approval. Explain each attempt, changed approach, likely outcome and stop condition before requesting it. |
| Interrogate exhausts its hard three-readiness-review limit | Report the diagnosis and readiness incomplete. Hold implementation; do not propose a fourth review. |
| Resume after 3 original attempts, a user-approved addition of 2, then a separately approved addition of 1; 6 used | Show both approvals and their amounts, 6 authorised/used and 0 remaining. A proposed addition of 1 makes 7 only if approved. Resume and reviewer changes grant no fresh budget. |
| Caller allowed one automatic addition of 2 after its original 3; all 5 used | Show the automatic addition and its caller-rule authority separately from user approvals. Any later request reports 5 used, not just the original 3. |
| A finding survives successive repairs and the next proposal repeats the same repair without new evidence | Diagnose stalled or cycling using the attempts. Hold review, omit an extension request, and give a reproduction, different repair or concrete blocker while independent work continues. |
| Old approval says only "continue" and the amount cannot be recovered | Mark the amount and cumulative authority unknown; show known consumption. Hold dependent review if remaining authority cannot be established and request the precise missing confirmation. |
| Uncapped scored loop stops after two non-improving rounds | Show target, best/current scores, counter and actual attempts; state no numeric cap. Diagnose stagnation before proposing a changed approach; extra rounds alone do not override the stopping rule. |

These walkthroughs specify expected decisions, not observed live-agent compliance.
