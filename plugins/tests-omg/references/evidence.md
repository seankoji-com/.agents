# Evidence contract v1

`python3 PKG/scripts/audit.py --state-root ROOT audit REPO --input FILE`
reads one normalized JSON object (8 MiB maximum), never invokes repo commands and
writes only private state outside the repo. Use the template as a minimal example.
Get real `head_sha` and `snapshot_sha256` first with `audit REPO --snapshot`.
Unknown sections may be omitted. Omission means unknown, never success. Input JSON
rejects duplicate keys, nonfinite numbers and symlink leaf files. Inspect and sanitize
input before use. Common token/header/query credentials are redacted defensively;
this is not a personal-data detector or permission to publish.

## Input sections

- `audit_effort: {incremental_seconds}` optionally records the coordinator's actual
  inspection/tool time for this attempt, excluding helper time. Resume adds it to
  retained cumulative effort. Missing coordinator effort is explicitly unavailable;
  helper counters alone never prove the complete audit met its ceiling.
- `schema_version: 1`, `repository`, `identity`: head SHA, tested SHA (which may
  differ for a synthetic merge, explicitly mark `synthetic_merge` and its ref),
  snapshot digest, exact comparison-base SHA, run ID, attempt, environment,
  tool versions and benchmark/config version. `artifacts` repeat head/tested/run/
  attempt/environment/config identity for every native report/shard. Disagreement
  rejects aggregation. Input identity must match the inspected snapshot.
- `references`: reusable `{id, source, observed_at, url?, available?, expires_at?}`
  records. Sources are exact command/log/file or incident locators with attempt
  identity; use content hashes and inspected line ranges where possible. Only safe
  HTTPS diagnostic URLs become links; no active embedded native attachments.
- `runs`: `{id, attempt, outcome, observed_seconds, loop_seconds?, capacity,
  graph_complete, ready_metadata, nodes, other_merge_blockers?}`. `capacity` maps
  runner pools to numeric worker limits. Each node has `{id, needs: [], duration,
  pool, phase}`, where phase names identify setup/install/build/test/retry/report.
  Include serialization/matrix batches and cross-workflow/repo nodes explicitly.
  `duration: null` prevents a complete time claim. Every computed schedule above
  600 seconds stays a budget gap when ready/start metadata is missing, including
  dependency chains and capacity serialization. Queue uncertainty remains explicit;
  `available_seconds` and its percentiles remain unknown. A known individual duration
  above 600 seconds also establishes a gap even with an incomplete graph.
  Record runner class, cold/warm setup, queue
  intervals and capacity-wait evidence as extra metadata. The helper
  schedules ready nodes at the earliest predecessor/lane availability, with stable
  ID tie-breaking, then reports `max(finish)` as an estimate, plus summed resource
  seconds/60. This is a realizable schedule under the stated pools, not a promise
  that arbitrary CI schedulers choose it. Unlimited capacity is never assumed.
  Phase sums are work, not added parallel wallclock. Nearest-rank p50/p95 use
  `ceil(p*n)`, expose rank/n and warn when at most one observation follows the tail.
  A run above 2,000 graph nodes stays unknown at the helper's calculation ceiling.
  Normalize or partition the evidence while retaining every dependency; do not
  drop expensive nodes to fit the ceiling. Unused advertised workers allocate no lanes.
- `expected_checks`: exact unique `check:shard` identities in the declared enabled
  pre-merge assurance set. Empty discovery is a gap. `assurance_set_complete: true`
  means the coordinator actually reconciled that set against configuration; it is
  not branch-rule enforcement. Missing/extra shards and zero discovery cannot yield
  complete validation. Check and shard IDs cannot contain the colon delimiter;
  normalize external labels into distinct IDs and retain their original labels in evidence.
- `checks`: every `{check, shard, attempt, outcome, discovered, report_complete,
  skipped_tests?, quarantined?, cause?, disposition?, repair_evidence?, tests?}`.
  Outcomes include pass/fail/skipped/setup-failed/cancelled/timed-out/report-failed/
  runner-lost/unknown. Tests are `{id, outcome}` per attempt. Preserve all attempts,
  diagnostics and original failures. `disposition: fixed` requires repair evidence;
  a cause label alone never repairs anything. Counts explicitly identify check-
  shard versus per-test units, with quarantine a subset, not an extra test total.
