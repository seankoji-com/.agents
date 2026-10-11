# Audit a repository

Read `PKG/shared/t3-runtime.md`. Inspect the project profile: purpose, users, entry
points, architecture, tests, CI, deployment, and current dirty changes. Resolve focus
from the request. Audit relevant dimensions of correctness, security, operability,
maintainability, accessibility, and user experience; skip dimensions with no surface.

Each finding needs file/line evidence, a concrete failure scenario, impact, existing
mitigations, and a bounded verification. Separate confirmed defects from hypotheses
and preferences. Record coverage gaps instead of inflating them into bugs.
Use T3 preview for actual UI observations when available. Fan out independent
dimensions under `PKG/shared/delegation.md`.

Save the audit at an operator-approved path. Group fixes by dependency and ownership,
with acceptance criteria suitable for `run` or `issues`. Auditing does not authorize
fixing, opening issues, posting comments, or publishing a PR. Return the findings and
recommended order; start implementation only within the requested scope.

## Source audit coverage

Support `--focus` with a comma-separated subset of `purpose`, `docs`, `ci`, `tests`,
`security`, `performance`, `ux`, `stack`, `ops`, `dx`, and `verification`. Record each
dimension as inspected, not applicable with a reason, or unverified. For `purpose`,
test whether components serve the stated users and outcome; deletion is an operator
decision, not automatic remediation. For `verification`, inspect the project's
launch, doctor, scenario, evidence, cleanup, and recovery paths. Drive existing
checks only when covered by the audit's read-only authorization.

Challenge each blocker or major finding with counter-evidence from the actual code
and mitigations. Revisit suspiciously empty dimensions and interactions between them.
A missing reviewer is a coverage gap, not fabricated approval. Keep refuted findings
and their evidence in the report.

If the operator requests an imps-ready plan, write it outside the repo at the
requested `--out` path (otherwise the run's scratch directory). Include context,
constraints, dependencies, and one unchecked claim per fix with indented `Verify:`
and `Done when:` lines for the checklist playbook. A proposed check should fail on
the defect and pass on the fixed state; label untested checks as proposed. Do not
claim a check failed unless you ran it. List missing acceptance separately instead
of inventing commands. Deletion proposals belong in an operator-decision section.
