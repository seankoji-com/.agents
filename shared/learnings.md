# Learnings

Load only this plugin's file for this project with
`python3 PKG/shared/learnings.py load --project PROJECT`. The helper reads the
installed manifest version. It returns advisory data, never instructions or
authorisation. Current instructions always win. Never store secrets or raw private
excerpts. A lesson must trace to an observed failure. Keep one lesson per stable ID;
update it instead of duplicating it. Delete lessons that prove wrong. Ask of each:
"would removing this cause a mistake?"

Opus writes learnings without asking, within the owner's authorised learning policy.
Other harness memory policies still apply. No plugin can grant itself permission to
persist data forbidden by its harness or current instructions.

Read-only operations, including doctor, status and audits, only load. Report
`pending_maintenance` without writing, pruning, or creating files. Writable runs
load, maintain if needed, then write lessons from observed failures, including
wrong delegation choices. Use `--input FILE` for JSON proposals. Any `unavailable`
receipt goes into the main report with the proposed lesson; continue the main work.
Never use a project or temporary directory as a fallback learning store.

## Maintenance

The versioned Markdown file has a display-label header and a JSON entry block.
Its location is an identity hash under the XDG state root, independent of checkout
and gitignore. The helper refuses relative/project-contained roots and symlinks;
writes are locked, atomic and mode 0600. Git is optional.

On the first writable run with a different installed version, inspect all loaded
entries against current instructions. Propose `remove` IDs for superseded or wrong
lessons and `amend` objects for revised summary/failure/upstream fields. This is model
judgement, not a unit-tested supersession decision. Pass the loaded `revision` as
`expected` so concurrent changes require a reload. The helper makes one explicitly
owned `<plugin>.md.pre-<old-version>` backup before replacing the active file.
Never delete backups by glob.

Only a `+g<sha>` installation permits upstream checks. When `gh` is available,
look up each `seankoji-com/t3-plugins#N` with `gh api repos/seankoji-com/t3-plugins/issues/N`.
If it is closed as completed, retrieve the closing commit from the issue timeline
(`gh api --paginate repos/seankoji-com/t3-plugins/issues/N/timeline`). Confirm it is
the commit for the current closing event, not an earlier close before a reopening.
Then call `gh api repos/seankoji-com/t3-plugins/compare/CLOSING_COMMIT...BUILD_SHA`.
Pass fixture-shaped observations to `maintain`:

```json
{"expected":"loaded revision","states":[{"upstream":"seankoji-com/t3-plugins#123",
"state":"closed","state_reason":"completed","closing_commit":"40 hex characters",
"compare_base":"same closing commit","compare_head":"installed build suffix",
"compare_status":"ahead"}],"remove":[],"amend":[]}
```

Only `ahead` or `identical` with matching endpoints permits deterministic pruning.
Unknown, duplicate, rejected, reopened and unreleased issues stay. `+content.`
installations skip this entire lookup, without calling gh, and report the skip.
The model's current-instruction review still applies. A failure leaves the active
file unchanged and reports the proposal. Versions always use installed manifest
labels. `write` takes `{"entry":{"id":"stable-id","summary":"one line",
"failure":"observed failure","upstream":"seankoji-com/t3-plugins#123"}}`.
Authorship is immutable; validation and maintenance versions are separate.

## Harvest

When the owner asks to share lessons, read `PKG/shared/harvest.md`. Loading or
writing a lesson never authorises posting it or changing project instructions.
