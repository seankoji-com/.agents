# Implementation delivery

Before editing UI work likely to end in a PR, use
[raise-pr](../../raise-pr/SKILL.md) to capture practical mobile and desktop
baselines. Verify the agreed endpoint after the repairs and checks.

- For PR creation or updates, use [raise-pr](../../raise-pr/SKILL.md) for
  evidence, templates, screenshots, attribution and independent review.
  Complete independent review before a new PR. If proof needs a PR before
  review, state the dependency and obtain an explicit waiver from the user.
- Bundle local repairs before pushing when practical. An authorised branch
  push or existing PR update can happen earlier for hosted checks or previews.
  Refresh checks and reviews for the current head before merging.
- For a deployment, verify the revision and behaviour on each target and
  report incomplete gates. After verified production, apply
  [issue status](../../ship/references/issue-status.md) done.
