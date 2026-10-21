# Evidence contract

Record shapes and interfaces that `scripts/evidence.py` enforces. Records are
canonical JSON under `ROOT/<study>/focus-group/evidence/`; `record_sha256` hashes the
record without that field. Every record is create-exclusive: a path accepts only
identical bytes. Exit 0 passes, 1 refuses, holds or quarantines (the attempt is
kept under `attempts/`), 2 is invalid input.

| Path under `evidence/` | Contents |
| --- | --- |
| `packs/<manifest-sha>.json` | manifest, verdict, problems, secret-finding locations, provenance |
| `quarantine/<artifact-sha>.json` | quarantined artifact hash, finding locations (no values), blocked consumers |
| `briefs/<rev16>.<cell>.<stage>.<doc16>.json`, `briefs/docs/*.md` | generated brief, its inputs and document hash |
| `first/<accepted-record-sha>.json` | first impression frozen by `record-acceptance` |
| `probes/<probe-id>.json` | isolation probe values and snippets |
| `bindings/<rev16>.<cell>.<nnnn>.json` | append-only context bindings; the latest is in force |
| `journeys/<accepted-record-sha>.json` | journey evidence and material bound by `record-acceptance` |
| `traces/*.json`, `attempts/*.json` | trace inspections and binding contradictions; refused or quarantined attempts |

## Capture manifest

`PKG/templates/capture-manifest.example.json` lists every field. `kind` is
`capture` or `supplied`. Context classes are `fresh-anonymous`,
`preauthenticated-test`, `unknown` and the always-refused `personal-profile`,
`default-profile` and `saved-profile`. A fresh context needs `freshness.verified`
with a method, no pre-existing state, `user_state: new` and the host's `reference`
for the context it was captured in (`context_reference_missing` fails a capture and
holds a supplied pack; the helper never invents it). The plan's `journey_context`
reference policy is separate. A test context needs
the owner answer
`Approve isolated test context <reference> for focus-group capture`, checked like
a plan approval. Known pre-existing state lists cookie names and storage keys,
never values. A capture records requested and final URLs and `http_status` (an
integer or `unavailable-from-mechanism`); a supplied pack records `source`,
`supplied_by`, `obtained_at` and `offline`. Files have a role (`initial-viewport`,
`view` with its profile view label, `text`), an absolute path, SHA-256, byte count
and media type. Images are PNG in v1, and the initial viewport is the profile
viewport times an integer scale. Page text and PNG text chunks are scanned whole.
v1 reads only standard PNG chunks: it decodes `tEXt`, `zTXt`, `iTXt` (compressed or
not) and `iCCP` for the scan, and refuses any other chunk (private, `eXIf`,
`sPLT`), bytes after `IEND` or an oversize compressed stream as unsupported
(`image_unsupported`, `evidence_unsupported`), naming offset and chunk type only.
A cleaned copy is a new file with its own hash and authority.

Verdicts: `failed` beats `quarantined`, which beats `held`, which beats `cleared`. A
supplied pack with unknown provenance is `held`, never completed by the helper. A
recapture is a new manifest whose `attempt.number` follows its recorded
predecessor. A file name or path cannot change bytes across attempts. A sanitised
derivative names a quarantined parent and keeps its context, request, capture time,
profile and readiness. Approval, dispatch and brief building need a `cleared` pack
whose files, provenance and profile equal the plan's `stimulus` and
`capture_profile`.

## Briefs

Headings are exactly `Persona`, `Material`, (journey: `Your earlier response`),
`Tasks`, `Expected output` and `Boundaries`, and the Boundaries text is fixed. The
contamination lint refuses another persona or cell, another cell's accepted text,
the plan decision, hidden or preferred findings, source code, backlog references
and suspected secrets. A journey brief needs the cell's effective first impression
(native, or carried by the written mapping), frozen and rehashed, and the cell's
latest `verified` binding. Credential goals become gaps.

## Payloads

First impression: `schema` `focus-group/first-impression`, `cell_id`,
`study_revision`, `brief_sha256`, `image_use {saw_images, basis}`,
`initial_viewport` and `walkthrough[]` (each `{file, reaction, observed, inferred}`),
`claims[] {id, kind visual|textual, statement, files}` and `simulated: true`. A
visual claim needs basis `image-and-text` and host-verified delivery.

