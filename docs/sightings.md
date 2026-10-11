---
description: "Historical provider results for imps 0.1.0+ga50f506cd178 on T3 Code 0.0.46-nightly.20261008.2849, generated from the conformance ledger."
---

# Historical sightings

This ledger predates imps 1.0. The current evidence gate has not completed a live
provider matrix. Use these results to understand the tested versions, not to select
a current provider on the assumption of a pass. See [compatibility](compatibility.md).

Live provider results for imps, generated at build time from
`conformance/compatibility.json`. A unit test passing is not a sighting. A plausible
answer from a model is not a sighting. A row here means a real T3 thread, on the named
provider and model, ran the case and the artifacts are in the repository. The caption
under the table names the imps version and T3 build the ledger describes; it says
nothing about any other version.

<!-- sightings-matrix -->

## How to read a row

- **Passes over repeats.** `3/3` means three fresh clones of the fixture branch, three separate messages, three correct outcomes. `1/3` is reported as `1/3`, not rounded up.
- **not run** means the case could not start on that provider during the matrix. The reason is in the ledger, and it counts against the provider's status.
- **Status.** `verified` needs every critical case at 3/3 with no operator intervention and no false completion. `partial` means some cases passed. `unavailable` means the provider was disabled, not installed, or not authenticated in the T3 build under test.

## What the matrix found

The matrix was useful because it failed. Two defects surfaced only under live
providers and were fixed afterwards, with regression tests:

1. Review briefs showed a `changed_files` example, and a Codex reviewer listed the files it had read there. The core rejected the claim and blocked two Antigravity repeats instead of accepting a false result. The original dispatcher was repaired to require an empty list in read-only results. The current gate no longer uses that result parser.
2. A Claude child cited an evidence path relative to its own scratch directory. The original dispatcher added absolute-path requirements and a correction round. The current gate validates submitted evidence paths directly.

Both are recorded in [the full ledger](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/compatibility.md),
with per-repeat transcripts under `conformance/results/`.

## Record a sighting

Follow the [live conformance procedure](https://github.com/seankoji-com/t3-plugins/blob/master/conformance/procedure.md).
Include the plugin version, T3 build, provider instance, exact model ID, operating
system, the case, and a redacted transcript. Failed attempts belong in the ledger too.
