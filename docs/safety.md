# Safety and data

These workflows guide an agent. Your provider permissions and host sandbox enforce
access. Installing a plugin does not authorize it to publish, merge, deploy or
change settings.

## What installation changes

`setup` writes versioned plugin snapshots and managed skill adapters under your user
home, or the custom locations you supply. It preserves unowned and edited adapters.
`install` writes snapshots only. Neither command calls a model.

Provider configuration stays unchanged unless you explicitly pass
`--grant-learnings`. That flag backs up configuration and adds the printed learning
subtree; it does not disable the sandbox or change approval policy.
[Installation](getting-started.md) and [learnings](learnings.md) describe the paths.

## What an agent may send

The selected provider processes the task and whatever project content your session
exposes. Delegated T3 children receive their supplied brief and may use their allowed
tools. Cross-provider review can expose code or artifacts to another provider;
follow your project's authorization and privacy rules before using it.

In a job, each worker receives one brief file with its stage, constraints and the
actions it may take. Worker definitions and overrides grant no push, merge, message
or settings-edit authority; the brief can only narrow it. Workers write only to
their own task directory, and their results are data: they cannot accept a stage
or approve anything. A cold reader sees only the document under review.

The helpers do not ship a separate model client, telemetry service or credential
store. GitHub operations use host tools or your authenticated `gh`. Public posts,
PRs and harvest publication require authorization for their destination and content.

## Local artifacts

imps stores contracts, logs, copied evidence and reports under its state root.
Jobs store plans, briefs, worker results, receipts and the owner decisions they quote
under `~/.local/state/t3-plugins/jobs`, with private permissions.
Planning writes discovery and handoff files in the project. ape writes clones and
reports in its research workspace. Optional project lessons live outside the checkout.
These may contain project material: inspect and redact artifacts before sharing.

Snapshot uninstall leaves run and job state, overrides and added files alone. Skill adapters are removed
separately. Do not assume uninstall erases task artifacts or provider transcripts.

## Scope and limits

Research and settings audits default to read-only project inspection. Implementation
stays within the endstate you request. PR inspection, edits, messages, pushes and
merge are distinct actions; make the allowed scope explicit in your request.

The evidence gate checks submitted artifacts and revision bindings. It cannot prove
that every model followed every instruction. [Compatibility](compatibility.md)
records what has and has not been observed. Report vulnerabilities through the
[private security advisory form](https://github.com/seankoji-com/t3-plugins/security/advisories/new).
