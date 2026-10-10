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
6. Run `brew update`, install/upgrade the formula, then `t3-plugins install` and
   `t3-plugins doctor` in an isolated test prefix. Verify the documented prompt path.
7. Observe the `Documentation` workflow's Pages deployment. Open the live site and
   check navigation, search, images, and installation text at desktop/mobile widths.

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
`t3-plugins activate PLUGIN VERSION`; run state is independent of the package version.

The formula's `imps` command is a second executable from the same catalog package. Its `imps` executable
is a direct state CLI; only `t3-plugins install` updates user snapshots.
