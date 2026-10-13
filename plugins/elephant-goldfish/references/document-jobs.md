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
  `review_verdict` is null, or `adverse` beside any blocker or major finding; such a
  result is ingested, its findings are retained, and the stage stays unaccepted.
- **Cold-read slot.** Worker `elephant-goldfish/cold-reader` with `role: review`,
  `context_policy: document-only`, `document: {path, sha256}`, `reviewed_documents`
  naming exactly that same `{path, sha256}`, and write scope `coordinator-only`. Its
  review subject is the document, not another task: never add `reviewed_task_ids`.
  `prepare` and acceptance both re-hash the document, so an edit after the read makes
  the verdict stale. The helper strips the job objective, predecessor outputs,
  requirement statements, resources and task contract from this brief. Do not try to
  pass them another way. The dispatch message contains only the brief path, its
  SHA-256 and the instruction to read that brief and the document it names. Never
  add planning notes, factual findings, repository answers or earlier cold-read
  reports. Start every cold read in a fresh child; never use a follow-up.

T3 workspace access is not a sandbox. Document-only isolation is an instruction
boundary plus the helper's brief filter. Report it that way.

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

Open the evidence behind consequential factual findings before you record an outcome.
The validator checks provenance, hashes and coverage, not truth. It rejects
`unknown`. Repair every `refuted` claim and check again before final acceptance.

## Repair rounds

You repair cold-read gaps yourself. Workers never edit the document. A repaired
document has a new hash, so:

1. Record each finding's disposition (`fixed`, `rejected` with evidence, or
   `deferred`). Deferred blockers keep the stage blocked.
2. Run `document-revision` with `{caller, task_id: <cold-read slot>, document: {path,
   sha256}, reason}`. Within the round budget this is a declared repair and needs no
   owner decision. It rebinds every stage contract and slot that names the path to the
   new hash and makes those stages and their successors stale.
3. `retry` the factual slot, run it, and accept the factual stage on the new hash.
   Then `retry` the cold-read slot and dispatch a fresh reader. Each retry charges its
   stage budget. The previous findings stay in job history; the new reader never
   sees them.

A `thinking` job has no factual slot. Repair through discovery or spec, re-render the
handoff with `render_handoff.py` and pass `thinking_state.py gate`. The old `handoff`
receipt no longer matches the new bytes, so run `accept-stage` on the `handoff` stage
again (a charged direct pass). Then run `document-revision` with the new `handoff.md`
hash and `retry` the cold-read slot.

When the budget is spent, `document-revision` refuses with `attempt_budget_exhausted`
and `owner_decision_required`. Another round then needs the owner, asked through the
question picker with the recommended option first, recorded with `decision`, and a
`plan-revision` that raises the limit. Do not seek another reviewer to overturn an
adverse verdict.

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

For thinking topics the topic is the record. `init` records the four-round default;
`resolve` reports `cold_read` with the remaining rounds. Record a legacy budget with
`thinking_state.py set <slug> cold_read.max_rounds=5 cold_read.rounds_performed=<k>
cold_read.limit_source=legacy-five-round-policy`, and update `rounds_performed` after
each round. `set` refuses a decreasing count, a count above the limit, and a raised
limit unless `limit_source=owner-decision` with a `decision_ref`. For `elephant.md`,
the job is the record; resume that job rather than creating a new one. These fields
record the budget; they never affect readiness and grant no execution authority.

When the budget is spent, report the document as NOT READY with its unresolved gaps.
Raising a limit is an owner decision through the picker, recorded with `decision`.

## Fallback

If T3 cannot run a suitable child, run the factual stage yourself under the same
contract with a visible fallback marker. A cold read cannot fall back to you: you
have seen the planning context. Report it as unreviewed and keep `R-COLD` blocked.

## Report

Report factual verification and cold readability as two separate results with their
receipts. A plausible document is not proof of working software.
