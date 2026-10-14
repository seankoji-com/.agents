---
# Searches for "brew" or "install" should land here before the release runbook.
search:
  boost: 2
---

# Install and first ten minutes

By the end of this page you will have the six workflows installed, a readiness report
from your agent, and one real result. The terminal steps install files and never call
a model.

You need T3 Code with a working provider that can read files and run shell commands on
the machine where you install. Homebrew brings Python 3.12; from source you need Python
3.10+, or 3.11+ for agent-tuneup's Codex TOML support. Workflows that touch GitHub
(babysitter, and imps or ralph when they open a PR) also need Git, `gh` and `jq`.

## 1. Install with Homebrew

On macOS or Linux. The tap's stable formula is still v0.4.0, which predates ralph and
several commands on this page, so install the HEAD build until the next release
([why](#homebrew-release-channel)):

```sh
brew install --HEAD seankoji-com/tap/t3-plugins
t3-plugins setup
t3-plugins doctor
```

`setup` copies each workflow into `~/.local/share/t3-plugins/` and writes a slash-menu
skill for it into `~/.agents/skills`, `~/.claude/skills` and `~/.gemini/config/skills`.
It doesn't change provider settings or overwrite skills you edited. `doctor` should
print one line per plugin with `"ok": true` and exit 0. It checks the installed files,
not T3 or your model.

This is what those two commands printed in an empty home directory, from the current
source. Long lines are cut with `…` here; the [full transcript](assets/recordings/quickstart.txt)
is unedited.

```console
$ t3-plugins setup
{"ok": true, "data": {"action": "install", "plugin": "agent-tuneup", "version": "1.1.2+gc93f8a7d6b0c", …, "files": 73}}
{"name": "t3-agent-tuneup", "path": "~/.agents/skills/t3-agent-tuneup/SKILL.md", …}
…
{"learnings_grant": {"provider": "claudeAgent", "status": "proposed", …}}
$ t3-plugins doctor
{"plugin": "agent-tuneup", "ok": true, "errors": [], "scope": "installed file integrity and package currency; provider behavior not tested"}
…
{"plugin": "ralph", "ok": true, "errors": [], "scope": "installed file integrity and package currency; provider behavior not tested"}
```

<video controls preload="none" width="100%" poster="../assets/quickstart-terminal.png" aria-label="Terminal recording of t3-plugins list, setup and doctor">
  <source src="../assets/quickstart.webm" type="video/webm">
  <source src="../assets/quickstart.mp4" type="video/mp4">
</video>

The whole session as video, with real output at recorded speed and simulated typing
([MP4](assets/quickstart.mp4)). The transcript ends each command with how long it took.

The `learnings_grant` lines are proposals, not changes. Setup applies them only with
`--grant-learnings`; see [learnings and harvest](learnings.md#sandbox-grants).

## 2. Turn on the slash menu

In T3, open **Settings > General**, turn on **Show skills in slash menu**, then run
**Restart agent session** from the command palette. Type `/` in a thread attached to
your repository and you should see `t3-imps`, `t3-ape` and the rest. Choosing one
inserts a `$t3-…` mention; type the operation after it. Some providers find skills in
other folders; [slash commands](slash-commands.md) lists them.

## 3. Ask the agent if it's ready

```text
$t3-imps doctor
```

The agent checks Python 3.10+, Git, whether its state directory is writable, and T3's
live list of providers and tools. It reports which providers can run child tasks and
why others can't. It changes nothing. If your provider has no slash menu, run
`t3-plugins prompt imps doctor` in a terminal and paste the line it prints:

```console
$ t3-plugins prompt imps doctor
Read ~/.local/share/t3-plugins/imps/current/entry.md and run: doctor
```

### A real doctor run

This came from a live T3 thread on 14 Oct 2026, with Claude Sonnet 5.5 on this
repository. It took 22 seconds. This is an excerpt with shortened paths and a trimmed
provider list. It leaves out a failed `cli.py doctor --help` probe at 9 s, the
reference files read at 12 s, the Learnings row, and the Features and Compatibility
notes. The full transcript has every step:

```text
you        $t3-imps doctor
[4 s]      Read ~/.local/share/t3-plugins/imps/current/entry.md
[9 s]      T3 tool: orchestrator_capabilities
[12 s]     python3 --version; git --version; probe a write in ~/.local/state/t3-plugins/imps
[16 s]     python3 shared/learnings.py load --project .
[22 s]     imps doctor (read-only, nothing changed)

           | Python            | 3.15.0, which meets the 3.10+ requirement           |
           | Git               | 2.56.0                                              |
           | Installed package | imps 1.0.3+gf457538010a2, via current               |
           | State directory   | ~/.local/state/t3-plugins/imps exists but is not    |
           |                   | writable from this sandbox. The probe write failed  |
           |                   | with "Read-only file system".                       |
           | T3 capabilities   | Live and responding                                 |

           A run from this session would need a writable results directory outside
           the repository, passed as --state-root on every call. $TMPDIR is writable.

           Providers that can run child tasks: Codex, Claude, OpenCode, Antigravity,
           Muse Code. Cannot: Cursor, Grok, Pi (disabled in T3 settings, no executable).
```

That run shows what doctor is for. It found a real problem, a sandbox that blocks the
state directory, and said how to work around it before any task started. The same
command on Codex (GPT-6.1-Sol) reported the state directory as writable. The full
timelines are in the [Claude transcript](assets/recordings/t3-imps-doctor-claude.txt)
and the [Codex transcript](assets/recordings/t3-imps-doctor-codex.txt). The Codex one
leaves out a step that read the agent's private memory notes.

If a sandbox blocks the state directory, do what doctor suggested: pass `--state-root`
with a writable directory outside the repository. To keep the default path, allow writes
to `~/.local/state/t3-plugins/imps` in your provider's sandbox settings (for Claude,
`sandbox.filesystem.allowWrite`). `t3-plugins setup --grant-learnings` won't do this:
it covers only the learnings subtree ([sandbox grants](learnings.md#sandbox-grants)).

## 4. Get one real result

Pick the row that matches something you need today. Each starts from a T3 thread.

| Workflow | Send | What comes back |
| --- | --- | --- |
| [imps](plugins/imps.md) | `$t3-imps run fix the date parser: reject 31 April with a clear error, add a regression test, do not commit` | The change, a run ID, and a report mapping each requirement to the check that covered it at this revision. Anything unverified is listed as blocked. |
| [elephant-goldfish](plugins/elephant-goldfish.md) | `$t3-elephant-goldfish thinking retry-policy` | An interview, then `thinking/retry-policy/discovery.md`, `spec.md` with numbered acceptance criteria, and `handoff.md` for a fresh thread. |
| [ape](plugins/ape.md) | `$t3-ape study https://github.com/python/cpython how are parser error cases tested?` | A report pinned to the commit it read, with Adopt, Adapt and Reject sections, line citations, and one small experiment for your repository. |
| [babysitter](plugins/babysitter.md) | `$t3-babysitter pr https://github.com/OWNER/REPO/pull/12 inspect reviews and CI only` | Read-only: the blocking reviews and checks at the current head. Drop "inspect only" to let it fix and push, get the head reviewed by a second model, then merge. |
| [agent-tuneup](plugins/agent-tuneup.md) | `$t3-agent-tuneup audit --provider claude --settings .claude/settings.json` | Finding codes and locations in that file. Setting values never appear. |
| [ralph](plugins/ralph.md) | `$t3-ralph fix the parser and add regression coverage` | It asks you to choose an implementer and a grader from different model lineages, retries until the grader has no feedback, then opens a PR. |

imps and agent-tuneup are the quickest to try on a repository you already have. For
something that needs no model at all, agent-tuneup's helper runs locally on a
synthetic file. Real output:

```console
$ printf '%s\n' '{"permissions":{"allow":["Bash(*)"]}}' > example-settings.json
$ python3 "$(dirname "$(t3-plugins path agent-tuneup)")/scripts/audit.py" --provider claude --settings example-settings.json
{"ok": true, "provider": "claude", "findings": [{"code": "broad_execution_allow", "location": "permissions.allow[0]"}], "scope": "known-pattern audit; not a complete permission evaluation", "writes": 0}
```

[Your first imps run](first-workflow.md) walks through a fix from task to evidence.

## Homebrew release channel

The tap installs a `t3-plugins` command and an `imps` command, with Python 3.12 as a
dependency. What has been checked, as of 14 Oct 2026:

- Linux x86_64: Homebrew installs and runs the stable formula. For the HEAD build, the
  formula's install steps were replayed by hand (same directories, same wrapper, same
  Homebrew Python 3.12), and `setup`, `doctor` and `list` passed. `brew install
  --HEAD` itself was not run on Linux.
- macOS: the tap's CI installs and tests the stable formula on macOS 15.

On a HEAD install, `brew test t3-plugins` fails: the tap's test still expects the
retired prompt-builder plugin in `t3-plugins list`. Use `t3-plugins doctor` instead.

The stable formula is v0.4.0. It has `setup`, `doctor` and `prompt`, but not ralph,
`agents`, `resolve` or `adopt`, and it still ships two retired plugins. These docs
describe the current `master`, which `--HEAD` builds:

```sh
brew uninstall t3-plugins                        # only if v0.4.0 is installed
brew install --HEAD seankoji-com/tap/t3-plugins
t3-plugins setup
```

Plain `brew upgrade` checks a HEAD install for new commits only when a new stable
version appears. To update it now, run `brew upgrade --fetch-HEAD t3-plugins`, then
`t3-plugins setup` again. After the next
release reaches the tap, you can switch back to stable with `brew uninstall t3-plugins`
and `brew install seankoji-com/tap/t3-plugins`; `t3-plugins list` shows `ralph` on
either build that has it. Homebrew's own formula test runs in a temporary home, so it
never populates your skills; run `setup` yourself.

## From source

```sh
git clone https://github.com/seankoji-com/t3-plugins.git
cd t3-plugins
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
```

Use `python3 bin/t3-plugins` wherever these guides say `t3-plugins`. The installed
snapshots don't depend on the checkout staying where it is.

Other setup forms: `t3-plugins setup imps` installs one plugin and its skills;
`t3-plugins install ape` installs a snapshot without skills; repeated `--root PATH`
replaces the three default skill folders.

## Paths and remote environments

Snapshots live in `~/.local/share/t3-plugins/<plugin>/<version>/`. A `current` symlink
gives the agent a stable entry path. Each snapshot contains its required shared files;
it does not depend on the source checkout remaining in place. Worker definitions go
into a matching bundle under `~/.agents/agents/t3-plugins`, and jobs keep their state
in `~/.local/state/t3-plugins/jobs`. See [custom locations](cli.md#custom-locations)
to move the agents root.

Install on the machine where the T3 provider executes tools. A path on your laptop
is not automatically available to a remote provider. If its sandbox cannot access
the default prefix, choose an allowed location:

```sh
t3-plugins --prefix /tmp/my-t3-plugins install
t3-plugins --prefix /tmp/my-t3-plugins prompt ape doctor
```

Set `T3_PLUGINS_PREFIX` to reuse a custom prefix. Use a persistent writable directory
for long-term installations; `/tmp` is only a demonstration.

## Upgrade and rollback

```sh
git pull --ff-only
python3 bin/t3-plugins setup
python3 bin/t3-plugins doctor
```

Run these in your source checkout. With Homebrew, run
`brew upgrade --fetch-HEAD t3-plugins` for a HEAD install (or `brew upgrade t3-plugins`
for a stable one), then `t3-plugins setup` and `t3-plugins doctor`. Reinstalling identical files changes nothing. A changed package gets a new snapshot. Local edits
to that same snapshot cause refusal; `--force` is an explicit overwrite. Older
snapshots remain available, including any edits you made there.

Use a version printed by the installer to roll back:

```sh
t3-plugins activate imps VERSION
```

Activation changes only `current` and selects that version's worker bundle with it.
Jobs already running keep the versions they pinned. Running `install` again while
rolled back reports `reactivated`: the snapshot already existed and only `current`
moved back to it.

Run `doctor` afterwards. An intentional rollback reports `snapshot_outdated` when its
files differ from the bundled package. The Homebrew `imps` command warns about the
same mismatch and doesn't rewrite snapshots. Use the rolled-back snapshot's `cli.py`
when you need its matching state engine.

Installing the full catalog activates each plugin separately, so a failure can leave
a partial upgrade. Read the per-plugin receipts and retry after fixing the error.

### Retired plugins

offload-sidecar and prompt-builder left the catalog. `t3-plugins setup` removes their
slash-menu adapters when the adapter's own `.t3-plugins-skill.json` marker shows that
setup wrote it and the adapter is unchanged. It keeps edited adapters, symlinks,
adapters with corrupt markers, and any files you added, and prints a receipt for each.
Old snapshots stay until you remove them:

```sh
t3-plugins uninstall offload-sidecar
t3-plugins uninstall prompt-builder
```

`uninstall` accepts a retired name only when an installed manifest records it.

## Model routing

Delegating workflows choose child models from a routing config in your user
configuration directory: `$XDG_CONFIG_HOME/t3-plugins/routing.json`, or
`~/.config/t3-plugins/routing.json` when `XDG_CONFIG_HOME` is unset. Setup writes a
starting config from a capabilities response the agent saved to a file. It never
calls T3 or reads credentials, and it never replaces an existing config.

```sh
t3-plugins setup --capabilities caps.json
t3-plugins resolve reviewer --capabilities caps.json
```

The config lists tiers from cheapest to most capable, a T3 `runtimeMode` per provider,
and the `workhorse`, `reviewer` and `judgement` roles. Each role entry names a provider
instance, a model, its tier and its `lineage`. Setup's tiers and lineage labels are
guesses: edit them. Providers default to `auto`, except OpenCode, which defaults to
`full-access` with `"requireRuntimeMode": true` because its children otherwise stall
on permission prompts.

```json
{
  "schema_version": 1,
  "tiers": ["low", "medium", "high"],
  "providers": {
    "codex": {"runtimeMode": "auto"},
    "opencode": {"runtimeMode": "full-access", "requireRuntimeMode": true}
  },
  "roles": {
    "reviewer": [
      {"providerInstanceId": "codex", "model": "MODEL_ID",
       "tier": "medium", "lineage": "openai"}
    ]
  }
}
```

`resolve` prints the role's candidates that the capabilities file can run, in tier
order, and lists each configured entry it could not use with the reason. It never
substitutes a different model. When a child's mode is broader than the parent
thread's, T3 refuses it, so `resolve` lowers the mode to the parent's and adds an
`owner_action` saying which mode to switch the child to. A provider with
`requireRuntimeMode` (OpenCode, unless set to `false`) is listed as unavailable instead. With `--implementer-lineage
LINEAGE`, each candidate is marked `independent`: `true` for another known lineage,
`null` when either lineage is `unknown`, `false` for the same lineage. They print in
that order. A repository can override
roles, providers or tiers in `.t3-plugins/routing.json`; repository policy wins.

## Uninstall

Remove skill adapters from every root first, then remove snapshots. Omitting the
plugin name attempts removal for all bundled plugins in that root. It stops at the
first modified or unowned adapter with exit 2; preserve those files and resolve the
conflict before retrying. Retired adapters need their explicit name, or the owned
adapter cleanup performed by `setup`:

```sh
t3-plugins skills uninstall --root ~/.agents/skills
t3-plugins skills uninstall --root ~/.claude/skills
t3-plugins skills uninstall --root ~/.gemini/config/skills
t3-plugins uninstall ape

# For a Homebrew installation only:
brew uninstall t3-plugins
```

Snapshot removal deletes only manifest-owned, unmodified files for that plugin and
its worker bundle. Added files, local edits and worker overrides remain. A version
that a live or resumable job pins is refused with `version_referenced`. Repeat for other snapshots you want removed
before uninstalling the Homebrew command. Run and job state are never removed by uninstall.

Homebrew's `imps` command runs the packaged CLI directly. It does not silently
install, overwrite, or change your user snapshots.
