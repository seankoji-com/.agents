---
name: hillclimb
description: "Improve a workflow, artifact or product toward an agreed score over several judged rounds. Use when asked to hillclimb or to keep improving something until it reaches a target score."
---

# Improve a candidate through scored rounds

Improve a workflow, artifact or product over scored rounds. Freeze the rubric
and confirm who will judge the work before starting. Use `review-loop` for an
implementation and repair loop, and `choose-design` to pick mockups before building.

The T3 workflow `workflows/scored-loop.ts` runs the rounds with `skill:
"hillclimb"`. Its code defines judge dispatch, the frozen candidate, the
primary and panel phases, the lowest-score panel metric, the target and check
gate, the two-non-improving-rounds stop, the one retry of a failed evaluation,
explicit limits, the single automatic recovery and the score ledger. This skill
keeps the judgment: goal, rubric, roster, packet, repairs, finding
dispositions, the recovery's diagnosis and delivery.

## Requires T3 Workflows

Before anything else, confirm all three:

- The host is T3 Code with Workflows turned on.
- `~/.t3/workflows/scored-loop.ts` exists.
- `~/.config/t3-workflows/scored-loop.curl` exists. The operator creates it
  once per host; the README's "Use the scored loop on T3 Workflows" section
  has the steps.

If any is missing, report `hillclimb needs T3 Workflows: <what is missing>`
and stop. Do not run the rounds by hand, read hook tokens or run the
`t3 workflow` CLI.

## Establish the run

1. Inspect the current candidate, applicable instructions and delivery policy.
   Record the goal, permitted changes, audience and constraints. For UI work,
   preserve the agreed identity and name the screens, flows, states, platforms
   and viewports in scope. Match setup to the scope.
2. Read [evaluation criteria](references/rubric.md) to define the score and
   required checks. Freeze the rubric, precision, target, evidence and coverage
   before baseline scoring or edits. In UI mode, capture the real interface and
   research comparable products when external examples materially help define
   quality.
3. Read [judge selection](references/judges.md) to propose and confirm the
   roster, panel trigger and any preapproved panel primary. Get explicit
   confirmation, including approval of any disclosed lineage overlap, before
   implementation or judging. Before confirmation, continue independent,
   read-only setup. In UI mode, finish each judge's access pilot before edits.
4. Commit the baseline candidate in your checkout and run the required checks
   on it. Judges read committed objects only.

## Run the rounds on T3 Workflows

1. **Write one packet** as a JSON file in a Git-ignored directory of your
   worktree, with the fields review-loop's packet step lists and these
   differences:
   - `skill`: `"hillclimb"`.
   - `primary`: the confirmed primary's route key, or `namedReviewer` for a
     confirmed model outside the workflow's routes.
   - `panel`: `judges` (route keys; `[]` for a confirmed primary-only run),
     `trigger` (`primary-pass`, or `baseline` when the operator confirmed an
     earlier panel start) and an optional preapproved `panelPrimary`.
   - `codeAuthors`: the implementers' model families, including your own.
   - `overlapApproval`: the operator's words approving a disclosed overlap,
     when there is one.
   - Do not set `singleRound`: Hillclimb needs its own scores.
   When the workflow dispatches a judge, it gives the judge the
   [assigned-reviewer card](../review/references/assigned-reviewer.md) as its
   only instructions, the frozen candidate, the rubric and no other judge's
   scores.
2. **Start the run** with review-loop's curl command and a
   `hillclimb-<short thread id>-<slug>` idempotency key, then end your turn.
   HTTP 202 with a `runId` means it started. Do not poll.
3. **Answer each workflow turn** as review-loop's turn step describes: the
   limits report, selection data, receipts, repair rounds and the two-turn
   recovery. Use [review](../review/SKILL.md) for finding severity, evidence
   and dispositions. Repair from the named base, which is the phase's best
   eligible candidate. Save each owned revision when authorised. After each
   round, append results, findings and evidence to the
   [rolling report](references/reports.md), update the JSON score ledger and
   render the [score line graph](../review/references/score-chart.md) inline
   with a short update. In a recovery, a roster change may only replace a seat
   from the routes the turn lists, without a new lineage overlap.
4. **Read the result.** Read [round accounting](references/rounds.md) when
   interpreting a stop, a panel-entry fallback or a revised contract. Accept
   only `passed` or `passed-revised`; the latter names the original and
   revised targets and never claims the original was met. If the result is
   `goal-not-met`, collect the implementer's retrospective and offer the operator
   [a changed approach from the latest candidate](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop).
   A continuation starts a new run whose packet carries `continuation` and
   the same limits. Add the notes, choice and any approved continuation to
   the rolling report.

## Deliver the result

Select and freeze the final candidate the result names. For repository
changes, follow [raise-pr](../raise-pr/SKILL.md) for independent review of the
actual diff, templates, screenshots where applicable, attribution and verified
PR creation. A scoring judge may take a separate formal review assignment when
eligible. Use the normal review budget and apply required companions there,
including Hydrogen high when the formal scope calls for it. If formal review
cannot complete, follow `raise-pr` and preserve the prepared handoff.
An adopted `review_rounds: 1` can affect formal rechecks. Hillclimb still
requires its own scores and checks on the delivery candidate for success; a
formal fix that changes the candidate needs a new scored run or is reported
as unscored.

Reconcile identified bugs against the final revision even on an incomplete run.
Invoking the workflow authorises filing confirmed unfixed bugs in the task
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

Hand back the selected revision, run ID, goal status, report and evidence
locations, verified PR URL and head when applicable, local checks and formal
review. Report hosted CI, merge, deployment and live acceptance separately.
Stop owned tasks and preserve required evidence before cleanup.

When this is the outermost handback and nothing remains, finish with
[settle](../settle/SKILL.md).

## Boundaries

Use the workflow for the run's state, never a second scheduler or a hand-run
substitute. Follow host model, sharing and permission rules. This skill grants
no extra permission to publish, message others, spend, merge or deploy.
