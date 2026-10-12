# agent-tuneup
Read `PKG/shared/learnings.md` and load this plugin's project lessons before work.

Audit and align agent configuration without weakening permissions. Read
`PKG/shared/t3-runtime.md`. For `audit`, `scan`, or `doctor`, read
`PKG/playbooks/audit.md`; for `align` or `apply`, read `PKG/playbooks/align.md`.
Delegation follows `PKG/shared/delegation.md`.

- `audit --provider <name> --settings <path>`: inspect explicitly supplied settings.
  Exit codes: `0` clean, `1` findings present, `2` unreadable or invalid settings.
- `align`: inventory every provider in T3's live catalog, compare permissions, MCPs,
  plugins, skills, instructions and hooks, and prepare native changes for review.
- `apply --plan <path>`: apply an unchanged, explicitly approved plan with its digest
  and a new private backup path. Approval is for the concrete changes, not the operation name.
- `scan --provider claude`: read recent Claude transcript tool-call frequencies with
  `python3 PKG/scripts/scan_perms.py --json`. This is usage evidence, not a permission recommendation.
- `doctor`: check Python and list supported adapters with
  `python3 PKG/scripts/audit.py --list-adapters`.

Any T3 provider can run this audit. The target settings format is separate from the
calling provider. Supported structured audits: Claude JSON, OpenCode JSON/JSONC,
Codex TOML (Python 3.11+). The alignment helper also supports Antigravity MCP JSON/JSONC.
Other settings get manual inspection only. Default to a report, with no settings
writes. Alignment uses explicit capability mappings, never translates permission
syntax by analogy, and retains unsupported or intentional differences.
