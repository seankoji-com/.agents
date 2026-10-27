# Learnings and harvest

Each plugin can keep project lessons outside the checkout. The installed
`shared/learnings.py` helper uses the installed manifest version and stores a
versioned Markdown file at:

```text
$XDG_STATE_HOME/agents/jobs/learnings/<project identity hash>/<plugin>.md
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

An entry may link to `seankoji-com/.agents#N`. For `+g<sha>` installations, the
agent uses gh to inspect issue state and the GitHub compare API. The deterministic
helper prunes only issues closed as completed whose current closing commit is an
ancestor of the installed build. Unknown, rejected, duplicate, reopened or
unreleased issues stay. For `+content.` installations, including Homebrew, this
lookup is skipped without calling gh. The model still reviews lessons against
current instructions and updates their validation versions. That supersession
judgement is not unit-tested; deterministic transaction and fixture-state rules are.

## Sandbox grants

`agents permissions` prints only the jobs, snapshots and locks write roots. It
changes no provider settings. Learnings live under jobs and use that grant.
The companion dotfiles renderer applies those narrow roots after verified cutover,
preserving unrelated settings and refusing grants that expose protected controls.
Keep launcher/updater installations, ownership receipts, active records, retained
legacy runtimes and service units outside every agent-writable root.

Native settings and host restrictions are separate. A configuration receipt does
not prove sandbox access. Inspect the provider's active restricted profile and
test it in a fresh session; do not disable sandboxing.

### Symlinked or dotfiles-managed settings

Change settings at their canonical source and sync through their owner.
Do not write through a native settings symlink or replace unrelated fields.
A denied write may also mean wrong filesystem ownership, permission bits or a
read-only mount; repair the actual cause rather than moving lessons into source.

### Confirm a real write

Start a fresh provider session. During an authorized lesson update, inspect the
helper's returned status and confirm the saved lesson under
`$XDG_STATE_HOME/agents/jobs/learnings`. A failed optional write reports
`unavailable` and the proposed lesson without blocking the main work.
Read-only operations never create probe lessons. Configuration, permission bits
or a test fixture alone do not establish live provider writes.

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