- `coverage`: tool, version, denominator unit, source_inventory, exclusions,
  generated_vendored, uninstrumented, per-file/line/branch identity_policy, counts,
  revision, instrumentation, and `baseline: {base_sha, policy, instrumentation,
  compatible}`. Compatible instrumentation, scope and environments must be verified
  by the coordinator. Missing base/denominator prevents comparison, even if a
  percentage was printed. Shards need shared identities before union, never sums of
  overlapping line counts. Store actual line/branch IDs in supporting evidence.
- `history`: runs_complete, bugs_accessible, 30-day run and 90-day severe/repeated
  incident windows, up to ten other fixes, exact counts/rules, omissions, pagination
  and permission failures. State severity and recurrence rules and any unexamined
  predecessor interval. Default recommendations are sampling rules, not a fabricated
  history collection. Unknown access remains unknown.
- `findings`: coordinator judgments for TEST-01 through TEST-12. Every supplied
  judgment needs state (`meets|gap|unknown|not_applicable`), reason, evidence IDs,
  confidence, consequence, owner and next_action. Exceptions add owner, reason,
  compensating evidence IDs and expiry without erasing the observation. Automatic
  identity/completeness/timing guards take precedence over supplied clean claims.
- `groups`: coherent check groups with id, tags, explicit priority, evidence IDs,
  failure, consequence, boundary, oracle, distinct_protection, maintenance, rationale,
  owner, cost/savings with measured/estimated distinction, protection_retained and
  protection_lost. `assessment_state: supported` needs those claims and an action
  (`keep|simplify|replace|delete`). Otherwise use `needs_evidence`, `action: null`,
  unresolved_claim and next_experiment. `inspected_groups` separately records actual
  inspection; the helper's reproducible sample is a selection, not proof it ran.
  Supported actions require the group to be in `inspected_groups` and its cited
  evidence to remain available. Otherwise the action becomes null with a next
  experiment. Omitting any selected group leaves sample assessment incomplete.
  Null actions are neither retention nor deletion conclusions.
- `comparisons`: `{group, same_corpus, same_environment, cases, existing_seconds,
  candidate_seconds, existing_runner_minutes, candidate_runner_minutes}`.
  Cases have named id, risk category and existing/candidate outcome
  (`detected|missed|unknown|equivalent|build-error|timeout`). Unsupported or lost
  detection cancels a replacement action and names lost cases under TEST-05/10.
  A supported replacement also needs named retained cases and measured existing/
  candidate elapsed seconds and runner-minutes. Missing compute costs leave the
  action unresolved rather than treating added capacity as free.
  Direct deletion uses `basis: obvious-tautology|dead-feature|confirmed-duplication`;
  duplication also needs independent_boundary_analysis. Direct inspection evidence
  is sufficient for obvious tautologies. No deletion quota or future-safety fraction.
- `execution`: admitted only with `--run-checks`. Each receipt needs exact argv,
  cwd, timeout_seconds (1..600), prerequisites, authorization source, exit_code,
  duration_seconds and cleanup. Record runtime/tool versions, fixture/seed, finite
  fault case/resource scope, network restrictions and disposable workspace when
  applicable. `production` or `uncontrolled_network` is refused. JSON grants no
  execution authority; the coordinator must already possess it.
- `selection_context`: authored findings or supported actions require `{record,
  selection_sha256, invocation_id, scope_id}` from the existing shared selection
  gate. The record includes the scoped upfront agreement admitting `tests-omg/audit`,
  either as its operation or an explicitly agreed nested operation. Unchanged
  continuations retain this producing agreement and its budgets. Keep the binding
  independently in the job/brief, not only in this input. Older records remain
  readable through deterministic status/report; use their pinned package for work.
  Deterministic collection/unknown records need no model launch. This admission
  proves local record consistency, not the truth of arbitrary authored claims.
- `strategy`: only when a substantial written strategy actually exists, supply
  `{snapshot_sha256, receipt}` from the shared planning runtime's accepted
  content-bound reference. Use the installed imps planning dependency, with its
  frozen choices, manifest-pinned reviewer and separate job/subject lifecycle.
  The helper validates the actual receipt, producing job, retained objections and
  current source bytes before ingesting dependent results. Never fabricate an
  artifact merely to activate this path. No receipt grants execution authority.

## Organization ingestion

