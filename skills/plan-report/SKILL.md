---
name: plan-report
description: "Show a plan, progress or final calibration on an HTML timeline from a private ledger. Use for coordinated work, timeline requests or reporting in ship, backlog-burn and implement."
---

# Show the plan and its progress

Show what was planned, what is running and which decisions need the user.
Keep one JSON ledger per project and render it with the bundled Python 3.10+
helper. Use the host's task list for live execution status.

## Cadence and ownership

1. Render at proposal, task completion, final handback and on request, including
   solo tasks. Task completion means the agreed endpoint, such as merge or close,
   not each review or fix round; those get short chat updates. Apply an adopted
   project's `report_cadence` override when present. Whole-run timelines appear
   only at proposal and final handback; progress reports show the remaining work.
2. The main-thread coordinator is the sole ledger writer and presenter. Delegates
   return segment start/completion timestamps, actual model/provider/effort,
   review round/result and exposed usage with sources. They never present the
   report. Use host start/completion notifications when available; label uncertain
   timing rather than inventing precision.
3. Reuse the caller's authority and settled decisions. Plan approval freezes
   estimates; it adds no authority to publish, dispatch, spend or change scope.

## Propose

1. Read the [ledger contract](references/ledger.md) before creating or changing a
   ledger. Read [host cost evidence](references/host-costs.md) when collecting
   usage or choosing its scope; refresh capability claims against the current host.
2. Choose a repository-ignored work directory inside the session's recorded
   worktree and verify the ledger and output paths with `git check-ignore` before
   writing. Keep ledgers and reports untracked, private and out of GitHub. Removing
   the worktree loses this history; use another destination only with authority.
   Checked-in fixtures must be synthetic.
3. Record project name/status, Australia/Sydney timezone, run start and as-of;
   tasks, streams, dependencies, owner identities, forecasts, build/review
   allocations and planned review rounds; milestones/gates with required reviewers;
   decision records and relevant external events. Estimates are wall-clock minutes,
   separate from tokens, turns and USD. Start titles with the issue number, such
   as `#242 Widescreen`, and record each task's `thread` link when the host
   exposes one; the chart links the number to it.
4. Render proposal mode and present it. Record actual owner approval, its timestamp
   and approver. Freeze each task's original baseline at that point. A proposal
   or silence is not approval. Continue only work already authorised while a
   decision is pending.

## Report

Before asking a material owner question, check the latest decision record and
settled answers. Batch foreseeable questions through the host-native question or
input tool, with the recommendation first. Continue independent authorised work
while an answer is pending. Rendering a report is not asking the question.

Record the actual prompt, owner, observed asked time and affected tasks as pending.
On a real reply, append a decided snapshot with the actual answer, observed decision
time and optional rationale/source, keeping earlier records. Unknown times stay
unknown. A recommendation or silence is not a decision. Do not re-prompt every
progress turn or ask again after an answer is recorded. The coordinator owns
asking and recording replies; the renderer only displays the ledger.

1. Read the real clock at render time and set as-of to that observation in
   Australia/Sydney with its correct offset. Never advance it to a forecast or
   imagined task completion. Historical observation boundaries remain valid.
   Update statuses, forecasts, observed segments, review rounds/results,
   decisions and events. Record each change of model or effort as a new segment.
   Refresh `forecast.end` for every running/review task on every coordinator
   update, even when no report is due; never invent an ETA to hide a stale forecast.
   Open segments end at as-of for the current view. Mark waiting periods as scoped
   events; do not silently charge them as build/review time.
2. Copy cost only from exposed host observations. Preserve the source and whether
   USD is a host estimate. Missing data is `unknown`, including unavailable USD
   on subscriptions. Keep each metric at either task or segment scope to avoid
   double-counting. A task total spanning models remains unattributed.
3. Preserve original baselines. A replan appends a timestamped rebaseline with
   reason, approver and complete changed-task allocations. Update forecasts
   separately. Earlier estimates and overruns remain visible.
4. Run the renderer using absolute input/output paths, from any working directory:

   ```sh
   python3 /installed/plan-report/scripts/render.py /worktree/ignored/ledger.json \
     --mode report --output /worktree/ignored/report.html
   ```

   Use `--mode propose` at proposal and `--mode final` at final handback. Read the
   [chart and renderer options](references/ledger.md#chart) before changing the
   view, theme flags or synthetic replay. Correct a rejected ledger before presenting.
   Use an observed as-of time for every live report.
5. In T3 the main thread uses `html_preview` then `html_render` on the generated
   file. Outside T3 use the host's equivalent artifact or an accessible file link.
   Reports are self-contained and make no network requests. Inspect the timelines
   included in that mode, the progress bar, mtoks totals and populated tables before
   claiming a report is readable. Explain any missing host presentation capability.

## Final calibration

1. Close observed segments and reconcile completed, cancelled and unfinished work.
   Render final mode even when the endpoint is incomplete; identify remaining gates.
2. Compare original approved build/review allocations with completed segments by
   provider, model, effort and kind. Compare planned and distinct actual review
   rounds per task. A changed identity makes that task/kind comparison **not
   comparable**; keep its original estimate rather than transferring it to the
   replacement model. Ratios use observed segment minutes, not task span or
   summed parallel project elapsed time.
3. Report sourced known cost subtotals and missing coverage separately. Unapproved
   proposals and unfinished tasks cannot establish final estimate accuracy.
   Feed this calibration and its limitations into ship's retrospective when ship
   is the caller. Keep local checks, independent review, hosted CI, publication,
   deployment and live acceptance separate.
