# agent-tuneup

Compare provider permissions, MCPs and plugins, then apply reviewed native changes.

## When to use it

You want consistent capabilities across the providers you use in T3 Code, while
keeping each provider's access boundaries. `align` inventories T3's live catalog
and reports gaps across permissions, MCPs, plugins, skills, instructions and hooks.
You can also audit one settings file, find exact duplicate permission rules, or
inspect Claude tool-use counts. The calling provider may differ from the target.

## Try it

After [installation](../getting-started.md), run in your terminal:

```sh
t3-plugins prompt agent-tuneup doctor
```

Paste the printed line into a T3 thread attached to your project. Once readiness is
clear, generate a task prompt:

```sh
t3-plugins prompt agent-tuneup audit --provider claude --settings .claude/settings.json
```

Paste that output into T3. Replace the sample task or path with your own.
If you installed [skill adapters](../slash-commands.md), select **t3-agent-tuneup**
from `/` and append the same request instead.

## Operations

`doctor`, `audit`, `align`, `apply`, `scan`. The [entry file](https://github.com/seankoji-com/t3-plugins/blob/master/plugins/agent-tuneup/entry.md) names the file to load for each operation.

## What you get

A private inventory, a comparison matrix, and proposed provider-native changes.
The deterministic receipts omit settings values and personal paths. `apply` writes
one explicitly approved settings candidate at a time, checks original and candidate
hashes, preserves a private backup, and refuses stale plans or newly added known
broad permission patterns. A single-file audit
returns finding codes and locations. A finding
is a known pattern worth inspecting, not proof that a tool is allowed after every
policy layer has been applied.

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

```sh
t3-plugins prompt agent-tuneup align
```

Paste the output into a T3 thread, or invoke **t3-agent-tuneup** with `align`.
The workflow discovers every provider instance in the live catalog and identifies
its global, project, local, managed and host settings layers. Disabled and unknown
providers stay visible. Choose which capabilities should be shared and which should
remain different; the workflow prepares a concrete proposal before requesting
approval.

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
entry="$(t3-plugins path agent-tuneup)"
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

The workflow prepares a native candidate for each settings file. Review a redacted
diff, every changed key, its access effect and the approval digest. Approving the
skill extension or asking for alignment does not approve live configuration edits.
Use `apply --plan <path>` only after approving that concrete plan.

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

Calling provider and target configuration format are separate. Unsupported formats receive manual inspection, not guessed writes. Antigravity
MCP JSON has structured inventory and native-file planning/apply; its permissions
and plugin/extension settings remain manual. Codex plugin identity tables do not
prove plugin installation. See [compatibility](../compatibility.md) for the distinction between deterministic tests and live provider results.

## Supported audit formats

| Adapter | Input | Scope |
| --- | --- | --- |
| Claude | JSON | Exact duplicate allow rules, known broad execution allows, bypass mode |
| OpenCode | JSON/JSONC | Global/tool wildcard allows |
| Codex | TOML, Python 3.11+ | Disabled approval/sandbox settings, including profiles |

These are known-pattern warnings, not a complete permission evaluator. Deny precedence, dynamic policies, host restrictions, and extension-specific semantics need contextual review.

Format references (checked on 12 October 2026): [Claude settings](https://code.claude.com/docs/en/settings),
[Claude MCP](https://code.claude.com/docs/en/mcp), [OpenCode configuration](https://opencode.ai/docs/config/),
[OpenCode plugins](https://opencode.ai/docs/plugins/), [Antigravity MCP](https://antigravity.google/docs/mcp),
[T3 Antigravity integration](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
[Claude permissions](https://code.claude.com/docs/en/permissions), [OpenCode permissions](https://opencode.ai/docs/permissions/), and [Codex configuration](https://developers.openai.com/codex/config-reference/).

## Run without a model

Create a synthetic settings file and audit it using the installed helper:

```sh
printf '%s\n' '{"permissions":{"allow":["Bash(*)"]}}' > example-settings.json
entry="$(t3-plugins path agent-tuneup)"
python3 "$(dirname "$entry")/scripts/audit.py" \
  --provider claude --settings example-settings.json
```

Expect a finding for the broad Bash rule and exit `1`. Exit `0` means no known
findings; `2` means unreadable or invalid input. The helper does not change the
settings file. Use `--list-adapters` to inspect supported formats.

`scan --provider claude` reads recent local transcript tool-call frequencies. Those
counts do not authorize permission changes. Do not share private transcripts.
