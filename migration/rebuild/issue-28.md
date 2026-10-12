# Rebuild t3-plugins around whole-job coordination and versioned stage agents

Source: https://github.com/seankoji-com/t3-plugins/issues/28 (state OPEN, fetched 2026-10-12)

## Objective

Reduce the main conversation's context load during large, multi-stage jobs while preserving result quality. The main agent coordinates the whole job, retains its requirements and decisions, integrates outputs and accepts work. Fresh specialized workers execute complete stages; their exploration, logs and full results stay in referenced artifacts. The operator can recover the whole plan and next blocker from one compact overview.

Rebuild the internals of all five plugins. Preserve their names and command meanings:

| Plugin | Operations |
|---|---|
| imps | doctor, run, resume, status, cancel, verification-init, blast-radius, audit, issues, prs, checklist, discussion |
| ape | doctor, forage, study, clean |
| elephant-goldfish | doctor, thinking, elephant, check |
| babysitter | doctor, pr, repo, org |
| agent-tuneup | doctor, audit, scan |

Defaults: coordinator-only dispatch; lowest suitable configured worker tier with escalation; unchanged coordinator model; uncapped plugin concurrency; initial stage attempt plus three repair cycles; finite declared stage/task plan; no fixed token or runtime ceilings. Continue accepted stages automatically within existing authorization. Report context, total usage, cache behavior, runtime and quality; numerical efficiency improvement is not a completion gate. Codex and Claude require live acceptance; OpenCode and Antigravity remain explicitly unverified.

## 1. Architecture and managed definitions

Keep three boundaries: workflow instructions guide the coordinator; Python 3.10+ standard-library helpers prepare, store and validate data; T3 owns model execution, task lifecycle, notifications and watches. No provider SDK, model client, shell agent broker, daemon, automatic dispatch loop or second scheduler. `core/` contains generic storage/evidence/schema concepts without plugin imports or vocabulary; workflow adapters own operation-specific policy and acceptance.

Entries load only the selected operation. The main agent reads the compact overview and contracts needed for its current action, rather than the entire catalog, all playbooks or worker transcripts. Keep cheap deterministic operations direct; do not launch agents for doctor/status/list. Whole-stage delegation is the default for substantive multi-stage work.

### Registry and installation

Source definitions: `plugins/<plugin>/agents/<worker>.md`; canonical shared contracts/schema: `shared/agents/`. Manifests enumerate stable worker IDs, relative definition paths, operation mappings and T3 routing roles. Definitions contain no fixed model IDs and are explicitly loaded only by plugin commands; do not register them as standalone skills/native harness agents or enable global automatic invocation.

Physically materialize managed definitions under configurable `--agents-root`, default `~/.agents/agents/t3-plugins`:

```text
<agents-root>/installations/<installation-id>/<plugin>/<package-version>/
  manifest.json
  workers/<worker>.md
  shared/<required-contract-files>
<agents-root>/overrides/<plugin>/<worker>.md
```

This is a documented plugin registry convention, not a claim about native harness discovery.

Generate one installation UUID per owned installation receipt. Distinct prefixes have distinct identities. Verified relocation preserves identity through explicit receipt/path adoption; duplicate live claims or copied receipts fail with an identity conflict. Validate pinned hashes before adoption and retain old/new locators. Encode directory components safely; never use raw prefix paths as components.

Package identity includes definition bytes and shared contracts. Distributions include these assets; runtime preparation reads only the matching external bundle and checks its digests against the pinned package manifest. A usable installation requires a complete immutable package/bundle pair. Diagnose interrupted installs and repair idempotently; activation/rollback selects the matching pair.

At job creation pin concrete absolute package version directories, package digests, bundle directories/digests and effective contents for **every dependency**, including cross-plugin dependencies such as imps `prs` using babysitter. Add `t3-plugins --job JOB path PLUGIN` to resolve recorded pins and refuse undeclared dependencies. Ordinary `path` retains its current behavior. Every job helper/entry/prepare call uses pins, never a mutable `current` pointer. Resume recovers pins before loading entries; a wrong-package caller refuses writes and prints the pinned invocation. Changing current pointers alone does not invalidate intact pinned jobs. Declared adapters may emit scoped observations without changing the invoking workflow/installation's ownership.

