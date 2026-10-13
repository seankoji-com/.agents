# Benchmark protocol v2 (frozen)

Frozen on 2026-10-12 in Stage 1 of issue #28, before any v2 run. Stage 6 runs it
unchanged. `bench/protocol.md`, `bench/rubric.md` and `bench/runs/` are the issue #15
protocol and results; v2 does not change or reinterpret them.

`frozen.json` records the SHA-256 of every frozen file, and `tests/test_bench_v2.py`
fails if any of them changes. A change after the first v2 start needs a dated amendment
in this file, recorded before the next start, that names the affected starts. Those
starts are then stale and must be repeated.

## Purpose

v2 measures what the rebuild changes: how much context the coordinator carries through
a multi-stage job, what every owned worker costs, and whether quality holds. Quality is
the gate. Efficiency is reported and may improve, stay level or get worse. A context
saving never offsets a failed required check.

## Locations

| What | Where | Committed |
| --- | --- | --- |
| Protocol, plan, fixture, hidden checks, reference solution, tools | `bench/v2/` | yes (`bench/` is export-ignored) |
| Start plan and canary list | [plan.json](plan.json) | yes |
| Frozen file digests | [frozen.json](frozen.json) | yes |
| Sanitised summaries | `bench/v2/runs/<start-id>/attempt-<n>/` | yes, written in Stage 6 |
| Raw transcripts, job state, provider homes | private results directory outside the repository | no; SHA-256 only |

## Arms and packages

- **baseline**: the packages identified in `migration/rebuild/baseline.json` (base commit
  `3cb0d11`), built with that commit's `scripts/install.py` into a scratch prefix.
- **rebuilt**: the packages and agent bundles built from the final Stage 5 commit with its
  own installer into a scratch prefix and scratch agent root.

Each installed package directory is made read-only before the first start and checked
with `bench/tools/verify_package.py` before the first and after the last start of its
arm. Workers receive version directories, never a `current` path.

## Isolation

Every start uses a fresh workspace from `tools/prepare_workspace.py`, a fresh
provider home and XDG roots, a scratch job state root and an authorised bench T3
instance. No start reads or writes the owner's real provider homes, settings,
credentials, transcripts or GitHub. Each S1b bench container runs its own headless
`t3 serve` with fresh empty Claude Code and Codex homes. Runtime API-key credentials come
from a private env file outside the repository and are injected only at runtime. Egress
is restricted by an allowlist proxy to Anthropic/OpenAI API hosts. A synthetic GitHub
sidecar shares only a private Docker network with the container; host loopback is
unreachable. The harness drives the container T3 server through its MCP endpoint with
self-minted auth. The mount namespace is the primary confinement guarantee; the audit
records attempted escapes. Raw transcripts remain on the bench host; only sanitized
summaries may be committed or uploaded. Production is never a substitute when it is
unreachable. Changing
permissions or configuration to unblock a run, other than as recorded in this protocol,
voids the start.

## Five-stage engineering fixture

The run agent receives [fixtures/five_stage/prompt.md](fixtures/five_stage/prompt.md)
and a workspace prepared from `fixtures/five_stage/workspace`: a CSV ledger in
standard-library Python with one seeded arithmetic defect and two seeded export flaws.

| Stage | Work | Primary rebuilt worker |
| --- | --- | --- |
| s1 | Cited root-cause investigation, no code change | imps/investigator |
| s2 | Exact amount parsing and its error contract | imps/stage-executor |
| s3 | `report --by month` | imps/stage-executor |
| s4 | Export audit and fixes | imps/auditor, then imps/stage-executor |
| s5 | Docs, changelog, full suite, independent review | imps/stage-executor, imps/reviewer |

The agent never sees `checks/`, the hidden datasets in `checks/five_stage.py` or
`checks/reference/`. The executor grades committed output in an isolated clone:

```sh
python3 bench/v2/checks/five_stage.py <isolated clone> --json
```

Required checks C1 to C13 cover the cited defect line, exact totals, rejected invalid
amounts (including `1e3`) on every command, the exact monthly report, rejected invalid
dates, formula neutralisation that leaves negative amounts numeric, refusal to export
onto its own input under three spellings, the workspace suite, unchanged `total` output,
README and changelog coverage, audit severities, and a recorded review verdict.
I1 (new tests fail on the original code) and I2 (one commit per stage) are informational.
`tests/test_bench_v2.py` proves that the reference passes and the untouched fixture and
named mutants fail. The checker runs workspace code, so it is run only on a disposable
clone.

Repetition 3 of each engineering pair is interrupted in both arms at the same boundary:
after s3 is accepted (rebuilt) or after the `stage-3:` commit (baseline). The executor
interrupts the thread, then sends `resume` to the same coordinator in a fresh turn.
Plan, decisions and next dependency must come from recorded state, not from transcripts.

## Other workflows and negative paths

[plan.json](plan.json) lists one ape, elephant-goldfish, babysitter and agent-tuneup
start per provider. Their complete synthetic inputs, expected artifact hashes, and named
checks are frozen in `fixtures/workflows/contracts.json`; the offline graders inspect the
corresponding source, job, receipt, workspace, thread, and host-observation artifacts.
Each must exercise both of its plugin's specialised workers. The ape start includes one
declared same-scope follow-up slot. It must show a new task ID in the same conversation,
an unchanged original result and delta-only input where the host permits continuation.
Otherwise it uses the fresh fallback and leaves continuation unverified.

Negative starts reuse the five-stage fixture. **Missing delegation**: change only the selected provider capability field
`canRunChildTask` from true to false. Keep the parent target provider ID, exact model ID and
options byte-identical to the validated target; parent/canary policy checks still require
the exact enabled catalog/model/options and family guard, while worker/child/reviewer
checks require child capability. The coordinator must run every stage directly, with the
same scope, counters and gates, and record a visible fallback marker per stage. **Unavailable required review**: no reviewer target satisfies the routing
rules. The job must stop blocked, naming `required_review_unavailable`, with no stage
accepted on the strength of a missing review and no final readiness.

## Planned starts

| Scenario | Starts |
| --- | --- |
| Paired five-stage engineering job: 3 baseline/rebuilt pairs × Codex, Claude | 12 |
| ape, elephant-goldfish, babysitter, agent-tuneup × Codex, Claude | 8 |
| Missing delegation, unavailable required review × Codex, Claude | 4 |
| **Total** | **24** |

Within a pair, both arms use the same parent provider instance, model, options,
runtime mode, fixture bytes, authority and environment. The executor reads the parent
model from live `orchestrator_capabilities` at the first start and records it; no model
ID is fixed here. Worker routing differences between arms are recorded, not equalised.
Across all of a provider's starts, every one of the 12 workers must be dispatched at least once.
Canaries and declared task/repair slots are recorded separately and are not starts.

### Owner amendment: live-test model costs, 2026-10-12

This amendment supersedes parent-model inheritance and unrestricted worker routing
above. The owner requires tests to use Haiku and Luna, never high-cost models.
All 24 starts, canaries, parents, workers, reviewers, retries, repairs and resumed
turns use only Claude Haiku and Codex Luna. Choose exact IDs from the bench
container's live catalog and freeze one target per provider before the first start.
Both arms use those same targets. Missing models block the run; there is no fallback
to Opus, Sonnet, Sol, Astra or an inherited session default. Use low effort and the
standard service tier, with fast mode disabled. Record exact targets and options.

`tools/model_policy.py` validates each explicit target against the live catalog.
Stage S1b must wire it into every parent/canary launch and child-dispatch path before
paid requests, and test that forbidden targets cause zero dispatches. Restrict the
container's exposed catalog and routing configuration to those validated targets;
reject any model change on resume or retry. Audit actual transcript model IDs,
including native children, against the frozen targets. A mismatch invalidates the
start and stops further requests. Never fix a quality failure by upgrading models.
Deterministic repository tests stay offline and use synthetic data.

No v2 start has run yet; all planned starts use this amendment. Refresh `frozen.json`
before the first start. Container integration and live enforcement are S1b gates.

## Canaries (before any quality start)

Per provider: child reads the pinned brief and returns its hash; child writes only its
own task subtree and runs one pinned helper; terminal `task_status.summary` keeps final
JSON verbatim at 32,767, 32,768 and 32,769 bytes; `t3_thread_read` returns the exact
final message; a queued follow-up to a terminal owned child gets a new task ID; the child
reaches the synthetic GitHub loopback and nothing else. A failed or missing canary
is a named blocker for the capability it probes. Schema discovery and unit tests are
not live acceptance. In Stage 1 every canary is planned for S1b; canaries are separate from Stage 1 and must pass before quality runs.

