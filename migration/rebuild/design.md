# Issue #28 interface design (Stage 1)

This is the Stage 2–4 implementation contract. Helpers remain Python 3.10+ and
standard-library only. They prepare, store and validate data; they never call a model,
dispatch work, or schedule tasks. T3 owns task execution and lifecycle. Workflow adapters
own operation policy and acceptance. The coordinator retains whole-job authority.

## Source and installed layout

Worker definitions live at `plugins/<plugin>/agents/<worker>.md`. The canonical contracts
are `shared/agents/worker-result.schema.json` v1 and additional shared contract/schema
files in `shared/agents/`. The parser is `shared/worker_result.py`; generic acceptance
receipts are created by `shared/job_acceptance.py`. Plugin validators are
`plugins/ape/scripts/validate_report.py`,
`plugins/babysitter/scripts/validate_pr.py`,
`plugins/agent-tuneup/scripts/validate_audit.py`, and
`plugins/elephant-goldfish/scripts/validate_document.py`. The latter uses repaired
`thinking_state.py` readiness plus `render_handoff.py --check` for handoff acceptance.
Imps continues to use the existing core gate `validate`.

Managed assets are immutable under
`<agents-root>/installations/<installation-id>/<plugin>/<package-version>/`:
`manifest.json`, `workers/<worker>.md`, and `shared/<required-contract-files>`. Explicit
customizations are under `<agents-root>/overrides/<plugin>/<worker>.md`; only a matching
explicit enabled record in `$XDG_CONFIG_HOME/t3-plugins/workers.json` (fallback
`~/.config/t3-plugins/workers.json`) activates one. `t3-plugins agents list [PLUGIN]`
and `t3-plugins agents show PLUGIN WORKER` inspect effective definitions and provenance.
`--agents-root` is supported by install/setup/doctor/activation/removal. The existing
prefix, skill-root and CLI behavior remains supported.

## CLI and state interfaces

- `t3-plugins --job JOB path PLUGIN` resolves a pinned concrete package and declared
dependency; it refuses undeclared plugins. Ordinary `path` retains current behavior.
- `t3-plugins agents list [PLUGIN]` and `agents show PLUGIN WORKER` are read-only.
- `$XDG_STATE_HOME/t3-plugins/jobs/<job-id>/` (or `--state-root`) contains versioned
  `job.json`, compact `overview.json`, immutable `briefs/<encoded-task-id>.json`,
  `results/<encoded-task-id>.json` or artifact envelopes, `acceptance/<stage>.json`,
  `artifacts/tasks/<encoded-task-id>/`, and private logs/references. Atomic replacement,
  process locks and private permissions apply. Existing plugin state, learnings and imps
  major-version-2 records remain separate and readable by compatible legacy paths.
- Each brief binds job/stage/logical-slot/request/worker IDs, effective-brief SHA-256,
  requirements, exact scope/authority, snapshot, pinned dependencies, slot/counters,
  target rationale, stop conditions and result contract. Routine prepare output is path,
  digest, size and compact provenance only.
- A result is exactly one full inline JSON object or one artifact envelope. Parse the full
  value; reject prose/fences, duplicate keys, non-finite numbers, unsupported versions,
  correlation/hash mismatches, missing/contradictory fields and oversize. No extraction or
  truncation. Preserve raw diagnostics privately. Result claims never grant authority or
  accept a stage.
- `job.json` stores plan/requirements, authorization, decisions, pins, counters, handles,
  bindings, blockers and metrics. It does not own readiness. `job_acceptance.py` calls the
  pinned workflow validator and emits hash-bound receipts; overview and dependency checks
  verify the chain and rerun applicable current validators.

## Schemas and versions