Retain pinned package versions/bundles while installed packages or live/resumable jobs reference them. Removing a referenced version is refused; explicit job discard/cancel must not erase artifacts. Activating an older package without bundles preserves legacy operations but refuses new-format job creation/resume through that package and supplies a compatible pinned path.

Uninstall removes only owned unchanged files for the selected installation/plugin/version. Preserve overrides, modified and extra user files; report retained/conflicted files. Reject symlinks, traversal, corrupt receipts and escaping roots; never delete another prefix/plugin's files. Add agent-root support to relevant install/setup/doctor/activation/removal paths and record it in receipts. Preserve existing prefix, skill-root and CLI behavior. Tests use isolated roots, never the owner's real home.

Add read-only `t3-plugins agents list [PLUGIN]` (IDs, version, role, override status, integrity) and `agents show PLUGIN WORKER` (effective definition/provenance, redacted where needed). Doctor verifies local integrity/references, not live model compatibility.

### Explicit overrides and policy snapshot

Use versioned `$XDG_CONFIG_HOME/t3-plugins/workers.json`, falling back to `~/.config/t3-plugins/workers.json`, for:

- `max_live_workers`: `null` (uncapped) or positive integer; reject booleans/fractions.
- `max_repair_cycles`: nonnegative integer, default `3`; reject boolean/null/fractional values.
- Explicit enabled overrides: worker ID, base bundle digest and a relative path under the sole override root above.

Presence alone does not enable an override. Require regular UTF-8 files, matching IDs/base digests and containment without symlinks/traversal. Missing/malformed enabled overrides fail; do not silently substitute defaults. A base upgrade makes prior overrides stale/inactive until explicit re-enable against the new digest. Routing/model/runtime policy remains in existing routing configuration, not this file.

Snapshot limits and exact base/shared/override contents and hashes at job creation. Compose immutable shared boundaries, specialized definition, enabled customization and task contract in that order; repository constraints and actual task authorization control permitted actions. Overrides cannot grant authority or broaden runtime mode. Edits affect new jobs only. Adoption into an existing job requires an explicit policy/plan revision, new briefs and invalidation of affected acceptance.

### Initial worker catalog

| Worker ID | Responsibility |
|---|---|
| imps/stage-executor | Complete engineering stage and verification preparation |
| imps/investigator | Read-only cited investigation |
| imps/auditor | Confirmed findings, hypotheses and refutation by audit dimension |
| imps/reviewer | Independent change review at exact base/snapshot |
| ape/source-researcher | Pinned source comparison, fingerprint and transferable proposals |
| ape/synthesizer | Accepted report comparison, conflicts and bounded experiment proposals |
| elephant-goldfish/factual-checker | Repository/command claim verification |
| elephant-goldfish/cold-reader | Document-only usability/evidence verdict |
| babysitter/pr-maintainer | One scoped PR's authorized triage/repair with exact-head evidence |
| babysitter/pr-reviewer | Independent review of final combined PR changes |
| agent-tuneup/config-researcher | Exact provider-format/scope semantics and sources |
| agent-tuneup/config-verifier | Authorized proposed/applied changes and parse/load/enforcement evidence |

Workers cannot dispatch children or accept their own work. Keep optional imps perspective IDs `solution-architect`, `grumpy-engineer`, `sre`, `business-analyst`, `ux-designer`; pin their full operative text before review, rather than resolving mutable files when recording results. Task authority narrows each role; a definition never grants push, merge or settings-edit permission.

## 2. Whole-job state and acceptance

Add a versioned generic store at `$XDG_STATE_HOME/t3-plugins/jobs/<job-id>` with `--state-root` alternative, outside the target repository by default. Use private permissions, atomic replacement and process locking. Preserve existing plugin state/lessons and imps major-version-2 records; incompatible schemas refuse writes and give the previous-package inspection/resume path.

