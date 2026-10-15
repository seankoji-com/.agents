# Document jobs: factual checks and cold reads

Load this when `elephant`, `check` or `thinking` is about to delegate a factual check
or a cold read. The generic protocol (create, prepare, dispatch, observe, ingest,
accept, retry, fallback, overview checklists) is in `PKG/shared/job-coordination.md`.
This file adds the document-specific contract. The helpers are
`python3 PKG/shared/job_cli.py` and `python3 PKG/shared/job_acceptance_cli.py`; the
validator is `PKG/scripts/validate_document.py`.

## Plan

Create one job per document review. Give `validator_dependency` the elephant-goldfish
pin. Declare every stage up front:

| Operation | Stages (in order) | Final acceptance |
| --- | --- | --- |
| `check` | `factual` | `validate-final` over `factual` |
| `elephant` | `factual`, then `cold-read` | `validate-final` over both |
| `thinking` (only when a cold read of `handoff.md` is authorised) | `handoff` (direct), then `cold-read` | `validate-final` over both |

Each `factual` or `cold-read` stage declares `validator_contract` with absolute `root`,
`slug`, `mode` (`factual` or `cold-read`), absolute `document_path` and its
`document_sha256`. The document must sit under `root/slug`. For `elephant.md`, use the
repository's parent directory as `root` and the repository directory name as `slug`.
The `handoff` stage is `execution_mode: direct` with contract `{root, slug, mode:
handoff}`. Its acceptance input is a descriptor with the same three fields.

