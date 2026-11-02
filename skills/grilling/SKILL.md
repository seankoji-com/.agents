---
name: grilling
description: Stress-test a plan, decision or idea through questions. Use when the user asks to be grilled or wants an interview to clarify their thinking.
---

# Grill the decisions that matter

Find the decisions whose answers could materially change the goal, design, risk
or next implementation step. Reuse settled decisions and inspect available facts
before asking the user. Look up small facts directly; delegate substantial,
independent investigations only when the host supports them and scope permits.
Apply [T3 dispatch preflight](../agent-tuneup/references/t3-dispatch.md) before those T3 investigations.

Ask the currently answerable questions together through the host's question tool,
or numbered text questions when no question tool is available,
with one decision per question, your recommendation first and its tradeoff.
Defer questions that depend on an unanswered decision. Do not turn routine,
reversible choices into owner decisions.

After the answers, revisit only affected decisions. The stop condition is that
the remaining uncertainty cannot materially change the next implementation step.
When you believe it is met, summarize the
goal, scope, choices, constraints, assumptions, observable acceptance criteria,
verification methods and unresolved gates in a concise brief. Preserve material
rejected alternatives and their reasons; do not exhaust every possible branch.
If the user requests an exhaustive interview, continue to that endpoint instead.

Before concluding the interview or handing off implementation, use
[review](../review/SKILL.md) to obtain a cross-lineage second opinion on that
stop condition. Supply the original request, current brief, settled decisions,
assumptions, relevant facts and intended next implementation step. Ask the
reviewer to state whether the condition is met and identify any remaining
uncertainty whose resolution could materially change that step, with its impact
and the question or investigation needed. This is a readiness review, not a
requirement to implement the feature or invent extra questions.

Verify material gaps, investigate available facts and ask only the affected
questions that need the user. Revise the brief and obtain a fresh readiness
review when material gaps change it. Allow at most three readiness reviews,
including failed attempts, across the interview and its resumes. If the budget
is exhausted or reviews stall, apply review's
[budget diagnosis](../review/references/budget-exhaustion.md) within this
three-review limit. If readiness remains unverified or cross-lineage review is
unavailable, report readiness as
incomplete and hold implementation. Still provide the brief in the requested
format, or offer the artifact choices below, marked not ready with the review
gate and next action. A reviewer verdict without supporting reasoning does not
establish readiness.

After readiness is established, honour an already-requested artifact or
implementation endpoint. Otherwise use the host's ask-user-question tool to ask
what the user wants to create:

1. An issue, with sub-issues when the work warrants them.
2. A Markdown brief saved to a file.
3. Complete the work now in the same session

For a chosen issue endpoint, apply [raise-issue](../raise-issue/SKILL.md) to
prepare and file the accepted brief in the owning repository.

Use numbered text questions only when no question tool is available. Wait for the
user's choice before creating either artifact. Carry the settled decisions,
assumptions and unresolved gates into the chosen artifact. Confirm a missing issue
destination only if it cannot be inferred from context. For the Markdown option,
honour any supplied path. Otherwise use the host-approved artifact location,
verifying an ignored directory inside the session worktree when required.
Report the file's absolute path and preserve it for the user's handoff.

Grilling alone does not authorize implementation. If implementation is already
requested, continue within that authority once material decisions are settled
and the readiness review establishes the stop condition.
For UI implementation, apply [design-chooser](../design-chooser/SKILL.md) after
settling product decisions and before editing when its trigger applies.
Preserve explicit constraints.
