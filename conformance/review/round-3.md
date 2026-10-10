# Pre-PR adversarial review, round 3

- Reviewer: Codex (`codex` / `gpt-6.1-sol`, reasoning high), dispatched with `delegate_task`, role `review`
- T3 task: `node:delegated-task:command%3Amcp%3A6cf59287-70f8-42b9-9f4a-1c586a5e8c93%3Adelegate-task%3Aimps-t3-build%253Acodex-review%253Ar3`
- clientRequestId: `imps-t3-build:codex-review:r3`
- Reviewed commit: `a50f506cd17889be887c675823142d04cea9a59d`
- Verdict: **adverse** (6 blocker, 7 major). 107 tests passed; the reviewer reproduced each gap with temporary fixtures.
- Earlier items: round-1 2, 3, 6, 7, 8, 10, 11, 13 and 15 resolved; round-2 B and E resolved; the rest had unresolved variants, folded into the findings below.

| # | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| 1 | blocker | Completion ignores accepted children whose threads still have pending runs | Fixed: rounds with pending child runs stay live; `ready`, `publishing` and `completed` are refused while any child or uncertain dispatch may be running, and `next` offers queries instead. `Round3FindingsTest.test_1_no_completion_while_child_runs_are_pending` |
| 2 | blocker | A late dispatch receipt cannot be recorded once cancellation starts, leaving a running child untracked | Fixed: a dispatch already sent can be recorded with its full echoed action during `cancelling` or `blocked`; cancellation then reaches it. `test_2_late_dispatch_receipt_is_tracked_during_cancellation` |
| 3 | blocker | A review result acquires the policy binding current at recording, not at issue | Fixed: the review dispatch action carries its full binding (snapshot, contract hash, policy hash), echoed by the record; the verdict binds to it. `test_3_review_binding_includes_issue_time_policy` |
| 4 | blocker | `verdict: approve` with unresolved blocker or major findings satisfies readiness | Fixed: `approve` with any blocker or major finding is recorded as `adverse` (the reported verdict is kept). `test_4_approve_with_major_findings_counts_as_adverse` |
| 5 | blocker | Uncommitted child edits are accepted, then "integrated" by merging an unchanged branch, then force-removed by cleanup | Fixed: a writer in its own worktree must leave it clean with commits beyond its baseline; integration refuses a branch with no new commits; worktree cleanup no longer uses `--force` (probes excepted) and branch cleanup uses `-d`. `test_5_uncommitted_child_work_is_rejected_not_lost` |
| 6 | blocker | A recipe changed after completion can still be stamped verified | Fixed: `recipe-stamp` requires the completed run to still be ready at the current tree. `test_6_recipe_stamp_refuses_a_tree_changed_after_completion` |
| 7 | major | Uncertain dispatches bypass cross-parent protection | Fixed: uncertain request IDs count as live work for cross-parent protection. `test_7_uncertain_dispatch_blocks_cross_parent_resume` |
| 8 | major | `--uninstall --version ../x` deletes outside the plugin root | Fixed: `--version` must name an installed version. `Round3InstallerTest.test_8_uninstall_version_cannot_traverse` |
| 9 | major | Dirty submodule contents and staged-only differences do not change the snapshot | Fixed: submodules contribute their own recursive snapshot; dirty paths also hash their staged index entries. `test_9_dirty_submodule_content_invalidates` |
| 10 | major | Uninstall deletes unowned `__pycache__` files | Fixed: uninstall removes only bytecode of owned modules. `Round3InstallerTest.test_10_uninstall_keeps_unowned_bytecode` |
| 11 | major | `recipe-scaffold` follows a symlinked `.agents` out of the repository | Fixed: `recipe-scaffold` refuses symlinked destination components. `test_11_scaffold_refuses_symlinked_destination` |
| 12 | major | Reviewer exclusion uses configured role candidates, not the provider that actually wrote the change | Fixed: the catalog step also excludes the providers that actually wrote changes for the excluded roles (the parent for self tasks, each dispatched target for delegated ones). `test_12_reviewer_excludes_the_provider_that_actually_wrote` |
| 13 | major | Retry after "no review target" clears capabilities but never offers discovery, so it re-blocks | Fixed: `executing` and review selection rediscover capabilities whenever they were cleared. `test_13_retry_after_no_review_target_rediscovers` |
