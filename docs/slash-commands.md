# Slash commands across providers

`t3-plugins setup` writes one small skill per workflow, so you can type `/` in T3,
pick `t3-imps`, and add the task. Every provider reads the same installed entry file,
so the workflow is identical whichever model you choose. The skills are `t3-imps`,
`t3-ape`, `t3-babysitter`, `t3-elephant-goldfish`, `t3-agent-tuneup` and `t3-ralph`.

`setup` installs the whole catalog and writes skills into the four default folders
below. `t3-plugins setup imps` does one plugin; repeated `--root PATH` replaces the
defaults. It won't overwrite a skill it didn't write or one you edited: it stops, and
the receipts it already printed stay valid, so fix the conflict and run it again. Run
`setup` again after every upgrade.

To install snapshots and skills separately, or into one folder at a time:

```sh
t3-plugins install imps
t3-plugins skills install imps --root ~/.agents/skills
t3-plugins skills install imps --root ~/.claude/skills
t3-plugins skills install imps --root ~/.gemini/config/skills
t3-plugins skills install imps --root ~/.config/muse/skills
```

Run these on the machine where your T3 provider runs tools. With a custom prefix, pass
the same `--prefix PATH` to both `install` and `skills`. Leaving out `imps` installs
skills for the whole catalog, after `t3-plugins install`; it stops at the first plugin
that isn't installed. Each output line is a receipt, so a partial run is safe to retry.

Worker definitions are not skills. They go under the
[agents root](cli.md#custom-locations), never into a skill folder, and only a
plugin's own coordinator loads them into a task brief. The agents root is a
t3-plugins convention, not a native agent directory for any provider.

## Discovery roots

| T3 provider | User skill directory | Notes |
| --- | --- | --- |
| Codex | `~/.agents/skills` | Use the agent's configured home if it differs. |
| Claude | `~/.claude/skills` | A custom Claude home uses its own `skills/` directory. |
| OpenCode | `~/.agents/skills` or `~/.config/opencode/skills` | Custom configuration can change discovery. |
| Cursor | `~/.agents/skills` | T3 also discovers provider-specific roots. |
| Antigravity | `~/.gemini/config/skills` | Its global discovery does not read `~/.agents/skills`. |
| Muse | `~/.config/muse/skills` | Muse's own managed root; it also reads `~/.agents/skills`. No T3 composer picker (below). |

Discovery is provider-owned. See
[Claude discovery](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/provider/Drivers/ClaudeSkills.ts),
[Cursor discovery](https://github.com/pingdotgg/t3code/blob/main/packages/provider-cursor/src/server/skills.ts),
[Antigravity's guide](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
and [OpenCode's skills guide](https://opencode.ai/docs/skills/).
Check custom instances and older versions rather than assuming one shared root.
[Pi uses native skill discovery](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-pi.md).
[Muse skills do not appear in T3's composer `$` menu, but Muse still loads
them itself](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-muse.md).
Setup therefore installs adapters into Muse's managed root
(`~/.config/muse/skills`, honoring `XDG_CONFIG_HOME` only when you pass that root
explicitly), where `muse skills list` shows them and `muse skills validate`
accepts the generated adapter. In a Muse thread, name the skill in your message
(for example `use t3-imps to run doctor`), or use
`t3-plugins prompt imps OPERATION` and paste its output. The installer cannot add
a picker to a provider integration that does not expose one. Muse also discovers
`~/.agents/skills`, so the same adapter can appear twice in `muse skills list`
diagnostics as shadowed; both copies read the same installed entry.

## Invoke and refresh

Turn on **Settings > General > Show skills in slash menu**, then run **Restart agent
session** from T3's command palette. Type `/`, select `t3-imps`, and add an operation:

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

Check each provider you use: find `t3-imps` in the picker, send `$t3-imps doctor`,
and read the entry path and T3 capabilities it reports. Installing a skill and passing
unit tests don't prove the provider will invoke it.

## Ownership and removal

Adapters follow the plugin's `current` link, so upgrades and activation switches
use the selected snapshot. Reinstall adapters if the prefix moves. They do not
change provider settings or permissions. Existing skill folders, edited adapters,
and symlinked skill paths are refused. For a symlinked root, pass its real directory.
The one exception is a root-owned system link that no other user can replace, such
as macOS `/var` or `/tmp`.
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
