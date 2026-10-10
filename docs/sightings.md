---
description: "Live provider results for imps on T3 Code, generated from the conformance ledger in the repository."
---

# Sightings

Live provider results for imps, generated at build time from
`conformance/compatibility.json`. A unit test passing is not a sighting. A plausible
answer from a model is not a sighting. A row here means a real T3 thread, on the named
provider and model, ran the case and the artifacts are in the repository. The ledger
was recorded on imps 0.1.0 against one T3 nightly; the current release has not been
re-run, and the table says which version it describes.

<!-- sightings-matrix -->

## How to read a row

- **Passes over repeats.** `3/3` means three fresh clones of the fixture branch, three separate messages, three correct outcomes. `1/3` is reported as `1/3`, not rounded up.
- **not run** means the case could not start on that provider during the matrix. The reason is in the ledger, and it counts against the provider's status.
- **Status.** `verified` needs every critical case at 3/3 with no operator intervention and no false completion. Nothing has reached it yet. `partial` means some cases passed. `unavailable` means the provider was disabled, not installed, or not authenticated in the T3 build under test.

## What the matrix found

The matrix was useful because it failed. Two defects surfaced only under live
providers and were fixed afterwards, with regression tests:

1. Review briefs showed a `changed_files` example, and a Codex reviewer listed the files it had read there. The core rejected the claim and blocked two Antigravity repeats instead of accepting a false result. Read-only briefs now show an empty list and a stray list gets one correction round.
2. A Claude child cited an evidence path relative to its own scratch directory. Briefs now require absolute paths, and a relative path that does not resolve gets one correction round.

Both are recorded in [the full ledger](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/compatibility.md),
with per-repeat transcripts under `conformance/results/`.

## Record a sighting

Follow the [live conformance procedure](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/procedure.md).
Include the plugin version, T3 build, provider instance, exact model ID, operating
system, the case, and a redacted transcript. Failed attempts belong in the ledger too.
