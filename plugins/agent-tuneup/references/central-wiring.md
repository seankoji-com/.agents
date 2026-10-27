# Default central wiring

Bare `audit` and every `align` cover this whole contract. A narrowed single-file or
`--t3-projects` audit stays narrow. Missing evidence is a finding, never an implicit
opt-out. Permission synchronization belongs here by default; do not recreate the
retired `sync-harness-permissions` skill. Retire `hatch-pet` and its aliases as part
of the proposed migration, preserving anything its owner cannot prove it owns.

## Authority and evidence

T3 owns orchestration, task lifecycle, watches, model selection and review routing.
Give all configured providers equal coverage, including disabled, unfamiliar and
version-unknown runtimes. Keep unsupported and intentional differences with reasons.
Do not enable every MCP, install a missing provider, alter privileges or remove
approval/sandbox protections to make the rows match.

| Surface | Default target and required evidence |
| --- | --- |
| `global-rules` | One maintained global source, native imports or generated shims only where needed. Record precedence and actual loaded layer. |
| `skills` | Canonical bodies live in the `~/.agents` source checkout. Shared discovery or receipt-owned native links expose them; no generated body or default picker YAML. .agents owns discovery; dotfiles owns native settings and frozen unmigrated-host compatibility. Preserve local/vendor content. |
| `permissions` | Compare intent and access boundaries using each native syntax, profiles, sandbox and approval rules. Sync shared policy without increasing access. File equality is insufficient. |
| `mcp` | One purpose-based capability catalog; render native names, transport, arguments, endpoints and tool filters. Scope profiles by task/project; keep credentials and host-specific overrides machine-local. Inspect T3-injected tools separately. |
| `roles` | Portable expertise briefs in `~/.agents/roles`, loaded only when useful. Separate them from T3 worker contracts, review personas and GitHub Apps. Roles grant no tools or orchestration authority. |
| `orchestration` | Inventory duplicate native brokers, agents, commands and hooks; propose retirement where T3 already owns the function. Preserve unrelated native features. |
| `repository-entrypoints` | Each repo owns an `AGENTS.md` entrypoint. Native files contain only the necessary import/adapter; retain native exceptions with evidence. |
| `worktree-bootstrap` | Run the T3 project bootstrap audit too. Check saved/imported scripts and fresh worktree results, not just a checked-in `t3.json`. |
| `lazy-context` | Small entrypoints link to task-specific context. Record always-loaded bytes versus on-demand bytes; avoid loading every role, tool description or reference. |
| `discovery` | Record per-provider loaded rules, skill/alias counts, role discovery and scoped MCP visibility. Report configured, loaded and exercised results separately with runtime version. |

For Muse and OpenCode, verify the installed runtime/version and primary configuration
schema. Never assume a historical MCP location or CLI subcommand still exists. A
version-unknown runtime stays unknown. The settings parsers recognize known shapes;
they do not certify current-version compatibility. Muse MCP/plugin state remains
manual until its runtime storage and loading are established.

## Structured coverage

`align.py compare` always returns `wiring`. Extend the private inventory with a
`wiring` object (version `1`):

- `authorities`: object keyed by the ten surface IDs above, each containing evidence.
- `providers`: records with `provider_instance_id`, `runtime_version` (string or
  `null`) and `surfaces`. Each surface has `state` (`configured`, `unknown`,
  `unsupported`, `intentional-difference`), `evidence`, and a `reason` for exceptions.
- Evidence is an array of `{"path": "/absolute/evidence", "sha256": "<64 hex>"}`.
  Bind source files or private observation receipts. No secret values in receipts.
- Capability-level `intentional_differences` must include a nonempty `reason` and an
  `evidence` array whose digests are all fresh (`bound`). Empty, stale or unreadable
  evidence does not bind the exception.
- `shared_skills`: the resolved shared skill directory. Provider records can name
  `skill_roots` (provider-specific directories only) and `reads_shared_skills: true`
  when native shared discovery has been established. Include every relevant root.

