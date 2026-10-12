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
start per provider. Their fixtures and hidden checks are **not frozen yet**. Stage 5
must build and freeze them, with this file amended, before Stage 6 starts any of them.
Each must exercise both of its plugin's specialised workers. The ape start includes one
declared same-scope follow-up slot. It must show a new task ID in the same conversation,
an unchanged original result and delta-only input where the host permits continuation.
Otherwise it uses the fresh fallback and leaves continuation unverified.

Negative starts reuse the five-stage fixture. **Missing delegation**: the bench
instance exposes no child-capable target. The coordinator must run every stage
directly, with the same scope, counters and gates, and record a visible fallback marker
per stage. **Unavailable required review**: no reviewer target satisfies the routing
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

- **Inference**: one model request, deduplicated by message ID, else request ID, across
  all sources. Lines without either are counted alone and reported.
- **Parent context per inference**: input including cached input
  (`input + cache_creation + cache_read` for Claude JSONL; `input_tokens` for Codex,
  which already includes cached input). Report peak and stage-boundary sizes separately
  from output and cumulative totals. Native sidechain lines are excluded and reported
  as unattributed.
- **Counters**: Codex per-call usage is `last_token_usage`, otherwise consecutive
  differences of cumulative `total_token_usage`. Repeated snapshots are one inference.
  A decreasing counter makes that inference unknown.
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
