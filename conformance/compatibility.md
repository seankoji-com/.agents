# Provider compatibility

Generated from `compatibility.json`. T3 server `0.0.46-nightly.20261008.2849`; plugin `0.1.0+ga50f506cd178`. A provider is `verified` only when every critical case passed 3/3 repeats with no intervention and no false completion; 1-2 of 3, or a case that could not run, is `partial`.

| Provider | Model | Status | Cases (passes/repeats) | Child-write probe | Interventions | Usage/cost |
| --- | --- | --- | --- | --- | --- | --- |
| codex | gpt-6.1-sol | `partial` | bugfix 3/3, missing-capability 3/3 | writes outside parent checkout | 0 | null |
| claudeAgent | claude-sonnet-5-5 | `partial` | bugfix 3/3, missing-capability 3/3, adverse-review 0/1, pending-task 2/3, provider-switch 1/1 | writes outside parent checkout | 1 | null |
| antigravity | gemini-3.8-flash-high | `partial` | bugfix 1/3, missing-capability 3/3, pending-task 0/1 | writes outside parent checkout | 0 | null |
| opencode | opencode/big-pickle | `partial` | none | writes outside parent checkout | 0 | null |
| grok | n/a | `unavailable` | none | not run | 0 | null |
| cursor | n/a | `unavailable` | none | not run | 0 | null |
| muse | n/a | `unavailable` | none | not run | 0 | null |
| pi | n/a | `unavailable` | none | not run | 0 | null |

## codex

bugfix 3/3 and missing-capability 3/3 with no intervention and no false completion. adverse-review and pending-task could not run: from about 13:45Z every Codex session in T3 failed to start ('Codex App Server process exited with code 0'), including review children and health probes; the T3 Codex driver path stayed down for the rest of the matrix. Not rerun to a pass: the gap is recorded.

- bugfix #1: pass; outcome `completed`; elapsed 169.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/codex/bugfix/1`
- bugfix #2: pass; outcome `completed`; elapsed 151.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/codex/bugfix/2`. reviewer child briefly modified and restored a file; parent re-verified the restored tree
- bugfix #3: pass; outcome `completed`; elapsed 151.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/codex/bugfix/3`
- missing-capability #1: pass; outcome `blocked`, block `provider_unavailable`; elapsed 106.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/codex/missing-capability/1`
- missing-capability #2: pass; outcome `blocked`, block `provider_unavailable`; elapsed 104.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/codex/missing-capability/2`
- missing-capability #3: pass; outcome `blocked`, block `provider_unavailable`; elapsed 107.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/codex/missing-capability/3`

## claudeAgent

bugfix 3/3, missing-capability 3/3, pending-task 2/3 (repeat 2 failed on a relative evidence path, a brief defect since fixed), adverse-review 0/1 (the Codex reviewer crashed; one operator message 'try it again' arrived from the T3 web UI). The Claude provider's sandbox makes ~/.local/state read-only, so every run used the documented --state-root fallback under $TMPDIR. Also: the build thread itself (claude-opus-5-5) acted as parent for the live delegate/cancel probe, the child-write probe run and every pre-PR review dispatch; see conformance/live-t3 and conformance/probes.

