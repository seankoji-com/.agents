# Slash commands across providers

Install a portable skill adapter for each plugin you want in T3's composer. The
adapter reads the same installed entry file regardless of the selected provider.
Skill names use the `t3-` prefix: `t3-imps`, `t3-ape`, `t3-babysitter`,
`t3-elephant-goldfish` and `t3-agent-tuneup`.

For one-step user setup after installation, use `t3-plugins setup`
(`python3 bin/t3-plugins setup` from source). For Homebrew, use
[catalog v0.5.0 or later](getting-started.md#homebrew-release-channel).
It installs the full catalog and adapters into the three default roots below.
Use `t3-plugins setup imps` for just imps, or repeat `--root PATH` for custom roots.
Setup preserves unowned or edited adapters and stops on a conflict. Earlier receipts
remain valid; resolve the conflict and retry. Run setup again after updating the installed package.
For snapshots only or individual adapter roots, use these separate commands:

```sh
t3-plugins install imps
t3-plugins skills install imps --root ~/.agents/skills
t3-plugins skills install imps --root ~/.claude/skills
t3-plugins skills install imps --root ~/.gemini/config/skills
```

Run these on the machine hosting your T3 environment. For a custom package prefix,
pass the same `--prefix PATH` before both `install` and `skills`. Omit `imps` to
install adapters for the entire catalog after `t3-plugins install`. It stops at the
first missing installation. An all-catalog operation can
partially succeed; each output line is a receipt and retries are safe.

## Discovery roots

| T3 provider | User skill directory | Notes |
| --- | --- | --- |
| Codex | `~/.agents/skills` | Use the agent's configured home if it differs. |
| Claude | `~/.claude/skills` | A custom Claude home uses its own `skills/` directory. |
| OpenCode | `~/.agents/skills` or `~/.config/opencode/skills` | Custom configuration can change discovery. |
| Cursor | `~/.agents/skills` | T3 also discovers provider-specific roots. |
| Antigravity | `~/.gemini/config/skills` | Its global discovery does not read `~/.agents/skills`. |

Discovery is provider-owned. See
[Claude discovery](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/provider/Drivers/ClaudeSkills.ts),
[Cursor discovery](https://github.com/pingdotgg/t3code/blob/main/packages/provider-cursor/src/server/skills.ts),
[Antigravity's guide](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
and [OpenCode's skills guide](https://opencode.ai/docs/skills/).
Check custom instances and older versions rather than assuming one shared root.
[Pi uses native skill discovery](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-pi.md).
[Muse currently does not expose skills in T3's composer](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-muse.md).
The installer cannot add a picker to a provider integration that does not expose
skills. Use `t3-plugins prompt imps OPERATION` and paste its output there.

## Invoke and refresh

Enable **Settings > General > Show skills in slash menu**, then use **Restart agent
session** in T3's command palette after installation. Type `/`, select `t3-imps`,
and append an operation:

```text
$t3-imps doctor
$t3-imps run fix the parser
$t3-imps --personas 42 43
$t3-imps checklist path/to/audit.md
```

Each adapter's description includes argument hints, such as
`study <GitHub URL> [focus]` or `audit --provider <name> --settings <path>`.
Angle brackets mark required values; square brackets mark optional arguments.
The hints live in the portable `description` frontmatter field. Run
`t3-plugins setup` again and restart the agent session to refresh existing adapters.

Selecting from `/` inserts a skill mention. `$t3-imps` is the portable invocation.
Provider-native slash commands must start the message. T3 accepts skill mentions on any line, but put the imps
mention first and its operation or task after it so scope routing is unambiguous. See
[T3's composer guide](https://github.com/pingdotgg/t3code/blob/main/docs/user/composer.md#commands-and-skills).

For OpenCode, refresh provider status after configuration changes. Its helper may
need to become idle before reloading configuration; an external server can need a
restart. See the [T3 OpenCode guide](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-opencode.md#refresh-models-commands-and-skills).

Verify with each selected provider: find `t3-imps` in the picker, invoke `doctor`,
and check the entry path and reported T3 capabilities. Adapter installation and
unit tests do not establish live invocation or provider parity.

## Ownership and removal

Adapters follow the plugin's `current` link, so upgrades and activation switches
use the selected snapshot. Reinstall adapters if the prefix moves. They do not
change provider settings or permissions. Existing skill folders, edited adapters,
and symlinked skill paths are refused. For a symlinked root, pass its real directory.
For `setup`, custom roots replace all defaults: repeat `--root` for each real
provider directory you want to populate. Setup also removes unchanged adapters for
[retired plugins](getting-started.md#retired-plugins) from the same roots.

If installation is interrupted between writing the skill and its ownership receipt,
the next attempt may report an unowned or modified adapter. Inspect and back up that
adapter directory, then remove only its generated `SKILL.md` and
`.t3-plugins-skill.json`; remove the directory only when empty, and retry. Preserve
any operator-added files. The installer deliberately does not guess ownership.

```sh
t3-plugins skills uninstall imps --root ~/.agents/skills
```

Repeat for each installed root. Removal preserves operator-added files and never
removes the plugin snapshot or run state. Remove adapters before uninstalling the
plugin, otherwise they report a missing entry.
