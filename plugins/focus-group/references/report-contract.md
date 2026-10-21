# Report contract

Record shapes and interfaces that `scripts/report.py` and the pinned
`scripts/validate_study.py` enforce. Records are canonical JSON under
`ROOT/<study>/focus-group/report/`; `record_sha256` hashes the record without that
field. Records are create-exclusive. Exit 0 passes, 1 refuses or holds, 2 is invalid
input. Findings are synthetic product hypotheses, never evidence of human demand,
prevalence, retention or revenue.

| Path under `report/` | Contents | Mutability |
| --- | --- | --- |
| `inputs/<inputs-sha>.json`, `.md` | frozen analysis inputs and the analyst's document-only brief document | immutable |
| `files/<sha256>-<name>` | delivered copies of every cleared pack file and accepted journey file | immutable |
| `synthesis/<rev16>/<nnnn>.json` | analyst syntheses and coordinator edits, each with its authors | append-only, chained |
| `edits/<sha>.json` | the exact edited synthesis a coordinator edit record names | immutable |
| `bundles/<bundle-sha>-<dir16>.json` | where a rendered bundle was written | immutable |

## Analysis inputs

`analysis-inputs --capabilities OBSERVATION [--assessments FILE]` refuses an
unapproved revision, a job on an earlier revision, an analyst the fresh catalog cannot
run, a missing analysis sharing grant, unresolved owned participant work, a blocked
`disclosure --consumer analysis` and zero usable first impressions
(`zero_denominator`). The evidence part is the current selection's records that the
shared usable-record resolver accepts now, each with its exact payload, cell, persona,
stage, revision, request, identity state, observed lineage, trace compliance and
bound journey material (names, hashes, the goal each file is bound to and inlined
text of text files, never paths); every unusable selected
record is a listed gap. It also carries the pack's file list, page text, provenance,
disclosure decision and parent hash, coverage, session outcomes and denominators
(declared cells, usable first impressions, journey records, hands-on journeys).
Older revisions, rejected or quarantined attempts and excluded history are never
included. `evidence_sha256` hashes this part; `feedback` adds every earlier review
round with its dispositions. Lineage is the shared review contract's
`lineage(providerInstanceId, model)` of the observed identity.

The record's `files` lists a content-addressed copy of every cleared pack file and
every file bound to a usable journey (`{path, sha256}`); quarantined bytes are
refused. The command returns `decision_input` and `plan_revision_input` that make the
job's analysis slot document-only on the inputs document with those `context_files`,
and pin `inputs_sha256` and `evidence_sha256` in the analysis stage contract. Shared
preparation rehashes each file and adds exactly those paths to the brief's read
authority. `admit` holds the analyst (`analysis_inputs_unbound`,
`analysis_inputs_stale`, `inputs_changed`) until that slot names this revision's
inputs and files, they are unchanged, and they still equal the accepted evidence.
Delivery makes the bytes readable; it does not show that a provider can view images.

Each `--assessments` entry is `{id, summary, authority {statement, source,
source_sha256}}`; the statement must occur in that absolute source outside the job.
Only these let a backlog item cite effort.

## Synthesis

The analyst writes `artifacts/tasks/<task-id>/synthesis.json`; its brief document
lists the shape. `synthesis --input {task_id, request_id, completion_id}` freezes it
only from the job's parsed, ready execution of the analysis slot's current request,
admitted in this revision, from a settled owned host task whose shared identity is
`verified`, prepared from recorded inputs that still equal the accepted evidence. A
completion the shared parser never recorded is `not_ingested_by_job`; worker
completion is never acceptance. `check-synthesis` runs the same checks and records
nothing.

Checks (codes in parentheses):

- Observations: a known source (`source_unknown`); a pointer matching that stage's
  evidence fields (`pointer_outside_evidence`) that resolves to a string
  (`pointer_unresolved`); the exact quote (`quote_mismatch`); the source's cell
  (`foreign_attribution`), stage and revision; one observation per source pointer
  (`duplicate_identity`); capture as a pack file the source cites at that pointer,
  an image only with a verified image basis, or a file the accepted journey bound to
  the same goal; another goal's file, or any file for a gap or drift record, is
  `unsupported_capture`. A first-impression field cites the capture it is about and a
  journey goal field cites every file bound to its goal (`capture_missing`); a goal
  that bound no file, and a gap or drift, need none and the report says so. Journey
  evidence paths reach the analyst as file names only.
  The stable ID is `O-` plus a hash of record and pointer.
- Findings: unique `F-` IDs, a category, and distinct observations
  (`support_unassociated`). An observed finding needs participant text or a browser
  event, not inference only (`unverified_as_observed`). Frictions are
  product-absence, feature-not-found or environment-failure; a feature the pack text
  shows is never absent (`claim_contradicted_by_pack`) and an unseen one is never
  "present but not found" (`feature_not_in_pack`). An environment failure cites a
  journey gap or drift; a model error cites the exact contradicting pack excerpt.
  A feature idea names `persona-requested` or `analyst-inferred` and keeps its
  supporting frustration; an analyst-inferred idea is an unverified suggestion.
  Claimed support must equal the computed support (`support_mismatch`).