`job.json` owns coordination facts, **not readiness authority**. Record installation/workflow ownership; source request/hashes; stable requirements and verbatim constraints; separate action authorization; all package/bundle/override pins; finite stages/task slots/dependencies/criteria/resources; counters/status; decisions/blockers; dispatch IDs, host task/child-thread IDs and follow-up relationships; selected target/reason; input/evidence bindings; integration/final acceptance; metrics including unknowns. Wrong installation/workflow/package callers refuse mutation.

A deterministic overview emits every stage, requirement coverage, current stage, outstanding decisions, blockers, task handles, evidence links and fallback indicators without ingesting raw transcripts/logs. A detailed report remains available by path. Resume starts here, reconciles existing handles, then selects an action; a missing reply is never sufficient reason to recreate work.

Validate unique IDs, known acyclic dependencies, finite task slots, scopes and references. Adding **any** stage/task slot/plugin dependency, weakening/removing requirements or constraints, broadening scope/authority, or raising limits requires an owner-decision record with quoted text, source/hash and explicit scope. Otherwise return `undeclared_expansion`. Activating declared optional slots or repairs is automatic; dependencies may be reordered without weakening coverage, and actions/limits may be narrowed. Preserve superseded requirements/dispositions. Decision receipts record evidence, not cryptographic proof of human intent. Helpers never dispatch or implement a scheduler loop.

### Stage and final gates

Distinguish pending, running, awaiting-followup, awaiting-acceptance, accepted-at-snapshot, blocked, failed, cancelled and stale. A terminal task is not an accepted stage. Dependencies consume accepted outputs at pinned hashes/revisions; pending/failed/stale prerequisites block dependents, while independent readers may overlap.

For imps, the coordinator creates the assigned stage gate run with parent ownership. A declared worker verification slot may execute the pinned helper and write only its assigned stage-state/artifact subtree. The actor captures a binding **before each check**, runs exact approved argv/cwd, retains logs/exit codes and submits with that original binding. Coordinator validation/claim inspection decides acceptance. If the worker cannot access/execute the gate, its diagnostics are informational: record coordinator verification fallback, then run authoritative checks with new coordinator pre-check bindings. Never certify earlier tests retroactively or broaden permissions to make a probe pass.

Bindings include applicable repository/source snapshot, requirements, policy, effective brief and consumed dependencies. New provenance affecting evidence meaning participates in acceptance, not just reporting. Implement pinned authoritative validators:

| Workflow | Authority |
|---|---|
| imps | Existing stage-local gate `validate` must currently report completed at the binding; adapters cannot replace it |
| ape | `plugins/ape/scripts/validate_report.py`: operation-specific structure, revision/provenance, sections/coverage and coordinator inspection receipts |
| elephant-goldfish | Repaired `thinking_state.py` readiness/review gate plus `render_handoff.py --check`; `scripts/validate_document.py` for distinct factual and cold-read checks |
| babysitter | `plugins/babysitter/scripts/validate_pr.py`: coordinator-observed current head, required checks, authorized endstate and host receipts |
| agent-tuneup | `plugins/agent-tuneup/scripts/validate_audit.py`: declared report, parse and authorized-edit criteria; correctly reported findings/exit 1 may complete an audit |

Inputs are pinned artifact/observation references, not worker readiness booleans. Semantic/external facts need coordinator inspection; validators establish provenance/coverage/criteria, not truth of arbitrary prose. Research findings need not authorize experiments; read-only PR triage may finish with named blockers; unknown enforcement remains unverified unless required by the task.

`shared/job_acceptance.py` invokes permitted pinned validators and emits receipts containing validator identity/version, stage/job binding, requirement outcomes, source hashes and observed revision. Core stores generic receipts without importing adapters. Overview/dependency checks validate receipt/artifact hash chains and rerun validators where current acceptance is required; editing an accepted flag cannot promote a stage. Integrity checks do not protect against a privileged actor forging all underlying records.

