# Research job shape

Field authority is `PKG/shared/agents/jobs-contract.md`; this page fixes ape's choices.
Run helpers from the pinned package: `python3 PKG/shared/job_cli.py COMMAND --state-root
ROOT --job ID --input FILE` and `python3 PKG/shared/job_acceptance_cli.py ACTION ...`.

## Source snapshots

The acceptance adapter compares a report's sources with the stage contract, and a
contract change needs an owner decision. So pin sources before the job exists: for each
clone, write one UTF-8 snapshot of the text files in scope at the resolved commit into
the research workspace, never under the job's `artifacts/`:

```sh
git -C "$CLONE" grep -I -z -l -e '' -- "$SCOPE" | (cd "$CLONE" && xargs -0 tail -n +1) > "$WORKSPACE/sources/$NAME.txt"
```

`tail` heads each file with `==> path <==`, so a quote still locates its file. Use `.`
or the study subdirectory as `$SCOPE`, and narrow it when the snapshot exceeds 16 MiB
or fails UTF-8 decoding. Record its SHA-256. The clone stays read-only.

## Plan

- `workflow`: `ape/study` or `ape/forage`. One dependency `{key: ape, plugin: ape}`.
- `authorization.actions`: `["read"]`. Research jobs never carry write, push, merge,
  settings or experiment actions. `constraints` quote the operator's focus and every
  repository instruction verbatim, plus "no writes to the current project or targets".
- Requirements: one per candidate (`R-SRC-<n>`: "pinned comparison of <url> at
  <revision>") plus, for forage, `R-SYNTH`. Every requirement belongs to a stage.
- Research stage: `validator_dependency: ape`, `revision` set to the resolved commit,
  `outputs: ["<job dir>/artifacts/tasks/<task-id>/report.md"]` (dependents receive
  these as `consumed_outputs`), `validator_contract.sources` pinning that candidate's
  snapshot, and criteria
  `{id: provenance, kind: source-provenance}` and
  `{id: coverage, kind: finding-source-coverage, minimum_findings: 1}`. A report with no
  Adopt or Adapt proposal still cites at least one Overlap or Reject finding.
- Research task: `worker_id: ape/source-researcher`, `logical_slot_id: primary`,
  `role: worker`, `write_scope: {mode: worker-evidence, path: artifacts/tasks/<task-id>}`,
  `max_followups: 1` for study (0 for forage), and the routing `target` you resolved.
- Synthesis stage (forage only): `depends_on` every research stage; its sources are
  every candidate snapshot (five at most, so one snapshot per candidate); one
  `ape/synthesizer` slot with the same write-scope shape and `max_followups: 0`. The
  synthesizer reads the accepted reports; each synthesis finding quotes the snapshot
  text the accepted report it rests on cited.
- Policy: keep defaults (`max_repair_cycles` 3, artifact limit 16 MiB) unless the owner
  set others. The plan is complete at creation; adding a candidate needs an owner
  decision and `plan-revision`.

## Worker result

One JSON object per `PKG/shared/agents/worker-result.schema.json` v1. The report lives
at `artifacts/tasks/<task-id>/report.md` and is listed in `artifacts` with that
job-relative path, its SHA-256 and bytes. Findings carry severity, scenario and blob-URL
evidence. `review_verdict` is null unless a finding is blocker or major (then `adverse`);
dispose of every blocker or major finding with `finding-disposition` before acceptance.

## Report descriptor (validator input)

Write it outside every worker artifact subtree, then freeze it with `observation`:

```json
{"sources": [{"id": "src-1", "url": "https://github.com/OWNER/REPO/tree/REV",
  "revision": "REV", "path": "/absolute/workspace/sources/NAME.txt", "sha256": "HEX"}],
 "findings": [{"source_id": "src-1", "quote": "exact text present in the source"}],
 "criteria": [{"id": "provenance", "kind": "source-provenance"},
              {"id": "coverage", "kind": "finding-source-coverage", "minimum_findings": 1}]}
```

`sources` and `criteria` must equal the stage contract exactly. At most five sources.
Each quote is the exact cited text you opened and confirmed; criteria never carry a
status. `validate_report.py` exit 0 means provenance and coverage hold for those bytes,
not that the conclusions are right.

## Acceptance input

`accept-stage` takes `{caller, stage_id, validator_argv, input_file, revision}` where
`validator_argv` is `[PKG/scripts/validate_report.py, --input, OBSERVATION]` and
`input_file` is the observation path. `validate-final` takes the same argv and input per
stage in `validator_argv_by_stage` and `input_file_by_stage`.
