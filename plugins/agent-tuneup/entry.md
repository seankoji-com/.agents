# agent-tuneup

Audit agent configuration without weakening permissions. Read
`PKG/shared/t3-runtime.md`, then `PKG/playbooks/audit.md`.

- `audit --provider <name> --settings <path>`: inspect explicitly supplied settings.
- `scan --provider claude`: read recent Claude transcript tool-call frequencies with
  `python3 PKG/scripts/scan_perms.py --json`. This is usage evidence, not a permission recommendation.
- `doctor`: check Python and list supported adapters with
  `python3 PKG/scripts/audit.py --list-adapters`.

Any T3 provider can run this audit. The target settings format is separate from the
calling provider. Supported structured audits: Claude JSON, OpenCode JSON/JSONC,
Codex TOML (Python 3.11+). Other providers get manual inspection only; never translate
permission syntax by analogy. Default to a report, with no settings writes.
