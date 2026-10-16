# Releasing

Release from reviewed `master` only. Local tests, hosted checks, merge, release,
Homebrew distribution, and Pages acceptance each need their own evidence.

1. Run the deterministic suite, documentation checks, strict site build, and browser
   verification. Inspect installation from the packaged tree and preserve a clean diff.
2. Complete the required adversarial review and resolve findings. Open the PR against
   refreshed `master`, link it to the T3 thread, and wait for current-head required CI.
3. Merge using the repository's permitted method. Never bypass the organization gate.
4. Dispatch the `Release` workflow from `master` with the intended version bump.
   It reruns tests, archives the commit, publishes an SHA-256 checksum and GitHub release,
   and proposes the updated formula in `seankoji-com/homebrew-tap`.
5. Observe the tap PR's own requirements and merge. A published GitHub release does
   not mean Homebrew can install it yet. Verify its URL and checksum against the asset.
6. Run `brew update`, install/upgrade the formula, then `t3-plugins setup --root PATH` and
   `t3-plugins doctor` in an isolated test prefix. Verify the documented prompt path.
7. Observe the `Documentation` workflow's Pages deployment. Open the live site and
   check navigation, search, images, and installation text at desktop/mobile widths.

## Before public promotion

Check the install experience against the release you are announcing, not just the
source branch. A plugin manifest's `1.0.0` is distinct from a catalog release tag and
its Homebrew formula. The docs must describe the package users can obtain.
Run a real installed workflow in T3 and retain the version, provider, T3 build,
operation, result and any intervention. A historical conformance pass is insufficient
for a changed evidence gate. The rebuilt whole-job workflows also need the live
Codex and Claude runs in the frozen
[benchmark protocol v2](https://github.com/seankoji-com/t3-plugins/blob/master/bench/v2/protocol.md);
until those are recorded, describe them as unverified. See the [launch kit](https://github.com/seankoji-com/t3-plugins/tree/master/launch).

## Supplemental review live acceptance

Include the remaining gaps in the PR body. Offline selection and ledger tests do
not prove free OpenCode provider compatibility, `delegate_task` idempotency by
`clientRequestId`, `task_cancel` behaviour, or isolated worktree setup/cleanup.
Verify that a supported `isolation: "worktree"` launch reviews the exact parent
local commit in its own clean checkout, never the parent path, and that setup
failures skip without shared fallback. Retain separate current evidence
for each before claiming support. A cancellation request or an initial status
still showing running is not a confirmed stop; report it as unresolved and keep
the owned handle for notification-driven reconciliation. Do not wait on optional
models to declare the mandatory review complete, waive existing pending-run gates,
or use a historical live run to certify changed eligibility/data-use rules.
Current validation of these changes is offline; no successful live cancellation
or host deduplication is claimed.

## GitHub Pages setup

Set repository **Settings → Pages → Build and deployment → Source** to **GitHub
Actions**. The workflow builds pull requests without deployment and publishes only
`master`. The site URL is `https://seankoji-com.github.io/t3-plugins/`.
Pages environment protection rules may require a maintainer's approval; do not bypass them.

## Recovery

A failed release is not complete. Inspect the exact failed step before rerunning.
If a release exists but the tap update failed, rerun `Release` with `existing_tag` set
to that tag: it skips tests, tagging, and the GitHub release, reads the published
`.sha256` asset, and only re-proposes the formula, so no second version is invented.
If Pages fails, retain the last successful deployment
and fix its build. Users can reactivate an earlier installed snapshot with
`t3-plugins activate PLUGIN VERSION`; run state is independent of the package version,
and running jobs keep the versions they pinned.

The formula's `imps` command is a second executable from the same catalog package and a
direct state CLI; `t3-plugins install` and `t3-plugins setup` update user snapshots.
