# Tests

Run `python3 scripts/run_tests.py`, or `python3 -m unittest discover -s tests -v`.
Use discover form for a focused module so `tests/` is on `sys.path`.
Tests use temporary Git repositories, isolated installation prefixes and loopback
HTTP fixtures. They never call live models or mutate GitHub.

## Current evidence gate

The major-version-2 gate retains the evidence guarantees of the earlier workflow.
The stage-3 migration removes dispatcher, lease, automatic cleanup and result-parser
APIs. [Migration rationale](../docs/imps-gate-migration.md) maps their tests to retained
behaviour or to the intentionally removed API.

| Boundary | Test IDs |
| --- | --- |
| Atomic process storage and old-state refusal | `test_ownership.StorageTest.test_concurrent_writers_keep_every_update`, `test_ownership.StorageTest.test_old_major_is_refused_by_every_state_command_without_writes` |
| Missing requirements/checks/review | `test_readiness.CompletionGateTest.test_missing_requirement_check_or_review_blocks_completion` |
| Dirty, untracked, semantic and artifact invalidation | `test_readiness.InvalidationTest.test_same_dirty_file_edited_again_invalidates`, `test_readiness.InvalidationTest.test_state_dir_inside_repo_and_checkbox_edits_do_not_invalidate`, `test_readiness.InvalidationTest.test_policy_change_invalidates`, `test_readiness.InvalidationTest.test_artifact_change_invalidates` |
| Staged bytes, modes, symlinks and submodules | `test_snapshot.SnapshotTest.test_staged_bytes_change_invalidates_with_same_working_bytes`, `test_snapshot.SnapshotTest.test_executable_bit_change_invalidates_even_with_same_porcelain`, `test_snapshot.SnapshotTest.test_dirty_submodule_content_invalidates_with_same_porcelain`, `test_snapshot.SnapshotTest.test_tracked_symlink_into_exclusion_and_symlink_loop_are_hashed` |
| Pre-check binding and exact command receipt | `test_core_audit_followups.EvidenceBindingTest.test_precheck_binding_required_and_edit_before_submission_rejected`, `test_core_audit_followups.EvidenceBindingTest.test_check_receipts_require_planned_argv_cwd_and_integer_exit` |
| Admissible evidence and readiness authority | `test_results.SubmissionTest.test_unknown_requirement_missing_artifact_and_unsupported_kind_rejected`, `test_results.SubmissionTest.test_submissions_cannot_change_authorization_constraints_or_readiness` |
| Child descendants and confirmed stops | `test_tasks.ChildTest.test_terminal_parent_with_pending_descendants_is_not_ready`, `test_tasks.ChildTest.test_confirmed_stop_required_before_cancel` |
| Review revision and adverse findings | `test_review.ReviewTest.test_review_sent_before_edit_is_rejected_and_never_relabelled`, `test_review.ReviewTest.test_approve_with_major_findings_is_adverse_and_final_for_revision` |
| Remote outcomes | `test_remote.RemoteTest.test_receipt_needs_independent_observation_at_verified_head` |
| Evidence containment and recipe behaviour | `test_paths.PathSafetyTest.test_traversal_is_rejected`, `test_verification_init.VerificationInitTest.test_generated_recipe_drives_fixture_and_evidence_survives_cleanup` |
| Installed artifact and operations | `test_review_round5.LauncherTest.test_launcher_runs_the_core_installed_and_from_source`, `test_contract.MappingTest.test_operations_and_removed_instruction_api` |

`test_contract.MappingTest` checks that every mapped method loads without errors.
Helper, installer, routing, publication, conformance-history and site tests remain
separate from the gate. Unit tests do not prove live provider compatibility.