All JSON schemas carry an explicit `schema_version`; incompatible writers fail closed and
show the compatible inspection/resume route. Stage 3 introduces
`shared/agents/job.schema.json` v1, `stage.schema.json` v1,
`shared/agents/worker-brief.schema.json` v1,
`shared/agents/worker-result.schema.json` v1, `shared/agents/result-envelope.schema.json`
v1, and `shared/agents/acceptance.schema.json` v1. Installation metadata uses
`manifest.json` v1 and existing receipt/manifest versions are migrated without claiming
acceptance. Routing remains in existing routing configuration; workers.json contains only
limits and explicit definition overrides. `workers.json` v1 allows `max_live_workers` null
or positive integer and `max_repair_cycles` nonnegative integer (default 3); booleans and
fractions are invalid. A stale override after base upgrade is inactive until explicit
re-enable. Snapshots pin exact definition and policy bytes.

## Ownership and integration order

Stage 2 and Stage 3 can proceed concurrently after Stage 1 outputs are accepted. They own
disjoint paths. If a listed future path does not exist yet, its named stage creates it.

| Stage | Owned paths | Boundary |
|---|---|---|
| 2: registry/installation | `scripts/install.py`, `scripts/catalog.py`, `scripts/setup.py`, `scripts/doctor.py`, `core/installation*.py`, `plugins/*/plugin.json`, `shared/agents/manifest.schema.json`, `tests/test_install.py`, `tests/test_catalog.py`, `tests/test_setup.py`, `tests/test_registry*.py`, `migration/rebuild/compat-map.d/stage-2.json` | Agent-root packages, receipts, identity, pins, overrides, inspection, upgrade/rollback/uninstall. No job-state implementation. |
| 3: jobs/briefs/results/acceptance | `core/jobs/`, `shared/agents/job.schema.json`, `shared/agents/stage.schema.json`, `shared/agents/worker-brief.schema.json`, `shared/agents/worker-result.schema.json`, `shared/agents/result-envelope.schema.json`, `shared/agents/acceptance.schema.json`, `shared/worker_result.py`, `shared/job_acceptance.py`, `plugins/*/scripts/validate_*.py`, `tests/test_jobs*.py`, `tests/test_worker_result.py`, `tests/test_job_acceptance.py`, `migration/rebuild/compat-map.d/stage-3.json` | Generic job data and adapter validation interfaces. No dispatch loop, registry mutation, or entry rewrite. |
| 4: coordinator adapters | `plugins/*/entry.md`, `plugins/*/agents/`, `plugins/*/playbooks/`, `plugins/*/references/`, `shared/t3-runtime.md`, `tests/test_*workflow*.py`, `migration/rebuild/compat-map.d/stage-4.json` | All five plugin policies, stage delegation, routing, repair/fallback and approval picker. |
| 5: integration | Remaining migration/docs/tests plus `migration/rebuild/compat-map.d/stage-5.json` | Legacy migration, installed artifact and cross-stage regressions, docs and review. |
| S1b: bench isolation | `bench/container/` (Dockerfile, launcher, synthetic GitHub sidecar, canary scripts) and S1b-owned protocol/plan amendment | Container confinement and live canaries; not a Stage 1 writer path. |

Integration order: Stage 2 and 3 work in parallel. Integrate their schemas and interfaces
before Stage 4 adapters; Stage 4 binds entries/validators to the integrated APIs. Stage 5
runs migration, installed-artifact and cross-stage coverage at one relevant head. S1b may
build its isolated bench infrastructure separately; live acceptance is Stage 6 and remains
a separate gate. Writers append stage-local compatibility shards so parallel work does not
edit the base map or another stage's shard.

## Approval and model-cost requirements

Every plugin approval and owner decision uses the host's native question picker
(`REQ-APPROVAL-PICKER`). Stage 4 must preserve the coordinator-authored contract in
`shared/t3-runtime.md`; Stage 5 verifies all plugins route approval waits through it.

For `REQ-TEST-MODELS`, every live parent, worker, reviewer, canary, retry, repair, resume,
and native child uses only Claude Haiku or Codex Luna. S1b discovers exact live-catalog
IDs, freezes them, uses low effort, standard service tier and no fast mode, and rejects
any other target without sending a request. No costly fallback or silent upgrade is
allowed after a quality failure. `bench/v2/tools/model_policy.py` is the policy helper;
S1b must wire it to every launch/dispatch route, restrict container catalogs/routes, test
forbidden targets produce zero dispatches, and audit actual transcript model IDs. Offline
Stage 1 tests use synthetic fixtures only.