## Attempts and infrastructure-invalid starts

A start is **infrastructure-invalid** only for: a verified provider, authentication,
transport or host failure before usable execution; a lost host-owned run; or a
confinement failure (the run read or wrote outside its workspace, package, job state
and harness directories). Model mistakes, wrong tools, malformed results, unhelpful
fallbacks and quality defects are failures, not grounds for a retry. Each planned start
may be retried once for an infrastructure-invalid attempt; both records are kept. A
second invalid attempt blocks the requirement that start serves. Every attempt is
reported, not only the counted one.

## Measurements

`tools/usage.py MANIFEST` is the frozen parser. The executor writes the manifest from job
records: one source per transcript file, its role (`parent`, `worker` with host task
ID/slot/stage/attempt, or `unattributed`) and the stage-boundary times.

- **Inference**: one model request, identified first by Claude message/request identity or
  Codex session plus token-count event position. Distinct known identities remain distinct
  even when timestamps and usage match. Same-identity resumed copies deduplicate only when
  role and task ownership agree. Identityless events are retained and reported as ambiguous;
  their content is never used to erase possible independent usage.
- **Parent context per inference**: input including cached input
  (`input + cache_creation + cache_read` for Claude JSONL; `input_tokens` for Codex,
  which already includes cached input). Report peak and stage-boundary sizes separately
  from output and cumulative totals. Native sidechain lines are excluded and reported
  as unattributed.
- **Counters**: Codex per-call usage is `last_token_usage`, otherwise consecutive
  differences of cumulative `total_token_usage`. A repeated snapshot is one inference only
  when a stable session/event identity supports that dedupe; otherwise it is counted and
  reported as ambiguous. A decreasing counter makes that inference unknown.
- **Usage and cache**: parent and each owned worker, with input, output, cache reads and
  cache writes. Fresh-stage and fresh-review caching is reported separately from
  retained-context follow-ups. Neither is assumed efficient.
- **Unknown**: `null` with a reason, never 0. An unknown total also carries
  `known_lower_bound`, which is a floor and not the total. A usage or stage-context proxy is
  never reported as actual peak occupancy.
- **Also recorded per start**: wall time; attempts, repairs and task counts; repeated
  setup; compactions; interventions; fallbacks; whether retained plan and decisions were
  correct after the interrupt; required-check results, defects, false acceptances,
  omitted requirements; and cold-reader contamination (any job objective, predecessor
  finding or repository answer reaching a cold reader).

Savings are claimed only from complete paired telemetry. Incomplete pairs are
reported as incomplete.

## Pass rule

Every counted rebuilt start must pass its frozen required checks, including the
expected blocked outcome of a negative start. Baseline failures are reported. They do
not excuse a rebuilt failure and do not gate completion.

## Records and privacy

Per attempt: start ID, attempt number, arm, provider instance and model as read
back, runtime mode, OS, T3 build, package/bundle digests, job ID, thread and task IDs,
check results, parser summary, interventions, failures and the SHA-256 of every
private raw file. Committed records contain only synthetic data, sanitised summaries,
identities and hashes. They contain no credentials, transcripts, absolute machine paths
or private hostnames.


### Owner amendment: container confinement, 2026-10-12

S1b owns `bench/container/` (Dockerfile, launcher, synthetic GitHub sidecar and canary
scripts). Each container uses a mount namespace as the primary confinement guarantee;
the confinement audit is an attempt detector. Container, proxy, homes, credentials and
transcripts are private bench infrastructure. The repository is public: publish only
sanitized summaries, synthetic identities and hashes. Live integration remains S1b’s gate;
no v2 start or canary is run by Stage 1.

### Owner amendment: frozen grading and attempt contracts, 2026-10-12

This amendment is recorded before any quality start. It preserves the original protocol and
freeze history. The four workflow scenarios use complete synthetic input bytes and hashed source/output
artifacts under `fixtures/workflows/`, pinned by `fixtures/workflows/contracts.json`.
`checks/workflow_contract.py` verifies hashes and independently derives each result from
those saved artifacts; self-reported flags or model output alone cannot pass. The ape case
checks immutable original-result bytes, exact source provenance, and a correlated new follow-up
task. Elephant-goldfish checks seeded incorrect facts against frozen source facts and verifies
that the cold brief omits prior findings. Babysitter binds checks and comments to one synthetic
head and checks trusted sidecar observations for unauthorized post or merge calls. Tuneup
checks byte-exact backup, allowlisted settings diff, and separate parse/load/enforcement
observations. The negative scenarios freeze five direct-stage receipts and their scope, budget
and gate hashes, plus an unavailable-review job state and dispatch observations. Their graders
inspect receipts and coordinator/host evidence rather than outcome booleans. `plan.json`
names each check ID. Stage 4 may provide a runtime adapter but cannot change the frozen
inputs, expected artifact hashes, or checks. The five-stage CSV export has
one header row exactly `date,account,description,amount`, then data rows.

Missing-delegation outcomes require direct execution of all five stages with a version-1
fallback marker on each stage and zero worker dispatches. Unavailable-review outcomes
require job status `blocked`, blocker code `required_review_unavailable`, zero accepted
stages, no final readiness receipt and zero reviewer dispatches. These are checked by
`checks/negative_start.py` using the named check IDs in the plan. No prose-only outcome is
accepted.

Every attempt record is schema version 1 and is checked against `tools/attempt.schema.json` by `tools/attempt_record.py`. It
requires start/attempt/arm, provider instance, exact model as read back, options, mode, OS,
T3 build, package and bundle pins, job/thread/task IDs, check results, parser summary,
interventions, failures, raw-file hashes and metrics. Unknown scalar environment or model
readbacks are null only with `unknown_reasons` keyed to that field. `model_as_read_back`
contains exact `provider_instance_id` and `model_id`; model options are an object preserving
all requested option IDs and read-back values. Metrics include wall
seconds, repair/attempt/task counts, compactions, fallback count, repeated setup, parent
peak context, worker usage, attribution gaps and retained-plan correctness; unavailable
measurements are null with a reason. Proxy values cannot populate peak occupancy.

The parser regression suite freezes same-basename sources, renamed resumed copies,
partial cumulative caches, copied sidechains, malformed metadata, naive timestamps,
invalid boundaries, lower-bound completeness and unknown reasons. No totals are published
from a proxy or an unattributed source as if attribution were complete.

### Owner amendment: S1 repair2, 2026-10-12

Before any quality start, this amendment replaces basename inference identities with
content-bound identities, checks source and task metadata types/conflicts, and records
boundary timestamp attribution gaps. The `frozen.json` amendment records the exact
post-repair file digests. Affected future starts: all 24 planned starts; none have run.
The immutable issue and original frozen file history are unchanged.

The benchmark checker executes arbitrary workspace code. The S1b protocol must invoke it
only inside the container-owned execution environment, with mount confinement; host-side
unit tests use synthetic trusted fixtures only. Synthetic GitHub is a private Docker
network sidecar, while host loopback must be unreachable. Every provider has separate
host-loopback exclusion, forbidden-target zero-dispatch and transcript model-ID audit
canaries. All failures remain blockers before quality starts.


### Owner amendment: role-aware child capability, 2026-10-12

The F4 repair adds an explicit target role to model-policy validation. Worker, child,
native-child and reviewer targets require `canRunChildTask: true`; parent and canary
targets do not. Every role still requires the exact enabled provider/model catalog entry,
allowed family and exact low-cost options. Missing-delegation changes only
`canRunChildTask`; the parent target and its options remain unchanged. The complete frozen
file-map integrity check still covers every launch-policy and plan source before starts.


### Owner amendment: Stage 1 final repair3, 2026-10-12

This amendment preserves the original freeze and repair2 history; the original frozen-map
SHA-256 is `cf2f99adae21024c9d520d67e9375825cbcbf9a0b6d2392dfe167f4faea75edf`, and the
repair2 map SHA-256 is `4dc67c32a5cab7b2659ee3dc4df242dab703e7a508fee0e79b8113c58be6602d`. No
quality start has used either map. Repair3 binds usage deduplication to known Claude message/request
IDs and Codex session/event identity; different IDs are never content-collapsed. Identityless
streams keep their counts and produce attribution gaps. Same-inference ownership conflicts fail
closed, and inference and gap provenance is manifest-relative.