- Backlog: unique `B-` IDs over existing findings; impact, impact reason, evidence
  strength, uncertainty, rank reason, proposed change and its origin, rationale and
  observable verification (`priority_incomplete`). An impact reason that argues from
  frequency is refused (`impact_frequency_only`); evidence strength cannot exceed
  its observations (`evidence_strength_overstated`); effort is unknown unless it
  cites an assessment (`effort_unsupported`). Order is the analyst's ranking; there
  is no formula.
- Text: suspected secret shapes (locations only) and machine paths are refused.

Support counts unique cells, personas and known lineages of the cited observations,
with first-impression and journey denominators. Several quotes, stages or retries
from one cell are one cell.

`edit --input {base_record_sha256, synthesis, reason} --capabilities CAPS` records a
coordinator edit of the current record after the same checks. The coordinator's
inherited host identity joins the author set. Rendering never adds an author.

## Bundle and review

`render --out DIR` writes a new directory outside the job: `report.md`,
`findings.json`, `backlog.json`, `issues/<B-id>.md`, `evidence/<sha16>-<name>` copies
of every referenced, disclosure-cleared capture file, `sources/<source-id>.json`,
`bundle.json` (file hashes, evidence and source disclosure decisions and parent
hashes, authors) and `document-authors.json` for the four reviewed documents. Each
source file is generated from the accepted payload of a cited source: record and
payload hashes, cell, persona, stage, revision, task and request, the disclosure
decision, `transform` (each journey evidence path replaced by its file name) and the
`payload`. An unchanged payload is also copied byte for byte as
`sources/<source-id>.payload.json`. Every observation names its `source_file`, and
report and issue lines link to it. Rendering is deterministic; a directory holding
other bytes is refused. Links must resolve inside the bundle; machine paths,
suspected secrets and quarantined hashes refuse it. From the bundle's own bytes, each
observation must resolve in its source to the exact quote with matching provenance,
a copied payload must hash to the accepted payload hash, and each cited capture must
be present (`source_missing`, `source_mismatch`, `pointer_unresolved`,
`quote_mismatch`, `source_hash_mismatch`, `capture_missing`). The target URL is
not rendered. `verify-bundle` compares every file with a fresh render and reports
extra or missing findings, changed counts, a zero denominator, extra or missing files
and changed bytes.

`review-slot --bundle DIR --capabilities OBSERVATION` refuses a bundle that is not
the current render, an analyst identity that is not still verified, a reviewer the
fresh catalog cannot run, of unknown lineage or sharing any author's lineage, a
missing review grant, an earlier finding without a disposition and, for a new round,
a spent `review_repairs` pool. It returns the shared-route inputs that set the review
slot's `reviewed_documents` and `independent_of_author` (the shared author refresh
imports the hash-bound authors), the round context in stage
`resources.focus_group_review` (bundle, inputs with every delivered file, authors, criteria, every earlier
round's findings with dispositions and responses) and the pins in the stage
contract. A new round then needs a charged `job_cli.py retry` with category
`review`.

## Study validator

`observation --stage S` prints the observation to freeze with `job_cli.py
observation`: the stage contract plus `schema_version`, and for analysis the analyst
record of the current request. `validate_study.py --input OBSERVATION` returns one
outcome per stage requirement and passes only when:

- every stage: the observation equals the declared contract, the revision is
  approved and its material still clears;
- first impression and journey: every cell has one usable effective record from the
  slot's current request or the written carry mapping, with no unresolved owned work;
- analysis: the analyst record of the current request is bound to that ingested
  execution and verified identity, its inputs equal the evidence now, the analyst
  brief carried them with their context files, and those files are unchanged;
- review: the bundle is the current render of the latest synthesis, whose base is that
  analyst record; the review slot names its exact documents; the current review
  execution is ingested, ready, `approve`, with every criterion passed, from a
  settled, verified reviewer whose observed lineage is canonical and differs from
  every author; the round context equals the recomputed one; every earlier finding
  has a disposition; and no owned work is unresolved.

`status` and `export` read the review state from the shared job's current receipts
(`validate` of the review stage and its predecessors). Optional or supplemental
reviews never stand in for this required review.

## Export

`export --bundle DIR --out NEW` copies a verified bundle into a new directory with
`review-status.json`, `review-status.md` and `export.json` (every file hash,
`external_actions: []`). It refuses a changed bundle, a blocked `disclosure --consumer
export`, machine paths, suspected secrets and broken links. `verify-export --bundle
DIR` needs no study state and checks a relocated export, including every source
projection, pointer, quote, copied payload hash and capture file. Export publishes nothing,
calls no imps, creates no thread and starts no fix. Pattern scanning refuses the
tested shapes; it does not guarantee arbitrary secrets are detected.
