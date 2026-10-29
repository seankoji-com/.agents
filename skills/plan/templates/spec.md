# Specification template

Define criteria someone can assess without the conversation. Adapt the sections to
the task and repository format.

## 1. Pass/fail criteria
Give each requirement a stable ID such as `[REQ-LOGIN]`, retained through handoff and
implementation. Specify its verification method (`inspection`, `command`, `runtime` or
`manual`), observable outcome, relevant environment and evidence needed. Include
failure/recovery cases where they affect acceptance. Cross-reference discovery when it
clarifies a constraint or decision.

Make judgement criteria explicit. For research, define source standards and which
claims require citations; "well researched" alone is not assessable.

## 2. Auto-reject conditions
Include only conditions that justify rejecting the whole deliverable. Select those
relevant to this task, such as:

- Ignores an accepted constraint or reintroduces a rejected alternative without new evidence
- Omits content explicitly required by the brief
- Leaves a required research claim unsupported or a required behavior unverified
- Changes files or systems outside the authorized scope

## 3. Quality bar
Describe task-specific qualities beyond minimum acceptance when useful. Separate
preferences from mandatory criteria; do not introduce hidden requirements here.

## 4. Grading notes
Explain how to handle partial results, source disagreement and unresolved questions.
State where an honest "not knowable" is acceptable. Record blockers and owners,
next actions, review status and finding dispositions, actual reviewers and the
source version for handoff.
