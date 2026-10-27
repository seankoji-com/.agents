# Architecture

Substantive public commands use a scoped upfront agreement after inspecting context. It binds the completion target, destinations, exact work/review chains and options, authority and limits to the existing selection and immutable briefs. The manifest operation inventory distinguishes substantive, continuation and direct controls. Endpoint observations remain separate from source readiness and live compatibility. See the [runtime agreement](https://github.com/seankoji-com/.agents/blob/main/shared/upfront-agreement.md).

agents has three execution paths. Instructions guide the current agent. Local
helpers do deterministic work. T3 owns delegated tasks and browser/PR interactions.
The repository does not implement another model client, task scheduler or dispatch loop.

<!-- inline-svg: assets/architecture.svg -->

## Package boundaries

| Directory | Responsibility | Dependency rule |
| --- | --- | --- |
| `skills/<name>/SKILL.md` | Canonical body and human-facing frontmatter | Pinned before helper-backed execution |
| `plugins/<name>/` | Routing manifest, playbooks, worker definitions, helpers, validators, templates | May use the shared runtime contract and core |
| `shared/` | T3 contract, whole-job protocol, worker registry, job and acceptance helpers, result parser, optional learnings | Standard library; no provider SDK or executable orchestration |
| `shared/agents/` | Worker boundaries, version-1 contracts and the separate compact-v2 brief schema | Data and contracts only |
| `core/` | imps run state, generic job storage, atomic writes, evidence, readiness | Python standard library; no plugin imports or vocabulary |
| `bin/` | Source development entry and stable-launcher delegation | Operational commands use the installed resolver |
| `scripts/` | Source resolver, snapshots, receiving, adoption and site tooling | Runtime is standard-library Python |
| `packaging/` | Retained historical Homebrew formula template | No new project Brew publishing |
| `tests/` | Deterministic regression tests and fixtures | No paid models or live GitHub mutations |
| `bench/` | Frozen benchmark protocols, fixtures and graders | Not installed; live runs need separate authorization |
| `conformance/` | Dated live-provider observations and the pre-merge review rounds under `review/` | Separate from unit-test success |
| `migration/` | Source provenance and the issue #28 compatibility map | Data for maintainers, not agent instructions |
| `docs/design/` | Design notes, including the `imps-t3` discovery, spec and handoff that shaped version 1 | Project documents, not executable instructions |
| `docs/` | Human guides and GitHub Pages source; the field guide data and bundled fonts | Documentation dependencies are build-time only |
| `overrides/` | MkDocs Material templates for the homepage and page metadata | Reads only `config.extra` filled by the site hook |
| `launch/` | Announcement drafts and repository-settings commands | Not installed, not published |

## Progressive instruction loading

An entry is a routing document, not a book. The agent reads the shared T3 contract
once and then the requested playbook. Helpers are invoked by path; their source is
loaded only when needed for inspection or debugging. Entry budgets are tested.

This reduces routine context use without hiding the behavior. All instructions ship
as readable files, and all deterministic decisions have local source and tests.

## Whole jobs

imps, ape, plan, babysitter and agent-tuneup run substantive multi-stage
work as one job. The main agent is the coordinator. It plans the whole job, keeps the
requirements and decisions, dispatches each stage to a fresh T3 task, reads the
result and decides acceptance. A worker completes one slot and returns one structured
result. It cannot dispatch, accept its own work or widen its authority.

`doctor`, `status` and list operations stay direct. They never create a job or
launch a worker. A single bounded change can also stay direct.

```text
plan job → prepare brief → delegate_task → completion → ingest result
                ↑                                            │
                └── repair (pinned limit) ←── reject ── validator ┘
                                            accept → next stage → final gate
```

The agent-facing protocol is
[`shared/job-coordination.md`](https://github.com/seankoji-com/.agents/blob/main/shared/job-coordination.md);
field-level rules and limits are in
[`shared/agents/jobs-contract.md`](https://github.com/seankoji-com/.agents/blob/main/shared/agents/jobs-contract.md).

### Job state

Jobs live in `$XDG_STATE_HOME/agents/jobs/<job-id>/` (default
`~/.local/state/agents/jobs`), or under an explicit `--state-root`. Never put
them inside the target repository. Files are private, replaced atomically and
written under a process lock.

| Path | Contents |
| --- | --- |
| `job.json` | Plan, requirements, verbatim constraints, separate action authorization, package and worker pins, counters, task handles, decisions, blockers, metrics |
| `overview.json` | Full stored overview; the pinned CLI adds fresh coordination metrics and bounded `--compact` resume pages |
| `briefs/` | One immutable, self-contained brief per task attempt |
| `brief-authority/` | Private full authority objects for compact attempts; never worker read references |
| `results/` | Validated worker results or artifact envelopes |
| `acceptance/` | Hash-chained validator receipts |
| `artifacts/tasks/<task-id>/` | The only place a worker may write job evidence |

`job.json` records coordination facts. It does not decide readiness; only
validator receipts do. Editing an accepted flag cannot promote a stage.

### Briefs and results

`prepare` writes a brief and prints only its path, SHA-256, size and provenance.
The worker reads that file and stops if the hash differs. Cold readers get only the
document and their procedural instructions, never the job objective or other
findings.

New jobs can explicitly select `policy.worker_brief_transport:
"worker-brief-compact-v2"`. The default stays `worker-brief-v1`. Compact preparation
uses the same worker IDs, task lifecycle and acceptance gates. T3 still owns dispatch.

A compact file starts with `T3-COMPACT-BRIEF/2`, followed by one JSON header line,
the `INLINE PROCEDURE (UTF-8)` marker, and the literal approved procedure. Required
result schemas and applicable full planning rubrics stay inline. The header binds
task authority, scope, requirements, evidence, stops, snapshot, revision, producing
selection/options and the retained procedure. It carries no full pins, model catalog,
other worker definitions or pointer to the private authority file. Cold readers gain
no history or reference reads; their existing extra-context refusal remains binding.
An executor assigned a native gate receives that helper's exact argv, hash and
gate arguments, without a package or registry read grant.
Required task-specific planning rubrics also stay inline. A rubric already present
verbatim in the definition is identified there, without a duplicate copy or file
read grant. Additional procedural text remains separately measurable.

The dedicated v2 schema validates the decoded projection. Admission hashes the
exact transmitted file, verifies the private coordinator reference, reconstructs
the current authority and projection, and compares exact bytes. Its effective
correlation hash still means canonical decoded content with only
`effective_brief_sha256` omitted. The separate file hash includes every byte.
Results retain `worker-result-v1` and `schema_version: 1`; the transport's version
does not change result semantics. Unknown or mixed formats refuse. Full canonical
definitions, original schemas, existing jobs and old pinned packages keep v1.

A result is exactly one JSON object that matches
`shared/agents/worker-result.schema.json`, or a short envelope that points to a full
result artifact. The parser rejects prose, code fences, duplicate keys and oversize
input. It never extracts or truncates. Inline results are limited to 32,768 bytes;
artifacts default to 16 MiB per job. Every finding stays on record with a fixed,
rejected or deferred disposition. A blocker or major finding makes the verdict
adverse.

### Acceptance

A finished task is not an accepted stage. The coordinator freezes its own observation
and runs the pinned validator:

| Workflow | Authority |
| --- | --- |
| imps | The stage gate run's `validate`; adapters cannot replace it |
| ape | `scripts/validate_report.py` |
| plan | `plan_state.py gate`, `render_handoff.py --check`, `scripts/validate_document.py` (source-plan readiness and handoff provenance) |
| babysitter | `scripts/validate_pr.py` at the observed current head |
| agent-tuneup | `scripts/validate_audit.py` |
| focus-group | `scripts/validate_study.py` |

Validators check provenance, coverage and declared criteria, not the truth of
arbitrary prose. The final stage is declared in the first plan. Final readiness
needs fresh acceptance of every requirement at the integrated snapshot. A failed
final check reopens the responsible stage within its remaining budget and marks
later stages stale. These hash checks do not stop a privileged user from forging
every underlying record.

### Repair, routing and fallback

- **Attempts.** Each stage gets an initial attempt plus `max_repair_cycles` repairs
  (default 20). Primary, support and review failures share that budget. Resume,
  escalation and replacement never reset it. An exhausted budget blocks for an owner
  decision.
- **Routing.** The coordinator recommends an eligible saved workhorse preference,
  otherwise the lowest suitable configured tier, with
  [`agents resolve`](getting-started.md#model-routing) and records the reason and
  escalation order. The user's upfront work/panel choices control dispatch and exact
  supported options. Reviewers need a reviewer or judgement tier; planning fallback
  reports its actual lineage mode. The coordinator's own model never changes.
- **Lifecycle.** Tasks start with `delegate_task` and a stable `clientRequestId`.
  An uncertain launch gets at most two retries with the same ID, then blocks. A
  capacity rejection waits for a completion notification from a task this job owns.
  Nothing polls. A follow-up reuses a child's conversation only when the host
  tracks it as a new task; otherwise a fresh child starts and the reason is shown.
- **Fallback.** When T3 or every suitable target is unavailable, an explicitly
  authorised work chain may permit the coordinator to run the stage itself under
  the same contract, counters and validator, and every
  checklist shows `fallback: direct (<reason>)`. Direct work cannot stand in for a
  required independent review; that stays a blocker.
- **Approvals.** Owner decisions go through the host's native question picker,
  recommended option first. The answer is saved with its quote and source hash. A plan
  change that adds work or weakens a requirement fails with `undeclared_expansion`
  until such a decision exists. Silence is not approval.

## Managed worker definitions

Each plugin ships its workers as `plugins/<plugin>/agents/<worker>.md`. The manifest
lists each worker's ID, file, operations, routing role, responsibility, allowed scope
and output contract. Scope is a ceiling narrowed by the brief, not action authority.
The installer checks catalog operations and metadata before writing a bundle. Definitions contain no
model IDs. They are not installed as skills or native harness agents; only the
plugin's own commands load them.

| Worker | Role |
| --- | --- |
| `imps/stage-executor` | Complete one engineering stage and prepare its verification |
| `imps/investigator` | Read-only cited investigation |
| `imps/auditor` | Confirmed findings, hypotheses and refutations by dimension |
| `imps/reviewer` | Independent review of an exact change snapshot |
| `ape/source-researcher` | Pinned source comparison and transferable proposals |
| `ape/synthesizer` | Compare accepted reports and propose bounded experiments |
| `plan/plan-reviewer` | Challenge the exact discovery, spec and declared evidence before handoff |
| `ralph/strategy-reviewer` | Assess an actually written strategy; final evaluation stays separate |
| `babysitter/pr-maintainer` | Authorized triage or repair of one PR at an exact head |
| `babysitter/pr-reviewer` | Independent review of the final combined PR change, when the operator asks for one |
| `agent-tuneup/config-researcher` | Provider format, scope and precedence with sources |
| `agent-tuneup/config-verifier` | Parse, load and enforcement evidence for authorized changes |
| `focus-group/plan-reviewer` | Challenge the exact study protocol before owner approval and panel work |
| `focus-group/participant` | One isolated invented persona cell on approved material |
| `focus-group/analyst` | Synthesise accepted evidence with citations and dissent |
| `focus-group/fidelity-reviewer` | Check the exact integrated report against its inputs and actual authors |

Installation copies each package's definitions and shared contracts into an
immutable bundle under the XDG registry (default `~/.local/state/agents/jobs/registry`):

```text
<agents-root>/installations/<installation-id>/<plugin>/<package-version>/
  manifest.json
  workers/<worker>.md
  shared/<contract files>
```

This is the plugin registry's own layout. No harness discovers these files as native
agents. Each materialized package retains an installation identity. Worker override
configuration is outside the source, under XDG config `agents/workers.json`.

A worker's effective definition is composed in a fixed order: shared boundaries,
the worker definition, an explicitly enabled override, then the task contract. An
override can change wording; it cannot grant push, merge or settings-edit authority
or change runtime mode. See [managed workers](cli.md#managed-workers) for inspection
and override commands.

## The imps evidence gate

The agent plans and performs the work. The core stores major-version-2 run contracts,
checks, artifacts, review evidence and child observations with atomic writes and
process locks. It does not schedule tasks or issue permitted actions.

Capture a binding before verification. It covers HEAD, dirty and staged bytes,
untracked files, file modes, symlinks, submodules, requirements, constraints and
verification policy. Submissions retain that binding and hashes of their copied
artifacts. `validate` recomputes readiness against the current tree. Pending child
runs prevent readiness, including descendants of a terminal child.

```text
plan → implement → capture binding → verify → submit evidence → validate
                      ↑                                        │
                      └──────── repair and reverify ────────────┘
```

In an imps job, every engineering stage keeps its own gate run, and job metadata
stays outside it. The other plugins use the validators in the
[acceptance table](#acceptance).

## Supplemental reviews

[Free supplemental reviews](supplemental-reviews.md) add up to three opportunistic
OpenCode views alongside an existing required review. The installed shared helper
selects from fresh host capabilities plus explicit fresh zero-price observations,
prepares read-only briefs and records handles/results in a separate private ledger.
Extras require a clean committed scope and fresh live-schema evidence for
`isolation: "worktree"`. T3 owns isolated checkout setup, dispatch and cleanup.
Optional failures never supply acceptance or use required repair counters;
confirmed findings go through the existing repair path.

## Optional learnings

Every installed package includes the shared learning helpers. They load only the
current plugin's project lessons from the XDG state root, maintain versioned entries
transactionally and report storage failures without blocking the task. Harvest
screens local drafts and requires owner approval before external publication.
See [learnings and harvest](learnings.md) for storage and sandbox boundaries.

## Installation and ownership

The installer builds a content manifest, copies a versioned package, writes the
matching worker bundle, and atomically repoints `current`. Each package includes
shared files and the core. That duplicates some small files, but makes rollback
independent of a changing shared installation. A package and its bundle are usable
only as a complete, digest-checked pair.

A job pins the exact package and bundle directories, digests and effective worker
text for every plugin it depends on, including cross-plugin ones such as imps `prs`
using babysitter. Moving `current` does not affect a running job. Uninstall refuses
to remove a version that a live or resumable job pins.

Uninstall follows the manifest, preserves modified and user-added files and
overrides, and leaves run and job state alone. Installation of the whole catalog is
per-plugin, not one global transaction. Receipts make partial completion visible.

## Provider boundary

The active provider supplies the agent's reasoning and shell/file tools. T3 supplies
capability discovery, children, task status/cancellation, previews, and PR watches.
Provider/model IDs come from the live catalog. A plugin never assumes that a role
like "reviewer" means a particular model.

## Tradeoffs

Instructions are portable but model adherence varies. Unit tests prove helper and
state behavior, not that every model follows a playbook. T3 tool schemas also evolve.
Whole-stage delegation is meant to keep the coordinator's context small, but no
provider token or cost saving is inferred from byte measurements; see
[measurement limits](compatibility.md#measurement-limits). The compatibility ledger
records this uncertainty rather than treating provider logos as proof. See
[compatibility](compatibility.md) and [testing](testing.md).

The issue96 installed fixtures measure a representative imps review brief at
648,465 bytes, then 107,859 bytes after removing dependency payloads alone, an
83.37% reduction with its procedure and task evidence unchanged. Separately, the
approved procedures plus required inline schemas and serialized procedural headers
measure as follows across all 18 workers:

| Worker class | Minimum bytes | Maximum bytes |
| --- | ---: | ---: |
| Ordinary | 16,284 | 24,547 |
| Code review | 17,007 | 23,700 |
| Configuration | 16,380 | 22,934 |
| Planning | 19,821 | 23,394 |
| Document only | 14,160 | 14,160 |

These counts include framing, escaping, definition hash/size headers, transport
instructions, result contract and artifact limit. Task evidence and authority are
separate measured header categories and may grow. The 24,576-byte target never
permits truncating required rules. Fixtures also prove that an unused worker or
unrelated schema does not increase the transmitted size. This is local transport
evidence; semantic review, model obedience and live compatibility remain separate.

Focus-group also uses the shared chooser and separate planning-review lifecycle.
Its exact study-plan receipt gates approval and panel work, with per-model work
roles and an independent fidelity reviewer. Stage resources retain the reviewed
revision and producing admission through generic plan revision. Its final fidelity
review remains separate and stronger; deterministic study helpers never dispatch.

Focus-group planning binds the product protocol and every declared evidence file
by content, with an explicit evidence-root path. Git HEAD is not a dependency of
this product study. Receipt consumption and local report export rehash those
inputs without launching Git or a publication command.

Deprecated elephant-goldfish snapshots and worker contracts remain available for
old pinned jobs. Default catalog/setup and the field guide use plan; deprecation
does not rewrite stored state or claim new acceptance for old receipts.