- bugfix #1: pass; outcome `completed`; elapsed 161.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/bugfix/1`. parent sandbox made ~/.local/state read-only; agent used the documented --state-root fallback /tmp/claude-1000/b1/state
- bugfix #2: pass; outcome `completed`; elapsed 106.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/bugfix/2`. state root fallback /tmp/claude-1000/b2/state
- bugfix #3: pass; outcome `completed`; elapsed 108.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/bugfix/3`. state root fallback /tmp/claude-1000/b3/state
- missing-capability #1: pass; outcome `blocked`, block `provider_unavailable`; elapsed 51.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/missing-capability/1`. state root fallback /tmp/claude-1000/m1/state
- missing-capability #2: pass; outcome `blocked`, block `provider_unavailable`; elapsed 34.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/missing-capability/2`. state root fallback /tmp/claude-1000/m2/state
- missing-capability #3: pass; outcome `blocked`, block `provider_unavailable`; elapsed 32.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/missing-capability/3`. state root fallback /tmp/claude-1000/m3/state
- adverse-review #1: FAIL; outcome `blocked`, block `task_failed`; elapsed 124.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/adverse-review/1`. FAIL (infrastructure): codex review child crashed twice ('Codex App Server process exited with code 0'); operator typed 'try it again'. No false completion.
- pending-task #1: pass; outcome `completed`; elapsed 104.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/pending-task/1`. state root /tmp/claude-1000/p1/state; child skipped sleep 90 (its harness blocks foreground sleep); one correction round r2 for a malformed first result
- pending-task #2: FAIL; outcome `blocked`, block `result_rejected`; elapsed 150.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/pending-task/2`. FAIL: reconciliation correct, but child cited a relative evidence path (result_rejected). state root /tmp/claude-1000/p2/state
- pending-task #3: pass; outcome `completed`; elapsed 188.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/pending-task/3`. state root /tmp/claude-1000/p3/state; waiting_for_children observed live and handled; collect_result via t3_thread_read
- provider-switch #1: pass; outcome `completed`; elapsed 362.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/claudeAgent/provider-switch/1`. REQ-LIVE-T3 provider switch within one thread: supported

## antigravity

missing-capability 3/3. bugfix 1/3: repeats 2 and 3 blocked when the Codex reviewer listed the files it reviewed as changed_files (result_rejected); the parent reported the block both times without claiming completion. pending-task 1: correct reconciliation on resume (no second dispatch), but the survey child never returned within 30 minutes, so the run did not finish. adverse-review not run (Codex reviewer down).

- bugfix #1: pass; outcome `completed`; elapsed 929.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/bugfix/1`
- bugfix #2: FAIL; outcome `blocked`, block `result_rejected`; elapsed 353.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/bugfix/2`. FAIL: codex review child listed reviewed files as changed_files; core rejected it (result_rejected) and the run blocked. No false completion.
- bugfix #3: FAIL; outcome `blocked`, block `result_rejected`; elapsed 268.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/bugfix/3`. FAIL: codex review child listed reviewed files as changed_files (result_rejected). No false completion.
- missing-capability #1: pass; outcome `blocked`, block `provider_unavailable`; elapsed 288.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/missing-capability/1`
- missing-capability #2: pass; outcome `blocked`, block `provider_unavailable`; elapsed 227.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/missing-capability/2`
- missing-capability #3: pass; outcome `blocked`, block `provider_unavailable`; elapsed 230.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/missing-capability/3`
- pending-task #1: FAIL; outcome `in_progress`; elapsed 3300.0s; artifacts `conformance/results/0.0.46-nightly.20261008.2849/antigravity/pending-task/1`. FAIL (incomplete): reconciliation correct, but the antigravity survey child never returned within 55 minutes

## opencode

Partial (procedure.md section 5: a case could not run): the provider can run, but T3 never opened its parent session, an infrastructure gap rather than a catalog refusal. As a parent: three attempts, none started. T3 reported 'Failed to open opencode provider session provider-session:provider-instance:opencode:shared' after 25 minutes in 'starting'. As a child it works: the live child-write probe ran on opencode/big-pickle and passed. Catalog lists it as able to run child tasks. plugin_version and starting_revision are empty because no conformance case run started; the probe result carries its own provenance in child_write_probe.source.

## grok

Catalog: 'Grok CLI is installed but not logged in. Run `grok login`.' / 'Provider is not authenticated.' Not logged in or enabled by this build, by design.

## cursor

Catalog: provider instance disabled, executable not installed, disabled in T3 Code settings.

## muse

Catalog: provider instance disabled, executable not installed, disabled in T3 Code settings.

## pi

Catalog: provider instance disabled, executable not installed, disabled in T3 Code settings.

## Where this was run

T3 Code server 0.0.46-nightly.20261008.2849 (CLI 0.0.46-nightly.20261007.2787) on Linux (desktop build), not the macOS nightly named in the design brief. Every conformance thread used runtime mode full-access, inherited from the build thread. One top-level thread per provider, as authorised; each case and repeat was a separate message with a fresh clone of the fixture branch. Driver messages are verbatim in each transcript.md.