Requirements stay distinct, for example `R-FACT` ("every cited claim is confirmed
against the checked revision") and `R-COLD` ("a fresh reader finds no blocking gap").
Never let one stage cover both.

## Slots

- **Factual slot.** Worker `elephant-goldfish/factual-checker`, write scope
  `coordinator-only` (inline result). Its brief carries the document path and hash,
  the checked revision, the claims to verify and read-only authority. Its
  contract sets `independent_of_author: true`; the host-observed identity must be
  verified before acceptance.
  `review_verdict` is null, or `adverse` beside any blocker or major finding; such a
  result is ingested, its findings are retained, and the stage stays unaccepted.
- **Cold-read slot.** Worker `elephant-goldfish/cold-reader` with `role: review`,
  `context_policy: document-only`, `document: {path, sha256}`, `reviewed_documents`
  naming exactly that same `{path, sha256}`, and write scope `coordinator-only`. Its
  review subject is the document, not another task: never add `reviewed_task_ids`.
  `prepare` and acceptance re-hash the document, so edits make the verdict stale. Its
  contract sets `independent_of_author: true`; unknown author or reviewer lineage
  fails closed. Author records are keyed by document SHA-256 and imported only when
  the current hash matches. A missing record means unknown authorship.
  The helper strips the objective, predecessor outputs, requirement statements,
  resources and task contract. Dispatch only the brief path and hash, with an
  instruction to read it and its named document. Never pass notes, findings, repository
  answers or earlier reports. Start each cold read in a fresh child; no follow-ups.

T3 workspace access is not a sandbox. Document-only isolation is an instruction
boundary plus the helper's brief filter. Report it that way.

## Author records and identity

Every new job has `policy.identity: observed`. Acceptance requires host-reported
verified identity for required reviewer executions, their subjects and factual
slots marked `independent_of_author`. Legacy jobs without the marker keep their
target-only rule.

Author identities are taken from a fresh `orchestrator_capabilities` response passed
as `--capabilities FILE`. The inherited provider, model and parent thread must be
present, and the model must occur in that provider's catalog. A checker never adds
itself as an author. A handoff's authors are its renderer plus authors from both
source hashes; an unrecorded source leaves authorship unknown. These are host facts
transcribed by the coordinator, not cryptographic proof of freshness.
After writing `discovery.md` or `spec.md`, run `thinking_state.py author <slug>
<document.md> --capabilities FILE`. Render with `render_handoff.py <slug>
--capabilities FILE`. A repair uses `job_cli.py document-revision` with
`--capabilities FILE`; the new author union is written beside the document and
copied to every affected author-independent slot. `job_cli.py direct-execution`
records the identity on each start or resume of a zero-slot direct factual stage.
The `check` operation imports authors only for the checked hash, never writes the
checker's identity, and proceeds when provenance is missing. Its report says
`author unrecorded` when the current hash has no record.

An owner `lineage-waiver:task:<task-id>` binds the review target, canonical author
list, slot contract and document hash. For a direct zero-slot factual stage, use
`lineage-waiver:stage:<stage-id>` and bind the latest direct-execution identity.
Neither waiver skips a requirement. A changed target, author list, contract or
document needs a new decision. Resuming direct execution under another identity also
needs a new stage waiver.

## Verdicts

The cold reader returns one worker result. Its `conclusion` starts with
`VERDICT: READY` or `VERDICT: NOT READY`, which keeps the operation identity. Map
READY to `review_verdict: approve` with status `ready-for-acceptance`, and NOT READY to
`adverse` with status `failed` and `R-COLD` failed. Each bootstrap gap is a
finding: `blocker` when it stops a newcomer, `minor` otherwise. Any blocker forces NOT
READY. A missing, failed or ambiguous verdict is `unavailable` or a failed result,
never READY.

After you inspect the result, freeze a coordinator observation with `observation` and
accept the stage with `accept-stage`:

- Cold read: `{"kind": "cold-read-observation", "document_path", "document_sha256",
  "verdict": "ready" | "not-ready", "evidence": [...]}`. Each evidence row is
  `{"observer": "coordinator", "kind": "cold-read", "source": <host task ID>,
  "content": {"document_sha256", "verdict"}, "sha256": <SHA-256 of canonical content>}`.
- Factual: `{"kind": "factual-observation", "document_path", "document_sha256",
  "claims": [{"claim_id", "outcome": "confirmed" | "refuted" | "unknown",
  "evidence": [...]}]}` with `kind: factual-claim` rows binding
  `{document_sha256, claim_id, outcome}`.

Open evidence behind consequential findings before recording outcomes. The validator
checks provenance, hashes and coverage, not truth; it rejects `unknown`. Repair refuted
claims and check again before final acceptance.

## Repair rounds

You repair cold-read gaps yourself; workers never edit the document. Record finding dispositions,
then call `document-revision` with the cold-read task and new `{path, sha256}`. It
rebinds stages naming that path and stales them and their successors. Retry the
factual stage first when present, accept it on the new hash, then retry the cold read.
The new reader never sees earlier findings. For a `thinking` handoff, repair discovery
or spec, render and gate again, accept the direct handoff stage, then revise the cold
read document and retry it. Each retry charges its stage budget. When the budget is
spent, `document-revision` refuses; raising it needs an owner decision through the
question picker and a `plan-revision`. An adverse verdict is not grounds to seek a
second opinion.

## Round limits

A cold-read round is one executed cold-read slot. The budget belongs to the topic or
document, not to a session, and resume never resets it.

- **New topics and documents.** Four rounds in total: the initial read plus three
  repairs. This is the default job policy (`max_repair_cycles: 3`).
- **Existing topics with a recorded limit.** Keep the recorded limit and count.
- **Legacy topics with no recorded limit** (a cold-read loop started under the older
  five-round instruction). Record a limit of five and the rounds already performed.
  Create the job with `max_repair_cycles` equal to the remaining rounds minus one,
  and quote the limit source in the job constraints. If no rounds remain, stop. If
  the performed count cannot be established, ask the owner through the picker
  instead of guessing.

For thinking topics, `init` records the four-round default and `resolve` reports the
remaining rounds. A legacy budget is recorded with `thinking_state.py set`; keep its
round count when resuming. For `elephant.md`, resume the existing job. Budget fields
do not affect readiness or grant execution authority.

When the budget is spent, report the document as NOT READY with its unresolved gaps.
Raising a limit is an owner decision through the picker, recorded with `decision`.

## Fallback

If T3 cannot run a suitable child, run the factual stage yourself under the same
contract with a visible fallback marker. A cold read cannot fall back to you: you
have seen the planning context. Report it as unreviewed and keep `R-COLD` blocked.

## Report

Report factual verification and cold readability as two separate results with their
receipts. A plausible document is not proof of working software.