Use `audit --org OWNER --input FILE`. `org` is `{owner, pages, expected_repos?,
expected_source?}`. Pages are `{page: 1, repos: [{name, archived, classification?,
owner?, priority?}], next_page: 2|null, error?}`. Supply every visible page, including archived
and unclassified repos; no silent filtering. An error, discontinuity or exhausted
budget returns partial. Credential-visible-only inventory has denominator unknown.
Owner-supplied expected scope or authoritative inventory supplies expected_repos and
its real source; observed missing repos are a gap. `repositories` maps each repo
name to `{snapshot, evidence}` collected under the same finite coordinator-wide
budget. Lower numeric priority selects high-consequence/expensive triage first after the
complete cheap inventory. Per-repo findings live in scope.results, not an aggregate fleet score.
Missing test-value evidence is explicitly incomplete triage. Organization execution
is refused; authorize each local repository invocation separately.
Inaccessible incident/fix history or omitted selected groups also makes scope
partial and prevents a fleet-wide complete-history claim.

## Records and revalidation

### Pinned advisory review

The installed `tests-omg/reviewer` consumes an immutable shared-job brief. The
coordinator supplies its frozen exact model/options; the worker never selects or
dispatches another model. Declare `role: review`, `independent_of_author: true`,
the actual document authors, and `reviewed_documents` containing the saved absolute
`audit.json` path and SHA-256. Read access to source paths comes only from the brief.

Use validator dependency `tests-omg` and the exact installed
`scripts/validate_audit.py --input <published-observation>` adapter. Its descriptor,
also the stage's exact `validator_contract`, has six fields: `state_root`, `run_id`,
`audit_sha256`, `input_sha256`, `snapshot_sha256`, and `head_sha`. The private state
root is absolute; obtain hashes from that saved run's manifest and snapshot. The
adapter never follows successor IDs or selects a different run. Shared acceptance
requires an independent review of those exact bytes in this stage or an accepted
ancestor, and checks report/source bindings again on revalidation.

The validator emits `audit-report-integrity`, `audit-source-current` and
`audit-scope-complete`. Passing means a current complete local advisory with twelve
findings, not passing tests, known measurements, merge authority or live acceptance.
Honest unknowns and repository gaps remain in the saved report. Missing source,
expired diagnostics, supersession, changed bytes and omitted selected groups block.
Organization reports have no local source binding and remain unavailable to this
adapter. Deterministic doctor/status/report do not launch a reviewer.

A private pending-ID.json checkpoint records scope, counters and cumulative effort
before collection, and its snapshot binding once collected. Ordinary interruption
leaves it available to status/resume; an uncatchable runner loss can leave only this
checkpoint, without HTML. Invalid input is retained as blocked evidence.

Private `runs/ID/` holds input.json, audit.json, report.html and manifest.json.
The manifest hashes all three and binds generator/benchmark, snapshot and creation
identity. index.json tracks repo/revision, config/benchmark, history, predecessor and
supersession. Files use atomic replacement under a nonblocking process lock, mode
0600, directories 0700. Symlink state paths are refused. Records may contain private
source names; do not commit them. Ordinary bulky attachments are external references
with expires_at (30 days); no automatic attachment fetch/copy or deletion runs.
Compact records remain until owner deletion. An expired/unavailable reference
invalidates dependent current claims. Saved HTML is immutable historical evidence;
status separately reports source freshness, expired diagnostics and supersession.
Report verifies deterministic saved rendering without changing dates or conclusions.
Local report identity can meet TEST-11; authenticated delivery and PR summary links
remain separate unverified observations. `analysis.evidence_rejections` records
`source_binding_mismatch` and `artifact_identity_mismatch` separately from unmeasured
advisories. Status/report expose those codes and exit 1 for rejected bindings,
expired or unavailable diagnostics, unavailable/stale source or supersession.
For older records without codes, they inspect saved input bindings without
recomputing findings or changing the record. A complete unmeasured advisory or
ordinary repository gap still exits 0. An organization record's absent local
source locator alone does not reject its per-repository evidence. An unrelated
expired reference does not erase independently supported findings or measurements.

Resume creates a successor while retaining original source/scope/limits/profiles,
authorization, cumulative elapsed effort, counters and owned handles. Source drift
refuses rebinding. Deterministic helpers own no tasks. Coordinator host work must
retain its own counters/handles in the pinned shared job and include tool time in
its declared audit ceiling. Comparisons retain compatible predecessor observations;
recommendation adoption and causal improvement still need coordinator evidence.
An interrupted checkpoint is claimed by one successor, then retired after saving.
Status/report on the original ID follows the saved successor; another resume of
that interrupted ID is refused. Partial files from the original attempt remain.
An occupied state lock is a blocked scope (exit 1), not invalid input (exit 2).
