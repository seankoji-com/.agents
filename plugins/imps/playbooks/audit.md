# Audit a repository

Read `PKG/shared/t3-runtime.md`. Inspect the project profile: purpose, users, entry
points, architecture, tests, CI, deployment, and current dirty changes. Resolve focus
from the request. Audit relevant dimensions of correctness, security, operability,
maintainability, accessibility, and user experience; skip dimensions with no surface.

Each finding needs file/line evidence, a concrete failure scenario, impact, existing
mitigations, and a bounded verification. Separate confirmed defects from hypotheses
and preferences. Record coverage gaps instead of inflating them into bugs.
Use T3 preview for actual UI observations when available. Independent T3 analysts
are optional; do not spawn one per heading merely to fill a panel.

Save the audit at an operator-approved path. Group fixes by dependency and ownership,
with acceptance criteria suitable for `run` or `issues`. Auditing does not authorize
fixing, opening issues, posting comments, or publishing a PR. Return the findings and
recommended order; start implementation only within the requested scope.
