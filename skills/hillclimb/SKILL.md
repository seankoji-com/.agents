---
name: hillclimb
description: "Improve a workflow, artifact or product toward an agreed score over several judged rounds. Use when asked to hillclimb or to keep improving something until it reaches a target score."
---

# Improve a candidate through scored rounds

Run [review-loop](../review-loop/SKILL.md) in Hillclimb mode to improve a workflow,
artifact or product to an agreed score. Freeze the rubric and confirm the judges
before work starts. Use `choose-design` to pick mockups before building.

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
   primary, secondary and any additional judges. Confirm any primary upgrade
   for the panel at the same time. Get explicit confirmation before
   implementation or judging. Continue independent, read-only setup while
   waiting.
4. Read [phase rules](references/rounds.md) before scoring and on resume.
   Keep the run record and original evidence in host-approved storage. Verify
   that repository-local storage is ignored. Track candidate/build identities,
   parents, models and options, task handles, scores, findings, checks, limits
   and next action. Reconcile the existing record on resume.

## Run the scored loop

To score and repair the candidate, call [review-loop](../review-loop/SKILL.md)
in the current thread. Supply the baseline, frozen rubric, confirmed roster,
required checks, evidence and explicit limits. The loop owns dispatch, repairs,
rechecks, score history and the HTML graph. Keep the
[rolling report](references/reports.md) for Hillclimb evidence and changes.

Give judges the same frozen candidate, scope, rubric, checks and evidence
requirements. Judges work read-only in separate sessions. Require independent
observations and scored reasoning. Each judge rechecks its prior findings, then
reports up to ten real issues and one unified score; read
[judge selection](references/judges.md) for the exact rules. In UI mode, each
judge uses the actual interface, exercises the required states and takes fresh
captures. Before judging, prepare access as described in
[judge selection](references/judges.md).

Run independent judges concurrently with isolated sessions and data. Give
each judge its own prior findings and a factual change summary. Keep other
judges' scores and verdicts out of its brief. Collect complete reports before
settling the next repair.

Use the [phase rules](references/rounds.md) for panel entry, candidate selection
and limits. Accept when all required scorers reach target on the same candidate
and checks and coverage pass. Keep measured results separate from judge scores.
Only two consecutive scores below the phase high trigger recovery. Explicit
limits, cancellation and blockers can interrupt the run without a scored failure.

If the loop returns a scored failure, as its caller follow the shared
[recovery procedure](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop)
through `review-loop`. Record the implementer's retrospective and any
operator-approved continuation in the rolling report.

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
