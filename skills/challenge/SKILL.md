---
name: challenge
description: "Pressure-test an idea, design or proposal with an independent reviewer when asked to challenge assumptions, give a second opinion or answer 'are you sure?'. Return findings without edits."
---

# Challenge a proposal

Get an independent critique of the idea, a simpler option and evidence that
would help the user choose. Use this workflow for "are you sure?", "challenge
this" or requests for an adversarial second opinion. Use the implementation
workflow for requests to build or repair.

Frame the problem, proposal, constraints and decision from the request and
available evidence. Ask only about material missing intent. Keep the work
read-only apart from task-owned probes and presentation. Do not edit source,
publish or change external state during the challenge. Observe host permissions
and sharing limits.

## Independent challenge

Apply [review](../review/SKILL.md) for scope-appropriate eligibility, reviewer
selection, dispatch and evidence. Use one fresh reviewer and require it to read
review's [assigned-reviewer card](../review/references/assigned-reviewer.md). Follow review's rule for named
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
unresolved consequential risk or disagreement. Apply review's model-selection
and companion rules. A fresh proposal opinion need not use another model family;
written-code review still excludes the code authors' lineages.
Report unresolved decisions after that; do not loop to unanimity. Follow explicit
user limits and stop task-owned work when complete or cancelled.

Return the recommendation, assumptions, supported findings, simpler alternative,
discriminating next check, reviewer identity and material gaps. In T3 Code, the coordinator checks user-facing
substantive reports with `html_preview`, inspects them and shows with `html_render`.
Use readable text when native HTML is unavailable or the result is brief.
Pressure testing alone does not authorize implementation.