Journey: `schema` `focus-group/journey`, `driver: participant-child`,
`context {reference, binding_sha256}`, `target {url, environment}`,
`environment_drift {state none-observed|observed|unavailable, detail}`,
`started_at` and `ended_at` (after the capture), `goals[]` and `gaps[]`. Each goal
has `{journey_id, outcome, steps[], reactions[], observed_events[], inferences[],
evidence[]}`. Each step has `{at, kind, permitted_action, description, url, field}`
with a nonempty description. Step times lie within `started_at..ended_at` and never
decrease along a goal's route; equal times are allowed (`step_outside_journey`,
`steps_out_of_order`). A goal record is an attempt: it needs at least one step, and
an unattempted goal is a gap (`goal_unattempted`). An `achieved` or `partial` goal
also needs an observed event or an evidence file (`goal_unsupported`); reactions and
inferences may be empty. Evidence files sit in the task's artifact scope and are
never pack files. Every planned journey has one goal or one gap. A journey whose
every goal is a gap is coverage state `gap`, never `hands-on-evidence`.

## Traces

`inspect-trace` takes `revision`, `cell_id`, `stage`, `task_id`, `request_id` (the
admitted request), `host_task_id`, `brief {path, sha256}` (the Markdown generated for
this task), `first_host_task_id`, `trace` (`{source, events[]}` or `null`) and
optional `result {path, sha256}`. An unadmitted request or a brief built for another
task, cell or stage is refused (`trace_unbound`).

For a generic job, the helper also resolves the exact immutable outer JSON brief
from the task and request, verifies its file hash, effective correlation, document
and approved `context_files`, and checks the recorded host handle. It records both
`document {path, sha256}` and `prepared_brief {path, sha256}`. The payload's
`brief_sha256` names the Markdown; the worker result copies
`effective_brief_sha256` from the outer JSON and sets `binding` to its `snapshot`.
Neither hash substitutes for the other, or for the outer file's SHA-256.

An execution is its admitted `request_id`. Across every cell, stage and revision,
one host task runs one request, and one request runs in one host task for one task
with one result. A contradiction (`host_task_reused`, `request_rebound`,
`result_rebound`) is refused as `trace_binding_conflict` and retained as
contaminated trace records of every request it names, so an already accepted
record of either execution becomes unusable. The one exception is a journey in its
own cell's first-impression host task: `not_fresh_child` contaminates the journey
only, because that first impression was frozen before the journey brief existed.

Each event's explicit `path`, `file_path` or `paths[]` is checked whatever the tool.
A read or write may touch only these two exact briefs, the plan's pack files and the task's own
`artifacts/tasks/<task-id>/` subtree, after resolving symlinks and `..`. Another
task's artifacts are `read_other_task`, including a journey reading its first
impression's directory (it gets that response through its brief), and anything else
is `read_outside_brief`. A `cmd` or `command` is opaque: it is never parsed or run,
an absolute path it names inside the study's job root is checked the same way, and
the event is an `opaque_event` limit. An unrecognised tool (`unsupported_event`) and
a file tool without a path (`unscoped_file_access`) are limits too. A trace with a
limit is `unverified`, never clean; this is not a shell parser or a sandbox.

Compliance is `unverified` without a trace or with any limit, `clean-in-trace` with
only recorded clean traces, and `contaminated` once any inspection of that request
found contamination; a later clean trace never clears it. Identical result bytes
from a distinct request never join another execution. `inspect-trace` reports newly
found contamination as `contaminated_attempt`. `record-acceptance` refuses a
contaminated execution (`attempt_contaminated`) or a result other than the one its
trace bound (`trace_result_mismatch`), and keeps it as an attempt. A trace found
after acceptance leaves the accepted record untouched but makes it unusable. A
clean trace records events; it is not sandbox enforcement.

## Usable records and the current selection

`record_problems` is the one resolver that freezing, journey verification, carry,
coverage and disclosure share. An accepted record is unusable when its result,
ingestion record, payload scan or bound material fails now, when its execution is
contaminated, when its own request's host-observed identity is neither verified nor
accepted by the owner for the discrepancy it shows now (`identity_unverified`), or,
for a journey, when the exact first-impression record it names is missing, ambiguous,
different from its reference or itself unusable (`predecessor_missing`,
`predecessor_unusable`). Briefs, journey slots, admission and ingestion resolve a
journey's first impression through the same resolver, a pilot included. Nothing is
reselected or rewritten.

The current selection is every record accepted in the current revision (a native
record occupies its slot whatever its state), every entry of the revision's written,
revalidated carry mapping, and the exact first impression each selected journey
names. `coverage` and `disclosure` use only this selection, so a stale or replaced
record from an earlier revision stays as excluded history and never blocks or joins
current consumers. A selected unusable record, an invalid written mapping
(`carry_invalid`) or a quarantined hash among the selected results, payloads and
material still blocks. Coverage reports `first_via`, `journey_via`, the selection and
unusable states (`trace-contaminated`, `identity-unverified`, `predecessor-unusable`,
`unusable`, `evidence-record-missing`) as gaps, never hands-on evidence, and
`verified_identity` counts only usable records. `disclosure` lists each selected
record's `identities`; an owner-accepted discrepancy shows its readings, evidence
hash and decision hash, with `verified: false`. There is no
whole-history export; a later consumer of excluded history needs its own check.