Attempt-record validation now loads the adjacent published JSON schema without changing shared
validation globals, rejects duplicate JSON keys and non-finite constants, checks nested types,
enums, bounds, digest maps, exact model readback consistency, and null-reason rules. Workflow
and negative-start grading now requires the frozen synthetic artifact sets and checks hashes,
provenance, correlations, receipts, scope/budget/gate continuity, and observed dispatch/action
records. Forged expected booleans and missing or tampered evidence fail. The amended map is
recorded in `frozen.json` before any quality start; all 24 planned starts remain unused.
Coordinator and synthetic host observations are labelled separately from worker results;
they are trusted fixture evidence for grading, not cryptographic proof of owner intent.


### Owner amendment: Stage 1 benchmark repair4, 2026-10-12

This amendment is recorded before any quality start. It preserves the original, repair2,
and repair3 freeze history and all prior failed ledgers. Frozen digests now cover only
workflow inputs and seeded sources. Per-run outputs are checked against a separate
coordinator/host context supplied with `--context`, stored outside worker output. Offline
context seed files carry only synthetic host observations; each fixture test builds a fresh
context with a new nonce and run ID. The context records exact output paths and hashes, observed ID
coverage, and IDs captured from host/coordinator observations. Missing context, copied
reference output without its corresponding run record, fresh IDs without matching host
observations, incomplete coverage, and tampered context fail. The worker cannot establish
run identity by writing a nonce or expected booleans into its own output. Synthetic
coordinator contexts are test fixtures only and do not establish live acceptance.

The five-stage checks require numeric input/actual/expected evidence for the seeded decimal
defect, distinct formula-injection and same-file audit findings with locations, reproducers,
severities and fixes, and a review tied to changed code, the seeded defect, and a current
check. Boilerplate, duplicate findings, and keyword-only evidence fail. Attempt records
whose exact model readback is known must match the permitted low/standard options, including
`fastMode: false` when that option exists. Runtime model IDs remain catalog-discovered.
The amended complete source map is recorded in `frozen.json`; no quality starts have used
any prior or current map.

2026-10-12 parent integration amendment: model_policy now combines the isolated
full frozen-map guard and legacy Haiku thinking:false control with disabled-model
checks and native-child capability checks. Attempt records accept only the exact
low-effort/standard control shape or the catalog-supported thinking:false shape.
Actual launches still require the discovered exact catalog target and frozen map.
No additional model/canary/start slots are granted by this amendment.

### Coordinator ledger and transport capture

Before dispatch, the coordinator writes a prelaunch ledger containing the scenario, fresh
run ID, nonce, and hashes of every frozen input. The host records the accepted transport
response and observed task/conversation/run identities in a captured-transport ledger.
Keep both ledgers and the coordinator context outside the worker's writable scope. Run
`tools/captured_ledger.py prelaunch` before launch and `tools/captured_ledger.py capture`
after the host has captured the response. Each workflow/negative grader receives
`--prelaunch-ledger`, `--context`, and `--capture-ledger`; it verifies the prelaunch hash,
scenario/input binding, context/run/nonce, captured-record hashes, observed identities,
and actual output digests. A worker-supplied context without a separately captured,
matching ledger fails. A legitimate fresh run passes. Offline positive fixtures remain
synthetic and can be copied for local tests.

These hashes detect mismatched, stale, and copied contexts when the coordinator ledger is
held outside worker write access. They do not authenticate an owner or protect against a
privileged actor who can forge both ledgers and observations. The helper is a reusable
standard-library record/verification API and CLI; live host integration must capture the
actual prelaunch and transport records from T3 and keep their storage outside worker
scopes. Unit tests do not establish that live integration or provider compatibility.

The five-stage grader checks that the unreleased changelog states the seeded exact-amount,
monthly-report, spreadsheet-formula, and same-file-overwrite fixes. Its audit check requires
exactly two finding blocks: one citing seeded `io.py:24` with severity, formula reproducer,
and a fix in that block, and one citing seeded `cli.py:31` with severity, same-file export
reproducer, and a fix in that block. A missing severity or fix cannot pass via a keyword
elsewhere in the document.

### Owner amendment: Stage 1 benchmark repair5, 2026-10-12

This amendment preserves every earlier map, measurement, and start ledger. It fixes C11 to
require concrete unreleased entries for each seeded change, and C12 to require a seeded
location, severity, concrete reproducer, and fix inside each of the two distinct finding
blocks. Workflow and negative-start grading now cross-check fresh context against a
coordinator-owned prelaunch ledger and independently captured transport-record hashes,
including run identity, frozen input digests, output digests, and required observed IDs.
Fixed copied contexts fail; fresh matching synthetic run records pass. The ledgers are
trusted host evidence, not cryptographic owner authentication. A privileged writer that
can forge the host-owned ledgers can forge the evidence. No runtime provider IDs or live
execution claims are added. All 24 quality starts and the 24-start gate remain unchanged.

### S1b container amendment, 2026-10-12 (integrated after benchmark repair5; before any live start)

The stage compatibility shard records source provenance only. Every fresh
container starts with a deny-all model gateway and no model default in either
provider CLI configuration. The driver obtains the isolated server's catalog via
its supported MCP endpoint and self-minted OAuth PKCE client session, discovers one
exact Haiku and Luna target with the required low/standard options, and writes a
private read-only per-run target manifest. The gateway is then restarted against
that manifest before any model launch. The launch driver rejects unsupported live
schemas if they cannot transmit the explicit provider/model/options and runtime,
workspace, project and message fields.

The gateway accepts only Claude Messages and OpenAI Responses requests for those
manifest IDs. It requires low effort, pins Anthropic to `standard_only` and OpenAI
to `default`, and rejects unknown endpoints, malformed or duplicate-key JSON,
missing model IDs, deceptive IDs, high effort and priority service before opening
an upstream connection. Agent containers have only an internal network and cannot
route around the gateway. The outbound gateway verifies provider TLS certificates.
When the selected Haiku catalog entry exposes no fast-mode control, no fast-mode
option is sent; its request is still fixed to the documented standard-only API tier.
If the isolated catalog exposes only the older `thinking` boolean, freeze it as
`false` and reject API requests that attempt extended thinking; omission keeps
extended thinking disabled on that model.

### S1b container repair3 amendment, 2026-10-12 (before any live canary)

Start the isolated T3 server with `/bench/ws` as its current working directory and
pass `--auto-bootstrap-project-from-cwd` as a boolean flag. Initialize the synthetic
Git workspace before starting the server. If the supported project list is still
empty, create the project through the server's supported pairing-code OAuth flow
with a full-access client used only for that isolated setup operation. The no-model
project preflight verifies exactly one project points at `/bench/ws` before any
model dispatch. Canary parents remain `auto`/`default`.
The gateway maps API option enforcement from the private frozen target manifest;
runtime source files contain no model-version pins.

The V1 and V2 workspace preparation helpers have colliding import names during
serial test discovery. V2 tests load their helper under an explicit V2 module name
so both suites exercise their own implementations. The smoke helper records a
content-hash baseline after T3 startup so synthetic `.git` files are allowed to
remain untouched while helper writes are limited to the assigned task subtree.
The provider catalog's `canRunChildTask` capability is required for worker, child
and reviewer targets. Parent and canary targets still require an exact live family,
model and low/standard option match, but may use a provider without child capability.

### Owner amendment: container repair6, 12 October 2026

The explicit task-local limit revision 5 to 6 preserves attempts 0–5 and authorizes
one further finite canary per Haiku/Luna target. It changes no shipped limit, frozen
quality scenario or 24-start acceptance gate. Parent messages are read by message
type; child terminal evidence is captured from the calling parent's actual host tool
records instead of an outside OAuth client impersonating that parent. Provider
response model/usage observations are retained separately from transcript/native
visibility gaps. Expected non-forwarding websocket negotiation is separate from
security-policy rejection. All prior model and quality failures remain recorded.
No quality starts may proceed while any required live observation is missing.

### Owner amendment: repair7, 12 October 2026

The owner authorized one additional pass, retaining attempts0–6 and shipped limits. Container canaries add one finite native probe each and preserve exact target/options, transport completion and independent host observations. Token estimation is separate from inference usage. Benchmark adverse-review repairs strengthen existing C6 header/column checks and C8 with the frozen reference suite, refuse cold-brief facts and worker-owned ledgers, and return structured failure for malformed context. The prompt now discloses its report labels. Individual investigation/audit checks evaluate correct diagnoses; copied notes alone cannot satisfy the complete required gate. Coordinator ledger fixtures remain consistency evidence; actual captured live execution is a separate Stage6 gate. The24-start plan and acceptance requirements are unchanged; no quality start occurred before this amendment.

### Owner-authorized pass 8 amendment, 13 October 2026 AEDT

All attempts 0–7 remain retained. The 24-start plan and shipped defaults are
unchanged, with no quality start yet permitted. `frozen.json.files` is the current
map; each history entry retains the superseded map, and the amendment receipt
binds both maps explicitly. History is never rewritten to make an old map current.

