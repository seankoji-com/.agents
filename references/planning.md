# Planning and review

Read on demand for substantial planned changes or `imps` runs. Small changes
need no planning ceremony. Follow the active repository and workflow instructions.

## Plan and verification

Keep the objective, acceptance criteria, verification steps and outstanding blockers
in the task's required plan format. Do not add a root `GOAL.md` when the workflow
uses another location or format. If a checklist is required, make each item testable:

```markdown
- [ ] <observable acceptance criterion>
  Verify: <command or inspection>
  Done when: <specific passing result>
```

Update the plan at milestones and before handoff. Preserve unrelated task state.
Bind evidence to the revision tested. Keep local checks, current-head CI, review,
merge, deployment and live acceptance separate; record unavailable checks and human
blockers. A plan does not require another approval for work already authorized.

## Review

Use the installed `imps` workflow for substantial plan or diff review when
delegation is enabled. Discover current roles and models; do not assume a named
reviewer, persona panel or legacy `/imps` command exists. Follow T3's delegation
contract in T3 sessions. Outside T3, use only tools the active workflow supports.

Give the reviewer the exact plan or diff and revision, scope, requirements and prior
unresolved findings. Track the task and inspect its result. Resolve findings with
evidence; do not substitute direct self-review for a required independent gate.
When delegation is unavailable, challenge the work directly and report the missing
gate. Never use an advisor tool or launch reviewers recursively.
