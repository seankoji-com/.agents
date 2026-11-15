---
name: plan-report
description: Propose a project plan or report progress and final calibration as a Gantt-style HTML report from a private JSON ledger. Use for coordinated runs, explicit timeline requests, or when ship, backlog-burn or implement calls for plan reporting.
---

# Show the plan and its progress

The coordinator keeps one JSON ledger per project and renders it with the bundled
Python 3.10+ standard-library helper. The ledger records estimates, observations
and decisions; it does not dispatch work or replace the host's task panel.

## Cadence and ownership

1. Render at plan proposal, at final handback and on request. During a coordinated
   run with delegates, render on every turn that made progress. Render solo
   progress only when asked. Skip no-progress turns.
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
   owner questions and relevant external events. Estimates are wall-clock minutes,
   separate from tokens, turns and USD.
4. Render proposal mode and present it. Record actual owner approval, its timestamp
   and approver. Freeze each task's original baseline at that point. A proposal
   or silence is not approval. Continue only work already authorised while a
   decision is pending.

## Report

1. Update as-of, statuses, forecasts, observed segments, review rounds/results,
   decisions and events. Record each change of model or effort as a new segment.
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

   Use `--mode propose` or `--mode final` for those boundaries. `--theme light`,
   `dark` or `auto` controls appearance; `--recent-hours 4` controls the recent
   timeline. Copy the complete skill folder when relocating it. Invalid ledgers
   exit nonzero with a useful message; correct the ledger before presenting.
5. In T3 the main thread uses `html_preview` then `html_render` on the generated
   file. Outside T3 use the host's equivalent artifact or an accessible file link.
   Reports are self-contained and make no network requests. Inspect the whole-run
   and recent timelines, scoped event rows, dependencies and tables before claiming
   a report is readable. Explain any missing host presentation capability.

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
