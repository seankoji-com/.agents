# imps evidence gate migration

Stage 3 of issue #15 replaces executable workflow scheduling with a small evidence gate.
The agent owns implementation, integration, routing, retries and process cleanup. T3 owns
child execution and watches. The core admits revision-bound evidence and validates it.
This removes a second scheduler without removing the requested evidence guarantees.
The later whole-job rebuild keeps this gate as each imps stage's authority; see
[whole-job coordination](migration.md#whole-job-coordination).

## Operations

| Operation | Decision | Finish line |
| --- | --- | --- |
| doctor | Keep operation; change evidence procedure | Prerequisites and live capability report |
| run | Keep operation; change evidence procedure | Current evidence and observed authorised outcome |
| resume | Keep operation; change evidence procedure | Reconcile children and finish missing evidence |
| status | Keep operation; change evidence procedure | Read current state and report |
| cancel | Keep operation; change evidence procedure | Confirm owned stops, then mark cancelled |
| verification-init | Keep operation; change evidence procedure | Scaffold, exercise and stamp a product recipe |
| blast-radius | Keep operation; change evidence procedure | Cited affected paths and failure paths |
| audit | Keep operation; change evidence procedure | Findings with verification evidence |
| issues | Keep operation; change evidence procedure | Combined issue criteria and evidence |
| prs | Keep operation; change evidence procedure | Use installed babysitter and host watches |
| checklist | Keep operation; change evidence procedure | Verify source claims within authorisation |
| discussion | Keep operation; change evidence procedure | Retain source and seed a bounded run |

## CLI commands and observation types

| Previous API | Decision | Current API or owner |
| --- | --- | --- |
| init, status, validate, report | Change | Major-version-2 contract and validation |
| claim, release, recover | Remove | Process lock serializes whole transactions; no agent lease |
| next | Remove | Agent plans work; core emits no permitted actions |
| record | Change | Named, schema-checked submissions |
| unblock | Remove | Agent reconciles missing evidence; no scheduler phase blockers |
| recipe-scaffold, recipe-check, recipe-stamp | Keep | Current validation required before stamping |
| capabilities record | Remove | Agent discovers T3 and saves the raw response in notes |
| transition, fail, block records | Remove | validate derives outcome; cancel requires terminal children |
| dispatch, observation, cancel records | Change | child observations retain task/request/parent identity and pending descendants |
| result record | Remove | Parent validates child artifacts; evidence submissions never accept a completion claim |
| check, acceptance records | Change | check and evidence submissions carry a pre-verification binding |
| waiver record | Change | waive retains owner quote and distinct label |
| repair record | Remove | Agent repairs within a stated limit and verifies the new revision |
| resource, cleanup, integration records | Remove | Agent performs isolated integration and confirmed task-owned cleanup |
| remote-receipt, remote-observation records | Change | remote receipt and independent observation at verified head |
| note, policy records | Change | note and policy submissions; existing obligations cannot weaken |
| snapshot, review, child | Add | Capture full binding; submit review and child evidence directly |

## Persisted files

| File | Decision | Reason |
| --- | --- | --- |
| run.json | Change | Major 2, no lease/counter/dispatcher tasks; stores contract and evidence |
| owner.json | Remove | No agent lease or recovery protocol |
| run.lock | Keep | Stable inode and flock across complete read-modify-write transactions |
| artifacts/ | Keep | Copied content-addressed evidence and hashes survive source cleanup |
| scratch/ | Keep | Verification logs, raw host responses and working notes |
| notes/ | Add | Saved issue/discussion/checklist sources |
| reports/report.json, reports/report.md | Change | Same current validation as validate; no stale completion claim |
| task worktrees and branches | Remove from core | Agent creates and reconciles isolated writers through shared delegation rules |
| recipe.json, SKILL.md, features/, evidence/ | Keep | Recipe format and product-verification guarantees survive |

## Core module lines

| Module | Before | After | Change |
| --- | ---: | ---: | ---: |
| core/__init__.py | 0 | 0 | +0 |
| core/acceptance.py | 195 | 201 | +6 |
| core/blockers.py | 79 | 0 | -79 |
| core/cli.py | 404 | 145 | -259 |
| core/contract.py | 96 | 96 | +0 |
| core/engine.py | 706 | 0 | -706 |
| core/errors.py | 37 | 37 | +0 |
| core/fsutil.py | 174 | 176 | +2 |
| core/planning.py | 184 | 68 | -116 |
| core/recipe.py | 195 | 195 | +0 |
| core/records.py | 959 | 174 | -785 |
| core/report.py | 140 | 41 | -99 |
| core/resources.py | 87 | 0 | -87 |
| core/results.py | 164 | 0 | -164 |
| core/review.py | 17 | 17 | +0 |
| core/schema.py | 139 | 139 | +0 |
| core/selection.py | 146 | 0 | -146 |
| core/snapshot.py | 176 | 176 | +0 |
| core/store.py | 200 | 98 | -102 |
| core/t3.py | 168 | 0 | -168 |
| core/transitions.py | 57 | 0 | -57 |
| Total | 4323 | 1563 | -2760 |

The count uses normally formatted Python, including blank lines and docstrings.
No dispatcher is relocated. Routing remains in scripts/routing.py from stage 2.
Task/result schemas and dispatcher fields are removed; surviving schemas keep normal formatting.

## Test migration

The [method-level appendix](imps-gate-test-map.md) lists every changed or removed test method.

Assertions about snapshots, semantic invalidation, command receipts, evidence containment,
readiness, process-safe storage and child liveness remain executable. Installer and recipe
assertions in mixed review modules are retained. New tests exercise the named submission API.
Tests whose entire subject was the removed dispatcher, lease, correction parser, automatic
integration, budget allocator or automatic resource cleanup are retired deliberately.
Routing availability and runtime-mode behaviour remain covered by test_routing.py; the gate
does not select providers or build delegate_task calls.

| Changed or removed test file | Reason and retained evidence |
| --- | --- |
| tests/support.py | Replace FakeT3 dispatcher driver with public named-submission helpers; keep isolated repository, argv and process utilities. |
| tests/test_blocked.py | Remove phase/blocker/resume action builders, budget/repair allocation and permitted-action dispatch APIs. |
| tests/test_bugfix_delegated.py | Remove automatic writer probe, fan-out, integration and repair scheduler. Shared delegation owns isolated writers and integration order. |
| tests/test_bugfix_direct.py | Retain red reproduction, regression check, green reproduction and validated report; independent review has focused submission tests. |
| tests/test_cleanup.py | Retain copied evidence survival; remove core-owned worktree/process cleanup and integration scheduling. |
| tests/test_contract.py | Keep CLI envelopes/exits, stdlib/purity, host surfaces, paths, installed entry references and test-map resolution. Tighten entry to 800 words and add all-12-operation and removed-instruction lints. |
| tests/test_core_audit_followups.py | Retain pre-check full binding, attested snapshot, exact argv/cwd, exit truthfulness and schema items checks. Removed result-file/parser and dispatcher role/correction APIs. |
| tests/test_core_hardening.py | Keep artifact stem/path and porcelain rename assertions unchanged. Task-ID path schema belonged to the removed result/dispatcher file naming API. |
| tests/test_instruction_hygiene.py | Keep all file and Python-generated adapter/handoff lint coverage. Dispatcher-generated briefs are removed; review finish-line text is now checked in the entry. |
| tests/test_ownership.py | Replace lease/counter/recovery assertions with 12 concurrent whole transactions, rejection atomicity, removed-API refusal and old-major refusal without writes. Scheduler time budgets are removed. |
| tests/test_paths.py | Retain every traversal, symlink and stored-artifact containment assertion; remove scheduler setup. |
| tests/test_readiness.py | Retain all readiness, semantic/artifact invalidation and label assertions; replace transition requests with current validate. |
| tests/test_remote.py | Adapt fixture/helper to major-version-2 API. |
| tests/test_resources_identity.py | Remove core automatic worktree deletion and identity capture API. Core now performs no resource cleanup or Git mutation. |
| tests/test_results.py | Retire fenced correction/result parser; retain prohibition on authorization/contract/readiness injection and false completion without artifacts through strict submissions. |
| tests/test_review.py | Retain revision/policy binding, adverse finality and repair invalidation; routing/fallback selection is outside core and tested by test_routing.py. |
| tests/test_review_followups.py | Retain real waiver target, unique check names, policy obligations, stale copy replacement and recipe evidence-name collision assertions. Removed writer-probe scheduling. |
| tests/test_review_perspectives.py | Retain every required perspective, retained handles, adverse panels, stale revision and immutable obligations; remove panel scheduling. |
| tests/test_review_regressions.py | Keep installer findings and assertions unchanged; move snapshot, evidence, pending-child and review boundaries to focused suites. Retire dispatcher correction, dependency integration, uncertain dispatch/cancel scheduling and PID cleanup APIs. |
| tests/test_review_round5.py | Keep installed/source launcher, missing-core diagnosis, installer preservation and recipe containment assertions unchanged. Focused suites retain evidence/remote/policy/waiver/snapshot guarantees; remove writer scheduling and automatic cleanup. |
| tests/test_review_round5_peripheral.py | Keep artifact, recipe, conformance-history and installer assertions unchanged. Remove scheduler budget blocker and old task-state shape tests; current schemas cover surviving evidence/child shape. |
| tests/test_runtime_mode.py | Retain config schema and mode persistence; selector/call builders removed. Public routing resolution tests retain owner modes and escalation reporting. |
| tests/test_schemas.py | Keep validator parity, invalid plan, corruption rejection, version refusal, evidence schema parity and runtime purity. Retire result/task/dispatcher fixtures; change run and plan fixtures to major 2. |
| tests/test_tasks.py | Retain pending descendants, persistent task identity, cross-parent refusal and confirmed cancellation. Dispatch/retry/correction scheduling belongs to the agent and T3. |
| tests/test_verification_init.py | Keep actual HTTP recipe steps, response assertions, placeholders, cleanup stop confirmation and copied evidence; cleanup is native and stamping uses current validate. |
| tests/fixtures/schemas/ | Retire dispatcher/result/budget/repair-only shapes; preserve surviving plan, evidence, role, recipe, installer and invalid-input checks. |
| tests/test_snapshot.py (new) | Preserve prior mode, dirty-submodule and excluded-symlink regressions; add staged-byte and symlink-target coverage. |
| tests/test_gate_boundaries.py (new) | Constraint invalidation, failed-check labels, optional-check staleness, current reports, artifact destination symlinks, policy-bound review and newer evidence after waivers. |

## Compatibility and paths

Old major-version-1 state is refused before writing any state or lock. To inspect, resume
or cancel it, use the previous installed package through agents activate, as explained
in the [imps guide](plugins/imps.md#previous-runs). No conversion is attempted.
Historical conformance observations and their old-format collector remain dated evidence;
they do not establish compatibility for the new gate. The frozen benchmark stays unchanged.
The stage run uses one private results directory for logs, isolated HOME/XDG directories,
a docs venv/build, and a scratch installation. Their concrete paths are in the PR run notes,
not public fixtures. No default-prefix install or owner configuration was changed.