Declare final integration/acceptance and its verification/review slots **in the initial plan** (an existing final stage may serve if it covers everything). Final readiness requires fresh acceptance of **every job requirement** at the integrated current snapshot/policy/dependencies. Imps uses a new final gate; other workflows use `job_acceptance.py validate-final` with applicable validators/current observations. Read-only/remote workflows use their actual source snapshots, not an invented Git head. Historical stage approvals never substitute for final evidence.

Final failure reopens the responsible earlier stage using its remaining cycles, preserves historical acceptance and marks affected dependents stale. Repairs, dependent re-executions and new final checks consume their own stage budgets. Exhaustion, undeclared work or out-of-scope fixes block for an owner decision. Merely inspecting an existing failure report is not another attempt.

## 3. Bounded dispatch, routing and context reuse

A stage attempt is a pass over finite declared primary/support slots at an input binding. Each slot dispatches at most once per attempt. Default attempts are initial `0` plus repairs `1–3`; after the fourth failed pass, block further execution without explicit limit revision. Accepted executions with unusable terminal results consume attempts: provider/model failure, malformed result, required support/review failure, failed acceptance or stale-input re-execution. Escalation/resume/replacement never resets counters. When only support fails and code/inputs/checks remain current, rerun only failed support. Review-only passes count. Cold-read repair is coordinator-owned; new topics default to four total rounds, existing topics retain recorded limits (legacy missing-limit topics record the documented five-round policy and prior performed rounds).

Only the coordinator dispatches. Workers return requests for additional work, checked against declared slots/authority. No recursive hidden work. Uncapped means no plugin live-worker ceiling; respect T3 capacity, dependencies and isolation. Optional configured caps count all owned nonterminal/uncertain tasks, excluding the parent. Parallel writers require verified owned worktrees/paths and declared integration order; otherwise serialize. Preserve cleanup ownership checks immediately before destructive cleanup.

Use live `orchestrator_capabilities` and tool schemas. Repository policy overrides owner routing. Map specialized roles to existing workhorse/reviewer/judgement categories. Record lowest suitable configured tier, suitability reason and ordered escalation. Reviewer roles use reviewer/judgement, applicable tier floors and required known different lineage; unknown lineage is unverified. Do not substitute unconfigured models, broaden runtime ceilings or change the coordinator's model. Do not switch reviewers merely to reverse an adverse verdict. Respect child and cross-provider capabilities separately.

### Task lifecycle

- Start `delegate_task` asynchronously with exact target/options/role and a distinct stable `clientRequestId`; retain the returned task ID immediately. New attempts/required review rounds use new IDs; retries reuse the original ID. Each fresh review carries the original brief, all prior findings/responses and unresolved objections; retain every finding and its disposition.
- Uncertain transport permits the original call plus at most two same-ID retries. Then retain `blocked:uncertain_dispatch`, handle/request/retry count. Resume reconciles that request without resetting retries. Replacement is forbidden until absence/termination is authoritative. Owner abandonment of a proven absent orphan consumes the attempt; inability to establish absence/cancel remains blocked.
- Definite pre-acceptance capacity rejection while this job owns live work is deferred, not an accepted slot/failed attempt. Retain the ID and retry once per newly observed, deduplicated owned completion notification; no polling. If a host forbids reuse of a rejected ID, establish absence before recording the replacement chain. With no owned live work, try the finite configured candidates once each, then fallback/blocker. Other definite target errors use that finite chain immediately. Accepted queued/running tasks remain owned; observation timeout is not termination.
- Completion notifications wake the coordinator. When reading results, check authoritative terminal status, `workState` and pending runs. Unexpected T3-visible descendants/follow-ups prevent acceptance until reconciled. Native channels may be invisible: no-child instructions are policy, not guaranteed host enforcement. Inspect authorized synthetic transcripts where observable and record coverage gaps.
- Cancel only owned tasks; confirm authoritative terminal/pending state. No polling watcher/daemon or top-level-thread substitute.

### Context-preserving follow-ups