## Ingestion

The participant acceptance boundary is the only acceptance boundary for
participant results; nothing depends on an earlier `check-payload` or a success
flag. With a job, only `lifecycle.py ingest` reaches it; `study.py
record-acceptance` reaches it only for a study without a job. Under
the study lock it:

1. reopens the result inside `artifacts/tasks/<task-id>/` (regular file, no
   symlinks, exact SHA-256) and refuses a quarantined hash;
2. parses those bytes as one strict payload; a worker-result envelope or any other
   shape is refused, and no member reference is followed;
3. reopens every journey evidence file the same way (at most 8 MiB).
   Paths may be absolute or relative to the study's job directory; both must stay
   inside `artifacts/tasks/<task-id>/`, without `..` or symlinks. It scans text
   and event logs whole as UTF-8, and scans PNG screenshots' text chunks. It clears
   screenshot pixels only from `material_inspection {inspector: coordinator,
   inspected_at, files {sha256: {viewed, secrets_visible, personal_data_visible}}}`.
   An oversize, undecodable, non-PNG, unsupported-chunk or uninspected file is
   refused, never cleared.
   Suspected secrets quarantine the payload by hash, location and class;
4. checks the record (identity, context, predecessors, one result per slot) and the
   stage contract, including the brief built for this task;
5. writes `first/` (with `image_delivery`) or `journeys/` (with the bound
   `material`) keyed by the accepted record, then the accepted record.

`check-payload` runs steps 1 to 4 and records no receipt. `freeze-first` and
`accept-journey` take `{record_sha256, payload}` and refuse
(`payload_not_accepted`) any payload other than the record's exact result. They
rehash and rescan it and its material, and resolve its execution and predecessor
(`material_unusable`). `disclosure` repeats that for every record of the current
selection, rehashes the pack, and blocks every consumer on any change, suspected
secret, contaminated execution, unusable predecessor or quarantined hash. Pattern scans
are shapes, not a guarantee; pixels depend on the coordinator's inspection.

## Isolation

`select-mechanism` reads `{schema_version, observed_at, source, tools[],
native_browser}`. `bind-context` takes `revision`, `cell_id`, `child_tools`,
`context {reference, boundary}`, `assignment {kind host-enforced|host-trace|none,
source, receipt_sha256, child_ref}`, `evidence_class fixture|live` and `probe
{probe_id, readings}`. Each reading is `{origin, shared {cookie, local, session},
others_own_seen {cookie, local, session}, cleared}`. A binding is `verified` only
when a mechanism exists, the boundary is `isolated-context`, the reference is
unique to the cell, every probe reading shows only the cell's own value, and the
host assignment is evidenced. `live_isolation_claim` is true only for `live`
evidence that passes all of these.

## Interfaces for later stages

- FG-3 dispatch: build briefs before `admit` and `prepare`; `admit` refuses a
  journey without its own current brief, uncharged (`journey_brief_missing`,
  `participant_brief_stale`). `job-spec --defer-journeys` declares no journey slots
  until briefs exist; `lifecycle.py journey-slots` adds them by recorded job plan
  revision. `lifecycle.py ingest` supplies image-delivery and journey context from
  host receipts, and the coordinator's screenshot inspection, to the acceptance
  boundary. Run `inspect-trace` with the same `task_id` and `request_id` as the
  execution, and its host task ID and result, before ingestion when the host
  exposes a trace. A trace that is not available leaves compliance `unverified` and
  is not a blocker; acceptance returns `trace_compliance`, and `first/` and
  `journeys/` keep `trace_compliance_at_acceptance`. `coverage` adds
  `first_identity`, `journey_identity` and `verified_identity` counts.
- FG-4 synthesis and export (`scripts/report.py`, `PKG/references/report-contract.md`):
  consume only the `first/` and `journeys/` records of
  the current selection (`disclosure` lists `selected_records`) and `coverage`.
  `disclosure --consumer export` refuses while the pack is not cleared or changed,
  any selected result or bound material changed or no longer clears, a selected
  execution or a selected journey's first impression is contaminated, the written
  carry mapping no longer validates, or a quarantined hash is among them. Report non-fresh state beside first impressions, fixture evidence as
  fixture, and each record's trace compliance (`first_trace_compliance` and journey
  `trace_compliance` in `coverage`); `unverified` is never reported as clean.
