---
name: hillclimb
description: "Improve a workflow, artifact or product toward an agreed score over several judged rounds. Use when asked to hillclimb or to keep improving something until it reaches a target score."
---

# Improve a candidate through scored rounds

Improve a workflow, artifact or product over scored rounds. Freeze the rubric
and confirm who will judge the work before starting. Use `review-loop` for an
implementation and repair loop, and `choose-design` to pick mockups before building.

## Establish the run

1. Inspect the current candidate, applicable instructions and delivery policy.
   Record the goal, permitted changes, audience and constraints. For UI work,
   preserve the agreed identity and name the screens, flows, states, platforms
   and viewports in scope. Match setup to the scope.
2. Read [evaluation criteria](references/rubric.md) to define the score and
   required checks. Freeze the rubric, decimal places, target, evidence and coverage
   before baseline scoring or edits. Capture a baseline under comparable
   conditions. In UI mode, capture the real interface and research comparable
   products when external examples materially help define quality.
3. Read [judge selection](references/judges.md) to propose and confirm the
   roster, panel trigger and any preapproved primary upgrade. Get explicit
   confirmation before implementation or judging. Before confirmation,
   continue independent, read-only setup.
4. Read [round accounting](references/rounds.md) before scoring and on resume.
   Keep the run record and original evidence in host-approved storage. Verify
   that repository-local storage is ignored. Track candidate/build identities,
   parents, models and options, task handles, scores, findings, checks, limits
   and next action. Reconcile the existing record on resume.

## Evaluate and improve

Use [review](../review/SKILL.md) for finding severity, evidence and dispositions.
Apply this skill's roster, score, companion and stopping rules to scoring tasks.
Apply ordinary formal review selection and required companions at delivery.

Give judges the same frozen candidate, scope, rubric, checks and evidence
requirements. Judges work read-only in separate sessions. Require independent
observations and scored reasoning. Each judge rechecks its prior findings, then
reports up to ten real issues and one unified score; read
[judge selection](references/judges.md) for the exact rules. In UI mode, each
judge uses the actual interface, exercises the required states and takes fresh
captures. Before judging, prepare access as described in
[judge selection](references/judges.md).

Run judges for the same evaluation concurrently with isolated sessions and data
where supported. Serialize only operations that cannot safely share resources.
Keep source, build, runtime and data stable during judging. Use the time to
organize evidence, prepare the report and investigate independent failures.
Judges may see their own prior findings and a factual change summary. Keep
other judges' scores and verdicts out of their briefs. Collect complete
reports before settling the next repair.

1. Score the baseline with the primary, or with the full panel if it starts at
   baseline. Seed the phase's best from that evaluation.
2. Make scoped repairs from the phase's best eligible candidate and run covering
   checks. Save each owned revision when authorised, or preserve an exact patch
   or snapshot. Obtain fresh evaluation.
3. After each round, append results, findings and evidence to the
   [rolling report](references/reports.md), update the JSON score ledger and
   render the [score line graph](../review/references/score-chart.md) inline
   (after every completed scoring round, recovery and final handback) with a
   short update. Include failed and incomplete rounds.
4. When the primary reaches target and required checks and coverage pass, or
   when an earlier confirmed trigger fires, confirm any pending primary upgrade
   choice. Run the full confirmed panel on that frozen candidate. The lowest
   judge score seeds the panel baseline. Evaluate every later panel candidate
   with the full panel. Primary-only scoring is final only when the operator
   confirmed a run without a panel.
5. Test transition and success gates before stagnation. The metric is the
   primary score during primary-only rounds and the lowest score during panel
   rounds. Only a strict increase over the phase's best resets stagnation.
   Two consecutive non-improving rounds stop the run. Apply the round reference
   for failures, explicit limits and changes to the delivery candidate.

   A failed run gets one automatic recovery before any operator question.
   Record the attempt before the fix, diagnose from the retained evidence, fix
   the cause and re-invoke once from the latest candidate under the original
   run ID and spent slot, with a fresh counter. A fix that fails or is blocked
   before dispatch is recorded as spent.
   Retain the phase and roster; record any criteria or roster change and flag a
   pass under either with the original target. A second failure stops the
   run and reports. Apply the shared [recovery procedure](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop)
   for accounting and handback.

Accept only when all confirmed scorers reach target on the same candidate and
all required checks and coverage pass. Keep measured results separate from
judge scores. Follow the run's explicit limits. Stop incomplete on an unresolved
blocker, a limit that prevents completion or stagnation, after the single
recovery.

After the automatic recovery, if the run still stops incomplete, collect the
implementer's retrospective and offer the operator [a changed approach from the
latest candidate](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop).
Add the notes, choice and any approved continuation to the rolling report.

## Deliver the result

Select and freeze the final candidate under the round rules. For repository
changes, follow [raise-pr](../raise-pr/SKILL.md) for independent review of the
actual diff, templates, screenshots where applicable, attribution and verified
PR creation. A scoring judge may take a separate formal review assignment when
eligible. Use the normal review budget and apply required companions there,
including Hydrogen high when the formal scope calls for it. If formal review
cannot complete, follow `raise-pr` and preserve the prepared handoff.
An adopted `review_rounds: 1` can affect formal rechecks. Hillclimb still
requires its own scores and checks on the delivery candidate for success.

Reconcile identified bugs against the final revision even on an incomplete run.
Invoking this skill authorises filing confirmed unfixed bugs in the task
repository, subject to explicit no-post limits. Follow
[deferred-bug tracking](../review/references/deferred-bugs.md) through `raise-issue`
for each confirmed unfixed bug.
Deduplicate and record verified issue URLs in the run record, PR and handoff.
Pending or blocked filing leaves tracking incomplete. Rejected findings and
preferences require no issue.

Where authorised and supported, raise a reviewed PR on success or a reviewed
draft with `GOAL NOT MET` in the title and description on an incomplete run
with changes. Include the score history, stop reason or success evidence, unmet
gates and accessible report. Follow repository policy when it has another
delivery path. For non-repository work or a no-change result, return the
selected candidate and its evidence. Keep pushes, private evidence uploads,
publication, merges and deployment within existing authority.

Hand back the selected revision, goal status, report and evidence locations,
verified PR URL and head when applicable, local checks and formal review.
Report hosted CI, merge, deployment and live acceptance separately. Stop
owned tasks and preserve required evidence before cleanup.

When this is the outermost handback and nothing remains, finish with
[settle](../settle/SKILL.md).