Start each new stage, changed definition/provider/model/authority, cold read and required fresh review in a fresh child. For a bounded same-scope follow-up where history helps, use continuation **only if active host/harness policy supports a new tracked task**:

1. Confirm the original owned task is terminal with no pending runs, and operative definition/provider/model/authority/path ownership remain unchanged.
2. Use supported `t3_thread_send` with `mode=queue`, the owned `childThreadId` and a new stable follow-up request ID. Send the delta/current binding and relevant objections without replaying unchanged exploration.
3. Retain its **new task ID**, link original task/conversation, track/cancel the new handle and keep the original result immutable. Apply fresh evidence binding and existing declared-slot/repair accounting.

Unsupported/forbidden continuation uses a fresh child with the current brief/relevant evidence and visible reuse-fallback reason. A missing follow-up task ID is uncertain dispatch under the same retry bound; do not silently send again under a new ID. Finding clarification may reuse context but cannot replace required fresh approval. Tool presence does not override stronger harness freshness rules. No provider CLI/native child/top-level conversation substitute.

If T3 or a suitable stage target is unavailable, record bounded discovery/errors and execute directly under the identical stage contract, counters, scope, evidence and metrics. Show the lost context isolation. Missing required independent review stays an acceptance blocker; direct execution cannot fabricate independence.

## 4. Context-efficient briefs and complete results

A deterministic prepare operation takes job/stage/task references plus saved live capabilities. Write a self-contained UTF-8 brief to the owned private task directory; routine output contains **only path, SHA-256, bytes and compact provenance**. No model calls, credential access or full-brief echo.

Include relevant role/shared boundaries; compact job objective; assigned requirements/finish line; pinned predecessor outputs; operation/base/worktree; exact constraints/authority; binding; target reason; stop conditions/slot/counters; result/redaction/no-child contracts. Do not copy the parent history, all playbooks or all lessons; never assume inherited context.

Prefer a short dispatch bootstrap to read the exact pinned file and check its hash. Prove target read/hash, narrow output/state write and pinned-helper execution through scoped Codex/Claude canaries at actual runtime modes/roots. If file reading is unsupported, inline the same full brief and record added context cost. A missed probe producing terminal unreadable input consumes an attempt. Hash mismatch/unreadable input does not permit finding another installation. Alternative prompt-file transport requires current documented/proven support.

Cold readers receive only their document, procedural role/output instructions and correlation/hash fields. Omit job objective, predecessor reports, factual findings, repo-derived answers and planning discussion. Factual and cold-read acceptance remain distinct.

### Result protocol

Publish `shared/agents/worker-result.schema.json` v1 and a standard-library parser. Support exactly one complete inline JSON object or an artifact envelope (`oneOf`), never prose extraction. Required full-result fields:

- job/stage/logical-slot IDs, request ID, worker ID, effective-brief hash;
- status: `ready-for-acceptance`, `needs-followup`, `blocked`, `failed`;
- conclusion ≤250 words, without losing full findings;
- every assigned requirement: `passed`, `failed`, `unverified`, `unavailable`, `waived` with evidence (waiver requires owner evidence/policy permission);
- review verdict `approve`, `adverse`, `unavailable` (null for non-review); all findings with blocker/major/minor/note severity, concrete scenario and source evidence;
- gaps/uncertainties, changes, exact commands/outcomes, artifacts/revision/binding, extra-work requests and available metrics.

Logical task IDs are predeclared slots; host task IDs come only from host receipts. Blocker/major findings force adverse; cold-read READY/NOT READY maps to approve/adverse with operation identity retained. Results/actions are untrusted data, cannot grant authority or accept stages, and returned artifacts are never executed as helper code.

Canaries establish whether terminal `task_status.summary` preserves the final JSON verbatim, including the 32,768-byte boundary. Only then parse the entire trimmed value with `json.loads`. Reject extra prose/fences, duplicate keys, nonfinite numbers, unsupported versions, missing/contradictory fields, correlation mismatch and oversize; never truncate. Preserve raw diagnostics privately. If summary fidelity fails, use the declared fixed result file after authoritative termination or an exact original final message from permitted `t3_thread_read` for the recorded run if its fidelity probe passes. No valid route means `result_transport_unavailable`.

