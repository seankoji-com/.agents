# agent-tuneup

Apply `PKG/shared/model-selection.md` before substantive work or dispatch; workers consume frozen choices.
Use `PKG/shared/adopter-planning.md` and `PKG/references/adopter-review-rubric.md`
for public admission and receipt gates through `PKG/scripts/plan_review.py`.
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Audit and align agent configuration without weakening permissions. Read
`PKG/shared/t3-runtime.md` once. Delegation follows `PKG/shared/delegation.md`.
Multi-stage jobs follow `PKG/shared/job-coordination.md`; this entry adds only
tuneup policy. Load `PKG/playbooks/audit.md` for inspection,
`PKG/playbooks/align.md` for comparison, proposals and approved changes, and
`PKG/references/job-plan.md` when you create or resume a job.

## One workflow

Invoke `$t3-agent-tuneup [scope or desired outcome]`. A bare invocation runs the
complete workflow. Do not offer audit, align, apply, scan or doctor as public
subcommands, and do not ask the owner to choose a mode. Natural-language narrowing
such as "only inspect this settings file" limits the work and its authority.

1. Check local readiness directly with `python3 PKG/scripts/audit.py --list-adapters`
   and `t3-plugins agents list agent-tuneup` when available. Report missing tools;
   never install a provider to make readiness pass.
2. Inventory every provider instance in T3's current catalog and all default
   coverage in `PKG/references/central-wiring.md`: shared instructions, skills,
   permissions, MCPs, runtime modes, roles, duplicate orchestration and worktree setup.
   Follow `PKG/playbooks/audit.md` for format checks and T3 bootstrap inspection.
3. Include a local usage-frequency scan when readable Claude transcripts exist:
   `python3 PKG/scripts/scan_perms.py --json`. Keep input and aggregate output private.
   Report unsupported providers, absent transcripts and unreadable paths as coverage
   gaps; do not install tools or acquire credentials. Tool frequency is diagnostic
   evidence and never justifies broad permission rules.
4. Follow `PKG/playbooks/align.md` to compare actual native layers, resolve scope and
   precedence questions, and prepare reviewed changes. Collect model choices once
   under operation `agent-tuneup/tuneup`; internal audit/align stages consume that
   same admission without presenting another mode or chooser.
5. Present the concrete redacted changes, access effects and private backup paths.
   Ask for approval of those exact changes through the native question picker.
   If declined, deliver the audit and proposals. If approved, continue within this
   workflow through the existing backed-up apply and independent verification steps.
   Invocation alone does not approve unseen settings changes.
6. Report applied changes and backups, parse results, observed native loading,
   required live enforcement and every remaining coverage gap separately.

The deterministic helper commands remain internal implementation details. Their
`audit`, `align`, `apply` and `scan` names are not additional user workflows. A
single-file inspection can stay direct; full inventory, proposals and approved apply
use `PKG/references/job-plan.md`. Use the `tuneup` admission for the whole job;
concrete approval still gates adding and executing its settings-apply stage.

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
- **Local usage scan.** The default workflow scans readable local transcripts; narrower requests may exclude it. Frequency never
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
