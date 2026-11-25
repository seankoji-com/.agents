# Issue status

Keep the repository's linked project board true as work moves. The board is
optional: a missing board, field, option or permission is reported and never
blocks the work.

## Transitions

| Event | Status | Delivery |
| --- | --- | --- |
| Work starts on the issue | `In Progress` | Any |
| A PR that closes the issue opens or is linked | `In Review` | PR repositories |
| Production is verified | `Done` | PR repositories |
| The direct publish is verified | `Done` | Direct-publish repositories |

Assign the operator once, when the issue has no assignee. Never reassign.
Never move `In Progress`, `In Review` or `Done` backwards. `Done` is the
logical production state; a configured release option may carry its name.

## Rules

1. **Identify the issue.** Use the explicit issue in the request, then the PR's
   closing references, then the issue named in the plan. `Refs #N` is not a
   closing reference. If none is unambiguous, report `issue status: untracked`
   and continue.
2. **Use the linked project.** Take the repository's linked project. If there
   are several, require an explicit project number rather than guessing. If
   there is none, report the gap and continue.
3. **Use the board's names.** Match `Status` and its options case-insensitively.
   A board without the field or the needed option is a reported gap.
4. **Assign the operator.** Use the verified human on whose behalf the skill
   runs, never a bot. If the operator cannot be verified, leave assignment
   unchanged and report it. Start-time assignment does not depend on board
   access; an unreadable board still reports it.
5. **Move forward only.** Skip a transition that would move an issue backwards.
   The helper never resets an issue; a reopened issue returns to `In Progress`
   only after an explicit manual status change. It re-reads the item before
   writing, but an external writer can still race between that read and the
   write.
6. **A PR means closing issues.** A draft PR counts. A PR that only says
   `Refs #N` moves nothing. Run `pr` with the PR number; the helper reads its
   closing references and ignores issues outside this repository.
7. **Done needs production.** Merge alone never sets `Done`. With no production
   signal, leave the issue `In Review` and report the missing evidence.
8. **Direct publish.** Skip `In Review`; set `Done` after the publish and its
   post-publish check are verified.
9. **Retry once.** Retry a transient read once, then report the gap. Never
   replay a status write.
10. **Check the board's own automation.** GitHub's default project status moves a
    linked PR to `In Review` and a closed issue to an option named `Done`. That
    is not production evidence, and renaming the option does not stop it:
    GitHub targets the name `Done`. A repository that reserves `Done` for
    production omits that option, maps `done` to its release option, and keeps
    the config below. If a close already set `Done`, report the board automation
    and the missing production evidence; never move the issue back.

## Configure option names

A board whose names differ from the defaults commits `.github/issue-status.json`:

```json
{"start": "In progress", "pr": "In review", "done": "Released", "project": 3}
```

`project` is optional and disambiguates several linked projects. The helper
reads this file from the target repository; `--config PATH` uses a local file
instead. Missing keys use `In Progress`, `In Review` and `Done`. A repository
that reserves production for `Done` should keep no option named `Done` and map
`done` to another option, such as `Released`. A config read error, invalid JSON
or duplicate status name is reported without changing the board.

## Run it

The ship skill's `scripts/issue_status.py` resolves the project, status field
and options, then performs the transition. It prints one line per issue and
exits 0 when the board is untracked. Run it from the ship skill folder.

```sh
# Work starts: assign when unassigned and set In Progress.
python3 scripts/issue_status.py start --repo OWNER/REPO --issue N

# A PR opened or linked: only its closing issues move.
python3 scripts/issue_status.py pr --repo OWNER/REPO --pr N

# Verified production or direct publish: state the evidence.
python3 scripts/issue_status.py done --repo OWNER/REPO --issue N --verified URL
```

Add `--operator LOGIN` when the authenticated account is not the operator, and
`--project NUMBER` when the repository has more than one linked project. Use
`--dry-run` to print the plan without changing GitHub.

`start` and `done` accept repeated `--issue`. `pr` requires `--pr` and derives
the issues from its closing references.

## Handoff

Report each result, or `issue status: untracked` with the gap. Name the issue,
the transition, the project and what is missing. This bookkeeping never fails
the main work.
