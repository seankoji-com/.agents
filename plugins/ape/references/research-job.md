# Research job shape

Field authority is `PKG/shared/agents/jobs-contract.md`; this page fixes ape's choices.
Run helpers from the pinned package: `python3 PKG/shared/job_cli.py COMMAND --state-root
ROOT --job ID --input FILE` and `python3 PKG/shared/job_acceptance_cli.py ACTION ...`.

## Source snapshots

The acceptance adapter compares a report's sources with the stage contract, and a
contract change needs an owner decision. So pin sources before the job exists, one
snapshot per clone, in the research workspace:

```sh
python3 PKG/scripts/snapshot_source.py --clone "$CLONE" --repo-url https://github.com/OWNER/REPO \
  --id src-1 --scope "$SCOPE" --output "$WORKSPACE/sources/$NAME.txt"
```

It reads the clean clone at its resolved commit, heads each tracked UTF-8 text file
with `==> path <==`, lists skipped files and prints the `pin` for
`validator_contract.sources`. It refuses a dirty clone, an existing output, a path inside
the clone or a job's `artifacts/`, and over 16 MiB (narrow `$SCOPE`).

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
  `{id: coverage, kind: finding-source-coverage, minimum_findings: 1}`.
- Research task: `worker_id: ape/source-researcher`, `logical_slot_id: primary`,
  `role: worker`, `write_scope: {mode: worker-evidence, path: artifacts/tasks/<task-id>}`,
  `max_followups: 1` for study (0 for forage), and the routing `target` you resolved.
- Synthesis stage (forage only): `depends_on` every research stage; its sources are
  every candidate snapshot (at most five); one `ape/synthesizer` slot with the same
  write-scope shape and `max_followups: 0`. It reads the accepted reports.
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

Write it outside worker artifact subtrees and freeze it with `observation`. Paths are
absolute; hashes are of current bytes:

```json
{"operation": "study",
 "sources": [{"id": "src-1", "url": "https://github.com/OWNER/REPO/tree/REV",
   "revision": "REV", "path": "/workspace/sources/NAME.txt", "sha256": "HEX"}],
 "requirements": [{"id": "R-SRC-1", "source_ids": ["src-1"]}],
 "fingerprint": {"path": "/workspace/fingerprint.md", "sha256": "HEX"},
 "report": {"path": "/job/artifacts/tasks/TASK/report.md", "sha256": "HEX"},
 "findings": [{"id": "F1", "section": "Adopt", "source_id": "src-1",
   "quote": "exact source text, also in that section"}],
 "inspections": [
   {"category": "report", "path": "<report>", "sha256": "HEX", "inspected": "sections"},
   {"category": "adopt", "path": "<source>", "sha256": "HEX", "finding_ids": ["F1"],
    "inspected": "lines L10-L24"}],
 "criteria": [{"id": "provenance", "kind": "source-provenance"},
              {"id": "coverage", "kind": "finding-source-coverage", "minimum_findings": 1}]}
```

- `operation`: `study` or `forage-research` (one source), `forage-synthesis` (one to
  five). Sources, criteria and requirement IDs equal the stage contract.
- `REV` is the resolved commit. The report's `## Provenance` names each source's
  revision and snapshot SHA-256 (synthesis: each accepted report's too) and no other
  hash. Blob citations use a pinned revision and `#L` lines, and cite no other repository.
- Research reports have Provenance, Overlap, Adopt, Adapt, Reject and Command case
  sections (900 words at most) and cite every source; synthesis has Provenance, Overlap,
  Conflicts, Recommended experiment and Rejected. A quote appears in its source and its
  report section. Every requirement and source has a finding.
- Synthesis adds `consumed_reports: [{id, source_id, path, sha256}]`: the dependency
  `outputs`, one per candidate. Each finding names its `report_id` and quotes text that
  report cited.
- Receipts: one `report` receipt, plus one naming each Adopt and Adapt finding
  (synthesis: Conflicts, Recommended experiment) at its cited source or accepted report.

Exit 0 means these hold for those bytes, not that the conclusions are right.

## Acceptance input

`accept-stage` takes `{caller, stage_id, validator_argv, input_file, revision}` where
`validator_argv` is `[PKG/scripts/validate_report.py, --input, OBSERVATION]` and
`input_file` is the observation path. `validate-final` takes the same argv and input per
stage in `validator_argv_by_stage` and `input_file_by_stage`.