## S1b canary acceptance

S1b owns separate isolated Docker containers. Each has its own headless `t3 serve`, fresh
empty Claude Code and Codex homes, runtime-injected API keys from a private env file
outside the repository, an allowlist proxy restricted to Anthropic/OpenAI API hosts, and
a synthetic GitHub sidecar on a private Docker network; host loopback is unreachable from
containers. The harness calls each container's own T3 MCP endpoint with self-minted auth.
The mount namespace is the primary confinement guarantee; the audit detects attempts.
Raw transcripts stay on the bench host. Only sanitized summaries may be committed or
uploaded.

Before quality starts, S1b proves for both providers: pinned brief read/hash; narrow task
subtree write and pinned helper execution; terminal summary fidelity at 32,767/32,768/
32,769 bytes; exact final-message retrieval; queued same-child follow-up yielding a new
task ID; synthetic GitHub reachability and host-loopback unreachability. It also proves
forbidden model targets dispatch zero requests and audits actual model IDs for parents,
workers, native children, reviewers, canaries and subsequent runs. A failed/unavailable
probe is a named blocker; no schema/unit-test result substitutes for live evidence.

## Requirements and proving tests

| Requirement | Owning stages | Required proof location |
|---|---|---|
| REQ-COMPAT | 2–5 | `tests/test_rebuild_compat_map.py`; installed operation routing and validator tests |
| REQ-REGISTRY | 2, 5 | `tests/test_registry*.py`, `tests/test_install.py` |
| REQ-OVERRIDES | 2–5 | registry/override tests; resume snapshot and stale-override tests |
| REQ-JOB | 3, 5 | `tests/test_jobs*.py`, restart/ownership/overview tests |
| REQ-DISPATCH | 4–5 | workflow dispatch and slot/capacity tests |
| REQ-REPAIR | 3–5 | job counter and workflow repair tests |
| REQ-HANDOFF | 3–5 | `tests/test_worker_result.py`, `tests/test_job_acceptance.py`, hostile artifact/result tests |
| REQ-EVIDENCE | 3–5 | core binding regressions and authoritative validator tests |
| REQ-LIFECYCLE | 3–5 | reconciliation/follow-up/approval-wait and handle tests |
| REQ-ROUTING | 4–6 | exact-target/routing tests and live-catalog observations |
| REQ-FALLBACK | 4–6 | direct fallback and unavailable-review tests; live negative scenarios |
| REQ-BOUNDARIES | 4–5 | per-plugin boundary and cold-reader tests |
| REQ-VISIBILITY | 3–5 | overview/restart/checklist tests |
| REQ-METRICS | 1, 6 | `tests/test_bench_v2.py`; parser tests and complete sanitized run records |
| REQ-LIVE | S1b, 6 | container canaries, exact-model audits and 24-start protocol records |
| REQ-DELIVERY | 5–6 | full required suite, isolated installed-artifact checks, docs inspection and separately reported hosted CI |
| REQ-APPROVAL-PICKER | 4–5 | `tests/test_contract.py` and per-plugin approval routing tests |
| REQ-TEST-MODELS | 1, S1b, 6 | model-policy unit tests, zero-dispatch forbidden-target test, actual transcript-model audits |

## Open decisions

- **OD-01: override CLI shape.** The issue defines file format and explicit-enable semantics,
but not management commands. Recommendation: Stage 2 adds explicit enable/disable subcommands
only if needed by existing setup conventions; never infer enablement from file presence.
- **OD-02: workers.json schema placement.** The issue fixes its location and fields but not
its schema filename. Recommendation: Stage 2 owns `shared/agents/workers-config.schema.json`
v1 and keeps routing fields out of it.
- **OD-03: artifact size override syntax.** The issue allows a per-job configurable 16 MiB
limit without naming its control. Recommendation: Stage 3 stores it in the versioned job
policy snapshot and rejects resume changes without policy revision.
