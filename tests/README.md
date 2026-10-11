# Tests

Run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

To run one module, keep the discover form so `tests/` is on `sys.path` (most modules import `support` from there):

```bash
python3 -m unittest discover -s tests -p test_install.py
```

Running by dotted name (`python3 -m unittest tests.test_install`) fails with `ModuleNotFoundError: support`.

Stdlib only. No network, credentials or model calls: T3 orchestration responses are scripted by `support.FakeT3`, whose response shapes come from live calls recorded in `conformance/live-t3/`. The imps suites drive `core/` code or the core CLI against temporary git repositories built from `tests/fixtures/`; the other plugins' suites exercise their helper scripts directly.

## Source-spec §14 cases

| Case | Behaviour | Test IDs |
| --- | --- | --- |
| 1 | Invalid schemas, unsupported versions and malformed task results are rejected without corrupting state | `test_schemas.VersionAndCorruptionTest.test_newer_schema_version_rejected_and_left_byte_identical`, `test_schemas.VersionAndCorruptionTest.test_invalid_plan_rejected_without_creating_state`, `test_schemas.VersionAndCorruptionTest.test_record_that_would_corrupt_state_is_rejected`, `test_schemas.VersionAndCorruptionTest.test_malformed_task_result_rejected_without_corrupting_state`, `test_schemas.SchemaParityTest.test_fixture_directories_match_validator_verdicts` |
| 2 | Concurrent claims and stale generations cannot write; unknown fields survive | `test_ownership.OwnershipTest.test_concurrent_claims_have_exactly_one_winner`, `test_ownership.OwnershipTest.test_concurrent_writers_with_same_generation_only_one_lands`, `test_ownership.OwnershipTest.test_stale_generation_rejected_and_state_bytes_unchanged`, `test_ownership.OwnershipTest.test_mutation_without_any_claim_is_rejected_when_no_owner_file_exists`, `test_ownership.OwnershipTest.test_unknown_fields_survive_updates` |
| 3 | A crashed invocation needs explicit confirmed-dead recovery | `test_ownership.OwnershipTest.test_recover_requires_confirmed_dead_even_after_deadline` |
| 4 | Completion fails when a requirement, required check or required review is missing | `test_readiness.CompletionGateTest.test_missing_requirement_check_or_review_blocks_completion`, `test_readiness.CompletionGateTest.test_failed_requirement_is_failed_not_unverified`, `test_readiness.CompletionGateTest.test_wrong_evidence_kind_and_missing_artifacts_rejected` |
| 5 | HEAD, dirty content, contract, policy and artifact changes invalidate readiness; checkbox edits do not | `test_readiness.InvalidationTest.test_head_change_invalidates`, `test_readiness.InvalidationTest.test_same_dirty_file_edited_again_invalidates`, `test_readiness.InvalidationTest.test_new_untracked_file_invalidates`, `test_readiness.InvalidationTest.test_state_dir_inside_repo_and_checkbox_edits_do_not_invalidate`, `test_readiness.InvalidationTest.test_policy_change_invalidates`, `test_readiness.InvalidationTest.test_artifact_change_invalidates` |
| 6 | An adverse review is retained and never triggers fallback; unavailable review follows the configured policy | `test_review.ReviewTest.test_adverse_verdict_is_retained_and_never_triggers_fallback`, `test_review.ReviewTest.test_unavailable_reviewer_walks_the_default_chain`, `test_review.ReviewTest.test_repository_policy_reviewer_overrides_default_chain` |
| 7 | Repair invalidates acceptance and review, obeys persisted limits; resume does not reset budgets | `test_review.ReviewTest.test_repair_invalidates_review_and_counters_survive_resume`, `test_ownership.OwnershipTest.test_budget_persists_across_resume` |
| 8 | A wait timeout keeps the task ID with no duplicate dispatch; rounds get distinct request IDs | `test_tasks.DelegatedTaskTest.test_wait_timeout_keeps_task_id_and_never_redispatches`, `test_tasks.DelegatedTaskTest.test_retry_reuses_client_request_id_until_recorded`, `test_tasks.DelegatedTaskTest.test_correction_round_gets_a_new_client_request_id` |
| 9 | Child output cannot weaken constraints, change authorised actions or claim completion without artifacts | `test_results.ResultFlowTest.test_result_cannot_change_constraints_authorization_or_completion`, `test_results.ResultFlowTest.test_completion_claim_without_artifacts_is_rejected`, `test_results.ResultFlowTest.test_claimed_files_or_commit_that_do_not_exist_are_rejected`, `test_results.ResultFlowTest.test_result_cannot_reword_requirements` |
| 10 | Missing capabilities and authentication are explicit; cross-parent resume does not misuse task IDs | `test_tasks.CapabilityTest.test_missing_capability_blocks_delegated_mode_explicitly`, `test_tasks.CapabilityTest.test_tools_not_callable_and_provider_reasons_are_separate`, `test_tasks.CapabilityTest.test_named_target_is_never_rewritten`, `test_tasks.DelegatedTaskTest.test_cross_parent_resume_refuses_old_task_ids` |
| 11 | Cancellation separates confirmed stop from uncertainty and never kills unrelated processes | `test_tasks.CancellationTest.test_cancelled_only_after_confirmed_stop`, `test_tasks.CancellationTest.test_unconfirmed_stop_stays_blocked_with_exact_task_ids`, `test_tasks.CancellationTest.test_cleanup_never_signals_an_unrelated_process` |
| 12 | Publish receipts are reconciled before retry; a local pass cannot satisfy a remote outcome | `test_remote.RemoteTest.test_receipt_is_reconciled_before_retry`, `test_remote.RemoteTest.test_local_pass_cannot_complete_a_pr_endstate`, `test_remote.RemoteTest.test_observation_at_a_different_head_does_not_complete` |
| 13 | Traversal and symlink escapes and install ownership conflicts are rejected; uninstall preserves evidence | `test_paths.PathSafetyTest.test_traversal_is_rejected`, `test_paths.PathSafetyTest.test_symlink_escape_is_rejected`, `test_paths.PathSafetyTest.test_tampered_stored_artifact_path_is_not_trusted`, `test_install.InstallTest.test_install_lifecycle` |
| 14 | A direct bug fix reproduces red, fixes, passes the original check and reports | `test_bugfix_direct.DirectBugFixTest.test_direct_bugfix_red_fix_green_report` |
| 15 | A delegated fix exercises dispatch, result validation, integration, verification and review repair | `test_bugfix_delegated.DelegatedBugFixTest.test_parallel_delegated_fix_with_review_repair`, `test_bugfix_delegated.DelegatedBugFixTest.test_serial_mode_when_probe_fails` |
| 16 | A generated verification recipe drives a fixture product; cleanup keeps the evidence | `test_verification_init.VerificationInitTest.test_generated_recipe_drives_fixture_and_evidence_survives_cleanup`, `test_verification_init.VerificationInitTest.test_placeholder_or_unproven_recipe_is_never_verified` |