Prefer an explicitly authorized private `<job>/artifacts/tasks/<encoded-task-id>/` full-result artifact plus a short JSON envelope with path/hash, complete finding-index reference and counts. Validate both schema variants, containment/regular files, correlation/hash and index/count agreement. Full-artifact maximum defaults to 16 MiB, explicitly configurable/pinned per job; this is a transport limit, not a usage/time ceiling. Validate size safely; oversize blocks rather than dropping content.

Strict no-write workers use inline results within the 32,768-byte transport limit. If complete evidence cannot fit without permitted artifact writes, block with size/access reason and request an output-permission decision; no truncation or false acceptance. Declare destinations before requiring artifact output.

The coordinator routinely imports only a short result/overview, opens consequential evidence to verify claims, retains every finding by reference and records fixed/rejected/deferred dispositions with evidence. Emit complete compact checklists at stage start, acceptance, blocker and integration milestones; no raw-log stream.

## 5. Compatibility and acceptance tests

Create a keep/change/remove map for every operation, helper API, manifest field, persisted format and changed/deleted test, with surviving assertions mapped to coverage. Preserve these workflow guarantees:

- **imps:** existing gate/evidence semantics and all operations; new metadata external to old runs; owned legacy status/resume/cancel with pinned recovery paths.
- **ape:** read-only target research, max-five candidates, fingerprints/source provenance/reports and explicitly authorized owned cleanup.
- **elephant-goldfish:** interactive discovery, content-bound discovery acceptance, factual/cold-read separation and deterministic handoff provenance. Coordinate #25; drafts, reminders, resume and requirement changes must not launch implementation or bypass readiness.
- **babysitter:** eligible roster/pagination, isolated PR workspaces, exact-head checks/reviews, explicit communication/merge scope, links/host watches and separately authorized future-PR sweeps.
- **agent-tuneup:** deterministic format checks, optional transcript scan, report-first behavior, authorized backed-up settings edits, distinct parse/load/live-enforcement observations.

Keep provider skill roots/adapters pointing to coordinator entries. Learnings/harvest remain optional, scoped/private and subject to current owner/memory policy. Rollback covers definitions, entries and helpers; migrations never manufacture acceptance.

All requirements below are mandatory. Missing required evidence is incomplete or a named blocker, never a pass. Deterministic tests must not call live models or mutate GitHub.