## Child-write probe (REQ-ISOLATION)

A live delegated imps run from the build thread (parent claudeAgent/claude-opus-5-5) pinned one writer to each child-capable provider. The core created sibling worktrees under ~/.local/state/t3-plugins/imps/worktrees, dispatched each probe with delegate_task, and read each marker itself: codex, claudeAgent, opencode and antigravity children could all write outside the parent checkout (with full-access runtime). Evidence: conformance/probes/0.0.46-nightly.20261008.2849/. The Antigravity child noted that its tool refuses a working directory outside the workspace roots, although writes there succeed.

## Live delegation and cancellation (REQ-LIVE-T3)

conformance/live-t3/cancel-probe.json: a wait-mode delegate_task returned a fenced t3-result block; an async child running `sleep 600` was cancelled with task_cancel, which answered cancel_requested; task_status then showed interrupted / result_available / no pending child runs, which the adapter treats as the confirmed stop. In the matrix, Claude children twice reported waiting_for_children and the parents treated it as not a result.

## Parent provider switch within one thread (REQ-LIVE-T3)

In the Claude conformance thread, run 20261009-142158-6ce8d6 dispatched a survey child under claudeAgent; the thread was then switched to antigravity/gemini-3.8-flash-high with t3_thread_configure and asked to resume. The core recorded `provider_switch: parent provider claudeAgent -> antigravity` and accepted the new provider's capabilities under the same parent thread ID; see conformance/results/.../claudeAgent/provider-switch/.

## Defects the matrix found (fixed after the matrix, at the PR head)

1. Review and read-only briefs showed a changed_files example, and a Codex reviewer listed the files it reviewed there; the core rejected the claim and blocked two Antigravity bug-fix repeats. Read-only briefs now show `"changed_files": []` and a stray list gets one correction round. 2. A child cited evidence relative to its own working directory (children inherit the thread's scratch folder, not the clone); briefs now require absolute evidence paths and a relative path that does not resolve gets one correction round. Both have regression tests in tests/test_review_regressions.py::MatrixFindingsTest.

## Grader change

The pending-task grader first required exactly one dispatched round. Claude repeat 1 legitimately had a second round: the core's one correction round after a malformed first result, with its own clientRequestId. The check now requires exactly one *initial* dispatch and a distinct clientRequestId per round, which is the property the case tests (no duplicate dispatch after interruption).

## Interventions and infrastructure

Interventions counted: one (an operator message 'try it again' in the Claude thread at 13:46:51Z). An earlier operator message ('what next', 13:11:10Z) arrived after a repeat had completed and did not affect it. Infrastructure retries, not counted as model behaviour: the OpenCode thread (three attempts, session never opened) and one Codex parent turn that failed to start.

## Observed but not adopted

This T3 build injects agent instructions that mention an ACP fallback transport and exposes link_pull_request, watch_pull_request and preview tools as standalone MCP tools. At plugin 0.1.0, the version this ledger records, imps was limited to the pinned orchestrator doc's surface (link_pull_request as a t3_thread_update action, no PR watcher, preview tools found by description) and did not call them. imps 0.2.0 adopted link_pull_request, watch_pull_request and unwatch_pull_request; the ledger has not been re-run since.

## Usage and cost

T3 does not expose token usage or cost to the parent at this version, so usage/cost is null for every repeat. usage.json in each repeat records the run's active-budget seconds.

## Plugin version

0.1.0+ga50f506cd178 is the installed snapshot every matrix repeat ran on. The final PR head adds the round-3 review fixes and two matrix-found fixes on top of it (see the other notes).

## Row fields

`starting_revision` lists the distinct fixture base SHAs that provider's repeats started from, in run order (each repeat used a fresh clone of the fixture branch, so a row can carry several); it is empty when no case run started. `child_write_probe.source` names the single probe run all rows share: run 20261009-121018-0f6d5d, plugin 0.1.0, base 7008f23c6ca6340cbc753c4494d7547f9618d021, evidence in conformance/probes/0.0.46-nightly.20261008.2849/.
