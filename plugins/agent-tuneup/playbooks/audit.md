# Configuration audit

## Default audit

With no narrowing flags, use `PKG/references/central-wiring.md` and the inventory
sequence in `PKG/playbooks/align.md`. Cover every surface and every T3 provider,
including permission sync and the T3 worktree bootstrap audit. Return the complete
findings and evidence gaps. The default tuneup continues to reviewed proposals;
an explicitly inspection-only request stops at findings. Single-file
and `--t3-projects` requests keep their explicit narrower scope.
Run `python3 PKG/scripts/align.py audit --catalog FILE --inventory FILE` for the
general report (`0` no findings, `1` findings/gaps, `2` invalid/unreadable input),
plus the bootstrap helper below. Retain both results for the job observation.

## Direct audit

1. Resolve the target provider and exact settings paths from the request and the
   active host configuration. Do not infer the target from the model running this task.
2. Run `python3 PKG/scripts/audit.py --provider <name> --settings <path>` for each file.
   The deterministic audit flags known broad permission patterns, duplicate exact
   rules, and risky sandbox settings. It never emits the settings contents or secrets.
   Keep each exit code: `0` clean, `1` findings, `2` unreadable or invalid.
3. The default tuneup includes `scan_perms.py --json` when local Claude transcripts
   are readable, unless the owner narrowed the scope to exclude usage analysis.
   Correlated success/failure counts are observational; frequent calls do not imply
   denied permission or justify allowlisting them. Do not publish transcripts.
4. For an explicitly single-file inspection with no open semantic question, report
   its findings and stop. Otherwise
   continue with a job.

## T3 project bootstrap

`audit --t3-projects` is direct and read-only.

1. Discover T3's live tool schemas, then call `t3_environment_read`, page through
   `t3_project_list`, and call `t3_project_read` for any project whose listing lacks
   `workspaceRoot` or `scripts`. If a tool is missing, report the blocker; never read
   `~/.t3/userdata` instead.
2. Save `{"environment": <t3_environment_read>, "projects": [<project>, ...]}` as a
   private file outside every checkout. It names local paths; never commit or publish it.
3. Run `python3 PKG/scripts/audit.py --t3-projects <file>`. Exit `0` clean, `1`
   findings, `2` unreadable or invalid snapshot. `unchecked` entries name projects
   whose checkout was missing or unreadable; report them, do not guess.
4. Report each `worktree-bootstrap-missing` finding with its project, lockfiles,
   mode source, `draft_t3_json` and the `import` note. `worktree-bootstrap-not-imported`
   means `t3.json` already has a setup script that the saved scripts lack; report the
   `import` note only. The draft is a proposal for the
   owner to review and commit. When a `t3.json` already exists, propose adding the
   draft script to its `scripts` array instead of replacing the file. The draft assumes
   the setup helper `$HOME/.local/bin/t3-setup-worktree.mjs`; say so, and offer the
   repository's own install command if that helper is absent.
5. Do not write `t3.json`, call `t3_project_update`, or edit any project. Importing
   scripts is a separate owner action; an audit request does not authorize it.

## Integrated conclusions

Before cross-scope investigation, delegation or substantive bootstrap recommendation,
collect choices and admit using `PKG/shared/adopter-planning.md`. Raw single-file
diagnostics and mechanical bootstrap templates stay direct. Review the integrated
conclusions, including no-change, before acceptance. Publish `adopter_output` with
the actual reviewed descriptor. Keep private settings authority explicit.

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