| ID | Required evidence/test cases |
|---|---|
| REQ-COMPAT | Installed command routing for all operations; synthetic helper/validator results, read-only/action/endstate boundaries; keep/change/remove and assertion map. Mocked commands do not establish authored-output quality. |
| REQ-REGISTRY | Isolated agent-root physical files; two prefixes/plugins; upgrade/rollback; relocation/collision; legacy activation; missing/corrupt/modified/extra/symlink/traversal files; interrupted install/activation; owned uninstall; live/resumable pins prevent deletion. |
| REQ-OVERRIDES | Explicit enable only; exact contents/limits survive resume; stale-on-upgrade; re-enable/adoption invalidates affected acceptance; missing/malformed/escaping files rejected; unrelated config and authority ceilings preserved. |
| REQ-JOB | Five-stage restart retains plan/coverage/decisions/handles; duplicate/cyclic/schema-invalid/undeclared plans rejected; owner evidence for weakening/broadening; concurrent writes; wrong-owner/package mutation rejected; imps/babysitter pins stable across independent current changes; complete overview without transcript ingestion. |
| REQ-DISPATCH | Coordinator-only task allocation; extra-work requests checked against slots; no hidden cap; configured cap vs host capacity distinguished; overlapping readers and isolated/serialized writers. |
| REQ-REPAIR | Initial+three only; fifth pass refused; support/review-only failure, escalation, stale inputs and resume cannot reset counters; final-stage budget and responsible-stage reopening/exhaustion; cold-read limit migration. |
| REQ-HANDOFF | Exact constraints/pins/provenance; hostile/malformed/partial/contradictory results rejected; all findings retained; inline no-write and large-artifact/index modes; inaccessible/corrupt/oversize artifacts; transport fidelity/fallback, no heuristic extraction. |
| REQ-EVIDENCE | Existing snapshot/artifact/review regressions; worker pre-check binding/narrow helper writes; denied access triggers fresh coordinator checks; retroactive bindings rejected; policy/definition/dependency changes stale evidence; hand-edited acceptance cannot bypass validators; injected stage-3 regression rejected by final integrated gate. |
| REQ-LIFECYCLE | Same-ID retries/no duplicates; uncertainty/orphan reconciliation; pending runs prevent acceptance; confirmed cancellation; tracked same-child/new-task follow-ups and immutable original; fresh bindings/counters; changed model/authority rejected; unsupported reuse fallback/missing handle uncertainty; unexpected descendants/native visibility gaps; approval waits; capacity deferral via deduplicated events. |
| REQ-ROUTING | Suitability/escalation/reasons; unchanged parent; exact targets/options; same model ID across providers; unknown lineage; denied cross-provider; missing/malformed catalog; repo precedence/runtime ceilings; overlapping #18 cases. |
| REQ-FALLBACK | Visible direct stage execution with identical scope/budget/gate; finite availability candidates; unavailable required review remains blocked; actual model failure not misclassified as capability absence. |
| REQ-BOUNDARIES | No research implementation, planning-to-engineering transition, audit permission expansion or unauthorized PR posts/push/merge; content-bound discovery; cold-reader isolation; no global automatic profile invocation. |
| REQ-VISIBILITY | Complete milestone checklists and fallback markers; five-stage restart identifies whole plan/next dependency without worker transcripts; unresolved cross-stage decisions retained. |
| REQ-METRICS | Protocol below; all attempts/usage/cache/runtime/quality and attribution; missing values null with reasons; no savings claim from proxies or incomplete telemetry. |
| REQ-LIVE | Installed-artifact Codex/Claude scenarios below with exact discovered IDs/build/modes/OS/interventions/failures; other providers explicitly unverified. |
| REQ-DELIVERY | Final relevant-head repository checks, isolated installation, documentation of registry/overrides/lifecycle/recovery/migration/fallback/measurement limits; desktop/mobile inspection for changed user-visible docs. Report hosted CI separately when authorized. |

## 6. Context measurement and live protocol

Create a new versioned protocol; retain historical benchmark protocol/results. Use isolated provider homes and authorized bench instances for parent/children; coordinate #21 prerequisites. Freeze synthetic tasks and hidden behavior/quality grading before new runs. Do not mutate real provider homes/settings, use real credentials/transcripts/hostnames in fixtures, or replace unreachable synthetic GitHub with production.

Planned live starts:

| Scenario | Scope |
|---|---|
| Paired five-stage engineering job | Three baseline/rebuilt pairs per Codex and Claude: **12 starts**. Same parent model/options, mode, repo/fixture bytes, authority and environment within each pair. Repetition 3 interrupts both arms at the same stage boundary. Record worker routing differences. |
| Other plugin workflows | One ape, elephant-goldfish, babysitter and agent-tuneup scenario per provider: **8 starts**. Synthetic GitHub/settings only. |
| Negative paths | One missing-delegation direct fallback and one unavailable-required-review scenario per provider: **4 starts**. |

Total **24 starts**, plus separately declared/recorded canary tasks and finite task/repair slots. Map all 12 workers to actual dispatches at least once per provider: engineering fixture covers investigator/executor/auditor/reviewer; other workflows cover their two specialized workers. Ape declares one same-scope source-research follow-up slot: prove new task ID/same conversation, immutable original and delta input where permitted. Otherwise exercise fresh fallback and leave continuation support explicitly unverified.

Before quality runs probe actual child input-root read/hash, narrow write/helper execution, verbatim summary/original-message transport and synthetic GitHub/loopback reachability. Missing isolated instances/login/measurement/fixture access is a named blocker; schema discovery/unit tests are not live acceptance. No undocumented permission/config changes to unblock runs.

