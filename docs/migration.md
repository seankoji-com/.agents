# Migration from claude-plugins

This is a T3-native port of the seven-plugin catalog at
[`edddf829de3c87515b44e8b816eaf03878e3f9de`](https://github.com/seankoji-com/claude-plugins/tree/edddf829de3c87515b44e8b816eaf03878e3f9de).
The source revision and copied-file hashes are recorded in
[`migration/source.json`](https://github.com/seankoji-com/t3-plugins/blob/master/migration/source.json).
The original MIT license is retained.

## What moves where

| Original | T3 entry | Migration decision |
| --- | --- | --- |
| imps | `imps` | Keep the existing T3 state engine; add audit, issue-set, blast-radius, and PR handoff modes |
| elephant-goldfish | `elephant-goldfish` | Retain discovery state, templates, publication helper, deterministic handoff and hashes; cold review uses T3 |
| prompt-builder | `prompt-builder` | Provider-neutral drafting; retain frozen-suite evaluator and comparable-evidence rules |
| ape | `ape` | Retain research/clone/cleanup helpers; replace Claude Workflow fan-out with optional T3 tasks |
| babysitter | `babysitter` | Retain GitHub/worktree helpers; T3 owns watches and any explicitly requested scheduled sweeps |
| claude-tuneup | `agent-tuneup` | Retain Claude transcript scanner; add read-only configuration adapters, with explicit format limits |
| offload-sidecar | `offload-sidecar` | Retain the MCP engine; add a one-shot file-request adapter for any provider's shell |

## Deliberate changes

Claude slash commands become entry operations. Use `t3-plugins prompt PLUGIN OPERATION`
and paste the result into T3. Old command names are not installed as hidden aliases.
`imps:imp-agency` becomes `imps audit`, and `imps:issue-mode` becomes `imps issues`.

Provider CLI brokers, fixed Haiku/Sonnet/Opus routes, and Claude Workflow scripts are
not copied as active orchestration. T3 already owns those responsibilities. The
standalone babysitter event script remains available for legacy use, but T3 playbooks
explicitly use host watches instead. Existing repository review requirements still apply.

The cold-reader review is a T3 child instructed to read only the document. It is not
a filesystem-isolated sandbox. The sidecar keeps its original local/cloud engine
boundary; “any T3 provider” does not mean every provider is a sidecar backend.

Automatic writes to personal learnings, dotfiles pushes, and permission broadening
are removed from the default workflows. State and settings are not migrated silently.
Your old Claude installation can remain alongside this one, but its slash commands
continue to use the old package.

## Scope of parity

All seven use cases have T3 entry points and working local helper paths. This is a
behavioral port, not byte-for-byte command compatibility. The original 1,700-line imps
command is replaced by the existing T3 core and focused playbooks. Legacy provider
brokers and persona-specific execution are intentionally replaced, not claimed as
portable implementations. Live parity across every provider remains experimental.
