# Publishing source

Publish reviewed source through the repository's actual PR and required-check
policy. New Homebrew releases and version-bump-only automation are retired. The
existing tap formula remains installable for hosts that have not migrated.

1. Run the complete Python suite without reduced coverage or timeout changes,
   documentation checks and strict site build. Verify the installed artifact and
   disposable-home migration/recovery fixtures. Inspect changed docs at desktop
   and mobile widths.
2. Obtain the required independent review at the exact final revision. Refresh
   the remote base, open/link the PR and observe current-head required CI.
3. Merge through the permitted path. Never bypass or weaken organization rules.
4. On each authorized host, validate its source and stable infrastructure separately.
   Ordinary skill/helper changes need no install. Infrastructure changes require an
   explicit `self-install` whose candidate self-test passes before activation.
5. Observe native discovery/loading and exact body/helper/worker pins in fresh
   restricted sessions. Local tests, CI, merge, installation and live acceptance are
   separate claims. Record unavailable hosts as incomplete.

Use `Refs #198` while its all-host rollout criteria remain incomplete. The MBP
milestone does not close the issue or waive Mint/WSL timer/startup observations.
Keep frozen dotfiles compatibility inputs and the tap until the rollout permits
their retirement. Remove only the MBP keg, after actual legacy-resume proof.

## GitHub Pages setup

The docs build remains useful independently of Pages. After the repository rename,
observe the Pages URL/routing and record an explicit verified or follow-up
disposition. Preserve the last working deployment if the dot-prefixed repository
needs a hosting change. Environment protection approval is not implied by a build.

## Supplemental review live acceptance

Offline tests do not prove provider/model adherence, delegate idempotency,
cancellation or worktree isolation. Retain current live observations before claiming
support; the historical [compatibility ledger](compatibility.md) stays separate.

## Recovery

Use the journaled `agents recover` interface for interrupted receiving/adoption.
Owner edits stop recovery. `agents rollback PIN` selects an earlier validated
runtime and records a hold; the source and newer pins are retained. Explicitly run
`agents rollback follow-source` before receiving again. A failed successor updater
keeps the previous installation available. See the [CLI](cli.md#storage-and-recovery).