Predeclare infrastructure-invalid criteria: verified provider/auth/transport/host failure before usable execution, lost host-owned run or confinement failure. Model mistakes, wrong tools, malformed results and quality defects count as failures, not rerun grounds. Allow one infrastructure-invalid retry per planned start; retain both records. A second invalid run blocks the requirement. Report all attempts, not only successful replacements.

Measure:

- Per-inference parent input/context, **including cached input**; deduplicate by actual request/message identity. Report peak/stage-boundary sizes separately from output and cumulative tokens.
- Parent plus every owned worker's usage, cache reads/writes, repeated setup, attribution gaps and known aggregate totals.
- Wall time, attempts/repairs/task counts, compactions, interventions, fallback and correctness of retained plan/decisions.
- Frozen behavioral quality, defects/false acceptances/omitted requirements and cold-reader contamination.

Unknown values are `null` with reasons, never zero. A verified usage/stage-context proxy is not actual peak occupancy. Add parser fixtures for duplicate messages, cumulative vs per-call counters, caches/missing values and attribution. Keep stable shared instructions before variable revision/delta/round fields where supported. Measure cache behavior of fresh stages/reviews and retained-context follow-ups separately; neither is automatically efficient. No SDK/cache-control bypass or redefining vendor accounting. Raw transcripts stay private; publish sanitized synthetic summaries/identities/hashes only.

Every counted rebuilt scenario must pass frozen required checks, including expected blocked negative outcomes. Baseline failures are reported, do not excuse rebuilt failures and do not gate completion. Incomplete paired telemetry remains explicit. Quality cannot be traded for context savings; numerical efficiency may improve, stay equal or worsen without itself blocking completion.

## 7. Implementation sequence and completion

Save this issue as the requirement source, refresh the intended implementation base and use pinned predecessor outputs at each stage. Six implementation stages:

1. Freeze operation/safety/assertion mapping, five-stage fixture, grading/measurement protocol and baseline package identity. Run separately authorized canaries; record transport/environment blockers.
2. Implement source catalog, managed bundles/ownership/pinning, explicit overrides, installation/doctor/inspection/upgrade/rollback/uninstall and isolated artifact tests.
3. Implement generic jobs, compact overview, task/attempt/provenance storage, restart reconciliation interfaces, brief/result parser and authoritative stage/final acceptance adapters. No scheduler.
4. Rebuild all five coordinator entries/adapters and specialized definitions: whole-stage dispatch, suitability routing, bounded tracked follow-ups, repair/fallback, operator milestones and preserved boundaries.
5. Complete legacy migration, cross-stage regressions, all-operation installed tests and docs; coordinate #25 readiness and #18 routing/cleanup overlap without automatically editing/closing those issues.
6. Execute the final installed-artifact 24-start Codex/Claude protocol, retain all evidence and report metrics/blockers. Later relevant changes invalidate affected evidence.

Each handoff records requirement coverage, exact head/package/bundle, checks/evidence, decisions and blockers. Required checks at the final relevant head:

```sh
python3 scripts/run_tests.py
python3 scripts/check_docs.py
python3 -m mkdocs build --strict
```

Use a docs venv with `requirements-docs.txt`. Changed shell helpers also need `bash -n` and focused fixtures. Test installed artifacts with isolated HOME/XDG roots, prefix, agent root and provider skill roots. Keep entries under 1,500 words; inspect changed user-visible docs at desktop/mobile widths. Tests should exercise outcomes/adversarial state changes, not mirror implementation; never weaken surviving safeguards to pass.

Completion requires evidence for every REQ, or explicit blocked/incomplete status. Reject silent truncation, mutable unpinned definitions, implicit scope expansion, terminal-task-only acceptance, missing usage presented as zero, owner-home test mutations and false live compatibility claims. Local checks, current-head hosted CI, merge, release, tap, Pages and live acceptance remain separate. Implementation commands govern action authorization; this specification is not blanket permission to push, merge, publish or deploy.

