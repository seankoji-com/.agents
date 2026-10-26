# agent-tuneup

Apply `PKG/shared/upfront-agreement.md`.

Apply `PKG/shared/model-selection.md` before substantive work or dispatch; workers consume frozen choices.
Public admission: `PKG/scripts/plan_review.py`; contract: `PKG/shared/adopter-planning.md`;
criteria: `PKG/references/adopter-review-rubric.md`.
Read `PKG/shared/learnings.md` and load lessons.

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
   Wiring v2 adds explicit native-agent/portable-role discovery and a private
   normalization proposal through the existing `align.py audit` entrypoint. V1
   retains its earlier coverage with detailed inventory marked unavailable.
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
Codex TOML, Gemini JSON, Cursor JSON. Target settings are never executed.

## Boundaries

- **Deterministic format checks.** `audit.py` and `align.py` decide format, changed
  keys, risk counts and write safety. A worker or model claim never overrides a
  helper exit code or refusal.
- **Local usage scan.** Scan readable local transcripts when available; narrower
  requests may exclude the scan. Frequency never justifies an allow rule, and
  transcripts stay private.
- **Report first.** `doctor`, `scan`, `audit` and `align` write no settings. Their
  findings, matrix and candidates are the deliverable.
  correctly reported findings and exit `1` completes when the criteria allow findings;
  exit `2` is a blocker.
- **Authorized, backed-up settings edits only.** Only the coordinator edits settings
  through `apply`, after the owner approves the concrete plan using the native
  question picker with the recommended option first. Record the answer with the
  job decision scoped `settings-change:<change-id>` before applying.
- **No permission expansion.** Never broadly allow shells, interpreters, installers,
  arbitrary MCP tools or remote commands. Never disable sandboxing or approvals.
  An audit or alignment request is not permission to widen access.
- **Distinct observations.** Parse, load and live enforcement are separate. Unknown
  enforcement stays `unverified`; it blocks acceptance only when the task requires
  live enforcement.

Worker definitions grant no settings-edit, push, merge or message authority.
`PKG/scripts/validate_audit.py` is the pinned acceptance authority. Never reroute
a denied write through another tool.

Apply creates a private backup before any write; report the backup path.
Apply is backed by a verified plan with an unchanged digest. When a settings
format is not supported, report the gap; do not guess an unstructured write.
