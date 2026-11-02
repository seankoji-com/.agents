---
name: challenge
description: Pressure-test an idea, design or proposal with an independent cross-lineage reviewer. Use when the user asks for an adversarial second opinion or to challenge assumptions; return findings without implementation.
---

# Challenge a proposal

Frame the problem, proposal, constraints and decision to be made from the user's
request and available evidence. Ask only about material missing intent. Keep this
workflow read-only apart from task-owned probes and presentation; no source edits,
publication or external mutations. Observe host permissions and sharing limits.

## Independent challenge

Apply [review](../review/SKILL.md) for cross-lineage eligibility, reviewer
selection, dispatch and evidence. Use one fresh reviewer and require it to read
and apply review in the assigned-reviewer role. Follow review's rule for named
models, settings and conflicts.

Give the reviewer the problem, constraints, proposal, source/version and raw
evidence. Do not prime it with the parent's preferred conclusion or earlier
reviewer verdicts. Ask it to:

- Identify assumptions that could invalidate the proposal.
- Offer the strongest simpler alternative and its tradeoff.
- Name evidence or a bounded probe that distinguishes the approaches.
- Separate demonstrated failures, static evidence, plausible risks and unknowns.

Require a complete plain-text final report with stable finding IDs, severity,
source locations, evidence, assumptions, alternative and discriminating next check.
The delegate must not use `html_render` or return only a child-thread presentation.
A timeout, missing report or completion status alone is not a completed challenge.

Allow safe, bounded probes only in task-owned isolated artifacts, with no live
system changes or source edits. No findings is acceptable. Do not demand scores,
consensus or a predetermined objection.

## Assess and report

Check each consequential finding against the sources or reproduction. Retain
statically demonstrated defects and clearly label risks that cannot safely be
reproduced. Preserve disagreement with evidence; do not automatically accept or
discard a finding because of its reviewer or rarity.

Default to one pass. Add one fresh, targeted second opinion only for a concrete
unresolved consequential risk or disagreement. Unless explicitly named, choose the
next eligible unused reviewer lineage in review's ordered list; report unavailable choices.
Report unresolved decisions after that; do not loop to unanimity. Follow explicit
user limits and stop task-owned work when complete or cancelled.

Return the recommendation, assumptions, supported findings, simpler alternative,
discriminating next check, reviewer identity and material gaps. In T3 Code, the coordinator checks user-facing
substantive reports with `html_preview`, inspects them and shows with `html_render`.
Use readable text when native HTML is unavailable or the result is brief.
Pressure testing alone does not authorize implementation.
