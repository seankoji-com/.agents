# Migration from claude-plugins

## Plugin version 1.0.0

This major version removes workflow machinery while retaining authorisation,
revision-bound evidence, locking and atomic storage. These are design hypotheses
about capable orchestrators, not claims that every model completes every workflow.
The stage 5 benchmark compares the old and new imps on fixed tasks; live acceptance
is limited to its recorded runs.

| Removal | Reason | Upgrade step |
| --- | --- | --- |
| offload-sidecar, including deterministic transforms and receipts | Retired on purpose. The separate transform protocol assumed the orchestrator needed a broker for local operations. | Use local tools for deterministic transforms and T3 delegation for judgement. Run `t3-plugins setup` to remove owned, unmodified retired adapters; modified or unrelated files are preserved. Use `t3-plugins uninstall offload-sidecar` for its installed package. |
| prompt-builder | Retired by the owner. Frozen prompt evaluation is no longer an active catalog workflow. | Use the active agent for drafting. Run `t3-plugins setup` for owned adapter removal and `t3-plugins uninstall prompt-builder` for the retired installed package. |
| imps dispatcher, claims and generation counters | The orchestrator now chooses its next step. The removed action loop encoded the hypothesis that the model needed a second scheduler to direct each action. | Use `snapshot`, named evidence submissions and `validate`; see the [API migration](imps-gate-migration.md). Process locking and atomic storage remain. Old run-state major-version-1 runs require the previous installed package; activate it to inspect, resume or cancel them. No state conversion occurs. |
| Repeated delegation rules | Multiple copies could drift without improving model decisions. | Follow the installed `shared/delegation.md` as the single contract, and discover the live catalog before selecting children. |

Install the new release into your chosen prefix, then run `t3-plugins setup` to refresh
skill adapters. Existing routing configuration is preserved. Review retained modified
adapters yourself before replacing them. The `1.0.0` plugin manifests do not create a
GitHub release: release tags use a separate series, set by the owner through the
Release workflow's `major` dispatch.

The historical compatibility ledger covers imps `0.1.0+ga50f506cd178` on T3
`0.0.46-nightly.20261008.2849`. It does not certify plugin version 1.0.0. See
[compatibility and evidence](compatibility.md) for the distinction between helper
tests and observed model workflows.

## Historical port: pre-1.0.0

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
and paste the result into T3, or install the [slash-menu skill adapters](slash-commands.md).
Old colon commands are not registered as hidden aliases.
`imps:imp-agency` becomes `imps audit`, and `imps:issue-mode` becomes `imps issues`.

Provider CLI brokers, fixed Haiku/Sonnet/Opus routes, and Claude Workflow scripts are
not copied as active orchestration. T3 already owns those responsibilities. The
standalone babysitter event script remains available for legacy use, but T3 playbooks
explicitly use host watches instead. Existing repository review requirements still apply.

The cold-reader review is a T3 child instructed to read only the document. It is not
a filesystem-isolated sandbox. The sidecar keeps its original local/cloud engine
boundary; "any T3 provider" does not mean every provider is a sidecar backend.

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

## imps workflow coverage

| Source behavior | T3 destination |
| --- | --- |
| Free-text brief, constraints, task graph and bounded diagnosis | `run`, brief probes, bug-fix playbook and core task engine |
| Numeric issue set and explicit issue-mode | `issues` and request classification |
| Discussion seed | `discussion`, retained source artifact and normal run |
| Checklist-file audit | `checklist`, non-executing parser and current-revision evidence |
| Whole-repo audit and remediation plan | `audit`, dimension coverage and checklist output |
| Blast-radius proof | `blast-radius` read-only consumer tracing |
| Optional five-persona panel | `--personas`, required core review perspectives |
| PR follow-up | `prs` handoff to the installed babysitter and T3 watches |
| Resume, cancellation, worktree isolation and review repairs | Core claims, task reconciliation and revision-bound evidence |
| Claude/Codex/OpenCode execution brokers | Replaced by T3 delegation; no provider CLI brokers |
| Automatic Discussion replies and persona account posts | Explicit authorization and actual remote receipts |
| Banners and automatic personal learning writes | Banners omitted; personal state is not written automatically |

The input playbooks use agent judgment; the core owns panel dispatch and readiness.
Deterministic tests cover classification, installed helper behavior, ownership, and review gates;
they do not prove live model execution of every new mode. See
[slash commands](slash-commands.md) for discovery and verification by provider.