The numeric investigation/review reproducer is computed from the frozen defect;
report templates disclose field labels without the expected numeric answer.
C13 requires a changed executable line in the amount parser plus separately
retained host review transport via `--review-context`, outside worker output.
The transport binds the actual low-cost reviewer target, candidate source hash,
owned task identity, successful terminal status and exact returned review text.
Synthetic positive fixtures verify this contract; they are not live provenance.
The actual host store and dispatch/catalog capture still require the independent
filesystem boundary and Stage 6 integration before acceptance.

Malformed context/prelaunch/capture records return a failed grade. Boolean model
options require booleans. No review or quality slot may start merely because the
local graders pass. Missing required transport, review, native permission proof,
or complete usage remains unverified or failed.

### Owner-authorized pass 9 amendment, 13 October 2026 AEDT

This amendment preserves attempts 0–8, every earlier map and ledger, shipped defaults and
the 24-start plan. C12 now requires each finding's fix to name its own mechanism: an
apostrophe or single-quote escape for the formula finding, and a path-identity check with a
refusal for the same-file finding. A shared keyword such as "prefix" cannot satisfy both.
The grader CLI refuses to execute candidate code unless it runs in a container that sets
`T3_BENCH_ISOLATED_GRADER=1`; that guard prevents accidental host execution and is not a
defence against a host user who forges it. Model-option checks reject non-boolean values
for boolean options instead of normalizing them. No quality start has run.

### Owner-authorized pass 10 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

C12 now classifies every finding block. A block counts only when it cites exactly one
seeded defect and carries that defect's evidence, severity, reproducer and fix: either
formula-only `io.py:24` or same-file-only `cli.py:31`. The audit passes only with exactly
one formula-only block and exactly one same-file-only block. A block citing both seeded
defects counts for neither, and a filler block fails the audit. The isolation guard now
sits on the execution path: `check()`, `Sandbox` construction and every `Sandbox.run`
refuse to execute workspace code unless the isolated grader container sets
`T3_BENCH_ISOLATED_GRADER=1` and provides `/.dockerenv`. Only offline tests over
repository-owned synthetic fixtures pass `trusted_synthetic_fixture=True`. Attempt records
with a null model readback still apply the low/standard policy to the requested options.
Workflow and negative-start regression tests mutate temporary copies, never frozen
fixtures. `plan.json` engineering grading names its required and informational check IDs,
the `--review-context` input and the isolated execution requirement.

Pass 9 receipt correction: the pass 9 receipt still bound the repair 8 pair at history
index 17. Pass 9 superseded map
`39a4430a9fe840a1c36e41bc24b972d2c5f4435c929ba4662a4b9989a93cfe8b`, which is bound only as
`history[17].replacement_map_sha256` because its file list was not retained, with map
`034e47bcb9a75651fd1684de57017a5f29e29889a4e111dcf27c154529256ca8`, stored as
`history[18].files`. `amendment_receipt.pass9` records that pair. `history[19]` retains the
pass 9 map as the map pass 10 superseded, and the receipt binds it to the pass 10 map. A map
digest is the SHA-256 of the `files` object serialized as compact JSON with sorted keys.

Superseded in-place text: before any start, four passages of the original protocol were
rewritten in place rather than amended. The original is the protocol committed in
`cedebed`, SHA-256
`c1232a40852b6b69a3b44b5c1a2eca33005e3008c864260cbff61de29b9ddca5`, which
`history[0].files["protocol.md"]` also records. The current wording under "Other workflows
and negative paths" and "Measurements" applies. The frozen grading, role-aware child
capability and repair3 amendments describe the replacements. The superseded passages were:

> Their fixtures and hidden checks are **not frozen yet**. Stage 5
> must build and freeze them, with this file amended, before Stage 6 starts any of them.

> **Missing delegation**: the bench
> instance exposes no child-capable target.

> - **Inference**: one model request, deduplicated by message ID, else request ID, across
>   all sources. Lines without either are counted alone and reported.

> Repeated snapshots are one inference.

### S1b container pass 10 amendment, 13 October 2026 AEDT

The model gateway now accepts only documented top-level request fields for each route:
Anthropic Messages, Anthropic Count Tokens and OpenAI Responses. Any other field is rejected
before an upstream connection and locks the gateway; the rejection event records field names,
never values. The allowlist comes from provider documentation and a no-model capture of field
names from the pinned Claude Code 2.1.296 and Codex 0.162.1 CLIs, run inside the bench image with
no network against a listener that refused every request. That capture added Codex's
`client_metadata`. Premium controls stay rejected: `speed`, `inference_geo`, premium
`anthropic-beta` or `openai-beta` tokens, non-standard service tiers, and enabled thinking or
non-low effort. A field the capture did not exercise still fails the canary closed.

Preflight must show that the running T3 server resolves its default and configured `claude` and
`codex` commands to the worker-UID shim. Canary acceptance reads the coordinator-only native
launch log and needs at least one new shim launch of the provider CLI under test; a missing,
unreadable or malformed log fails closed. Each app-owned child's projected thread and run
`modelSelection` must match the frozen target exactly; the parent's `delegate_task` input alone
is not enough.

The no-model smoke runs container-side positive controls (gateway reachability and
`host.docker.internal` resolution) alongside its negatives, and counts token-estimation forwards
as provider requests. It still does not prove general host-network isolation. A refused or
unsupported tracked continuation is recorded but never counts as a pass. The canary summary
rejects duplicate keys and non-finite numbers. An oversize provider stream is recorded as an
upstream failure. If a replacement gateway's identity cannot be recorded, containers matching the
run labels and exact name are removed and the command fails. Any provider non-2xx response still
locks the gateway, so a transient 429 ends that finite canary as unverified; it is not retried.

Clarification: negative starts use their own fixtures under `fixtures/workflows/negative-*`, as
`plan.json` records; the earlier sentence that they reuse the five-stage fixture describes the
scenario source, not the fixture path.

### Owner-authorized pass 11 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

C3 now sends every invalid amount, including exponent forms, to `total`, `report FILE --by
month` and `export`, and each must exit 2 with `error:` on stderr and empty stdout, as the
prompt already requires for every command. The frozen reference suite's invalid-amount test
covers the same three commands. C13's independent review now needs `parent_target` in the
review context: the implementing parent's target. The reviewer and parent targets must both
pass the cheap-target policy, differ in provider/model, and have known, different lineages.
Lineage is the policy family (`luna` for Codex, `haiku` for Claude); a recorded lineage that
disagrees with the family, a missing parent target or an unknown model fails. Workers run on
the start's provider, so the parent target stands for the implementing lineage. The review
source marker now also binds `README.md`, `CHANGELOG.md` and `notes/audit.md`, recording an
absent file as absent. It excludes `notes/review.md`, which carries the review itself.

`APE-FOLLOWUP-CORRELATED` requires the follow-up to be a new host-observed task: exactly one
host `research_followup` dispatch whose task ID matches the follow-up, whose recorded
`prior_task_id` matches the original task, and whose ID differs from the original task ID.
No other host dispatch may reuse the follow-up ID. The `workflow-ape` coordinator-context
seed records that predecessor.

`tools/usage.py` merges a same-identity inference seen in several sources by per-field
maximum, the rule already used within one Claude transcript, so a partial capture and its
resumed final copy give the same totals in either source order. Per-source totals are
computed after every source is read. A copy reporting a different model is a usage conflict:
it is listed under `aggregate.usage_conflicts` and makes `attribution_complete` false.

Receipt: `history[20].files` retains the pass 10 map
`0fd7c28881fd99df977b3ba857f9ffab7d15a966fd41636c521f59320df02b59`, which pass 11
supersedes. `amendment_receipt.pass10` keeps the pass 10 pair: `history[19]` and the pass 9
map `034e47bcb9a75651fd1684de57017a5f29e29889a4e111dcf27c154529256ca8`.

### S1b container pass 11 amendment, 13 October 2026 AEDT

The model gateway now checks nested tool definitions as well as top-level fields. Anthropic
Messages and Count Tokens accept only client tools with no `type` or `type: "custom"`; OpenAI
Responses accepts only `function`, `custom` and `local_shell` tools. A non-list `tools` value, any
provider server tool (web search or fetch, image generation, computer use, code execution or
interpreter, file search, MCP, tool search) and any unknown type are rejected before upstream,
lock the gateway, and are logged by tool type name only. The bench Codex configuration sets
`web_search = "disabled"` and turns off Codex 0.162.1's default-on `image_generation`,
`computer_use`, `fast_mode`, `ultrafast_mode` and `browser_use` features; an offline check in the
pinned image (no network, refusing listener) confirmed the configuration parses and those features
read false.

