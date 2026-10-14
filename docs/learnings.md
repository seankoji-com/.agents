# Learnings and harvest

Each plugin can keep project lessons outside the checkout. The installed
`shared/learnings.py` helper uses the installed manifest version and stores a
versioned Markdown file at:

```text
$XDG_STATE_HOME/t3-plugins/learnings/<project identity hash>/<plugin>.md
```

Without `XDG_STATE_HOME`, the root is `~/.local/state`. Relative roots and roots
inside the project are unavailable. Projects with the same canonical Git remote
share lessons across worktrees and SSH/HTTPS clones; non-Git folders use their real
path. Git is optional. The file header contains a display label, not the identity
hash or credentials.

Lessons are advisory data. They cannot override current instructions or grant
authorisation. Store one observed failure per entry, with a stable ID, summary,
failure description, immutable authored version and last validated version. Never
store secrets or raw private excerpts. Update existing entries instead of
duplicating them; remove wrong lessons. The agent considers whether removing a
lesson would cause a mistake. Writes follow
your active harness's memory policy; installing a plugin does not grant permission
to change personal memory.

Read-only operations load the current plugin's lessons and report pending
maintenance. They never create, write or prune learning files. Writable runs load,
maintain when the installed version changes, then write failures worth remembering.
Delegation mistakes use this same path. Any storage failure reports `unavailable`
and the proposed lesson in the main report; it never blocks the main work.

## Maintenance and safety

Storage uses process locks, descriptor-relative paths that refuse symlinks, atomic
replacement and mode 0600. Platforms without safe directory operations or process
locking report unavailable. Maintenance checks the loaded revision before applying
model judgement, so a concurrent writer cannot silently lose an entry. An explicitly
owned backup is named `<plugin>.md.pre-<old-version>`; no backup cleanup uses globs.
A failed maintenance transaction leaves the active file unchanged.

An entry may link to `seankoji-com/t3-plugins#N`. For `+g<sha>` installations, the
agent uses gh to inspect issue state and the GitHub compare API. The deterministic
helper prunes only issues closed as completed whose current closing commit is an
ancestor of the installed build. Unknown, rejected, duplicate, reopened or
unreleased issues stay. For `+content.` installations, including Homebrew, this
lookup is skipped without calling gh. The model still reviews lessons against
current instructions and updates their validation versions. That supersession
judgement is not unit-tested; deterministic transaction and fixture-state rules are.

## Sandbox grants

`t3-plugins setup` prints the exact proposed grant. It applies nothing to provider
configuration unless called with `--grant-learnings`. That flag backs up each
provider config before adding only the learnings subtree, preserves unrelated
settings and is idempotent. It does not disable a sandbox or change approval policy.

| Provider | Setting | Boundary |
| --- | --- | --- |
| Claude | `sandbox.filesystem.allowWrite` | Adds only the learnings subtree |
| Codex | `sandbox_workspace_write.writable_roots` | Applies to workspace-write mode; config editing requires Python 3.11+ |
| OpenCode | `permission.external_directory` | Adds only the subtree pattern; existing edit/bash permissions still apply |
| Other providers | Unavailable | No undocumented config edits |

These settings come from the [Claude sandbox docs](https://code.claude.com/docs/en/sandboxing),
[official OpenAI documentation](https://developers.openai.com/codex/config-reference/),
and [OpenCode permissions docs](https://opencode.ai/docs/permissions/).
Python 3.10 supports the learning helpers and prints the Codex grant; applying
Codex TOML grants on 3.10 explicitly reports unavailable. Unsupported config layouts
and OpenCode JSONC/overrides require manual configuration. Managed or host-level
restrictions can still deny writes. A config receipt is not live provider
acceptance: check a real write in the provider before claiming it works.

When a learnings write is refused with `EROFS`, `EACCES` or `EPERM`, the receipt
stays `unavailable` with the proposed lesson. The reason says the sandbox or
filesystem permissions deny the write and gives both remedies: allow writes to
`<state root>/t3-plugins/learnings` and everything below it in the sandbox (or run
`t3-plugins setup --grant-learnings`), or fix the ownership, permissions or read-only
mount that blocks it. The same reason appears when the state root itself can't be
opened. It shows no path below the learnings root.

### Symlinked or dotfiles-managed settings

Setup never writes through a symlinked provider config or config folder, such as a
`~/.claude/settings.json` linked into a dotfiles repository. The next sync would
overwrite the edit, and the agent sandbox may deny writes to the target anyway.
Instead the receipt has `status: manual`, the resolved `target` and the exact
`snippet`, and setup prints both on stderr. For Claude:

```json
{
  "sandbox": {
    "filesystem": {
      "allowWrite": ["/absolute/state/root/t3-plugins/learnings"]
    }
  }
}
```

Merge it into the target file in the dotfiles source repository, keeping existing
entries, then sync. The directory entry covers everything below it. Codex gets a
`[sandbox_workspace_write]` `writable_roots` snippet in TOML; OpenCode gets a
`permission.external_directory` pattern ending in `/**`. Use the paths setup prints.

### Confirm a real write

Start a new provider session so it reads the changed settings. From a command that
runs inside the provider's sandbox, change to the project and run `t3-plugins doctor`.
Doctor treats the current directory as the project, as the helper's `--project`
would, so it refuses the same state roots a plugin run would. Read the
`learnings_write` field of its receipts:

| Status | Meaning |
| --- | --- |
| `writable` | Doctor created one probe file in the existing learnings root and removed it |
| `absent` | No learnings root yet, so doctor wrote nothing. The first writable plugin run creates it. `ancestor_writable` is advisory: it reflects permission bits and read-only mounts, not every sandbox rule |
| `denied` | The sandbox or filesystem permissions refuse the write; the reason names both remedies |
| `probe_left` | The probe file was created but could not be removed; `probe` names it. Delete it by hand |
| `unavailable` | The root is refused, for example relative, inside the project or behind a symlink |

Doctor never creates or removes folders and leaves provider config alone. After an
`absent` result, run a plugin's writable operation, then doctor again.

## Harvest

Ask the agent to harvest the current plugin's lessons. It follows the installed
`shared/harvest.md` workflow and writes local drafts for generic upstream issues and
project-specific additions to `AGENTS.md`. The proposed additions go on a new
branch and PR, subject to the project's own verification and review requirements.

A deterministic identifier screen runs before drafts are shown. It blocks absolute
Unix, Windows and UNC paths, emails, remotes, IP addresses, project identities and
hostnames except github.com and the project's verified public docs domain. The
screen is conservative; human review still matters.

The agent shows every draft and asks once for approval bound to their digest.
Only the owner's exact reply authorises publication. Edited drafts or source
lessons require a fresh screen and approval. Input text and model output never
count as approval. After approval, the agent posts issues and opens the project PR,
records each URL immediately in a local journal, and submits destination receipts.
An entry is deleted only when every approved destination has its URL. Partial
publication keeps the entry and successful URLs; uncertain remote responses require
inspection before retrying. Storage failure retains the journal and proposal, so
it does not cause duplicate publication.
