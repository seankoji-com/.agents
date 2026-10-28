# Tuneup job plan

At configuration verification, the coordinator may use
`PKG/shared/supplemental-reviews.md` within existing sharing authority. Skip private
settings unless explicitly authorised for that provider. Keep extras outside required
slots; verify concrete findings before the normal repair path. Optional failure never
supplies acceptance or charges a required retry.

Read this only when creating or resuming a tuneup job. The generic commands, lifecycle
and repair rules are in `PKG/shared/job-coordination.md` and
`PKG/shared/agents/jobs-contract.md`; this file adds the tuneup shapes.

## Stages

Declare every stage the request authorizes in the initial plan. Each stage names the
`agent-tuneup` dependency as its validator and a `validator_contract` whose `criteria`
object the published observation must repeat exactly.

| Stage | Mode | Slots | Criteria |
|---|---|---|---|
| `inspect` | direct | none | `{"operation": "audit", "findings_allowed": true, "live_enforcement_required": false}` |
| `semantics` | workers | `config-researcher`, one per provider or scope group | audit, as above |
| `report` | direct | none | audit, with integrated independent report-quality review |
| `proposal` | workers | `config-verifier` for proposed candidates | audit, as above |
| `apply` | workers | `config-verifier` for applied files | `{"operation": "apply", "findings_allowed": true, "live_enforcement_required": <task>}` |

The default `tuneup` uses readiness, local usage scanning, `inspect`, `semantics` and
`proposal` in one job. Retain one `tuneup` model admission throughout. Before the
final job gate, present the reviewed proposal. Concrete owner approval also covers
the plan revision that adds the `apply` stage and its settings-apply action; record
that decision and revise the job through the supported helpers. Do not create a
second model chooser. A declined proposal finalizes the existing report stages
with no settings writes. There is no synthetic conditional-stage status. Internal
validator modes remain unchanged.

For narrowly scoped internal stages, `audit` uses `inspect`, `semantics` and a final
direct `report`, plus `proposal` when changes were requested.
`align` uses `inspect` for the inventory and comparison receipts, `semantics` for
precedence and syntax questions, and `proposal`. `apply` gets its own job, or a declared
`apply` stage when the owner asked for it in the original request. Adding `apply` to an
existing job later is a plan revision that needs its owner decision. Set
`live_enforcement_required` to true only when the task requires it. The last declared
stage is the final integration stage.

Worker task slots use `dependency_key` for the tuneup dependency, a recorded `target`
with provider instance, model and lineage, and either a coordinator-only scope or an
evidence directory under `artifacts/tasks/<task-id>/`. No slot gets settings-write
authority. The job `authorization.actions` lists `read`, and `settings-apply` only when
the owner approved a concrete plan.

### Explicit audited-target reports

New report recipes put this coordinator-authored value in
`validator_contract.target_report`, repeated unchanged in both observations:

```json
{
  "schema_version": 1,
  "finding_scope": "audited-target",
  "reports": [{"task_id": "research-1", "path": "artifacts/tasks/research-1/target-findings.json"}],
  "quality_review": "integrated-adopter-planning"
}
```

Both stages use audit criteria with `findings_allowed` exactly `true` and no changes.
The worker stage adds `validator_contract.report_stage: "research"`; the final
direct stage adds `report_stage: "integrated"` and depends on every research and
proposal stage. Admission identifies proposals by the `proposal` stage ID or
`config-verifier` slots, including renamed verifier stages.
Each observation repeats `report_stage`. Reports follow the declared researcher
slot order. Only non-review `config-researcher` slots with their own worker-evidence
subtree may produce them. The final contract lists every report in research-stage
order. This final stage is required by admission for an explicit report contract.

For each opt-in research stage, the coordinator must also set
`stage.resources.target_report` to the exact `validator_contract.target_report`,
and `stage.resources.target_report_instructions` to the literal text below.
Copy it before creating or revising the job. Admission compares both resources
without changing job state. Prepare carries them through the existing immutable
brief resources in full and compact transport. These per-invocation instructions
specialize the unchanged canonical researcher only for this declared contract.
The same text is `RESEARCH_INSTRUCTIONS` in `PKG/scripts/target_report.py`.

```text
The coordinator assigned the explicit audited-target contract in resources.target_report.
Do not choose this scope yourself. Write original target findings to your assigned
target-findings.json under artifacts/tasks/<task-id>/, using the exact path in that
contract. The artifact is {"schema_version":1,"findings":[...]} in discovery order.
Each finding needs a stable id, severity (blocker, major, minor, note), code,
redacted location, concrete scenario and source_evidence (URL and version, or the
command and an excerpt). Preserve whole objects, severity and order. Include the
artifact's exact path, SHA-256 and byte count in worker-result artifacts.

Carry every assigned deterministic inspect finding and gap from consumed_outputs
or the brief's explicit inputs into that artifact. Preserve assigned IDs,
severities and whole objects in their assigned order. If an inspect row lacks the
required fields, have the coordinator assign them before dispatch. Add research
findings after those rows. Keep coverage_gap and unsupported intact; Muse native
approval-policy-store coverage remains unsupported. Never omit or demote a gap
because its underlying semantics could not be verified.

Worker-result findings describe defects in your delivered report, including
missing evidence. Any major or blocker there requires review_verdict: adverse
and fails acceptance. Otherwise review_verdict is null. List gaps, uncertainties
and exact commands. The later integrated quality review is not a prerequisite
for research completion.

Never return secrets, tokens, headers, private URLs, hostnames, home paths or
settings values. Refer to settings by scope and JSON pointer. Excerpt output;
do not paste it whole. Never fetch raw remote settings for local redaction or
transfer raw/aggregate transcripts. Do not bypass a guard refusal or
install/execute a remote extractor. If safe extraction is unsupported, report a
coverage gap.
```

