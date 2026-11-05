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

The operator chooses the roster: implementor, a mandatory primary judge and any
additional judges: one by default, zero or several on request. Discover eligible
models and exact options through supported host tools first, then ask for each
role the request leaves unnamed in the first setup batch, with a recommendation. Until the operator
answers, do only roster-independent setup; dispatch no implementor or judge.
No round cap, deadline, spend ceiling or endpoint allowance is required.
Record and honour explicit user limits. Routine implementation decisions need no
further approval. Changing criteria or roster requires explicit reconciliation
with the operator, retaining the old run's incomplete result and consumed budget.
When reconciling an additional-judge replacement before implementation, reuse a
valid primary baseline only if its primary, rubric, candidate and evidence remain
unchanged; retain consumed limits and failed attempts.

Keep the run record and evidence in the host-approved artifact location, verifying
that repository-local storage is ignored. Track setup, candidate revisions, model
identities/options, task handles, scores, findings, checks, counters and next action.
On resume, reconcile this record rather than reset budgets or discard evidence.

Schedule by dependency rather than section order. Start additional judges' access
pilots as soon as the roster, target environment and dispatch preflight are ready;
they need not wait for reference research or the scoring rubric. The primary's
baseline task verifies its access before scoring, once the rubric is frozen.
While pilots run, research references, capture the baseline in an independent
session, inspect the implementation, run independent existing checks, and prepare
the rubric, task coverage, evaluation briefs and report storage. Freeze criteria before edits and
scoring as required below. Wait only when no useful authorized work remains that
is independent of pending results.

Research leading examples relevant to the product's tasks and audience. Capture
their actual UI and the product's baseline before editing. Record source URLs,
capture dates, state, viewport and why each example is useful. Explain access gaps;
do not replace observations with invented screenshots. Reference quality and
interaction patterns without expanding scope or copying another product's identity.

Read [rubric](references/rubric.md) to select dimensions and define their boundaries
from the scoped user outcome and intended emotional response. Fix the reference
set, rubric, weights, precision, measurable checks and thresholds, and target score
before edits.

## Prepare independent judges

Use [review](../review/SKILL.md) for verified cross-lineage eligibility, dispatch,
evidence, finding severity and reporting. Judges differ from the coordinator and
all material implementors for the primary review. Additional judges may share
a lineage under review's verified higher-reasoning exception; otherwise they
differ from the coordinator, implementors and one another. Report unavailable
models or lineage conflicts without silent substitution.
Apply [dispatch preflight](../agent-tuneup/references/t3-dispatch.md) for T3 tasks,
including permission compatibility and the actual source of sharing authority.
Send only task-relevant material within that authority.

Dispatch additional judges' access pilots concurrently using supported browser or
device tools. Combine the primary's access verification with its baseline task:
first confirm the candidate identity, required interaction access and fresh capture
capability, then continue into scoring against the frozen rubric. Access failure
leaves the evaluation incomplete with no score. Additional pilots may run alongside
the baseline; require all routes to pass before implementation or panel entry. Prefer
isolated sessions to avoid interference; serialize only
operations that cannot safely share a browser, device or test data. A route unable
to do so is an unresolved roster conflict, not a screenshot-only substitute.
Record access results.

Judges are read-only. Give each the same scope, rubric, reference anchors, candidate
identity and task/state coverage. Require direct interaction with the actual UI,
fresh screenshots and action/results evidence. Code inspection and coordinator
captures alone do not satisfy this.

Launch panel judges concurrently on the same frozen candidate using isolated
sessions and data where supported. Run independent checks concurrently with one
another. During judging, organize
evidence, prepare report structure and draft possible repair plans from known
findings. Keep pending scores and verdicts explicitly unknown. Preserve the
candidate's source, build, runtime and test data until judging completes; checks
or captures that would alter them must use isolation or wait. Keep speculative
repairs as notes until complete reports establish the next action.

Judges may receive their own previous findings and a factual change summary.
Keep other judges' scores/verdicts and the operator's round reports out of their
briefs. Collect complete evidence-backed reports; task completion alone is not
approval. Return consequential findings to the coordinator for disposition.

## Run the two phases

Read [round accounting](references/rounds.md) before the first evaluation and on
recovery. This skill's score target and two-round stagnation counters govern design evaluation instead
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
   A primary-only roster has no panel phase: these gates accept the candidate.
5. In the primary phase, compare the primary score to its best. In the panel phase,
   compare the lowest judge score to the panel best. Only a strict increase resets
   the non-improvement counter. Two consecutive non-improving rounds stop the run.
   Never return to the primary phase to reset progress.

Apply the panel-entry and success gates before a stagnation stop, even when the
qualifying candidate scores below an earlier best. Retain its identity separately
from the historical best score. Follow the round reference for code-review repairs
that change the repair base or invalidate design approval.

Stop earlier for cancellation, an explicit user limit or a blocker that bounded recovery
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
are not code review. Without code review or an explicit waiver under `raise-pr`,
preserve the prepared body, branch and artifacts and report PR creation blocked.

Before concluding any run, reconcile all identified bugs against the final revision.
Invoking this skill authorises filing confirmed bugs left unfixed in the task's
repository, subject to explicit no-post limits. Apply [deferred-bug tracking](../review/references/deferred-bugs.md)
through `raise-issue`, including deduplication and verified issue URLs. Record
those URLs in the run record, PR and final handoff. Pending or blocked filing
leaves tracking incomplete, even when the design target passes. Rejected findings
and design preferences require no issue.

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
