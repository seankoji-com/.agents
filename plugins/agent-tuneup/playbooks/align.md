# Align T3 providers

## Inventory and comparison

1. Discover `orchestrator_capabilities` and retain its current response as private
   JSON. Inventory every provider instance, including disabled and unfamiliar
   drivers. Catalog runnable means child-task capability, not proof of use, settings
   precedence, authentication, or working MCPs. Never infer a provider from the
   active model or substitute a different installation.
2. Resolve exact settings paths and environment overrides from the host and current
   provider documentation. Inspect global, project, local, managed and host layers.
   Inspect T3 runtime mode, launch arguments, injected MCPs and instruction files
   separately. T3's own tools need not appear in a persistent MCP settings file.
   Retain the private catalog's disabled/not-installed reasons for the matrix.
   Missing or unreadable layers remain unknown; do not call them absent or aligned.
3. Use a private inventory with the schema below. Map capabilities by purpose and
   reviewed identity, not similar names. Check MCP transport, executable/arguments
   or endpoint, authentication references, enabled state, tool filters and approval
   policy locally. Never print credentials, headers, private URLs, commands or paths.
   Matching names or states alone do not establish equivalent access.
4. Run `python3 PKG/scripts/align.py compare --catalog FILE --inventory FILE`.
   Receipt indices follow catalog, source and capability order. Keep the private
   index-to-name legend local. This reports configured states in supplied files,
   not effective policy. Conflicting scopes need provider-specific precedence review.
5. Complete a human-readable matrix covering permissions/approvals/sandbox/network,
   MCPs, plugins/extensions, skills, instruction files and hooks for every instance.
   The helper compares MCP and configured plugin entries only. Skills, instructions,
   hooks, plugin installation/version and effective permissions require manual
   evidence. Mark each cell configured, verified, disabled, unsupported, unknown or
   intentionally different, with the source/scope and reason. Do not install a
   provider to fill a disabled row or run transcript scans unless requested.

```json
{
  "version": 1,
  "providers": [
    {"provider_instance_id": "instance-from-live-catalog", "adapter": "claude",
     "sources": [{"scope": "global", "path": "/absolute/settings.json"}]}
  ],
  "capabilities": [
    {"kind": "mcp", "members": {"instance-from-live-catalog": "native-server-name"}},
    {"kind": "plugin", "members": {"instance-from-live-catalog": "native-plugin-id"}}
  ]
}
```

Use `claude`, `codex`, `opencode`, or `antigravity` adapters independent of instance
IDs. Claude JSON supports `mcpServers` and `enabledPlugins`; OpenCode JSON/JSONC
supports `mcp` and `plugin`; Codex TOML supports `mcp_servers`. Codex plugin identity
policy tables are not installed-plugin evidence. For Claude, include `.mcp.json`,
user/local MCPs in `~/.claude.json`, and settings that contain approval/disable lists.
Nested `projects.<path>.mcpServers` and project disable lists are detected but remain
unknown until the relevant project and native precedence are reviewed locally. Antigravity JSON/JSONC supports
`mcpServers` inventory only; its permissions, extensions and loading behavior need
current host/provider evidence. Antigravity remote MCP uses `serverUrl`, not a
Claude-style `url`. Verify the ACP runtime actually loads the selected source.
Unknown adapters remain manual. Do not feed
transcripts, auth stores, instruction Markdown or plugin directories to the parser.
Codex TOML needs Python 3.11+; all other runtime code remains Python 3.10+.

## Plan changes

Choose the owner's desired capabilities and access boundaries. Retain intentional
provider differences. Never copy permission expressions between providers, infer
broad allows from tool frequency, disable approvals/sandboxing, or copy secrets to
make a matrix look uniform. A provider-specific unsupported capability is a valid
result. Use environment or secret-manager references where the provider supports
it. Verify exact syntax, scope and version against primary documentation.

For each writable native settings file, prepare a separate candidate preserving
unrelated values and comments. Show a locally redacted diff, the reason for every
change, its access effect, and any new executable, network connection or credential
exposure. Candidates, inventories, plans and backups are private local artifacts;
keep them out of commits and remote reviews. Do not download plugins or execute MCP
launchers during inventory. Plugin installation, skill adapter installation and
instruction/hook edits require their own concrete proposals and authorization;
this helper only replaces existing native settings files.

