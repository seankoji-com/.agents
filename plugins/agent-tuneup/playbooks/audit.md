# Configuration audit

## Direct audit

1. Resolve the target provider and exact settings paths from the request and the
   active host configuration. Do not infer the target from the model running this task.
2. Run `python3 PKG/scripts/audit.py --provider <name> --settings <path>` for each file.
   The deterministic audit flags known broad permission patterns, duplicate exact
   rules, and risky sandbox settings. It never emits the settings contents or secrets.
   Keep each exit code: `0` clean, `1` findings, `2` unreadable or invalid.
3. For Claude transcript scanning, run `scan_perms.py --json` only when requested.
   Correlated success/failure counts are observational; frequent calls do not imply
   denied permission or justify allowlisting them. Do not publish transcripts.
4. If one file has no open semantic question, report its findings and stop. Otherwise
   continue with a job.

## Audit job

Create the job from `PKG/references/job-plan.md`: an `inspect` stage the coordinator
runs directly, then a `semantics` stage with one `config-researcher` slot per provider
or scope group. Add a `proposal` stage with a `config-verifier` slot only when the
owner asked for proposed changes. Declare the last stage as the final integration
stage. Every stage uses the `audit` criteria; none may record a settings change.

1. `inspect`: publish the helper findings as a coordinator observation and accept it.
   Exit `2` on any file is a named blocker; do not guess its contents.
2. `semantics`: prepare each researcher brief with only the findings, scopes and
   questions it owns, plus redacted excerpts. Dispatch, record the handle, end the
   turn, and ingest the strict result when T3 wakes you. Compare global, project and
   local scope against the cited documentation. Exact duplicate strings may be
   redundant; quote variants, bare commands and globs are not necessarily
   equivalent. Record the source and version for every syntax claim. An uncited claim
   stays `unverified`.
3. `proposal`: present minimal changes with reasons and their effect on access. Never
   broadly allow shells, interpreters, installers, arbitrary MCP tools, or remote
   commands. Do not disable sandboxing or approvals to reduce prompt frequency. The
   verifier checks each candidate's parse result, changed keys and risk counts before
   you show it to the owner.
4. Dispose every finding with evidence, publish the integrated report observation,
   accept the stage, then run final validation over every stage.

Repairs, fallback and follow-ups follow the coordination contract. If no suitable
worker target exists, research directly under the same brief and gate, and show the
fallback marker.

## Edits

An audit never edits settings. When the owner wants proposed changes applied, switch to
`apply` in `PKG/playbooks/align.md`. Inspect symlink destinations, preserve unrelated
keys, back up original bytes, validate the full file, and verify the provider actually
loads the result. Restore a backup only with existing approval.

## Report

Report findings, proposals, parse results and live verification separately. A
parseable file is not evidence that the provider enforces it. Emit the overview
checklist at stage start, acceptance, blockers and the final result. Do not commit,
push, or persist personal learnings unless separately requested.
