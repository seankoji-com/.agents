---
name: design-loop
description: Improve a product's UI through reference research, direct interaction and scored cross-lineage judging, with annotated HTML reports each round and a final PR. Use for autonomous design iteration toward a score target, rather than operator-selected mockup options.
---

# Improve a product's design

Research comparable products, improve the real UI and collect evidence until the
agreed design target passes or the run stops. Model scores are design judgments,
not objective measurements or proof of user satisfaction.

## Establish the run

Inspect repository instructions, working tree, current UI and delivery policy.
Preserve unrelated work. Record the goal, audience, allowed screens and flows,
brand constraints, supported platforms, states and viewports. Iterate autonomously
inside that boundary; ask only about decisions that change it. Use `choose-design`
instead when the user wants to select mockup options before implementation.

Keep the run record and evidence in the host-approved artifact location, verifying
that repository-local storage is ignored. Track setup, candidate revisions, model
identities/options, task handles, scores, findings, checks, counters and next action.
On resume, reconcile this record rather than reset budgets or discard evidence.

Research leading examples relevant to the product's tasks and audience. Capture
their actual UI and the product's baseline before editing. Record source URLs,
capture dates, state, viewport and why each example is useful. Explain access gaps;
do not replace observations with invented screenshots. Reference quality and
interaction patterns without expanding scope or copying another product's identity.

Read [rubric](references/rubric.md) before scoring. Fix the reference set, rubric,
weights, precision, measurable checks and thresholds, and target score before edits.
Select the implementor, primary judge and at least one additional judge with the
operator at setup, reusing explicit choices. Record a design ceiling across both
phases in rounds, deadline or observable spend, plus an endpoint allowance and any
absolute limits; ask if none was supplied. Routine implementation decisions need
no further approval. Changing criteria or roster requires explicit reconciliation
with the operator, retaining the old run's incomplete result and consumed budget.

## Prepare independent judges

Use [review](../review/SKILL.md) for verified cross-lineage eligibility, dispatch,
evidence, finding severity and reporting. Judges differ from the coordinator and
all material implementors; panel judges also differ in lineage from one another. Discover
exact models/options through supported host tools and preserve named choices.
Report unavailable models or lineage conflicts without silent substitution.
Apply [dispatch preflight](../agent-tuneup/references/t3-dispatch.md) for T3 tasks,
including permission compatibility and the actual source of sharing authority.
Send only task-relevant material within that authority.

Before baseline scoring, pilot each selected judge route's ability to view and
interact with the target using supported browser or device tools. A route unable
to do so is an unresolved roster conflict, not a screenshot-only substitute.
Record access results and stop dependent evaluation when access is unavailable.

Judges are read-only. Give each the same scope, rubric, reference anchors, candidate
identity and task/state coverage. Require direct interaction with the actual UI,
fresh screenshots and action/results evidence. Code inspection and coordinator
captures alone do not satisfy this. Freeze the candidate during judging. Serialize
sessions where browsers, devices or test data would interfere.

Judges may receive their own previous findings and a factual change summary.
Keep other judges' scores/verdicts and the operator's round reports out of their
briefs. Collect complete evidence-backed reports; task completion alone is not
approval. Return consequential findings to the coordinator for disposition.

## Run the two phases

Read [round accounting](references/rounds.md) before the first evaluation and on
recovery. This skill's user-defined design acceptance requires every judge to
pass. Its phase counters and run-wide ceiling govern design evaluation instead
of `review`'s generic finding-based round limit or advice against unanimity.
Independent code review at the PR endpoint keeps its normal budget and gates.

1. Evaluate the baseline with the primary judge to seed the primary best score.
2. Implement scoped repairs from the phase's best candidate, run covering checks
   and obtain fresh evaluation. Save each owned candidate as a local commit when
   authorized, or preserve an exact patch/snapshot without touching unrelated work.
3. After every change round, create and present the HTML report defined in
   [reports](references/reports.md), including unsuccessful rounds. Preserve the
   original findings and captures; append dispositions and fresh evidence.
4. Enter the panel phase once the primary meets target, required checks pass and
   required coverage is complete. The first complete panel evaluation seeds its
   best score. All judges, including the primary, independently evaluate this same
   candidate. Each subsequent change requires fresh evaluation by the whole panel.
5. In the primary phase, compare the primary score to its best. In the panel phase,
   compare the lowest judge score to the panel best. Only a strict increase resets
   the non-improvement counter. Two consecutive non-improving rounds stop the run.
   Never return to the primary phase to reset progress.

Apply the panel-entry and success gates before a stagnation stop, even when the
qualifying candidate scores below an earlier best. Retain its identity separately
from the historical best score. Follow the round reference for code-review repairs
that change the repair base or invalidate design approval.

Stop earlier for cancellation, the design ceiling or a blocker that bounded recovery
cannot resolve. A failed or missing evaluation never becomes a fabricated score.
The round reference distinguishes candidate failures from infrastructure failures.

Accept only when every panel judge meets target on the same candidate, required
checks pass and required interaction coverage is complete. Preserve measured
results separately from scores. A high score cannot waive a failed gate.

## Deliver the result

Keep the best candidate with its matching evidence and complete history. On a
stop, state the reason and unmet criteria; do not call the run successful. Select
the final revision under the round rules before requesting final code review.

Apply [raise-pr](../raise-pr/SKILL.md), including independent code review of the
actual diff, templates, screenshots, attribution and verified PR creation. A design
judge can perform code review in a separate task if eligible. Design scores alone
are not code review. Address confirmed bugs under `review`'s disposition/tracking
rules within authority. Missing code review blocks PR creation unless the user
explicitly waives that gate under `raise-pr`; absent a waiver, preserve the prepared
body, branch and artifacts and report that gate rather than infer a waiver.

For success, raise the product PR with current evidence. For an incomplete run,
raise a **draft** with `GOAL NOT MET` in its title and description, identifying
the stop reason, failed checks, missing evidence and remaining work. Include
per-round scores, actual model identities, candidate history and accessible HTML
reports/screenshots. Disclose artifacts unavailable to PR readers. Follow the
target repository's delivery policy where it does not use PRs. This skill grants
no extra authority to push, upload private evidence, publish, merge or deploy.

Hand back the verified PR URL and head, score and goal status, report locations, local
checks, code review and remaining gates. Separate hosted CI, merge, deployment and
live acceptance. Stop owned tasks and preserve required evidence before cleanup.
