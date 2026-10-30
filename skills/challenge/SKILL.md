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

Discover host delegation capabilities and exact model identities. Preserve named
models and settings. Otherwise choose the first available reviewer in this order
whose verified lineage differs from both the coordinating model and the proposal's
material model authors:
**Sol, Opus, Wonder Full, Argon, Grok 4.7**. Another provider alias, version or
effort of the same lineage is not independent. If authorship or reviewer lineage
cannot be established, or a required choice is unavailable, report the gap rather
than claiming cross-lineage review or silently substituting.

Use one fresh reviewer. In T3 Code, resolve models with
`orchestrator_capabilities`, dispatch with `delegate_task`, record `taskId` and
follow the returned `next`. Use native delegation elsewhere. Do not poll, create
a top-level thread, or let the child start further agents.

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
next eligible unused reviewer lineage in the ordered list; report unavailable choices.
Report unresolved decisions after that; do not loop to unanimity. Follow explicit
user limits and stop task-owned work when complete or cancelled.

Return the recommendation, assumptions, supported findings, simpler alternative,
discriminating next check, reviewer identity and material gaps. Delegated agents
return complete plain-text results. In T3 Code, the coordinator checks user-facing
substantive reports with `html_preview`, inspects them and shows with `html_render`.
Use readable text when native HTML is unavailable or the result is brief.
Pressure testing alone does not authorize implementation.
