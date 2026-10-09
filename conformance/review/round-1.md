# Pre-PR adversarial review, round 1

- Reviewer: Codex (`codex` / `gpt-6.1-sol`, reasoning high), dispatched with `delegate_task`, role `review`
- T3 task: `node:delegated-task:command%3Amcp%3Ae8eb6bcd-a2f7-437b-9d1e-575bca98bf84%3Adelegate-task%3Aimps-t3-build%253Acodex-review%253Ar1`
- clientRequestId: `imps-t3-build:codex-review:r1`
- Reviewed commit: `b7350d0e11378847679336dfb82178d38535aa8f` (diff from `ccf025c`)
- Verdict: **adverse** (6 blocker, 9 major)

| # | Severity | Location | Finding | Resolution |
| --- | --- | --- | --- | --- |
| 1 | blocker | core/records.py | Review approval bound to the revision at collection, not the reviewed revision | Fixed: the review binding is captured at dispatch (`records.rec_dispatch`), so a later tree change makes the verdict stale. `test_review_regressions.CoreFindingsTest.test_1_review_is_bound_to_the_revision_it_was_asked_to_read` |
| 2 | blocker | core/records.py | Check receipts rebound to the current tree; cwd not checked | Fixed: `check` and `acceptance` must echo the action's snapshot token and are refused if the tree changed; cwd must equal the planned cwd. `test_2_check_receipts_must_name_the_checked_snapshot_and_cwd` |
| 3 | blocker | core/acceptance.py | PR completion compares HEAD only, ignoring verified dirty changes | Fixed: PR and merge endstates get a `commit` action before evidence, and `remote_confirmed` refuses a dirty tree. `test_3_pr_endstate_requires_committed_changes` |
| 4 | blocker | core/snapshot.py | Snapshot hash omits executable mode | Fixed: snapshot hashes file type and executable bits. `test_4_executable_bit_change_invalidates` |
| 5 | blocker | core/records.py | Uncertain dispatch error treated as terminal; retry dispatches a new request ID | Fixed: timeouts and transport errors are `uncertain`; the same clientRequestId is retried, never a new one, and after three attempts the task blocks with a retry that still reuses it. `test_5_uncertain_dispatch_errors_retry_the_same_request` |
| 6 | blocker | core/report.py | Report keeps `completed` after readiness goes stale | Fixed: a completed run whose readiness no longer holds reports outcome `stale` with the completion binding. `test_6_report_of_a_completed_run_goes_stale_when_the_tree_changes` |
| 7 | major | core/records.py | Writer baselines captured after dispatch and reset on correction | Fixed: the writer baseline is fixed at worktree creation or in the dispatch action, and never reset by corrections. `DelegationFindingsTest.test_7_fast_child_commits_and_corrections_keep_the_baseline` |
| 8 | major | core/engine.py | Serial fallback still writes outside the inherited checkout | Fixed: serial mode runs writers one at a time in the parent checkout, with no external worktree and no integration. `test_bugfix_delegated.DelegatedBugFixTest.test_serial_mode_when_probe_fails` |
| 9 | major | core/engine.py | Dependent tasks start before prerequisites are integrated | Fixed: parallel mode integrates each accepted writer eagerly, and a dependant starts only after its writer prerequisite is integrated. `test_9_dependants_start_only_after_prerequisites_are_integrated` |
| 10 | major | core/engine.py | Cleanup offers `kill PID` before checking process identity | Fixed: `next` checks process identity before offering a command; a replaced or gone PID gets `argv: null`. `test_10_cleanup_never_offers_a_kill_for_a_replaced_pid` |
| 11 | major | core/fsutil.py | Artifact destination directories not checked for symlink escape | Fixed: `fsutil.safe_dir` refuses symlinked run-directory components. `test_11_artifact_destination_symlink_is_refused` |
| 12 | major | scripts/install.py | Uninstall trusts manifest paths without containment | Fixed: `owned_path` refuses absolute, `..` and symlink-crossing manifest paths on install and uninstall. `InstallerFindingsTest.test_12_manifest_paths_cannot_escape_the_version_directory` |
| 13 | major | scripts/install.py | Uninstall drops ownership metadata for preserved modified files | Fixed: uninstall keeps a manifest for preserved modified files, so reinstall still refuses to overwrite them. `test_13_modified_files_stay_owned_after_uninstall` |
| 14 | major | core/cli.py | Retry resume leaves unavailable evidence and failed remote observations in place | Fixed: `retry` invalidates unavailable evidence and supersedes failed remote observations; blocker IDs are stable across claim and release. `test_blocked.BlockedPathsTest.test_every_resume_command_unblocks` runs every printed resume command. |
| 15 | major | core/cli.py | Invalid record input can raise past the JSON envelope | Fixed: `pid` is validated, and the CLI wraps any remaining exception in the JSON envelope (exit 2 for bad input, 5 otherwise). `test_15_bad_record_input_still_returns_an_envelope` |
