# Slash commands across providers

The editable skill bodies live at `~/.agents/skills/<name>/SKILL.md`.
The active workflows are `imps`, `plan`, `ape`, `babysitter`, `agent-tuneup`,
`ralph`, `focus-group`, `bug-report` and `tests-omg`; `unslop` is a prose skill.
Install the stable resolver and adopt an existing directory using
[getting started](getting-started.md). Ordinary body/helper edits need no install,
release, version bump or commit before local testing.

## Discovery roots

The source-owned `discovery.json` declares shared discovery or exact native links.
It contains no provider settings or credentials.

| Provider | Registration |
| --- | --- |
| Codex, OpenCode, Muse, Grok | Shared `~/.agents/skills` |
| Claude | Owned per-skill links under `~/.claude/skills` |
| Antigravity | Owned per-skill links under `~/.gemini/config/skills` |
| Gemini CLI | Owned per-skill links under `~/.gemini/skills` |

Custom provider homes need an explicit supported registry change and collision
check. Existing personal, marketplace and vendor stores keep their owners.
Cursor management is outside this migration's scope.

Worker definitions are package data, not native skills or provider agents.
Only the workflow coordinator loads its pinned definitions into task briefs.

## Invoke and refresh

Enable **Settings > General > Show skills in slash menu**, restart the T3 agent
session, then select the explicit skill mention:

```text
$imps doctor
$imps run fix the parser
$plan investigate the migration risks
```

The portable description owns argument hints. `plugin.json` owns operation
routing. A helper-backed skill first calls `$HOME/.local/bin/agents start NAME`
and reloads the returned pinned body and manifest. Its helpers, playbooks and
workers all use that pin. A prose-only exemption needs no launcher.

After adding, renaming or deleting a skill, the owner runs `agents discovery` to
reconcile native links, then refreshes the provider session. Editing an existing
body or helper needs no discovery reconciliation. Use an explicit skill mention
to distinguish `plan` from built-in commands. If a provider still shadows a name,
record the collision and stop that name's rollout.

Discovery remains provider-owned. A link receipt or unit test does not prove live
loading. In a fresh session, verify one effective skill per required name, run its
bounded operation, and inspect the returned pinned body/helper/worker identities.
Providers without a composer picker may accept an explicit request such as
`use imps to run doctor`; verify actual loading there separately.

## Ownership and removal

Receipts outside the checkout record only the exact links owned by `.agents`.
Reconciliation preflights every destination before applying changes. An unowned
directory or link is a collision even if its target looks useful; preserve it and
resolve ownership explicitly. Never delete a whole native skill root.

Canonical skills are full editable bodies. No `agents/openai.yaml` is generated.
Custom metadata and supporting files remain source assets; adoption preserves or
reports them rather than overwriting them.

Deleting a canonical skill and running owner reconciliation removes only its
unchanged owned native links. Existing immutable pins and old jobs remain usable.
Retired `elephant-goldfish`, `offload-sidecar` and `prompt-builder` packages are
legacy dependencies, not newly registered skills. See
[legacy compatibility](cli.md#legacy-compatibility).
