# agent-tuneup

agent-tuneup audits centralized wiring across every provider in T3's catalog and
prepares native changes for approval. Shared rules and skills, permissions, scoped
MCPs, portable roles, repo entrypoints and worktree setup are included by default.
It is read-only until you approve a concrete plan. It can also audit one settings
file for broad allow rules without a model.

## Try it

```text
$agent-tuneup
```

The command checks readiness, inventories every provider, audits shared wiring and
worktree setup, scans supported readable local usage, compares native configuration,
and prepares reviewed changes. There is no subcommand menu. It shows the concrete
changes and backup paths before asking to apply them, then verifies approved changes
in the same workflow. A declined proposal ends with the report and no writes.

Narrow the scope in ordinary language when needed:

```text
$agent-tuneup inspect only .claude/settings.json; do not propose changes
```

The provider running the workflow need not be the one being inspected. Missing
providers, unreadable transcripts and unsupported formats remain coverage gaps.
Usage scan input and output remain private; tool frequency never justifies a broad
allow rule. To inspect one file without a model, [run the helper locally](#run-without-a-model).

## What you get

An audit returns finding codes and locations, such as `broad_execution_allow` at
`permissions.allow[0]`. It never prints setting values or personal paths. A finding is
a known pattern worth a look; it doesn't prove a tool is allowed after every policy
layer applies.

The comparison stage returns a private inventory, a comparison matrix and proposed native changes.
After concrete approval, the apply stage writes one approved settings file at a time. It checks the original and
candidate hashes, keeps a private backup, and refuses stale plans or newly added broad
permission patterns.

## Worktree setup for T3 projects

A T3 thread in worktree mode starts in a fresh checkout. Without a setup script,
`node_modules`, `.venv` and module caches are missing, and the agent's first test run
fails. The worktree inspection reads your projects through T3's own tools
(`t3_environment_read`, `t3_project_list`, `t3_project_read`) and flags
`worktree-bootstrap-missing` when all three hold:

- The project's thread mode is `worktree`. The audit takes the project setting
  first, then the environment default, then `defaultThreadEnvMode` in `t3.json`.
  That order follows T3's project-file contract as read on 14 October 2026; if your
  T3 build resolves it differently, treat the mode source in the finding as a hint.
- The checkout root has a tracked `pnpm-lock.yaml`, `package-lock.json`, `bun.lock`,
  `uv.lock` or `go.mod`. Untracked or gitignored lockfiles don't count.
- No saved project script sets `runOnWorktreeCreate: true`. When `t3.json` has
  such a script but the saved scripts don't, the finding is
  `worktree-bootstrap-not-imported` instead, with no draft: the script exists and
  only needs importing.

A `worktree-bootstrap-missing` finding carries a draft `t3.json`:

```json
{
  "scripts": [
    {
      "name": "Setup Worktree",
      "command": "node \"$HOME/.local/bin/t3-setup-worktree.mjs\"",
      "icon": "configure",
      "runOnWorktreeCreate": true,
      "async": false
    }
  ]
}
```

`async` is `false` for JavaScript and Python projects, so the agent waits for the
install, and `true` when `go.mod` is the only lockfile. The command assumes a setup
helper at `$HOME/.local/bin/t3-setup-worktree.mjs`; put your repository's install
command there if you don't have one. If the project already has a `t3.json`, add the
script to its `scripts` array rather than replacing the file.

The audit writes nothing. It doesn't create `t3.json`, change project settings or
import scripts. A committed `t3.json` isn't enough on its own: import its scripts in
Settings → your project → Actions, or ask the agent to call `t3_project_update` with
the existing saved scripts plus this one. `draft_saved_script` carries an `id` that
none of the project's saved scripts already use.

To run the check without a model, save T3's responses in a private file outside every
checkout. It holds local paths, so don't commit it:

```json
{"environment": {"preferences": {"defaultThreadEnvMode": "worktree"}},
 "projects": [{"id": "example", "workspaceRoot": "/absolute/checkout",
               "defaultThreadEnvMode": null, "scripts": []}]}
```

```sh
python3 "$(dirname "$(agents path agent-tuneup)")/scripts/audit.py" --t3-projects private-snapshot.json
```

It exits `1` with findings, `0` with none and `2` for an unreadable snapshot. Findings
name projects by index and T3 id, never by path. Projects whose checkout is missing
or isn't a readable git repository appear under `unchecked`.


## Jobs and workers

`doctor`, `scan` and a single-file audit with no open question stay direct.
Audits that compare several files or need provider semantics, alignment across
providers, and every `apply` run as one [job](../architecture.md#whole-jobs).

- `agent-tuneup/config-researcher` reports provider format, scope and precedence with
  primary sources.
- `agent-tuneup/config-verifier` checks only the listed changes and reports parse,
  load and live enforcement separately.

Neither worker can edit settings. `scripts/validate_audit.py` decides acceptance: an
audit that reports its findings and exits `1` can pass, and an apply needs your
recorded approval, an exact backup and passing parse and load observations.

## Align all T3 providers

```text
$agent-tuneup
```

Invoke the explicit skill mention in a T3 thread.
The workflow discovers every provider instance in the live catalog and identifies
its global, project, local, managed and host settings layers. Disabled and unknown
providers stay visible. Choose which capabilities should be shared and which should
remain different; the workflow prepares a concrete proposal before requesting
approval.

The default target is one maintained source for each surface with minimal native
adapters. Custom skills live in `~/.agents/skills`; portable role briefs live in
`~/.agents/roles` and grant no tools or delegation authority. T3 owns orchestration
and review routing. Duplicate native orchestration and the retired `hatch-pet` and
`sync-harness-permissions` skills enter the migration proposal. Permission sync is
part of tuneup. Local/vendor files stay protected by ownership checks.

The comparison helper now always reports ten `wiring` surfaces for every catalog
provider. Missing or stale evidence stays visible. Its private input can bind source
and observation files by SHA-256 and inventory shared/provider skill roots. It counts
skill aliases, reports redundant discovery and preserves all files. The full input
contract and migration checklist are in
[central wiring](https://github.com/seankoji-com/.agents/blob/4899a8e870eb8aa12fd3109cc6a704d2929c0aeb/plugins/agent-tuneup/references/central-wiring.md).
These checks bind supplied evidence; they do not establish native loading.

Matching capability names does not prove matching access. Permission expressions
are never translated by analogy. MCP transport, authentication references, tool
filters and approvals need inspection. Plugins and extensions can use different
formats and installation mechanisms; skills, instructions and hooks need their own
loading checks. T3's injected tools are checked in a T3 session separately from
persistent MCP settings. For Claude, inspect `.mcp.json`, user/local MCP definitions
in `~/.claude.json`, and approval/disable lists in its settings. Project-keyed MCP
definitions are detected but stay unknown until the relevant project is reviewed.

For a deterministic comparison, save the `orchestrator_capabilities` response and
an inventory like this in private local files. Substitute exact IDs and paths from
your environment; this is a synthetic example, not a discovery rule:

```json
{
  "version": 1,
  "providers": [
    {"provider_instance_id": "example-instance", "adapter": "claude",
     "sources": [{"scope": "global", "path": "/absolute/settings.json"}]}
  ],
  "capabilities": [
    {"kind": "mcp", "members": {"example-instance": "repo-tools"}}
  ]
}
```

```sh
entry="$(agents path agent-tuneup)"
python3 "$(dirname "$entry")/scripts/align.py" compare \
  --catalog private-catalog.json --inventory private-inventory.json
```

The receipt uses indices in catalog/source/capability order, with states such as
`configured`, `disabled`, `scope_conflict`, `not_in_supplied_sources`, and `unknown`.
Keep the name legend private. `configured` describes the supplied file only. It does
not prove that the provider loads the file, that a plugin is installed, or that an
MCP authenticates. An approval-list entry without a supplied MCP definition remains `unknown`.
No files change during comparison.

## Apply approved changes

Before any migration write, verify the exact source/package revision and ownership
receipts for all destinations. Back up original bytes, modes and alias/junction
targets outside checkouts. Refuse linked write parents; preserve modified and
unowned files. A provider that reads the shared skill root needs no duplicate
per-skill aliases. Adapter generation uses the verified current package's manifest,
even when the CLI bundles a newer version. Windows migrations need Python 3.11+
for TOML, native path quoting and explicit junction checks; settings apply is
POSIX-only.

The workflow prepares a native candidate for each settings file. Review a redacted
diff, every changed key, its access effect and the approval digest. Approving the
skill extension or asking for alignment does not approve live configuration edits.
Use `apply --plan <path>` only after approving that concrete plan.

For multiple settings plans, first run `align.py preflight --batch FILE`, where
`FILE` is a private array of `{"plan":"/absolute/plan.json",
"backup":"/absolute/new-backup"}` records. Each record must have exactly those
two keys with nonempty string values; missing or extra keys return `invalid_batch`.
Keep the existing plan input and
not-yet-existing backup destination at private paths. This checks every target,
candidate and backup destination before writing, including collisions and stale plans. It grants
no approval and is not a multi-file transaction. Rerun preflight after any plan,
target, candidate or backup change. Every apply repeats its safeguards.

The helper supports existing Claude JSON, OpenCode JSON/JSONC, Codex TOML,
Antigravity MCP JSON/JSONC and Muse JSON files. It does not install plugins or edit instruction/skill
files. Those changes require separate proposals. For one synthetic Claude change:

```sh
python3 "$(dirname "$entry")/scripts/align.py" plan --adapter claude \
  --target /absolute/settings.json --candidate /absolute/candidate.json \
  --allow-key /permissions/allow --out /absolute/private-plan.json
python3 "$(dirname "$entry")/scripts/align.py" apply \
  --plan /absolute/private-plan.json --approval APPROVED_DIGEST \
  --backup /absolute/new-backup
```

Repeat `--allow-key` for each changed JSON pointer; arrays count as one change.
OpenCode permission-pattern reordering changes the parent pointer and needs review.
Scalar-to-object permission rewrites may be conservatively refused.
Unrelated settings roots cannot change. Supported changes include Claude permissions,
MCP settings and sandbox; Codex approval/sandbox/MCP/plugin settings and
profile policy overrides; OpenCode permissions, MCPs, plugins and agent permission
overrides; Antigravity MCP definitions; and Muse permission profiles
(`permissions.profiles` — MCP and plugin state lives outside its `settings.json`).
Profile/agent model edits, hooks, and Claude
project-keyed store writes need separate proposals. Risk code counts are retained
in plans. Protection-deletion and broad-rule-substitution checks also apply.
The receipt explicitly says permission semantics are not evaluated. Unlisted
options, changed glob/command meaning, deny precedence and inheritance can loosen
access without a finding. Review every changed key and its native defaults; equal
risk counts do not prove equivalent or unchanged access. Plans and backups are private, mode 0600,
and never overwrite existing files. Choose private storage outside every checkout; the helper does not enforce
repository exclusion. Use canonical absolute paths. For OS aliases such as macOS
`/tmp` or `/var`, inspect the real destination and use it consistently in the plan.
Settings must be owned regular files without symlinks, hard links or group/other write access. Codex TOML requires Python 3.11+;
planning and apply require POSIX. Stop other configuration writers first: conflict
checks are optimistic and cannot exclude a race at the final replacement.

Apply handles one file at a time, without a multi-file transaction. If a later
change fails, earlier applied files and their backups remain. On failure, inspect
the actual target and backup before restoring or reporting writes. Verify the
provider loads the result in a fresh session, then test any approved MCP or plugin
capability. Parsing, settings applied, and live acceptance are separate results.
Exit `0` means the helper operation succeeded; exit `2` means invalid, unsafe,
stale or unapproved input, or an I/O failure.

## Limits

The provider running the workflow and the configuration format it reads are separate
questions. Unsupported formats get a manual inspection, never a guessed write.
Antigravity MCP JSON has structured inventory and native-file planning and apply; its
permissions and plugin or extension settings stay manual. Codex plugin identity tables
don't prove a plugin is installed. Unit tests don't show how a given model behaves;
see [compatibility](../compatibility.md).

## Supported audit formats

| Adapter | Input | Scope |
| --- | --- | --- |
| Claude | JSON | Exact duplicate allow rules, known broad execution allows, bypass mode |
| OpenCode | JSON/JSONC | Global/tool wildcard allows |
| Codex | TOML, Python 3.11+ | Disabled approval/sandbox settings, including profiles |
| Muse | Known JSON permission-profile shape | Approval, filesystem and network warnings; MCP/plugin storage requires runtime evidence |

These are known-pattern warnings, not a complete permission evaluator. Deny precedence, dynamic policies, host restrictions, and extension-specific semantics need contextual review.
Record the installed runtime version, especially for Muse and OpenCode. An unknown
version or changed schema needs inspection rather than assuming these historical
shapes or CLI commands still apply.

Format references (checked on 12 October 2026): [Muse Code configuration](https://dev.meta.ai/docs/muse-code/configuration),
[Muse Code permissions](https://dev.meta.ai/docs/muse-code/permissions), [Claude settings](https://code.claude.com/docs/en/settings),
[Claude MCP](https://code.claude.com/docs/en/mcp), [OpenCode configuration](https://opencode.ai/docs/config/),
[OpenCode plugins](https://opencode.ai/docs/plugins/), [Antigravity MCP](https://antigravity.google/docs/mcp),
[T3 Antigravity integration](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
[Claude permissions](https://code.claude.com/docs/en/permissions), [OpenCode permissions](https://opencode.ai/docs/permissions/), and [Codex configuration](https://developers.openai.com/codex/config-reference/).

## Run without a model

The audit helper is plain Python. Point it at a synthetic settings file and it reports
the broad Bash rule. This is real output, captured with
[`scripts/capture_terminal.py`](https://github.com/seankoji-com/.agents/blob/main/scripts/capture_terminal.py):

```console
$ printf '%s\n' '{"permissions":{"allow":["Bash(*)"]}}' > example-settings.json
$ python3 "$(dirname "$(agents path agent-tuneup)")/scripts/audit.py" --provider claude --settings example-settings.json
{"ok": true, "provider": "claude", "findings": [{"code": "broad_execution_allow", "location": "permissions.allow[0]"}], "scope": "known-pattern audit; not a complete permission evaluation", "writes": 0}
```

It exits `1` when it reports findings, `0` when it finds nothing it knows, and `2` for
unreadable or invalid input. It never changes the settings file. `--list-adapters`
shows the supported formats.

`scan --provider claude` counts tool calls in recent local transcripts. Those counts
don't authorize permission changes. Don't share private transcripts.

Jobs created through the shared CLI carry `policy.identity: observed`. Required reviewer executions, their subjects, and slots marked `independent_of_author` need verified host identity at acceptance. Authoring jobs enforce author-lineage checks from `policy.author_independence`, even if a slot omits its flag. Legacy jobs without the identity marker retain target-only acceptance semantics. A first author record cannot identify earlier authors of an unrecorded document. Direct cold-read stages cannot fall back to the coordinator.

## Proposal review

Cross-scope conclusions, alignment proposals and substantive bootstrap recommendations
now receive planning review, including no-change recommendations. Raw diagnostics and
mechanical templates stay direct. Choose work/review models before synthesis or
delegation. Private settings still need specific recipient authority.

Review precedes concrete apply approval. Apply consumes the unchanged reviewed
proposal and owner answer; candidate changes reopen both. Backup, parse, provider
load, required enforcement and rollback remain separate checks.

See [planning review](../plan-review.md) for default triggers, model choices,
receipt freshness, fallback labels and requester reporting.