Host observation now requires every app-owned child thread to have at least one projected run, one
completed run, and no run outside completed, failed, interrupted or cancelled. No observed
descendant may have an active run, whatever a cached `task_status` says. The pinned T3 projects no
run rows for provider-native children, so the native probe records `native_runs_projected` (`none`
or a count) instead of claiming run evidence. It is accepted only with the completed subagent row,
`completedAt`, the exact input hash and the exact child-thread selection; any projected native run
must be completed with that selection. The canary summary rejects numeric overflow to infinity at
any depth. A manifest write error while recording the replacement gateway counts as a failed
recording, and label-and-name cleanup always runs, even if its receipt cannot be saved.

### Owner-authorized pass 12 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

`tools/usage.py` no longer merges derived Codex cumulative deltas by maximum. Every source is
read first. Cumulative `total_token_usage` snapshots that carry a session identity are then
grouped by session and event across sources, and each delta is taken against the event's
preceding snapshot from whichever source recorded it. A resumed tail that starts at a later
event therefore gives the same totals and context as the full capture, in either source
order. A snapshot with no earlier snapshot in any source counts from zero only when a source
not marked `resumed` starts with it and it is the session's only possible start: cumulative
counters only grow, so a larger unlinked first snapshot is a tail. Otherwise that inference's
usage and context are unknown, with a `cumulative_baseline_unknown` gap, and
`attribution_complete` is false. A manifest source may set `"resumed": true` when the executor
knows the capture continues an earlier session. Two sources reporting different snapshots or
different baselines for one event are a usage conflict (`cumulative_snapshot`). Per-call
`last_token_usage` and the Claude per-field maximum merge are unchanged.

`EG-COLD-BRIEF-OMISSIONS` no longer treats the absence of known answers as proof that the cold
reader is isolated. The cold brief must equal the frozen
`fixtures/workflows/workflow-elephant-goldfish/cold-brief-template.md`, now one of that
scenario's hashed inputs, with only its document and source references filled in: the names
`incorrect.md` and `source.md` and their SHA-256 digests. Any other text fails, including a
paraphrased predecessor finding. The fixture's `cold-brief.md` is the rendered template.

`BABY-NO-UNAUTHORIZED-POST` and `BABY-NO-UNAUTHORIZED-MERGE` now require host
`trace_coverage` to list `sidecar_post_calls` and `sidecar_merge_calls` respectively. An empty
call log without that coverage is unverified and fails, as `_no_implementation` and the
negative-start graders already require for dispatch coverage.

Receipt: `history[21].files` retains the pass 11 map
`598590155d51b6681ce7f4753b442686823b1cb16f09c73757c5749f8f0ee599`, which pass 12
supersedes. `amendment_receipt.pass11` keeps the pass 11 pair: `history[20]` and the pass 10
map `0fd7c28881fd99df977b3ba857f9ffab7d15a966fd41636c521f59320df02b59`.

### S1b container pass 12 amendment, 13 October 2026 AEDT

Canary acceptance now requires `assigned_helper_output_valid` to find
`canary/<provider>/task-1/helper.json` as a single-link regular file opened without following
links. Its resolved parent must be the physically assigned directory, and no symlink may exist
under `canary/<provider>/`. `smoke_helper.py` refuses symlinked outputs or ancestors below
`/bench/ws`; an offline run in the pinned image as the worker user over bind mounts confirmed a
symlinked output and a symlinked ancestor are both refused and nothing is written outside the
workspace. `workspace_write_scope_valid` fails on any added or changed symlink and on any symlink
inside the assigned directory. Every `resource-manifest.json` write is atomic: a same-directory
temporary file is fsynced, set to mode 0600, moved into place with `os.replace`, and the directory
is fsynced, so a failed write leaves the last good manifest intact and `down` keeps its cleanup
authority. `usage_complete` is true only when every inference row has `input_tokens` and
`output_tokens`; partial or absent usage is reported as `usage-partial` or `usage-absent` with the
observed counters kept.

### Owner-authorized pass 13 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

`tools/usage.py` no longer identifies a Codex event by its position in one capture. When a
session's `token_count` events carry no event ID, the event's identity is its cumulative
`total_token_usage` snapshot. Repeated identical snapshots collapse before anything is
numbered, so a capture with snapshots A, A, B and a copy with A, B align by value and count
two inferences in either source order. A session whose captures cannot be aligned this way
has unknown usage and context, with a `session_alignment_ambiguous` gap, and
`attribution_complete` is false. That covers per-call events with no cumulative snapshot in
more than one source, captures that mix explicit event IDs with snapshot identities, and a
snapshot that recurs after a different one inside a capture. A row with no stable identity
is still counted once per source, but `attribution_complete` is now false, because a copy of
it in another source cannot be recognised.

An unparseable, truncated, non-object or undecodable line in a usage source may have held
an inference. That source's totals, the totals of its parent, worker or unattributed group,
and, when sidechain usage was observed, the sidechain totals if any Claude source is
damaged are unknown. The parsed usage remains
as `known_lower_bound`, and each source reports `damaged_lines`. Damage in a parent source
also makes `peak_context` and every stage-boundary context unknown, with `known_max_context`
kept as a lower bound. `attribution_complete` is false. The frozen `parent.jsonl` fixture
contains a malformed line, so its parent totals, peak and boundary contexts are now unknown;
boundary selection is still tested on a temporary copy without that line.

`EG-COLD-BRIEF-OMISSIONS` now grades the input the host recorded for the cold reader, not
only the saved brief. The host context must trace `dispatch_calls` and record exactly one
`cold_read` dispatch by `elephant-goldfish/cold-reader`. Its task ID must be shared by no
other dispatch, and its whole `input` must be `{"task": <rendered brief>}`, where the
rendered brief is the frozen template with only the document and source references filled.
An absent, repeated or contaminated reader dispatch fails, even when every saved artifact
is unchanged. The scenario also requires the observed ID `cold_reader_task_id`: the reader
task named in `observation.json` must equal the host-recorded `cold_read` task.

Every workflow contract now lists `required_worker_dispatches`, equal to the plan's
`workers_expected` for that scenario. The grader requires host `dispatch_calls` coverage and,
for each required worker, at least one host-recorded dispatch naming that worker whose task
IDs belong to no other worker. The coordinator-context seed fixtures record those dispatches;
the babysitter and agent-tuneup seeds now list `dispatch_calls` in `trace_coverage`.

Receipt: `history[22].files` retains the pass 12 map
`074bf49d53f0f04d9fa4ed08027fb55527d01cdf73dc1800d2eab2cccb502935`, which pass 13
supersedes. `amendment_receipt.pass12` keeps the pass 12 pair: `history[21]` and the pass 11
map `598590155d51b6681ce7f4753b442686823b1cb16f09c73757c5749f8f0ee599`.

### S1b container pass 13 amendment, 13 October 2026 AEDT

The canary workspace check now records every entry below `/bench/ws` by type without following
links: directories, regular files with SHA-256, symlinks with their target, and FIFOs, sockets,
devices or other kinds. Any entry created, removed, modified or retyped outside
`canary/<provider>/task-1/` fails `workspace_write_scope_valid`; the only exception is creating
`canary`, `canary/<provider>` and `canary/<provider>/task-1` as directories. Links, special files
and unlistable directories also fail it, and the no-model smoke applies the same rule to
`smoke/task-1`. If T3 or a provider CLI creates its own directories in the workspace during a
canary, that canary fails closed.

Every Docker resource that `up` creates (image, both networks, bootstrap gateway, GitHub sidecar
and agent), and the replacement gateway, goes through one recorder that checks the exact name and
run labels and commits the immutable ID within three attempts; otherwise it removes the resource by
run labels and exact name and fails, so no running resource is left without cleanup authority. A
failure before `os.replace` leaves the previous manifest unchanged and records nothing; a
directory-fsync failure after `os.replace` counts as committed and is noted as
`manifest_durability_uncertain`. `down` treats a recorded ID that Docker inspect reports as missing
as `already-absent`; the matched not-found messages were checked against the pinned Docker daemon.
The gateway prints only JSON objects, so any other line in its log is damage: it counts as a
possible provider request in the no-model smoke, as a rejection for `gateway_policy_clean`, and
makes model observations unverified.

### Owner-authorized pass 14 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