The helper checks evidence freshness, complete surface coverage and immediate skill
entries. It counts aliases and receipt-matching adapters, reports retired skills,
copies and redundant aliases, and preserves everything. Counts cover declared paths
only; it never traverses vendor trees, executes launchers or infers loaded state.
Runtime versions and state assertions are operator observations. A matching hash
binds an observation; it does not prove its content. Report helper findings with
locations such as `wiring.providers[0].skills`, and keep the index legend private.
Use `align.py audit --catalog FILE --inventory FILE` for the same report with audit
exit codes: `0` no reported findings, `1` findings/gaps, `2` invalid input or an
unreadable native settings layer. Comparison itself stays a diagnostic matrix.
Capability gaps also produce findings. A capability may declare
`intentional_differences` keyed by provider instance ID, each with a nonempty
`reason` and fresh `evidence`; a general surface exception does not exempt it.

Skill duplicates are scoped to each provider's effective roots. The shared root
counts only for providers declaring `reads_shared_skills: true`; other providers
can retain required aliases. Entry receipts identify `agents`, `dotfiles`, or
`unmanaged` ownership with `verified`, `modified`, `invalid`, `unsupported`, or
`unmanaged` status. Both receipt formats check every listed file; malformed receipts
stay findings. Receipt paths must remain inside the skill directory after resolving
aliases. Canonical source ownership is `agents-source`/`identity-bound`, using the
protected cutover identity and external discovery receipt for native links. Editable
bodies are not immutable receipt assets. Legacy t3-plugins receipts stay recognized.
Inventory preserves all files and aliases; none of these checks proves live loading.

## Migration preflight and recovery

Before **any** migration write, including adapter generation, capture the exact
owner/source revision, active package, ownership receipt, destination bytes/modes,
alias targets and candidate hashes. Verify every receipt-owned file first. A familiar
name, matching template or common prefix is not ownership. Modified, unowned, vendor
and local files stay in place with a named blocker or an explicitly reviewed preserve
plan. Do not overwrite an immutable installed package to repair its adapter.

Preflight **all destinations** before the first write. Include absent destinations,
backup parents, native roots, rules, skills, roles, MCPs and repo shims. Refuse linked
parents rather than following them to replace someone else's tree. Inventory may read
an explicit alias, but a write must name the reviewed canonical destination. Check
for collisions and concurrent writers; refresh preflight if anything changes.

For existing settings plans, save a private JSON array of
`{"plan": "/absolute/plan.json", "backup": "/absolute/new-backup"}` and run:

```sh
python3 PKG/scripts/align.py preflight --batch /absolute/batch.json
```

Each record must contain exactly the `plan` and `backup` keys, both nonempty
strings. Missing or extra keys are rejected as `invalid_batch`.

It revalidates every plan and backup destination without writing. It grants no
approval and provides no multi-file transaction. Each apply retains its digest,
planning review, owner-decision, backup and parse/load gates. Settings apply remains
POSIX-only. Non-settings migrations need their own concrete proposal and checks.
Target and backup parents need effective write and search access. Platforms without
an effective-access check report unknown readiness and refuse preflight. These
read-only checks cannot guarantee free space, mount writability or future access.

Keep recoverable private backups outside checkouts, created exclusively before
replacement/removal. Preserve file bytes, modes, relative paths and link/junction
targets, including broken aliases; copying dereferenced content loses alias recovery.
Verify backup contents before mutation. Never recursively delete a directory to
remove a managed alias. Report completed steps and backup locations after a partial
failure; never restore blindly over a concurrent edit.

Adapter metadata must come from the selected `current/plugin.json` and its verified
install receipt, not the CLI's bundled version. The adapter marker proves only its
listed files. Keep unlisted local/vendor files. Once a provider natively reads the
shared skill root, remove only proven duplicate provider aliases after backing them
up; retain necessary adapters for other readers.

On Windows use Python 3.11+ for TOML inspection. Inventory junctions as reparse
points, record their targets and refuse linked write parents just as for symlinks.
Use native discovery or a reviewed minimal adapter where junction replacement cannot
be made safe. Quote each path as its own argv item; for a manual PowerShell launch,
use the call operator, for example `& 'C:\Program Files\Python311\python.exe'
'C:\Tools\audit.py' --list-adapters` on one line. Do not transplant POSIX shell
quoting or claim this POSIX settings writer can migrate Windows junctions.

After an authorized migration, recapture discovery counts and context bytes in a
fresh provider session. Exercise only authorized read-only probes. Keep parse, load,
enforcement, review and live acceptance separate. Do not turn fixtures into a claim
that the live migration happened.
