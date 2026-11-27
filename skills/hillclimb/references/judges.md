# Confirm the implementer and judges

## Propose the roster

1. Use the current thread as implementer by default. List proposed delegated
   implementers as well. Default the primary judge to Sol, or Opus if the
   current thread is Sol. Propose a secondary from Sol, Opus or DeepSeek Flash.
   Prefer models unused by implementers or other judges. Include additional
   scoring seats when the operator chooses them.
2. Use high effort for each role at setup. Discover exact routes and validate
   effort settings through the host. If the current thread cannot implement at
   verified high effort, propose an eligible implementer.
   Apply [T3 dispatch preflight](../../agent-tuneup/references/t3-dispatch.md)
   where applicable. Check sharing authority, permissions, headroom and route
   support for the chosen mode. Surface unavailable or incompatible options and ask
   the operator to choose when a required seat cannot be filled.
3. Prefer different lineages. Flag overlaps among implementers and primary
   or secondary judges, or among judges. Explain that shared lineage can
   share blind spots. Offer an eligible diverse lineup when available.
   Explicit approval of the disclosed overlap allows a shared lineage or
   model for scoring, with distinct read-only judge sessions. Record it.
4. Present exact models, routes, effort and any proposed primary upgrade.
   Get explicit confirmation before scoring or implementation.
   Reconfirm material roster changes, except a replacement made during the
   single automatic recovery from an already authorised eligible model that
   needs no new lineage approval. Record and report that change. When the
   primary first scores at least 90% of target, start every confirmed panel
   seat on that candidate. Use the [phase rules](rounds.md#state-transitions)
   when starting the panel and applying the acceptance gate.

## Route scoring and delivery review

Use the [reviewer selection rules](../../review/references/model-selection.md)
to verify every direct judge's route and effort, including DeepSeek Flash.
Check execution metadata before accepting each score. Report a route blocker
when the required setting or access cannot be verified. For delivery, apply
the [formal review companion rules](../../review/references/parallel-review.md).
Hydrogen high is used only if required by separate formal delivery review.
Formal code review retains its code-author lineage constraints when the
operator approves an overlap for scoring.

## Prepare access

Use the [assigned reviewer card](../../review/references/assigned-reviewer.md)
for scoring tasks. Identify the task as scoring, share only the approved
scope and include expected models and settings, the candidate, the rubric,
required observations and approval of any overlap. Ask for an independent
view with evidence.

One score covers correctness, accessibility and design. Each judge first
rechecks its findings on the previous candidate, marking each fixed or open
with evidence, then lists up to 10 findings: the issues that most affected its
score, most important first. It reports only real issues; fewer, or none, is
valid.

After roster confirmation, verify access to the candidate and evidence
needed by the selected mode. In UI mode, start confirmed panel judges'
access pilots before edits. They may run alongside remaining setup or
the primary's baseline task. The primary verifies access before scoring.
Each UI route needs direct interaction and fresh captures in the supported
browser or device. Use isolated sessions and test data wherever possible.
Confirm all UI routes before editing or entering panel scoring. For a judge
added at panel entry, verify the replacement's access before it scores.
Record access failures as incomplete evaluations with unavailable scores
and apply [bounded recovery](rounds.md#failures-and-explicit-limits).
Record which route, environment and required actions each access pilot proved.
On a [continued run](../../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop),
reuse successful pilots that still cover the same judge and conditions.
Run only a missing or invalidated capability probe. Each scored UI candidate
still needs direct interaction and fresh captures in the required states.

## Confirm any primary upgrade before scoring

At roster confirmation, offer an eligible model or effort upgrade for panel
entry when useful, such as Opus xhigh or Fable high. Show the exact model,
route, effort, headroom and any lineage overlap. Offer settings the host can
verify, at or below xhigh. Use an approved upgrade when its route, effort and
lineage conditions still match. Otherwise start the panel with the existing
confirmed primary and record why.

Use a fresh task for the approved panel primary. All panel judges score the
same frozen candidate together before the next edit. Keep the chosen primary
throughout the panel phase. A required later roster change needs explicit
reconciliation under [round accounting](rounds.md#state-transitions).
