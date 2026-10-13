# Tuneup job plan

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
| `proposal` | workers | `config-verifier` for proposed candidates | audit, as above |
| `apply` | workers | `config-verifier` for applied files | `{"operation": "apply", "findings_allowed": true, "live_enforcement_required": <task>}` |

`audit` uses `inspect` and `semantics`, plus `proposal` when changes were requested.
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

1. Confirm the plan file and digest are unchanged with `align.py`'s own checks.
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
- Verifier unavailable: run the read-only checks directly with a visible fallback
  marker and report independence as unverified.
