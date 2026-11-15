# Verify repairs after one review round

Read when the project's adopted Delegation settings explicitly sets
`review_rounds: 1`. This replaces rechecks and the caller's score gate only for
repairs to that round's findings. Required human approvals, repository/release gates, severity,
code-author lineage and primary/companion coverage remain in force.

1. Obtain one logical independent round on the full frozen change. Include the
   required primary and parallel companions. A missing, failed or refused report
   is incomplete review, not the one-round allowance consumed successfully.
2. Record the reviewed revision, authors, reviewer identities, reports and each
   finding's disposition. Have the author repair accepted findings within scope.
   Keep a finding-to-change record covering every repair.
3. The coordinator verifies the repaired revision. Reproduce the original
   failure where feasible, show the covering regression failing before and
   passing after the fix, and exercise a focused mutation for each new guard
   where meaningful. Run affected and repository-required suites and live/UI
   checks where relevant. Record unavailable proof and why; failed or missing
   material verification keeps the task incomplete. Documentation-only repairs
   use source/caller checks rather than invented executable tests.
4. Apply this exception only to changes traceable to that round's findings that
   preserve the reviewed design and shared assumptions. New behavior beyond
   those fixes, changed interfaces/shared assumptions, unrelated changes and
   later CI or bot findings retain ordinary review requirements. A new behavior
   change cannot be relabelled as a repair to avoid review.
5. If verification and all other gates pass, the coordinator may complete the
   authorized endpoint without a reviewer recheck of those fixes. Report the
   reviewed revision and repaired revision separately, with the exact statement
   **fixes coordinator-verified, not independently re-reviewed** in the PR and
   handoff. Scores remain bound to the reviewed candidate; do not invent a
   repaired score or claim current-head independent approval.

For those repairs, this setting replaces the caller's ordinary recheck and score
gate with coordinator verification. Report the original score as-is, even when
below target; it does not block acceptance once every accepted finding is
verified and all other acceptance/release gates pass. Do not assign a repaired
score. A separate explicit demand for another scored review conflicts with this
setting; settle that conflict before using the exception. Missing material proof
or unmet acceptance criteria still keep the task incomplete.