Researchers write `{"schema_version":1,"findings":[...]}` to the assigned artifact
and include its exact path, SHA-256 and byte count in worker-result `artifacts`.
Each original finding has a stable `id`, `severity`, `code`, redacted `location`,
concrete `scenario` and `source_evidence`. The coordinator preserves whole objects,
all severities and their order in observation `findings`. It cannot omit, rename,
reclassify or reorder them. Duplicate IDs, changed bytes and unsafe paths refuse.
Assign every deterministic inspect finding/gap to a researcher through accepted
`inspect.outputs` (consumed by its dependent stage) or explicit brief inputs.
Assign missing IDs, severity, scenario and source evidence before dispatch; retain
existing IDs/severities/objects. Researchers copy those rows into their artifacts
before adding research findings. This includes Muse `coverage_gap`/`unsupported`;
exact final aggregation cannot add an omitted inspect row later.

Worker-result `findings` still mean report-quality defects. A major or blocker there
requires `review_verdict: "adverse"` and fails acceptance. Research otherwise uses
null. Workers cannot opt into target scope. The independent quality review checks
classification against original evidence as well as report correctness. Do not
turn a target major into a note to satisfy generic acceptance.

Research has no prerequisite for its subsequent report review. Do not set generic
`review_required` on its slot to represent that later gate; if explicitly requested,
same-stage generic review remains mandatory. The final report requires actual
producing `adopter_output` planning review, even with zero findings. Include original
target artifacts in that review's `evidence_paths`; every required review pass
must list those paths in its actual `inspected_paths`. It reviews report quality, not
whether the target is defect-free. Adverse or incomplete quality review refuses.
For a proposal, also include its exact accepted published observation in the final
review's evidence and every pass's inspected paths. The pinned job contract binds
the dependency and its acceptance; final report input hashes bind the observation's
path, bytes and SHA-256. Unaccepted or altered proposal observations refuse.
Legacy contracts retain generic adverse behavior. Apply and config-verifier gates
remain separate and cannot use this target-report contract.
Each proposal with `config-verifier` slots requires its own producing
`adopter_output` review even when a final report follows it.

## Observation input

Publish the validator input with the job `observation` command, then accept the stage
with `PKG/scripts/validate_audit.py --input <published path>`. In a worker stage, publish
only after every slot's result is ingested: a new observation stales the stage's slots,
and a stale executed slot needs a charged repair. The input repeats the stage criteria:

```json
{
  "criteria": {"operation": "audit", "findings_allowed": true, "live_enforcement_required": false},
  "audit_exit_code": 1,
  "findings": [{"code": "broad_execution_allow", "location": "global:/permissions/allow/0"}],
  "changes": []
}
```

`audit_exit_code` is the highest helper exit across the files the stage covers. Exit
`2` cannot be accepted; report the unreadable layer as a blocker. Findings carry codes
and locations, never settings values.

## Apply sequence

1. Validate the actual proposal planning receipt before concrete approval using
   `PKG/shared/adopter-planning.md`. Retain the before snapshot, private sharing
   authority, source request, domain criteria and stable subject record.
   Confirm the plan file and digest are unchanged with `align.py`'s own checks.
2. Ask the owner through the native question picker, with the recommended option
   first. Show the redacted diff, every changed key, its access effect, the target and
   the backup location. Record a pending approval as an `approval-wait` task
   observation; it blocks acceptance until resolved.
3. Save the owner's exact answer to a private file outside job state and every worker
   scope. Record it with the `decision` command: stable ID, literal quote, that path,
   its SHA-256 and scope `settings-change:<change-id>`. Resolve the approval wait.
4. Copy the target's current bytes to a private before-edit snapshot, then run
   `align.py apply` with the approved digest and a new backup path. A denied write
   stops the job with a named blocker.
5. Parse: rerun `audit.py` on the target. Load: observe the provider loading the layer
   in a fresh session when authorized; otherwise `unverified`. Enforcement: observe a
   minimal read-only probe when the task requires it; otherwise `unverified` or
   `not-required`.
6. Dispatch the `config-verifier` slot with the plan digest, changed keys, hashes and
   observations. Ingest its result and dispose every finding.
7. Publish the apply observation and accept the stage.

```json
{
  "criteria": {"operation": "apply", "findings_allowed": true, "live_enforcement_required": false},
  "audit_exit_code": 0,
  "findings": [],
  "authorization_records": ["<the recorded owner decision, byte for byte>"],
  "changes": [{
    "id": "change-1", "authorization_ref": "<decision id>",
    "before_path": "/private/before.json", "before_sha256": "<hex>",
    "backup_path": "/private/backup.json", "backup_sha256": "<hex>",
    "parse_result": "passed", "load_result": "passed",
    "enforcement_required": false, "enforcement_result": "unverified",
    "observation": {"observer": "coordinator", "kind": "settings-change",
                    "source": "<where you observed it>", "content": {"...": "..."},
                    "sha256": "<SHA-256 of canonical content>"}
  }]
}
```

The observation `content` repeats `authorization_ref`, the backup and before-edit
paths and hashes, and the three results. `authorization_records` must equal the job's
recorded decisions exactly. When live enforcement is required, add a `live_observation`
of kind `live-enforcement` whose content has `"result": "passed"`.

## Failure handling

- Load `failed` or `unverified`: the apply stage cannot be accepted. Report the applied
  file, its backup, and the restoration you propose; restore only with approval.
- A later file fails: report the files already applied and keep every backup.
- Verifier unavailable: preserve the required slot. A work-target change or direct
  fallback needs its own selected work chain or a new choice; review fallback alone
  grants none. Existing parse/load/enforcement requirements remain.