`test_contract.MappingTest` fails if any ID above stops resolving to a test.

## Rubric criteria with their own tests

| Criterion | Test IDs |
| --- | --- |
| REQ-CLI | `test_contract.CliContractTest.test_every_op_returns_one_envelope_and_each_exit_code_occurs`, `test_contract.CliContractTest.test_usage_errors_are_json_too` |
| REQ-OWNERSHIP | `test_ownership.OwnershipTest.test_mutation_without_any_claim_is_rejected_when_no_owner_file_exists` (the `workflow-evidence.py:212` regression) |
| REQ-SNAPSHOT | `test_readiness.InvalidationTest.test_same_dirty_file_edited_again_invalidates`, `test_readiness.InvalidationTest.test_state_dir_inside_repo_and_checkbox_edits_do_not_invalidate` |
| REQ-SCHEMAS | `test_schemas.SchemaParityTest` |
| REQ-PURITY | `test_contract.PurityTest` |
| REQ-ENTRY | `test_contract.EntryTest` |
| REQ-T3-SURFACE | `test_contract.SurfaceTest` |
| REQ-TASKS | `test_tasks.DelegatedTaskTest`, `test_tasks.CancellationTest` |
| REQ-RESULT | `test_results.ExtractTest`, `test_results.ResultFlowTest` |
| REQ-ISOLATION | `test_bugfix_delegated.DelegatedBugFixTest` (parallel and serial) |
| REQ-REVIEW | `test_review.ReviewTest` |
| REQ-BLOCKED | `test_blocked.BlockedPathsTest.test_every_blocker_code_is_actionable`, `test_blocked.BlockedPathsTest.test_resume_command_runs_as_printed` |
| REQ-CLEANUP | `test_cleanup.CleanupTest` |
| REQ-ACCEPTANCE | `test_readiness.LabelTest`, cases 4, 5 and 12 above |
| REQ-INSTALL | `test_install.InstallTest` |
| REQ-NO-PATHS | `test_contract.NoMachinePathsTest` |
| Round-1 adversarial review findings | `test_review_regressions` (one test per finding; see `conformance/review/round-1.md`) |
