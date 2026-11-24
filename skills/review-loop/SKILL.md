---
name: review-loop
description: "Implement, review and repair in rounds when asked to iterate with independent review or when the user invokes review-loop. Work toward the agreed score and acceptance criteria."
---

# Implement, review, repair

Agree on what success looks like, then alternate repairs and independent
evaluation until the score and required checks pass. Ordinary engineering work
does not automatically need this loop.

The T3 workflow `workflows/scored-loop.ts` runs the loop. Its code defines
reviewer selection, judge dispatch, the frozen candidate, the score metric, the
target and check gate, the two-non-improving-rounds stop, the one retry of a
failed evaluation, explicit limits, the single automatic recovery and the score
ledger. This skill keeps the judgment: scope, rubric, packet, repairs, finding
dispositions, the recovery's diagnosis and delivery.

## Requires T3 Workflows

Before anything else, confirm all three:

- The host is T3 Code with Workflows turned on.
- `~/.t3/workflows/scored-loop.ts` exists.
- `~/.config/t3-workflows/scored-loop.curl` exists. The operator creates it
  once per host; the README's "Use the scored loop on T3 Workflows" section
  has the steps.

If any is missing, report `review-loop needs T3 Workflows: <what is missing>`
and stop. Do not run the loop by hand, read hook tokens or run the
`t3 workflow` CLI.

## Steps

1. **Set the scope and score.**
   Read the request, repository rules, working tree and existing progress.
   Record observable acceptance criteria and the authorised endpoint, which may
   be a verified local change. Ask only about material unresolved choices.
   Fix the rubric, precision and target before editing; reuse supplied
   criteria and ask about the target only if you cannot infer it. Record any
   explicit round or deadline limit. Done when criteria, rubric, precision,
   target and limits are written down.

2. **Prepare the baseline.**
   For UI work likely to end in a PR, use [raise-pr](../raise-pr/SKILL.md)
   before editing to capture mobile and desktop baselines. Implement directly
   by default; delegate substantial independent work when it warrants a worker.
   Commit the baseline candidate in your checkout and run the required checks
   on it. Judges read committed objects only. Done when the baseline SHA and
   its check results exist.

3. **Choose companions.** Before naming any, read the
   [review](../review/SKILL.md) skill's companion rules. Name Hydrogen as a companion for UI or visual scope. Where
   the OCR lane applies, run it on each frozen candidate yourself and report it
   in that round's checks. Leave the primary unnamed unless the user named one:
   the workflow selects it under review's
   [model selection](../review/references/model-selection.md) rules. When the
   workflow dispatches a judge, it requires the
   [assigned-reviewer card](../review/references/assigned-reviewer.md) as the
   judge's only review instructions.

4. **Write one packet** as a JSON file in a Git-ignored directory of your
   worktree:
   - `invokerThread`: `printenv T3CODE_THREAD_ID`.
   - `skill`: `review-loop`. `title`: a short task name.
   - `project`: your T3 project ID; judges open their threads there.
   - `maxRuntimeMode`: your thread's `runtimeMode` from `t3_thread_read`.
   - `scope`: `code`, `plan`, `prose` or `visual`. Only `code` applies the
     lineage gate.
   - `checkout` (absolute path), `base`, `candidate` and `checks`
     (`passed`, `coverage`, `summary`) for the baseline.
   - `criteria`, `rubric`, `target` and `scale` (`min`, `max`, `precision`).
   - `codeAuthors`: the model families that wrote or will repair the code,
     including your own.
   - `reviewContext`: the checks judges may run, the exact commands and
     environment, a scratch directory verified with `git check-ignore`, and
     the evidence and screenshots required.
   - Optional `roster` (`primary` only when the user named one; `companions`),
     `limits` (`repairRounds`, `deadline`, `spendCap`), `judgeMinutes`,
     `repairMinutes`.
   - `continuation` only for an operator-approved continuation (step 7):
     `priorRun`, the prior run's `repairsUsed`, the `approval` message, its
     final ledger as `priorLedger` (JSON text) and `sameContract`.
   Never set `test`: test fields are for acceptance runs.

5. **Start the run, then end your turn.**

   ```sh
   curl -sS --noproxy '' -K ~/.config/t3-workflows/scored-loop.curl \
     -H 'content-type: application/json' \
     -H 'idempotency-key: loop-<short thread id>-<slug>' \
     --data-binary @<packet>.json
   ```

   HTTP 202 with a `runId` means it started; the same key returns the same
   run. `404 hook_not_found` means the workflow or hook is missing: report it
   and stop. Do not poll. The workflow writes to this thread.

6. **Answer each workflow turn**, then end your turn:
   - **Selection data:** call the limits snapshot and
     `orchestrator_capabilities` as asked and submit what they show,
     including each listed route whose exact model or effort is missing and
     whether the spend cap is reached.
   - **Receipts:** read each listed judge thread with `t3_thread_read` and
     submit its turn ID, `executedModel` and run count, null where none is
     shown, with refreshed route availability and the spend cap.
   - **Repair round:** before repairing, read the
     [implementation-participant card](../review/references/implementation-participant.md).
     Verify each finding's location, evidence, severity and impact. When
     deciding it, apply review's [feedback dispositions](../review/references/feedback-dispositions.md).
     If consecutive rounds found different verified defects from the same
     design assumption, reconsider that assumption before repairing. Repair
     from the named base, delete or narrow code when that fixes the cause,
     commit, run the required checks and submit the candidate. Set
     `addsRequiredFix` when every later candidate must keep a fix it adds; the
     workflow then never hands back an earlier candidate. After each
     round, update the JSON score ledger from the turn and render the
     [score line graph](../review/references/score-chart.md). Report a blocker
     or a reached spend cap or deadline in `stop` instead of repairing past it.
   - **Recovery:** follow budget-exhaustion's
     [single recovery](../review/references/budget-exhaustion.md#continue-a-stopped-scoring-loop),
     steps 2 to 4: diagnose from retained evidence, fix the cause and submit
     the frozen candidate, any revised contract or checks, and refreshed route
     availability, or `fix-failed` when the fix is blocked. The workflow
     records the attempt, checks the revision and runs it at most once.

7. **Accept the evidence or explain the stop.**
   The result turn gives the status, final candidate, scores, findings and
   the full ledger. Render the chart. Apply review's release rules to each
   remaining finding and track confirmed unfixed bugs with verified issue
   URLs. On `goal-not-met`, collect a retrospective and offer the operator a
   changed approach from the latest candidate, as budget-exhaustion's
   operator-approved continuation describes. A continuation starts a new run
   whose packet carries `continuation` and the same limits, so it gets no
   second automatic recovery.
   A `passed-revised` result names the original and revised targets; never
   claim the original target was met.

8. **Verify the agreed endpoint.**
   A source fix does not complete a requested merge or deployment. For PR
   creation or updates use [raise-pr](../raise-pr/SKILL.md); new PRs need
   completed independent review. Refresh checks and reviews for the current
   head before merging. For a deployment, verify the deployed revision and
   behaviour on each target.

## Outputs

Keep updates brief: result, material findings and next action. The final
handoff gives revision, run ID, eras, rounds, target, best and current scores,
models and their receipts, checks, dispositions, deferrals and endpoint
evidence. Separate local validation, hosted checks, independent review, merge
and deployment. Delegates return plain-text reports and the ledger path; only
the main thread renders charts and findings reports.

## Boundaries

Use the workflow for the loop's state, never a second scheduler or a hand-run
substitute. Follow host model, sharing and permission rules. Preserve
unrelated work and repository protections. This skill grants no extra
permission to publish, message others, spend, merge or deploy.