`tools/usage.py` now identifies a Codex cumulative snapshot by its required counters only:
`input_tokens`, `cached_input_tokens` and `output_tokens`. Optional counters such as
`total_tokens` and `reasoning_output_tokens` are not part of identity. Two copies of one
session, one recording those optional counters and one omitting them, therefore align and
count each request once, in either source order. When both copies report the same counter
with different values, the snapshot is a usage conflict (`cumulative_snapshot`) and
`attribution_complete` is false. A repeated snapshot collapses only when it is identical or
complete and agrees on every counter both copies report. A session captured by several
sources whose snapshot lacks a required counter cannot be aligned and has unknown usage.

A cumulative delta counts as one inference only when nothing unread lies between its two
snapshots. When a damaged line, or a `token_count` without `total_token_usage`, falls between
them, the delta may cover several requests. That inference's usage and context are then
unknown, with a `cumulative_interval_unknown` gap. It adds nothing to `known_lower_bound` or
`known_max_context`. The same holds for a first snapshot preceded by a damaged line: it is
not taken as usage from zero. Another source that records the preceding snapshot still
supplies the baseline; otherwise the gap is `cumulative_baseline_unknown`. Per-call
`last_token_usage` that disagrees with the cumulative counters may leave requests uncounted.
Each source reports `usage_mismatches`. When it is above zero, the totals of that source and
of its group, and the parent peak and boundary contexts if the source is a parent, are
unknown above their lower bounds, and `attribution_complete` is false.

A stage boundary's last parent inference is no longer chosen while any parent inference has
a missing, invalid or timezone-naive timestamp, even when older inferences are orderable,
because that inference may fall on either side of the boundary. Every boundary's inference
and context are then null with a reason. The same applies when parent inferences from
different sources share the last instant before the boundary. Each case adds a
`boundary_order_unknown` gap and makes `attribution_complete` false, as does an invalid
boundary timestamp. Usage totals and the peak are unaffected. A source's `first_at` and
`last_at` are ordered by instant, not by string. They are unknown, with a reason, when the
source is damaged, has a per-call mismatch or holds an unorderable timestamp.

`APE-RO-SOURCES` now requires host `trace_coverage` to list `source_access_events` and the
host to record those events as a list before the absence of write or delete events counts
as read-only access. The observed reads and their hashes are still required. A unique
follow-up dispatch in `APE-FOLLOWUP-CORRELATED`, and the host-observed follow-up and cold
reader task IDs, now require `dispatch_calls` coverage. `_no_implementation` requires both
`dispatch_calls` and `stage_transitions` to be covered and recorded as lists; a covered route
with no recorded log no longer counts as empty. Coverage must be a list in every grader, so a
coverage map such as `{"dispatch_calls": false}` no longer satisfies `N4-ZERO-WORKER-DISPATCH`
or `N8-ZERO-REVIEWER-DISPATCH`.

Receipt: `history[23].files` retains the pass 13 map
`985c2562434bdea7ac27757d8ae686c2c9fd6740de40a3d3c838b03c42b5eeec`, which pass 14
supersedes. `amendment_receipt.pass13` keeps the pass 13 pair: `history[22]` and the pass 12
map `074bf49d53f0f04d9fa4ed08027fb55527d01cdf73dc1800d2eab2cccb502935`.

### S1b container pass 14 amendment, 13 October 2026 AEDT

Workspace confinement now compares mode bits, owner UID and GID for every entry and for the
workspace root, plus the link count for regular files. Any metadata change outside the assigned
path fails the canary and the smoke; inside it, among entries that already existed only the helper
output's regular-file record may change. Before creating a resource, `up` commits a write-ahead
intent (kind, exact name, run labels), and every cleanup receipt keeps the matched immutable IDs.
`down` reconciles every intent and receipt by exact run labels and name (lookup, removal, confirmed
absence), then requires an empty label-only lookup, and reports `cleanup-failed` until both hold.
Docker cleanup commands are bounded by a timeout, and a timeout counts as a failed command. An
unavailable container log is missing evidence, never a zero count: the smoke fails, a canary is
blocked before its slot is used, and an unavailable gateway log after a canary is recorded as an
unverified model audit. The preflight needs every named check present and exactly true.

### Owner-authorized pass 15 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

`tools/usage.py` no longer rebuilds Codex usage from cumulative counters case by case. It
checks each Codex session against a fixed list and publishes that session's per-call usage,
totals and contexts only when every condition holds:

1. No source that carries the session has a damaged, undecodable or non-object line.
2. Every `token_count` from the session's first usage report on has `info.total_token_usage`
   and `info.last_token_usage`, each with `input_tokens`, `cached_input_tokens` and
   `output_tokens` as non-negative integers. A `token_count` whose `info` is null or missing
   before the first usage report claims no usage. After that report it makes the session unknown.
3. Inside each capture, a repeated snapshot collapses only when every reported counter,
   optional ones included, and the event ID are identical. A repeat that differs in any of
   them is a `usage_conflict`. Apart from such repeats, no cumulative counter may decrease.
4. The session's first snapshot proves a zero start: its `last_token_usage` equals its
   `total_token_usage`, and a capture not marked `resumed` starts with it.
5. Every snapshot's `last_token_usage` equals the difference from the previous distinct snapshot.
6. Across captures, the snapshots form one increasing sequence, each capture is a contiguous
   run of it, and a snapshot that two captures record is identical in every counter and event ID.

Each inference is then one snapshot, with `last_token_usage` as its usage and its
`input_tokens` as its context. Captures of a session align by session and required counters.
When a condition fails, the session's usage, totals and contexts are unknown and a gap names
each failed condition: `session_damaged`, `token_count_without_usage`, `usage_conflict`,
`counter_decreased`, `ambiguous_repeated_snapshot`, `cumulative_baseline_unknown`,
`per_call_vs_cumulative_mismatch` or `session_alignment_ambiguous`. Every source that carries
the session then has unknown totals, a parent source also makes the peak and boundary contexts
unknown, and `attribution_complete` is false. The session's rows are counted once per capture.
`known_lower_bound` and `known_max_context` keep only rows proven on their own: complete, with
nothing unread before them, and either a zero start or exactly the preceding snapshot plus
their per-call usage. Those rows come from the one capture with the most proven rows, so two
copies of a request are never summed. Codex rows without a session identity form a session
of their own capture. A repeated snapshot there may be a copied line or a new session, so it
makes that session unknown.

Every change is stricter than pass 14. Cumulative-only captures, which pass 14 counted from
zero, are unknown. Copies of one session that differ in an optional counter, which pass 14
aligned, are a conflict. An undamaged copy no longer repairs a damaged capture of the same
session. A per-call row that disagrees with the cumulative counters no longer adds to the
floor. In the frozen parser fixtures, the per-call worker's capture ends with a null `info`
after usage, so that worker is unknown above a floor of 2,500 input tokens. The
cumulative-only worker's floor falls from 2,800 input tokens to 0.

Receipt: `history[24].files` retains the pass 14 map
`47f33c892c26102645b691503203f3fdb28ce42d459aaf35e5bbd1f7521af2d9`, which pass 15
supersedes. `amendment_receipt.pass14` keeps the pass 14 pair: `history[23]` and the pass 13
map `985c2562434bdea7ac27757d8ae686c2c9fd6740de40a3d3c838b03c42b5eeec`.

### S1b container pass 15 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan, and changes no budget, default or quality gate. No quality
start has run.

A run's first committed manifest is a write-ahead intent: `created_resources` may be empty
while `pending_resources` names each resource the run is about to create, and
`unrecorded_resources` records objects Docker made before the intent was proven. `down`
reads a missing `created_resources` map as empty, so a legacy pending-only manifest is
reconciled to confirmed absence rather than refused, and it removes an image or container
that exists only as a labelled orphan. A recovery map of the wrong type still blocks `down`
before it opens any Docker connection.

Helper execution and host-recorded file changes are attributed to the declared primary child
thread. A helper run counts only when exactly one matching command execution appears in the
whole thread tree, inside the primary's thread, completed with exit status zero; a run
observed in a boundary-reader, native-probe, parent, grandchild, follow-up or unknown thread
fails. Every app-owned subagent row for the task must be parent-owned and agree with the
parent's task status on one non-primary child thread. A file change recorded against any
thread other than the primary now fails closed, and a missing file-change list fails closed.
The canary binds both the helper and the recorded writes to the primary task.

The crash-consistency sweep kills setup before the first write and at every role's create
command, before and after Docker made the object; covers the boot-time label lookup and the
`--rm` provenance probes; covers all six `configure_gateway` crash points; and runs a `down`
killed midway then finished by a later `down`. Each ends `stopped` with an empty owned set,
and until the objects are confirmed absent the receipt stays `cleanup-failed`.

Live risk: a parent that writes any file through T3's edit tool, or that runs the helper
itself, now fails the canary.