Run one plan per file, with canonical absolute, non-symlink paths. If an OS alias
such as macOS `/tmp` or `/var` appears, inspect its real destination and use that
canonical path consistently in the proposal and plan. The helper never silently
follows a write-target alias.

```sh
python3 PKG/scripts/align.py plan --adapter claude \
  --target /absolute/settings.json --candidate /absolute/candidate.json \
  --allow-key /permissions/allow --out /absolute/private-plan.json
```

Supported roots: Claude `permissions`, `mcpServers`, MCP approval/disable settings,
`sandbox`; Codex approval/sandbox/MCP/plugin settings, including those
policy fields inside named `profiles`; OpenCode `permission`, `mcp`, `plugin` and
agent-specific `permission`; Antigravity `mcpServers`. Profile/agent model changes
and Claude `projects`/`hooks` writes are excluded. Propose those edits separately when
needed, with the same approval, backup and validation requirements.

`--allow-key` repeats for every changed JSON pointer, using `~1` for `/` and `~0`
for `~`. Arrays are reviewed as a whole. OpenCode permission-pattern reordering counts
as a change to its parent object because pattern precedence depends on order. The helper rejects changes outside its
supported settings roots and mismatched change lists. It also refuses newly added
known broad permission/sandbox patterns, including supported policy overrides.
The helper also conservatively refuses removal of exact Claude deny/ask rules,
protected sandbox fields, explicit Codex policies, and OpenCode deny/ask actions,
including supported overrides. It detects distinct broad Claude rules, sandbox
`allowUnsandboxedCommands` and `autoAllowBashIfSandboxed`, auto-approval of project
MCPs, and added Codex workspace networking.
Plans and receipts retain before/after risk counts and explicitly say permission
semantics are not evaluated. Unlisted options, changed glob/command meaning, deny
precedence and inheritance can still loosen access without a finding. Review every
changed key and its native defaults before approving; equal counts prove nothing. Private plans contain paths,
changed keys, hashes and file identity, but no configuration values. The public
receipt contains the digest, changed-key count, risk code counts and validation limits. Plans and backups are 0600,
created exclusively, and never overwrite existing files. The helper does not
enforce repository exclusion; choose private storage outside every checkout. The settings files must
be owned regular files without hard links or group/other write access.

## Apply approved changes

An `align` request authorizes inventory and preparation. `apply` needs owner approval
of the concrete plan and its digest, unless that exact plan was already authorized.
A digest is an integrity check, not evidence that the owner approved it. Repeat no
approval already given for the same unchanged plan. Stop on a denied write and
report it; do not reroute it through another tool.

Stop concurrent settings writers before applying, including provider processes that
rewrite their configuration. Apply is POSIX-only, one existing file per invocation:

```sh
python3 PKG/scripts/align.py apply --plan /absolute/private-plan.json \
  --approval APPROVED_DIGEST --backup /absolute/new-backup
```

The helper revalidates original/candidate bytes, changed keys, identity and mode,
backs up original bytes, stages the exact candidate, checks the target again, and
replaces it atomically. Directory descriptors prevent symlink ancestor redirection.
Conflict checks are optimistic; another writer can still race the final check and
replace. This is not a multi-file transaction. If a later file fails, report the
already-applied files and retain backups. On an error, inspect target and backup
before reporting writes or restoring; never blindly overwrite a concurrent edit.
Propose restoration from the exact backup when needed and honor existing approval.

After applying, parse and audit again, then verify the provider loads the expected
layer in a fresh session. With authorization, check MCP authentication and a minimal
read-only tool call; verify installed plugin/skill discovery and approval behavior.
T3-injected tools need a T3 session check. Report comparison, proposal, owner approval,
files applied, backups, parser results and live acceptance separately. Do not claim
aligned effective permissions from file equality, fixture tests or a running process.

Scalar-to-object OpenCode permission rewrites may be conservatively refused.
Review such native shape changes separately instead of treating the refusal as
proof that the proposed grant is broad.
