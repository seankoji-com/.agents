# agent-tuneup
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Audit and align agent configuration without weakening permissions. Read
`PKG/shared/t3-runtime.md` once. Delegation follows `PKG/shared/delegation.md`.
Multi-stage jobs follow `PKG/shared/job-coordination.md`; this entry adds only
tuneup policy. Load only the selected operation's files: `PKG/playbooks/audit.md`
for `audit`, `PKG/playbooks/align.md` for `align` or `apply`, and
`PKG/references/job-plan.md` when you create or resume a job.

## Operations

`doctor` and `scan` are direct. They never create a job or launch a worker.

- `doctor`: check Python and list supported adapters with
  `python3 PKG/scripts/audit.py --list-adapters`. When the `t3-plugins` command is
  available, add `t3-plugins agents list agent-tuneup` for local bundle integrity.
  Doctor checks local files, not live provider behaviour.
- `scan --provider claude`: only on explicit request, read recent Claude transcript
  tool-call frequencies with `python3 PKG/scripts/scan_perms.py --json`. This is usage
  evidence, not a permission recommendation. Never publish transcripts.
- `audit --provider <name> --settings <path>`: inspect explicitly supplied settings.
  Exit codes: `0` clean, `1` findings present, `2` unreadable or invalid settings.
  One file with no open syntax, scope or precedence question is direct: run the
  helper and report. When findings need provider semantics, several files or
  scopes need comparing, or the owner wants changes proposed, coordinate a job.
- `align`: inventory every provider in T3's live catalog, compare permissions, MCPs,
  plugins, skills, instructions and hooks, and prepare native changes for review.
  Inventory and proposals write no settings. Alignment across several providers is a
  job with research and proposal stages.
- `apply --plan <path>`: apply an unchanged, explicitly approved plan with its digest
  and a new private backup path. Approval is for the concrete changes, not the
  operation name. Every apply is a job with an `apply` stage, so its backup, parse,
  load and enforcement evidence pass the validator.

Any T3 provider can run this audit. The target settings format is separate from the
calling provider. Supported structured audits: Claude JSON, OpenCode JSON/JSONC,
Codex TOML (Python 3.11+) and Muse JSON (named permission profiles under
`permissions.profiles`). The alignment helper also supports Antigravity MCP JSON/JSONC.
Other settings get manual inspection only. Alignment uses explicit capability
mappings, never translates permission syntax by analogy, and retains unsupported or
intentional differences.

## Workers

Only the coordinator dispatches, through the routing and lifecycle rules in the
coordination contract.

- `agent-tuneup/config-researcher`: exact provider format, scope, precedence and
  version semantics with primary-source citations. Route at the lowest suitable
  workhorse tier. Read-only.
- `agent-tuneup/config-verifier`: checks only listed proposed or applied changes and
  returns parse, load and live-enforcement outcomes separately. Route at reviewer
  tier, on a different known lineage from the researcher when one is configured;
  otherwise report independence as unverified.

Worker definitions grant no settings-edit, push, merge or message authority, and task
briefs narrow them further. Workers never run `align.py apply`, restore a backup, edit
settings, dispatch children or accept their own results. An extra-work request that
does not fit a declared slot and its authority is refused or needs an owner decision.

## Boundaries

- **Deterministic format checks.** `audit.py` and `align.py` decide format, changed
  keys, risk counts and write safety. A worker or model claim never overrides a
  helper exit code or refusal.
- **Optional transcript scan.** `scan` runs only when requested. Frequency never
  justifies an allow rule, and transcripts stay private.
- **Report first.** `doctor`, `scan`, `audit` and `align` write no settings. Their
  findings, matrix and candidates are the deliverable.
- **Authorized, backed-up settings edits only.** Only the coordinator edits settings,
  only through `apply`, and only for a concrete plan the owner approved through the
  native question picker with the recommended option first. Record the answer with
  the job `decision` command scoped `settings-change:<change-id>` before applying.
  Keep a before-edit snapshot and a new private backup outside job state and every
  checkout. Stop on a denied write; never reroute it through another tool.
- **No permission expansion.** Never broadly allow shells, interpreters, installers,
  arbitrary MCP tools or remote commands. Never disable sandboxing or approvals,
  copy permission expressions between providers, or remove deny or ask rules to
  reduce prompts. An audit or alignment request is not permission to widen access.
- **Distinct observations.** Parse, load and live enforcement are separate
  observations. A parseable file is not loaded, and a loaded file is not enforced.
  Unknown enforcement stays `unverified`; it blocks acceptance only when the task
  requires live enforcement.
- **Privacy.** Never print credentials, headers, private URLs, hostnames or settings
  values. Inventories, plans, candidates and backups stay private and out of commits.

## Acceptance

The authority is the pinned `PKG/scripts/validate_audit.py`, run through
`PKG/shared/job_acceptance_cli.py` from the job's pinned package. It accepts a published
coordinator observation that matches the stage's declared criteria. An audit with
correctly reported findings and exit `1` completes when the criteria allow findings;
exit `2` is a blocker. A report-only audit with settings changes is rejected. An apply
needs each change's recorded owner authorization, an exact backup of the before-edit
bytes, and passed parse and load observations. Required live enforcement must pass.
A worker's `ready-for-acceptance` or a terminal task is never acceptance.

Report findings, proposals, owner approvals, files applied, backups, parse, load and
live-enforcement results separately. Never claim aligned effective permissions from
file equality, fixture tests or a running process. Do not commit, push or persist
personal learnings unless separately requested.