### Owner-authorized pass 16 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run.

Codex usage keeps session-wide replay uniqueness. Inside `check_segment`, a complete
snapshot whose required-counter key repeats a key already seen in the same run marks the run
broken, and a cumulative counter that decreases marks it broken too. From that point no later
row, including one that copies an earlier request, is ever proven, so a replayed
`A,B,A,B` capture never re-proves the copied suffix. `known_lower_bound` and
`known_max_context` therefore count only the unique proven rows: the frozen `A,B,A,B` floor
falls from an inflated 300 to the true 200 input tokens, with the output floor at 20.

An empty `token_count` is judged across the whole session, not capture-locally. `resolve_codex`
passes each capture the session's `(has_usage, first_instant)` computed over every capture that
carries the session, and an empty report is exempt from the usage-less rule only when it
provably precedes every usage report; otherwise it is `token_count_without_usage`. A resumed-only
capture whose only `token_count` is usage-less and later than (or not orderable against) the
session's usage therefore leaves that session's totals, peak and boundary contexts unknown in
both manifest orders. An empty report that provably precedes every usage report, resumed or
not, still claims nothing.

An already-launched, pre-prepared uncertain follow-up stays reconcilable after its stage is
invalidated. When a host observation adopts a prepared follow-up whose request is the one the
recorded uncertain follow-up dispatch names, the observation is accepted even though the
stage revision has made the task `stale`, and the task keeps `inputs_stale` and `stale` status
rather than being revived. A follow-up that was prepared but never launched uncertainly, or one
whose identity, target, scope or frozen correlation differs, is still refused as a fresh
stale-authority launch, and the execution budget still bounds adoption.

Accepted-but-uningested terminal work is an unresolved obligation. A task whose owned host
handle is terminal with `result_available` and no pending child runs, but whose request has no
ingested execution-history row, now blocks slot removal and task-contract changes until its
result is ingested. Accepted work can no longer be removed or replaced to reset the slot's
inherited execution budget or to discard a late result, and a late adverse major result blocks
replacement until it is dispositioned. Observation-first and ingestion-first orders reach the
same obligation.

Receipt: `history[25].files` retains the pass 15 map
`fd2a5ef774e05629bca5d4564173cafb93ba6a266b11e6b32d0dc21ee08cd27f`, which pass 16
supersedes. `amendment_receipt.pass15` keeps the pass 15 pair: `history[24]` and the pass 14
map `47f33c892c26102645b691503203f3fdb28ce42d459aaf35e5bbd1f7521af2d9`.

### S1b container pass 16 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan, and changes no budget, default or quality gate. No quality
start has run.

The finite canary role authority now freezes the complete host-produced assignment, not just a
marker line and scope substring. `canary_role_protocol` carries, for each app child, the exact
`task` string and, for the provider-native probe, the exact `prompt` string, alongside the
marker line and scope token. `frozen_protocol_is_valid` rejects a role whose frozen template is
missing, empty, or does not carry its own declared marker line and scope token. The canary
prompt embeds every exact literal verbatim and instructs the parent to dispatch each task byte
for byte with no added, removed, quoted, indented or reformatted text.

A captured `delegate_task` input classifies a role only when its `target` equals the frozen
target with identical raw types (a boolean option is never an integer option) and its `task`
equals the complete frozen literal. A task that quotes the marker or scope token and adds
contradictory, extra or reformatted text therefore no longer classifies as that role. The
captured provider-native subagent row must carry `prompt` equal to the frozen native prompt
exactly; a missing projection fails closed. Missing, duplicated, conflicting, quoted,
extra-text, mis-scoped or type-confused assignments continue to fail the canary, and the
final report, thread ownership alone and worker-written receipts are still never used to
classify a role.

Live risk: the frozen assignment is matched byte for byte, so a live parent that reformats or
quotes even the exact task text now fails the canary.

### Owner-authorized pass 19 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt (0 through 18), map, ledger and amendment,
the shipped defaults and the 24-start plan. No quality start has run. The owner raised the
pass limit to 19 and authorized passes 17, 18 and 19. Pass 17 ended without a source
change. Pass 18 kept the container and Stage 3 repairs described here; its benchmark slot
failed with a connection reset before any edit, so pass 18 changed no frozen bench-v2 file
and recorded no map. Pass 19 is the final authorized pass.

Claude copies of one inference are now compared the same way inside a capture as across
captures. `parse_claude` records every repeated `message.id` (else `requestId`) whose model
differs from the first copy's model, with a missing model read as `"unknown"`, exactly as
`merge_duplicate` compares a copy from another source. `summarise` reports each such copy
as a `usage_conflict` gap and a `usage_conflicts` entry with `fields: ["model"]` and the
capture as both `source` and `first_source`, so attribution is incomplete. Before this, two
rows sharing an identity, a timestamp and equal usage but naming different models were
published as one complete inference under the first model when they sat in one file, and
as a conflict only when they were split across files. The count of conflict entries is the
same in both layouts when the first copy is read first. Agreeing copies, copies that both
lack a model, partial usage merged by per-field maximum and `<synthetic>` rows stay
complete; sidechain copies are compared the same way; distinct identities are never merged
by timestamp, usage or model. The Codex session validator and its floors are unchanged.

Unread terminal work stays an obligation in every lifecycle path. A task whose owned host
handle is terminal with `result_available` and no pending child runs, but whose request has
no ingested execution, blocks acceptance (`_pending` and `_check_slots`), a charged retry,
follow-up preparation, slot removal or replacement, and (from pass 19) fresh preparation:
re-preparing the launched request after a policy-only revision would otherwise clear its
stale inputs and let a result produced under the superseded policy be accepted. A late
result of an owned request stays importable after a budget or policy change, is charged on
import, stays `stale` when its inputs were invalidated, and keeps its findings.

Already-launched work stays recoverable without granting fresh authority. An accepted
observation of the uncertain original request, or a follow-up observation of the recorded
uncertain follow-up request with its frozen parent, target, scope and prepared brief, is
accepted after a policy narrowing or exhausted budget, after input invalidation, and after
`cancel` or `discard`. A live discovery is recorded as live for cleanup and a terminal one
is then reconciled against the recovered handle. Cancellation and discard intent are kept;
a fresh, uncorrelated or re-targeted launch is still refused, and recovery reopens neither
retry nor follow-up preparation.

Receipt: `history[26].files` retains the pass 16 map
`9e0daa1f9267e8c11d49a5bcf13a6b4183850f7effe96dc506aff29a5a3d6b76`, which pass 19
supersedes. `amendment_receipt.pass16` keeps the pass 16 pair: `history[25]` and the pass 15
map `fd2a5ef774e05629bca5d4564173cafb93ba6a266b11e6b32d0dc21ee08cd27f`. No map was recorded
for pass 17 or pass 18.

### S1b container pass 19 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt, map, ledger and amendment, the shipped
defaults and the 24-start plan, and changes no budget, default or quality gate. No quality
start has run.

Pass 18 serialized every gateway lock writer (policy, endpoint and method rejections and a
non-2xx provider response) and the single upstream admission point on one mutex, so a
request whose body was still being read when another request locked the gateway is
refused before any provider connection. Pass 19 closes the remaining gap: admission
returned before the request's `forward-started` event was written, so a parallel lock could
be logged before that start. Admission now refuses the request or writes its
`forward-started` event inside the same critical section. Every recorded start therefore
precedes any lock, no request is admitted after a lock, and a refused request records no
start and never reaches the provider. The provider connection and the SSE relay run after
the mutex is released, so a slow upstream never blocks a lock writer.

Continuation dispatch targets are compared with type-strict equality everywhere they are
checked: the continuation launch against the original dispatch, each owned task against
the frozen target, and (from pass 19) the resumed continuation's `model` and
`providerInstanceId` against the launch target, which must be strings.

Live risk: the start record is written while the mutex is held, so a stalled log consumer
delays lock writers just as it already delays every handler's log line.

### Owner-authorized pass 20 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt (0 through 19), map, ledger and amendment,
the shipped defaults and the 24-start plan. No quality start has run. The owner raised the
pass limit to 20 and authorized pass 20 alone; it repairs one benchmark finding and changes
no budget, default, model target or quality gate.

