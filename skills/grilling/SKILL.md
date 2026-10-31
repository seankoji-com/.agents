---
name: grilling
description: Stress-test a plan, decision or idea through questions. Use when the user asks to be grilled or wants an interview to clarify their thinking.
---

# Grill the decisions that matter

Find the decisions whose answers could materially change the goal, design, risk
or next implementation step. Reuse settled decisions and inspect available facts
before asking the user. Look up small facts directly; delegate substantial,
independent investigations only when the host supports them and scope permits.

Ask the currently answerable questions together through the host's question tool,
or numbered text questions when no question tool is available,
with one decision per question, your recommendation first and its tradeoff.
Defer questions that depend on an unanswered decision. Do not turn routine,
reversible choices into owner decisions.

After the answers, revisit only affected decisions. Stop when the remaining
uncertainty cannot materially change the next implementation step. Summarize the
choices, assumptions and any unresolved gate; do not exhaust every possible branch.
If the user requests an exhaustive interview, continue to that endpoint instead.

After summarizing, use the host's ask-user-question tool to ask what the user
wants to create:

1. An issue, with sub-issues when the work warrants them.
2. A Markdown file in a temporary location outside the worktree.

Use numbered text questions only when no question tool is available. Wait for the
user's choice before creating either artifact. Carry the settled decisions,
assumptions and unresolved gates into the chosen artifact. Confirm a missing issue
destination only if it cannot be inferred from context. For the Markdown option,
honor any supplied path; otherwise choose a temporary location outside the
worktree and report the file's absolute path.

Grilling alone does not authorize implementation. If implementation is already
requested, continue within that authority once material decisions are settled.
Use native host tools and preserve explicit constraints.
