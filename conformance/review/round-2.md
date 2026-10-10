# Pre-PR adversarial review, round 2

- Reviewer: Codex (`codex` / `gpt-6.1-sol`, reasoning high), dispatched with `delegate_task`, role `review`
- T3 task: `node:delegated-task:command%3Amcp%3Ae8eb6bcd-a2f7-437b-9d1e-575bca98bf84%3Adelegate-task%3Aimps-t3-build%253Acodex-review%253Ar2`
- clientRequestId: `imps-t3-build:codex-review:r2`
- Reviewed commit: `73c2809bec20da87539305240aefe3871417f06e`
- Verdict: **none.** T3 cancelled the task when the parent session ended, before the final message. Its progress messages (read with `t3_thread_read`) reported the gaps below; they are treated as findings and the next round re-reviews all of them.
- The reviewer ran the full suite: 99 tests passed in 167.7 s.

| # | Reported gap | Resolution |
| --- | --- | --- |
| A | A review's binding is captured when the dispatch is recorded, so edits between the host call and the record let approval cover a later tree | The review dispatch action carries `args.snapshot` (excluded from the action id). The record echoes it, and the verdict binds to that snapshot. A dispatch that was already sent but is no longer offered can be recorded with the whole echoed action, whose id and clientRequestId are checked, so the child is never orphaned. `verifying` always queries live children. `test_review_regressions.Round2FindingsTest.test_a_review_binding_is_the_snapshot_next_issued` |
| B | A fast serial child that commits before the parent records its dispatch changes HEAD, which changes the dispatch action id | The serial writer baseline comes from run state (`execution.serial_base`, set on entering executing, after each serial writer and on repair), not from live HEAD. `test_b_fast_serial_child_keeps_its_dispatch_valid` |
| C | An uncertain dispatch has no recorded round, so cancellation could report success without confirming that the child stopped | Cancellation blocks with `cancel_unconfirmed`, naming the uncertain clientRequestIds; `cancelled` is refused until the operator clears them with the printed `retry-cancel`. `test_c_cancel_does_not_ignore_uncertain_dispatches` |
| D | An accepted child whose thread still has pending runs is skipped by cancellation | Rounds with `hasPendingChildRuns` count as live (`engine.needs_stop`) for cancellation and cross-parent checks; accepted results stay accepted. `test_d_cancel_reaches_accepted_children_with_pending_runs` |
| E | The artifact temp file used a predictable name that a planted symlink could redirect | The temp file is created with `mkstemp` (O_EXCL), and a symlinked target is refused. `test_e_planted_artifact_target_symlink_is_refused` |
| F | Uninstall could delete through a symlinked version directory before failing | Uninstall and install refuse symlinked plugin or version directories before touching anything. `Round2InstallerTest.test_f_symlinked_version_directory_is_refused` |
| G | Unfinished at cancellation: recipe stamping, recovery from an unavailable reviewer | Recipe stamping now refuses symlinked evidence directories. Recovery from an exhausted reviewer chain goes through the `provider_unavailable` retry, covered by `test_blocked.BlockedPathsTest.test_every_resume_command_unblocks`. Both are in round 3's scope. |