Codex copies of one cumulative snapshot are now compared the same way inside a capture as
across captures. `parse_codex` collapses a repeated snapshot (same `total_token_usage`,
`last_token_usage` and event ID) of an identified session, as before. From pass 20 it also
compares the model in force at the repeat (the latest `session_meta` or `turn_context`
model, else `"unknown"`) with the model of the first copy's row, exactly as
`merge_duplicate` compares a copy from another source, and records every difference on
that row. `summarise` reports each one as a `usage_conflict` gap and a `usage_conflicts`
entry with `fields: ["model"]` and the capture as both `source` and `first_source`, so
attribution is incomplete. Before this, a session that reported one snapshot under model A,
switched to model B and repeated the snapshot was published as one complete inference
under A when both copies sat in one capture, and as a conflict only when they were split
across captures. Usage is unchanged: the copies still count as one inference, and the
session validator, alignment, floors, damage accounting and duplicate counts are untouched.
Agreeing copies and copies that both lack a model stay complete, a `turn_context` without
a model keeps the session's model, and a new snapshot after a model switch is a new call by
the new model, not a conflict. Repeats without a session identity are still kept as
ambiguous rows. The pass 19 Claude comparison is unchanged.

Receipt: `history[27].files` retains the pass 19 map
`003958833f88b812f78f76396e4135249ec63d9c76c5191bd68c12237175c1d2`, which pass 20
supersedes. `amendment_receipt.pass19` keeps the pass 19 pair: `history[26]` and the pass 16
map `9e0daa1f9267e8c11d49a5bcf13a6b4183850f7effe96dc506aff29a5a3d6b76`.

### Owner-authorized pass 21 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt (0 through 20), map, ledger and amendment,
the shipped defaults and the 24-start plan. No quality start has run. The owner raised the
pass limit to 21 and authorized pass 21 alone; it repairs two benchmark findings and changes
no budget, default, model target or quality gate.

`EG-CORRECTIONS-CITED` now requires exactly one correction row for each seeded fact and no
other row. Each row must give the value stated in `source.md` and cite `source.md` with its
SHA-256. Before pass 21 the check only asked that some row for each fact be correct, so an
artifact that also listed the seeded wrong value (`fact-rate` 0.20 beside 0.25) passed in
any row order, even with truthfully captured output bytes. An extra row now fails the check
whether it contradicts the correct row, repeats it exactly or names an unseeded fact. A
missing, wrong, uncited or non-object row, or a `corrections` value that is not a list, also
fails. The two frozen fixture rows pass in either order. Every other check and the
captured-output bindings are unchanged.

`attempt_record.validate` returns errors for a malformed typed model readback instead of
raising. A non-string `model_as_read_back.model_id` already failed the schema, but the policy
check then passed it to a regular expression, which raised `TypeError`, and the CLI printed a
traceback. It now matches no permitted tier, so the record is reported invalid with exit 1.
A non-string requested `model_options.provider_instance_id` without a readback is likewise an
error rather than an unhashable lookup. Exact cheap-model records and the false/zero, premium
and unknown-readback refusals are unchanged. One case was reported twice, as
R20-benchmark-shard-4-01 and R20-benchmark-shard-3-02; both IDs are retained.

Receipt: `history[28].files` retains the pass 20 map
`8c429d47572c14daed096e8337adbdb681c41670090da204582d6052d01677bd`, which pass 21
supersedes. `amendment_receipt.pass20` keeps the pass 20 pair: `history[27]` and the pass 19
map `003958833f88b812f78f76396e4135249ec63d9c76c5191bd68c12237175c1d2`.

### Owner-authorized pass 22 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt (0 through 21), map, ledger and amendment,
the shipped defaults and the 24-start plan. No quality start has run. The owner raised the
pass limit to 23 and authorized passes 22 and 23; pass 22 repairs two benchmark findings and
changes no budget, default, model target or quality gate.

`usage.parse_codex` no longer carries a model from one Codex session into another. Before
pass 22 the model was capture-wide state: when a new session's `session_meta` named no model,
that session took the previous session's model. A later copy of the same snapshot naming
that model then looked consistent inside one capture, while the same records split across
captures reported an unknown-versus-known model conflict. A newly opened session now starts
with only its own model evidence (`unknown` if none), so every packaging reports the same
conflict. Within one session a model-less `turn_context` or repeated `session_meta` still
keeps that session's model, and an explicit model change is still a new call by the new
model. Deduplication, counters, floors and null reasons are unchanged. Reported as
R21-benchmark-shard-2-01.

`attempt_record.validate` treats every JSON integer as a finite number without converting it
to a float. Before pass 22 a valid record whose `metrics.wall_seconds` was a 1001-digit
integer raised `OverflowError`, and the CLI printed a traceback. Such a record is now judged
like any other: it is valid if every other field is, and a negative value is below the
minimum. Non-finite floats and booleans are still not numbers, and the exact cheap-model
policy is unchanged. Reported as R21-benchmark-shard-3-01.

Receipt: `history[29].files` retains the pass 21 map
`20c0c60b49a02787bc9eec195a11cdca82e8bc4c43aa790d9a7f8ca826154f4c`, which pass 22
supersedes. `amendment_receipt.pass21` keeps the pass 21 pair: `history[28]` and the pass 20
map `8c429d47572c14daed096e8337adbdb681c41670090da204582d6052d01677bd`.

### Owner-authorized pass 23 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt (0 through 22), map, ledger and amendment,
the shipped defaults and the 24-start plan. No quality start has run. Pass 23 is the second
of the two passes the owner authorized when raising the pass limit to 23; it repairs one
benchmark finding and changes no budget, default, model target or quality gate.

`usage.summarise` reports each source's `sha256` over the exact bytes its single parsing
read consumed. Before pass 23 it parsed the capture, then reopened the path and hashed a
second read. A transcript appended or replaced between the two reads was published with the
old usage, context and boundary attribution but the new file's hash, which named a capture
with different totals. `records` now feeds every byte it reads, including damaged,
unparseable and undecodable lines, to an optional digest that `parse_claude` and
`parse_codex` pass through; the file is no longer reread for hashing. Both parsers keep
their two-argument form. Totals, floors, null reasons, context, boundaries, deduplication,
ownership, conflicts and per-session model evidence are unchanged, and a stable file has
the same hash as before. Bytes written after that read are not described by the summary.
Reported as R22-benchmark-shard-2-01.

Receipt: `history[30].files` retains the pass 22 map
`3f5293b175df63280fbf3c04597099da9107ef7881b7c7a7b1b53217335b4a24`, which pass 23
supersedes. `amendment_receipt.pass22` keeps the pass 22 pair: `history[29]` and the pass 21
map `20c0c60b49a02787bc9eec195a11cdca82e8bc4c43aa790d9a7f8ca826154f4c`.

### Owner-authorized pass 25 amendment, 13 October 2026 AEDT

This amendment preserves every earlier attempt 0-24, map, ledger and amendment, the shipped
defaults and the 24-start plan. No quality start has run. The owner raised the pass limit
from 24 to 25 for one repair of one benchmark finding. Pass 24 was review-only and changed
no frozen file, so the pass 23 map stayed current through it. This pass changes no budget,
default, model target or quality gate.

C12 used to check each audit `Fix:` field for keywords. A field naming the mechanism
passed even when it rejected the fix. For example, `Fix: Never add an apostrophe; leave
dangerous cells untouched.` scored as the formula fix, and `Fix: Never reject samefile paths;
always overwrite the input.` scored as the same-file fix. Now the whole field must match one
of two affirmative sentences that the fixture prompt discloses:
`[`func`] prefix(es) dangerous [text] cells with an apostrophe.` for the formula finding, and
`[`func`] check(s)|compare(s) [paths with] `os.path.samefile` and refuse(s) the output
[before opening it].` for the same-file finding. Negated, opposite, swapped, qualified,
contradictory and unsupported wording fails closed. The reference audit already uses the
supported sentences. C12 scores what the fix states, not whether the code does it. C6, C7
and C8 grade behaviour. Citations, severity, evidence, reproducers, the rule of one block
per defect and the C13 review check are unchanged. Reported as
R24-benchmark-range-shard-2-01.

Pass 25 review then found that C12 matched only the first `Fix:` line, so a second `Fix:` line
or an unlabelled continuation line could contradict an accepted fix. C12 now splits each
block into labelled fields; a line without a known label continues the field above it.
`Finding`, `Severity`, `Evidence`, `Reproducer` and `Fix` must each appear exactly once,
and the whole continued `Fix` field must match a supported sentence. The prompt states this
rule. Reported as R25-benchmark-range-shard-1-01, -2-01, -3-01 and -5-01.

Receipt: `history[31].files` retains the pass 23 map
`1279d4741bc967ae3855d01a2772ef60aba6df79d1b47a88951e4b037c831120`, which pass 25
supersedes. `amendment_receipt.pass23` keeps the pass 23 pair: `history[30]` and the pass 22
map `3f5293b175df63280fbf3c04597099da9107ef7881b7c7a7b1b53217335b4a24`.
